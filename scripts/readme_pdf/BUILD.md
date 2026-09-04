# Building `b24bb1029_ControlPlane_README.pdf`

The submission README PDF. Source is `readme.html` plus the five print plates; the
content is the same claims as `README.md`, reordered into the section order of the
README template supplied with the challenge brief (Introduction → Table of contents
→ Requirements → Installation → Configuration, then this project's supplementary
sections, then the optional Troubleshooting / FAQ / Maintainers).

## Render

```sh
weasyprint -e utf-8 readme.html ../../submission/b24bb1029_ControlPlane_README.pdf
```

WeasyPrint, not headless chromium: the page furniture (running header, `page N / M`
footer) is `@page` margin boxes, which chromium's print path ignores. Verified on
WeasyPrint 69.0 → 34 pages, A4. The one warning it emits (`word-break: break-word`
ignored) is cosmetic and applies only to long tokens inside `<pre>`.

## Plates

`dia/*.mmd` are print-specific redraws of the `docs/diagrams/` sources — narrower and
shallower, because a diagram that fits an A4 text column at a legible label size is a
different diagram from one that fits a browser. Render and measure with:

```sh
PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium mmdc -i dia/p3-engine.mmd -o p3-engine.png -s 3 -b white
python3 measure.py                      # on-page mm + label pt, per plate
```

`measure.py` exists because eyeballing this does not work. The plate CSS caps art at
174 × 228 mm, and every plate must clear an **8 pt on-page label floor** at that cap;
the shipped five measure 8.16–10.49 pt. The binding constraint is *height*, not width:
mermaid wraps labels at a fixed width, so longer label text stacks into more lines and
makes a plate taller rather than wider. Reducing the number of ranks is the only lever
that reliably works — rewording is not.
