# Creative style

How every image and every video is made. The generator renders the static set automatically
from `../creative/ad-templates/`; this page is the standard it renders to and the standard a
human shooting real footage has to match.

## The one rule everything else serves

**Show the object, in the world, at the size a person actually holds it.**

The category's default is a product floating on white. That works for a catalogue and it is
the least persuasive thing a small printer can do, because the whole argument is that the
thing is real. A card in a hand beats a card on white. A banner on a railing beats a banner
on a render. Product-on-white is still in the rotation, but it is the supporting shot, never
the hero.

## Static: the five image styles

Each product in `../config/products.yml` declares which of these it can use, and the ad
generator picks per variant.

| Style | What it is | Best rung | Shot notes |
|---|---|---|---|
| `in_hand` | The item held, single hand, natural skin, no manicure | identity, story | Eye-level, 35-50mm equivalent. Fingers touching the edge so the stock thickness reads. |
| `lifestyle_in_context` | The item where it lives: a counter, a railing, a window | purpose, story | Shoot the real premises. A generic studio "shop" reads as fake in about half a second. |
| `install_shot` | Signage or banner as installed, wide enough to show the site | proof | Include something that gives scale: a door, a person, a parked car. |
| `before_after` | The faded old thing, then the new thing, same framing | proof | Same camera position, same time of day. If you cannot match the light, do not run it. |
| `product_on_white` | Clean catalogue shot | purpose | Only as the supporting image. Never the hero. |
| `stack_macro` / `detail_macro` | Edge-on stack, die-cut edge, embroidery stitch | proof, identity | Shallow depth. This is the shot that sells stock weight, and it is the one nobody takes. |
| `unboxing` | Packaging opened, contents visible | story, identity | Hands in shot. Motion blur is fine and reads as real. |
| `flat_lay` | Arranged set, top-down | purpose | Leave more space than feels comfortable. |
| `worn_in_context` | Apparel on a real person at work | identity | Staff, not models, wherever possible. |

### Layout rules for the generated cards

Enforced by `../creative/ad-templates/base.html.j2`:

- 4px signature gradient rule across the top. It is the only place the gradient appears.
- Logo and an uppercase product kicker top-left, always in that order.
- Headline centred vertically, one word in `print-orange`, never two.
- Proof cards get a `print-blue-bright` left rule. Proof is never orange.
- Footer carries the qualifier (turnaround, or the offer with its exclusions) bottom-left;
  the CTA sits bottom-right.
- Type scales with headline length rather than the sentence being cut. Losing a line's
  payoff word costs more than losing four points of type.
- Body type never below 32px on a 1080 canvas.

### Ratios

Every variant renders at 1:1, 4:5 and 9:16. 4:5 is the feed workhorse, 9:16 is stories and
reels, 1:1 is the fallback and the one used for the Meta upload. 16:9 is available for
YouTube pre-roll and is not rendered by default.

## Video

Nine to fifteen seconds. Shot vertical, 9:16, and cropped down rather than the reverse.

**The shape, every time:**

| Seconds | What happens |
|---|---|
| 0.0 - 1.5 | The hook line, on screen, in the brand card style. Spoken if there is a voice. No logo yet. |
| 1.5 - 3.0 | The object appears. Hands, real premises, real light. |
| 3.0 - 9.0 | One point, demonstrated rather than stated. The thing being made, held, installed, compared. |
| 9.0 - 12.0 | The qualifier: turnaround, price, or the offer with its exclusions. |
| 12.0 - 14.0 | Logo and one CTA. First and only appearance of the logo. |

Rules:

- **Hold the logo to the end.** A logo in the first second is the cheapest way to be scrolled past.
- **Caption everything.** Assume no sound. Burnt-in captions, not platform auto-captions, which
  break on product names and get the stock weights wrong.
- **One point per video.** If it needs two, it is two videos.
- **Real audio or no audio.** The press running, paper being handled, a door opening. Licensed
  music underneath at low level is fine; a trending track we have no licence for is not.
- **No stock footage of "small business owners".** We have real customers. Use them, with the
  permission record on file per `compliance.md` #5.
- **Shoot 20% wider than the crop you want** so the same take cuts to 9:16, 4:5 and 1:1.

## The Meaning asset

Once a year, in the window `../calendar/annual.yml` reserves for it, one film that carries no
offer, no percentage, no deadline and no CTA beyond the report it accompanies. Longer than
fifteen seconds. Shot properly. It exists to be remembered rather than to convert, and the
generator is structurally incapable of attaching an offer to anything dated inside that
window.

## What we never do

- No competitor's photograph, layout, or template, ever. Not as a reference board, not
  "for inspiration", not cropped.
- No AI-generated image presented as a photograph of a real customer, a real premises, or a
  real printed job. Generated texture, background and abstract work is fine and is labelled
  as such in the asset filename.
- No stock photo of a person implied to be a customer.
- No screenshot of a review or a message without the permission record behind it.
- No before/after where the "before" was staged to look worse.
