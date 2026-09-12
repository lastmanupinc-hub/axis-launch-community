"""Integration tests for the two builders.

These hold the launch-readiness coupling in place: what the product can actually do has to
bound what the generated assets claim, in both builders, or the gate is decorative.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
os.environ.setdefault("PMD_POSTAL_ADDRESS", "Test, 1 Example Street")

from lib import config, guards  # noqa: E402
import build_ads  # noqa: E402
import build_newsletter  # noqa: E402

DAY = dt.date(2026, 9, 12)
CAN_TRANSACT = config.capabilities("print_my_design").get("can_transact") is True
CAN_FULFIL = config.capabilities("print_my_design").get("can_fulfil") is True
HAS_PRICE = config.capabilities("print_my_design").get("has_price_confidence") is True


def build_set(day=DAY):
    return build_ads.build_day(day, {"history": []})[0]


# --- the ad builder ---------------------------------------------------------

def test_no_ad_carries_an_offer_while_checkout_takes_no_money():
    if CAN_TRANSACT:
        return
    offered = [v["id"] for v in build_set()["variants"] if v["offer"]]
    assert not offered, f"ads carry an offer but nothing can be paid for: {offered}"


def test_no_ad_promises_delivery_while_nothing_ships():
    if CAN_FULFIL:
        return
    bad = []
    for v in build_set()["variants"]:
        for field in (v["meta"]["primary_text"], v["meta"]["headline"],
                      v["meta"]["description"], v["creative"]["footer"]):
            if guards.check_launch_readiness(field, "print_my_design", v["id"]):
                bad.append((v["id"], field[:60]))
    assert not bad, f"delivery or price claims present: {bad[:3]}"


def test_no_ad_advertises_a_price_while_prices_are_placeholders():
    if HAS_PRICE:
        return
    bad = [(v["id"], v["meta"]["headline"]) for v in build_set()["variants"]
           if "$" in v["meta"]["headline"]]
    assert not bad, f"headline advertises an unverified price: {bad}"


def test_the_call_to_action_matches_what_a_visitor_can_do():
    expected = {"Shop now", "Learn more"} if CAN_TRANSACT else {"Try the editor", "Learn more"}
    ctas = {v["meta"]["cta"] for v in build_set()["variants"]}
    assert ctas <= expected, f"unexpected CTA for current capability: {ctas}"


def test_every_ad_links_to_a_real_product_path():
    real = {p["path"] for p in config.products()["products"].values()}
    for v in build_set()["variants"]:
        assert any(path in v["meta"]["url"] for path in real), \
            f"{v['id']} links somewhere that is not a real product page: {v['meta']['url']}"


def test_every_ad_url_is_utm_tagged():
    for v in build_set()["variants"]:
        for url in (v["meta"]["url"], v["google"]["url"]):
            assert "utm_source=" in url and "utm_campaign=" in url, url


def test_ads_only_reference_products_that_exist():
    known = set(config.products()["products"])
    for v in build_set()["variants"]:
        assert v["product"] in known, f"{v['id']} references {v['product']}"


def test_hooks_needing_an_unavailable_slot_are_not_candidates():
    blocked = build_ads.unavailable_slots()
    assert blocked, "expected some slots to be unavailable at current capability"
    for rung in ("proof", "purpose", "identity", "story"):
        for _, _, fill in build_ads.candidate_hooks(
                build_ads.planner.plan_for(DAY), rung):
            for slot in blocked:
                assert "{" + slot + "}" not in fill, f"{slot} offered in: {fill[:60]}"


# --- the newsletter builder -------------------------------------------------

def test_the_newsletter_carries_no_offer_while_checkout_takes_no_money():
    if CAN_TRANSACT:
        return
    payload, _ = build_newsletter.build_issue(DAY, offline=True)
    assert payload["offer"] is None, "newsletter renders an offer nobody can redeem"


def test_the_newsletter_subject_passes_every_guard():
    payload, report = build_newsletter.build_issue(DAY, offline=True)
    hard = [v for v in report.failures if v.rule != "postal-address"]
    assert not hard, [str(v) for v in hard]


def test_the_send_is_blocked_while_there_is_no_list():
    if config.capabilities("print_my_design").get("has_subscriber_capture") is True:
        return
    v = guards.check_can_send("print_my_design")
    assert v and v[0].rule == "no-subscriber-capture"


# --------------------------------------------------------------- the creative itself

def render_ctx(template="statement", footer="Free online editor", cta="Try the editor"):
    """A rendered creative, as HTML, without needing Chromium.

    The template is the last stop before a PNG, and a PNG is not greppable. Everything the
    artwork must carry -- or must not -- is decided here in markup and CSS, so it is
    testable here even though the image is not.
    """
    import render_creative as R
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    env = Environment(
        loader=FileSystemLoader(str(config.REPO_ROOT / "marketing/creative/ad-templates")),
        undefined=StrictUndefined, autoescape=False)
    w = h = 1080
    headline = "A headline of roughly ordinary length for a print advertisement."
    return env.get_template("base.html.j2").render(
        p=R.palette(), w=w, h=h, template=template, kicker="Business cards",
        headline_html=R.emphasise(headline), support="", footer=footer, cta=cta,
        domain=R.display_domain(),
        logo_src=(config.BRAND_DIR / "logo" / "print-my-design-mark.svg").as_uri(),
        font_dir=(config.BRAND_DIR / "fonts").as_uri(),
        **R.scale_for(w, h, headline))


def test_every_creative_carries_the_domain():
    """An ad gets screenshotted and reposted away from every surface that carried a link.
    At that point a CTA reading "Try the editor" is an instruction with no destination."""
    assert "printmydesign.jonathanarvay.com" in render_ctx()


def test_the_domain_comes_from_config_not_a_literal_in_the_renderer():
    """If the site moves, the artwork must follow the same config every link already uses
    rather than keep advertising the old address."""
    import render_creative as R
    site = config.brand("print_my_design")["site"]
    assert R.display_domain() in site
    assert "://" not in R.display_domain()


def test_the_domain_survives_a_creative_with_no_call_to_action():
    """Not every rung gets a CTA. The address is the one thing that is never optional."""
    html = render_ctx(cta="")
    assert "printmydesign.jonathanarvay.com" in html
    assert 'class="cta' not in html


def test_the_deadline_template_can_actually_reach_the_footnote():
    """Regression: `.deadline .footnote` was written while the template class sat only on
    .mid, and .footnote lives in .bottom -- a sibling. The selector matched nothing, so
    every urgency ad rendered its deadline in the same grey as an ordinary footnote and
    nothing errored. Scoping the class to <body> is what makes the rule reachable."""
    html = render_ctx(template="deadline", footer="20% off until 30 September.")
    assert '<body class="deadline">' in html
    assert ".deadline .footnote" in html
    body = html.split("</style>", 1)[1]
    assert body.index('class="deadline"') < body.index('class="footnote"')


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
