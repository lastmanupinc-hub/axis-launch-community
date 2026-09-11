"""Integrity tests for the YAML configs.

These catch the failures that only show up weeks later: an offer pointing at a product that
was renamed, an evidence key that no longer resolves, a hook that quietly contains a blocked
term. All of it is cheap to check and expensive to discover in an inbox.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import config, guards  # noqa: E402

PRODUCTS = config.products()
ALL_OFFERS = {**PRODUCTS["offers"], **PRODUCTS.get("seasonal_offers", {})}


# --- products ---------------------------------------------------------------

def test_every_product_has_the_required_fields():
    for key, product in PRODUCTS["products"].items():
        for field in ("name", "short", "slug", "path", "role", "turnaround"):
            assert product.get(field), f"{key} is missing {field}"


def test_every_product_has_keywords_for_affinity_matching():
    for key, product in PRODUCTS["products"].items():
        assert product.get("keywords"), f"{key} has no keywords; hooks cannot match it"


def test_short_names_fit_a_google_headline():
    limit = config.limits("ads")["google_headline_max"]
    for key, product in PRODUCTS["products"].items():
        assert len(product["short"]) <= limit, \
            f"{key} short name {product['short']!r} exceeds {limit} chars"


def test_product_paths_are_root_relative():
    for key, product in PRODUCTS["products"].items():
        assert product["path"].startswith("/"), f"{key} path must start with /"


# --- offers -----------------------------------------------------------------

def test_every_offer_applies_to_real_products():
    for key, offer in ALL_OFFERS.items():
        for product in offer.get("applies_to") or []:
            assert product in PRODUCTS["products"], \
                f"offer {key} applies_to unknown product {product!r}"


def test_every_offer_declares_exclusions():
    """compliance.md #2: an offer with no exclusions key cannot be reasoned about."""
    for key, offer in ALL_OFFERS.items():
        assert "exclusions" in offer, f"offer {key} does not declare exclusions"
        assert isinstance(offer["exclusions"], list), f"offer {key} exclusions must be a list"


def test_every_offer_evidence_key_resolves():
    """compliance.md #3: urgency needs evidence, so evidence has to exist."""
    for key, offer in ALL_OFFERS.items():
        ev = offer.get("evidence")
        assert ev in PRODUCTS["evidence"], \
            f"offer {key} evidence {ev!r} does not resolve in products.yml"


def test_always_on_offers_have_no_end_date():
    for key, offer in ALL_OFFERS.items():
        if offer.get("always_on"):
            assert not offer.get("ends"), \
                f"offer {key} is always_on but carries an end date; pick one"


def test_seasonal_offers_all_have_end_dates():
    """They are the only offers allowed to carry urgency, so they must be dated."""
    for key, offer in PRODUCTS.get("seasonal_offers", {}).items():
        assert offer.get("ends"), f"seasonal offer {key} has no end date"


def test_offer_phrases_pass_their_own_guards():
    for key, offer in ALL_OFFERS.items():
        phrase = offer.get("phrase")
        if not phrase:
            continue
        violations = guards.check_competitor_terms(phrase, key) + \
            guards.check_unsupportable(phrase, key) + \
            guards.check_offer_claim(phrase, offer, key)
        fails = [v for v in violations if v.severity == "fail"]
        assert not fails, f"offer {key} phrase trips its own guards: {fails}"


# --- hooks ------------------------------------------------------------------

def test_no_hook_contains_a_blocked_term():
    """The library must not smuggle in what the guards exist to stop."""
    problems = []
    for family, fam in config.hooks()["families"].items():
        for pattern in fam["patterns"]:
            for fill in pattern.get("fills", []):
                v = guards.check_competitor_terms(fill, pattern["id"])
                v += guards.check_unsupportable(fill, pattern["id"])
                problems += [x for x in v if x.severity == "fail"]
    assert not problems, "hooks.yml contains blocked terms:\n" + \
        "\n".join(f"  {p}" for p in problems)


def test_every_hook_declares_a_ladder_rung():
    valid = {"purpose", "story", "identity", "proof", "scarcity"}
    for family, fam in config.hooks()["families"].items():
        for pattern in fam["patterns"]:
            assert pattern.get("ladder") in valid, \
                f"{pattern.get('id')} has an invalid ladder rung {pattern.get('ladder')!r}"


def test_every_hook_has_at_least_one_fill():
    for family, fam in config.hooks()["families"].items():
        for pattern in fam["patterns"]:
            assert pattern.get("fills"), f"{pattern['id']} has no concrete fills"


def test_hook_ids_are_unique():
    seen = set()
    for family, fam in config.hooks()["families"].items():
        for pattern in fam["patterns"]:
            assert pattern["id"] not in seen, f"duplicate hook id {pattern['id']}"
            seen.add(pattern["id"])


def test_the_library_covers_every_ladder_rung():
    rungs = {p["ladder"] for f in config.hooks()["families"].values()
             for p in f["patterns"]}
    assert rungs == {"purpose", "story", "identity", "proof", "scarcity"}, \
        f"hook library does not cover every rung; missing {rungs ^ {'purpose','story','identity','proof','scarcity'}}"


def test_proof_rung_has_enough_hooks_to_meet_its_own_floor():
    """value-ladder.md sets a proof floor; the library has to be able to satisfy it."""
    need = round(config.limits("ads")["variants_per_day"] *
                 config.limits("ads")["min_proof_share"] + 0.4999)
    proof = [p for f in config.hooks()["families"].values()
             for p in f["patterns"] if p["ladder"] == "proof"]
    assert len(proof) >= need, \
        f"only {len(proof)} proof hooks but {need} needed per day"


# --- weekly slots -----------------------------------------------------------

def test_every_weekday_slot_names_real_hook_families():
    known = set(config.hooks()["families"])
    for day, slot in config.weekly_slots()["days"].items():
        for family in slot.get("families", []):
            assert family in known, f"{day} references unknown hook family {family!r}"


def test_every_weekday_slot_can_actually_be_built():
    """A slot whose families contain no hooks for its own lead rung is a dead day."""
    library = config.hooks()["families"]
    for day, slot in config.weekly_slots()["days"].items():
        for rung in (slot.get("ad_emphasis") or {}):
            available = [p for fam in slot["families"]
                         for p in library[fam]["patterns"] if p["ladder"] == rung]
            wider = [p for fam in library.values()
                     for p in fam["patterns"] if p["ladder"] == rung]
            assert available or wider, \
                f"{day} emphasises {rung!r} but no hook anywhere provides it"


# --- brands -----------------------------------------------------------------

def test_every_brand_declares_a_postal_address_variable():
    for key, brand in config.brands()["brands"].items():
        assert brand.get("postal_address_env"), \
            f"brand {key} has no postal_address_env; CAN-SPAM cannot be satisfied"


def test_every_brand_site_is_https():
    for key, brand in config.brands()["brands"].items():
        assert brand["site"].startswith("https://"), f"brand {key} site is not https"


def test_utm_templates_have_the_slots_the_code_fills():
    utm = config.brands()["utm"]
    assert "{date}" in utm["newsletter"]["campaign_template"]
    assert "{platform}" in utm["ads"]["source"]
    assert "{date}" in utm["ads"]["campaign_template"]


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn(); passed += 1
        except Exception:
            failed += 1; print(f"FAIL {name}"); traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    sys.exit(1 if failed else 0)
