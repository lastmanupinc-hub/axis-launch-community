#!/usr/bin/env python3
"""Build one day's ad set for Print My Design.

This is the "Moment" assembler described in strategy/cadence.md: it recombines the hook
library, the product catalogue and the day's offer into N placement-ready variants, none of
which were hand-designed.

Selection is seeded by the date, so re-running for the same day is byte-identical (safe to
re-run a failed workflow) while consecutive days differ.

Usage:
  python3 marketing/scripts/build_ads.py                     # today
  python3 marketing/scripts/build_ads.py --date 2026-09-12
  python3 marketing/scripts/build_ads.py --days 7            # a week's plan at once
  python3 marketing/scripts/build_ads.py --check             # readiness report, no output
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, copy as C, guards, planner  # noqa: E402

BRAND = "print_my_design"
ROTATION_FILE = config.OUT_DIR / ".hook-rotation.json"


# --------------------------------------------------------------------------- rotation

def load_rotation() -> dict:
    if ROTATION_FILE.exists():
        try:
            return json.loads(ROTATION_FILE.read_text(encoding="utf-8"))
        except Exception:                                # noqa: BLE001
            return {}
    return {}


def save_rotation(data: dict) -> None:
    ROTATION_FILE.parent.mkdir(parents=True, exist_ok=True)
    ROTATION_FILE.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")


def fill_key(pattern_id: str, fill: str) -> str:
    """Identity of one concrete ad line: the pattern plus the words actually used."""
    return f"{pattern_id}:{hashlib.sha1(fill.encode()).hexdigest()[:8]}"


def recently_used(rotation: dict, days: int = 21) -> tuple[set[str], set[str]]:
    """(fill keys, pattern ids) used in the last N issues, so the feed does not repeat."""
    fills: set[str] = set()
    patterns: set[str] = set()
    for entry in sorted(rotation.get("history", []), key=lambda e: e["date"])[-days:]:
        fills.update(entry.get("fills", []))
        patterns.update(entry.get("hooks", []))
    return fills, patterns


# --------------------------------------------------------------------------- selection

def seeded_rng(date: dt.date, salt: str = "") -> random.Random:
    digest = hashlib.sha256(f"{date.isoformat()}|{salt}".encode()).hexdigest()
    return random.Random(int(digest[:16], 16))


def ladder_quota(plan: planner.DayPlan, n: int) -> list[str]:
    """Turn the day's ad_emphasis weights into a concrete list of rungs, length n."""
    emphasis = dict(plan.slot.get("ad_emphasis") or {})
    if plan.is_meaning_window:
        emphasis = {"story": 3, "identity": 2, "purpose": 1}
    if not emphasis:
        emphasis = {"proof": 2, "purpose": 2, "identity": 2}

    lim = config.limits("ads")
    # Honour the ceilings from value-ladder.md while expanding the weights.
    max_scarcity = int(n * lim["max_scarcity_share"])
    min_proof = -(-int(n * lim["min_proof_share"] * 100) // 100)     # ceil
    min_proof = max(1, round(n * lim["min_proof_share"] + 0.4999))

    # No real deadline means no scarcity, whatever the slot asks for. An always-on offer
    # cannot carry urgency (compliance.md #3), so a scarcity ad built on one would either
    # trip the guards or, worse, quietly imply a deadline that does not exist.
    dated_offer = bool(plan.offer and plan.offer.get("ends")
                       and not plan.offer.get("always_on"))
    if not dated_offer and "scarcity" in emphasis:
        emphasis = {k: v for k, v in emphasis.items() if k != "scarcity"}
        emphasis["identity"] = emphasis.get("identity", 0) + 1
        if not emphasis:
            emphasis = {"proof": 2, "purpose": 2, "identity": 2}

    total = sum(emphasis.values())
    rungs: list[str] = []
    for rung, weight in sorted(emphasis.items(), key=lambda kv: -kv[1]):
        count = round(n * weight / total)
        if rung == "scarcity":
            count = min(count, max_scarcity)
        rungs.extend([rung] * count)

    rungs = rungs[:n]
    # Top up to length, then force the proof floor.
    filler = [r for r in ("proof", "purpose", "identity", "story") if r in emphasis] or ["proof"]
    i = 0
    while len(rungs) < n:
        rungs.append(filler[i % len(filler)])
        i += 1
    while rungs.count("proof") < min_proof:
        for idx, r in enumerate(rungs):
            if r not in ("proof",) and rungs.count(r) > 1:
                rungs[idx] = "proof"
                break
        else:
            rungs[-1] = "proof"
    if plan.is_meaning_window:
        rungs = [r for r in rungs if r != "scarcity"] or ["story"] * n
        while len(rungs) < n:
            rungs.append("story")
    return rungs[:n]


UNAVAILABLE_SLOTS_BY_CAPABILITY = {
    "has_price_confidence": {"price", "price_high"},
    "can_fulfil": {"turnaround", "deadline"},
}


def unavailable_slots() -> set[str]:
    """Slots that cannot be filled truthfully today.

    A hook needing {price} cannot run while no price has been reconciled against vendor
    cost; one needing {turnaround} cannot run while nothing ships. Rather than fail the
    build on an unfilled slot, those hooks are simply not candidates yet.
    """
    caps = config.capabilities(BRAND)
    out: set[str] = set()
    for capability, slots in UNAVAILABLE_SLOTS_BY_CAPABILITY.items():
        if caps.get(capability) is not True:
            out |= slots
    return out


def candidate_hooks(plan: planner.DayPlan, rung: str) -> list[tuple[str, dict, str]]:
    """(family, pattern, fill) tuples matching the day's families and this rung."""
    library = config.hooks()["families"]
    families = plan.families or list(library)
    blocked = unavailable_slots()

    def usable(fill: str) -> bool:
        return not (set(re.findall(r"\{([a-z_]+)\}", fill)) & blocked)

    out: list[tuple[str, dict, str]] = []
    for family in families:
        fam = library.get(family)
        if not fam:
            continue
        for pattern in fam["patterns"]:
            if pattern.get("ladder") != rung:
                continue
            for fill in pattern.get("fills", []):
                if usable(fill):
                    out.append((family, pattern, fill))
    if not out:      # widen to every family before giving up on the rung
        for family, fam in library.items():
            for pattern in fam["patterns"]:
                if pattern.get("ladder") == rung:
                    for fill in pattern.get("fills", []):
                        if usable(fill):
                            out.append((family, pattern, fill))
    return out


def product_affinity(text: str) -> list[str]:
    """Which products a piece of hook copy is actually talking about.

    Modular assembly's failure mode is incoherence: a hook about a run of 500 cards pasted
    onto a banner ad. If the copy names a thing, the ad has to be about that thing.
    """
    catalogue = config.products()["products"]
    lowered = " " + re.sub(r"\s+", " ", (text or "").lower()) + " "
    hits: list[tuple[int, str]] = []
    for key, product in catalogue.items():
        for word in product.get("keywords") or []:
            if re.search(rf"\b{re.escape(word.lower())}s?\b", lowered):
                hits.append((len(word), key))          # longest keyword wins
                break
    return [key for _, key in sorted(hits, reverse=True)]


def pick_product(plan: planner.DayPlan, rng: random.Random, used: set[str],
                 affinity: list[str] | None = None) -> tuple[str, dict]:
    catalogue = config.products()["products"]
    # 1. If the hook named a product, the ad is about that product. Non-negotiable.
    for key in affinity or []:
        if key in catalogue:
            return key, catalogue[key]
    lead = [k for k in plan.lead_products if k in catalogue]
    pool = lead or list(catalogue)
    fresh = [k for k in pool if k not in used]
    if not fresh:
        # Lead products exhausted: widen to the rest of the catalogue before repeating one.
        fresh = [k for k in catalogue if k not in used and
                 catalogue[k].get("role") != "lead_magnet"] or pool
    key = rng.choice(sorted(fresh))
    return key, catalogue[key]


# --------------------------------------------------------------------------- assembly

def build_variant(plan: planner.DayPlan, rung: str, family: str, pattern: dict, fill: str,
                  product_key: str, product: dict, index: int) -> dict:
    lim = config.limits("ads")
    currency = config.products()["defaults"]["currency"]
    offer = offer_for_rung(plan, rung)

    blocked = unavailable_slots()
    values = {
        "product": product["name"].lower(),
        "qty": product.get("qty_anchor", ""),
        "audience": "small shops",
    }
    if "price" not in blocked:
        values["price"] = C.money(product.get("price_from", 0), currency)
        values["price_high"] = C.money(
            C.round_price(product.get("price_from", 0) * 2.2), currency)
    if "turnaround" not in blocked:
        values["turnaround"] = product.get("turnaround", "")
        values["deadline"] = (offer or {}).get("ends", "")
    hook, missing = C.fill_slots(fill, values)

    # Body: the hook, then one concrete talking point, then the offer clause if there is one.
    talking = product.get("talking_points") or []
    # Drop any talking point that names a different product than the hook does.
    hook_affinity = set(product_affinity(hook))
    usable = [t for t in talking
              if not (set(product_affinity(t)) - hook_affinity - {product_key})]
    talking = usable or talking
    support = talking[index % len(talking)] if talking else ""
    parts = [hook]
    if support and support.lower() not in hook.lower():
        parts.append(support)

    offer_clause = ""
    if offer:
        offer_clause = C.offer_phrase(offer, currency).capitalize() + "."
        excl = C.exclusions_line(offer)
        parts.append(f"{offer_clause} {excl}".strip())

    primary_text = " ".join(p.rstrip() for p in parts if p)

    # Headline: product-led and short. Never the hook, which is always too long for 40 chars.
    # The rung decides what the headline is *about*: only a price rung leads on price.
    short = product.get("short") or product["name"]
    caps = config.capabilities(BRAND)
    # A headline may only lean on something that is true today. With fulfilment and
    # pricing unconfirmed, that leaves the product and its options - which is honest and
    # still specific, because the option set is real.
    if offer and offer.get("kind") == "percent" and caps.get("can_transact"):
        headline_raw = f"{offer['value']}% off {short.lower()}"
    elif rung == "proof" and product.get("turnaround") and caps.get("can_fulfil"):
        headline_raw = f"{short} in {compact_turnaround(product['turnaround'])}"
    elif product.get("price_from") and caps.get("has_price_confidence"):
        headline_raw = f"{short} from {C.money(product['price_from'], currency)}"
    elif product.get("stocks"):
        headline_raw = f"{short}, {len(product['stocks'])} stocks"
    elif product.get("sizes"):
        headline_raw = f"{short}, {len(product['sizes'])} sizes"
    else:
        headline_raw = f"Design your own {short.lower()}"
    headline = C.truncate(headline_raw, lim["meta_headline_max"])
    description = C.truncate(
        product["turnaround"] if product.get("turnaround") and caps.get("can_fulfil")
        else "Free online editor", lim["meta_description_max"])

    path = product.get("path", "/")
    meta_url = C.ad_url(BRAND, path, date=plan.date.isoformat(), platform="meta",
                        hook_family=family, ladder=rung, variant=index)
    google_url = C.ad_url(BRAND, path, date=plan.date.isoformat(), platform="google",
                          hook_family=family, ladder=rung, variant=index)

    # Google needs three short headlines and two descriptions.
    third = (compact_turnaround(product["turnaround"])
             if product.get("turnaround") and caps.get("can_fulfil")
             else "Design it yourself")
    g_heads = [
        C.truncate(short, lim["google_headline_max"]),
        C.truncate(headline_raw, lim["google_headline_max"]),
        C.truncate(third, lim["google_headline_max"]),
    ]
    g_descs = [
        C.truncate(C.first_sentence(hook), lim["google_description_max"]),
        C.truncate(support or C.offer_phrase(offer, currency) or product["name"],
                   lim["google_description_max"]),
    ]

    return {
        "id": f"{plan.date.isoformat()}-{index:02d}",
        "date": plan.date.isoformat(),
        "ladder": rung,
        "hook_family": family,
        "hook_id": pattern["id"],
        "fill_key": fill_key(pattern["id"], fill),
        "product": product_key,
        "offer": plan.offer_key if offer else None,
        "unfilled_slots": missing,
        "meta": {
            "primary_text": primary_text,
            "primary_text_prefold": C.truncate(primary_text, lim["meta_primary_text_max"]),
            "headline": headline,
            "description": description,
            "cta": ("Learn more" if rung in ("purpose", "story")
                    else ("Shop now" if caps.get("can_transact") else "Try the editor")),
            "url": meta_url,
        },
        "google": {
            "headlines": g_heads,
            "descriptions": g_descs,
            "url": google_url,
        },
        "creative": {
            "template": creative_template_for(rung, product),
            "image_style": (product.get("image_style") or ["product_on_white"])[
                index % max(1, len(product.get("image_style") or [1]))],
            # Long enough to keep a sentence's payoff word; render_creative scales the
            # type down rather than cutting the line short.
            "headline": C.truncate(C.first_sentence(hook), 130),
            "kicker": product["name"],
            "footer": offer_clause or (product["turnaround"]
                                   if product.get("turnaround") and caps.get("can_fulfil")
                                   else "Free online editor"),
            "ratios": ["1:1", "4:5", "9:16"],
        },
    }


def compact_turnaround(text: str) -> str:
    """"3 business days" -> "3 days". Headline slots are 30-40 chars; "business" never fits."""
    text = (text or "").strip()
    text = re.sub(r"\bbusiness\s+days?\b", "days", text)
    text = re.sub(r"\bposted within\b", "posted in", text)
    return re.sub(r"\s+", " ", text).strip()


def offer_for_rung(plan: planner.DayPlan, rung: str) -> dict | None:
    """Which rungs are allowed to carry the price.

    value-ladder.md: proof, purpose and story are about the object and the evidence. Hanging
    a discount on them collapses them into scarcity, which is how a feed quietly turns into
    an all-discount feed while every individual ad still looks fine.
    """
    if plan.is_meaning_window or not plan.offer:
        return None
    if not config.capabilities(BRAND).get("can_transact"):
        # No checkout, no offer. An ad promising a discount the buyer cannot redeem is
        # the worst kind of wasted click.
        return None
    if rung == "scarcity":
        return plan.offer
    if rung == "identity" and plan.discount_weight >= 0.75:
        return plan.offer
    return None


def creative_template_for(rung: str, product: dict) -> str:
    return {
        "proof": "receipt",
        "scarcity": "deadline",
        "story": "quote",
        "identity": "statement",
        "purpose": "statement",
    }.get(rung, "statement")


# --------------------------------------------------------------------------- build

def build_day(date: dt.date, rotation: dict) -> tuple[dict, guards.GuardReport]:
    plan = planner.plan_for(date)
    lim = config.limits("ads")
    n = lim["variants_per_day"]
    rng = seeded_rng(date, "ads")
    rungs = ladder_quota(plan, n)
    avoid_fills, avoid_patterns = recently_used(rotation)

    variants: list[dict] = []
    used_products: set[str] = set()
    used_hooks: set[str] = set()
    used_fills: set[str] = set()
    family_counts: dict[str, int] = {}
    reused = 0

    for index, rung in enumerate(rungs, start=1):
        pool = candidate_hooks(plan, rung)
        if not pool:
            continue
        today_ok = [c for c in pool
                    if c[1]["id"] not in used_hooks
                    and fill_key(c[1]["id"], c[2]) not in used_fills]
        tiers = [
            # best: neither the technique nor these words seen in the rotation window
            [c for c in today_ok
             if c[1]["id"] not in avoid_patterns
             and fill_key(c[1]["id"], c[2]) not in avoid_fills],
            # next: technique seen recently, but these exact words have not been used
            [c for c in today_ok if fill_key(c[1]["id"], c[2]) not in avoid_fills],
            # last: anything not already used today
            today_ok,
            pool,
        ]
        pool_to_use = next((t for t in tiers if t), pool)
        if pool_to_use is not tiers[0]:
            reused += 1
        # Prefer the family used least so far today, so one family cannot own the whole set.
        least = min(family_counts.get(c[0], 0) for c in pool_to_use)
        balanced = [c for c in pool_to_use if family_counts.get(c[0], 0) == least]
        family, pattern, fill = rng.choice(sorted(balanced, key=lambda c: (c[1]["id"], c[2])))
        used_hooks.add(pattern["id"])
        used_fills.add(fill_key(pattern["id"], fill))
        family_counts[family] = family_counts.get(family, 0) + 1
        product_key, product = pick_product(plan, rng, used_products,
                                            affinity=product_affinity(fill))
        used_products.add(product_key)
        variants.append(build_variant(plan, rung, family, pattern, fill,
                                      product_key, product, index))

    report = guards.GuardReport()
    report.extend(guards.check_ladder_mix([v["ladder"] for v in variants],
                                          where=f"ad-set {date.isoformat()}"))
    catalogue_offers = {**config.products()["offers"],
                        **config.products().get("seasonal_offers", {})}
    for v in variants:
        offer = catalogue_offers.get(v["offer"]) if v["offer"] else None
        texts = [
            (v["meta"]["primary_text"], f"{v['id']} meta.primary_text"),
            (v["meta"]["headline"], f"{v['id']} meta.headline"),
            (v["creative"]["headline"], f"{v['id']} creative.headline"),
        ] + [(h, f"{v['id']} google.headline") for h in v["google"]["headlines"]] \
          + [(d, f"{v['id']} google.description") for d in v["google"]["descriptions"]]
        for text, where in texts:
            report.extend(guards.check_copy(text, offer=offer, window=plan.window,
                                            today=date, where=where))
        report.extend(guards.check_length(v["meta"]["headline"], lim["meta_headline_max"],
                                          f"{v['id']} meta.headline"))
        report.extend(guards.check_length(v["meta"]["description"],
                                          lim["meta_description_max"],
                                          f"{v['id']} meta.description"))
        for h in v["google"]["headlines"]:
            report.extend(guards.check_length(h, lim["google_headline_max"],
                                              f"{v['id']} google.headline"))
        for d in v["google"]["descriptions"]:
            report.extend(guards.check_length(d, lim["google_description_max"],
                                              f"{v['id']} google.description"))
        if v["unfilled_slots"]:
            report.add(guards.Violation(
                "unfilled-slot", "fail", where=v["id"],
                message=f"template slots left unfilled: {', '.join(v['unfilled_slots'])}"))

    unverified = [v["product"] for v in variants
                  if not config.products()["products"][v["product"]].get(
                      "verified", config.products()["defaults"].get("verified", False))]
    if unverified:
        report.add(guards.Violation(
            "unverified-catalogue", "warn", where="products.yml",
            message=("prices/turnarounds not yet verified against the live shop for: "
                     + ", ".join(sorted(set(unverified)))
                     + ". Proofing is fine; publishing live is blocked.")))

    mix: dict[str, int] = {}
    for v in variants:
        mix[v["ladder"]] = mix.get(v["ladder"], 0) + 1

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "brand": BRAND,
        "plan": plan.as_dict(),
        "ladder_mix": mix,
        "ladder_mix_pct": {k: round(100 * v / max(1, len(variants)))
                           for k, v in sorted(mix.items())},
        "diversity": {
            "variants": len(variants),
            "from_rotation_window": reused,
            "note": ("hooks reused from the last 21 days because the library ran out of "
                     "unseen lines for one of today's rungs; see README, Growing the library")
                    if reused else "every line unseen in the last 21 days",
        },
        "variants": variants,
        "guards": {
            "ok": report.ok,
            "failures": [str(v) for v in report.failures],
            "warnings": [str(v) for v in report.warnings],
        },
        "publishable": report.ok and not unverified,
    }
    return payload, report


# --------------------------------------------------------------------------- output

def write_outputs(payload: dict) -> list[Path]:
    date = payload["plan"]["date"]
    out = config.OUT_DIR / "ads" / date
    out.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    json_path = out / "ad-set.json"
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    written.append(json_path)

    meta_csv = out / "meta-bulk.csv"
    with meta_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Ad Name", "Primary Text", "Headline", "Description", "Link",
                    "Call To Action", "Ladder", "Hook Family", "Hook ID", "Product"])
        for v in payload["variants"]:
            w.writerow([v["id"], v["meta"]["primary_text"], v["meta"]["headline"],
                        v["meta"]["description"], v["meta"]["url"], v["meta"]["cta"],
                        v["ladder"], v["hook_family"], v["hook_id"], v["product"]])
    written.append(meta_csv)

    google_csv = out / "google-bulk.csv"
    with google_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["Ad Name", "Headline 1", "Headline 2", "Headline 3",
                    "Description 1", "Description 2", "Final URL", "Ladder", "Product"])
        for v in payload["variants"]:
            h = v["google"]["headlines"] + ["", "", ""]
            d = v["google"]["descriptions"] + ["", ""]
            w.writerow([v["id"], h[0], h[1], h[2], d[0], d[1], v["google"]["url"],
                        v["ladder"], v["product"]])
    written.append(google_csv)

    md_path = out / "review.md"
    md_path.write_text(render_review(payload), encoding="utf-8")
    written.append(md_path)
    return written


def render_review(payload: dict) -> str:
    plan = payload["plan"]
    lines = [
        f"# Ad set - {plan['date']} ({plan['weekday'].title()})",
        "",
        f"**Window** {plan['window']['label']} (`{plan['window']['id']}`, posture "
        f"{plan['window']['posture']}, discount weight {plan['window']['discount_weight']})",
        f"**Slot** {plan['slot']['label']} - leads on *{plan['slot']['ladder']}*",
        f"**Offer** {plan['offer']['key'] if plan['offer'] else 'none today, by design'}",
        "",
        "**Ladder mix** " + ", ".join(f"{k} {v}%" for k, v in
                                      payload["ladder_mix_pct"].items()),
        "",
        "**Publishable** " + ("yes" if payload["publishable"] else
                              "no - see guards below"),
        "",
    ]
    if payload["guards"]["failures"]:
        lines += ["## Guard failures", ""] + \
                 [f"- {f}" for f in payload["guards"]["failures"]] + [""]
    if payload["guards"]["warnings"]:
        lines += ["## Guard warnings", ""] + \
                 [f"- {w}" for w in payload["guards"]["warnings"]] + [""]
    for v in payload["variants"]:
        lines += [
            f"## {v['id']} - {v['ladder']} / {v['hook_family']} / `{v['hook_id']}`",
            "",
            f"**Product** {v['product']}",
            "",
            "**Meta**",
            "",
            f"> {v['meta']['primary_text']}",
            "",
            f"- Headline: `{v['meta']['headline']}` ({len(v['meta']['headline'])} chars)",
            f"- Description: `{v['meta']['description']}`",
            f"- CTA: {v['meta']['cta']}",
            f"- Link: {v['meta']['url']}",
            "",
            "**Google**",
            "",
            "- " + " | ".join(f"`{h}`" for h in v["google"]["headlines"]),
            "- " + " | ".join(f"`{d}`" for d in v["google"]["descriptions"]),
            "",
            f"**Creative** template `{v['creative']['template']}`, style "
            f"`{v['creative']['image_style']}`, ratios "
            f"{', '.join(v['creative']['ratios'])}",
            "",
        ]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="ISO date; defaults to today")
    ap.add_argument("--days", type=int, default=1, help="build this many consecutive days")
    ap.add_argument("--check", action="store_true",
                    help="report readiness and exit without writing files")
    ap.add_argument("--out-json", action="store_true", help="print the payload to stdout")
    args = ap.parse_args(argv)

    start = dt.date.fromisoformat(args.date) if args.date else dt.date.today()
    rotation = load_rotation()
    rotation.setdefault("history", [])
    exit_code = 0

    for offset in range(max(1, args.days)):
        date = start + dt.timedelta(days=offset)
        payload, report = build_day(date, rotation)

        if args.out_json:
            print(json.dumps(payload, indent=2))
        else:
            plan = payload["plan"]
            print(f"\n=== {date.isoformat()} ({plan['weekday']}) "
                  f"{plan['window']['label']} / {plan['slot']['label']} ===")
            print(f"    offer: {plan['offer']['key'] if plan['offer'] else 'none'}"
                  f"    mix: " + ", ".join(f"{k} {v}%" for k, v in
                                           payload['ladder_mix_pct'].items()))
            for v in payload["variants"]:
                print(f"    [{v['ladder']:<9}] {v['hook_family']:<13} "
                      f"{v['product']:<16} {v['meta']['headline']}")

        if not args.check:
            written = write_outputs(payload)
            rotation["history"] = [h for h in rotation["history"]
                                   if h.get("date") != date.isoformat()]
            rotation["history"].append({
                "date": date.isoformat(),
                "hooks": [v["hook_id"] for v in payload["variants"]],
                "fills": [v["fill_key"] for v in payload["variants"]],
                "products": [v["product"] for v in payload["variants"]],
            })
            rotation["history"] = sorted(rotation["history"],
                                         key=lambda h: h["date"])[-90:]
            print(f"    wrote {len(written)} files to "
                  f"{written[0].parent.relative_to(config.REPO_ROOT)}")

        if report.failures:
            print("\n" + report.summary())
            exit_code = 1
        elif report.warnings:
            print(f"    {len(report.warnings)} warning(s): "
                  + "; ".join(w.message[:80] for w in report.warnings[:2]))

    if not args.check:
        save_rotation(rotation)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
