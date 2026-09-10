#!/usr/bin/env python3
"""Read curation verdicts back out, and say what they mean.

The gallery collects judgements; this is the half that uses them. Two jobs:

    python3 tools/curate.py                 # what has been judged, per batch
    python3 tools/curate.py <batch>         # the kept recipes, and per-axis rates

The second is the one that matters. A list of forty ids I should keep is
barely worth collecting -- the useful output is WHICH AXIS the keeps came
from, because that is a finding about the generator rather than about forty
individual pictures. "Every broad build was kept and every `layers` garment
was rejected" changes what the next batch should contain; "keep c003, c017,
c022" does not.

So this reports, for every axis value, how often it was kept versus rejected,
and flags the ones a person clearly liked or clearly did not. With small
batches those rates are noisy and the tool says so rather than pretending.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, ".scratch", "candidates")

# Below this many judged candidates carrying a value, the keep rate is noise
# and printing it as a finding would be inventing signal from three samples.
MIN_SAMPLES = 4


def batch_dir(name):
    return DIR if name == "_root" else os.path.join(DIR, name)


def load(name):
    try:
        with open(os.path.join(batch_dir(name), "manifest.json")) as fh:
            man = json.load(fh)
    except (OSError, ValueError):
        return None, {}
    try:
        with open(os.path.join(batch_dir(name), "verdicts.json")) as fh:
            verdicts = json.load(fh)
    except (OSError, ValueError):
        verdicts = {}
    return man, verdicts


def batches():
    out = []
    if os.path.isfile(os.path.join(DIR, "manifest.json")):
        out.append("_root")
    if os.path.isdir(DIR):
        for e in sorted(os.listdir(DIR)):
            if os.path.isfile(os.path.join(DIR, e, "manifest.json")):
                out.append(e)
    return out


def summary():
    names = batches()
    if not names:
        print("no batches under %s" % DIR)
        return 0
    print("%-16s %-12s %8s %6s %6s %6s" %
          ("batch", "kind", "judged", "keep", "maybe", "rej"))
    for name in names:
        man, v = load(name)
        if man is None:
            continue
        rows = [c for c in man.get("candidates", []) if "error" not in c]
        vals = [v.get(c["id"]) for c in rows]
        print("%-16s %-12s %5d/%-3d %6d %6d %6d" % (
            name, man.get("kind", "?"),
            sum(1 for x in vals if x), len(rows),
            vals.count("keep"), vals.count("maybe"), vals.count("reject")))
    return 0


def detail(name, as_json):
    man, v = load(name)
    if man is None:
        print("no such batch: %s" % name, file=sys.stderr)
        return 1
    rows = [c for c in man.get("candidates", []) if "error" not in c]
    kept = [c for c in rows if v.get(c["id"]) == "keep"]
    maybe = [c for c in rows if v.get(c["id"]) == "maybe"]
    judged = [c for c in rows if v.get(c["id"])]

    if as_json:
        print(json.dumps({
            "batch": name,
            "keep": [{"id": c["id"], "recipe": c.get("recipe", {})} for c in kept],
            "maybe": [{"id": c["id"], "recipe": c.get("recipe", {})} for c in maybe],
        }, indent=1))
        return 0

    print("%s: %d judged of %d — %d keep, %d maybe"
          % (name, len(judged), len(rows), len(kept), len(maybe)))
    if not judged:
        print("nothing judged yet")
        return 0

    # Per axis: how a value fared when it was actually looked at. Rejections
    # count in the denominator and 'maybe' does not count either way -- a maybe
    # is "I did not decide", and folding it in would put a thumb on the scale.
    tally = defaultdict(lambda: defaultdict(lambda: [0, 0]))   # axis -> val -> [keep, seen]
    for c in judged:
        verdict = v.get(c["id"])
        if verdict == "maybe":
            continue
        for axis, val in (c.get("recipe") or {}).items():
            cell = tally[axis][str(val)]
            cell[1] += 1
            if verdict == "keep":
                cell[0] += 1

    print()
    print("what the keeps have in common")
    thin = 0
    for axis in sorted(tally):
        parts = []
        for val in sorted(tally[axis], key=lambda k: -tally[axis][k][1]):
            keep, seen = tally[axis][val]
            if seen < MIN_SAMPLES:
                thin += 1
                continue
            parts.append("%s %d/%d" % (val, keep, seen))
        if parts:
            print("  %-10s %s" % (axis, "   ".join(parts)))
    if thin:
        print("  (%d values seen fewer than %d times, not shown — too few to read)"
              % (thin, MIN_SAMPLES))

    print()
    print("kept")
    for c in kept:
        r = c.get("recipe") or {}
        print("  %-6s %s" % (c["id"], " ".join("%s=%s" % kv for kv in sorted(r.items()))))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("batch", nargs="?", help="omit to list every batch")
    ap.add_argument("--json", action="store_true",
                    help="machine-readable keeps, for a generator to consume")
    args = ap.parse_args()
    return summary() if not args.batch else detail(args.batch, args.json)


if __name__ == "__main__":
    raise SystemExit(main())
