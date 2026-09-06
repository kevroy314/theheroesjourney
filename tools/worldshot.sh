#!/usr/bin/env bash
# One PNG of any rectangle of the overworld, drawn by the game's own renderer.
#
#   ./tools/worldshot.sh X Y W H OUT.png [HOUR] [--no-light]
#   ./tools/worldshot.sh 100 96 70 80 .scratch/town.png 0.45
#
# X Y W H   the rectangle in world cells. It comes out at 32 px per cell, so
#           70x80 cells is a 2240x2560 image.
# HOUR      0..1, midnight to midnight; 0.25 dawn, 0.5 noon, 0.75 dusk.
#           Default 0.5, the one hour at which the ambient ramp writes nothing.
# --no-light  skip the lighting overlay entirely and photograph the raw art.
#
# WHY THIS IS NOT `godot --headless`
#
# It very nearly is, and that is the trap. `--headless` gives Godot the *dummy*
# rendering driver: the scene tree runs, every script behaves, nothing is ever
# drawn, and `SubViewport.get_texture().get_image()` hands back null with one
# line about a null parameter deep in the dummy texture storage. So the shot
# needs a real GL context, and the cheapest real GL context on a build box is a
# throwaway X server with llvmpipe behind it. Xvfb is started here, used, and
# killed; nothing is ever shown on a screen.
set -euo pipefail
cd "$(dirname "$0")/.."

GODOT="${GODOT:-/home/kevin/godot-tools/Godot_v4.7-stable_linux.x86_64}"

if [ "$#" -lt 5 ]; then
  sed -n '2,12p' "$0" | sed 's/^#\( \|$\)//'
  exit 2
fi

X=$1; Y=$2; W=$3; H=$4; OUT=$5
shift 5

# Absolute, because the engine's working directory is not the shell's and a
# relative path would land somewhere nobody was looking for it.
OUT=$(realpath -m "$OUT")
mkdir -p "$(dirname "$OUT")"

# A display nobody else is on. The lock file is what X itself uses to claim a
# number, so testing for it is the same question the server would ask.
DISPLAY_NUM=99
while [ -e "/tmp/.X${DISPLAY_NUM}-lock" ] && [ "$DISPLAY_NUM" -lt 130 ]; do
  DISPLAY_NUM=$((DISPLAY_NUM + 1))
done

# Deliberately not `xvfb-run`: the wrapper shells out to getopt, and on this
# box that is a Windows-PATH getopt built against a newer glibc, so it dies
# before Xvfb is ever started. Owning the server is three lines and no mystery.
Xvfb ":${DISPLAY_NUM}" -screen 0 1280x1024x24 -nolisten tcp >/dev/null 2>&1 &
XVFB_PID=$!
# The shot is short and the trap has to survive a failure, or a killed run
# leaves an X server and its lock file behind for the next one to skip over.
trap 'kill "$XVFB_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 50); do
  [ -e "/tmp/.X${DISPLAY_NUM}-lock" ] && break
  sleep 0.1
done

set +e
# --audio-driver Dummy is not cosmetic. On a box whose ALSA config points at a
# device an Xvfb session has no business opening, the audio driver blocks on
# shutdown and the engine never returns from quit(): the PNG is written and
# the process then sits there until something kills it.
DISPLAY=":${DISPLAY_NUM}" "$GODOT" --path . --rendering-driver opengl3 \
  --audio-driver Dummy \
  -- --worldshot "$X" "$Y" "$W" "$H" "$OUT" "$@" 2>&1 \
  | grep -vE "^(ALSA lib|WARNING: Could not set V-Sync|OpenGL API|Godot Engine| +at: set_use_vsync|$)"
CODE=${PIPESTATUS[0]}
set -e

# The engine can exit 0 having written nothing — a push_error does not fail a
# run — so the file itself is the test.
if [ "$CODE" -ne 0 ] || [ ! -s "$OUT" ]; then
  echo "worldshot: FAILED (exit $CODE, $OUT $( [ -s "$OUT" ] && echo written || echo missing ))" >&2
  exit 1
fi
echo "worldshot: wrote $OUT"
