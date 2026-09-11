#!/usr/bin/env python3
"""Push a day's ad set to the ad platforms.

DRY RUN IS THE DEFAULT, and there is no flag that skips the compliance guards.

Meta: creates paused ad creatives and ads in an existing ad set via the Marketing API. It
never creates or edits a campaign, never changes a budget, and never un-pauses anything.
Turning spend on is a human action in Ads Manager, deliberately.

Google: the Google Ads API needs an approved developer token and an OAuth client, which is
a poor fit for an unattended daily job. The daily build already writes google-bulk.csv in
the Google Ads Editor column format; import that. `--platform google` reports the file and
what to do with it.

Usage:
  python3 marketing/scripts/publish_ads.py --date 2026-09-11
  python3 marketing/scripts/publish_ads.py --date 2026-09-11 --platform meta --live
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, guards  # noqa: E402

GRAPH = "https://graph.facebook.com/v21.0"


def load_set(date: str) -> tuple[dict, Path]:
    path = config.OUT_DIR / "ads" / date / "ad-set.json"
    if not path.exists():
        raise SystemExit(f"no ad set at {path.relative_to(config.REPO_ROOT)}. "
                         f"Run build_ads.py --date {date} first.")
    return json.loads(path.read_text(encoding="utf-8")), path


def recheck(payload: dict, date: str) -> guards.GuardReport:
    """Re-run guards at publish time. An offer's end date may have passed since the build."""
    report = guards.GuardReport()
    today = dt.date.fromisoformat(date)
    offers = {**config.products()["offers"], **config.products().get("seasonal_offers", {})}
    window = payload["plan"]["window"]
    for v in payload["variants"]:
        offer = offers.get(v["offer"]) if v["offer"] else None
        for text, where in (
            (v["meta"]["primary_text"], f"{v['id']} primary_text"),
            (v["meta"]["headline"], f"{v['id']} headline"),
            (v["creative"]["headline"], f"{v['id']} creative"),
        ):
            report.extend(guards.check_copy(text, offer=offer, window=window, today=today,
                                            where=where))
    report.extend(guards.check_ladder_mix([v["ladder"] for v in payload["variants"]]))
    if not payload.get("publishable", False):
        report.add(guards.Violation(
            "not-publishable", "fail", where="build",
            message="the build marked this set not publishable (unverified catalogue or "
                    "build-time guard failures). See review.md."))
    return report


def publish_meta(payload: dict, creative_dir: Path, *, live: bool) -> list[dict]:
    account = config.env("META_AD_ACCOUNT_ID", required=True)      # act_123456
    token = config.env("META_ACCESS_TOKEN", required=True)
    page_id = config.env("META_PAGE_ID", required=True)
    ad_set_id = config.env("META_AD_SET_ID", required=True)
    results = []

    for v in payload["variants"]:
        image = next(iter(sorted(creative_dir.glob(
            f"*-{v['id'].rsplit('-', 1)[-1]}-{v['ladder']}-1x1.png"))), None)
        plan = {
            "ad_name": v["id"],
            "ad_set_id": ad_set_id,
            "status": "PAUSED",                 # always. Un-pausing is a human action.
            "creative": {
                "object_story_spec": {
                    "page_id": page_id,
                    "link_data": {
                        "message": v["meta"]["primary_text"],
                        "name": v["meta"]["headline"],
                        "description": v["meta"]["description"],
                        "link": v["meta"]["url"],
                        "call_to_action": {"type": "LEARN_MORE"
                                           if v["meta"]["cta"] == "Learn more"
                                           else "SHOP_NOW"},
                    },
                },
            },
            "image_file": str(image.relative_to(config.REPO_ROOT)) if image else None,
        }
        if not live:
            results.append({"would_create": plan})
            continue

        if image is None:
            results.append({"ad": v["id"], "error": "no 1:1 creative rendered; skipped"})
            continue
        with image.open("rb") as fh:
            up = requests.post(f"{GRAPH}/{account}/adimages",
                               data={"access_token": token},
                               files={"filename": fh}, timeout=60)
        if up.status_code >= 300:
            results.append({"ad": v["id"], "error": f"image upload: {up.text[:200]}"})
            continue
        images = up.json().get("images", {})
        image_hash = next(iter(images.values()), {}).get("hash")
        if not image_hash:
            results.append({"ad": v["id"], "error": "no image hash returned"})
            continue

        spec = plan["creative"]["object_story_spec"]
        spec["link_data"]["image_hash"] = image_hash
        cr = requests.post(f"{GRAPH}/{account}/adcreatives", timeout=60, data={
            "access_token": token, "name": f"{v['id']} creative",
            "object_story_spec": json.dumps(spec)})
        if cr.status_code >= 300:
            results.append({"ad": v["id"], "error": f"creative: {cr.text[:200]}"})
            continue
        creative_id = cr.json().get("id")

        ad = requests.post(f"{GRAPH}/{account}/ads", timeout=60, data={
            "access_token": token, "name": v["id"], "adset_id": ad_set_id,
            "creative": json.dumps({"creative_id": creative_id}), "status": "PAUSED"})
        if ad.status_code >= 300:
            results.append({"ad": v["id"], "error": f"ad: {ad.text[:200]}"})
            continue
        results.append({"ad": v["id"], "creative_id": creative_id,
                        "ad_id": ad.json().get("id"), "status": "PAUSED"})
    return results


def report_google(date: str) -> list[dict]:
    csv_path = config.OUT_DIR / "ads" / date / "google-bulk.csv"
    return [{
        "file": str(csv_path.relative_to(config.REPO_ROOT)) if csv_path.exists()
                else "MISSING - run build_ads.py first",
        "how": ("Google Ads Editor > Account > Import > from file. Review the diff, then "
                "post. The API path needs an approved developer token and an OAuth client, "
                "which is a poor fit for an unattended daily job."),
    }]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="ISO date; defaults to today")
    ap.add_argument("--platform", default="all", choices=["all", "meta", "google"])
    ap.add_argument("--live", action="store_true",
                    help="actually create PAUSED ads. Without this nothing is created.")
    args = ap.parse_args(argv)

    date = args.date or dt.date.today().isoformat()
    payload, set_path = load_set(date)
    report = recheck(payload, date)

    mode = "LIVE" if args.live else "dry run"
    print(f"=== publish ads {date} ({mode}) ===")
    print(f"  variants  {len(payload['variants'])}")
    print(f"  mix       " + ", ".join(f"{k} {v}%" for k, v in
                                      payload["ladder_mix_pct"].items()))

    if not report.ok:
        print("\n" + report.summary())
        print("\nREFUSING TO PUBLISH. There is no override flag.")
        return 1
    print(f"  guards    clean ({len(report.warnings)} warning(s))")

    creative_dir = set_path.parent / "creative"
    if not creative_dir.exists():
        print(f"  note      no rendered creative in "
              f"{creative_dir.relative_to(config.REPO_ROOT)}; "
              f"run render_creative.py --date {date}")

    if args.platform in ("all", "meta"):
        print("\n-- meta --")
        try:
            for row in publish_meta(payload, creative_dir, live=args.live):
                print("  " + json.dumps(row)[:240])
        except config.ConfigError as exc:
            print(f"  missing credentials: {exc}")
            if args.live:
                return 1

    if args.platform in ("all", "google"):
        print("\n-- google --")
        for row in report_google(date):
            print(f"  file: {row['file']}")
            print(f"  {row['how']}")

    if not args.live:
        print("\n  Dry run only. Nothing was created. Re-run with --live to create PAUSED "
              "ads; turning them on stays a human action in Ads Manager.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
