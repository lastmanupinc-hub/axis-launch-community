"""Compliance enforcement.

Every rule in strategy/compliance.md is implemented here. The build calls these; nothing
reaches an inbox or an ad platform without passing them.

Design notes:
  - Guards return a list of Violation records rather than raising, so a build can report
    everything wrong at once instead of one thing per run.
  - Severity is either "fail" (blocks the build) or "warn" (recorded, does not block).
  - Matching is case-insensitive over whitespace-normalised text, so "Vista  Print" and
    "vistaprint" both trip the same rule.
"""
from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass, field

from . import config


@dataclass(frozen=True)
class Violation:
    rule: str
    severity: str          # "fail" | "warn"
    message: str
    where: str = ""
    term: str = ""

    def __str__(self) -> str:
        loc = f" [{self.where}]" if self.where else ""
        return f"{self.severity.upper()}: {self.rule}{loc}: {self.message}"


@dataclass
class GuardReport:
    violations: list[Violation] = field(default_factory=list)

    def add(self, *violations: Violation) -> None:
        self.violations.extend(violations)

    def extend(self, violations: list[Violation]) -> None:
        self.violations.extend(violations)

    @property
    def failures(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "fail"]

    @property
    def warnings(self) -> list[Violation]:
        return [v for v in self.violations if v.severity == "warn"]

    @property
    def ok(self) -> bool:
        return not self.failures

    def summary(self) -> str:
        if not self.violations:
            return "guards: clean"
        return (
            f"guards: {len(self.failures)} failure(s), {len(self.warnings)} warning(s)\n"
            + "\n".join(f"  {v}" for v in self.violations)
        )


# --------------------------------------------------------------------------- text matching

_WS = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace, neutralise common obfuscations."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    # curly quotes and dashes to plain, so "don't" and "don’t" match the same entry
    text = text.replace("’", "'").replace("‘", "'")
    text = text.replace("—", " ").replace("–", " ")
    return _WS.sub(" ", text).strip()


def _contains(haystack: str, needle: str) -> bool:
    """Substring match on normalised text, with word boundaries where the term is one word."""
    h, n = normalise(haystack), normalise(needle)
    if not n:
        return False
    if " " in n or not n.isalnum():
        return n in h
    return re.search(rf"\b{re.escape(n)}\b", h) is not None


def _scan(text: str, terms: list[str], rule: str, severity: str, where: str,
          message: str) -> list[Violation]:
    hits = []
    for term in terms or []:
        if _contains(text, term):
            hits.append(Violation(rule=rule, severity=severity, where=where,
                                  term=term, message=message.format(term=term)))
    return hits


# --------------------------------------------------------------------------- rule 1

def check_competitor_terms(text: str, where: str = "") -> list[Violation]:
    """compliance.md #1 - never name or echo a competitor."""
    bl = config.blocklist()
    out = _scan(text, bl.get("competitor_brands", []), "competitor-brand", "fail", where,
                "names a competitor brand ({term}). Never in generated creative.")
    out += _scan(text, bl.get("competitor_campaigns", []), "competitor-campaign", "fail", where,
                 "echoes another company's campaign or slogan ({term}).")
    return out


def check_unsupportable(text: str, where: str = "") -> list[Violation]:
    """compliance.md #1 / brand voice - no superlative we cannot receipt."""
    bl = config.blocklist()
    out = _scan(text, bl.get("unsupportable_claims", []), "unsupportable-claim", "fail", where,
                "makes a claim we cannot receipt ({term}).")
    out += _scan(text, bl.get("discouraged_tone", []), "off-brand-tone", "warn", where,
                 "off-brand filler ({term}). Rewrite before this ships.")
    return out


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_DISCOUNT_SIGNAL = re.compile(
    r"(\d+\s*%)"                      # 30%
    r"|([$\u00a3\u20ac]\s*\d)"       # $20
    r"|\b(off|save|saving|savings|discount|sale|reduced|deal|half price|bogo)\b",
    re.I,
)


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_SPLIT.split(text or "") if p.strip()]
    return parts or ([text] if text else [])


def _has_discount_signal(text: str) -> bool:
    return bool(_DISCOUNT_SIGNAL.search(text or ""))


# --------------------------------------------------------------------------- rule 2

def check_offer_claim(text: str, offer: dict | None, where: str = "") -> list[Violation]:
    """compliance.md #2 - an absolute discount claim needs an empty exclusion list.

    `offer` is a record from products.yml. Passing None means the asset carries no offer,
    in which case any absolute claim is unsupported by definition.
    """
    bl = config.blocklist()
    absolutes = bl.get("absolute_claims", [])
    # An absolute word is only a *discount claim* when it sits in the same sentence as a
    # discount figure. "Everything else is adjustable" is prose; "30% off everything" is a
    # claim. Without this, the guard fires on ordinary English and gets switched off, which
    # is worse than not having it.
    hits = [t for t in absolutes
            if any(_contains(sentence, t) and _has_discount_signal(sentence)
                   for sentence in _sentences(text))]
    if not hits:
        return []

    exclusions = (offer or {}).get("exclusions")
    if offer is not None and isinstance(exclusions, list) and len(exclusions) == 0:
        # Deliberately, explicitly exclusion-free. Permitted.
        return []

    why = "the asset carries no offer record" if offer is None else \
          f"its offer excludes {', '.join(exclusions or ['(unspecified)'])}"
    return [
        Violation(
            rule="absolute-discount-claim", severity="fail", where=where, term=hit,
            message=(f"absolute claim '{hit}' but {why}. State the qualifier in the same "
                     "line or drop the number. See compliance.md #2."),
        )
        for hit in hits
    ]


# --------------------------------------------------------------------------- rule 3

def check_urgency(text: str, offer: dict | None, *, today: dt.date | None = None,
                  where: str = "") -> list[Violation]:
    """compliance.md #3 - urgency needs a real, dated, evidenced deadline."""
    bl = config.blocklist()
    hits = [t for t in bl.get("urgency_terms", []) if _contains(text, t)]
    if not hits:
        return []

    today = today or dt.date.today()
    out: list[Violation] = []

    def fail(msg: str, term: str) -> None:
        out.append(Violation(rule="unevidenced-urgency", severity="fail", where=where,
                             term=term, message=msg))

    for hit in hits:
        if offer is None:
            fail(f"urgency language '{hit}' on an asset with no offer record.", hit)
            continue
        if offer.get("always_on") or not offer.get("ends"):
            fail(f"urgency language '{hit}' against an always-on offer with no end date. "
                 "compliance.md #3 forbids this outright.", hit)
            continue
        ends = _as_date(offer["ends"])
        if ends is None:
            fail(f"urgency language '{hit}' but the offer's `ends` is not a valid date.", hit)
            continue
        if ends < today:
            fail(f"urgency language '{hit}' but the offer ended on {ends.isoformat()}. "
                 "An expired deadline reused is the exact pattern under litigation.", hit)
            continue
        ev_key = offer.get("evidence")
        evidence = config.products().get("evidence", {}).get(ev_key)
        if not evidence:
            fail(f"urgency language '{hit}' but evidence key '{ev_key}' does not resolve "
                 "to a record in products.yml.", hit)
            continue
        if evidence.get("type") == "no_deadline":
            fail(f"urgency language '{hit}' against evidence '{ev_key}', which is explicitly "
                 "marked as having no deadline.", hit)
    return out


def _as_date(value) -> dt.date | None:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value)
        except ValueError:
            return None
    return None


# --------------------------------------------------------------------------- rule 4

def check_send_preconditions(brand_key: str, recipients: list[dict] | None = None
                             ) -> list[Violation]:
    """compliance.md #4 - postal address, consent, unsubscribe."""
    out: list[Violation] = []
    b = config.brand(brand_key)

    addr_var = b.get("postal_address_env", "")
    if not addr_var:
        out.append(Violation("postal-address", "fail", where=brand_key,
                             message="brand has no postal_address_env configured."))
    elif not config.env(addr_var):
        out.append(Violation(
            "postal-address", "fail", where=brand_key,
            message=(f"{addr_var} is empty. CAN-SPAM requires a real postal address in every "
                     "send and the build will not substitute a placeholder."),
        ))

    for i, r in enumerate(recipients or []):
        who = r.get("email", f"recipient[{i}]")
        if not r.get("consent_source") or not r.get("consent_at"):
            out.append(Violation(
                "missing-consent", "fail", where=who,
                message="recipient has no consent_source/consent_at. Not sendable.",
            ))
    return out


# --------------------------------------------------------------------------- rule 5

def check_attribution(customer_id: str | None, *, today: dt.date | None = None,
                      where: str = "") -> list[Violation]:
    """compliance.md #5 - a named customer needs a current permission record."""
    if not customer_id:
        return []
    today = today or dt.date.today()
    record = config.permissions().get("customers", {}).get(customer_id)
    if not record:
        return [Violation("missing-permission", "fail", where=where, term=customer_id,
                          message=(f"asset references customer '{customer_id}' with no record "
                                   "in config/permissions.yml."))]
    expires = _as_date(record.get("expires")) if record.get("expires") else None
    if expires and expires < today:
        return [Violation("expired-permission", "fail", where=where, term=customer_id,
                          message=(f"permission for '{customer_id}' expired "
                                   f"{expires.isoformat()}."))]
    if not record.get("scope"):
        return [Violation("unscoped-permission", "warn", where=where, term=customer_id,
                          message=f"permission for '{customer_id}' records no agreed scope.")]
    return []


# --------------------------------------------------------------------------- meaning window

def check_meaning_window(window: dict, offer: dict | None, where: str = "") -> list[Violation]:
    """cadence.md - the meaning window carries no offer at all."""
    if window.get("meaning_window") and offer is not None:
        return [Violation(
            "offer-in-meaning-window", "fail", where=where,
            message=(f"an offer was attached inside the '{window.get('id')}' window, which is "
                     "the one offer-free stretch of the year. See strategy/cadence.md."),
        )]
    return []


# --------------------------------------------------------------------------- ladder mix

def check_ladder_mix(rungs: list[str], where: str = "daily-set") -> list[Violation]:
    """value-ladder.md - proof floor and scarcity ceiling."""
    if not rungs:
        return []
    lim = config.limits("ads")
    total = len(rungs)
    scarcity = rungs.count("scarcity") / total
    proof = rungs.count("proof") / total
    out: list[Violation] = []
    if scarcity > lim["max_scarcity_share"] + 1e-9:
        out.append(Violation(
            "scarcity-ceiling", "fail", where=where,
            message=(f"scarcity is {scarcity:.0%} of the set, over the "
                     f"{lim['max_scarcity_share']:.0%} ceiling. A feed that slides into "
                     "all-discount stops being read before the numbers show it."),
        ))
    if proof < lim["min_proof_share"] - 1e-9:
        out.append(Violation(
            "proof-floor", "fail", where=where,
            message=(f"proof is {proof:.0%} of the set, under the "
                     f"{lim['min_proof_share']:.0%} floor. Proof is what makes the other "
                     "rungs survive a sceptical reader."),
        ))
    return out


# --------------------------------------------------------------------------- length limits

def check_length(text: str, maximum: int, where: str) -> list[Violation]:
    if len(text) > maximum:
        return [Violation("over-length", "fail", where=where,
                          message=f"{len(text)} chars, limit {maximum}: {text[:60]!r}...")]
    return []


# --------------------------------------------------------------------------- composite

def check_copy(text: str, *, offer: dict | None = None, window: dict | None = None,
               customer_id: str | None = None, today: dt.date | None = None,
               where: str = "") -> list[Violation]:
    """Run every text-level guard over one piece of copy."""
    out = check_competitor_terms(text, where)
    out += check_unsupportable(text, where)
    out += check_offer_claim(text, offer, where)
    out += check_urgency(text, offer, today=today, where=where)
    out += check_attribution(customer_id, today=today, where=where)
    if window is not None:
        out += check_meaning_window(window, offer, where)
    return out
