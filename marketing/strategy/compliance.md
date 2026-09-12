# Compliance guardrails

These are enforced in code, not trusted to judgement. `scripts/lib/guards.py` implements every
rule on this page and both daily workflows fail closed when a rule trips. If you need to change
a rule, change it here and in `guards.py` in the same commit.

## 1. Following a cadence is legal. Copying creative is not.

What we take from the category leader is **timing and structure**: when to discount, when to go
quiet, when to lead with a story. Timing is not protectable.

What we never take:

| Never | Why |
|---|---|
| Their photography, illustration, video, or any frame of it | Copyright |
| Their layouts and template designs | Copyright / trade dress |
| Their slogans, campaign names, or offer names | Trademark |
| Their product descriptions or body copy, reworded or not | Copyright; rewording a sentence is still a derivative of it |
| Their brand name in any paid creative | Comparative-advertising exposure with no upside at our size |
| Their research figures presented as ours | Plain misrepresentation |

Citing a published industry statistic with attribution is fine and we do it. Presenting someone
else's survey as our own finding is not.

**Enforced:** `guards.py` holds a blocklist of competitor brand names, campaign names and
slogan fragments, and rejects any generated headline, body, subject line or alt text that
contains one. The list lives in `../config/blocklist.yml`.

## 2. Discount claims must carry their exclusions

The category leader is currently defending a class action alleging that subject lines of the
"X% off everything" shape concealed material exclusions until after the open, and that sales
described as ending were not in fact ending. The claims are allegations and unproven. They are
also a precise map of how to get sued, and Washington's CEMA is an active enforcement area with
parallel suits against several large retailers.

So:

- A **percentage or dollar figure in a subject line** must be accompanied by its qualifier in
  the same subject line. "30% off signage" is fine. "30% off everything" is only fine if it is
  literally everything, and it never is.
- The words **everything, storewide, sitewide, all products, no exclusions** are blocked in
  subject lines and ad headlines unless the offer record carries `exclusions: []`. An empty
  exclusion list has to be a deliberate, explicit act.
- Every offer in `../config/products.yml` carries `exclusions`, `starts`, `ends` and
  `evidence`. An offer with no `ends` cannot be rendered with urgency language at all.

**Enforced:** `guards.check_offer_claim()`.

## 3. Urgency must map to a real deadline

Permitted scarcity:

- A press cutoff time we actually operate to.
- A calendar date that exists independently of us: a market date, a postal deadline, a holiday.
- Genuine stock limits on a specific paper or a limited run.
- Real capacity limits on rush slots.

Forbidden:

- Countdowns that reset.
- "Only N left" on anything printed to order.
- A permanent "ending soon".
- A stated end date that the offer then outlives. If an offer is extended, the extension is
  announced as an extension.

**Enforced:** `guards.check_urgency()` requires any asset tagged `ladder: scarcity` to name an
`evidence` key resolving to a dated record in `products.yml`. No evidence, no scarcity.

## 4. Email law

Every send, without exception:

- A real physical postal address in the footer, injected from the environment
  (`PMD_POSTAL_ADDRESS` / `AXIS_POSTAL_ADDRESS`). The build **fails** if the variable is empty —
  it will not substitute a placeholder.
- A working one-click unsubscribe, honoured within ten days and in practice immediately, plus
  `List-Unsubscribe` and `List-Unsubscribe-Post` headers.
- A subject line that describes the actual contents of the email.
- A real from-name and a reply-to that a human reads.
- No sending to an address that has not opted in. No purchased lists, ever, and no
  "we found your business online" scraping.

That covers CAN-SPAM in the US. If a single subscriber is in the EU, UK, or Canada, consent
must be affirmative and logged with a timestamp and source, which is a property of the signup
form, not of this repo — but `send_newsletter.py` refuses to send to any recipient record
missing `consent_source` and `consent_at`.

**Enforced:** `guards.check_send_preconditions()`.

## 5. Testimonials, customers and photographs

- A customer's name, business, logo, or premises appears only with permission recorded in
  `marketing/config/permissions.yml`, with a date and the scope they agreed to.
- Testimonials are quoted as given. We do not tidy grammar in a way that changes meaning, and
  we do not composite several customers into one voice.
- If a result is not typical, the asset says so. FTC endorsement guidance treats an atypical
  result shown without qualification as deceptive.
- Any incentive given for a testimonial is disclosed in the asset itself.
- Stock photography is licensed and the licence is recorded. No AI-generated image is presented
  as a photograph of a real customer, a real premises, or a real printed job.

**Enforced:** `guards.check_attribution()` blocks any asset referencing a `customer_id` with no
current permission record.

## 6. Paid social and search

- Advertiser disclosure and paid-partnership labels are used where the platform requires them.
- Claims about turnaround are tied to the operating record, not to the best day we ever had.
- No targeting that touches a protected category, and no special-category ad configuration
  unless we are running one, which we are not.

## 7. The things this file cannot do

This is an operating standard, not legal advice. Two things should be reviewed by a lawyer
before the first live send: the consent and data-retention posture for any non-US subscriber,
and the exact wording of any guarantee we decide to advertise. Both are cheap to get right
up front and expensive to retrofit.
