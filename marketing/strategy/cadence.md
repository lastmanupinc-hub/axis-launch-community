# The cadence we are borrowing

The category leader in small-business print has run the same annual rhythm for a decade. That
rhythm is the thing worth taking: *when* to push, *when* to go quiet, *when* to lead with a
story instead of a number. The words, pictures, offer names and product photography are ours
and only ours — see `compliance.md`, which is a hard gate in the build scripts, not advice.

## What the research actually established

Evidence grades below are carried from the source research so that nobody later mistakes a
coupon-aggregator estimate for a filing.

- **[Documented]** — primary source: press release, trade press, the company's own newsroom.
- **[Reported]** — single secondary source, usually a coupon aggregator with an affiliate
  incentive. Directionally useful, not audit-grade.
- **[Inferred]** — our reading. Not established. Never repeat as fact.

### The findings we built on

| Finding | Grade |
|---|---|
| January and February together carry more than a third of the year's promotional launches | [Reported] |
| National Small Business Week (late Apr / early May) is a **research and earned-media** beat, not a discount beat — an annual SMB survey report has anchored it for ten years | [Documented] |
| June is events, weddings and graduations, with invitations discounted hardest | [Reported] |
| Summer runs **category-laddered** pop-ups — a different percentage per category, set by margin, rather than one sitewide number | [Reported] |
| Q4 peaks at the deepest discounts of the year, with *daily rotating* deals through the peak week | [Reported] |
| Always-on spine: a first-order offer with no minimum, a lower email-signup offer, free shipping above a threshold, a tiered spend ladder, and **free physical sample kits as the top-of-funnel lead magnet** | [Documented] for samples, [Reported] for the numbers |
| Email runs near-daily — roughly six sends a week, heaviest on Saturday, mostly early evening | [Reported] |
| Creative is split into **"Meaning"** (one emotional brand film a year, no offer in it at all) and **"Moment"** (a large modular library that recombines per placement and per customer) | [Documented] |
| Their 2015 brand film was explicitly the first in company history to carry no offer or discount messaging | [Documented] |
| Business cards are the acquisition anchor; signage, apparel, promotional products and packaging are where the growth is | [Reported] |

### What the research did *not* establish

Do not let these into a deck as researched facts: their Meta and Instagram creative specifics,
Google Shopping strategy, video-versus-static ratio, aspect ratios, hook formulas,
abandoned-cart and welcome-series mechanics, any back-to-school activity, and speed or quality
guarantees as campaign-level pillars. The Meta Ad Library would close most of that gap and was
unreachable from this environment.

## The structural idea worth stealing

Not a slogan — an architecture. They split creative in two:

**Meaning** is one emotional, offer-free brand asset per year. It exists to be remembered, and
it deliberately does not sell anything.

**Moment** is a large library of modular components — headline variants, tone variants, product
image styles — that get assembled into placement-specific units automatically, so there is
always a relevant unit for a given customer at the point of intent.

That is exactly what this repo is. `config/hooks.yml` is the headline and tone library,
`config/products.yml` is the product and offer library, `strategy/value-ladder.md` supplies the
tone axis, and `scripts/build_ads.py` is the assembler. Six units a day, recombined, none of
them hand-designed.

Our Meaning asset is one film a year, offer-free, and the calendar reserves it for the National
Small Business Week window — the one moment in the year when the whole category stops
discounting and starts talking about the customer.

## Our annual calendar

Same rhythm, our own products, our own numbers, our own scale. Machine-readable in
`../calendar/annual.yml`; this is the reasoning behind it.

| Window | Posture | What runs | Discount weight |
|---|---|---|---|
| **Jan 2 – Feb 28** | Heaviest of the year | New year, new signage. Rebrand-your-shop bundles. Semi-annual sale. | High |
| **Mar 1 – Apr 20** | Quiet, build | Education and proof. How-to-print-well content. Sample kits pushed hard. | Low |
| **Apr 21 – May 10** | **Meaning window** | Our annual customer report + the one offer-free brand film. Real customers, named, with their permission on file. | **None** |
| **May 11 – Jun 30** | Events season | Weddings, graduations, markets, fairs. Invitations and banners lead. | Medium, category-scoped |
| **Jul 1 – Aug 31** | Category ladder | Pop-up sales with a different percentage per category, set by margin. Never one sitewide number. | Medium, staggered |
| **Sep 1 – Oct 31** | Ramp | Autumn trading, holiday cards and calendars seeded early. | Medium, rising |
| **Nov 1 – Nov 24** | Teaser | Pre-peak warm-up, one step below the peak number. | Medium-high |
| **Nov 25 – Dec 2** | Peak | The year's deepest offer, with a genuinely different deal each day. Small Business Saturday gets its own signage-and-postcard angle. | Highest |
| **Dec 3 – Dec 24** | Deadline | Gifting, then hard shipping-deadline urgency, which is the one honest countdown we own. Seed the January offer into every Q4 touchpoint. | High, then none |
| **Dec 25 – Jan 1** | Dark | Nothing sells. One thank-you, no offer. | None |

### The always-on spine

Runs underneath every window, never announced as a sale:

1. **First-order offer**, no minimum. The acquisition workhorse.
2. **Email signup offer**, deliberately *lower* than the first-order offer. Two-step ladder:
   the smaller number buys the address, the bigger number buys the order.
3. **Free shipping above a threshold**, calculated after discounts.
4. **A tiered spend ladder** in flat dollars, with the top tier the aggressive one.
5. **Free sample kits.** The most underrated mechanic in the whole research: a physical lead
   magnet that is also a direct-mail touch into the prospect's premises, and the single
   strongest proof asset a printer has. You cannot argue with paper someone is holding.
6. **Reorder prompts showing the customer's own previous job.** Documented as one of the
   category's highest-performing tactics. Cheap, warm, and almost nobody small does it.

### Where we deliberately diverge

Copying the rhythm does not mean copying the posture. Four deliberate differences:

1. **No absolute discount claims.** They are being sued over subject lines of the "X% off
   everything" shape where the exclusions only appear after opening. Our subject lines carry
   the exclusion or they do not carry the number. `compliance.md` enforces this.
2. **No urgency we cannot evidence.** Same lawsuit alleges sales described as ending that were
   not ending. Every countdown we run maps to a real press cutoff or a real calendar date, and
   the generator records which.
3. **Proof floor.** Their mix can run heavily promotional. Ours cannot: at least a fifth of
   every day's output has to be evidence, and the build fails if it is not.
4. **Smaller, nearer, named.** They advertise to a national average. We can put a real local
   customer's name and street in an ad, which is a thing their scale forbids. That is our only
   structural advantage and the calendar spends it every week.

## Email frequency

The research puts the category leader at roughly six sends a week. A daily newsletter sits
inside that norm, but only if most days earn the send. The rule that keeps it honest lives in
`../README.md`: a day with nothing to say sends the short edition, and a day with genuinely
nothing to say does not send at all. The build supports both and defaults to holding rather
than padding.
