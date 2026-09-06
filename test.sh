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
#
# The list started as the three parse/compile shapes and missed a whole class:
# "Lambda capture ... was freed" fired twice on every run for who knows how
# long, because a lambda that outlives the node it captured is a runtime error,
# not a compile one. That is the deferred-work-outlives-its-screen trap this
# project has hit before, and it was shipping.
ENGINE_ERRORS="SCRIPT ERROR|Parse Error|Compile Error|Lambda capture|Condition \"|USER ERROR|Attempt to call|Invalid access|nonexistent"
if grep -qE "$ENGINE_ERRORS" "$OUT"; then
  echo
  echo "FAIL — engine errors during the run:"
  grep -E "$ENGINE_ERRORS" "$OUT" | sort -u | head -20
  rm -f "$OUT"
  exit 1
fi
rm -f "$OUT"
exit $CODE
