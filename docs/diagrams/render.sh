#!/usr/bin/env bash
# Render every docs/diagrams/*.mmd to SVG + PNG in docs/diagrams/images/.
#
# The .mmd sources are the authority; images/ is generated output. Edit the source,
# re-run this script, never hand-edit an SVG.
#
# One-time setup:
#   mkdir -p .tools && cd .tools
#   echo '{"name":"cp-diagram-tools","private":true}' > package.json
#   npm install @mermaid-js/mermaid-cli@11.4.2
#
# Note: mermaid-cli 11.x bundles puppeteer-core, which does NOT auto-resolve a
# browser. CP_CHROME must point at a real Chrome/Chromium binary.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

MMDC="${CP_MMDC:-.tools/node_modules/.bin/mmdc}"
CHROME="${CP_CHROME:-/usr/bin/chromium}"
SRC_DIR="docs/diagrams"
OUT_DIR="$SRC_DIR/images"
SCALE="${CP_SCALE:-2}"      # 2x for crisp slides / print
WIDTH="${CP_WIDTH:-1600}"

[ -x "$MMDC" ] || { echo "mmdc not found at $MMDC — see setup above" >&2; exit 1; }
[ -x "$CHROME" ] || { echo "browser not found at $CHROME — set CP_CHROME" >&2; exit 1; }

export PUPPETEER_EXECUTABLE_PATH="$CHROME"
mkdir -p "$OUT_DIR" .tools
PCONF=".tools/puppeteer.json"
[ -f "$PCONF" ] || printf '{ "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"] }\n' > "$PCONF"

failed=0
for src in "$SRC_DIR"/*.mmd; do
  base="$(basename "$src" .mmd)"
  for fmt in svg png; do
    out="$OUT_DIR/${base}.${fmt}"
    if "$MMDC" -i "$src" -o "$out" -p "$PCONF" -b white -s "$SCALE" -w "$WIDTH" \
         >"/tmp/mmdc_${base}_${fmt}.log" 2>&1 && [ -s "$out" ]; then
      printf '  OK   %-40s %6s\n' "${base}.${fmt}" "$(du -h "$out" | cut -f1)"
    else
      printf '  FAIL %-40s (see /tmp/mmdc_%s_%s.log)\n' "${base}.${fmt}" "$base" "$fmt"
      failed=1
    fi
  done
done

[ "$failed" -eq 0 ] || { echo "one or more diagrams failed to render" >&2; exit 1; }
echo "All diagrams rendered to $OUT_DIR"
