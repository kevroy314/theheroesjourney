#!/usr/bin/env python3
"""
Put a picture of a thing into the world as a prop.

The distance this closes: today, adding one prop means writing a builder in
tools/make_tiles.py, regenerating a 70-slot atlas and 1,722 sprites, and
hand-checking the manifest. There is no route from "I have a picture of a well"
to "there are wells in the world". This is that route.

    tools/add_prop.py add --src art/gen/well.png \\
        --id well_covered --biome path_dirt --density 0.004 --solid

Five stages, each of which can be run and inspected on its own:

  INGEST      a PNG from anywhere: an AI generation, a scan, a photo. Or, with
              --generate and the explicit --spend-quota flag, drive
              art/chatgpt_gen.py to make one. Opt-in, because every generation
              costs the owner real image quota.
  CONDITION   art/cutout.py takes the background out; the subject is measured
              down to the 64x96 slot by area coverage, so the alias lands where
              the shape actually is. See that file for why this is the hard part.
  GRADE       the sprite is re-graded and quantised into the same ramps
              tools/make_tiles.py builds from data/themes/firstlight.json, so a
              new prop is literally made of the colours the old ones are made
              of. Then the house rim and the house contact shadow.
  REGISTER    appended to assets/tiles/props.png and assets/tiles/tiles.json.
              APPEND ONLY. Plane ids live in world data and in hand edits; the
              tool refuses to run if anything already in the catalogue has
              moved, and refuses to write if its own append would move anything.
  VERIFY      the art-direction checks from docs/ART-DIRECTION-OVERWORLD.md,
              plus a preview of the prop standing on the ground it claims, at
              the game's 3x zoom and at 1:1.

Subcommands:
    add       ingest -> ... -> register one prop
    reapply   re-append every authored prop after make_tiles.py has regenerated
              the atlas and wiped them (it will; it owns those files)
    verify    check the catalogue against the authored registry and re-run the
              art checks
    list      what has been authored, and at which plane id

The authored registry lives at art/props/authored.json with the finished 64x96
sprites beside it, so `reapply` is byte-exact and needs neither the source image
nor a second generation.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
sys.path.insert(0, os.path.join(ROOT, "art"))

import make_tiles as MT                                    # noqa: E402
from cutout import CutoutError, cutout                     # noqa: E402

TILES = os.path.join(ROOT, "assets", "tiles")
ATLAS = os.path.join(TILES, "props.png")
MANIFEST = os.path.join(TILES, "tiles.json")
STORE = os.path.join(ROOT, "art", "props")
REGISTRY = os.path.join(STORE, "authored.json")

W, H = MT.PROP_W, MT.PROP_H                                # 64 x 96
GAMMA = 2.2

# The biggest thing anyone has drawn by hand is tree_broad at 41x50. Anything
# bigger than the slot minus its rim cannot be drawn at all.
BIGGEST_AUTHORED = (41, 50)
MAX_CONTENT = (60, 92)


def say(*a):
    print(*a)


def die(msg):
    sys.exit("add_prop: " + msg)


# --- colour ------------------------------------------------------------------
#
# make_tiles.py is the single source of truth for what colour anything in this
# game is: it reads data/themes/firstlight.json and grades every material to a
# stated luma with at_luma(). We import it rather than re-deriving it, so a
# theme edit moves imported props exactly as far as it moves drawn ones.

def lift(a):
    return np.clip(a, 0.0, 1.0) ** (1.0 / GAMMA)


def luma(a):
    return a[..., 0] * 0.299 + a[..., 1] * 0.587 + a[..., 2] * 0.114


DARK = np.array(MT.DARK, float)
LIGHT = np.array(MT.LIGHT, float)


def grade(rgb, lo, hi, sat=1.0):
    """Re-grade the subject's value structure into the band props are allowed.

    §2.6: the ground plane lives at mean luma 21-72 and the headroom above 90 is
    reserved for prop crowns, cliff lips and the character. An AI render arrives
    with its own arbitrary exposure, so map its 2nd..98th luma percentile onto
    [lo, hi] and then move each pixel to its new value the way every material in
    make_tiles.py is moved: toward DARK or toward LIGHT, which keeps the hue and
    keeps the result inside the theme's value axis.
    """
    out = rgb * 255.0
    if sat != 1.0:
        g = luma(out)[..., None]
        out = np.clip(g + (out - g) * sat, 0, 255)
    l = luma(out)
    p2, p98 = np.percentile(l, 2), np.percentile(l, 98)
    if p98 - p2 < 1e-3:
        target = np.full_like(l, (lo + hi) * 0.5)
    else:
        target = lo + (l - p2) * (hi - lo) / (p98 - p2)
    target = np.clip(target, 4.0, 150.0)

    ld, ll = float(luma(DARK)), float(luma(LIGHT))
    down = target <= l
    t = np.zeros_like(l)
    span_d = np.maximum(l - ld, 1e-3)
    span_u = np.maximum(ll - l, 1e-3)
    t = np.where(down, (l - target) / span_d, (target - l) / span_u)
    t = np.clip(t, 0.0, 1.0)[..., None]
    anchor = np.where(down[..., None], DARK, LIGHT)
    return np.clip(out + (anchor - out) * t, 0, 255) / 255.0


def ramp_colours(name):
    return [tuple(c) for c in MT.PP[name].values()]


def choose_ramps(rgb, mask, k=3, forced=None):
    """Pick the prop palettes this subject is actually made of.

    Greedy: whichever of make_tiles.py's eighteen prop ramps explains the most
    of the picture, then whichever explains the most of what is left. That is a
    matching pursuit, and it beats "the ramp whose mean hue is nearest" for
    anything two-toned, which is most props -- a well is stone and rope, a cart
    is wood and metal.
    """
    if forced:
        return list(forced)
    px = lift(rgb[mask])
    if px.shape[0] > 4000:
        px = px[np.linspace(0, px.shape[0] - 1, 4000).astype(int)]
    best, err = [], np.full(px.shape[0], 1e9)
    for _ in range(k):
        pick, pick_err, pick_d = None, None, None
        for name in MT.PP:
            if name in best:
                continue
            P = lift(np.array(ramp_colours(name), float) / 255.0)
            d = ((px[:, None, :] - P[None, :, :]) ** 2).sum(2).min(1)
            e = np.minimum(err, d)
            if pick is None or e.sum() < pick_err:
                pick, pick_err, pick_d = name, e.sum(), e
        best.append(pick)
        err = pick_d
    return best


def quantise(rgb, mask, palette):
    """Nearest palette entry in gamma-lifted space -- the same distance metric,
    for the same reason, as art/postprocess.py."""
    P = lift(np.array(palette, float) / 255.0)
    px = lift(rgb[mask])
    idx = ((px[:, None, :] - P[None, :, :]) ** 2).sum(2).argmin(1)
    out = rgb.copy()
    out[mask] = np.array(palette, float)[idx] / 255.0
    return out, idx


# --- ingest and condition -----------------------------------------------------

def generate(prompt_file, out_png, tab):
    """Drive art/chatgpt_gen.py. Deliberately a subprocess call to the script
    the owner already uses: the CDP recipe in .claude/skills/game-art-pipeline
    is fiddly and there must be exactly one copy of it."""
    gen = os.path.join(ROOT, "art", "chatgpt_gen.py")
    cmd = [sys.executable, gen, prompt_file, out_png] + ([tab] if tab else [])
    say("spending image quota:", " ".join(cmd))
    r = subprocess.run(cmd)
    if r.returncode != 0 or not os.path.exists(out_png):
        die("generation failed; nothing was spent on a retry. Fix the prompt or "
            "the browser session and run again.")
    return out_png


def box_resize(a, size):
    """Area-average resize of a float plane. This is the whole anti-aliasing
    story: a target pixel's value is the mean of the source pixels under it, so
    coverage becomes a real number and the binary edge is decided once, at the
    resolution the sprite is actually drawn at."""
    return np.asarray(Image.fromarray(a.astype(np.float32), "F")
                      .resize(size, Image.BOX), dtype=np.float32)


def condition(src_img, size, tol, work, drop_shadow, fill_holes, crop,
              cover=0.5, min_blob=0.02):
    """Source image -> (rgb float HxWx3, bool mask) laid out in the 64x96 slot,
    anchored bottom-centre."""
    if crop:
        src_img = src_img.crop(crop)
    rgb, cov = cutout(src_img, tol=tol, work=work, drop_shadow=drop_shadow,
                      fill_holes=fill_holes, min_blob=min_blob,
                      report=lambda s: say("  " + s))
    m = cov >= 0.5
    ys, xs = np.where(m)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rgb, cov = rgb[y0:y1, x0:x1], cov[y0:y1, x0:x1]
    h, w = cov.shape

    tw, th = size
    s = min(tw / float(w), th / float(h))
    nw, nh = max(1, int(round(w * s))), max(1, int(round(h * s)))
    if s > 1.0:
        say("  warning: the source is smaller than the slot it is going into "
            "(%dx%d -> %dx%d). It will look soft." % (w, h, nw, nh))

    a = box_resize(cov, (nw, nh))
    pre = np.stack([box_resize(rgb[:, :, c] * cov, (nw, nh)) for c in range(3)], -1)
    col = pre / np.maximum(a, 1e-4)[..., None]      # un-premultiply: no bg bleed
    mask = a >= cover

    if not mask.any():
        raise CutoutError("nothing survived the downsample to %dx%d" % (nw, nh))
    ys, xs = np.where(mask)
    mask = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    col = col[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    nh, nw = mask.shape

    out_rgb = np.zeros((H, W, 3), np.float32)
    out_m = np.zeros((H, W), bool)
    ox = W // 2 - nw // 2                    # anchor: bottom-centre of the slot
    oy = H - nh                              # base sits on the anchor row
    out_rgb[oy:oy + nh, ox:ox + nw] = np.clip(col, 0, 1)
    out_m[oy:oy + nh, ox:ox + nw] = mask
    return out_rgb, out_m


# --- compose ------------------------------------------------------------------

def base_halfwidth(mask):
    """Half the width of the part of the prop that is actually on the ground:
    the widest of its bottom five rows. The contact shadow is sized from this,
    not from the crown, or a tree gets a shadow the size of its canopy."""
    rows = np.flatnonzero(mask.any(1))
    if rows.size == 0:
        return 4
    y1 = rows[-1]
    band = mask[max(0, y1 - 4):y1 + 1]
    cols = np.flatnonzero(band.any(0))
    return max(2, (cols[-1] - cols[0] + 1) / 2.0) if cols.size else 4


def compose(rgb, mask, outline=True, shadow=True, shadow_w=None):
    """RGB + mask -> the finished RGBA sprite, with the house rim and the one
    house contact shadow, both taken from make_tiles.py rather than restated."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = np.zeros((H, W, 4), np.uint8)
    px[:, :, :3] = np.clip(rgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    px[:, :, 3] = np.where(mask, 255, 0)
    img = Image.fromarray(px, "RGBA")
    if outline:
        MT.poutline(img)
    if shadow:
        # Measured over the 29 hand-drawn props that cast one: the shadow is a
        # median 1.27x the width of the base it sits under. It has to be wider,
        # or pshadow's "under, never over" rule leaves nothing visible.
        rw = shadow_w if shadow_w is not None else 1.25 * base_halfwidth(mask)
        # "should not exceed a tile in length" -- §2.2b, quoting Slynyrd.
        rw = int(round(max(4, min(16, rw))))
        MT.pshadow(img, rw)
    return img


# --- the catalogue ------------------------------------------------------------
#
# tiles.json is the contract between make_tiles.py, make_world.py,
# world_to_tiled.py / tiled_to_world.py and scripts/ui/World.gd. Slot index is
# plane id minus one, plane ids are stored in world data and in hand edits, and
# so the only safe edit is an append. Everything below exists to make an append
# provably an append.

def load_manifest():
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def save_manifest(man):
    with open(MANIFEST, "w", encoding="utf-8") as f:
        json.dump(man, f, indent=2, sort_keys=True)
        f.write("\n")


def check_catalogue(man, atlas):
    """Refuse to touch a catalogue that is already inconsistent. If any of this
    fails, something else renumbered the props and the world data is already
    wrong; appending would only bury it."""
    p = man.get("props")
    if not p:
        die("tiles.json has no props section.")
    for key, want in (("cols", MT.PROP_COLS), ("slot", [W, H]),
                      ("anchor", [MT.PROP_AX, MT.PROP_AY])):
        if p.get(key) != want:
            die("props.%s is %r, expected %r. The slot geometry changed; this "
                "tool would write sprites into the wrong place." % (key, p.get(key), want))
    seen = set()
    for i, e in enumerate(p["list"]):
        if e["index"] != i or e["plane"] != i + 1:
            die("props.list[%d] is id=%r index=%d plane=%d -- the list has been "
                "reordered or renumbered. Every world file and every hand edit "
                "that stores plane ids is now wrong. Fix that before adding "
                "anything." % (i, e["id"], e["index"], e["plane"]))
        if e["id"] in seen:
            die("duplicate prop id %r at index %d." % (e["id"], i))
        seen.add(e["id"])
    rows = (len(p["list"]) + MT.PROP_COLS - 1) // MT.PROP_COLS
    if p.get("rows") != rows:
        die("props.rows is %r but %d props need %d rows."
            % (p.get("rows"), len(p["list"]), rows))
    if atlas.size != (MT.PROP_COLS * W, p["rows"] * H):
        die("props.png is %dx%d but the manifest says %d cols x %d rows."
            % (atlas.size[0], atlas.size[1], p["cols"], p["rows"]))
    return p["list"]


def sha(path_or_img):
    if isinstance(path_or_img, Image.Image):
        return hashlib.sha256(path_or_img.tobytes()).hexdigest()[:16]
    with open(path_or_img, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def load_registry():
    if not os.path.exists(REGISTRY):
        return {"base_count": None, "props": []}
    with open(REGISTRY, encoding="utf-8") as f:
        return json.load(f)


def save_registry(reg):
    os.makedirs(STORE, exist_ok=True)
    with open(REGISTRY, "w", encoding="utf-8") as f:
        json.dump(reg, f, indent=2, sort_keys=True)
        f.write("\n")


def append_prop(entry, sprite, replace=False):
    """The only function in this repo outside make_tiles.py that writes
    props.png or the props section of tiles.json.

    Appends one slot. Then proves, against the bytes it started from, that
    nothing that already existed moved -- both in the manifest and in the atlas
    pixels. If either check fails nothing is written.
    """
    man = load_manifest()
    atlas = Image.open(ATLAS).convert("RGBA")
    before_list = check_catalogue(man, atlas)
    before_px = atlas.tobytes()
    before_json = json.dumps(before_list, sort_keys=True)

    existing = {e["id"]: e["index"] for e in before_list}
    if entry["id"] in existing:
        if not replace:
            die("prop id %r is already at index %d. Adding it again would give "
                "the same thing two plane ids. Use --replace to redraw it in "
                "place (index and plane keep their values), or choose another "
                "--id." % (entry["id"], existing[entry["id"]]))
        idx = existing[entry["id"]]
    else:
        idx = len(before_list)

    rows = max(man["props"]["rows"], (idx + MT.PROP_COLS) // MT.PROP_COLS)
    if atlas.size[1] < rows * H:
        grown = Image.new("RGBA", (MT.PROP_COLS * W, rows * H), (0, 0, 0, 0))
        grown.paste(atlas, (0, 0))
        atlas = grown
        say("  atlas grew to %d rows (%d slots)" % (rows, rows * MT.PROP_COLS))

    slot = ((idx % MT.PROP_COLS) * W, (idx // MT.PROP_COLS) * H)
    atlas.paste(sprite, slot)                       # paste, not composite

    new = dict(entry)
    new["index"] = idx
    new["plane"] = idx + 1
    lst = list(before_list)
    if idx < len(lst):
        lst[idx] = new
    else:
        lst.append(new)

    # --- the two proofs ------------------------------------------------------
    others = [e for e in lst if e["index"] != idx]
    if json.dumps(others, sort_keys=True) != json.dumps(
            [e for e in before_list if e["index"] != idx], sort_keys=True):
        die("internal check failed: an existing catalogue entry changed. "
            "Nothing written.")
    old = Image.frombytes("RGBA", Image.open(ATLAS).size, before_px)
    for e in before_list:
        if e["index"] == idx:
            continue
        sx, sy = (e["index"] % MT.PROP_COLS) * W, (e["index"] // MT.PROP_COLS) * H
        box = (sx, sy, sx + W, sy + H)
        if old.crop(box).tobytes() != atlas.crop(box).tobytes():
            die("internal check failed: slot %d (%r) changed pixels. Nothing "
                "written." % (e["index"], e["id"]))
    del before_json

    man["props"]["list"] = lst
    man["props"]["rows"] = rows
    atlas.save(ATLAS)
    save_manifest(man)
    return idx, rows


# --- verification -------------------------------------------------------------

def ground_mean(biome):
    m = MT.MATERIALS.get(biome)
    return None if m is None else m["mean"]


def check_art(sprite, biomes, warn):
    """The checks docs/ART-DIRECTION-OVERWORLD.md asks for, as numbers.

    Every threshold below is calibrated against the 70 props make_tiles.py
    already draws, so "fails a check" means "unlike anything in the game",
    not "unlike my taste". The measurements, on body pixels (rim excluded):

        rim coverage      1.00 for all 55 outlined props, once the anchor row
                          -- which is the bottom edge of the slot and cannot
                          be rimmed -- is left out
        max luma          118 is the highest anything reaches
        colours           median 5, p90 8, most 11
        vs the ground     54 of 54 have either a highlight >= ground+18 or a
                          shadow <= ground-12. Mean luma is NOT the test: 20
                          of 54 sit within 8 points of their ground's mean and
                          read perfectly well, because what separates a prop
                          from the ground is its extremes and its rim.
    """
    a = np.asarray(sprite)
    opaque = a[:, :, 3] == 255
    shadow = a[:, :, 3] == MT.SHADOW_A
    rgb = a[:, :, :3].astype(float)
    ok = True

    if not opaque.any():
        warn("FAIL  the sprite is empty")
        return False
    ys, xs = np.where(opaque)
    bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
    say("  size          %dx%d px  (catalogue median 23x18, largest 41x50)" % (bw, bh))
    if bw < 6 or bh < 6:
        warn("WARN  under 6px on a side: it will read as a speck at 1:1")
        ok = False
    if bw > BIGGEST_AUTHORED[0] or bh > BIGGEST_AUTHORED[1]:
        warn("WARN  bigger than anything hand-drawn (%dx%d). Check it does not "
             "swallow the tile it stands on." % BIGGEST_AUTHORED)

    out = np.array(MT.OUTLINE)
    body = opaque & ~(rgb == out).all(2)
    if not body.any():
        warn("FAIL  the sprite is nothing but rim")
        return False

    edge = np.zeros_like(body)
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        edge |= body & ~np.roll(np.roll(body, dy, 0), dx, 1)
    edge[H - 1, :] = False            # the anchor row is the slot's own edge
    rim = (rgb == out).all(2) & opaque
    nb = np.zeros_like(rim)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            nb |= np.roll(np.roll(rim, dy, 0), dx, 1)
    covered = (edge & nb).sum() / max(1, edge.sum())
    say("  rim           %.0f%% of the silhouette boundary is rimmed "
        "(every hand-drawn prop: 100%%)" % (100 * covered))
    if covered < 0.98:
        warn("WARN  the rim is broken. It is what lets one sprite sit on grass "
             "and on snow; without it the prop disappears into dark ground.")
        ok = False

    last = np.flatnonzero(opaque.any(1))[-1]
    say("  contact       lowest opaque row y=%d of %d; %d shadow px"
        % (last, H - 1, int(shadow.sum())))
    if last < H - 3:
        warn("WARN  the base is %d px above the anchor row: it will float."
             % (H - 1 - last))
        ok = False
    if not shadow.any():
        warn("NOTE  no contact shadow. Correct for ground cover (grass, "
             "flowers); wrong for anything that stands up.")

    l = luma(rgb[body])
    say("  value         min %.0f  mean %.0f  p99 %.0f  max %.0f  "
        "(nothing drawn exceeds 118)"
        % (l.min(), l.mean(), np.percentile(l, 99), l.max()))
    if l.max() > 130:
        warn("WARN  max luma over 130. §2.6 reserves 130-150 for the "
             "character's lit side; this will blow out the scene.")
        ok = False
    for b in biomes:
        g = ground_mean(b)
        if g is None:
            continue
        hi, lo = l.max() - g, g - l.min()
        say("  vs %-12s ground mean %.0f: highlight %+.0f, shadow %+.0f"
            % (b, g, hi, lo))
        if hi < 18 and lo < 12:
            warn("WARN  on %s it has neither a highlight 18 above the ground "
                 "nor a shadow 12 below it. All 54 scattered props have one or "
                 "the other; this one will read as texture." % b)
            ok = False

    cols = {tuple(c) for c in rgb[body].astype(int).reshape(-1, 3).tolist()}
    say("  colours       %d distinct (hand-drawn props: median 5, most 11)"
        % len(cols))
    if len(cols) > 14:
        warn("WARN  %d colours. Lower --ramps; at 24px this reads as noise."
             % len(cols))
        ok = False
    return ok


def world_has(biome):
    """How many cells of this material the generated world actually contains.

    Worth checking, and it is the mistake this tool made first: `hardpan` is a
    real material in the tileset and a legal `biome` value, and the current
    world generator does not produce a single cell of it. A prop declared on it
    is correctly registered, correctly drawn, and will never once appear.
    Returns None if the world has not been generated.
    """
    path = os.path.join(ROOT, "data", "world", "overworld.json")
    if not os.path.exists(path):
        return None
    try:
        import base64
        import zlib
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        key = next((k for k in d if k.startswith("tiles")), None)
        if key is None:
            return None
        raw = zlib.decompress(base64.b64decode(d[key]))
        if biome not in MT.ORDER:
            return 0
        return raw.count(MT.ORDER.index(biome))
    except Exception:
        return None


def preview(sprite, pid, biomes, out_png):
    """The prop standing on the ground it claims, at the 3x zoom the game uses,
    beside a hand-drawn prop of the same biome for scale -- plus a 1:1 strip,
    because 1:1 is where a sprite is actually judged."""
    zoom = 3
    tiles = {}                       # a uniform patch needs no overlay tiles
    panels = []
    for b in biomes:
        if b not in MT.MATERIALS:
            continue
        gw, gh = 9, 5
        grid = [[b] * gw for _ in range(gh)]
        neighbour = next((p["id"] for p in MT.PROPS
                          if p["biome"] == b and p["id"] != pid), None)
        placed = [(2, 3, sprite), (5, 3, sprite)]
        if neighbour:
            placed.append((7, 3, MT.build_prop(neighbour)))
        panels.append((b, neighbour,
                       MT.render_patch(grid, tiles, seed=4, props=placed, zoom=zoom)))
    if not panels:
        panels = [("(none)", None, Image.new("RGBA", (9 * 32 * zoom, 5 * 32 * zoom),
                                             (18, 19, 28, 255)))]

    pw, ph = panels[0][2].size
    strip_h = H * 3 + 8
    sheet = Image.new("RGBA", (pw, ph * len(panels) + strip_h), (18, 19, 28, 255))
    for i, (_, _, im) in enumerate(panels):
        sheet.paste(im, (0, i * ph))
    x = 6
    for s in (1, 2, 3):
        im = sprite.resize((W * s, H * s), Image.NEAREST)
        sheet.alpha_composite(im, (x, ph * len(panels) + 4))
        x += W * s + 8
    sheet.save(out_png)
    say("  preview       %s  (%s)" % (os.path.relpath(out_png, ROOT),
                                      ", ".join("%s%s" % (b, " + " + n if n else "")
                                                for b, n, _ in panels)))


# --- commands -----------------------------------------------------------------

def cmd_add(a):
    os.makedirs(STORE, exist_ok=True)
    # Before anything else, and specifically before --generate can spend quota:
    # if the catalogue has already been renumbered, stop here.
    check_catalogue(load_manifest(), Image.open(ATLAS).convert("RGBA"))
    src = a.src
    if a.generate:
        if not a.spend_quota:
            die("--generate spends the owner's ChatGPT image quota. Pass "
                "--spend-quota as well if that is what you mean to do.")
        src = generate(a.generate, os.path.join(STORE, a.id + "_gen.png"), a.tab)
    if not src:
        die("give --src <png>, or --generate <prompt.txt> --spend-quota")
    if not os.path.exists(src):
        die("no such file: %s" % src)

    say("ingest       %s" % src)
    img = Image.open(src)
    say("             %dx%d %s" % (img.width, img.height, img.mode))

    crop = None
    if a.crop:
        try:
            x, y, w, h = (int(v) for v in a.crop.split(","))
        except ValueError:
            die("--crop wants x,y,w,h")
        crop = (x, y, x + w, y + h)

    size = tuple(int(v) for v in a.size.lower().split("x"))
    if size[0] > MAX_CONTENT[0] or size[1] > MAX_CONTENT[1]:
        die("--size %s does not fit the %dx%d slot with a rim around it "
            "(max %dx%d)." % (a.size, W, H, MAX_CONTENT[0], MAX_CONTENT[1]))

    say("condition")
    try:
        rgb, mask = condition(img, size, a.bg_tol, a.work, a.drop_shadow,
                              a.fill_holes, crop, cover=a.coverage,
                              min_blob=a.min_blob)
    except CutoutError as e:
        die("background removal failed: %s\n"
            "            Try --bg-tol, or --crop to a tighter box around the "
            "subject, or see docs/ADDING-ASSETS.md 'when the image is "
            "unusable'." % e)

    say("grade")
    graded = grade(rgb, a.luma_lo, a.luma_hi, a.saturate)
    ramps = choose_ramps(graded, mask, k=a.ramps,
                         forced=a.palette.split(",") if a.palette else None)
    for r in ramps:
        if r not in MT.PP:
            die("no such prop palette %r. Available: %s" % (r, ", ".join(MT.PP)))
    palette = []
    for r in ramps:
        palette += ramp_colours(r)
    for hexc in a.keep:
        s = hexc.lstrip("#")
        palette.append(tuple(int(s[i:i + 2], 16) for i in (0, 2, 4)))
    palette = list(dict.fromkeys(palette))
    quant, idx = quantise(graded, mask, palette)
    counts = np.bincount(idx, minlength=len(palette))
    say("  palette       %s -> %d colours, %d used"
        % (" + ".join(ramps), len(palette), int((counts > 0).sum())))
    for i in np.argsort(-counts)[:8]:
        if counts[i]:
            say("                #%02X%02X%02X %6d px" % (*palette[i], counts[i]))

    sprite = compose(quant, mask, outline=not a.no_outline,
                     shadow=not a.no_shadow, shadow_w=a.shadow_width)

    biomes = [a.biome] + [b for b in a.preview_on if b != a.biome]
    say("verify")
    warns = []
    ok = check_art(sprite, biomes, lambda m: warns.append(m) or say("  " + m))
    if a.biome != "placed":
        n = world_has(a.biome)
        if n is None:
            say("  world         not generated yet; run tools/make_world.py")
        else:
            say("  world         %d %s cells in data/world/overworld.json" % (n, a.biome))
            if n == 0:
                warns.append("WARN  zero cells")
                say("  WARN  the world has no %s. This prop is legal and will "
                    "never appear. Pick a material the generator produces, or "
                    "use --biome placed and put it somewhere on purpose." % a.biome)
                ok = False
    preview(sprite, a.id, biomes, os.path.join(STORE, "_preview_%s.png" % a.id))

    if warns and not a.force:
        die("%d check(s) failed. Look at the preview, fix the flags (or the "
            "source), and run again -- or pass --force if you disagree with "
            "the checks." % len(warns))

    if a.dry_run:
        # Never the registered filename: a dry run must not be able to leave a
        # sprite on disk that disagrees with the one already in the atlas.
        out = os.path.join(STORE, "_dryrun_%s.png" % a.id)
        sprite.save(out)
        say("dry run      wrote %s, catalogue untouched"
            % os.path.relpath(out, ROOT))
        return 0

    entry = {"id": a.id, "biome": a.biome, "density": a.density,
             "solid": bool(a.solid),
             "foot": [int(v) for v in a.foot.lower().split("x")]}
    say("register")
    reg = load_registry()
    man_len = len(load_manifest()["props"]["list"])
    authored = {p["id"] for p in reg["props"]}
    if reg["base_count"] is None:
        reg["base_count"] = man_len
    elif man_len != reg["base_count"] + len([p for p in reg["props"]
                                             if p["id"] in authored]):
        die("the catalogue has %d props but the registry expects %d "
            "(%d drawn + %d authored). tools/make_tiles.py has probably been "
            "re-run, which rewrites props.png and tiles.json from scratch. Run "
            "`tools/add_prop.py reapply` first."
            % (man_len, reg["base_count"] + len(reg["props"]),
               reg["base_count"], len(reg["props"])))

    # Append first. Only once the atlas and the manifest have accepted the
    # sprite does the authored copy on disk change -- otherwise a refused add
    # leaves a sprite file that disagrees with the atlas and `reapply` jams.
    sprite_path = os.path.join(STORE, a.id + ".png")
    idx, rows = append_prop(entry, sprite, replace=a.replace)
    sprite.save(sprite_path)
    say("  appended      %s at index %d, plane id %d (atlas %d rows)"
        % (a.id, idx, idx + 1, rows))

    rec = dict(entry, index=idx, plane=idx + 1, sprite=os.path.relpath(sprite_path, ROOT),
               source=os.path.relpath(os.path.abspath(src), ROOT),
               sprite_sha=sha(sprite), ramps=ramps,
               args=dict(size=a.size, bg_tol=a.bg_tol, luma=[a.luma_lo, a.luma_hi],
                         saturate=a.saturate, crop=a.crop, drop_shadow=a.drop_shadow,
                         coverage=a.coverage, fill_holes=a.fill_holes))
    reg["props"] = [p for p in reg["props"] if p["id"] != a.id] + [rec]
    reg["props"].sort(key=lambda p: p["index"])
    save_registry(reg)
    say("  registry      %s" % os.path.relpath(REGISTRY, ROOT))
    say("")
    say("Done. The prop is plane id %d. It is in the atlas and the catalogue; "
        "it is not in the world until tools/make_world.py runs." % (idx + 1))
    return 0 if ok else 1


def cmd_reapply(a):
    """make_tiles.py owns props.png and tiles.json and rewrites both from
    scratch. That is correct and must stay true. This puts the authored props
    back on top, in their recorded order, at their recorded plane ids -- or
    refuses, loudly, if it cannot."""
    reg = load_registry()
    if not reg["props"]:
        say("nothing authored")
        return 0
    man = load_manifest()
    lst = man["props"]["list"]
    check_catalogue(man, Image.open(ATLAS).convert("RGBA"))
    have = {e["id"] for e in lst}
    missing = [p for p in reg["props"] if p["id"] not in have]
    if not missing:
        say("all %d authored props are present" % len(reg["props"]))
        return cmd_verify(a)
    base = len(lst) - len([p for p in reg["props"] if p["id"] in have])
    if base != reg["base_count"]:
        die("the drawn catalogue is %d props but this registry was built "
            "against %d. Re-appending would give the authored props different "
            "plane ids than the world data already stores.\n"
            "            Either restore the drawn catalogue to %d props, or "
            "accept the renumbering deliberately: edit base_count in %s and "
            "re-generate the world."
            % (base, reg["base_count"], reg["base_count"],
               os.path.relpath(REGISTRY, ROOT)))
    for p in sorted(missing, key=lambda p: p["index"]):
        path = os.path.join(ROOT, p["sprite"])
        if not os.path.exists(path):
            die("the sprite for %r is gone (%s). It cannot be re-appended "
                "without re-running `add`." % (p["id"], p["sprite"]))
        sprite = Image.open(path).convert("RGBA")
        if sha(sprite) != p["sprite_sha"]:
            die("the sprite for %r has changed on disk since it was appended. "
                "Re-run `add --replace` deliberately rather than letting a "
                "silent edit into the atlas." % p["id"])
        entry = {k: p[k] for k in ("id", "biome", "density", "solid", "foot")}
        idx, rows = append_prop(entry, sprite)
        if idx != p["index"]:
            die("%r would land at index %d, not %d. Nothing further written."
                % (p["id"], idx, p["index"]))
        say("re-appended  %s at index %d, plane %d" % (p["id"], idx, idx + 1))
    return 0


def cmd_verify(a):
    man = load_manifest()
    atlas = Image.open(ATLAS).convert("RGBA")
    lst = check_catalogue(man, atlas)
    say("catalogue    %d props, %d rows, %d free slots"
        % (len(lst), man["props"]["rows"],
           man["props"]["rows"] * MT.PROP_COLS - len(lst)))
    reg = load_registry()
    bad = 0
    for p in reg["props"]:
        here = [e for e in lst if e["id"] == p["id"]]
        if not here:
            say("MISSING      %s (was plane %d) -- run `reapply`"
                % (p["id"], p["plane"]))
            bad += 1
            continue
        if here[0]["index"] != p["index"]:
            say("MOVED        %s is at index %d, registry says %d -- world data "
                "that stores plane %d now means something else"
                % (p["id"], here[0]["index"], p["index"], p["plane"]))
            bad += 1
            continue
        sx = (p["index"] % MT.PROP_COLS) * W
        sy = (p["index"] // MT.PROP_COLS) * H
        cur = atlas.crop((sx, sy, sx + W, sy + H))
        say("ok           %s  plane %d  %s" % (p["id"], p["plane"],
                                               "pixels match" if sha(cur) == p["sprite_sha"]
                                               else "PIXELS DIFFER"))
        if sha(cur) != p["sprite_sha"]:
            bad += 1
        if a.art:
            check_art(cur, [p["biome"]], lambda m: say("  " + m))
    return 1 if bad else 0


def cmd_list(a):
    man = load_manifest()
    reg = {p["id"] for p in load_registry()["props"]}
    for e in man["props"]["list"]:
        say("%3d  plane %3d  %-16s %-12s d=%-6s %-5s foot=%s%s"
            % (e["index"], e["plane"], e["id"], e["biome"], e["density"],
               "solid" if e["solid"] else "", e["foot"],
               "   <- authored" if e["id"] in reg else ""))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("add", help="put one image into the catalogue")
    p.add_argument("--src", help="source PNG (any size, any origin)")
    p.add_argument("--generate", metavar="PROMPT.TXT",
                   help="generate the source with art/chatgpt_gen.py instead")
    p.add_argument("--spend-quota", action="store_true",
                   help="required with --generate: this costs real image quota")
    p.add_argument("--tab", help="ChatGPT tab URL substring for --generate")
    p.add_argument("--id", required=True, help="catalogue id, e.g. well_covered")
    p.add_argument("--biome", required=True,
                   help="the material it scatters on, or 'placed' for hand placement")
    p.add_argument("--density", type=float, default=0.0,
                   help="per-walkable-cell chance; 0 for placed props")
    p.add_argument("--solid", action="store_true", help="blocks the footprint")
    p.add_argument("--foot", default="1x1", help="collision footprint in cells")
    p.add_argument("--size", default="32x36",
                   help="max content box inside the 64x96 slot (median hand-drawn "
                        "prop is 23x18, largest is 41x50)")
    p.add_argument("--crop", help="x,y,w,h of the subject in the source")
    p.add_argument("--bg-tol", type=float, default=0.10,
                   help="background residual tolerance, gamma-lifted units")
    p.add_argument("--work", type=int, default=512, help="working resolution")
    p.add_argument("--coverage", type=float, default=0.5,
                   help="area coverage a target pixel needs to be opaque")
    p.add_argument("--drop-shadow", action="store_true",
                   help="try to strip the render's own studio shadow (see "
                        "art/cutout.py: measured as not reliably a win)")
    p.add_argument("--fill-holes", type=float, default=0.0,
                   help="punch enclosed background regions this big or bigger")
    p.add_argument("--min-blob", type=float, default=0.02)
    p.add_argument("--luma-lo", type=float, default=14.0)
    p.add_argument("--luma-hi", type=float, default=124.0,
                   help="§2.6 reserves 130-150 for the character; stay under it")
    p.add_argument("--saturate", type=float, default=1.0)
    p.add_argument("--ramps", type=int, default=3,
                   help="how many of make_tiles.py's prop palettes to use")
    p.add_argument("--palette", help="force ramps, comma separated, e.g. stone,wood")
    p.add_argument("--keep", nargs="*", default=[],
                   help="hex colours to pin into the palette, as postprocess.py does")
    p.add_argument("--shadow-width", type=float,
                   help="contact shadow semi-width, px (default 72%% of the base)")
    p.add_argument("--no-shadow", action="store_true")
    p.add_argument("--no-outline", action="store_true")
    p.add_argument("--replace", action="store_true",
                   help="redraw an existing authored prop in place, keeping its "
                        "index and plane id")
    p.add_argument("--dry-run", action="store_true",
                   help="condition, grade and preview; do not touch the catalogue")
    p.add_argument("--force", action="store_true",
                   help="register even though a check failed")
    p.add_argument("--preview-on", nargs="*", default=[],
                   help="extra biomes to preview on -- use it to prove the rim "
                        "works on light ground and dark")
    p.set_defaults(fn=cmd_add)

    p = sub.add_parser("reapply", help="restore authored props after make_tiles.py")
    p.add_argument("--art", action="store_true")
    p.set_defaults(fn=cmd_reapply)

    p = sub.add_parser("verify", help="check the catalogue and the authored props")
    p.add_argument("--art", action="store_true", help="also re-run the art checks")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("list", help="the whole props catalogue")
    p.set_defaults(fn=cmd_list)

    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
