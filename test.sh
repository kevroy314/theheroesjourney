#!/usr/bin/env bash
# Headless end-to-end check: plays full journeys through the real systems and
# builds every screen. Non-destructive — the save is snapshotted and restored.
set -euo pipefail
cd "$(dirname "$0")"

GODOT="${GODOT:-/home/kevin/godot-tools/Godot_v4.7-stable_linux.x86_64}"
OUT=$(mktemp)
set +e
"$GODOT" --headless --path . -- --selftest 2>&1 | tee "$OUT"
CODE=${PIPESTATUS[0]}
set -e

# An engine-level error never fails an assertion, so it would otherwise scroll
# past unnoticed. Treat any of them as a failing run.
if grep -qE "SCRIPT ERROR|Parse Error|Compile Error" "$OUT"; then
  echo
  echo "FAIL — engine errors during the run:"
  grep -E "SCRIPT ERROR|Parse Error|Compile Error" "$OUT" | sort -u | head -20
  rm -f "$OUT"
  exit 1
fi
rm -f "$OUT"
exit $CODE
