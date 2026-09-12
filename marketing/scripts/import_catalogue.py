#!/usr/bin/env python3
"""Regenerate config/products.yml from the product repo's catalogue.

The catalogue is an active workstream in PMD-MASTER, so a hand-written copy here would be
stale within a week and nobody would notice until an ad linked to a product that no longer
exists. This makes products.yml *derived*:

    PMD catalogue source  +  config/products.overrides.yml  ->  config/products.yml

Everything in the overrides file is marketing's to write (keywords, talking points, image
styles, role, and the whole offers/evidence/not_built blocks). Everything else comes from
the product repo and is overwritten on every run.

Two sources, in priority order:

  1. --printful <file.json>   A Printful catalogue export. This is where the product repo is
                              heading: commit aba0e82 wired Printful because its v1 catalog
                              needs no authentication and returns real, FLAT-RATE prices, so
                              a price here is cost-justified rather than a placeholder.
  2. --pmd-repo <path>        The storefront's own ui/src/catalog/productCatalog.ts. This is
                              what renders today. Its prices are hardcoded literals never
                              checked against vendor cost, so they import as placeholders.

Usage:
  python3 marketing/scripts/import_catalogue.py --pmd-repo /home/user/pmd-master
  python3 marketing/scripts/import_catalogue.py --pmd-repo ../pmd-master --check
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

CATALOGUE_REL = "plugins/pmd-customizer/ui/src/catalog/productCatalog.ts"

HEADER = """# Print My Design - product and offer catalogue.
#
# GENERATED FILE - do not edit by hand.
#
#   python3 marketing/scripts/import_catalogue.py --pmd-repo <path-to-PMD-MASTER>
#
# Catalogue fields (name, slug, path, prices, tiers, options) come from the product repo.
# Marketing fields (short, role, keywords, image_style, talking_points) and the whole offers,
# seasonal_offers, evidence and not_built blocks come from products.overrides.yml, which IS
# hand-written. Edit that file, then re-run the importer.
#
# price_basis records how much a price can be trusted:
#   ui_placeholder  - a hardcoded literal in the storefront, never checked against vendor
#                     cost. Nothing guarantees it clears cost plus margin. Not advertisable.
#   vendor_quoted   - a real vendor price with the margin floor applied. Advertisable once
#                     has_price_confidence is set in launch-readiness.yml.
#
# QUANTITY TIERS ARE NOT PRICE BREAKS on the storefront path. The shopper store multiplies a
# unit price linearly, which the product repo's own usePriceQuote.ts calls out as wrong:
# "Gelato's US business-card table runs about 35.9c a unit at 50 and 10.9c at 500 - a 3.3x
# drop." So never advertise a per-unit price at a quantity, and never imply a volume
# discount, unless the product carries flat_rate: true. Flat-rate is the exception the
# product repo relies on: a dropship price that genuinely does not move with volume, so
# multiplying it is arithmetic rather than estimation.
"""


# --------------------------------------------------------------------------- TS parsing

def _block_for(src: str, start: int) -> str:
    """Return the balanced { ... } block beginning at `start`."""
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    return src[start:]


def _field(block: str, name: str) -> str | None:
    m = re.search(rf"\b{name}:\s*'((?:[^'\\]|\\.)*)'", block)
    if m:
        return m.group(1).replace("\\'", "'")
    m = re.search(rf"\b{name}:\s*([0-9]+(?:\.[0-9]+)?)", block)
    return m.group(1) if m else None


def _labels(block: str, section: str) -> list[str]:
    """Pull the human labels out of an options sub-array."""
    m = re.search(rf"{section}:\s*\[", block)
    if not m:
        return []
    inner = _bracket(block, m.end() - 1)
    labels = [lbl.replace('\\"', '"') for lbl in re.findall(r"label:\s*'([^']+)'", inner)]
    if labels:
        return labels
    # Presets referenced by name, e.g. STOCKS.premium -> "premium"
    return [n.split(".")[-1] for n in re.findall(r"[A-Z_]+\.([A-Za-z0-9_]+)", inner)]


def _bracket(src: str, start: int) -> str:
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "[":
            depth += 1
        elif src[i] == "]":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    return src[start:]


def _quantities(block: str) -> list[int]:
    m = re.search(r"quantities:\s*\[([^\]]*)\]", block)
    if not m:
        return []
    return [int(x) for x in re.findall(r"\d+", m.group(1))]


def parse_pmd_catalogue(repo: Path) -> tuple[list[dict], str]:
    path = repo / CATALOGUE_REL
    if not path.exists():
        raise SystemExit(f"catalogue not found at {path}\n"
                         "Pass --pmd-repo pointing at a PMD-MASTER checkout.")
    src = path.read_text(encoding="utf-8")
    m = re.search(r"export const CATALOG[^=]*=\s*\[", src)
    if not m:
        raise SystemExit(f"no `export const CATALOG` array in {path}")
    array = _bracket(src, m.end() - 1)

    products: list[dict] = []
    for om in re.finditer(r"\n  \{", array):
        block = _block_for(array, om.end() - 1)
        slug = _field(block, "slug")
        if not slug:
            continue
        if _field(block, "status") not in (None, "active"):
            continue
        qty = _quantities(block)
        price = _field(block, "startingPrice")
        products.append({
            "key": slug.replace("-", "_"),
            "name": _field(block, "name") or slug,
            "slug": slug,
            "path": f"/products/{slug}",
            "short_description": _field(block, "shortDescription") or "",
            "qty_tiers": qty,
            "qty_anchor": qty[0] if qty else 1,
            "price_from": float(price) if price else None,
            "price_basis": "ui_placeholder",
            "currency": _field(block, "currency") or "USD",
            "stocks": _labels(block, "stocks"),
            "finishes": _labels(block, "finishes"),
            "sizes": _labels(block, "sizes"),
        })
    return products, f"{path.relative_to(repo)} @ {repo.name}"


def parse_printful(export: Path) -> tuple[list[dict], str]:
    """A Printful catalogue export. Prices here are real and flat-rate."""
    data = json.loads(export.read_text(encoding="utf-8"))
    rows = data.get("result") if isinstance(data, dict) else data
    grouped: dict[str, dict] = {}
    for row in rows or []:
        ptype = (row.get("type") or row.get("product_type") or "other").lower()
        key = ptype.replace("-", "_")
        price = row.get("price")
        entry = grouped.setdefault(key, {
            "key": key,
            "name": row.get("title") or ptype.title(),
            "slug": ptype.replace("_", "-"),
            "path": f"/products/{ptype.replace('_', '-')}",
            "short_description": "",
            "qty_tiers": [1],
            "qty_anchor": 1,
            "price_from": None,
            "price_basis": "vendor_quoted",
            "currency": row.get("currency") or "USD",
            "flat_rate": True,
            "variants": 0,
        })
        entry["variants"] += 1
        if price is not None:
            p = float(price)
            entry["price_from"] = p if entry["price_from"] is None else min(entry["price_from"], p)
    return list(grouped.values()), f"printful export {export.name}"


# --------------------------------------------------------------------------- emit

def short_name(name: str, limit: int) -> str:
    if len(name) <= limit:
        return name
    head = re.split(r"\s+(?:&|and)\s+", name)[0]
    return head[:limit].rstrip()


def build_document(products: list[dict], overrides: dict, source: str) -> dict:
    limit = config.limits("ads")["google_headline_max"]
    marketing = overrides.get("products") or {}
    missing = []

    out_products: dict[str, dict] = {}
    for p in products:
        extra = marketing.get(p["key"])
        if extra is None:
            missing.append(p["key"])
            extra = {}
        record = {
            "name": p["name"],
            # `short` is a copy decision, not catalogue data: it fills 30-char ad slots, so
            # "Flyers" beats "Flyers & Brochures". Marketing may set it; otherwise derive.
            "short": extra.get("short") or short_name(p["name"], limit),
            "slug": p["slug"],
            "path": p["path"],
            "role": extra.get("role", "volume"),
        }
        if extra.get("season"):
            record["season"] = extra["season"]
        record.update({
            "qty_anchor": p["qty_anchor"],
            "qty_tiers": p["qty_tiers"],
            "price_from": p["price_from"],
            "price_basis": p["price_basis"],
            "turnaround": None,
            "margin_band": "unknown" if p["price_basis"] == "ui_placeholder" else "floor_applied",
            "keywords": extra.get("keywords") or [p["slug"].replace("-", " ")],
            "image_style": extra.get("image_style") or ["product_on_white"],
        })
        for axis in ("sizes", "stocks", "finishes"):
            if p.get(axis):
                record[axis] = p[axis]
        if p.get("flat_rate"):
            record["flat_rate"] = True
        record["talking_points"] = extra.get("talking_points") or (
            [p["short_description"]] if p.get("short_description") else [])
        out_products[p["key"]] = record

    doc = {
        "version": 1,
        "generated_from": source,
        "defaults": {
            "currency": products[0]["currency"] if products else "USD",
            "verified": False,
            "price_basis": products[0]["price_basis"] if products else "ui_placeholder",
            "path_template": "/products/{slug}",
        },
        "products": out_products,
    }
    for block in ("not_built", "offers", "seasonal_offers", "evidence"):
        if block in overrides:
            doc[block] = overrides[block]
    return doc, missing


def render(doc: dict) -> str:
    return HEADER + "\n" + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=94)


# --------------------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pmd-repo", help="path to a PMD-MASTER checkout")
    ap.add_argument("--printful", help="path to a Printful catalogue export (JSON)")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit non-zero; write nothing")
    args = ap.parse_args(argv)

    if args.printful:
        products, source = parse_printful(Path(args.printful))
    elif args.pmd_repo:
        products, source = parse_pmd_catalogue(Path(args.pmd_repo).resolve())
    else:
        ap.error("pass --pmd-repo or --printful")

    if not products:
        print("no products parsed; refusing to write an empty catalogue")
        return 1

    overrides_path = config.CONFIG_DIR / "products.overrides.yml"
    overrides = yaml.safe_load(overrides_path.read_text(encoding="utf-8"))
    doc, missing = build_document(products, overrides, source)
    rendered = render(doc)

    target = config.CONFIG_DIR / "products.yml"
    current = target.read_text(encoding="utf-8") if target.exists() else ""

    print(f"source   {source}")
    print(f"products {len(products)}: {', '.join(p['key'] for p in products)}")
    if missing:
        print(f"NOTE     no marketing copy yet for: {', '.join(missing)}")
        print("         add them to config/products.overrides.yml; the import used defaults.")

    if rendered == current:
        print("result   products.yml is already up to date")
        return 0

    diff = list(difflib.unified_diff(
        current.splitlines(), rendered.splitlines(),
        fromfile="products.yml (current)", tofile="products.yml (from catalogue)",
        lineterm="", n=1))
    added = sum(1 for d in diff if d.startswith("+") and not d.startswith("+++"))
    removed = sum(1 for d in diff if d.startswith("-") and not d.startswith("---"))

    if args.check:
        print(f"result   DRIFT: {added} line(s) added, {removed} removed")
        print("         the catalogue has moved. Re-run without --check to regenerate.")
        for line in diff[:40]:
            print("    " + line)
        return 1

    target.write_text(rendered, encoding="utf-8")
    print(f"result   rewrote products.yml ({added} added, {removed} removed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
