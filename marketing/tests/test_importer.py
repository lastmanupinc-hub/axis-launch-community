"""Tests for the catalogue importer.

The catalogue is an active workstream in the product repo, so the thing these tests protect
is that products.yml stays *derived*: re-running the importer must be stable, marketing copy
must survive a regeneration, and a product that leaves the catalogue must leave here too.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from lib import config  # noqa: E402
import import_catalogue as imp  # noqa: E402

OVERRIDES = yaml.safe_load((config.CONFIG_DIR / "products.overrides.yml").read_text())
GENERATED = yaml.safe_load((config.CONFIG_DIR / "products.yml").read_text())

FAKE_TS = """
export const CATALOG: CatalogProduct[] = [
  {
    id: 'widgets',
    slug: 'widgets',
    name: 'Widgets & Gadgets',
    shortDescription: 'A thing.',
    description: 'A longer thing.',
    category: 'widgets',
    startingPrice: 12.50,
    currency: 'USD',
    options: {
      stocks: [STOCKS.standard, STOCKS.premium],
      finishes: [FINISHES.none],
      sizes: [
        { id: 'a', label: '1" x 1"', width: 1, height: 1, priceMultiplier: 1.0 },
      ],
      quantities: [10, 20, 50],
    },
    customizable: true,
    status: 'active',
  },
  {
    id: 'draft-thing',
    slug: 'draft-thing',
    name: 'Draft Thing',
    startingPrice: 1.00,
    currency: 'USD',
    options: { quantities: [1] },
    status: 'draft',
  },
];
"""


def parse_fake(tmp: Path):
    root = tmp / "repo"
    target = root / imp.CATALOGUE_REL
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(FAKE_TS, encoding="utf-8")
    return imp.parse_pmd_catalogue(root)


def test_parser_reads_a_product():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        products, _ = parse_fake(Path(tmp))
    assert len(products) == 1
    p = products[0]
    assert p["key"] == "widgets"
    assert p["slug"] == "widgets"
    assert p["path"] == "/products/widgets"
    assert p["price_from"] == 12.50
    assert p["qty_tiers"] == [10, 20, 50]
    assert p["qty_anchor"] == 10


def test_parser_skips_drafts():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        products, _ = parse_fake(Path(tmp))
    assert [p["slug"] for p in products] == ["widgets"]


def test_parser_reads_option_axes():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        products, _ = parse_fake(Path(tmp))
    p = products[0]
    assert p["sizes"] == ['1" x 1"']
    assert p["stocks"] == ["standard", "premium"]


def test_imported_prices_are_marked_as_placeholders():
    """A storefront literal is never cost-justified, and must not claim to be."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        products, _ = parse_fake(Path(tmp))
    assert products[0]["price_basis"] == "ui_placeholder"


def test_printful_prices_are_marked_as_vendor_quoted():
    """Printful is flat-rate and needs no key, which is why the product repo chose it."""
    import json, tempfile
    rows = [{"type": "POSTER", "title": "Enhanced Matte Poster", "price": "8.05"},
            {"type": "POSTER", "title": "Enhanced Matte Poster", "price": "12.30"}]
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "printful.json"
        f.write_text(json.dumps(rows))
        products, _ = imp.parse_printful(f)
    assert products[0]["price_basis"] == "vendor_quoted"
    assert products[0]["price_from"] == 8.05          # lowest variant wins
    assert products[0]["flat_rate"] is True


def test_marketing_copy_survives_a_regeneration():
    """The whole point of the overrides file."""
    for key, extra in OVERRIDES["products"].items():
        generated = GENERATED["products"].get(key)
        if not generated:
            continue
        for field in ("short", "role", "keywords", "image_style", "talking_points"):
            if field in extra:
                assert generated[field] == extra[field], f"{key}.{field} lost on import"


def test_offers_and_evidence_survive_a_regeneration():
    for block in ("not_built", "offers", "seasonal_offers", "evidence"):
        assert GENERATED[block] == OVERRIDES[block], f"{block} not carried through"


def test_the_generated_file_records_where_it_came_from():
    assert GENERATED.get("generated_from"), "products.yml does not say what generated it"


def test_the_generated_file_is_stable():
    """Re-running the importer on unchanged input must be a no-op, or every run is a diff."""
    doc, _ = imp.build_document(
        [{"key": "widgets", "name": "Widgets", "slug": "widgets", "path": "/products/widgets",
          "short_description": "", "qty_tiers": [10], "qty_anchor": 10, "price_from": 1.0,
          "price_basis": "ui_placeholder", "currency": "USD",
          "stocks": [], "finishes": [], "sizes": []}],
        OVERRIDES, "test")
    assert imp.render(doc) == imp.render(imp.build_document(
        [{"key": "widgets", "name": "Widgets", "slug": "widgets", "path": "/products/widgets",
          "short_description": "", "qty_tiers": [10], "qty_anchor": 10, "price_from": 1.0,
          "price_basis": "ui_placeholder", "currency": "USD",
          "stocks": [], "finishes": [], "sizes": []}],
        OVERRIDES, "test")[0])


def test_a_product_with_no_marketing_copy_is_reported_not_dropped():
    doc, missing = imp.build_document(
        [{"key": "brand_new", "name": "Brand New", "slug": "brand-new",
          "path": "/products/brand-new", "short_description": "It is new.",
          "qty_tiers": [1], "qty_anchor": 1, "price_from": 5.0,
          "price_basis": "ui_placeholder", "currency": "USD",
          "stocks": [], "finishes": [], "sizes": []}],
        OVERRIDES, "test")
    assert missing == ["brand_new"]
    assert "brand_new" in doc["products"]
    # It still gets usable defaults rather than being silently skipped.
    assert doc["products"]["brand_new"]["keywords"] == ["brand new"]
    assert doc["products"]["brand_new"]["talking_points"] == ["It is new."]


def test_every_generated_product_has_marketing_copy_today():
    """If this fails, the catalogue moved and config/products.overrides.yml needs a new entry."""
    missing = [k for k in GENERATED["products"] if k not in OVERRIDES["products"]]
    assert not missing, f"no marketing copy for: {missing}"


def test_no_stale_override_survives():
    """A product removed from the catalogue must not linger in the generated file."""
    for key in GENERATED["products"]:
        assert key in OVERRIDES["products"], f"{key} generated with no override entry"


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
