# Print My Design — brand kit

Everything the newsletter and the daily ad set are allowed to look like. If an asset is not
buildable from this page, it does not ship.

## The mark

`logo/print-my-design-mark.svg` — a rounded diamond ring, orange at the upper-left, blue at
the lower-right, with a diamond of negative space punched through the middle. The negative
space is the point: it is a print registration window. Things you make show *through* us.

`logo/print-my-design-mark-mono.svg` — same geometry, `currentColor` fill. Use this any time
the mark sits on a photograph, a product, or a coloured panel. The gradient mark only ever
sits on `ink` or `white`.

| Rule | Value |
|---|---|
| Minimum size | 24 px / 8 mm across the diagonal |
| Clear space | Half the mark's width on every side. Nothing enters it, including page edges. |
| Rotation | Never. The diamond is already rotated; rotating it again makes a square. |
| Recolour | Never on the gradient version. Mono version takes any single brand colour. |
| Effects | No drop shadows, no bevel, no outer glow. The supplied render has an extrude; the flat vector is the real logo. |
| On photography | Mono white, over a scrim of `ink` at 55% or darker. |

## Colour

Full values, roles and contrast maths live in `palette.json`. The short version:

| Token | Hex | Use it for |
|---|---|---|
| `print-orange` | `#F2A93B` | The accent. Highlight words, CTA fills, the 4px top rule. |
| `print-orange-deep` | `#D6862A` | Urgency, deadlines, pressed states, orange text on white. |
| `print-blue` | `#2B66A0` | Proof, verification, links on paper, header type. |
| `print-blue-bright` | `#3C87CE` | Blue on dark grounds. |
| `ink` | `#0E0E10` | The default ad ground. |
| `paper` | `#FAFAF7` | The default email ground. |

Three colour rules that are not negotiable:

1. **Orange never carries proof.** Numbers, receipts, verification badges and testimonials are
   blue. Orange is desire and deadline; blue is evidence. Mixing them makes the evidence look
   like a sales claim.
2. **Orange text never sits on white.** It fails contrast at 1.9:1. On paper, use ink type with
   an orange underline or an orange rule above.
3. **The gradient is for the mark, a hero wash, or a 4px rule.** Never behind body copy, never
   on a button, never as a text fill.

## Type

The supplied logo is set in a geometric sans with a heavy weight on "PRINT" and a light weight
on "MY DESIGN". The rendering stack matches that shape:

```
Display  : Poppins SemiBold 600 / Montserrat 600
Body     : Inter 400-500
Fallback : "Liberation Sans", "DejaVu Sans", Arial, sans-serif
```

Brand fonts are **not** vendored in this repo and are not installed on the CI runner. Drop the
`.woff2` files into `marketing/brand/fonts/` and the creative renderer picks them up
automatically via `@font-face`; without them it falls back to the stack above, which is close
enough for proofing but **not** for anything that goes live. `scripts/render_creative.py`
prints a loud warning when it falls back, and the daily ad workflow surfaces that warning in
its job summary.

Type rules for ad creative:

- One idea per card. If the headline needs a comma to survive, it is two cards.
- Headline 56-72px on a 1080 square. Body no smaller than 32px. Below 32px nobody reads it on
  a phone and the platforms down-rank it.
- Highlight exactly one word per headline in `print-orange`. Two highlights is zero highlights.
- Sentence case for body, title case never. The logo is the only all-caps in the system.

## Voice

Print My Design sells the moment a small thing you made turns into a real object someone holds.
The voice follows from that:

- **Concrete over clever.** "500 cards, on your desk Thursday" beats "elevate your brand".
- **The customer made it, we printed it.** Their name on the work, always. We are the press,
  not the designer, unless they ask us to be.
- **No superlatives we cannot receipt.** "Fastest" needs a number and a date. So does "best".
- **Price is never hidden.** If a post implies a price, the post states the price.
- **One ask per asset.** Every ad ends on one verb.

## The identity question, deferred

The supplied logo and the live site do not agree. **This is deliberately not being resolved
now** - the product team is prioritising the catalogue over the theme, which is the right
call: a catalogue with no products is a broken shop, while two blues is a cosmetic mismatch
on a shop that already works.

Recorded here so the decision is ready when the theme comes up, not so it blocks anything.

| | Supplied brand asset | Live storefront |
|---|---|---|
| Wordmark | PRINT / MY DESIGN | "PMD Print Studio" |
| Accent | orange `#F2A93B` to blue `#2B66A0` gradient | flat `#00BFFF` deep sky blue |
| Mark | rounded diamond ring with a registration window | none |

The storefront's own code is also internally inconsistent: `tailwind.config.js` defines
`pmdBlue: '#00BFFF'` while the button variants in `App.tsx` hardcode `#00A3FF`. Two blues,
neither of them the logo's.

**This system follows the supplied asset**, because that is what was handed over as the brand
and because it is the only one of the three that is a complete identity rather than a colour.
Everything in `palette.json` is sampled from it. But every asset this system produces will
therefore look unlike the site it links to, which is a real inconsistency a visitor will
notice at the click.

Three ways out, for whenever the theme comes up:

1. Bring the site to the logo. One accent token and a wordmark swap; the smallest change that
   makes the two agree.
2. Bring the logo to the site. Recolour the mark to `#00BFFF` and keep "PMD Print Studio".
   Cheap, but it discards the gradient that makes the mark distinctive.
3. Decide they are different brands — "PMD Print Studio" the product, "Print My Design" the
   company. Defensible, and it needs saying out loud, because right now it reads as an

**Meanwhile this system follows the supplied asset and does not wait.** The consequence
to accept knowingly: ad creative will not match the page it links to. At today's spend,
which is zero, that costs nothing. It starts costing something the day paid traffic runs,
which is also the day the catalogue work will have landed, so the sequencing takes care
of itself.

## What we never do

Carried straight into `strategy/compliance.md`, repeated here because it is a brand rule too:
we do not use another printer's photography, layouts, slogans, offer names, or product
descriptions, and we do not name a competitor in paid creative. We study the *rhythm* the
category has already proven; the words and pictures are ours.
