#!/usr/bin/env python3
"""Measure what Print My Design can currently do, and write it down.

This is the file that lets the system run unattended. Before it existed, the capability
flags in config/launch-readiness.yml were hand-maintained, which meant the system's idea of
what the product could do was only ever as fresh as someone's memory. Now it asks.

    python3 marketing/scripts/probe_capabilities.py

writes config/launch-readiness.detected.yml, and both builders read the merged view.

MERGE RULE, and it matters:

    a capability is TRUE only when something positively says so

  - a fresh, reachable probe wins over the declared baseline, in both directions. The
    product shipping checkout flips can_transact on with no human edit; the product
    regressing flips it back off the same way.
  - an unreachable or stale probe is ignored entirely, and the declared baseline applies.
  - the declared baseline is conservative. Blindness therefore reads as "stop", never as
    "carry on", which is the only safe default when the failure mode is spending money.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config, pmd_api  # noqa: E402

BRAND = "print_my_design"
DETECTED = config.CONFIG_DIR / "launch-readiness.detected.yml"

HEADER = """# Detected capabilities - GENERATED, do not edit by hand.
#
#   python3 marketing/scripts/probe_capabilities.py
#
# The declared baseline lives in launch-readiness.yml and is conservative. This file is what
# the product actually answered when asked. A fresh, reachable probe overrides the baseline
# in both directions; an unreachable or stale one is ignored and the baseline applies.
#
# `reachable: false` means the probe could not see the product at all. That is treated as
# "stop", not as "carry on" - see scripts/probe_capabilities.py.
"""


def sample_variant() -> tuple[str | None, int]:
    """A variant key and quantity to demonstrate that pricing works.

    Uses the first catalogue product that carries one. Nothing is invented: with no variant
    key recorded anywhere, the pricing probe reports no confidence rather than guessing a
    key that would 404 and look like a different failure.
    """
    for key, product in config.products()["products"].items():
        vk = product.get("variant_key")
        if vk:
            return vk, int(product.get("qty_anchor") or 1)
    return None, 1


def run(*, write: bool = True) -> dict:
    api = pmd_api.PmdApi()
    variant, quantity = sample_variant()
    report = pmd_api.probe_capabilities(api, sample_variant=variant,
                                        sample_quantity=quantity)

    payload = {
        "version": 1,
        "brand": BRAND,
        "checked_at": report.checked_at,
        "reachable": report.reachable,
        "api_base": api.base,
        "api_authenticated": api.configured,
        "capabilities": report.detected,
        "evidence": report.evidence,
        "calls": api.calls,
    }
    if write:
        DETECTED.write_text(HEADER + "\n" + yaml.safe_dump(payload, sort_keys=False,
                                                           width=94), encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-write", action="store_true", help="report only")
    args = ap.parse_args(argv)

    payload = run(write=not args.no_write)

    print(f"=== capability probe {payload['checked_at']} ===")
    print(f"  api       {payload['api_base']}"
          f"  (authenticated: {payload['api_authenticated']})")
    print(f"  reachable {payload['reachable']}")
    if not payload["reachable"]:
        print("  NOTE: the product could not be reached. The declared baseline in")
        print("        launch-readiness.yml applies, which is conservative by design.")
    for cap, value in payload["capabilities"].items():
        mark = "yes" if value else "no "
        print(f"  [{mark}] {cap:<24} {payload['evidence'].get(cap, '')[:78]}")

    effective = config.capabilities(BRAND, refresh=True)
    print("  effective (declared merged with detected):")
    for cap, value in sorted(effective.items()):
        print(f"      {cap:<24} {value}")
    if not args.no_write:
        print(f"  wrote {DETECTED.relative_to(config.REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
