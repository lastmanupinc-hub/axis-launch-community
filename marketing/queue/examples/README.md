# Example queue items

Three worked examples of the front-matter format, one per section. They live here rather
than in `../` so the builder does not pick them up and publish them.

To try the newsletter end to end with content in it:

```bash
cp marketing/queue/examples/*.md marketing/queue/
PMD_POSTAL_ADDRESS="..." python3 marketing/scripts/build_newsletter.py --offline
```

The build retires whatever it publishes into `../published/`, so re-running after a
successful build correctly produces a hold.
