# Product photography

`{slug}-{style}.png` — one file per product/style pair the ad builder can ask for.
`generate_product_imagery.py --check` prints the full list and which ones exist.

Empty is the normal state. `build_ads.py` picks an `image_style` for every variant from
`products.overrides.yml`; `render_creative.py` uses the matching file **if it is here** and
otherwise renders the type-on-ink layout. A missing photograph costs a plainer ad, never a
broken one, so there is no placeholder to add and nothing to stub.

## Getting the files

```bash
python3 marketing/scripts/generate_product_imagery.py --check     # keys + what is missing
python3 marketing/scripts/generate_product_imagery.py --dry-run   # read the prompts first
python3 marketing/scripts/generate_product_imagery.py
```

That script needs an image-API key from `../key.txt`, which never travels with the repo, so
it cannot run in the daily job — run it on a workstation, review the output, commit what you
keep.

## Review every file before committing it

The prompts forbid two things for reasons that are not stylistic:

- **No parcels, mailers, couriers, postage or delivery.** `can_fulfil` is false. A photograph
  of a package makes a delivery promise as surely as the word "delivered" does, and no guard
  can read a picture.
- **No prices, price tags, currency symbols, percentage signs or discount stickers.**
  `can_transact` and `has_price_confidence` are both false. The copy refuses to name a
  number; the artwork must not smuggle one in behind it.

A model will occasionally put one in anyway. `test_builders.py` checks that the *prompt*
still bans them, which is all a test can do here — only a person can see a parcel in the
corner of a photograph. That review is the actual gate.

Also: no other printer's layouts, logos or house style in shot
(`brand/print-my-design.md`, "what we never do").

## What the renderer does with them

Full-bleed behind the ad, under a scrim of ink that never goes lighter than 76% where type
sits — the brand floor is 55%, and the extra is what keeps the orange highlight word at
4.6:1 against a near-white photograph instead of 3.1:1. Over a photograph the mark switches
to the mono file, inlined so `currentColor` resolves to white, and the footnote drops
`--slate` (1.19:1 over a photo) for the same light grey the domain uses.
