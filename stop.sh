#!/usr/bin/env bash
# Stop the FitRogue server container. Leaves the reverse proxy alone —
# https://fitrogue.home.kevinhorecka.com will 502 until you ./run.sh again.
set -uo pipefail
cd "$(dirname "$0")"

docker compose down 2>&1 | tail -2

# Older revisions of this project served build/ with a bare `python3 serve.py`.
# Clean that up too if it is still holding the port.
PIDS=$(ss -tlnp 2>/dev/null | grep ":8070 " | grep -oP 'pid=\K[0-9]+' | sort -u || true)
for pid in $PIDS; do
  if ps -p "$pid" -o args= 2>/dev/null | grep -q "serve.py"; then
    kill "$pid" 2>/dev/null && echo "stopped leftover serve.py (pid $pid)"
  fi
done
