"""Tests for the parts that let this run unattended.

The property under test throughout is FAIL CLOSED: when the system cannot see the product,
it must behave as though the product cannot do anything. A false negative costs a quiet day;
a false positive spends money advertising something that does not work.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
os.environ.setdefault("PMD_POSTAL_ADDRESS", "Test, 1 Example Street")

from lib import config, pmd_api  # noqa: E402
import build_ads  # noqa: E402
import import_catalogue as imp  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload
        self.content = b"{}" if payload is not None else b""
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def api_with(responses, token="t"):
    """A PmdApi whose transport returns canned responses keyed by path substring."""
    api = pmd_api.PmdApi(base="https://example.test/api/v4", token=token)

    def fake_request(method, url, headers=None, json=None, timeout=None):
        for fragment, resp in responses.items():
            if fragment in url:
                return resp
        return FakeResponse(404)

    import lib.pmd_api as mod
    api._transport_patch = mod.requests.request
    mod.requests.request = fake_request
    return api, mod


def restore(mod, api):
    mod.requests.request = api._transport_patch


# --- the client fails closed ------------------------------------------------

def test_no_token_means_no_catalogue_and_no_price():
    api = pmd_api.PmdApi(base="https://example.test/api/v4", token="")
    assert api.configured is False
    items, res = api.catalogue()
    assert items == [] and res.ok is False
    quote, res = api.quote("anything", 1)
    assert quote is None


def test_a_422_no_cost_basis_is_not_an_error_it_is_no_price():
    api, mod = api_with({"/pricing/quote": FakeResponse(
        422, {"error": "no_cost_basis", "message": "No cost basis for x"})})
    try:
        quote, res = api.quote("x", 50)
        assert quote is None
        assert res.ok is True          # the service answered correctly
        assert "no_cost_basis" in res.detail
    finally:
        restore(mod, api)


def test_a_real_quote_comes_back_as_a_price():
    api, mod = api_with({"/pricing/quote": FakeResponse(
        200, {"price_cents": 853, "currency": "USD", "floor_applied": True})})
    try:
        quote, _ = api.quote("poster|10x10", 1)
        assert quote is not None
        assert quote.price == 8.53
        assert quote.floor_applied is True
    finally:
        restore(mod, api)


def test_a_quote_with_no_price_field_is_rejected_not_guessed():
    api, mod = api_with({"/pricing/quote": FakeResponse(200, {"currency": "USD"})})
    try:
        quote, res = api.quote("x", 1)
        assert quote is None and res.ok is False
    finally:
        restore(mod, api)


def test_network_failure_yields_no_price():
    api = pmd_api.PmdApi(base="https://example.invalid/api/v4", token="t", timeout=1)
    quote, res = api.quote("x", 1)
    assert quote is None and res.ok is False


# --- the probe fails closed -------------------------------------------------

def test_probe_without_a_token_reports_every_capability_absent():
    api = pmd_api.PmdApi(base="https://example.test/api/v4", token="")
    report = pmd_api.probe_capabilities(api)
    for cap in ("can_transact", "can_fulfil", "has_price_confidence",
                "has_subscriber_capture"):
        assert report.detected[cap] is False
        assert "cannot probe" in report.evidence[cap]


def test_a_404_on_a_payment_route_means_cannot_transact():
    api, mod = api_with({"/checkout/": FakeResponse(404)})
    try:
        report = pmd_api.probe_capabilities(api)
        assert report.detected["can_transact"] is False
        assert "404" in report.evidence["can_transact"]
    finally:
        restore(mod, api)


def test_a_route_that_answers_at_all_means_can_transact():
    """400 or 422 still proves something is listening, which is all this probe claims."""
    api, mod = api_with({"/checkout/pay": FakeResponse(400, {"error": "bad request"})})
    try:
        report = pmd_api.probe_capabilities(api)
        assert report.detected["can_transact"] is True
    finally:
        restore(mod, api)


# --- the merge rule ---------------------------------------------------------

def with_detected(payload):
    """Swap in a detected-readiness file and return the effective capabilities."""
    path = config.CONFIG_DIR / "launch-readiness.detected.yml"
    backup = path.read_text() if path.exists() else None
    try:
        path.write_text(yaml.safe_dump(payload), encoding="utf-8")
        return config.capabilities("print_my_design", refresh=True)
    finally:
        if backup is None:
            path.unlink(missing_ok=True)
        else:
            path.write_text(backup, encoding="utf-8")
        config.capabilities("print_my_design", refresh=True)


def fresh(caps, reachable=True):
    return {"version": 1, "brand": "print_my_design", "reachable": reachable,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "capabilities": caps}


def test_a_fresh_probe_can_turn_a_capability_on_with_no_human_edit():
    caps = with_detected(fresh({"can_transact": True}))
    assert caps["can_transact"] is True


def test_a_fresh_probe_can_turn_a_capability_off_again():
    caps = with_detected(fresh({"can_browse": False}))
    assert caps["can_browse"] is False


def test_an_unreachable_probe_is_ignored_entirely():
    """Blindness must read as 'stop', which means falling back to the conservative baseline,
    never adopting the probe's all-false answer as if it were measurement."""
    caps = with_detected(fresh({"can_browse": False, "can_transact": True},
                               reachable=False))
    declared = config.launch_readiness()["print_my_design"]["capabilities"]
    assert caps["can_browse"] is declared["can_browse"]
    assert caps["can_transact"] is declared["can_transact"]


def test_a_stale_probe_is_ignored():
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
        hours=config.DETECTION_MAX_AGE_HOURS + 1)
    caps = with_detected({"version": 1, "brand": "print_my_design", "reachable": True,
                          "checked_at": old.isoformat(timespec="seconds"),
                          "capabilities": {"can_transact": True}})
    assert caps["can_transact"] is False


def test_a_probe_for_another_brand_is_ignored():
    caps = with_detected(fresh({"can_transact": True}) | {"brand": "somebody_else"})
    assert caps["can_transact"] is False


# --- pricing drives the copy ------------------------------------------------

def test_no_quote_means_no_price_slot_is_offered():
    assert build_ads.PRICE_SLOTS <= build_ads.unavailable_slots(None)


def test_a_quote_unlocks_the_price_slots():
    q = pmd_api.Quote(variant_key="x", quantity=1, price_cents=1000)
    assert not (build_ads.PRICE_SLOTS & build_ads.unavailable_slots({"posters": q}))


def test_no_ad_carries_a_price_when_the_engine_returns_none():
    payload, _ = build_ads.build_day(dt.date(2026, 9, 12), {"history": []})
    assert payload["pricing"]["ads_carrying_a_price"] == 0
    assert all(v["price"] is None for v in payload["variants"])


def test_products_without_a_variant_key_are_not_quoted():
    prices, notes = build_ads.fetch_prices(
        pmd_api.PmdApi(base="https://example.test/api/v4", token=""))
    assert prices == {}
    assert all(n["priced"] is False for n in notes)
    keyless = [n for n in notes if "no variant_key" in n.get("reason", "")]
    assert keyless, "expected products with no variant key to be reported, not quoted"


# --- the importer is safe to run unattended ---------------------------------

def test_an_empty_catalogue_is_refused_rather_than_written():
    rc = imp.main(["--printful", str(_empty_export())])
    assert rc == 1


def _empty_export():
    f = Path(tempfile.mkdtemp()) / "empty.json"
    f.write_text("[]")
    return f


def test_only_the_live_api_marks_a_catalogue_verified():
    assert imp.source_is_live("https://x/api/v4/catalog/products") is True
    assert imp.source_is_live("ui/src/catalog/productCatalog.ts @ pmd-master") is False
    assert imp.source_is_live("printful export x.json") is False


def test_the_current_catalogue_records_its_provenance():
    cat = config.products()
    assert "generated_from" in cat
    assert cat["defaults"]["verified"] == bool(cat.get("generated_from_live_api"))


# --- run health: the difference between waiting and broken -------------------

from lib import health  # noqa: E402


def runs(n, kind="ads", **flags):
    base = {"product_reachable": True, "api_authenticated": True,
            "catalogue_live": True, "produced": True, "capabilities": {}}
    base.update(flags)
    return [dict(base, date=f"2026-09-{i + 1:02d}", kind=kind) for i in range(n)]


def test_a_healthy_run_reports_nothing():
    assert health.assess(history=runs(5)) == []


def test_a_known_blocker_never_alarms():
    """Ads not publishing because checkout takes no money is the system declining on
    purpose. Alarming on it would train everyone to ignore the alarm."""
    blocked = runs(20, produced=True)
    for r in blocked:
        r["dispatched"] = False
        r["blocked_by"] = ["cannot-transact"]
    assert health.ok(health.assess(history=blocked))


def test_being_unreachable_notes_before_it_fails():
    two = health.assess(history=runs(2, product_reachable=False))
    assert [f.severity for f in two if f.condition == "product_unreachable"] == ["note"]


def test_being_unreachable_long_enough_fails():
    three = health.assess(history=runs(3, product_reachable=False))
    hit = [f for f in three if f.condition == "product_unreachable"]
    assert hit and hit[0].severity == "fail"
    assert not health.ok(three)


def test_a_dry_newsletter_eventually_fails():
    dry = runs(health.THRESHOLDS["newsletter_dry"], kind="newsletter", produced=False)
    hit = [f for f in health.assess(history=dry) if f.condition == "newsletter_dry"]
    assert hit and hit[0].severity == "fail"


def test_a_single_quiet_day_is_not_a_dry_pipeline():
    mixed = runs(6, kind="newsletter")
    mixed[-1]["produced"] = False
    assert health.ok(health.assess(history=mixed))


def test_a_capability_regression_fails_immediately():
    hist = runs(2)
    hist[0]["capabilities"] = {"can_transact": True}
    hist[1]["capabilities"] = {"can_transact": False}
    hit = [f for f in health.assess(history=hist) if f.condition == "capability_regression"]
    assert hit and hit[0].severity == "fail" and hit[0].streak == 1


def test_going_blind_is_not_reported_as_a_regression():
    """A capability vanishing because we cannot see the product is the blindness, and is
    already reported as product_unreachable. Reporting it twice, once as a regression,
    would send someone hunting for a bug that is not there."""
    hist = runs(2)
    hist[0]["capabilities"] = {"can_transact": True}
    hist[1].update({"product_reachable": False, "capabilities": {}})
    assert not [f for f in health.assess(history=hist)
                if f.condition == "capability_regression"]


def test_a_capability_appearing_is_not_a_regression():
    hist = runs(2)
    hist[0]["capabilities"] = {"can_transact": False}
    hist[1]["capabilities"] = {"can_transact": True}
    assert not [f for f in health.assess(history=hist)
                if f.condition == "capability_regression"]


def test_recording_replaces_the_same_date_and_kind():
    import tempfile
    from pathlib import Path as P
    original = health._path
    with tempfile.TemporaryDirectory() as tmp:
        health._path = lambda: P(tmp) / "health.json"
        try:
            health.record(health.RunRecord(date="2026-09-12", kind="ads", produced=False))
            health.record(health.RunRecord(date="2026-09-12", kind="ads", produced=True))
            hist = health.load()
            assert len(hist) == 1 and hist[0]["produced"] is True
            health.record(health.RunRecord(date="2026-09-12", kind="newsletter"))
            assert len(health.load()) == 2      # a different kind is a different record
        finally:
            health._path = original


def test_no_history_reports_nothing():
    assert health.assess(history=[]) == []


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
