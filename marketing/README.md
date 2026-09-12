# Marketing system

A daily newsletter and a daily ad set for **Print My Design**, with the AXIS Launch community
and both sites as content sources. Everything runs on a schedule, everything is generated from
config rather than hand-written, and nothing reaches an inbox or an ad account without passing
a set of compliance guards that are enforced in code.

```
                      calendar/annual.yml  +  calendar/weekly-slots.yml
                                        |
                                   planner.py            "what is today supposed to be?"
                                   /         \
              build_newsletter.py             build_ads.py
                     |                              |
        sources.py (discussions, sites,     hooks.yml x products.yml
         RSS, manual queue)                        |
                     |                        render_creative.py  -> PNG, 3 ratios
              HTML + text + archive                |
                     |                              |
                guards.py  <---- every string ----> guards.py
                     |                              |
             send_newsletter.py             publish_ads.py
              (dry run default)              (dry run default, ads created PAUSED)
```

## Picking this up on a workstation

This system was built by a **cloud session** — an ephemeral container with no `../key.txt`
and a network policy that refuses arbitrary hosts. `config/launch-readiness.detected.yml`
records the result: `ProxyError`. Everything here is written to run where the key and the
network are, and two steps have therefore never actually run:

| Run this | Gets you | Notes |
|---|---|---|
| `python3 marketing/scripts/generate_product_imagery.py` | 18 product photographs the ad creative already asks for | `--check` = plan + key labels, `--dry-run` = the prompts. Spends nothing. |
| `python scripts/fetch_app_articles.py` *(sibling repo `axis-launch-platform`, same branch)* | The newsletter's "In their own words" citations | `--dry-run` doubles as a reachability probe; exit 2 = nothing was reachable |

Neither is required. A missing photograph renders the plain type-on-ink ad; a missing
`app-articles.json` renders an issue with no citation block. **Missing is the designed
state, not a fault** — there is nothing to stub and no placeholder to add.

**Review every generated photograph before committing it.** The prompts ban parcels,
mailers, couriers and delivery, and ban prices, price tags and percentage signs, because
`can_fulfil` and `can_transact` are both false — a photograph of a package makes a delivery
promise as surely as the word does. `tests/test_builders.py` asserts the *prompt* still bans
them, which is all a test can do. Only a person can see a parcel in the corner of a picture.

Full detail: `brand/photography/README.md`, and the module docstring of each script.

## Start here

| You want to | Read |
|---|---|
| Know why the calendar looks like it does | [`strategy/cadence.md`](strategy/cadence.md) |
| Know why the daily send is Print My Design, not AXIS Launch | [`strategy/newsletter-cadence.md`](strategy/newsletter-cadence.md) |
| Know what the product can and cannot honour | [`config/launch-readiness.yml`](config/launch-readiness.yml) |
| Know what still needs a human | [`strategy/autonomy.md`](strategy/autonomy.md) |
| Know what we are and are not allowed to say | [`strategy/compliance.md`](strategy/compliance.md) |
| Understand the tone system | [`strategy/value-ladder.md`](strategy/value-ladder.md) |
| Write or edit a hook | [`config/hooks.yml`](config/hooks.yml) |
| Change prices, products or offers | [`config/products.yml`](config/products.yml) |
| Shoot something | [`strategy/creative-style.md`](strategy/creative-style.md) |
| Use the logo or the colours | [`brand/print-my-design.md`](brand/print-my-design.md) |

## Run it locally

```bash
pip install -r marketing/requirements.txt

# what is today, and what would go out
python3 marketing/scripts/build_ads.py --days 7 --check

# build a real ad set, then render the images
python3 marketing/scripts/build_ads.py --date 2026-09-12
python3 marketing/scripts/render_creative.py --date 2026-09-12

# build a newsletter (--offline skips the network sources)
export PMD_POSTAL_ADDRESS="Print My Design, <real street address>"
cp marketing/queue/examples/*.md marketing/queue/      # give it something to say
python3 marketing/scripts/build_newsletter.py --offline

# dry runs. Neither sends anything without --live.
python3 marketing/scripts/send_newsletter.py --date 2026-09-12
python3 marketing/scripts/publish_ads.py   --date 2026-09-12

# the whole test suite
for t in guards sources config calendar; do python3 marketing/tests/test_$t.py; done
```

## The schedule

| Workflow | When | What it does |
|---|---|---|
| `daily-newsletter.yml` | 11:12 UTC daily | Builds the issue, commits the archive, uploads an artifact, then dispatches via the `newsletter-send` environment. |
| `daily-ads.yml` | 12:07 UTC daily | Builds the ad set, renders creative at three ratios, commits both, then offers them via the `ads-publish` environment. |
| `marketing-ci.yml` | every PR | Runs all 155 tests plus a 14-day ad build and an offline newsletter build. |

### Two independent safety switches

Neither daily job can send or spend until **both** are deliberately turned on:

1. **The environment gate.** `newsletter-send` and `ads-publish` are GitHub environments. Add
   required reviewers to either one in repo settings and every run waits for a human click.
2. **The live variable.** `NEWSLETTER_LIVE` and `ADS_LIVE` must be the literal string `true`
   in repository variables. Anything else and the job completes as a dry run.

Ads are created **PAUSED** even on a live publish. Turning spend on is a human action in Ads
Manager and there is no flag that changes that.

## The catalogue is generated, not maintained

`config/products.yml` is a **generated file**. The catalogue is an active workstream in the
product repo, so a hand-written copy here would go stale without anyone noticing until an ad
linked to a product that no longer exists.

```bash
# regenerate from the storefront's own catalogue
python3 marketing/scripts/import_catalogue.py --pmd-repo /path/to/PMD-MASTER

# fail if the catalogue has moved and this has not been regenerated
python3 marketing/scripts/import_catalogue.py --pmd-repo /path/to/PMD-MASTER --check
```

What you edit is `config/products.overrides.yml`: the short name, role, keywords, image
styles and talking points per product, plus the whole offers, seasonal_offers, evidence and
not_built blocks. Everything else is overwritten on every import. Add a product key to the
overrides *before* it appears in the catalogue and its copy is ready the day it ships.

When a new product arrives with no copy yet, the importer says so and fills sensible defaults
rather than dropping it. `test_importer.py` fails if any generated product has no override
entry, so the gap cannot pass unnoticed.

**Printful is where the catalogue is heading.** The product repo wired it because its v1
catalog needs no authentication and returns real, flat-rate prices, which makes a price
cost-justified rather than a placeholder. The importer already reads a Printful export
(`--printful`) and marks those prices `vendor_quoted`. Flat-rate also decides what may be
said: it is the one case where multiplying a stated price by a quantity is arithmetic rather
than a guess. Everywhere else, never advertise a per-unit price at a quantity and never imply
a volume discount - the product repo's own note puts the real drop at 3.3x between 50 and 500.

## Configuration

Repository **secrets**:

| Secret | For |
|---|---|
| `PMD_POSTAL_ADDRESS` | CAN-SPAM footer. The build fails if it is empty; it will not substitute a placeholder. |
| `BUTTONDOWN_API_KEY` / `RESEND_API_KEY` + `RESEND_AUDIENCE_ID` / `MAILCHIMP_API_KEY` + `MAILCHIMP_LIST_ID` | Whichever provider you use |
| `META_AD_ACCOUNT_ID`, `META_ACCESS_TOKEN`, `META_PAGE_ID`, `META_AD_SET_ID` | Meta publishing |

Repository **variables**:

| Variable | Default | Notes |
|---|---|---|
| `NEWSLETTER_PROVIDER` | `buttondown` | `buttondown`, `resend` or `mailchimp` |
| `NEWSLETTER_LIVE` | unset | `true` to actually send |
| `ADS_LIVE` | unset | `true` to actually create paused ads |
| `ASSET_BASE_URL` | brand site `/email-assets` | Where the email images are hosted. Email cannot render SVG, so the PNGs in `brand/logo/png/` need to live at a public URL. |
| `UNSUBSCRIBE_URL`, `PREFERENCES_URL` | brand site paths | Real endpoints, not placeholders |

## Before anything goes live

The catalogue and the site paths are now read from source, not guessed:
`config/products.yml` holds the six products the storefront actually renders, and
`config/brands.yml` holds the real routes for both sites. What remains is not configuration.

### Two blockers that no setting can work around

1. **Print My Design cannot take money.** Checkout exposes estimate, coupon-validation and
   finalize. Finalize creates an order and returns totals; there is no payment intent, no
   capture, no webhook, and no `core/ecommerce/payments/` at all. Every order placed today is
   free. `guards.check_can_spend()` therefore blocks all paid advertising, and
   `publish_ads.py` refuses. Flip `can_transact` in `config/launch-readiness.yml` when that
   is actually true — not before.
2. **There is no email capture on the site.** No newsletter route, no signup endpoint, no
   list. `guards.check_can_send()` blocks the dispatch. The daily build still runs and still
   commits the archive; it just has nobody to send to. See
   `strategy/newsletter-cadence.md`.

Nothing can ship either — the renderer throws by design and no vendor order adapter exists —
which is why every product's `turnaround` is null and every delivery phrase is a build
failure.

### Then, in order

3. **Reconcile the six prices.** They are hardcoded UI literals
   (`price_basis: ui_placeholder`), never checked against the server's own rule of
   `max(marketReference, vendorCost x 1.06)`. Nothing guarantees $19.99 clears cost plus
   margin. Flip `has_price_confidence` once a real vendor quote backs each one.
4. **Fix the two false claims on the live storefront.** It advertises "Ships in 3-5 days" and
   a "100% satisfaction guarantee" while nothing can ship and no money is taken. Both are
   recorded in `config/launch-readiness.yml` under `site_claims_to_correct`. This system will
   not repeat them, but it also cannot fix the page.
5. **Set `PMD_POSTAL_ADDRESS`** to a real address. Nothing sends without it, by design.
6. **Point `ASSET_BASE_URL`** at wherever you host `brand/logo/png/email-header@2x.png`.
7. **Vendor the brand fonts** into `brand/fonts/` as `.woff2`. Without them the creative
   renderer falls back to a system sans and says so; fine for proofing, not for anything live.
8. **Confirm the consent posture** for any non-US subscriber, and get a lawyer's eye on any
   guarantee you plan to advertise. `strategy/compliance.md` section 7 says why.

Not on this list on purpose: the logo and the live site disagree on wordmark and accent
colour. The product team is prioritising the catalogue over the theme, which is the right
order, so this system follows the supplied asset and does not wait. See
`brand/print-my-design.md`, "The identity question, deferred".

### What can run today, honestly

M1 is reached: the storefront is up and the editor works. So the one true ask is "open the
editor and make something" — no price, no deadline, no delivery. That is what the generator
now produces, and `config/launch-readiness.yml` lists it as the permitted ask alongside the
channels it is permitted on (organic, content, email to people who already asked). Paid
spend is not on that list.

## Editorial rules the code enforces

- **A thin day sends the short edition. An empty day holds.** A held send exits 0; it is not a
  failure. Padding a daily newsletter is how a daily newsletter dies.
- **Proof never drops below 20% of a day's ads. Scarcity never exceeds 33%.** The build fails
  if either is breached. The failure mode this prevents is silent: a feed slides into
  all-discount over about three weeks and nobody notices until the numbers move.
- **A number in a subject line travels with its qualifier.** See `compliance.md` §2 and the
  litigation it cites.
- **Urgency requires a dated, evidenced deadline.** If the day has no dated offer, the
  generator removes the scarcity slot entirely rather than implying a deadline that does
  not exist.
- **No offer of any kind inside the meaning window.** One stretch a year, structurally
  offer-free.
- **A named customer requires a permission record** in `config/permissions.yml`.

## Growing the library

`config/hooks.yml` holds 40 patterns across five families, with 80 concrete lines. At six ads
a day that is roughly a fortnight before a line repeats, and the generator reports it: every
ad set carries a `diversity` block saying whether every line was unseen in the last 21 days.

When it starts reporting reuse, add fills rather than patterns — a new line under an existing
technique is cheaper to write and rotates just as well. Keep the `ladder` tag honest; it is
what the proof floor and scarcity ceiling are computed from.

## What this system is not

It does not buy media, set budgets, or manage bids. It does not decide who to target. It
writes the day's copy, renders the day's images, and puts both in front of a person who can
approve them in one click. The judgement stays human on purpose.
