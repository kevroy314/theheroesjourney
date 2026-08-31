#!/usr/bin/env python3
"""The one place the app's version is decided, and the only writer of it.

    python3 tools/version.py                 # 0.2.0 200
    python3 tools/version.py --name          # 0.2.0
    python3 tools/version.py --code          # 200
    python3 tools/version.py --sync          # push it into the generated files
    python3 tools/version.py --bump patch    # 0.2.0 -> 0.2.1, then --sync
    python3 tools/version.py --set 1.0.0     # explicit, then --sync

Source of truth is `package.json`'s `version`. It already existed, it is
already what the repo calls itself, and package.json is documented as the one
discoverable entry point for the build commands — so the version lives next to
them rather than in a new file nobody thinks to look at.

**The Android version code is never authored, only derived**:

    code = major * 10000 + minor * 100 + patch

so 0.2.0 is 200 and 1.4.12 is 10412. There is exactly one number a human edits,
which is what makes it impossible for the name and the code to drift apart — the
failure mode the literals in export_presets.cfg had (they said 0.1.0/1 while
package.json said 0.2.0). It is monotonic for as long as minor and patch stay
under 100, which is checked below rather than assumed.

`--sync` rewrites the version in two *generated* locations:

  * export_presets.cfg `[preset.2]` — `version/code` and `version/name`. Only
    this preset; the Web and Linux presets are load-bearing for the live site.
  * project.godot — `application/config/version` and `config/version_code`, so
    the running game can read its own version with ProjectSettings.get_setting()
    and compare itself with releases/releases.json without a second copy of the
    number in GDScript. scripts/autoload/Updater.gd depends on version_code
    matching the APK exactly, or the phone re-offers an update it just applied.

build_android.sh runs `--sync` on every build, so those two files are outputs,
not inputs: editing them by hand is pointless rather than dangerous.

Standard library only — this runs before anything else in the build.
"""
import argparse
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "package.json")
PRESETS = os.path.join(ROOT, "export_presets.cfg")
PROJECT = os.path.join(ROOT, "project.godot")

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
PARTS = ("major", "minor", "patch")


def die(msg):
    sys.exit("[version] ERROR: %s" % msg)


def read_name():
    """The semver string, validated hard: a bad version must stop the build."""
    try:
        with open(PACKAGE, encoding="utf-8") as f:
            raw = json.load(f).get("version")
    except FileNotFoundError:
        die("no %s — the version has nowhere to live" % PACKAGE)
    except (OSError, ValueError) as exc:
        die("%s is unreadable (%s)" % (PACKAGE, exc))
    if not raw:
        die('%s has no "version" field' % PACKAGE)
    if not SEMVER.match(str(raw).strip()):
        die('version %r in package.json is not MAJOR.MINOR.PATCH' % raw)
    return str(raw).strip()


def to_code(name):
    major, minor, patch = (int(x) for x in SEMVER.match(name).groups())
    # Android version codes are a single monotonically increasing integer and a
    # phone will not install a build whose code is <= the one it already has.
    # Packing three fields into one number only stays monotonic while the lower
    # two fit their digit budget, so refuse rather than silently going backwards.
    if minor > 99 or patch > 99:
        die("minor/patch must stay under 100 for the derived code to stay "
            "monotonic (got %s) — bump the major instead" % name)
    if major > 210000:
        die("major %d overflows Android's 2100000000 version code ceiling" % major)
    return major * 10000 + minor * 100 + patch


def write_package(name):
    """Rewrite the version in place, textually, to keep formatting and order."""
    with open(PACKAGE, encoding="utf-8") as f:
        blob = f.read()
    new, n = re.subn(r'("version"\s*:\s*")[^"]*(")', r"\g<1>%s\g<2>" % name, blob, count=1)
    if n != 1:
        die('could not find the "version" field in package.json to rewrite')
    with open(PACKAGE, "w", encoding="utf-8") as f:
        f.write(new)


def sync_presets(name, code):
    """Rewrite version/name and version/code inside [preset.2] only.

    Scoped to the Android block by slicing the file at its section headers: a
    global regex would also rewrite a future preset, and the Web and Linux
    presets are what the live deployment is built from.
    """
    with open(PRESETS, encoding="utf-8") as f:
        blob = f.read()
    start = blob.find("[preset.2.options]")
    if start < 0:
        die("no [preset.2.options] in export_presets.cfg — is the Android preset gone?")
    nxt = blob.find("\n[", start)
    end = len(blob) if nxt < 0 else nxt
    body, changed = blob[start:end], []

    for key, value in (("version/code", str(code)), ("version/name", '"%s"' % name)):
        body, n = re.subn(r"(?m)^%s=.*$" % re.escape(key), "%s=%s" % (key, value), body)
        if n != 1:
            die("expected exactly one %s in [preset.2.options], found %d" % (key, n))
        changed.append("%s=%s" % (key, value))

    updated = blob[:start] + body + blob[end:]
    if updated != blob:
        with open(PRESETS, "w", encoding="utf-8") as f:
            f.write(updated)
    return changed


def sync_project(name, code):
    """Keep application/config/version{,_code} in step, creating them if absent.

    Both, not just the name: scripts/autoload/Updater.gd reads
    `application/config/version_code` to decide whether releases.json is
    offering it something newer than what is running. If that number lags the
    one baked into the APK, the phone downloads an update, installs it, still
    reads the old code and offers the same update again — forever.
    """
    with open(PROJECT, encoding="utf-8") as f:
        blob = f.read()
    lines = []
    for key, value in (("config/version_code", str(code)), ("config/version", '"%s"' % name)):
        line = "%s=%s" % (key, value)
        lines.append(line)
        if re.search(r"(?m)^%s=" % re.escape(key), blob):
            blob = re.sub(r"(?m)^%s=.*$" % re.escape(key), line, blob, count=1)
        else:
            # Sits directly after config/name so the [application] block reads
            # in the order the Godot editor writes it.
            blob, n = re.subn(r"(?m)^(config/name=.*)$", r"\1\n" + line, blob, count=1)
            if n != 1:
                die("no config/name= in project.godot to anchor %s to" % key)
    with open(PROJECT, "w", encoding="utf-8") as f:
        f.write(blob)
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    out = ap.add_mutually_exclusive_group()
    out.add_argument("--name", action="store_true", help="print the version name only")
    out.add_argument("--code", action="store_true", help="print the derived version code only")
    ap.add_argument("--force", action="store_true",
                    help="allow --set to move the version backwards")
    ap.add_argument("--sync", action="store_true",
                    help="write the version into export_presets.cfg and project.godot")
    edit = ap.add_mutually_exclusive_group()
    edit.add_argument("--bump", choices=PARTS, help="increment a component, then --sync")
    edit.add_argument("--set", dest="set_to", metavar="X.Y.Z",
                      help="set the version explicitly, then --sync")
    args = ap.parse_args()

    name = read_name()

    if args.set_to or args.bump:
        if args.set_to:
            if not SEMVER.match(args.set_to):
                die("--set wants MAJOR.MINOR.PATCH, got %r" % args.set_to)
            new = args.set_to
        else:
            nums = [int(x) for x in SEMVER.match(name).groups()]
            i = PARTS.index(args.bump)
            nums[i] += 1
            # A bump resets everything below it, or 0.2.9 -> 0.3.9.
            nums[i + 1:] = [0] * (len(nums) - i - 1)
            new = "%d.%d.%d" % tuple(nums)
        if to_code(new) < to_code(name) and not args.force:
            die("%s would move the version *backwards* from %s. A phone will not "
                "install a code lower than the one it has, so this only ever "
                "helps when correcting a version that was never published — "
                "pass --force if that is what this is." % (new, name))
        to_code(new)  # validate the derived code before touching anything
        write_package(new)
        print("[version] %s -> %s" % (name, new))
        name = new
        args.sync = True

    code = to_code(name)

    if args.sync:
        for line in sync_presets(name, code):
            print("[version] export_presets.cfg [preset.2] %s" % line)
        for line in sync_project(name, code):
            print("[version] project.godot %s" % line)

    if args.name:
        print(name)
    elif args.code:
        print(code)
    elif not args.sync:
        print("%s %d" % (name, code))


if __name__ == "__main__":
    main()
