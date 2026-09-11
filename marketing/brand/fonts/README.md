# Brand fonts

Drop the `.woff2` files here and `render_creative.py` picks them up automatically via
`@font-face`. Expected filenames:

```
Poppins-SemiBold.woff2      # display
Inter-Regular.woff2         # body
```

They are **not** committed (`.gitignore` excludes the binaries) because font licences are
usually per-seat and a public repo is not a seat. Without them the renderer falls back to a
system sans and prints a warning; the daily ads workflow surfaces that warning in its job
summary.
