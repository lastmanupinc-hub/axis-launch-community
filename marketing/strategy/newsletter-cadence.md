# The cadence conflict, and how this system resolves it

There is a direct conflict between what was asked for and a commitment the platform has
already made in writing. It is resolved here deliberately rather than silently, because the
resolution changes what gets sent and to whom.

## The conflict

**The ask:** a daily newsletter publishing updates on the seeded content and the sites.

**The existing commitment:** `axis-launch-platform/channel-rulebook.md` states, as the first
line of its first section:

> **Newsletter (the primary distribution channel — replaces upvote ranking, Root Design v2 D1)**
> **Cadence:** weekly, Monday, aligned with the launch batch going live.

and opens the file with:

> Cadences are commitments — publish them and keep them.

It also fixes the structure: this week's launches, one line each → one featured deep-dive
picked from last week's click data → active auctions as anonymized cards → one M&A education
link. And the tool: Squarespace Email Campaigns at launch, revisiting the provider at around
two thousand subscribers.

Publishing a *daily* AXIS Launch newsletter would break a stated commitment, abandon a
structure tied to a weekly launch batch, and quadruple the send rate on a list built on the
promise of a Monday email.

## The resolution

**They are two different newsletters, and this system only owns one of them.**

| | AXIS Launch newsletter | Print My Design daily |
|---|---|---|
| Owner | the existing commitment in `channel-rulebook.md` | this system |
| Cadence | weekly, Monday, with the launch batch | daily |
| Structure | fixed, as the rulebook specifies | the weekday rotation in `../calendar/weekly-slots.yml` |
| Audience | makers, operators, acquirers | print customers |
| Sender | AXIS Launch | Print My Design |
| Tool | Squarespace Email Campaigns | whatever `NEWSLETTER_PROVIDER` is set to |

The daily send goes out as **Print My Design**. AXIS Launch content rides along in a
community section, and Thursday is the day it leads — but a Print My Design subscriber is
never billed as an AXIS Launch subscriber, and the weekly Monday AXIS email is untouched by
anything in this repo.

If the intent really was to replace the weekly AXIS newsletter with a daily one, that is a
deliberate change to a published commitment and it belongs in `channel-rulebook.md` first.
This system will not make that change by implication.

## What the rulebook gives us for free

Adopted here rather than reinvented, because it is better than what a fresh guess would
produce:

- **Subject lines: concrete, no clickbait.** The rulebook's own example is the standard:
  "6 new AI apps + an $1.8k MRR resume builder for sale". A number, a noun, no adjective.
- **No exclamation marks in product or marketplace copy. One CTA per section.** Already how
  the templates are built.
- **Dates absolute, never "recently".** From `voice-and-tone.md`: pages live for years, so
  "July 2026" and never "last month". The newsletter archive is a permanent page too.
- **Fake scarcity is prohibited** — "countdown timers not tied to a real auction window", in
  `content-constraints.md`. The same rule this system enforces as its scarcity-evidence gate,
  arrived at independently.
- **The lexicon avoid-list** is now in `../config/blocklist.yml` and enforced.
- **AXIS Launch's UTM convention** is in `../config/brands.yml` as `utm_axis`, so links to
  AXIS surfaces land in the same attribution buckets as the rest of the platform.

## The blocker nobody can configure around

Print My Design has **no email capture anywhere on the site**. No newsletter route, no
signup endpoint, no list. An audit of the product repo found no `/subscribe`, no waitlist,
no email-capture handler of any kind.

So there is currently nobody to send a Print My Design daily newsletter to, and
`guards.check_can_send()` blocks the send rather than letting it look configured. The fix is
upstream of this repo: a capture form and a consent record, per `compliance.md` section 4.
Until then the daily build still runs, still produces the issue, still commits the archive —
it just cannot dispatch. That is the right failure: the content pipeline is proved and the
list is the only missing piece.
