"""Copy assembly helpers: slot filling, safe truncation, UTM tagging.

Kept separate from build_ads.py so the newsletter can use the same primitives and the two
never drift on how a URL gets tagged or how a headline gets shortened.
"""
from __future__ import annotations

import re
from urllib.parse import urlencode, urlparse, urlunparse, parse_qsl

from . import config

_SLOT = re.compile(r"\{([a-z_]+)\}")


def fill_slots(template: str, values: dict) -> tuple[str, list[str]]:
    """Substitute {slot} tokens. Returns the text and any slots left unfilled."""
    missing: list[str] = []

    def repl(match: re.Match) -> str:
        key = match.group(1)
        if key in values and values[key] not in (None, ""):
            return str(values[key])
        missing.append(key)
        return match.group(0)

    return _SLOT.sub(repl, template), missing


def truncate(text: str, limit: int, *, ellipsis: str = "") -> str:
    """Trim to a limit on a word boundary. Never cuts mid-word, never leaves dangling punctuation."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if len(text) <= limit:
        return text
    budget = limit - len(ellipsis)
    if budget <= 0:
        return text[:limit]
    cut = text[:budget]
    if " " in cut:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,;:.-") + ellipsis


def first_sentence(text: str) -> str:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip(), maxsplit=1)
    return parts[0] if parts else text


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", (text or "").strip()) if s]


def round_price(value: float) -> int:
    """Round a derived comparison price to a number a person would actually say."""
    value = float(value)
    if value < 50:
        return int(round(value / 5.0) * 5)
    if value < 200:
        return int(round(value / 10.0) * 10)
    return int(round(value / 25.0) * 25)


def money(value: float, currency: str = "USD") -> str:
    symbol = {"USD": "$", "GBP": "£", "EUR": "€"}.get(currency, "")
    if float(value) == int(value):
        return f"{symbol}{int(value)}"
    return f"{symbol}{value:,.2f}"


def tag_url(url: str, params: dict) -> str:
    """Append UTM parameters, preserving anything already on the URL."""
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query.update({k: v for k, v in params.items() if v})
    return urlunparse(parsed._replace(query=urlencode(query)))


def slugify(text: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return text or "item"


def newsletter_url(brand_key: str, path_or_url: str, *, date: str, section: str,
                   slug: str) -> str:
    cfg = config.brands()["utm"]["newsletter"]
    return tag_url(config.absolute_url(brand_key, path_or_url), {
        "utm_source": cfg["source"],
        "utm_medium": cfg["medium"],
        "utm_campaign": cfg["campaign_template"].format(date=date),
        "utm_content": cfg["content_template"].format(section=section, slug=slugify(slug)),
    })


def ad_url(brand_key: str, path_or_url: str, *, date: str, platform: str,
           hook_family: str, ladder: str, variant: str | int) -> str:
    cfg = config.brands()["utm"]["ads"]
    return tag_url(config.absolute_url(brand_key, path_or_url), {
        "utm_source": cfg["source"].format(platform=platform),
        "utm_medium": cfg["medium"],
        "utm_campaign": cfg["campaign_template"].format(date=date),
        "utm_content": cfg["content_template"].format(
            hook_family=hook_family, ladder=ladder, variant=variant),
    })


def offer_phrase(offer: dict | None, currency: str = "USD") -> str:
    """One clause describing an offer. Always carries its qualifier - compliance.md #2."""
    if not offer:
        return ""
    if offer.get("phrase"):
        return str(offer["phrase"])
    kind = offer.get("kind")
    if kind == "percent":
        return f"{offer['value']}% off your {offer.get('label', 'order')}"
    if kind == "shipping":
        return f"free delivery over {money(offer['threshold'], currency)}"
    if kind == "tiered_flat":
        tiers = offer.get("tiers") or []
        if tiers:
            top = tiers[-1]
            return (f"{money(top['off'], currency)} off orders over "
                    f"{money(top['over'], currency)}")
    return str(offer.get("label", ""))


def exclusions_line(offer: dict | None) -> str:
    """The qualifier that has to travel with any number. compliance.md #2."""
    if not offer:
        return ""
    exclusions = offer.get("exclusions") or []
    if not exclusions:
        return "No exclusions."
    return "Excludes " + ", ".join(exclusions) + "."
