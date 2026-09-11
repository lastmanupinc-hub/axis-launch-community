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

## Start here

| You want to | Read |
|---|---|
| Know why the calendar looks like it does | [`strategy/cadence.md`](strategy/cadence.md) |
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
| `marketing-ci.yml` | every PR | Runs all 82 tests plus a 14-day ad build and an offline newsletter build. |

### Two independent safety switches

Neither daily job can send or spend until **both** are deliberately turned on:

1. **The environment gate.** `newsletter-send` and `ads-publish` are GitHub environments. Add
   required reviewers to either one in repo settings and every run waits for a human click.
2. **The live variable.** `NEWSLETTER_LIVE` and `ADS_LIVE` must be the literal string `true`
   in repository variables. Anything else and the job completes as a dry run.

Ads are created **PAUSED** even on a live publish. Turning spend on is a human action in Ads
Manager and there is no flag that changes that.

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

## Before the first live send

These are the things this build could not do for you, in the order they matter.

1. **Verify the catalogue.** `config/products.yml` is schema-correct but its prices, quantities
   and turnarounds are placeholders — the shop was unreachable from the environment this was
   built in. Every product carries `verified: false`, and `publish_ads.py` refuses to publish
   while any product in the day's set is unverified. Fix the numbers, flip the flags.
2. **Check the site paths.** `config/brands.yml` declares the URL structure of both sites
   rather than having discovered it. Correct anything that does not match.
3. **Set `PMD_POSTAL_ADDRESS`** to a real address. Nothing sends without it, by design.
4. **Point `ASSET_BASE_URL`** at wherever you host `brand/logo/png/email-header@2x.png`.
5. **Vendor the brand fonts** into `brand/fonts/` as `.woff2`. Without them the creative
   renderer falls back to a system sans and says so; that is fine for proofing and not fine
   for anything live.
6. **Confirm the consent posture** for any non-US subscriber, and get a lawyer's eye on any
   guarantee you plan to advertise. `strategy/compliance.md` §7 says why.

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
