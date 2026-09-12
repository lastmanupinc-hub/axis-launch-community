#!/usr/bin/env python3
"""Render a day's ad set into branded image creative.

Reads marketing/out/ads/<date>/ad-set.json and renders each variant at every ratio the set
asks for, using headless Chromium. Output is PNG, named so the filename alone tells you the
date, variant, ladder rung and ratio.

Brand fonts are not vendored (see brand/print-my-design.md). If they are absent the render
falls back to a system stack and says so loudly - fine for proofing, not for anything live.

Usage:
  python3 marketing/scripts/render_creative.py --date 2026-09-11
  python3 marketing/scripts/render_creative.py --date 2026-09-11 --ratios 1:1
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import config  # noqa: E402

RATIOS = {
    "1:1":  (1080, 1080),
    "4:5":  (1080, 1350),
    "9:16": (1080, 1920),
    "16:9": (1200, 675),
}

CHROMIUM_CANDIDATES = [
    "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    shutil.which("chromium") or "",
    shutil.which("chromium-browser") or "",
    shutil.which("google-chrome") or "",
]


def find_chromium() -> str | None:
    for path in CHROMIUM_CANDIDATES:
        if path and Path(path).exists():
            return path
    return None


def palette() -> dict:
    raw = json.loads((config.BRAND_DIR / "palette.json").read_text(encoding="utf-8"))
    return {
        "orange": raw["core"]["print-orange"]["hex"],
        "orange_deep": raw["core"]["print-orange-deep"]["hex"],
        "blue": raw["core"]["print-blue"]["hex"],
        "blue_bright": raw["core"]["print-blue-bright"]["hex"],
        "ink": raw["neutral"]["ink"]["hex"],
        "slate": raw["neutral"]["slate"]["hex"],
    }


def display_domain(brand_key: str = "print_my_design") -> str:
    """The site address as a person would read it aloud.

    From brands.yml, never a literal here: if the domain moves, the artwork follows the
    same config every link already uses instead of quietly advertising the old address.
    The scheme and any www. come off -- nobody types them and they cost width on a canvas
    where the footnote is already competing for the same row.
    """
    site = config.brand(brand_key)["site"]
    return re.sub(r"^https?://(www\.)?", "", site).rstrip("/")


def fonts_present() -> bool:
    font_dir = config.BRAND_DIR / "fonts"
    return font_dir.exists() and any(font_dir.glob("*.woff2"))


def emphasise(headline: str) -> str:
    """Mark exactly one word in the accent colour.

    brand/print-my-design.md: one highlight per headline, because two highlights is zero.
    Picks the longest meaningful word, which is almost always the load-bearing one.
    """
    escaped = html.escape(headline)
    words = re.findall(r"[A-Za-z][A-Za-z'-]{4,}", escaped)
    stop = {"about", "after", "again", "their", "there", "these", "those", "which",
            "would", "could", "should", "because", "before", "every", "other", "under",
            "where", "while", "your", "yours", "something", "anything", "everything"}
    candidates = [w for w in words if w.lower() not in stop]
    if not candidates:
        return escaped
    target = max(candidates, key=len)
    return re.sub(rf"\b{re.escape(target)}\b", f"<em>{target}</em>", escaped, count=1)


def scale_for(width: int, height: int, headline: str = "") -> dict:
    """Type scale per canvas, responsive to headline length.

    Body never drops below 32px on a 1080: platforms down-rank small type and nobody reads
    it on a phone (brand/print-my-design.md). The headline shrinks instead of the sentence
    being cut - losing a line's payoff word is worse than losing four points of type.
    """
    base = min(width, height)
    n = len(headline or "")
    if n <= 55:
        head_ratio = 0.082
    elif n <= 85:
        head_ratio = 0.068
    elif n <= 115:
        head_ratio = 0.057
    else:
        head_ratio = 0.049
    # Tall canvases have room for a larger headline at the same character count.
    if height > width:
        head_ratio *= 1.08
    return {
        "pad": round(base * 0.085),
        "logo": round(base * 0.085),
        "kicker_px": max(20, round(base * 0.026)),
        "head_px": max(34, round(base * head_ratio)),
        "body_px": max(32, round(base * 0.033)),
        "foot_px": max(20, round(base * 0.024)),
        "cta_px": max(24, round(base * 0.030)),
    }


def render_one(chromium: str, env: Environment, variant: dict, ratio: str,
               out_dir: Path, date: str) -> Path | None:
    width, height = RATIOS[ratio]
    creative = variant["creative"]
    ctx = {
        "p": palette(),
        "w": width, "h": height,
        "template": creative["template"],
        "kicker": creative["kicker"],
        "headline_html": emphasise(creative["headline"]),
        "support": "",
        "footer": creative["footer"],
        "cta": variant["meta"]["cta"],
        "domain": display_domain(),
        "logo_src": (config.BRAND_DIR / "logo" / "print-my-design-mark.svg").as_uri(),
        "font_dir": (config.BRAND_DIR / "fonts").as_uri(),
        **scale_for(width, height, creative["headline"]),
    }
    page = env.get_template("base.html.j2").render(**ctx)

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "creative.html"
        src.write_text(page, encoding="utf-8")
        name = (f"{date}-{variant['id'].rsplit('-', 1)[-1]}-{variant['ladder']}"
                f"-{ratio.replace(':', 'x')}.png")
        dest = out_dir / name
        result = subprocess.run(
            [chromium, "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
             "--allow-file-access-from-files",
             f"--window-size={width},{height}",
             f"--screenshot={dest}", src.as_uri()],
            capture_output=True, timeout=90,
        )
        if not dest.exists():
            sys.stderr.write(f"  render failed for {name}: "
                             f"{result.stderr.decode()[:200]}\n")
            return None
        return dest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="ISO date; defaults to today")
    ap.add_argument("--ratios", help="comma-separated subset, e.g. 1:1,4:5")
    args = ap.parse_args(argv)

    date = args.date or dt.date.today().isoformat()
    set_path = config.OUT_DIR / "ads" / date / "ad-set.json"
    if not set_path.exists():
        print(f"no ad set at {set_path.relative_to(config.REPO_ROOT)}. "
              f"Run build_ads.py --date {date} first.")
        return 1

    chromium = find_chromium()
    if not chromium:
        print("no Chromium binary found; cannot render creative.")
        print("  Looked in: " + ", ".join(c for c in CHROMIUM_CANDIDATES if c))
        return 1

    if not fonts_present():
        print("WARNING: brand fonts are not in marketing/brand/fonts/.")
        print("         Falling back to a system sans. Fine for proofing; do NOT ship")
        print("         these files as live creative. See brand/print-my-design.md.")

    payload = json.loads(set_path.read_text(encoding="utf-8"))
    env = Environment(
        loader=FileSystemLoader(str(config.MARKETING_ROOT / "creative" / "ad-templates")),
        undefined=StrictUndefined, autoescape=False)

    out_dir = set_path.parent / "creative"
    out_dir.mkdir(parents=True, exist_ok=True)

    wanted = ([r.strip() for r in args.ratios.split(",")] if args.ratios else None)
    rendered = 0
    for variant in payload["variants"]:
        for ratio in (wanted or variant["creative"]["ratios"]):
            if ratio not in RATIOS:
                print(f"  unknown ratio {ratio!r}, skipping")
                continue
            path = render_one(chromium, env, variant, ratio, out_dir, date)
            if path:
                rendered += 1
    print(f"rendered {rendered} image(s) to "
          f"{out_dir.relative_to(config.REPO_ROOT)}")
    return 0 if rendered else 1


if __name__ == "__main__":
    raise SystemExit(main())
