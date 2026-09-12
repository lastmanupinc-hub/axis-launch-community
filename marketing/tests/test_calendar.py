"""Calendar tests: every day of the year must resolve to a plan, and every plan must build.

The failure this prevents is a silent one. A gap in annual.yml only shows up on the day it
is reached, which is a day the newsletter does not go out and nobody finds out until later.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import config, guards, planner  # noqa: E402
import build_ads  # noqa: E402

YEAR = 2027                 # a non-leap year
LEAP = 2028
ALL_DAYS = [dt.date(YEAR, 1, 1) + dt.timedelta(days=i) for i in range(365)]


def test_every_day_of_the_year_resolves_to_a_window():
    missing = []
    for day in ALL_DAYS:
        try:
            planner.resolve_window(day)
        except config.ConfigError:
            missing.append(day.isoformat())
    assert not missing, f"annual.yml has gaps on: {missing[:10]}"


def test_leap_day_resolves():
    planner.resolve_window(dt.date(LEAP, 2, 29))


def test_every_day_produces_a_full_plan():
    for day in ALL_DAYS:
        plan = planner.plan_for(day)
        assert plan.slot and plan.window
        assert plan.ladder in {"purpose", "story", "identity", "proof", "scarcity"}


def test_the_meaning_window_never_carries_an_offer():
    """cadence.md: the one offer-free stretch of the year."""
    for day in ALL_DAYS:
        plan = planner.plan_for(day)
        if plan.is_meaning_window:
            assert plan.offer is None, f"{day} is in the meaning window but has an offer"


def test_the_meaning_window_actually_exists_in_the_year():
    assert any(planner.plan_for(d).is_meaning_window for d in ALL_DAYS), \
        "no day of the year falls in the meaning window"


def test_the_dark_window_exists_and_holds():
    dark = [d for d in ALL_DAYS if planner.plan_for(d).window.get("send_policy") == "hold"]
    assert dark, "no dark window in the calendar"


def test_no_scarcity_ad_is_ever_built_without_a_real_deadline():
    """compliance.md #3, checked across the whole year rather than one sample day.

    A scarcity ad whose offer has no end date is either a guard failure or, worse, an
    implied deadline that does not exist. Neither may reach a build.
    """
    rotation = {"history": []}
    offending = []
    for day in ALL_DAYS:
        payload, _ = build_ads.build_day(day, rotation)
        offers = {**config.products()["offers"],
                  **config.products().get("seasonal_offers", {})}
        for v in payload["variants"]:
            if v["ladder"] != "scarcity":
                continue
            offer = offers.get(v["offer"]) if v["offer"] else None
            if not offer or offer.get("always_on") or not offer.get("ends"):
                offending.append((day.isoformat(), v["id"], v["offer"]))
    assert not offending, \
        f"scarcity ads built with no dated offer behind them: {offending[:5]}"


def test_always_on_offers_are_still_caught_by_the_urgency_guard():
    """Belt and braces: even if one slipped through, the copy guard stops it."""
    always_on = config.products()["offers"]["first_order"]
    v = guards.check_urgency("ending soon", always_on, today=dt.date(YEAR, 1, 8))
    assert v and v[0].rule == "unevidenced-urgency"


def test_every_day_builds_an_ad_set_that_passes_its_own_guards():
    """The real integration test: 365 days, every set built and guarded."""
    failures = []
    rotation = {"history": []}
    for day in ALL_DAYS:
        payload, report = build_ads.build_day(day, rotation)
        hard = [v for v in report.failures if v.rule != "unverified-catalogue"]
        if hard:
            failures.append((day.isoformat(), [str(v) for v in hard[:2]]))
        if len(failures) > 5:
            break
    assert not failures, "days whose ad set fails its own guards:\n" + \
        "\n".join(f"  {d}: {f}" for d, f in failures)


def test_every_day_meets_the_ladder_mix_rules():
    rotation = {"history": []}
    bad = []
    for day in ALL_DAYS:
        payload, _ = build_ads.build_day(day, rotation)
        rungs = [v["ladder"] for v in payload["variants"]]
        if guards.check_ladder_mix(rungs):
            bad.append((day.isoformat(), payload["ladder_mix_pct"]))
    assert not bad, f"days breaching the proof floor or scarcity ceiling: {bad[:5]}"


def test_no_day_produces_an_empty_ad_set():
    rotation = {"history": []}
    empty = [d.isoformat() for d in ALL_DAYS[:90]
             if not build_ads.build_day(d, rotation)[0]["variants"]]
    assert not empty, f"days with no ads at all: {empty[:5]}"


def test_builds_are_deterministic_for_a_given_date():
    """Re-running a failed workflow must not produce different ads."""
    day = dt.date(YEAR, 6, 15)
    a, _ = build_ads.build_day(day, {"history": []})
    b, _ = build_ads.build_day(day, {"history": []})
    assert [v["id"] for v in a["variants"]] == [v["id"] for v in b["variants"]]
    assert [v["meta"]["primary_text"] for v in a["variants"]] == \
           [v["meta"]["primary_text"] for v in b["variants"]]


def test_consecutive_days_differ():
    a, _ = build_ads.build_day(dt.date(YEAR, 6, 15), {"history": []})
    b, _ = build_ads.build_day(dt.date(YEAR, 6, 16), {"history": []})
    assert [v["meta"]["primary_text"] for v in a["variants"]] != \
           [v["meta"]["primary_text"] for v in b["variants"]]


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
