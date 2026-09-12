# The value ladder

> The stone never changed. Your want changed.

The reference card puts it in one line: a worthless stone becomes valuable through
**Purpose → Story → Identity → Proof → Scarcity**, and nothing about the stone is different at
the end. Every rung is a different reason to want the same object.

A business card is about six cents of card stock. It sells for forty dollars a box because of
the five rungs, not because of the cardboard. This file is how we climb them on purpose
instead of accidentally living on the bottom one.

## The five rungs, in print

| Rung | The question it answers | What it sounds like for us | What it costs us if we skip it |
|---|---|---|---|
| **Purpose** | What is this *for*? | "A card is the thing you hand someone when the conversation is already going well." | We sell cardstock, and cardstock competes on price forever. |
| **Story** | Where did it come from? | The market stall whose banner said six words and doubled her queue. | The product is interchangeable with any other press. |
| **Identity** | Who does owning this make me? | "A shop that has its act together." Not a hustler, not a hobby. | Nobody upgrades. Everyone buys the cheapest run once. |
| **Proof** | Why should I believe you? | Turnaround we hit, reprints we own, a paper proof before the run. | The first three rungs read as sales talk and collapse. |
| **Scarcity** | Why today? | A real cutoff: the press schedule, the market date, the season. | Everything converts eventually, which means never. |

## Rules of the ladder

**One rung per asset.** An ad that argues purpose *and* proof *and* scarcity argues nothing.
The daily ad set covers several rungs by running several ads, not by cramming.

**You cannot skip to scarcity.** A deadline on a thing nobody has been given a reason to want
is just noise, and it is the single most common failure in small-business advertising. The
generator enforces this: a day's set may not be more than one-third scarcity, and a cold
audience may not be served scarcity at all.

**Proof is load-bearing.** Rungs one to three are claims. Proof is the only rung that makes the
others survive contact with a sceptical reader, which is why proof is always `print-blue` and
never orange, and why every authority hook is required to carry a number.

**Scarcity must be true.** A deadline we invented is a deadline we will be caught inventing.
Acceptable scarcity for us: press cutoff times, seasonal dates that exist anyway (market
season, the holiday post deadline), genuine stock limits on a paper, and capacity on rush
slots. Unacceptable: a countdown that resets, "only 3 left" on a print-to-order product,
permanent "ending soon".

## Mapping to the hook families

`config/hooks.yml` tags every pattern with a `ladder` rung, so the calendar can ask for a rung
and get the right hooks back.

| Rung | Families that climb it best |
|---|---|
| Purpose | controversy, curiosity |
| Story | storytelling |
| Identity | relatability, authority |
| Proof | authority, storytelling (the receipts variants) |
| Scarcity | relatability (deadline variants) |

## The weekly shape

Across a week the set should land roughly:

```
Purpose   ####            ~20%
Story     ######          ~25%
Identity  #####           ~22%
Proof     ######          ~25%   <- never below 20%
Scarcity  ##               ~8%   <- never above 33% in one day
```

`scripts/build_ads.py` computes the realised mix for each day and each trailing week, writes it
into the generated set, and fails the daily job if proof drops under 20% or scarcity runs over
33%. The mix is a hard gate, not a suggestion, because the failure mode is silent: a feed
slides into all-discount over about three weeks and the audience stops reading before anyone
notices the trend in the numbers.
