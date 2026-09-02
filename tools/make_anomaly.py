#!/usr/bin/env python3
"""Draw the anomaly: the animated tear the roguelite content hangs off.

    python3 tools/make_anomaly.py          # writes assets/anomaly/*

An anomaly is a location on the overworld you walk onto to open its task graph.
It has to be a *hole in the world*, not a decal lying on top of one; it has to
be findable from across a 7.5-tile screen; and its `tier` (0 near town, 4 at the
edge) has to be readable before you step on it, because that is the only
difficulty signal the player gets.

Same production as tools/make_tiles.py, and it imports that file rather than
copying it: the palette, the ramp grader, the one shadow colour and the Bayer
matrix are all the tileset's, so an anomaly is lit by the same light and graded
against the same value axis as the ground it sits in. Nothing here is a
free-floating hex.


WHY A SPRITE STRIP AND NOT A SHADER
-----------------------------------
The obvious answer is a ColorRect per visible anomaly carrying a ShaderMaterial,
because TileWorld._draw is immediate mode and cannot host one. It loses on a
detail of this renderer:

  * A Control's children draw *after* the parent's own _draw, and
    `show_behind_parent` puts them *before all of it* — under the terrain. There
    is no ordering that lands a child node between the ground and the Y-sorted
    scenery pass. So a shaded ColorRect either hides under the grass or paints
    over the character's legs when he walks onto it, and TileWorld's whole
    scenery pass exists to stop exactly that.

    A strip drawn from inside `_draw_scenery` at the anomaly's own row inherits
    the Y-sort for free and is correct in both directions: standing on the tear
    the character is drawn over it (his row's props are drawn before he is),
    walking behind it the tear is drawn over him. That is worth more than any
    shader effect available here.

  * Nodes are the thing to be careful with on a phone. Zero is cheaper than a
    handful, and this is zero: no node, no layout pass, no per-frame reposition,
    no shader compile on first sight of an anomaly (which on a mobile GL driver
    is a visible hitch at exactly the moment the player finds one).

  * The pipeline is already good at this, and the house rules — aliased, no
    smooth gradients, ordered dither instead of alpha ramps, one shadow colour —
    are rules a fragment shader would quietly break.

What a strip costs is memory and the risk of a visible loop point. Both are
measured rather than hoped at:

  * 24 frames x 5 tiers of 72x72 is one 1728x360 texture, 37 KB on disk and
    2.5 MB of RGBA in VRAM, plus 1.7 MB for the collapse. The tileset already
    ships a 512x3072 overlay atlas at 6.3 MB, so this is within the budget the
    project has already set for itself.

  * Every animated quantity here is a function of `phase = frame / FRAMES`
    built out of terms whose period divides the loop, and draw_anomaly()
    normalises phase, so frame FRAMES *is* frame 0. verify() measures the pixel
    churn at the wrap against the churn at every other step rather than
    trusting the claim -- which is how the first draft was caught rotating by
    turns/arms^2 instead of turns/arms and visibly jumping every two seconds.


HOW IT READS AS A HOLE
----------------------
Five devices, in the order the eye picks them up:

  1. It owns both ends of the value axis. The shipped overworld frame measures
     luma 11..122 with half of it between 34 and 53 (docs/ART-DIRECTION-
     OVERWORLD.md §1.3). The core here is luma ~4 and the accretion tip is
     ~198. It is simultaneously the darkest and the brightest thing on the
     screen, which is why it survives grass, sand, snow and flagstone without
     being redrawn for any of them.

  2. It owns a hue nothing else in the world has. The tier ramp runs
     accent_2 -> danger *the long way round the wheel*, through indigo, violet
     and magenta. The tileset's hues are greens, ochres, blue-greys and one
     cold blue; 240-324 degrees is empty. Interpolating straight through RGB
     instead would pass through mud-grey at tier 2, which is the one colour the
     world is already full of.

  3. The ground around it is broken. Three to seven 1px fractures run out from
     the rim into the stain, with the tear's light in the first pixels of each.
     This is the cheapest device in the file and close to the most effective:
     if the material around a mouth is intact, the mouth is a sticker lying on
     it. Static, because ground that crawled would read as animation noise.

  4. The pit is lit backwards from a mound. Everything else in this game is lit
     from the north-west with a lit crown and a shadowed underside. A pit's
     inner wall faces *inward*, so the wall that catches the light is the
     south-east one, at the *bottom* of the shape, and the north-west inner wall
     is the dark one. That inversion is most of what separates "hole" from
     "disc", and it is why the lit arc below is deliberately the opposite of
     blob() in make_tiles.py -- and why it is an arc and not a mass. The first
     draft lit the whole south-east wall and the result read as a beetle shell,
     because a lighter bottom-right on a dark oval is the signature of a convex
     object.

  5. The mouth does not spin. The torn rim is fixed — holes do not rotate their
     edges — and only the contents move. A shape whose outline rotates reads as
     a spinning object lying on the ground; a fixed opening with something
     turning inside it reads as a hole.

The falloff into the ground is the tileset's one shadow colour, ordered-dithered
rather than alpha-ramped, so the whole sheet uses two alpha values (255 and 118)
exactly like props.png and stays lossless under TEXTURE_FILTER_NEAREST.


HOW TIER READS
--------------
Five channels move together, so no single one has to carry it and none of them
is colour alone (docs/DESIGN.md: "colour is a second channel, never the only
one"):

    tier   mouth   stain   cracks  arms  turns/loop  motes  tip luma  hue
    0      17 px   29 px     3       2      0.50        3      138    201  ice
    1      20 px   35 px     4       2      0.50        5      152    242  indigo
    2      23 px   41 px     5       3      0.67        8      166    283  violet
    3      26 px   46 px     6       4      0.75       11      182    324  magenta
    4      29 px   52 px     7       5      0.80       15      198      5  coral

Mouth, stain and cracks are the across-the-screen read: a tier-4 tear breaks and
discolours a tile and a half of ground around itself, a tier-0 one barely leaves
its own cell. Arms, turns and motes are the up-close read: tier 0 is nearly
still — "a stall in the air", which is what data/anomalies/anomalies.json calls
it — and tier 4 is visibly churning. For scale, a tier-4 mouth is about the
width of the character's shoulders and its stain is about his height.


THE COLLAPSE
------------
16 frames, one shot, 1.33 s, ending fully transparent so the caller can simply
stop drawing. It never paints ground, only removes itself, so it is correct on
any material:

    0-3    the spin runs away — an eighth of a revolution to start, one and a
           quarter by the end. It is being pulled shut, not switched off, and
           the acceleration is the only thing that says so
    4-9    the mouth closes like an iris, eased so no two frames of it are the
           same size. Everything it gives up becomes transparent, so the real
           ground comes back rather than being repainted — which is what makes
           the one animation correct on grass and on flagstone alike. The
           ground stain does *not* shrink with it
    10-11  one flash: an aliased four-point star at the point, at the brightest
           value in the sheet
    12-14  a smooth 1px shockwave goes out through where the stain was, stepping
           tip -> hot -> arm down the ramp while the stain dithers away under it
    15     nothing. Fully transparent, so the caller just stops drawing.


HOW THE RENDERER USES IT
------------------------
Two textures and a frame index. assets/anomaly/AnomalyArt.gd is this written
out and ready to preload -- it holds the two textures, the frame maths and the
handful of in-flight collapses, has no class_name, and is three lines at the
call site:

    const AnomalyArt := preload("res://assets/anomaly/AnomalyArt.gd")
    var _anomalies := AnomalyArt.new()

    # inside _draw_scenery's inner loop, before the prop blit:
    var tier := world.anomaly_at(x, y)          # -1 where there is none
    if tier >= 0:
        _anomalies.draw_at(self, Vector2i(x, y), tier, cam, TILE, ZOOM)

    # in _process, next to the walk cycle:
    _anomalies.advance(delta)

and `_anomalies.collapse(cell)` when the mechanic clears one, `finished(cell)`
when it has played out. What that file does, spelled out, is this. Inside
TileWorld, near the props load:

    var _anom: Texture2D = load("res://assets/anomaly/anomaly.png")
    var _anom_end: Texture2D = load("res://assets/anomaly/anomaly_collapse.png")

    const ANOM := 72        # cell size in the sheet
    const ANOM_FPS := 12
    const ANOM_FRAMES := 24
    const ANOM_END_FRAMES := 16

One call, from inside `_draw_scenery`'s row loop — in the same place a prop is
drawn, so it inherits the Y-sort:

    for x in range(...):
        var tier := anomaly_at(x, y)          # -1 for none
        if tier >= 0:
            _draw_anomaly(x, y, tier, cam)
        var plane := world.prop_at(x, y)
        ...

    ## Centred on its cell, not anchored to its foot: it lies *in* the ground
    ## plane rather than standing on it, so its middle is the tile's middle.
    func _draw_anomaly(x: int, y: int, tier: int, cam: Vector2) -> void:
        if _anom == null:
            return
        var f := int(Time.get_ticks_msec() * ANOM_FPS / 1000) % ANOM_FRAMES
        var origin := Vector2(x * TILE + TILE / 2 - ANOM / 2,
                              y * TILE + TILE / 2 - ANOM / 2)
        draw_texture_rect_region(_anom,
            Rect2(origin * float(ZOOM) - cam, Vector2(ANOM, ANOM) * float(ZOOM)),
            Rect2(f * ANOM, clampi(tier, 0, 4) * ANOM, ANOM, ANOM))

The one-shot is the same blit against the other sheet with a clock that starts
when the anomaly is cleared, and the anomaly stops being drawn when it runs out:

    var _collapsing: Dictionary = {}          # Vector2i -> seconds elapsed

    func collapse(cell: Vector2i) -> void:
        _collapsing[cell] = 0.0

    # in _process, before queue_redraw():
    for cell in _collapsing.keys():
        _collapsing[cell] += delta
        if _collapsing[cell] >= float(ANOM_END_FRAMES) / ANOM_FPS:
            _collapsing.erase(cell)

    # in _draw_anomaly, replacing the two lines that pick the frame:
    var tex := _anom
    var f := int(Time.get_ticks_msec() * ANOM_FPS / 1000) % ANOM_FRAMES
    if _collapsing.has(cell):
        tex = _anom_end
        f = mini(int(float(_collapsing[cell]) * ANOM_FPS), ANOM_END_FRAMES - 1)

`Time.get_ticks_msec()` rather than an accumulated float on purpose: every
anomaly on screen is then on the same clock, which is what makes two of them in
frame look like two mouths of one thing rather than two independent props, and
it costs no state.

Per-frame cost: one draw_texture_rect_region per visible anomaly, from the same
atlas, in a loop that is already running. On the shipped world the densest
7.5x7.6-tile viewport contains one anomaly; the theoretical worst case is two.
No node, no material, no allocation, and the redraw was already happening every
frame for the walk cycle.

assets/anomaly/anomaly.json carries the same numbers as data, if the renderer
would rather read them than hold constants.


WHAT IS WRITTEN, AND WHERE
--------------------------
    assets/anomaly/anomaly.png            1728x360, 24 frames x 5 tiers
    assets/anomaly/anomaly_collapse.png   1152x360, 16 frames x 5 tiers
    assets/anomaly/anomaly.json           the constants above, as data
    art/anomaly/*.png, *.gif              the evidence

The previews live in art/ rather than assets/ because export_presets.cfg
excludes art/ and they are 1.7 MB against the sheets' 65 KB. They are composited
with PIL rather than screenshotted out of the game on purpose: the game blits
this sheet with TEXTURE_FILTER_NEAREST at an integer zoom over the same tiles
make_tiles.fill() produces, so an alpha_composite at integer scale is not an
approximation of what the device shows -- it is the same operation, pixel for
pixel. viewport_*.png are whole 8x8-tile screens with the character in them, at
the exact zoom the phone renders, which is the only test that answers "can you
find it and can you tell how bad it is".
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image

import make_tiles as T
from make_tiles import BAYER8, C, at_luma, hashv, luma, mix, rng_for

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "anomaly")
# Previews go to art/, not to assets/. art/ is the production side of the
# pipeline and export_presets.cfg excludes it, so the composites and the GIFs
# below cost the web build nothing -- and they are 1.7 MB, which is fifty times
# the two sheets that actually ship.
LOOK = os.path.join(ROOT, "art", "anomaly")

N = 72              # sheet cell, px. Wider than two tiles: the mouth is the
                    # small part of an anomaly and the torn, stained ground
                    # around it is what sits the mouth *in* the world.
FRAMES = 24         # loop length
FPS = 12            # 2.00 s per loop
END_FRAMES = 16     # collapse, 1.33 s
TIERS = 5

SQUASH = 0.78       # the mouth is an ellipse, matching the contact shadows in
                    # make_tiles.pshadow — the ground is not seen dead-on

TRANSPARENT = (0, 0, 0, 0)


# --- the tier table -----------------------------------------------------------
#
# `R` is the radius of the mouth before the rim's tear is applied; `stain` is the
# outer edge of the ground shadow as a multiple of it. Everything else is
# described in the module docstring's table.
#
# `turns` must be a whole number of arm-slots per loop -- rotation over the loop
# is 2*pi*turns/arms -- or the spiral does not land back on itself and the loop
# has a visible restart. `fall` (mote infalls per loop) must be a whole number
# for the same reason.

TIER = [
    dict(R=8.5,  stain=1.75, arms=2, turns=1, motes=3,  fall=1, tip=138, sharp=2.2),
    dict(R=10.0, stain=1.78, arms=2, turns=1, motes=5,  fall=1, tip=152, sharp=2.4),
    dict(R=11.5, stain=1.80, arms=3, turns=2, motes=8,  fall=2, tip=166, sharp=2.6),
    dict(R=13.0, stain=1.80, arms=4, turns=3, motes=11, fall=2, tip=182, sharp=2.8),
    dict(R=14.5, stain=1.80, arms=5, turns=4, motes=15, fall=3, tip=198, sharp=3.0),
]

# The five radial bands, as fractions of the mouth. These numbers are the whole
# read: a big hard-edged black pupil, a ring of light around it, a wall that is
# dark everywhere except one thin lit arc at the BOTTOM, and a black lip.
#
# The first draft made the wall a wide lit mass and the result read as a beetle
# shell -- a lighter bottom-right on a dark oval is the signature of a convex
# object, which is the exact opposite of the thing being built. A pit is dark
# almost everywhere with light on one thin edge.
CORE_U = 0.38       # event horizon. Dead black, hard edge, no dither.
WALL_U = 0.84       # below this is throat and accretion, above it is the wall
CREST_U = 0.90      # the lit arc lives between here and the lip, and nowhere else
LIP_U = 1.12        # the black rim of torn ground ends here


def tier_hue(tier):
    """accent_2 -> danger the long way round the wheel.

    Both ends are theme colours and so are the ramp's two anchors; only the path
    between them is chosen, and it is chosen to avoid grey. A straight RGB lerp
    between a cold blue and a warm red passes through #B4939A at tier 2 -- a
    dusty mid-grey, which is the exact colour the overworld is already made of
    and the one value the anomaly cannot afford to be."""
    import colorsys
    ha, sa, va = colorsys.rgb_to_hsv(*[c / 255.0 for c in C["accent_2"]])
    hb, sb, vb = colorsys.rgb_to_hsv(*[c / 255.0 for c in C["danger"]])
    t = tier / float(TIERS - 1)
    h = (ha + (hb + 1.0 - ha) * t) % 1.0
    rgb = colorsys.hsv_to_rgb(h, sa + (sb - sa) * t, va + (vb - va) * t)
    return tuple(int(round(c * 255)) for c in rgb)


def tier_ramp(tier):
    """Six values, sparsely used, exactly like make_tiles.ramp().

    The bottom of the ramp is not the bottom of the hole: `void` below is darker
    than anything a material is allowed to reach, because the core has to be the
    darkest pixel on the screen and the ground's own `deep` is not."""
    h = tier_hue(tier)
    tip = TIER[tier]["tip"]
    return {
        "void": mix(C["bg"], (0, 0, 0), 0.78),          # luma ~4
        "throat": at_luma(h, 9.0),
        "wall": at_luma(h, 26.0 + tier * 2.0),
        "wall_lit": at_luma(h, 54.0 + tier * 4.0),
        "arm": at_luma(h, tip * 0.42),
        "hot": at_luma(h, tip * 0.72),
        "tip": at_luma(h, float(tip)),
        "flare": at_luma(h, min(232.0, tip + 34.0)),
    }


# The lip. Near-black, and the *same* near-black every prop is outlined in, so
# the tear is cut out of the world by the same rule a tree is.
LIP = T.OUTLINE
# One pale pixel of intact ground curling up on the north-west edge. The rest of
# the shape is lit by the tear; this is the only thing in it lit by the sky, and
# without it the hole reads as printed on the ground rather than torn out of it.
LIP_LIT = at_luma(mix(C["muted"], C["accent_2"], 0.25), 96.0)

SHADOW = T.SHADOW
SHADOW_A = T.SHADOW_A

NORTHWEST = (-0.707, -0.707)
SOUTHEAST = (0.316, 0.949)      # where the inside of a pit catches the light


# --- geometry -----------------------------------------------------------------

def rim_shape(tier):
    """A torn mouth, as five harmonics of the angle.

    Periodic in theta by construction, so there is no seam where the tear closes
    on itself, and *static* -- see the docstring: a rotating outline reads as a
    spinning disc."""
    rng = rng_for("rim", tier)
    terms = [(k, 1.0 / (k * k), rng.uniform(0, math.tau)) for k in range(2, 7)]
    amp = 0.115 + 0.012 * tier
    norm = sum(a for _, a, _ in terms)
    return [(k, amp * a / norm, ph) for k, a, ph in terms]


def rim_at(shape, th):
    return 1.0 + sum(a * math.cos(k * th + ph) for k, a, ph in shape)


def polar(x, y):
    """Pixel centre to (radius, angle) in circle space -- the vertical axis is
    un-squashed first, so every radial test below is a plain circle test and the
    ellipse falls out once, here."""
    dx = (x + 0.5) - N * 0.5
    dy = ((y + 0.5) - N * 0.5) / SQUASH
    return math.hypot(dx, dy), math.atan2(dy, dx), dx, dy


def bayer(x, y, offset=0):
    return (BAYER8[(y + offset) % 8][(x + offset * 3) % 8] + 0.5) / 64.0


def quantize(v, ramp_keys, ramp):
    """Pick one of a handful of named values rather than interpolating.

    Smooth gradients are not this game's language and they do not survive
    nearest filtering at 3x; a five-step ramp does."""
    i = int(v * len(ramp_keys))
    return ramp[ramp_keys[min(len(ramp_keys) - 1, max(0, i))]]


# --- one frame ----------------------------------------------------------------

def draw_anomaly(tier, phase, scale=1.0, spin=0.0, fade=1.0, flash=0.0,
                 stain_scale=None):
    """One NxN frame.

    `phase` is 0..1 through the loop and every animated term below is periodic
    in it. `scale`, `spin`, `fade`, `flash` and `stain_scale` are only ever
    moved by the collapse; at their defaults this is the looping portal.

    `stain_scale` is the mouth scale the *ground* stain is measured from, which
    the collapse holds at 1.0 while the mouth shrinks. Discoloured ground does
    not un-discolour itself as the tear closes, and letting the shadow shrink
    with the mouth made the stain jump back out to full size on the flash frame.
    """
    p = TIER[tier]
    ramp = tier_ramp(tier)
    shape = rim_shape(tier)
    # Every animated term below has period 1 in `phase`; normalising here makes
    # that structural rather than a promise, so frame FRAMES *is* frame 0.
    phase = phase - math.floor(phase)
    img = Image.new("RGBA", (N, N), TRANSPARENT)
    if scale <= 0.02 or fade <= 0.0:
        return img
    put = img.putpixel

    R = p["R"] * scale
    R_stain = p["R"] * (scale if stain_scale is None else stain_scale)
    # `rot` is the phase of the arm field, not an angle: cos(arms*a - rot)
    # repeats when rot advances by a whole 2*pi, and the *picture* has then
    # turned by 2*pi/arms. So one whole `turns` per loop is turns/arms of a
    # revolution -- which is the "turns/loop" column in the docstring table --
    # and the loop closes exactly.
    rot = math.tau * p["turns"] * phase + spin * p["arms"]
    stain = p["stain"]
    # A slow breath on the accretion, one cycle per loop, so the brightness is
    # not constant between the arm passes.
    breath = 0.86 + 0.14 * math.sin(math.tau * phase)
    # The one thing that moves at tier 0: a brighter length of the lit crescent,
    # travelling once around the wall per loop.
    travel = math.tau * phase

    for y in range(N):
        for x in range(N):
            r, th, dx, dy = polar(x, y)
            tear = rim_at(shape, th)
            rim = R * tear
            outer = R_stain * tear * stain
            if r > outer:
                continue
            u = r / rim

            if u >= LIP_U:
                # --- the stain: the ground's own shadow, ordered-dithered.
                #
                # This is the whole of the "sits in the world" read from more
                # than a tile away. Dense at the rim and gone by the edge of the
                # cell, in the tileset's one shadow colour at its one alpha, so
                # it darkens grass and snow and flagstone by the same amount the
                # game already darkens them under a tree.
                inner = rim * LIP_U
                k = (outer - r) / max(0.001, outer - inner)
                cov = (0.30 + 0.70 * k ** 1.6) * (k ** 0.35) * fade
                if cov > bayer(x, y):
                    put((x, y), tuple(SHADOW) + (SHADOW_A,))
                elif tier >= 2 and k > 0.55 and fade >= 1.0:
                    # A little of the tear's light thrown back onto the ground.
                    # Sparse on purpose: dense enough to see, thin enough not to
                    # read as coloured noise on grass.
                    if (0.08 + 0.14 * tier / 4.0) * breath > bayer(x, y, 5):
                        put((x, y), tuple(ramp["wall"]) + (255,))
                continue

            if u >= 1.0:
                # --- the lip: ground torn open, pulled over the edge.
                #
                # Black, and the *same* black every prop in the game is outlined
                # in, so the tear is cut out of the world by the rule a tree is.
                # The one exception is a single pale pixel on the north-west
                # where intact ground curls up into the sky's light -- the only
                # thing in the shape not lit by the tear itself, and the thing
                # that stops it reading as printed on the ground.
                nx, ny = dx / max(r, 0.001), dy / max(r, 0.001)
                nw = nx * NORTHWEST[0] + ny * NORTHWEST[1]
                if u < 1.045 and nw > 0.50:
                    put((x, y), tuple(LIP_LIT) + (255,))
                else:
                    put((x, y), tuple(LIP) + (255,))
                continue

            if u < CORE_U:
                # --- past the horizon. A hard-edged black pupil, undithered,
                # the darkest pixel in the game. Everything else in the shape
                # exists to put an edge on this.
                put((x, y), tuple(ramp["void"]) + (255,))
                continue

            if u >= WALL_U:
                # --- the inner wall.
                #
                # Dark almost everywhere. The only lit part is one thin arc at
                # the BOTTOM, because a pit's south-east inner wall is the one
                # facing a north-west light -- the inverse of make_tiles.blob(),
                # which lights the crown. Widening this into a mass is what made
                # the first draft read as a shell instead of a hole, so it is
                # deliberately confined to the outer tenth of the mouth.
                nx, ny = dx / max(r, 0.001), dy / max(r, 0.001)
                lit = nx * SOUTHEAST[0] + ny * SOUTHEAST[1]
                lit = max(0.0, lit) ** 2.0
                lit *= 0.55 + 0.45 * math.cos(th - travel)   # the travelling length
                c = ramp["throat"]
                if u >= CREST_U:
                    if lit > 0.42:
                        c = ramp["wall_lit"]
                    elif lit > 0.16:
                        c = ramp["wall"]
                elif lit > 0.55:
                    c = ramp["wall"]
                put((x, y), tuple(c) + (255,))
                continue

            # --- the throat and its accretion.
            #
            # A logarithmic spiral: the arm's angle shifts with log(r), so the
            # arms wind in rather than radiating, and the whole field turns by a
            # whole number of arm-slots over the loop.
            a = th + 2.35 * math.log(max(r, 1.2) / max(R, 1.0))
            s = 0.5 + 0.5 * math.cos(p["arms"] * a - rot)
            s = s ** p["sharp"]
            # Radial envelope: nothing at the horizon's edge, brightest a third
            # of the way out, gone by the wall. Plus a floor, so even tier 0 --
            # whose two arms are nearly still -- keeps a continuous ring of light
            # around the pupil. At 29 source pixels across, a ring is legible and
            # a pattern of arms alone is not.
            e = math.sin(math.pi * min(1.0, max(0.0, (u - CORE_U) / (WALL_U - CORE_U))))
            v = (0.26 + 0.74 * s) * (e ** 0.55) * breath
            if v > 0.72:
                c = ramp["tip"]
            elif v > 0.50:
                c = ramp["hot"]
            elif v > 0.30:
                c = ramp["arm"]
            elif v > 0.13 + 0.10 * bayer(x, y, 4):
                c = ramp["wall"]
            else:
                c = ramp["throat"]
            put((x, y), tuple(c) + (255,))

    if scale > 0.5:
        _cracks(img, tier, R, shape, ramp, phase)
    _motes(img, tier, phase, R, shape, ramp)
    if flash > 0.0:
        _flash(img, ramp, flash)
    return img


def _cracks(img, tier, R, shape, ramp, phase):
    """Ground broken outward from the rim.

    The single cheapest thing that says "hole in the world" rather than "disc on
    the world": if the material around the mouth is intact, the mouth is a
    sticker. A few 1px fractures running out into the stain, in the same black
    the lip is drawn in, with the tear's light showing in the first pixel or two
    of each -- the crack goes all the way through.

    The fractures themselves never move -- ground that crawled would read as
    animation noise at 3x, and the ground is not what is moving here. Only the
    light in their mouths breathes, once per loop, each crack on its own phase
    so they do not blink in unison."""
    rng = rng_for("cracks", tier)
    n = 3 + tier
    for i in range(n):
        th = (i + rng.uniform(0.15, 0.85)) * math.tau / n
        r0 = R * rim_at(shape, th) * 1.0
        r1 = R * rim_at(shape, th) * (1.28 + rng.random() * (TIER[tier]["stain"] - 1.32))
        drift = rng.uniform(-0.16, 0.16)
        r = r0
        step = 0.9
        lit = 2 + tier // 2
        glow = 0.5 + 0.5 * math.cos(math.tau * phase + i * 2.399)
        j = 0
        while r < r1:
            th += drift * (rng.random() - 0.45) * 0.6
            x = int(N * 0.5 + math.cos(th) * r)
            y = int(N * 0.5 + math.sin(th) * r * SQUASH)
            if 0 <= x < N and 0 <= y < N:
                # The first pixels glow: light coming up out of the fracture.
                # After that it is just broken ground.
                if j >= lit:
                    c = LIP
                elif glow > 0.66:
                    c = ramp["hot"]
                elif glow > 0.30:
                    c = ramp["arm"]
                else:
                    c = ramp["wall"]
                img.putpixel((x, y), tuple(c) + (255,))
            r += step
            j += 1


def _motes(img, tier, phase, R, shape, ramp):
    """Things falling in.

    Each mote's life is `frac(phase * fall + offset)` with `fall` a whole
    number, so the set of motes at phase 1 is the set at phase 0. It spawns out
    on the dark lip where a dim pixel is invisible and brightens as it falls, so
    nothing pops into existence."""
    p = TIER[tier]
    rng = rng_for("motes", tier)
    for i in range(p["motes"]):
        th0 = rng.uniform(0, math.tau)
        off = rng.random()
        swirl = rng.uniform(1.6, 2.8)
        t = (phase * p["fall"] + off) % 1.0
        # Accelerating infall: slow out at the rim, fast at the horizon.
        e = t * t * (1.6 - 0.6 * t)
        rim = R * rim_at(shape, th0)
        r = rim * (1.10 + (CORE_U - 1.10) * min(1.0, e))
        th = th0 + swirl * e
        x = int(N * 0.5 + math.cos(th) * r)
        y = int(N * 0.5 + math.sin(th) * r * SQUASH)
        if not (0 <= x < N and 0 <= y < N):
            continue
        # Brighter the further in it has fallen, and dim for its first tenth of
        # life so it emerges out of the lip rather than appearing on it.
        b = min(1.0, e * 1.8) * min(1.0, t * 10.0)
        c = ramp["tip"] if b > 0.72 else (ramp["hot"] if b > 0.42 else
                                          (ramp["arm"] if b > 0.16 else ramp["wall"]))
        img.putpixel((x, y), tuple(c) + (255,))
        if tier >= 3 and b > 0.55 and x + 1 < N:
            # A one-pixel tail, in the direction of travel, only where the mote
            # is moving fast enough that a single pixel would strobe.
            tx = int(N * 0.5 + math.cos(th - 0.16) * r * 1.03)
            ty = int(N * 0.5 + math.sin(th - 0.16) * r * 1.03 * SQUASH)
            if 0 <= tx < N and 0 <= ty < N:
                img.putpixel((tx, ty), tuple(ramp["arm"]) + (255,))


def _flash(img, ramp, k):
    """The collapse's one bright beat: an aliased four-point star, which is how
    this project already draws a highlight, plus a hard ring."""
    c = tuple(ramp["flare"]) + (255,)
    arm = int(round(3 + 13 * k))
    cx = cy = N // 2
    for i in range(arm + 1):
        w = 1 if i > arm * 0.45 else 2
        for j in range(-w // 2, w // 2 + 1):
            for (x, y) in ((cx + i, cy + j), (cx - i, cy + j),
                           (cx + j, cy + int(i * SQUASH)),
                           (cx + j, cy - int(i * SQUASH))):
                if 0 <= x < N and 0 <= y < N:
                    img.putpixel((x, y), c)


def collapse_frame(tier, f):
    """One frame of the one-shot. See the docstring for the beat sheet.

    It never paints ground. Everything it removes it removes by becoming
    transparent, so it is correct on grass and on flagstone without knowing
    which it is standing on."""
    n = END_FRAMES
    t = f / float(n - 1)
    p = TIER[tier]
    ramp = tier_ramp(tier)

    # The spin runs away quadratically the whole way through -- an eighth of a
    # revolution at the start, one and a quarter by the time the mouth is gone.
    # It is being pulled shut, not switched off, and the acceleration is the
    # only thing that says so.
    spin = math.tau * (0.12 + 1.15 * t * t)
    phase = (t * 2.0) % 1.0

    if f <= 9:
        # Beats 1 and 2, run together: three frames at full size while the spin
        # winds up, then the iris closes over the next six. The shrink is eased
        # so no two frames of it are the same size -- the first draft held for
        # five frames and then dropped to nothing in two, and a shape that stops
        # existing between frames reads as a dropped frame rather than a
        # collapse.
        k = max(0.0, (f - 3) / 6.0)
        scale = 1.0 - 0.90 * (k ** 1.25)
        img = draw_anomaly(tier, phase, scale=scale, spin=spin,
                           fade=1.0 - 0.30 * k, stain_scale=1.0)
        if f >= 8:
            _flash(img, ramp, (f - 7) * 0.12)
        return img

    img = Image.new("RGBA", (N, N), TRANSPARENT)

    # The ground goes on healing after the mouth is gone. Without this the stain
    # vanishes on one frame and the collapse ends with a hole in the shadow.
    _residual(img, p["R"] * p["stain"], 0.62 - 0.125 * (f - 10))

    if f <= 11:
        # Beat 3: one flash. A four-point star, aliased, which is how this
        # project already draws a highlight.
        _flash(img, ramp, 1.0 if f == 10 else 0.62)
        _ring(img, ramp, r=(3.0 if f == 10 else 8.0), tone="tip")
        return img

    # Beat 4: a shockwave going out through where the stain was, dimming down
    # the ramp rather than dissolving. A ring thinned by dither coverage reads
    # as a dotted outline of a shape -- which is what the first draft did, and
    # it looked like a lasso lying on the flagstones.
    _ring(img, ramp, r=(9.0, 15.0, 21.0)[f - 12] if f < 15 else 0.0,
          tone=("hot", "arm", "wall")[f - 12] if f < 15 else "")
    return img


def _residual(img, r, cov):
    """What is left of the stain, dithered away over the last frames."""
    if cov <= 0.0:
        return
    for y in range(N):
        for x in range(N):
            rr, _, _, _ = polar(x, y)
            if rr > r:
                continue
            if cov * (1.0 - (rr / r) ** 2) ** 0.5 > bayer(x, y):
                img.putpixel((x, y), tuple(SHADOW) + (SHADOW_A,))


def _ring(img, ramp, r, tone):
    """A smooth 1px ellipse. Deliberately *not* torn like the mouth is: the
    mouth is a wound in the ground and the shockwave is a wave."""
    if r <= 0.0 or not tone:
        return
    c = tuple(ramp[tone]) + (255,)
    for y in range(N):
        for x in range(N):
            rr, _, _, _ = polar(x, y)
            if abs(rr - r) <= 1.1:
                img.putpixel((x, y), c)


# --- sheets -------------------------------------------------------------------

def build():
    loop = Image.new("RGBA", (N * FRAMES, N * TIERS), TRANSPARENT)
    end = Image.new("RGBA", (N * END_FRAMES, N * TIERS), TRANSPARENT)
    frames = {}
    for tier in range(TIERS):
        for f in range(FRAMES):
            im = draw_anomaly(tier, f / float(FRAMES))
            frames[(tier, f)] = im
            loop.paste(im, (f * N, tier * N))
        for f in range(END_FRAMES):
            end.paste(collapse_frame(tier, f), (f * N, tier * N))
    return loop, end, frames


# --- verification -------------------------------------------------------------

def verify(frames):
    """Numbers, not impressions. Three things can go wrong and all three are
    invisible in a contact sheet: a loop that jumps, a shape that clips the
    cell, and motion fast enough to strobe."""
    ok = True

    for tier in range(TIERS):
        # 1. Seamless. draw_anomaly() normalises phase, so frame FRAMES is frame
        #    0 by construction -- the thing that can still go wrong is a term
        #    that is not periodic, which shows up as the wrap being a bigger
        #    step than any other. Measured as changed pixels, not asserted.
        steps = [_changed_fraction(frames[(tier, f)],
                                   frames[(tier, (f + 1) % FRAMES)])
                 for f in range(FRAMES)]
        wrap = steps[-1]
        typical = sorted(steps[:-1])[len(steps) // 2]
        if wrap > typical * 1.6 + 0.002:
            print("  !! tier %d jumps at the loop point: %.1f%% against a "
                  "typical %.1f%%" % (tier, wrap * 100, typical * 100))
            ok = False

        # 2. Nothing touches the edge of the cell, or the stain has a straight
        #    cut across it.
        for f in range(FRAMES + END_FRAMES):
            im = frames[(tier, f)] if f < FRAMES \
                else collapse_frame(tier, f - FRAMES)
            px = im.load()
            for i in range(N):
                for (x, y) in ((i, 0), (i, N - 1), (0, i), (N - 1, i)):
                    if px[x, y][3] != 0:
                        print("  !! tier %d frame %d clips the cell at %d,%d"
                              % (tier, f, x, y))
                        ok = False
                        break

        # 3. Strobe. How far the arms travel between frames; over half an
        #    arm-spacing and the spiral appears to run backwards.
        worst = max(steps)
        p = TIER[tier]
        rev = p["turns"] / float(p["arms"]) / FRAMES
        spacing = math.tau * (0.9 * p["R"]) / p["arms"]
        step = math.tau * (0.9 * p["R"]) * rev
        print("  tier %d  mouth %2d px  stain %2d px  arms %d  %.2f rev/loop  "
              "%.2f px/frame (arm spacing %.1f)  churn %.0f%%"
              % (tier, int(2 * p["R"]), int(2 * p["R"] * p["stain"]), p["arms"],
                 p["turns"] / float(p["arms"]), step, spacing, worst * 100))
        if step > spacing * 0.5:
            print("  !! tier %d strobes: %.2f px/frame against %.1f px spacing"
                  % (tier, step, spacing))
            ok = False

    # 4. It owns both ends of the value axis. The shipped overworld frame is
    #    luma 11..122 (docs/ART-DIRECTION-OVERWORLD.md 1.3).
    for tier in range(TIERS):
        px = frames[(tier, 0)].load()
        lo, hi = 255.0, 0.0
        for y in range(N):
            for x in range(N):
                c = px[x, y]
                if c[3] != 255:
                    continue
                lo = min(lo, luma(c[:3]))
                hi = max(hi, luma(c[:3]))
        print("  tier %d  luma %.0f..%.0f   hue #%02X%02X%02X"
              % ((tier, lo, hi) + tier_hue(tier)))
        if lo > 9.0 or hi < 120.0:
            print("  !! tier %d does not beat the world at both ends" % tier)
            ok = False

    # 5. The collapse ends on nothing, or the caller has to special-case it.
    for tier in range(TIERS):
        last = collapse_frame(tier, END_FRAMES - 1)
        if last.getbbox() is not None:
            print("  !! tier %d collapse leaves %s behind"
                  % (tier, last.getbbox()))
            ok = False

    print("  verify: %s" % ("ok" if ok else "FAILED"))
    return ok


def _changed_fraction(a, b):
    pa, pb = a.load(), b.load()
    n = 0
    for y in range(N):
        for x in range(N):
            if pa[x, y] != pb[x, y]:
                n += 1
    return n / float(N * N)


# --- previews -----------------------------------------------------------------
#
# See "WHAT IS WRITTEN, AND WHERE" in the module docstring for why these are
# composited rather than screenshotted, and why they go to art/ and not assets/.

GROUNDS = ["grass_short", "snow", "sand", "floor_stone"]


def _patch(material, tiles_w, tiles_h, seed=7):
    grid = [[material] * tiles_w for _ in range(tiles_h)]
    ov = {}
    for y in range(tiles_h):
        for x in range(tiles_w):
            for key in T.overlay_plan(grid, x, y, seed):
                ov[key] = None
    tiles = {}
    for (mat, kind, mask, v) in ov:
        tiles[(mat, kind, mask, v)] = T.overlay_tile(mat, kind, mask, v)
    return T.render_patch(grid, tiles, seed=seed)


def _at(img, frame, cx, cy):
    """Exactly the offset the GDScript snippet uses: centred on the cell."""
    img.alpha_composite(frame, (cx * T.N + T.N // 2 - N // 2,
                                cy * T.N + T.N // 2 - N // 2))
    return img


def _place(patch, frame, cx, cy):
    return _at(patch.copy(), frame, cx, cy)


_PLAYER = None


def _hero(img, cx, cy):
    """The character, at his real size and his real anchor, standing on a cell.

    In these previews only, and only because "does it read at a glance" is a
    question about scale and the only scale reference this game has is him."""
    global _PLAYER
    if _PLAYER is None:
        _PLAYER = Image.open(os.path.join(ROOT, "assets", "sprites",
                                          "player.png")).convert("RGBA")
    fw, fh = 32, 48
    img.alpha_composite(_PLAYER.crop((0, 0, fw, fh)),
                        (cx * T.N + (T.N - fw) // 2, cy * T.N + T.N - fh))
    return img


def previews(frames):
    written = []

    def save(img, name):
        img.save(os.path.join(LOOK, name))
        written.append(name)

    # 1. Every tier on every ground, at the zoom the phone shows, with the
    #    character beside it. Grass, snow, sand and flagstone are the four
    #    extremes of the ground set: the darkest walkable field, the lightest,
    #    the warmest and the one closest in value to the tear's own black.
    w, h = 4, 4
    cell = w * T.N * 3
    sheet = Image.new("RGBA", (cell * len(GROUNDS), cell * TIERS))
    for gi, g in enumerate(GROUNDS):
        base = _patch(g, w, h)
        for tier in range(TIERS):
            im = _place(base, frames[(tier, 5)], 1, 2)
            _hero(im, 3, 2)
            im = im.resize((cell, cell), Image.NEAREST)
            sheet.paste(im, (gi * cell, tier * cell))
    save(sheet, "grounds.png")

    # 2. Every frame of the loop, so the motion can be read off a still.
    for tier in (0, 4):
        base = _patch("grass_short", 3, 3)
        cell = 3 * T.N * 2
        cols = 8
        rows = (FRAMES + cols - 1) // cols
        sheet = Image.new("RGBA", (cell * cols, cell * rows))
        for f in range(FRAMES):
            im = _place(base, frames[(tier, f)], 1, 1)
            im = im.resize((cell, cell), Image.NEAREST)
            sheet.paste(im, ((f % cols) * cell, (f // cols) * cell))
        save(sheet, "loop_t%d.png" % tier)

    # 3. The collapse, frame by frame.
    base = _patch("floor_stone", 3, 3)
    cell = 3 * T.N * 2
    cols = 8
    sheet = Image.new("RGBA", (cell * cols, cell * 2))
    for f in range(END_FRAMES):
        im = _place(base, collapse_frame(4, f), 1, 1)
        im = im.resize((cell, cell), Image.NEAREST)
        sheet.paste(im, ((f % cols) * cell, (f // cols) * cell))
    save(sheet, "collapse.png")

    # 4. One real viewport. TileWorld at ZOOM 3 shows the player 7.5 x 7.6 tiles
    #    (docs/ART-DIRECTION-OVERWORLD.md 1.0), so this is the whole screen: the
    #    across-the-screen read, which is the thing a contact sheet cannot show,
    #    with the character in it for scale and a tier 0 and a tier 4 in frame
    #    together so the difficulty read can be judged rather than asserted.
    for gi, g in enumerate(GROUNDS):
        base = _patch(g, 8, 8, seed=3)
        im = _place(base, frames[(0, 5)], 1, 6)
        _at(im, frames[(2, 5)], 6, 5)
        _at(im, frames[(4, 5)], 5, 1)
        _hero(im, 3, 3)
        save(im.resize((8 * T.N * 3, 8 * T.N * 3), Image.NEAREST),
             "viewport_%s.png" % g)

    # 5. Something that actually moves, for a human.
    for tier in (0, 2, 4):
        base = _patch("grass_short", 3, 3)
        gif = []
        for f in range(FRAMES):
            im = _place(base, frames[(tier, f)], 1, 1)
            gif.append(im.resize((3 * T.N * 3, 3 * T.N * 3), Image.NEAREST)
                       .convert("P", palette=Image.ADAPTIVE, colors=64))
        gif[0].save(os.path.join(LOOK, "anomaly_t%d.gif" % tier),
                    save_all=True, append_images=gif[1:], loop=0,
                    duration=int(1000 / FPS), disposal=2)
        written.append("anomaly_t%d.gif" % tier)

    base = _patch("grass_short", 3, 3)
    seq = [_place(base, frames[(4, f)], 1, 1) for f in range(FRAMES)] + \
          [_place(base, collapse_frame(4, f), 1, 1) for f in range(END_FRAMES)] + \
          [base.copy()] * 6
    gif = [im.resize((3 * T.N * 3, 3 * T.N * 3), Image.NEAREST)
           .convert("P", palette=Image.ADAPTIVE, colors=64) for im in seq]
    gif[0].save(os.path.join(LOOK, "anomaly_collapse.gif"), save_all=True,
                append_images=gif[1:], loop=0, duration=int(1000 / FPS),
                disposal=2)
    written.append("anomaly_collapse.gif")
    return written


def main():
    os.makedirs(OUT, exist_ok=True)
    os.makedirs(LOOK, exist_ok=True)
    loop, end, frames = build()
    loop.save(os.path.join(OUT, "anomaly.png"))
    end.save(os.path.join(OUT, "anomaly_collapse.png"))
    meta = dict(
        _comment="Written by tools/make_anomaly.py. Read that file before "
                 "changing anything here; these are its constants, not a "
                 "second copy of them.",
        cell=N, frames=FRAMES, fps=FPS, collapse_frames=END_FRAMES,
        tiers=TIERS, anchor="centre",
        loop="anomaly.png", collapse="anomaly_collapse.png",
        tier_hue=["#%02X%02X%02X" % tier_hue(t) for t in range(TIERS)],
        mouth_px=[int(2 * TIER[t]["R"]) for t in range(TIERS)],
        stain_px=[int(2 * TIER[t]["R"] * TIER[t]["stain"]) for t in range(TIERS)],
    )
    with open(os.path.join(OUT, "anomaly.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")
    print("anomaly.png          %d x %d  (%d frames x %d tiers)"
          % (loop.size[0], loop.size[1], FRAMES, TIERS))
    print("anomaly_collapse.png %d x %d  (%d frames x %d tiers)"
          % (end.size[0], end.size[1], END_FRAMES, TIERS))
    verify(frames)
    for name in previews(frames):
        print("  art/anomaly/%s" % name)


if __name__ == "__main__":
    main()
