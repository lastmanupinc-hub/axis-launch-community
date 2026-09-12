#!/usr/bin/env python3
"""Record what this run managed to do, and fail loudly if the pattern is broken.

Run after the daily build. It reads the run's own output, appends a health record, and
exits non-zero when a condition has persisted past its grace period.

    python3 marketing/scripts/report_health.py --kind ads --date 2026-09-12

Exit 0 means "either healthy, or correctly waiting on a known blocker". Exit 1 means
something a person needs to look at. The difference is the whole point - see lib/health.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, health  # noqa: E402

BRAND = "print_my_design"


def read_ads(date: str) -> dict:
    path = config.OUT_DIR / "ads" / date / "ad-set.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def read_issue(date: str) -> dict:
    path = config.OUT_DIR / "newsletter" / date / "issue.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def probe_state() -> dict:
    return config.detected_readiness() or {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kind", choices=["ads", "newsletter"], required=True)
    ap.add_argument("--date", help="ISO date; defaults to today")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args(argv)

    date = args.date or dt.date.today().isoformat()
    probe = probe_state()
    catalogue = config.products()
    caps = config.capabilities(BRAND)

    blocked: list[str] = []
    produced = False
    dispatched = False
    note = ""

    if args.kind == "ads":
        payload = read_ads(date)
        produced = bool(payload.get("variants"))
        dispatched = bool(payload.get("publishable"))
        if payload and not payload.get("publishable"):
            blocked = [f.split(":")[0] for f in payload.get("guards", {}).get("failures", [])]
        note = (f"{len(payload.get('variants', []))} variants, "
                f"{payload.get('pricing', {}).get('ads_carrying_a_price', 0)} priced")
    else:
        payload = read_issue(date)
        decision = payload.get("decision", "hold")
        produced = decision != "hold"
        note = f"decision={decision}, items={payload.get('item_count', 0)}"

    run = health.RunRecord(
        date=date,
        kind=args.kind,
        product_reachable=bool(probe.get("reachable")),
        api_authenticated=bool(probe.get("api_authenticated")),
        catalogue_live=bool(catalogue.get("generated_from_live_api")),
        capabilities={k: bool(v) for k, v in caps.items()},
        produced=produced,
        dispatched=dispatched,
        blocked_by=sorted(set(blocked)),
        note=note,
    )

    history = health.load() if args.no_write else health.record(run)
    if args.no_write:
        history = history + [run.as_dict()]
    findings = health.assess(history=history)

    print(f"=== health {args.kind} {date} ===")
    print(f"  reachable={run.product_reachable} authenticated={run.api_authenticated} "
          f"catalogue_live={run.catalogue_live}")
    print(f"  produced={run.produced} dispatched={run.dispatched}  {run.note}")
    if run.blocked_by:
        print(f"  blocked by: {', '.join(run.blocked_by)}")
    print()
    print(health.summarise(findings))

    if not health.ok(findings):
        print()
        print("Exiting non-zero so this is visible. Nothing is wrong with today's content;")
        print("the system cannot currently see or reach what it needs to do its job.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
