#!/usr/bin/env python3
"""Generate the product photography the ad creative asks for but does not have.

MANUAL, NETWORK-BOUND, KEY-GATED. Never wired into either daily workflow, for the same
reason import_catalogue.py is a separate step: a build that can call a paid image API is a
build that can spend money on a schedule. Run it by hand, review what comes back, commit the
files you keep. From then on the renderer just reads them off disk.

WHY THIS EXISTS

build_ads.py already chooses an `image_style` for every variant from products.overrides.yml
-- in_hand, stack_macro, flat_lay, detail_macro, install_shot, lifestyle_in_context,
product_on_white. That choice has been going into ad-set.json and then nowhere, because no
image existed to satisfy it. Six products x three declared styles each is 18 real pairs.

There is no existing photography to use instead. PMD-MASTER carries none (only Playwright
failure screenshots), and the three photographs in the AXIS Launch repo are that brand's
office/lifestyle set -- a person at a laptop looking at a dashboard. Putting those behind a
print ad would be decorative filler showing nobody printing anything, which is the failure
this whole system is built to refuse.

WHAT THE PROMPTS MAY NOT SHOW

Two bans, both load-bearing rather than stylistic:

  No shipping, packaging, couriers, mailers, delivery vans or parcels. `can_fulfil` is
  false -- nothing ships -- and a photograph of a parcel makes a delivery promise just as
  surely as the word "delivered", except no guard can read it. guards.check_offer_claim()
  greps text; nothing greps a picture, so the restraint has to live in the prompt.

  No prices, price tags, discount stickers, or percentage signs on any surface in frame.
  `can_transact` is false and `has_price_confidence` is false. The copy refuses to name a
  number; the artwork must not smuggle one in behind it.

Also banned, for brand rather than truth reasons (brand/print-my-design.md "what we never
do"): no other printer's layouts, logos or product lines in shot, and no competitor's
recognisable house style. Study the rhythm, not the pictures.

KEYS

Read by label from ../key.txt, never printed, never committed, never echoed -- CLAUDE.md's
hard rule. Labels are tried in order and the first present one decides the provider:

    GEMINI_API_KEY / GOOGLE_API_KEY  ->  Gemini image ("nano banana")
    XAI_API_KEY                      ->  xAI Grok Imagine

The sibling repo's scripts/generate_marketing_media.py established the xAI path; this
supports both because which key exists is the owner's choice, not this script's to assume.
Absent every label it exits 3 saying which labels it looked for -- never a stack trace, and
never a partial value.

Usage:
    python3 marketing/scripts/generate_product_imagery.py --check         # keys + plan only
    python3 marketing/scripts/generate_product_imagery.py --dry-run       # print prompts
    python3 marketing/scripts/generate_product_imagery.py                 # generate all 18
    python3 marketing/scripts/generate_product_imagery.py --slug posters
    python3 marketing/scripts/generate_product_imagery.py --style in_hand --force

Exit codes: 0 fine, 2 nothing generated, 3 no usable key.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

KEY_FILE = Path(config.REPO_ROOT).parent / "key.txt"
OUT_DIR = Path(config.REPO_ROOT) / "marketing" / "brand" / "photography"

KEY_LABELS = [
    ("GEMINI_API_KEY", "gemini"),
    ("GOOGLE_API_KEY", "gemini"),
    ("XAI_API_KEY", "xai"),
]

GEMINI_MODEL = "gemini-2.5-flash-image"
XAI_MODEL = "grok-imagine-image-quality"

# --------------------------------------------------------------------------- direction

# Shot grammar per declared style. These are the seven values products.overrides.yml
# actually uses; a new style there without a line here is a hard error rather than a
# silent fallback, so the config and the camera cannot drift apart.
STYLES = {
    "in_hand":              "held in one person's hands, fingers and thumb visible at the "
                            "edge of the piece, hands doing something real rather than "
                            "presenting to camera",
    "stack_macro":          "a squared-off stack shot close and low, so the cut edges and "
                            "the thickness of the stock are the subject",
    "flat_lay":             "laid out flat from directly above on a work surface, a little "
                            "off-grid, with the everyday objects that would really be there",
    "detail_macro":         "extreme close-up on one edge or corner, the texture of the "
                            "material and the quality of the cut filling the frame",
    "install_shot":         "in place on a wall in a real room, seen at a slight angle, "
                            "with the room readable around it",
    "lifestyle_in_context": "in use where it would actually be used, people present but "
                            "unaware of the camera, the piece incidental rather than posed",
    "product_on_white":     "on a clean warm off-white surface in soft directional daylight, "
                            "one piece, plenty of empty space around it",
}

# Appended to every prompt. The first half is craft; the second half is the honesty gate,
# and it is not decoration -- see WHAT THE PROMPTS MAY NOT SHOW above.
DIRECTION = (
    " Editorial documentary photography, shot on film, natural directional window light, "
    "shallow depth of field, candid and a little imperfect, real paper texture and real "
    "ink. Warm neutral palette; a single small warm-orange object detail is welcome but "
    "never forced, and never a glow or a gradient."
    " Absolutely avoid: glossy 3D render, neon or purple gradients, hologram or "
    "circuit-board motifs, generic futuristic tech cliches, posed corporate stock "
    "photography, forced grins at camera, airbrushed skin, studio flash."
    " Must not appear anywhere in frame: parcels, mailers, shipping boxes, courier bags, "
    "delivery vehicles, postage or tracking labels; prices, price tags, currency symbols, "
    "percentage signs or discount stickers; any other printing company's name, logo or "
    "house style. Legible words on the printed piece should be plain placeholder text."
)


def plan() -> list[tuple[str, str, str]]:
    """Every (slug, style, product name) pair the ad builder can actually ask for."""
    raw = config.products()
    items = raw["products"] if isinstance(raw, dict) and "products" in raw else raw
    out = []
    for slug, product in items.items():
        for style in product.get("image_style") or ["product_on_white"]:
            if style not in STYLES:
                raise SystemExit(
                    f"products.overrides.yml declares image_style {style!r} for {slug}, "
                    f"which this script has no shot direction for. Add it to STYLES rather "
                    f"than letting the renderer ask for a picture nobody described.")
            out.append((slug, style, product.get("name") or slug))
    return out


def prompt_for(slug: str, style: str, name: str) -> str:
    subject = {
        "business_cards": "a small stack of freshly printed business cards on thick uncoated stock",
        "postcards":      "a full-colour printed postcard on heavy card stock",
        "flyers":         "a printed single-sided flyer on matte paper",
        "stickers":       "die-cut vinyl stickers on a backing sheet",
        "posters":        "a large-format printed poster",
        "invitations":    "a printed invitation card with its envelope",
    }.get(slug, f"a printed {name.lower()}")
    return f"{subject}, {STYLES[style]}.{DIRECTION}"


# --------------------------------------------------------------------------- keys

def find_key() -> tuple[str, str, str] | None:
    """(label, provider, key) for the first label present, or None. Never logs a value."""
    if not KEY_FILE.exists():
        return None
    try:
        lines = KEY_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for label, provider in KEY_LABELS:
        for line in lines:
            if line.strip().startswith(f"{label}="):
                value = line.strip().split("=", 1)[1].strip()
                if value:
                    return (label, provider, value)
    return None


# --------------------------------------------------------------------------- providers

def gemini_image(prompt: str, key: str) -> bytes:
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"x-goog-api-key": key, "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read())
    for cand in body.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            data = (part.get("inlineData") or part.get("inline_data") or {}).get("data")
            if data:
                return base64.b64decode(data)
    raise RuntimeError("Gemini returned no image part")


def xai_image(prompt: str, key: str) -> bytes:
    req = urllib.request.Request(
        "https://api.x.ai/v1/images/generations",
        data=json.dumps({"model": XAI_MODEL, "prompt": prompt,
                         "response_format": "b64_json", "n": 1}).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        body = json.loads(resp.read())
    for item in body.get("data") or []:
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
    raise RuntimeError("xAI returned no image data")


PROVIDERS = {"gemini": gemini_image, "xai": xai_image}


# --------------------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="only this product")
    ap.add_argument("--style", help="only this image style")
    ap.add_argument("--force", action="store_true", help="regenerate files that exist")
    ap.add_argument("--dry-run", action="store_true", help="print prompts, generate nothing")
    ap.add_argument("--check", action="store_true", help="report key and plan, then stop")
    args = ap.parse_args(argv)

    wanted = [(s, st, n) for s, st, n in plan()
              if (not args.slug or s == args.slug) and (not args.style or st == args.style)]
    if not wanted:
        print("nothing matched --slug/--style")
        return 2

    found = find_key()
    if args.check or args.dry_run:
        labels = ", ".join(lbl for lbl, _ in KEY_LABELS)
        # Label and pass/fail only. Never a length that could narrow a value, never a value.
        print(f"key file      : {'present' if KEY_FILE.exists() else 'absent'} "
              f"(../key.txt, never committed)")
        print(f"usable key    : {found[0] + ' -> ' + found[1] if found else 'none of ' + labels}")
        print(f"output        : {OUT_DIR.relative_to(config.REPO_ROOT)}")
        print(f"would produce : {len(wanted)} image(s)\n")
        for slug, style, name in wanted:
            exists = (OUT_DIR / f"{slug}-{style}.png").exists()
            print(f"  {slug:<16} {style:<20} {'(have)' if exists else '(missing)'}")
            if args.dry_run:
                print(f"      {prompt_for(slug, style, name)}\n")
        return 0 if found else 3

    if not found:
        labels = ", ".join(lbl for lbl, _ in KEY_LABELS)
        sys.stderr.write(
            f"no usable key. Looked for {labels} in {KEY_FILE.name} beside the repo.\n"
            f"This script is meant to run where that file lives -- a workstation, or CI "
            f"with the key as a secret. It never travels with the repo.\n")
        return 3

    label, provider, key = found
    generate = PROVIDERS[provider]
    print(f"using {label} -> {provider}, writing to "
          f"{OUT_DIR.relative_to(config.REPO_ROOT)}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    made = skipped = failed = 0
    for slug, style, name in wanted:
        dest = OUT_DIR / f"{slug}-{style}.png"
        if dest.exists() and not args.force:
            skipped += 1
            print(f"  {slug:<16} {style:<20} have it already (--force to redo)")
            continue
        try:
            dest.write_bytes(generate(prompt_for(slug, style, name), key))
            made += 1
            print(f"  {slug:<16} {style:<20} wrote {dest.name}")
        except (urllib.error.URLError, RuntimeError, ValueError) as exc:
            failed += 1
            # Type and status only. An API error body can echo the request, so it is never
            # printed here -- CLAUDE.md's hard rule covers API responses, not just keys.
            status = getattr(exc, "code", None)
            print(f"  {slug:<16} {style:<20} FAILED "
                  f"({type(exc).__name__}{f' {status}' if status else ''})")

    print(f"\n{made} generated, {skipped} already present, {failed} failed")
    if made:
        print("Review every file before committing. Nothing here is verified by a test: a "
              "guard can read copy, but only a person can see a parcel in the corner of a "
              "photograph.")
    return 0 if (made or skipped) else 2


if __name__ == "__main__":
    sys.exit(main())
