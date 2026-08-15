#!/usr/bin/env bash
# Build the FitRogue web client and make sure it is being served.
#
#   ./run.sh              build + content-hash + (re)start the server container
#   ./run.sh --no-build   just make sure the server is up
#
# After the Godot export, the [hash] step below renames every artefact to
# include a hash of its own bytes (index.<hash>.wasm, index.<hash>.pck, ...)
# and rewrites index.html to point at the new names.  nginx (web.conf) then
# serves the hashed files as `immutable, max-age=1y` and index.html as
# `no-cache`, which means:
#
#   * a warm reload costs one conditional request for index.html (a 304, zero
#     bytes) and nothing else — the ~40MB wasm is never re-fetched;
#   * a rebuild still reaches the user: index.html is revalidated on every
#     load, and the new index.html points at new hashed URLs, so exactly the
#     assets whose bytes changed get downloaded.  No manual cache clearing.
#
# The step also writes precompressed .gz/.br siblings (served by
# gzip_static/brotli_static) for anything that compresses meaningfully, and
# deletes artefacts from previous builds.  Compression is skipped when the
# hashed name already exists, so the slow brotli -q11 pass over the wasm is
# paid once per Godot template, not once per build.
#
# build/ is bind-mounted into the container, so a rebuild shows up on a plain
# browser reload — no restart needed.
set -euo pipefail
cd "$(dirname "$0")"

GODOT="${GODOT:-/home/kevin/godot-tools/Godot_v4.7-stable_linux.x86_64}"
PORT=8070
export BROTLI_QUALITY="${BROTLI_QUALITY:-11}"

mkdir -p build
# Without this, Godot's importer treats the *exported* icons/splash in build/ as
# project resources: it re-imports them into .godot/imported and ships them back
# inside index.pck, and every content-hashed rename leaves a dangling .import
# file behind.  build/ is output, never input.
touch build/.gdignore

if [[ "${1:-}" != "--no-build" ]]; then
  echo "[build] exporting web client..."
  # A fresh checkout needs an import pass before the first export.
  "$GODOT" --headless --path . --import >/dev/null 2>&1 || true
  "$GODOT" --headless --path . --export-release "Web" build/index.html
fi

python3 - <<'PY'
"""Content-hash + precompress the Godot web export in build/."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

BUILD = "build"
HTML = os.path.join(BUILD, "index.html")
HASHLEN = 12
# Only keep a .gz/.br sibling if it actually buys something.
MAX_RATIO = 0.90
BR_Q = os.environ.get("BROTLI_QUALITY", "11")

# These four come out of the export template together and reference each other
# through a single `executable` prefix (the audio worklets are fetched as
# "<executable>.audio.worklet.js"), so they must share one hash.
ENGINE = [
    "index.js",
    "index.wasm",
    "index.audio.worklet.js",
    "index.audio.position.worklet.js",
]
# These are addressed individually, so each gets its own hash — which is what
# makes a code-only rebuild leave the 40MB wasm URL untouched.
SOLO = ["index.pck", "index.icon.png", "index.apple-touch-icon.png", "index.png"]
COMPRESSIBLE = (".js", ".wasm", ".pck")

GZIP = ["pigz", "-9", "-c"] if shutil.which("pigz") else ["gzip", "-9", "-c"]


def die(msg):
    sys.exit("[hash] ERROR: %s" % msg)


def digest(paths):
    h = hashlib.sha256()
    for p in paths:
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()[:HASHLEN]


def hashed(name, h):
    return "index.%s%s" % (h, name[len("index"):])


def human(n):
    return "%.1f MB" % (n / 1e6) if n >= 1e6 else "%.0f kB" % (n / 1e3)


if not os.path.exists(os.path.join(BUILD, "index.wasm")):
    print("[hash] build/ is already content-hashed, nothing to do")
    sys.exit(0)
for name in ENGINE:
    if not os.path.exists(os.path.join(BUILD, name)):
        die("expected %s in %s — did the export fail?" % (name, BUILD))

# ---------------------------------------------------------------- hash + rename
engine_hash = digest([os.path.join(BUILD, n) for n in ENGINE])
mapping = {n: hashed(n, engine_hash) for n in ENGINE}
for name in SOLO:
    path = os.path.join(BUILD, name)
    if os.path.exists(path):
        mapping[name] = hashed(name, digest([path]))
if "index.pck" not in mapping:
    die("no index.pck in %s — did the export fail?" % BUILD)

for old, new in sorted(mapping.items()):
    src, dst = os.path.join(BUILD, old), os.path.join(BUILD, new)
    if os.path.exists(dst):
        # Same bytes as the previous build: drop the fresh copy and keep the
        # existing file (and its already-computed .gz/.br) untouched.
        os.remove(src)
    else:
        os.replace(src, dst)
        print("[hash] %-32s -> %s (%s)" % (old, new, human(os.path.getsize(dst))))

# --------------------------------------------------------------- rewrite index.html
with open(HTML, encoding="utf-8") as f:
    html = f.read()

m = re.search(r"const GODOT_CONFIG = (\{.*\});", html)
if not m:
    die("could not find GODOT_CONFIG in %s" % HTML)
cfg = json.loads(m.group(1))
# `executable` is the prefix for the wasm and the audio worklets; `mainPack`
# lets the pck be addressed independently of it.
cfg["executable"] = "index.%s" % engine_hash
cfg["mainPack"] = mapping["index.pck"]
# fileSizes drives the loading bar and is keyed by the exact request path.
cfg["fileSizes"] = {mapping.get(k, k): v for k, v in cfg.get("fileSizes", {}).items()}
html = (
    html[:m.start(1)]
    + json.dumps(cfg, separators=(",", ":"), sort_keys=True)
    + html[m.end(1):]
)
# <script src>, <link href>, splash <img src>.
for old, new in mapping.items():
    html = html.replace('"%s"' % old, '"%s"' % new)

stale = [o for o in mapping if '"%s"' % o in html]
if stale:
    die("index.html still references un-hashed %s" % ", ".join(sorted(stale)))
with open(HTML, "w", encoding="utf-8") as f:
    f.write(html)

# ------------------------------------------------------------------- precompress
def precompress(name):
    path = os.path.join(BUILD, name)
    raw = os.path.getsize(path)
    limit = raw * MAX_RATIO
    for ext, cmd in ((".gz", GZIP), (".br", ["brotli", "-q", BR_Q, "-c"])):
        out = path + ext
        if os.path.exists(out):
            continue
        if shutil.which(cmd[0]) is None:
            print("[gzip] %s not installed, skipping %s" % (cmd[0], ext))
            continue
        if ext == ".br" and not os.path.exists(path + ".gz"):
            # gzip already decided this file is incompressible; do not pay for
            # a brotli -q11 pass over it as well.
            continue
        print("[gzip] %s%s (%s)%s" % (name, ext, cmd[0],
              " — one-time, takes a couple of minutes" if raw > 8e6 else ""))
        tmp = out + ".tmp"
        with open(tmp, "wb") as f:
            subprocess.run(cmd + [path], stdout=f, check=True)
        size = os.path.getsize(tmp)
        if size < limit:
            os.replace(tmp, out)
            print("[gzip]   %s -> %s (%.0f%%)" % (human(raw), human(size), 100.0 * size / raw))
        else:
            os.remove(tmp)
            print("[gzip]   not worth it (%.0f%%), serving %s raw" % (100.0 * size / raw, name))


for name in sorted(mapping.values()):
    if name.endswith(COMPRESSIBLE):
        precompress(name)

# ------------------------------------------------------------- drop stale builds
keep = {"index.html", ".gdignore"}
for new in mapping.values():
    keep |= {new, new + ".gz", new + ".br"}
# Only ever delete things this script itself produced (an artefact from an
# earlier build) or knows to be junk — never an unrecognised file, so that
# turning on e.g. the PWA export does not silently lose its service worker.
hashed_re = re.compile(r"^index\.[0-9a-f]{%d}\." % HASHLEN)
for name in sorted(os.listdir(BUILD)):
    if name in keep:
        continue
    # .import files are leftovers from before build/.gdignore existed.
    if hashed_re.match(name) or name.endswith(".import"):
        os.remove(os.path.join(BUILD, name))
        print("[hash] removed stale %s" % name)
    else:
        print("[hash] leaving unrecognised %s alone (served with no-cache)" % name)

total = sum(os.path.getsize(os.path.join(BUILD, n)) for n in os.listdir(BUILD))
print("[hash] done — build/ is %s on disk" % human(total))
PY

# The PWA files are copied in verbatim after hashing: sw.js and the manifest
# are addressed by fixed name and must stay revalidated (web.conf serves
# anything un-hashed as no-cache), and the icons are referenced by the manifest.
echo "[pwa] copying web/ into build/"
cp -r web/. build/

echo "[serve] ensuring the fitrogue container is up..."
# --force-recreate: web.conf is bind-mounted and only read at startup, and
# `up -d` alone will happily leave a container running against a stale copy.
docker compose up -d --build --force-recreate >/dev/null
sleep 1

LANIP=$(hostname -I | awk '{print $1}')
echo
echo "The Heroes' Journey is live:"
echo "  https://fitrogue.home.kevinhorecka.com:1403   <- public (Google login)"
echo "  http://0.0.0.0:$PORT"
echo "  http://localhost:$PORT"
echo "  http://$LANIP:$PORT                          <- LAN / phone, no login"
echo
echo "stop with: ./stop.sh"
