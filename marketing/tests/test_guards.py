"""Tests for the compliance guards.

Each test names the rule in strategy/compliance.md that it holds in place. If a test here
fails, the corresponding paragraph in compliance.md has become a lie.

Run: python3 -m pytest marketing/tests -q      (or: python3 marketing/tests/test_guards.py)
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import guards  # noqa: E402

TODAY = dt.date(2026, 9, 11)

ALWAYS_ON = {"label": "first order", "always_on": True, "ends": None,
             "exclusions": ["delivery"], "evidence": "always_on_acquisition"}
DATED_LIVE = {"label": "autumn signage", "ends": "2026-10-31",
              "exclusions": ["installation"], "evidence": "press_schedule_autumn"}
DATED_EXPIRED = {"label": "old", "ends": "2026-03-01",
                 "exclusions": ["installation"], "evidence": "press_schedule_autumn"}
NO_EXCLUSIONS = {"label": "clean", "ends": "2026-10-31", "exclusions": [],
                 "evidence": "press_schedule_autumn"}


def rules(violations):
    return sorted({v.rule for v in violations})


# --- compliance.md #1 -------------------------------------------------------

def test_competitor_brand_is_blocked():
    v = guards.check_competitor_terms("Cheaper than Vistaprint for 250 cards")
    assert "competitor-brand" in rules(v)
    assert v[0].severity == "fail"


def test_competitor_brand_matches_spaced_and_cased():
    assert guards.check_competitor_terms("VISTA  PRINT charges more")
    assert guards.check_competitor_terms("vistaprint")


def test_competitor_campaign_name_is_blocked():
    v = guards.check_competitor_terms("Print your possible with us")
    assert "competitor-campaign" in rules(v)


def test_clean_copy_passes():
    assert guards.check_competitor_terms("250 cards, on your desk Thursday") == []


def test_unsupportable_superlative_fails():
    v = guards.check_unsupportable("The cheapest business cards anywhere")
    assert "unsupportable-claim" in rules(v)


def test_off_brand_tone_only_warns():
    v = guards.check_unsupportable("Elevate your brand today")
    assert [x.severity for x in v] == ["warn"]


# --- compliance.md #2 -------------------------------------------------------

def test_absolute_claim_with_exclusions_fails():
    v = guards.check_offer_claim("30% off everything", ALWAYS_ON)
    assert "absolute-discount-claim" in rules(v)


def test_absolute_claim_with_no_offer_fails():
    v = guards.check_offer_claim("Sitewide savings this week", None)
    assert "absolute-discount-claim" in rules(v)


def test_absolute_claim_is_allowed_when_exclusions_are_explicitly_empty():
    assert guards.check_offer_claim("30% off everything", NO_EXCLUSIONS) == []


def test_qualified_discount_passes():
    assert guards.check_offer_claim("20% off signage", DATED_LIVE) == []


# --- compliance.md #3 -------------------------------------------------------

def test_urgency_on_always_on_offer_fails():
    v = guards.check_urgency("Last chance to save", ALWAYS_ON, today=TODAY)
    assert "unevidenced-urgency" in rules(v)


def test_urgency_with_no_offer_fails():
    v = guards.check_urgency("Ends tonight", None, today=TODAY)
    assert "unevidenced-urgency" in rules(v)


def test_urgency_on_expired_offer_fails():
    v = guards.check_urgency("Ending soon", DATED_EXPIRED, today=TODAY)
    assert "unevidenced-urgency" in rules(v)
    assert "ended on 2026-03-01" in v[0].message


def test_urgency_on_live_dated_evidenced_offer_passes():
    assert guards.check_urgency("Ending soon", DATED_LIVE, today=TODAY) == []


def test_urgency_with_unresolvable_evidence_fails():
    bad = dict(DATED_LIVE, evidence="no_such_record")
    v = guards.check_urgency("Last chance", bad, today=TODAY)
    assert "unevidenced-urgency" in rules(v)


def test_curly_apostrophe_still_trips_urgency():
    v = guards.check_urgency("Don’t miss out", ALWAYS_ON, today=TODAY)
    assert "unevidenced-urgency" in rules(v)


# --- compliance.md #4 -------------------------------------------------------

def test_missing_postal_address_blocks_send(monkeypatch=None):
    import os
    os.environ.pop("PMD_POSTAL_ADDRESS", None)
    v = guards.check_send_preconditions("print_my_design")
    assert "postal-address" in rules(v)


def test_recipient_without_consent_is_blocked():
    import os
    os.environ["PMD_POSTAL_ADDRESS"] = "1 Example St, Example City"
    v = guards.check_send_preconditions(
        "print_my_design",
        [{"email": "a@example.com"},
         {"email": "b@example.com", "consent_source": "footer-form",
          "consent_at": "2026-01-04"}],
    )
    assert [x.where for x in v] == ["a@example.com"]
    assert "missing-consent" in rules(v)


# --- compliance.md #5 -------------------------------------------------------

def test_unknown_customer_reference_is_blocked():
    v = guards.check_attribution("nobody-real", today=TODAY)
    assert "missing-permission" in rules(v)


def test_no_customer_reference_is_fine():
    assert guards.check_attribution(None, today=TODAY) == []


# --- cadence.md: the meaning window ----------------------------------------

def test_offer_inside_meaning_window_fails():
    v = guards.check_meaning_window({"id": "meaning_window", "meaning_window": True},
                                    DATED_LIVE)
    assert "offer-in-meaning-window" in rules(v)


def test_offer_outside_meaning_window_is_fine():
    assert guards.check_meaning_window({"id": "autumn_ramp"}, DATED_LIVE) == []


# --- value-ladder.md: the mix ----------------------------------------------

def test_scarcity_over_ceiling_fails():
    v = guards.check_ladder_mix(["scarcity", "scarcity", "proof"])
    assert "scarcity-ceiling" in rules(v)


def test_proof_under_floor_fails():
    v = guards.check_ladder_mix(["story", "story", "identity", "purpose", "identity"])
    assert "proof-floor" in rules(v)


def test_balanced_mix_passes():
    assert guards.check_ladder_mix(
        ["proof", "proof", "story", "identity", "purpose", "scarcity"]) == []


# --- lengths ----------------------------------------------------------------

def test_over_length_fails():
    assert guards.check_length("x" * 41, 40, "meta-headline")


def test_within_length_passes():
    assert guards.check_length("x" * 40, 40, "meta-headline") == []


# --- composite --------------------------------------------------------------

def test_check_copy_aggregates_every_rule():
    v = guards.check_copy(
        "Last chance! Cheapest cards, beats Vistaprint, 40% off everything",
        offer=ALWAYS_ON, today=TODAY, where="ad-1",
    )
    found = rules(v)
    for expected in ("competitor-brand", "unsupportable-claim",
                     "absolute-discount-claim", "unevidenced-urgency"):
        assert expected in found, f"{expected} not caught; got {found}"


def test_report_collects_and_reports_ok():
    r = guards.GuardReport()
    r.extend(guards.check_copy("250 cards, on your desk Thursday", offer=None, today=TODAY))
    assert r.ok
    r.extend(guards.check_copy("Cheapest anywhere", offer=None, today=TODAY))
    assert not r.ok
# --- absolute claims must be number-proximate (regression) -------------------

def test_absolute_word_without_a_discount_figure_is_prose_not_a_claim():
    """'Everything else is adjustable' is English, not an offer. Guarding it would get the
    guard switched off, which is worse than not having it."""
    assert guards.check_offer_claim(
        "One factor decides how your print looks: the stock. "
        "Everything else is adjustable after.", None) == []


def test_absolute_word_with_a_percentage_is_still_caught():
    v = guards.check_offer_claim("30% off everything this week", ALWAYS_ON)
    assert "absolute-discount-claim" in rules(v)


def test_absolute_word_with_a_currency_figure_is_caught():
    v = guards.check_offer_claim("$20 off everything in the shop", ALWAYS_ON)
    assert "absolute-discount-claim" in rules(v)


def test_absolute_word_with_the_word_off_is_caught():
    v = guards.check_offer_claim("Money off everything", ALWAYS_ON)
    assert "absolute-discount-claim" in rules(v)


def test_discount_signal_in_a_different_sentence_does_not_trip():
    assert guards.check_offer_claim(
        "20% off signage. Everything else we print stays at list price.", ALWAYS_ON) == []


if __name__ == "__main__":
    import traceback
    fns = [(n, f) for n, f in sorted(globals().items())
           if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in fns:
        try:
            fn()
            passed += 1
        except Exception:
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{passed} passed, {failed} failed, {len(fns)} total")
    sys.exit(1 if failed else 0)
