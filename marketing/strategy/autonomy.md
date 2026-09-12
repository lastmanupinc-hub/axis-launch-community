# Running unattended

The goal is that updating the websites is the only intervention. This page is the honest
accounting of how close that is, what closes the remaining gaps, and what will never close.

## What the system now works out for itself, every day

| Was hand-maintained | Now |
|---|---|
| The product catalogue | Imported from the live shop: `import_catalogue.py --api`. Update the site, the next run picks it up. |
| Prices in ad copy | Quoted at generation time from `/pricing/quote`. The engine applies its own floor and refuses rather than guess; a refusal means the ad carries no price. |
| Whether checkout works | Probed. `probe_capabilities.py` asks for a payment route and records what answered. |
| Whether anything ships | Probed, via the renderer status. |
| Whether there is a list to send to | Probed, via a subscribe route. |
| Whether a price can be trusted | Proved, by a quote coming back. |
| Whether the catalogue is verified | Derived: a catalogue read from the running shop is verified against it by definition; a repo file or a vendor export is not. |

Each of those was a line in a YAML file that was only ever as fresh as somebody's memory.
Each is now a question the system asks the product.

## The safety property that makes it safe to leave alone

**Fail closed, everywhere.** Every unknown resolves to "cannot", never to "probably fine":

- A probe that cannot reach the product reports nothing and the conservative declared
  baseline stands. Blindness reads as *stop*.
- A probe older than 36 hours is not evidence about the product as it is now, and is
  ignored.
- A missing API token means no catalogue, no prices, no capabilities. Not defaults.
- A pricing 422 is the engine correctly refusing to invent a number. It propagates to "no
  price in the ad", not to "use the config literal".
- An empty catalogue import is refused, so a bad token or an unseeded table cannot blank
  the config and take the ads down with it. The previous catalogue stands.
- A catalogue refresh that fails does not fail the daily job. A stale catalogue is worth
  less than a fresh one and far more than no run at all.

The asymmetry is deliberate. A false negative costs a quiet day. A false positive spends
money advertising something that does not work, which is the failure that is expensive and
hard to undo.

## The capability merge, precisely

```
capability is TRUE only when something positively says so

  fresh + reachable probe   ->  wins, in both directions
  unreachable or stale      ->  ignored; the declared baseline applies
  declared baseline         ->  conservative
```

A product that ships checkout flips `can_transact` on with no human edit, and the ads
unblock on the next run. A product that regresses flips it back off the same way. Neither
needs anyone to remember.

## One-time setup, then it runs

These are set once and never again. They are credentials and addresses, not judgement.

| Secret | Without it |
|---|---|
| `PMD_API_TOKEN` | No catalogue refresh, no live prices, no capability probe. The system runs on the declared baseline and spends nothing. |
| `PMD_POSTAL_ADDRESS` | The newsletter cannot send. CAN-SPAM. |
| ESP credentials | The newsletter builds and archives but cannot dispatch. |
| Meta credentials | Ads generate and render but cannot be created, even paused. |

| Variable | Effect |
|---|---|
| `PMD_API_BASE` | Defaults to the brand site plus `/api/v4`. |
| `NEWSLETTER_LIVE`, `ADS_LIVE` | Must be the string `true` before anything leaves. |

## What a human still does, and why that is correct

**1. Approve the first send and the first spend.** Two GitHub environments gate them, and
they can require a reviewer. This is deliberate and should stay: the system is good at
refusing to say false things and has no opinion about whether today is a sensible day to
start spending money.

**2. Write copy for a genuinely new product.** When the catalogue gains something, the
import reports it, generates usable defaults from the product's own description, and keeps
running. The ads are then generic rather than good until somebody adds keywords, talking
points and an image style to `config/products.overrides.yml`. Nothing breaks; the copy is
just worse than it could be. A test fails so the gap cannot pass unnoticed.

**3. Grow the hook library.** Forty patterns and eighty lines is about a fortnight before a
line repeats at six ads a day. Every ad set reports its own diversity, so the system tells
you when it is running thin rather than quietly recycling.

**4. Decide the things that are decisions.** Whether to correct the two false claims on the
storefront. Whether the logo or the site wins. Whether to change a published cadence
commitment. A system that made those calls on its own would be a worse system.

## What would close the remaining automation gaps

In the order they are worth doing:

1. **Seed the catalogue variants table and publish `variant_key` on catalogue products.**
   Today no product carries one, so no product can be quoted, so no ad can carry a price.
   This single field is what turns pricing from a capability into a fact.
2. **A renderer status endpoint.** The probe asks for one; if the product answers, the
   fulfilment gate opens itself.
3. **Payment on the order path.** Opens the spend gate.
4. **An email capture route.** Opens the send gate.

Each is one probe away from being noticed automatically. None needs a change here.

## What this will never do

Set budgets, choose bids, pick audiences, or decide it is time to start spending. It writes
the day's copy from what is true, renders it, refuses what is not true, and hands the result
to someone who can say yes.
