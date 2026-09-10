#!/usr/bin/env python3
"""Generate a batch of townsperson candidates for a human to curate.

The cast is authored in code -- `tools/make_sprites.py` builds every figure
from one `TOWNSPERSON` base plus a delta dictionary -- which means variety is a
parameter sweep and costs nothing but time. That is the whole reason this file
can exist: there is no image quota to spend, so producing sixty candidates and
throwing away fifty is the cheap option rather than the expensive one.

What it does NOT do is decide which are good. A generator can measure contrast
and silhouette width; it cannot tell you that a figure reads as a bailiff. So
this writes candidates and a manifest, the manifest goes into a gallery, and a
person marks the ones worth keeping. `tools/curate.py` reads the verdicts back.

    python3 tools/candidates.py --count 48 --seed 7

Output lands in `.scratch/candidates/` -- deliberately not in the repo, because
a rejected candidate is not an asset and should not be committed.
"""
import argparse
import base64
import io
import json
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
OUT = os.path.join(ROOT, ".scratch", "candidates")

import make_sprites as ms  # noqa: E402  -- after sys.path, by necessity


# --- the axes -------------------------------------------------------------------
#
# Each axis is a named set of deltas over TOWNSPERSON. They are named because
# the point of curation is to learn WHICH AXIS produced the ones Kevin keeps --
# "the heavy builds all worked and the tall ones all read as the player" is a
# finding, and it is only available if every candidate records how it was made.

BUILDS = {
    "child":   dict(crown=11, head_h=10, head_w=12, neck_w=5, neck_rows=2,
                    sh_w=14, chest_w=14, elbow_w=15, waist_w=14, hem_w=15,
                    hem_y=36, leg_w=4, leg_gap=2, stride=3,
                    shadow=7.5, shadow_y=3.4),
    "slight":  dict(crown=4, head_h=11, head_w=11, sh_w=16, chest_w=15,
                    elbow_w=17, waist_w=14, hem_w=14, hem_y=32, leg_w=3,
                    stride=4, shadow=8.5),
    "average": dict(),
    "broad":   dict(crown=2, head_w=13, sh_w=21, chest_w=21, elbow_w=23,
                    waist_w=20, hem_w=19, hem_y=33, leg_w=5, leg_gap=2,
                    stride=4, shadow=11.0),
    "stooped": dict(crown=5, head_h=11, sh_w=19, chest_w=18, elbow_w=20,
                    waist_w=18, hem_w=17, hem_y=31, lean=1, leg_w=4,
                    stride=3, shadow=10.0, shadow_y=4.4),
}

# Read off the builder, not invented. The first draft of this list had "hood",
# "bare" and "brim" in it, none of which `make_sprites.py` has ever heard of --
# an unknown crown does not raise, it quietly draws the default, so every one
# of those candidates would have been a figure whose manifest lied about how it
# was made. `hood` is in the module's own comment but there is no `kind ==
# "hood"` arm to answer it, so it is left out until there is.
CROWNS = ["cap", "mop", "bun", "bald", "horseshoe"]
GARMENTS = ["coat", "cloak", "dress", "apron", "vest", "layers"]

SKINS = {
    "pale": ms.SKIN_PALE, "ash": ms.SKIN_ASH,
    "warm": ms.SKIN_WARM, "deep": ms.SKIN_DEEP,
}
HAIRS = {
    "straw": ms.HAIR_STRAW, "dark": ms.HAIR_DARK,
    "white": ms.HAIR_WHITE, "iron": ms.HAIR_IRON,
}
CLOTHS = {
    "leaf": ms.LEAF, "moss": ms.MOSS, "lilac": ms.LILAC, "shawl": ms.SHAWL,
    "sack": ms.SACK, "rust": ms.RUST, "linen": ms.LINEN, "brass": ms.BRASS,
    "slate": ms.SLATE, "dress": ms.DRESS, "rose": ms.ROSE,
}


def axes():
    """The vocabularies, checked against the builder rather than trusted.

    A crown kind the builder does not implement is drawn as the default and
    raises nothing, so the only way to keep the manifest honest is to prove
    every name has an arm before the batch is generated.
    """
    src = open(os.path.join(ROOT, "tools", "make_sprites.py")).read()
    missing = [k for k in CROWNS + GARMENTS if '"%s"' % k not in src]
    if missing:
        raise SystemExit("candidates: make_sprites.py has no arm for %s"
                         % ", ".join(missing))
    return CROWNS, GARMENTS


def one(rng, crowns, garments):
    """One candidate: a build, a crown, a garment and a palette."""
    build = rng.choice(sorted(BUILDS))
    crown = rng.choice(crowns)
    garment = rng.choice(garments)
    skin = rng.choice(sorted(SKINS))
    hair = rng.choice(sorted(HAIRS))
    cloth = rng.choice(sorted(CLOTHS))
    trouser = rng.choice(sorted(CLOTHS))
    recipe = {
        "build": build, "crown": crown, "garment": garment,
        "skin": skin, "hair": hair, "cloth": cloth, "trouser": trouser,
    }
    delta = dict(BUILDS[build])
    delta.update(
        crown_kind=crown, garment=garment,
        skin=SKINS[skin], hair=HAIRS[hair],
        cloth=CLOTHS[cloth], trouser=CLOTHS[trouser],
    )
    # `layers` is the only garment that demands a parameter of its own: it is
    # the man wearing everything he owns and some of it somebody else's, so it
    # needs two more hues to patch with. Without them the builder raises
    # KeyError('patch') and every layered candidate is lost, which is what the
    # first batch did -- six of forty-eight, all the same way.
    if garment == "layers":
        pool = [c for c in sorted(CLOTHS) if c not in (cloth, trouser)]
        a, b = rng.choice(pool), rng.choice(pool)
        recipe["patch"] = "%s+%s" % (a, b)
        delta["patch"] = (CLOTHS[a], CLOTHS[b])
    return recipe, delta


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=48)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    rng = random.Random(args.seed)
    crowns, garments = axes()

    rows = []
    seen = set()
    tries = 0
    while len(rows) < args.count and tries < args.count * 40:
        tries += 1
        recipe, delta = one(rng, crowns, garments)
        # The same recipe twice is a wasted slot on the gallery page and, worse,
        # two rows a curator has to compare and find identical.
        key = tuple(sorted(recipe.items()))
        if key in seen:
            continue
        seen.add(key)

        cid = "c%03d" % len(rows)
        try:
            cels = ms.hu_build_all(ms.townsperson(**delta))
        except Exception as exc:                      # noqa: BLE001
            # A build that throws is a finding about the parameter space, not a
            # reason to abandon the batch. Record it and carry on.
            rows.append({"id": cid, "recipe": recipe, "error": str(exc)})
            continue

        sheet = ms.town_sheet(cels)
        # Two pictures per candidate, because they answer different questions.
        # The 4x contact sheet says whether the figure is drawn correctly; the
        # single south-facing cel at game zoom says whether it reads at the size
        # it will actually be seen, which is the only size that matters.
        big = ms.spite_contact(sheet)
        small = cels[("down", "neutral")]
        small = small.resize((small.width * 3, small.height * 3),
                             ms.Image.NEAREST)

        with open(os.path.join(OUT, "%s.png" % cid), "wb") as fh:
            fh.write(png_bytes(big))
        rows.append({
            "id": cid,
            "recipe": recipe,
            "big": base64.b64encode(png_bytes(big)).decode("ascii"),
            "small": base64.b64encode(png_bytes(small)).decode("ascii"),
        })

    manifest = {"seed": args.seed, "count": len(rows), "candidates": rows}
    with open(os.path.join(OUT, "manifest.json"), "w") as fh:
        json.dump(manifest, fh)
    built = sum(1 for r in rows if "error" not in r)
    print("candidates: %d built, %d failed, seed %d -> %s"
          % (built, len(rows) - built, args.seed, OUT))
    for r in rows:
        if "error" in r:
            print("  x %s %s: %s" % (r["id"], r["recipe"], r["error"]))


if __name__ == "__main__":
    main()
