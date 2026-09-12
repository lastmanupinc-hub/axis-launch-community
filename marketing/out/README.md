# Generated output

Everything here is written by the build, not by hand. It is committed rather than ignored
because two files in it are **state the system depends on**:

| File | Carries |
|---|---|
| `.published-index.json` | What the newsletter has already sent, so tomorrow's issue does not repeat it, and what the next issue number is. |
| `.hook-rotation.json` | Which ad lines have run in the last 21 days, so the feed does not repeat itself. |

Both daily workflows commit this directory at the end of a run. That commit is how the state
travels from one run to the next; a CI runner keeps nothing of its own. Deleting either file
resets that memory, which means a few days of repeated content rather than anything broken.

The rest is the archive: one directory per day under `newsletter/` and `ads/`, holding the
rendered issue, the ad set, the bulk-upload CSVs, and the creative PNGs.

This directory starts empty. To see what a day looks like, build one:

```bash
python3 marketing/scripts/build_ads.py --date 2026-09-12
python3 marketing/scripts/render_creative.py --date 2026-09-12
```
