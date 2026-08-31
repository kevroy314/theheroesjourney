#!/usr/bin/env python3
"""Publish a built Android APK so a sideloaded phone can update itself.

The phone has no app store and cannot log in to Google from a background
download, so over-the-air updates are just two static files served by the same
nginx container that already serves the game:

    releases/releases.json    the index the updater polls, newest first
    releases/HeroesJourney-<version_name>-<version_code>.apk

Both are reached through the home reverse proxy at
`https://fitrogue.home.kevinhorecka.com:1403/releases/...`, on a location that
bypasses oauth2-proxy and authenticates with a shared secret instead — see
`docs/android-release-nginx.conf` and `docs/DEPLOY.md`.

This script is the *only* writer of that directory. It is deliberately
idempotent: publishing the same build twice is a no-op, and republishing a
version that already exists replaces its entry rather than adding a second one,
so an updater can never see two candidates for the same version code.

    python3 tools/publish_release.py \
        --apk android/build/outputs/apk/release/app-release.apk \
        --version-name 0.3.0 --version-code 7 \
        --notes "Overworld walking"

Standard library only, so it can run from a bare build box.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASES = os.path.join(ROOT, "releases")
INDEX = "releases.json"
# Older builds are just disk; the updater only ever wants the newest, and the
# rest are kept solely so a bad release can be rolled back by hand.
KEEP = 5
PREFIX = "HeroesJourney"
# The proxy's location regex only serves names matching this; a version string
# with a space or a slash in it would publish fine here and 404 on the phone.
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def die(msg):
    sys.exit("[release] ERROR: %s" % msg)


def sha256(path):
    """Streamed, because the APK is tens of MB and this may run on a laptop."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def human(n):
    return "%.1f MB" % (n / 1e6) if n >= 1e6 else "%.0f kB" % (n / 1e3)


def load_index(path):
    """Existing entries, tolerating both a bare list and {"releases": [...]}."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, ValueError):
        # A half-written or hand-edited index must not wedge every future
        # publish — the APKs on disk are the real state, so start over.
        print("[release] %s is unreadable; rebuilding it" % path)
        return []
    if isinstance(data, dict):
        data = data.get("releases", [])
    return [e for e in data if isinstance(e, dict) and e.get("file")]


def write_atomic(path, blob):
    """Rename into place: the phone may be reading this file right now."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(blob)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)


def copy_atomic(src, dst):
    tmp = dst + ".tmp"
    shutil.copyfile(src, tmp)
    # nginx runs as its own uid inside the container and the directory is
    # bind-mounted, so the host's permissions are the ones that decide.
    os.chmod(tmp, 0o644)
    os.replace(tmp, dst)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--apk", required=True, help="the signed release APK to publish")
    ap.add_argument("--aab", help="optional AAB, archived beside the APK but never served")
    ap.add_argument("--version-name", required=True, help='e.g. "0.3.0"')
    ap.add_argument("--version-code", required=True, type=int, help="monotonic integer")
    ap.add_argument("--notes", help="release notes; falls back to $RELEASE_NOTES")
    ap.add_argument("--dir", default=RELEASES, help="releases directory (default: %s)" % RELEASES)
    args = ap.parse_args()

    apk = os.path.abspath(args.apk)
    if not os.path.isfile(apk):
        die("no APK at %s — build it first" % apk)
    if os.path.getsize(apk) == 0:
        die("%s is empty" % apk)
    with open(apk, "rb") as f:
        if f.read(2) != b"PK":
            die("%s is not a zip archive — is that really an APK?" % apk)
    if args.aab and not os.path.isfile(args.aab):
        die("--aab given but no file at %s" % args.aab)

    name, code = args.version_name.strip(), args.version_code
    if not SAFE.match(name):
        die("version name %r must be letters, digits, dot, dash or underscore" % name)
    if code <= 0:
        die("version code must be a positive integer, got %d" % code)

    out = os.path.abspath(args.dir)
    os.makedirs(out, mode=0o755, exist_ok=True)
    # Same reason server/ and tools/ carry one: without it Godot scans this
    # directory, imports releases.json as a project resource and packs a 60 MB
    # APK into the pck.
    gdignore = os.path.join(out, ".gdignore")
    if not os.path.exists(gdignore):
        open(gdignore, "w").close()

    filename = "%s-%s-%d.apk" % (PREFIX, name, code)
    dest = os.path.join(out, filename)
    digest = sha256(apk)

    # Re-running with an identical APK must not rewrite the file the phone is
    # mid-download of, so compare before copying.
    if os.path.isfile(dest) and sha256(dest) == digest:
        print("[release] %s is already published, unchanged" % filename)
    else:
        copy_atomic(apk, dest)
    if args.aab:
        copy_atomic(args.aab, os.path.join(out, "%s-%s-%d.aab" % (PREFIX, name, code)))

    index_path = os.path.join(out, INDEX)
    existing = load_index(index_path)
    previous = next((e for e in existing if e.get("version_code") == code), None)

    notes = args.notes if args.notes is not None else os.environ.get("RELEASE_NOTES")
    if notes is None:
        # Republishing without --notes keeps whatever this version already said,
        # rather than silently blanking it.
        notes = (previous or {}).get("notes", "")

    entry = {
        "version_name": name,
        "version_code": code,
        "file": filename,
        "notes": notes.strip(),
        "sha256": digest,
        "size_bytes": os.path.getsize(dest),
        "published_at": int(time.time() * 1000),
    }

    highest = max((int(e.get("version_code", 0) or 0) for e in existing), default=0)
    if code < highest:
        print("[release] WARNING: %d is below the published %d — phones already "
              "on %d will not offer this as an update" % (code, highest, highest))

    # Rebuilding a version replaces its entry; entries whose APK has since been
    # deleted by hand are dropped, so the index never advertises a 404.
    merged = [e for e in existing
              if e.get("version_code") != code
              and os.path.isfile(os.path.join(out, str(e["file"])))]
    merged.append(entry)
    merged.sort(key=lambda e: int(e.get("version_code", 0) or 0), reverse=True)

    keep, pruned = merged[:KEEP], merged[KEEP:]
    write_atomic(index_path, json.dumps(keep, indent=2) + "\n")
    for stale in pruned:
        for path in (os.path.join(out, str(stale["file"])),
                     os.path.join(out, str(stale["file"])[:-4] + ".aab")):
            if os.path.isfile(path):
                os.remove(path)
                print("[release] pruned %s" % os.path.basename(path))

    print("[release] published %s (%s, sha256 %s…)" % (filename, human(entry["size_bytes"]), digest[:12]))
    print("[release] %d release(s) hosted in %s" % (len(keep), out))
    print("[release] phone fetches "
          "https://fitrogue.home.kevinhorecka.com:1403/releases/%s" % INDEX)


if __name__ == "__main__":
    main()
