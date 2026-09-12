# Manual queue

Drop a markdown file here and it appears in the next issue. This is the escape hatch for
anything the automated sources cannot see.

```markdown
---
title: "Six hundred labels for a bakery that opened on a Tuesday"
brand: print_my_design
url: "https://printmydesign.jonathanarvay.com/blog/bakery-labels"
date: 2026-09-12
section: proof          # proof | writing | community | product | editorial
ladder: proof           # purpose | story | identity | proof | scarcity
customer_id: null       # set this only with a permission record in config/permissions.yml
---

Two sentences is enough. The newsletter renders the first paragraph as the item body and
links the title.
```

Required front matter: `title`, `brand`, `url`. Everything else is optional; `section` and
`ladder` default to the day's lead.

After an item is published the build moves the file to `published/` with the issue date
prepended, so the queue stays a to-do list rather than an archive.

## Worked examples

`examples/` holds three items, one per section, that are not picked up by the builder. To try
the newsletter end to end with content in it:

```bash
cp marketing/queue/examples/*.md marketing/queue/
PMD_POSTAL_ADDRESS="..." python3 marketing/scripts/build_newsletter.py --offline
```

That glob copies exactly the three example items and nothing else, which is why `examples/`
deliberately has no README of its own — one would land here and overwrite this file.

The build retires whatever it publishes into `published/`, so re-running after a successful
build correctly produces a hold.
