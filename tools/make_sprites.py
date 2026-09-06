#!/usr/bin/env python3
"""Draw the player walk cycle as true pixel art.

The pipeline skill's hard finding is that the image model cannot hold an
identity across frames -- sprite sheets come back as labelled contact sheets
with wandering column pitch and a silhouette that redraws every frame. So the
character is authored, the same way tools/make_glyphs.py authors the icons and
tools/make_tiles.py authors the ground.

The subject is the traveller who wakes in the Waking Room every loop: hooded,
cloaked, a pack and a scarf, boots. He is now 32 x 48 -- one tile wide, one and
a half tall -- and at that size he can have legs, arms outside his own outline,
and a face.

Four decisions a loader depends on, all inherited from the 24x32 sheet and all
still true:

  Column 0 is the neutral pose, not the first step. A character standing still
  shows column 0, so idle needs no lookup table and no special case. The walk
  therefore plays 1, 0, 2, 0 -- step-left, neutral, step-right, neutral.
  Playing 0, 1, 2 gives a limp: there is no neutral between the two steps.

  `right` is a horizontal mirror of `left`. The figure is symmetric apart from
  the shoulder the satchel strap crosses; a separately drawn right-facing set
  would only be an extra chance for the two to drift apart.

  The sole sits on a fixed row in every frame. A bob applied to the whole
  figure looks better in isolation and worse in the game, because idle is the
  pose you see most. The step frames compress the *upper* body by one pixel
  instead, and the lifted foot is drawn short rather than drawn somewhere new.

  The outline is derived from the alpha mask, not drawn, so the silhouette is
  guaranteed closed no matter what the pose does.

What changed in the rework, and why -- measured, not asserted:

  SIZE. 24x32 is 0.75 x 1.0 tiles against a genre convention of 1.0 x 1.5
  (LPC) to 1.6 x 2.0 (Slynyrd). There was no room for legs in 30 rows once the
  hood took 10, so the silhouette was a bollard. 32x48 is exactly LPC's ratio
  against our 32px tile, and 32 wide -- rather than the 28 the art direction
  guessed -- because `TileWorld` centres the frame on the tile with
  `(TILE - FRAME_W) * 0.5`: at 32 that offset is zero, the sprite grid *is* the
  tile grid, and the contact shadow gets to spread past the boots without being
  clipped by the frame edge. The four extra columns cost 768 bytes.

  VALUE. The old sheet meaned 54 luma. Measured against the current tileset the
  ground runs 34 (grass_tall) to 72 (snow), so 54 sits *inside* the ground on
  grass and *below* it across the whole desert and mountain half of the world.
  No single mid-tone can separate from a 38-point spread. So he is bracketed
  instead: cloth lit at 90-178, folds at 30-43, and a hard near-black rim at
  luma 9 between him and whatever he is standing on. On every walkable material
  at least 45% of him reads light against it and at least 26% dark. The rim is
  what makes one sprite work on grass and on snow -- exactly the mechanism every
  standing prop in make_tiles.py uses, and it is the same colour and the same
  8-connected pass.

  SHADOW. He had none and he floated. He now carries a baked contact shadow in
  the one shadow colour at the one alpha the tiles use, centred under the sole,
  filling only pixels the figure and its rim have not claimed. Centred, not
  offset, for the same reason props are: he can stand anywhere.

Colours are read from data/themes/firstlight.json and mixed. Nothing here is a
free-floating hex -- see COOL / WARM / SKIN / SHADOW.

    python3 tools/make_sprites.py      # writes assets/sprites/*.png
"""
import hashlib
import json
import math
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "sprites")
TILES = os.path.join(ROOT, "assets", "tiles")
THEME = os.path.join(ROOT, "data", "themes", "firstlight.json")

FW, FH = 32, 48                      # one frame -- 1.0 x 1.5 tiles
FACINGS = ["down", "up", "left", "right"]
FRAMES = ["neutral", "step_left", "step_right"]
WALK_ORDER = [1, 0, 2, 0]            # columns, in playback order

CX = 15.5                            # the frame's centre line, between 15 and 16
SOLE = 44                            # the row the planted boot ends on, always
GROUND = 47                          # the shadow's last row == the tile's last row

CLEAR = (0, 0, 0, 0)
BLACK = (0, 0, 0)


def theme_colors():
    with open(THEME, encoding="utf-8") as f:
        colors = json.load(f)["colors"]
    return {k: tuple(int(v.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
            for k, v in colors.items()}


C = theme_colors()


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


# --- the ramps ----------------------------------------------------------------
#
# Three of them, which is the art direction's ask: the cloak is cool, the face
# is warm, and one saturated garment carries the accent. The old sheet had ten
# colours of which eight were one blue-grey ramp, and it read as a grey figure
# in a grey-green-brown world.
#
# COOL runs 178 155 146 128 108 90 43 30, so "one step darker" is a real step
# and the sculpting pass below can just add 1 to an index. It is deliberately
# NOT an even ramp: there is a hole between 43 and 90, because sand (62), ice
# (66), dune (68) and snow (72) all live in it, and a cloak pixel in that band
# is a cloak pixel that dissolves into the desert or the mountain. So the cloth
# -- which is most of him -- is pushed to either side of the ground rather than
# spanning it: lit at 90-178, folds at 30-43, rim at 9. Only the leather lands
# inside the hole, and leather is warm brown against ground that is not.
COOL = [
    mix(C["muted"], C["text"], 0.40),   # 0  178  crown specular
    mix(C["muted"], C["text"], 0.12),   # 1  155  lit
    C["muted"],                         # 2  146
    mix(C["line"], C["muted"], 0.80),   # 3  128  the cloak's own value
    mix(C["line"], C["muted"], 0.58),   # 4  108
    mix(C["line"], C["muted"], 0.38),   # 5   90
    mix(C["line"], C["bg"], 0.35),      # 6   43
    mix(C["line"], C["bg"], 0.70),      # 7   30  deepest fold
]

# The one saturated garment: the scarf at the throat and the pack's flap. This
# is the only place in the sheet with real chroma, and it is what stops the
# figure reading as greyscale. Kept small -- about 6% of him.
WARM = [
    mix(C["accent"], C["text"], 0.20),  # 0
    C["accent"],                        # 1
    mix(C["accent"], C["line"], 0.40),  # 2
    mix(C["accent"], C["bg"], 0.62),    # 3
]

# Leather: pack, boots, gloves. Warm but dark, so the figure is heavy where it
# meets the ground -- which is half of why he stops looking pasted on.
LEATHER = [
    mix(C["accent"], C["bg"], 0.42),    # 0  111
    mix(C["accent"], C["bg"], 0.60),    # 1   83
    mix(C["accent"], C["bg"], 0.76),    # 2   56
    mix(C["accent"], C["bg"], 0.88),    # 3   39
]

# Skin, under the hood, in the hood's own shadow. Two eye pixels sit near the
# rim's value; the nose catches the only unshadowed skin on the figure.
_SKIN = mix(C["accent"], C["muted"], 0.30)
SKIN = [
    _SKIN,                              # 0  lit
    mix(_SKIN, C["bg"], 0.45),          # 1
    mix(_SKIN, C["bg"], 0.66),          # 2  the face, in the brim's shadow
    mix(C["bg"], BLACK, 0.30),          # 3  eyes
]

# Identical to make_tiles.py's OUTLINE and SHADOW/SHADOW_A. Deliberately the
# same numbers, not similar ones: the character and the props have to look like
# they are lit by the same sun and standing on the same ground.
OUTLINE = mix(C["bg"], BLACK, 0.55)
SHADOW = mix(C["bg"], BLACK, 0.45)
SHADOW_A = 118


def cool(i):
    return COOL[max(0, min(len(COOL) - 1, i))]


# --- drawing ------------------------------------------------------------------

class Frame:
    """A 32x48 cel. Draws body colours only; the rim is added afterwards from
    the alpha mask, so the silhouette is guaranteed closed no matter what the
    pose does."""

    def __init__(self):
        self.img = Image.new("RGBA", (FW, FH), CLEAR)

    def px(self, x, y, c):
        if 0 <= x < FW and 0 <= y < FH:
            self.img.putpixel((int(x), int(y)), tuple(c) + (255,))

    def row(self, y, x0, x1, c):
        for x in range(int(x0), int(x1) + 1):
            self.px(x, y, c)

    def col(self, x, y0, y1, c):
        for y in range(int(y0), int(y1) + 1):
            self.px(x, y, c)

    def box(self, x0, y0, x1, y1, c):
        for y in range(int(y0), int(y1) + 1):
            self.row(y, x0, x1, c)


def sculpt(f, spans, keys, dy=0, hi=2, sh=3):
    """Paint a run of horizontal spans and light it from the north-west.

    `spans` is the pure geometry -- (y, x0, x1) -- and `keys` gives the base
    COOL index per row, so the silhouette and the shading are edited
    separately. Each row gets its base value, then the leftmost `hi` pixels go
    one step lighter and the rightmost `sh` go one step darker, with the last
    column two steps darker.

    Doing this generically rather than by hand is the difference between this
    file and the 24x32 one: there, every lit pixel was its own tuple, and the
    comments record what that cost ("it read as a postbox"). Here the form is
    one function and the pose tables are geometry only.
    """
    if isinstance(keys, int):
        keys = [keys] * len(spans)
    for (y, x0, x1), k in zip(spans, keys):
        yy = y + dy
        f.row(yy, x0, x1, cool(k))
        f.row(yy, x0, min(x1, x0 + hi - 1), cool(k - 1))
        f.row(yy, max(x0, x1 - sh + 1), x1, cool(k + 1))
        f.px(x1, yy, cool(k + 2))


def rim(img):
    """A hard rim in near-black around every opaque pixel.

    This is the single most important pass in the file, and it is the same pass
    `poutline()` in make_tiles.py runs over every standing prop. The tiles are
    quiet by design and the ground spans 34 to 72 luma; no single figure value
    separates from all of it, so the *edge* has to. Eight-connected, not four:
    at 48 rows there are many more diagonal steps in the silhouette than there
    were at 32, and a four-connected rim leaks daylight through every one of
    them.

    Derived from the alpha mask rather than drawn, so it can never disagree
    with the pose.
    """
    w, h = img.size
    src = img.load()
    edge = []
    for y in range(h):
        for x in range(w):
            if src[x, y][3]:
                continue
            for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0),
                           (1, 1), (-1, -1), (1, -1), (-1, 1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < w and 0 <= ny < h and src[nx, ny][3] == 255:
                    edge.append((x, y))
                    break
    for (x, y) in edge:
        img.putpixel((x, y), tuple(OUTLINE) + (255,))
    return img


def contact_shadow(img, rx=11.5, ry=4.5):
    """The one contact shadow: flat, hard-edged, aliased, one colour, centred
    under the sole. Not a soft blur -- that is not this game's language and it
    would not survive nearest filtering.

    Centred rather than offset south-east, for the same reason props are: the
    character stands anywhere, including the cell below a cliff, and an offset
    shadow eventually falls across something it should not. Fills only pixels
    the figure and its rim have not claimed, so it can never eat the boots.
    """
    cy = GROUND - ry + 0.5
    for y in range(FH):
        for x in range(FW):
            if img.getpixel((x, y))[3]:
                continue
            u = (x - CX) / rx
            v = (y - cy) / ry
            if u * u + v * v <= 1.0:
                img.putpixel((x, y), tuple(SHADOW) + (SHADOW_A,))
    return img


# --- the figure ---------------------------------------------------------------
#
# Shared vertical structure, so he keeps his proportions when he turns. 44 rows
# of figure in a 48-row cell, and the four rows that are not figure are the rim
# above the crown and the shadow spreading under the boots.
#
#   y  1..13   hood        13 rows, 30% of the figure
#   y 14..15   collar      the scarf on `down`, plain cloak on `up`
#   y 16..29   torso       shoulders, waist, belt, cloak flaring to a hem
#   y 20..26   arms        OUTSIDE the torso, with a one-pixel gap the rim
#                          fills -- this is what stopped him being a barrel
#   y 30..44   legs        15 rows, 34% of the figure
#   y 40..47   shadow
#
# The width plan is what makes the outline read as a body rather than as a
# container: hood 16, collar 12, shoulders 22, waist 12, hem 18. Every one of
# those steps is 2px or more, so it survives being 1/3 of a phone tile. The
# belt at y21 is the other half of it: without a value break at the waist the
# figure is one barrel of cloth from the collar to the hem however it is
# shaped.

HOOD_F = [                                   # front and back are identical --
    (1, 13, 18), (2, 12, 19), (3, 11, 20),   # the same person turning round
    (4, 10, 21), (5, 10, 21), (6, 9, 22),    # should not change size
    (7, 9, 22), (8, 9, 22), (9, 9, 22),
    (10, 8, 23), (11, 8, 23), (12, 9, 22), (13, 10, 21),
]
HOOD_F_K = [1, 1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 5]

TORSO_F = [
    (14, 10, 21), (15, 10, 21),
    (16, 8, 23), (17, 6, 25),                # the shoulder step: 22 against a
    (18, 5, 26), (19, 5, 26),                # 12-wide collar, so there is a
    (20, 9, 22), (21, 9, 22),                # neck in the silhouette even
    (22, 10, 21), (23, 10, 21), (24, 10, 21),  # though no neck is drawn
    (25, 9, 22), (26, 9, 22), (27, 8, 23), (28, 7, 24),
]
TORSO_F_K = [2, 2, 2, 2, 3, 3, 3, 3, 4, 5, 5, 5, 6, 6, 6]

# The hem parts over the legs instead of ending in a straight line. A flat hem
# is the other half of what made the old figure read as a bollard.
HEM_F = [(29, 7, 14), (29, 17, 24)]
HEM_K = 7

# Arms hang clear of the torso. The gap is one transparent column that the rim
# turns into a hard black line -- the art direction's "the arm must break the
# body outline" without spending three pixels of width on it.
ARM_F = [(y, 5, 7) for y in range(20, 25)]
HAND_F = [(25, 5, 7), (26, 6, 8)]


def mirror_spans(spans):
    return [(y, int(2 * CX) - x1, int(2 * CX) - x0) for (y, x0, x1) in spans]


# The face opening, cut into the hood. Two eyes' worth of dark under a lit brow
# plus a warm skin note is the whole of what makes `down` and `up` tell apart at
# a glance, because at this size the two silhouettes are the same silhouette.
FACE = [(6, 13, 18), (7, 12, 19), (8, 12, 19), (9, 12, 19),
        (10, 12, 19), (11, 13, 18)]


def draw_face(f, dy):
    for (y, x0, x1) in FACE:
        f.row(y + dy, x0, x1, SKIN[2])
    # The brim: a lit edge of cloth all the way round the opening. Without it
    # the hood is a smooth dome and the figure reads as bald.
    f.row(5 + dy, 11, 20, cool(0))
    f.row(6 + dy, 13, 18, mix(SKIN[2], C["bg"], 0.60))   # the brim's shadow
    f.row(7 + dy, 12, 19, mix(SKIN[2], C["bg"], 0.30))
    f.col(11, 7 + dy, 10 + dy, cool(1))                  # the hood wall, lit
    f.col(20, 7 + dy, 10 + dy, cool(3))                  # and in shade
    f.row(12 + dy, 11, 20, cool(4))                      # the cowl under the chin
    f.row(9 + dy, 13, 14, SKIN[3])                       # eyes
    f.row(9 + dy, 17, 18, SKIN[3])
    f.px(15, 10 + dy, SKIN[0])                           # nose, the one lit skin
    f.px(16, 10 + dy, SKIN[1])
    f.row(11 + dy, 14, 17, SKIN[2])                      # chin, still in shadow


def draw_scarf(f, dy):
    """`down` only. The one saturated garment, at the throat, where it is next
    to the face and reads as the same person's colour."""
    f.row(14 + dy, 10, 21, WARM[1])
    f.row(14 + dy, 10, 11, WARM[0])
    f.row(14 + dy, 19, 21, WARM[2])
    f.row(15 + dy, 9, 22, WARM[2])
    f.row(15 + dy, 9, 10, WARM[1])
    f.row(15 + dy, 20, 22, WARM[3])
    f.px(13, 16 + dy, WARM[2])                           # a tail over the chest


def draw_cowl(f, dy):
    """`up` only. Seen from behind there is no opening -- one seam down the
    back of the cowl and a fuller crown."""
    f.col(15, 3 + dy, 12 + dy, cool(3))
    f.col(16, 3 + dy, 12 + dy, cool(4))
    f.row(13 + dy, 13, 18, cool(5))


def draw_pack(f, dy):
    """`up` only. The warm mass moves from the throat to the middle of the
    back, which is the second cue that this is the back: on `down` the colour
    note is at head height, on `up` it is at torso height and four times the
    size."""
    f.box(11, 18 + dy, 20, 27 + dy, LEATHER[1])
    f.box(11, 18 + dy, 12, 27 + dy, LEATHER[0])
    f.box(18, 18 + dy, 20, 27 + dy, LEATHER[2])
    f.row(18 + dy, 11, 20, LEATHER[0])                   # lit top of the roll
    f.row(27 + dy, 11, 20, LEATHER[3])
    f.row(21 + dy, 11, 20, WARM[2])                      # the flap
    f.row(22 + dy, 11, 20, WARM[3])
    f.px(15, 22 + dy, WARM[0])                           # buckle
    f.px(16, 22 + dy, WARM[0])
    for i in range(3):                                   # shoulder straps
        f.col(11 + i, 16 + dy, 17 + dy, WARM[3])
        f.col(18 + i, 16 + dy, 17 + dy, WARM[3])


def draw_belt(f, dy, x0, x1):
    """The waist. A dark band with one warm pixel of buckle, at the point where
    the light chest gives way to the dark skirt -- so the figure has a top half
    and a bottom half instead of being one barrel from collar to hem."""
    f.row(21 + dy, x0, x1, LEATHER[1])
    f.row(22 + dy, x0, x1, LEATHER[2])
    f.px(x0, 21 + dy, LEATHER[0])
    f.px(15, 21 + dy, WARM[1])
    f.px(16, 21 + dy, WARM[2])
    f.px(15, 22 + dy, WARM[3])


def draw_strap(f, dy):
    """`down` only. The satchel strap crossing the chest -- the one asymmetry
    on the figure, and the reason `right` may be a mirror of `left` without
    anyone noticing."""
    for i in range(9):
        f.px(10 + i, 17 + i + dy, WARM[3])
        f.px(11 + i, 17 + i + dy, LEATHER[2])
    f.px(19, 26 + dy, WARM[1])
    f.px(20, 26 + dy, WARM[1])


def legs_frontal(f, pose, dy):
    """Two legs seen from front or back.

    The planted boot always ends on SOLE. The lifted leg is drawn five rows
    short: at this size a raised foot still reads better as an absence than as
    a foot drawn somewhere new, and now there is enough leg for the absence to
    be visible.
    """
    def leg(x0, lift, out):
        w = 3
        top = 30 + dy
        bot = SOLE - lift
        for y in range(top, bot - 3 + 1):
            f.row(y, x0, x0 + w, cool(5))
            f.row(y, x0, x0, cool(4))
            f.px(x0 + w, y, cool(6))
        for y in range(bot - 2, bot + 1):                # the boot
            f.row(y, x0 - out, x0 + w, LEATHER[1])
            f.row(y, x0 - out, x0 - out, LEATHER[0])
            f.px(x0 + w, y, LEATHER[2])
        f.row(bot, x0 - out, x0 + w, LEATHER[2])

    if pose == "neutral":
        leg(11, 0, 1)
        leg(17, 0, 0)
    elif pose == "step_left":
        leg(10, 0, 1)                                    # swung out and planted
        leg(18, 5, 0)                                    # lifted
    else:
        leg(10, 5, 1)
        leg(18, 0, 0)


def build_frontal(pose, facing_up):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    sculpt(f, HOOD_F, HOOD_F_K, dy)
    if facing_up:
        draw_cowl(f, dy)
    else:
        draw_face(f, dy)
    sculpt(f, TORSO_F, TORSO_F_K, dy)
    sculpt(f, HEM_F, HEM_K, dy)
    swing = {"neutral": 0, "step_left": 1, "step_right": -1}[pose]
    sculpt(f, [(y + swing, x0, x1) for (y, x0, x1) in ARM_F],
           [3, 4, 4, 4, 5], dy, hi=1, sh=1)
    sculpt(f, [(y - swing, x0, x1) for (y, x0, x1) in mirror_spans(ARM_F)],
           [4, 5, 5, 5, 6], dy, hi=1, sh=1)
    for (y, x0, x1) in HAND_F:
        f.row(y + swing + dy, x0, x1, LEATHER[1])
        f.px(x0, y + swing + dy, LEATHER[0])
    for (y, x0, x1) in mirror_spans(HAND_F):
        f.row(y - swing + dy, x0, x1, LEATHER[2])
        f.px(x0, y - swing + dy, LEATHER[1])
    draw_belt(f, dy, 9, 22)
    if facing_up:
        draw_pack(f, dy)
    else:
        draw_scarf(f, dy)
        draw_strap(f, dy)
    # Cloak sway: the hem swings against the stride, one column deep.
    if pose == "step_left":
        f.col(24, 26 + dy, 28 + dy, cool(7))
        f.row(29 + dy, 17, 25, cool(6))
    elif pose == "step_right":
        f.col(7, 26 + dy, 28 + dy, cool(4))
        f.row(29 + dy, 6, 14, cool(6))
    legs_frontal(f, pose, dy)
    return f


# --- profile ------------------------------------------------------------------
#
# Narrower everywhere -- hood 13 wide against the frontal 16 and pushed forward
# rather than centred, shoulders 16 against 22 -- and the hood's brow juts two
# pixels further forward than anything else on the figure. That brow, plus the
# cloak trailing off the back, is what tells you at a glance this is a side view
# and not a narrow front view. Facing LEFT, so the front of the figure is low x.

HOOD_P = [
    (1, 12, 18), (2, 11, 19), (3, 10, 20), (4, 9, 20),
    (5, 8, 20), (6, 8, 20),                  # the brow, jutting forward
    (7, 10, 20), (8, 10, 20),                # the opening, cut INTO the front
    (9, 9, 20), (10, 9, 20),                 # the jaw, forward again
    (11, 10, 20), (12, 11, 19), (13, 12, 18),
]
HOOD_P_K = [1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 4, 4, 5]

TORSO_P = [
    (14, 11, 19), (15, 10, 20),
    (16, 8, 22), (17, 7, 22), (18, 7, 22), (19, 8, 22),
    (20, 11, 22), (21, 11, 22), (22, 11, 21), (23, 11, 21), (24, 11, 22),
    (25, 11, 23), (26, 11, 24), (27, 10, 25), (28, 10, 25),
]
TORSO_P_K = [2, 2, 2, 2, 3, 3, 3, 3, 4, 5, 5, 5, 6, 6, 6]
HEM_P = [(29, 10, 25)]


def draw_brow(f, dy):
    """The profile's face is a notch cut into the front of the hood: a brow
    that juts two pixels forward, the opening set back behind it, and the jaw
    coming forward again below. That two-pixel step in the *silhouette* is what
    makes a side view a side view at 3x -- more than the narrower body, more
    than the trailing cloak, and it survives being three device pixels wide.

    Drawing a nose that broke the outline instead gave him a beak. So did
    cutting a wider notch: two indentations one above the other read as a jaw,
    not as a cowl.
    """
    # The brim is the UNDERSIDE of the hood, so it is darker than the crown
    # above it, not lighter. Lighting it made a beak: a bright wedge sticking
    # out of a pale dome is a bird's head at any zoom.
    f.row(5 + dy, 8, 11, cool(3))
    f.row(6 + dy, 8, 11, cool(4))
    f.row(7 + dy, 10, 12, SKIN[2])                  # the opening
    f.row(8 + dy, 10, 12, SKIN[2])
    f.px(10, 7 + dy, SKIN[3])                       # the eye
    f.px(11, 7 + dy, SKIN[3])
    f.px(10, 8 + dy, SKIN[0])                       # cheek, the one lit skin
    f.row(9 + dy, 9, 11, cool(5))                   # the cowl wraps the jaw


def build_profile(pose):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    sculpt(f, HOOD_P, HOOD_P_K, dy)
    draw_brow(f, dy)
    sculpt(f, TORSO_P, TORSO_P_K, dy)
    sculpt(f, HEM_P, HEM_K, dy)
    f.col(21, 16 + dy, 26 + dy, cool(6))            # the back seam of the cloak

    # The cloak trails behind him, thrown further back on the step frames.
    trail = 2 if pose == "neutral" else 4
    for y in range(20, 29):
        t = int(round(trail * (y - 19) / 9.0)) + 1
        f.row(y + dy, 24, 24 + t, cool(7))
        f.px(24, y + dy, cool(6))

    # The scarf, at the throat where it is on `down` too.
    f.row(14 + dy, 11, 19, WARM[1])
    f.row(14 + dy, 11, 12, WARM[0])
    f.row(15 + dy, 10, 20, WARM[2])
    f.row(15 + dy, 10, 11, WARM[1])
    f.row(15 + dy, 19, 20, WARM[3])

    draw_belt(f, dy, 11, 22)

    # The pack rides on his back -- the same object `up` shows, seen edge-on,
    # so the three facings describe one character rather than three.
    f.box(21, 18 + dy, 23, 25 + dy, LEATHER[1])
    f.row(18 + dy, 21, 23, LEATHER[0])
    f.row(25 + dy, 21, 23, LEATHER[3])
    f.row(21 + dy, 21, 23, WARM[2])

    # The near arm, swinging opposite the near leg, outside the silhouette with
    # a transparent column the rim fills.
    ax, ay = {"neutral": (7, 20), "step_left": (6, 19), "step_right": (7, 22)}[pose]
    for y in range(ay, ay + 5):
        f.row(y + dy, ax, ax + 2, cool(3))
        f.px(ax, y + dy, cool(2))
        f.px(ax + 2, y + dy, cool(4))
    f.row(ay + 5 + dy, ax, ax + 2, LEATHER[1])      # the glove
    f.row(ay + 6 + dy, ax, ax + 2, LEATHER[2])

    # Legs. A pixel of daylight between them even at rest: two touching legs
    # read as one thick one, and the stance is half of what says "standing".
    # The far leg is drawn first and in shadow, so the near one overlaps it and
    # the stride has depth instead of reading as two legs side by side.
    if pose == "neutral":
        near, far, nlift, flift = 11, 16, 0, 0
    elif pose == "step_left":
        near, far, nlift, flift = 9, 18, 0, 3
    else:
        near, far, nlift, flift = 18, 9, 3, 0

    def leg(x0, lift, shade, toe):
        top = 30 + dy
        bot = SOLE - lift
        for y in range(top, bot - 3 + 1):
            f.row(y, x0, x0 + 3, cool(5 + shade))
            f.px(x0, y, cool(4 + shade))
        for y in range(bot - 2, bot + 1):
            f.row(y, x0 - toe, x0 + 3, LEATHER[1 + shade])
            f.px(x0 - toe, y, LEATHER[0 + shade])
        f.row(bot, x0 - toe, x0 + 3, LEATHER[2 + shade])

    # The far boot gets no toe: with one it filled the daylight column between
    # the legs and the two feet merged into a single bar.
    leg(far, flift, 1, 0)
    leg(near, nlift, 0, 2)
    return f


def build(facing, pose):
    if facing == "down":
        f = build_frontal(pose, False)
    elif facing == "up":
        f = build_frontal(pose, True)
    else:
        f = build_profile(pose)
    return f.img


def recentre(imgs):
    """The profile is drawn where its geometry wants to live, not where its
    centre wants to be, because the trailing cloak only exists on one side.
    Shift the whole set by one common offset so `left` and its mirror `right`
    share a centre -- otherwise the character twitches sideways every time the
    player turns round. One offset for all three poses, or he twitches when he
    steps instead."""
    boxes = [i.getbbox() for i in imgs]
    x0 = min(b[0] for b in boxes)
    x1 = max(b[2] for b in boxes) - 1
    shift = int(round(CX - (x0 + x1) / 2.0))
    if shift == 0:
        return imgs
    out = []
    for im in imgs:
        n = Image.new("RGBA", (FW, FH), CLEAR)
        n.paste(im, (shift, 0))
        out.append(n)
    return out


def build_all():
    cels = {}
    for fa in ("down", "up"):
        for po in FRAMES:
            cels[(fa, po)] = build(fa, po)
    prof = recentre([build("left", po) for po in FRAMES])
    for po, im in zip(FRAMES, prof):
        cels[("left", po)] = im
    for key in list(cels):
        contact_shadow(rim(cels[key]))
    lb = [cels[("left", po)].getbbox() for po in FRAMES]
    lc = (min(b[0] for b in lb) + max(b[2] for b in lb) - 1) / 2.0
    for po in FRAMES:
        m = cels[("left", po)].transpose(Image.FLIP_LEFT_RIGHT)
        cels[("right", po)] = m
    rb = [cels[("right", po)].getbbox() for po in FRAMES]
    rc = (min(b[0] for b in rb) + max(b[2] for b in rb) - 1) / 2.0
    shift = int(round(lc - rc))
    if shift:
        for po in FRAMES:
            n = Image.new("RGBA", (FW, FH), CLEAR)
            n.paste(cels[("right", po)], (shift, 0))
            cels[("right", po)] = n
    return cels


# --- verification -------------------------------------------------------------

def tile_means():
    """Read the real tileset and measure it, rather than trusting a table in a
    doc. The old sheet's whole failure was that it was judged as a 24x32 image
    on a transparent background instead of as a figure standing on grass."""
    path = os.path.join(TILES, "tileset.png")
    manifest = os.path.join(TILES, "tiles.json")
    if not (os.path.exists(path) and os.path.exists(manifest)):
        return []
    with open(manifest, encoding="utf-8") as fh:
        man = json.load(fh)
    order = man["order"]
    wk = man.get("walkable", {})
    walkable = {k for k, v in wk.items() if v} if isinstance(wk, dict) else set(wk)
    sheet = Image.open(path).convert("RGB")
    out = []
    for i, name in enumerate(order):
        if name not in walkable:
            continue
        t = sheet.crop((32 * i, 0, 32 * i + 32, 32))
        px = list(t.getdata())
        out.append((name, i, sum(luma(p) for p in px) / len(px), t))
    out.sort(key=lambda r: r[2])
    return out


def sprite_stats(img):
    px = [p for p in img.getdata() if p[3] == 255]
    ls = sorted(luma(p) for p in px)
    n = len(ls)
    return dict(n=n, lo=ls[0], p50=ls[n // 2], p90=ls[int(n * 0.9)],
                hi=ls[-1], mean=sum(ls) / n)


def ground_patch(tile, w, h):
    p = Image.new("RGB", (w, h))
    for y in range(0, h, 32):
        for x in range(0, w, 32):
            p.paste(tile, (x, y))
    return p


def legibility(cels, grounds):
    """How the figure separates from each ground he can stand on.

    The mean is reported because it is the number the brief was written around,
    but on its own it is a trap: a figure deliberately bracketed either side of
    the ground has a mean *near* the ground by construction, and that is the
    goal rather than the fault. The three columns that matter are `lit` (pixels
    at least 15 luma above the ground), `dark` (at least 15 below) and `lost`
    (within 10 either way, so they carry no read of their own). The silhouette
    itself is never at risk on any of them: the rim is luma 9 and the brightest
    ground he can stand on is snow at 72.
    """
    st = sprite_stats(cels[("down", "neutral")])
    px = [luma(p) for p in cels[("down", "neutral")].getdata() if p[3] == 255]
    n = float(len(px))
    rows = []
    for name, _i, gm, _t in grounds:
        lit = sum(1 for v in px if v - gm >= 15) / n
        dark = sum(1 for v in px if gm - v >= 15) / n
        lost = sum(1 for v in px if abs(v - gm) < 10) / n
        rows.append((name, gm, st["mean"] - gm, lit, dark, lost))
    return st, rows


# --- output -------------------------------------------------------------------

def contact(sheet, scale=4):
    """A 4x preview with the cell grid ruled over it. The grid is the point:
    the sheet is what the engine slices, so the eye should be checking that
    every figure sits inside its own 32x48 box, not admiring the art."""
    pad_l, pad_t = 44, 16
    big = sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST)
    out = Image.new("RGBA", (big.width + pad_l + 8, big.height + pad_t + 8),
                    mix(C["bg"], BLACK, 0.35) + (255,))
    # Composite, not paste: paste would carry the sprite's transparent pixels
    # through and leave the preview showing holes instead of the backing.
    out.alpha_composite(big, (pad_l, pad_t))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    rule = C["line"] + (255,)
    for c in range(len(FRAMES) + 1):
        x = pad_l + c * FW * scale
        d.line([(x, pad_t), (x, pad_t + big.height)], fill=rule)
    for r in range(len(FACINGS) + 1):
        y = pad_t + r * FH * scale
        d.line([(pad_l, y), (pad_l + big.width, y)], fill=rule)
    for c, name in enumerate(FRAMES):
        d.text((pad_l + c * FW * scale + 2, 3), "%d %s" % (c, name),
               fill=C["muted"] + (255,), font=font)
    for r, name in enumerate(FACINGS):
        d.text((3, pad_t + r * FH * scale + 4), name,
               fill=C["muted"] + (255,), font=font)
    return out


def on_ground(cels, grounds, zoom=3):
    """The legibility check, rendered rather than argued: every facing on every
    walkable ground, at the zoom the game actually runs at. Look at it."""
    cw, ch = 64, 80
    pad_l, pad_t = 48, 14
    cols = len(FACINGS)
    out = Image.new("RGBA",
                    (pad_l + cols * cw * zoom + 8,
                     pad_t + len(grounds) * ch * zoom + 8),
                    mix(C["bg"], BLACK, 0.35) + (255,))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for r, (name, _i, gm, tile) in enumerate(grounds):
        for c, fa in enumerate(FACINGS):
            cell = ground_patch(tile, cw, ch).convert("RGBA")
            cell.alpha_composite(cels[(fa, "neutral")], (16, ch - 48))
            big = cell.resize((cw * zoom, ch * zoom), Image.NEAREST)
            out.alpha_composite(big, (pad_l + c * cw * zoom,
                                      pad_t + r * ch * zoom))
        d.text((3, pad_t + r * ch * zoom + 4), "%s\n%.0f" % (name[:11], gm),
               fill=C["muted"] + (255,), font=font)
    for c, fa in enumerate(FACINGS):
        d.text((pad_l + c * cw * zoom + 3, 3), fa, fill=C["muted"] + (255,),
               font=font)
    return out


def walk_strip(cels, grounds, zoom=3):
    """The walk cycle in playback order -- 1, 0, 2, 0 -- on a mid ground, so
    the check is on the animation and not on a static pose."""
    tile = None
    for name, _i, _gm, t in grounds:
        if name == "grass_short":
            tile = t
    if tile is None and grounds:
        tile = grounds[len(grounds) // 2][3]
    if tile is None:
        return None
    cw, ch = 32, 64
    n = len(WALK_ORDER)
    out = Image.new("RGBA", (n * cw * zoom, len(FACINGS) * ch * zoom), CLEAR)
    for r, fa in enumerate(FACINGS):
        for i, col in enumerate(WALK_ORDER):
            cell = ground_patch(tile, cw, ch).convert("RGBA")
            cell.alpha_composite(cels[(fa, FRAMES[col])], (0, ch - 48))
            out.alpha_composite(
                cell.resize((cw * zoom, ch * zoom), Image.NEAREST),
                (i * cw * zoom, r * ch * zoom))
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    cels = build_all()
    grounds = tile_means()
    written = []

    def save(img, name):
        p = os.path.join(OUT, name)
        img.save(p)
        written.append(name)

    # Per-facing strips: 3 columns of 32x48, frame order == FRAMES.
    for fa in FACINGS:
        strip = Image.new("RGBA", (FW * len(FRAMES), FH), CLEAR)
        for i, po in enumerate(FRAMES):
            strip.paste(cels[(fa, po)], (i * FW, 0))
        save(strip, "walk_%s.png" % fa)

    # The sheet the engine slices. Strictly regular: 3 columns x 4 rows of
    # 32x48, no padding, no margin, no per-cell offset of any kind.
    sheet = Image.new("RGBA", (FW * len(FRAMES), FH * len(FACINGS)), CLEAR)
    for r, fa in enumerate(FACINGS):
        for c, po in enumerate(FRAMES):
            sheet.paste(cels[(fa, po)], (c * FW, r * FH))
    save(sheet, "player.png")
    save(contact(sheet), "_player_x4.png")
    if grounds:
        save(on_ground(cels, grounds), "_player_ground.png")
        ws = walk_strip(cels, grounds)
        if ws is not None:
            save(ws, "_player_walk.png")

    write_animals(save, grounds)

    # Prove the contract rather than assert it.
    print()
    print("player.png  %dx%d  =  %d cols x %d rows of %dx%d"
          % (sheet.width, sheet.height, len(FRAMES), len(FACINGS), FW, FH))
    print("rows %s / cols %s / walk order %s" % (FACINGS, FRAMES, WALK_ORDER))
    print("TileWorld.gd needs FRAME_W = %d, FRAME_H = %d" % (FW, FH))
    print()
    ok = True
    for fa in FACINGS:
        boxes = [cels[(fa, po)].getbbox() for po in FRAMES]
        body = []
        for po in FRAMES:
            im = cels[(fa, po)]
            rowsy = [y for y in range(FH)
                     if any(im.getpixel((x, y))[3] == 255 for x in range(FW))]
            body.append((min(rowsy), max(rowsy)))
        feet = {b[1] for b in body}
        x0, x1 = min(b[0] for b in boxes), max(b[2] for b in boxes) - 1
        centre = (x0 + x1) / 2.0
        stable = len(feet) == 1
        ok = ok and stable and abs(centre - CX) <= 0.5
        print("  %-6s bbox x %d..%d  centre %.1f   figure y %d..%d   sole row %s"
              % (fa, x0, x1, centre, min(b[0] for b in body),
                 max(b[1] for b in body),
                 "%d stable" % feet.pop() if stable else "MOVES %s" % sorted(feet)))

    st, rows = legibility(cels, grounds) if grounds else (
        sprite_stats(cels[("down", "neutral")]), [])
    print()
    print("figure: %d opaque px   luma min %.0f / p50 %.0f / p90 %.0f / max %.0f"
          "   MEAN %.1f" % (st["n"], st["lo"], st["p50"], st["p90"], st["hi"],
                            st["mean"]))
    if rows:
        print()
        print("  %-13s %6s %8s %7s %7s %7s"
              % ("ground", "luma", "delta", "lit", "dark", "lost"))
        worst = None
        for name, gm, dl, lit, dark, lost in rows:
            print("  %-13s %6.1f %+8.1f %6.1f%% %6.1f%% %6.1f%%"
                  % (name, gm, dl, lit * 100, dark * 100, lost * 100))
            if worst is None or lost > worst[5]:
                worst = (name, gm, dl, lit, dark, lost)
        print("  worst ground: %s (%.1f) -- %.0f%% of the figure reads light on"
              " it, %.0f%% dark, %.0f%% lost"
              % (worst[0], worst[1], worst[3] * 100, worst[4] * 100,
                 worst[5] * 100))
    alphas = sorted({p[3] for p in sheet.getdata()})
    print()
    print("alpha values in the sheet: %s   (0 clear, %d shadow, 255 figure)"
          % (alphas, SHADOW_A))
    print("colours: %d opaque" % len({p[:3] for p in sheet.getdata()
                                      if p[3] == 255}))
    h = hashlib.md5()
    for name in sorted(written):
        with open(os.path.join(OUT, name), "rb") as fh:
            h.update(fh.read())
    print("wrote %d files, md5 %s" % (len(written), h.hexdigest()))
    if not ok:
        raise SystemExit("CONTRACT FAILED")




# --- the animals ---------------------------------------------------------------
#
# The dog and the cat, 4 directions x 4 columns of 32x32.
#
# Authored, not generated, and the pipeline skill's own finding is the reason:
# the image model cannot hold an identity across frames, so a walk cycle asked
# for as a sheet comes back as a contact sheet of four different animals. That
# is fatal here in a way it is not for a one-off prop -- the whole point of a
# walk cycle is that it is the *same* animal in a different pose. So this is the
# same authored-pixels path the player takes, at zero quota, and every frame is
# the previous frame with two legs moved.
#
# The layout is deliberately the player's, one column wider:
#
#   rows    down, up, left, right     -- the order in HJTileWorld.FACINGS, which
#                                        HJCritters.FACING_ROW repeats
#   col 0   neutral                   -- what a still animal shows, no lookup
#   col 1   step A       } the walk plays 1, 0, 2, 0, the same CYCLE as the
#   col 2   step B       } player, for the same reason: no neutral between the
#                          two steps is a limp
#   col 3   fidget                    -- ear cocked and tail up. A perfectly
#                                        still animal is furniture, so the
#                                        renderer drops this in for a quarter of
#                                        a second every few seconds while idle.
#
# 32x32 rather than the player's 32x48, with about 18 rows of animal inside it,
# so the dog comes up to the 44-row traveller's knee.
#
# Two things learned the hard way while drawing these, both recorded because
# they are not obvious and both cost a rewrite:
#
#   THE RIM CLOSES SMALL GAPS. The eight-connected near-black rim every sprite
#   in this project carries is what makes one figure legible on eighteen
#   grounds, and it fills any hole two pixels or narrower from both sides. Four
#   separately drawn legs one or two pixels apart therefore render as one solid
#   skirt. Hence two legs per profile with five pixels between them, which is
#   also what actually reads at this size.
#
#   PARAMETRIC ELLIPSES DO NOT MAKE AN ANIMAL. A head disc and a body disc of
#   similar radius merge into one lozenge with ears. So these are pose tables of
#   half-widths per row -- geometry only, shaded generically afterwards -- which
#   is exactly the split the player's sculpt() uses and for the same reason: the
#   silhouette and the lighting are edited separately.
#
# `right` is the mirror of `left`, as the player's is, so the two cannot drift.

AW, AH = 32, 32
APAW = 27                            # the row a planted paw ends on, always
AGROUND = 30                         # the shadow's last row
ACX = 15.5
APOSES = ["neutral", "step_a", "step_b", "fidget"]

# Two ramps, deliberately far apart in value: the dog is a warm mid-brown and
# the cat is pale and cool, so at 32 pixels on a phone you can tell which animal
# you are looking at from value alone, before any shape reads. Same construction
# as COOL above -- mixed from the theme, never a free hex.
DOG_FUR = [
    mix(C["accent"], C["line"], 0.16),   # 0  lit
    mix(C["accent"], C["line"], 0.42),   # 1  base
    mix(C["accent"], C["bg"], 0.56),     # 2  mid
    mix(C["accent"], C["bg"], 0.74),     # 3  dark
    mix(C["accent"], C["bg"], 0.88),     # 4  deep
]
CAT_FUR = [
    mix(C["muted"], C["text"], 0.58),
    mix(C["muted"], C["text"], 0.20),
    C["muted"],
    mix(C["line"], C["muted"], 0.58),
    mix(C["line"], C["bg"], 0.28),
]
DOG_EYE = mix(C["bg"], BLACK, 0.30)
CAT_EYE = mix(C["accent"], C["text"], 0.45)


def blob(cx, y0, widths, k=1):
    """(y, x0, x1, ramp index) spans from a column of half-widths.

    Geometry only. One number per row is enough to draw a head, a rump or a
    muzzle, and keeping it to one number is what makes these tables editable."""
    out = []
    for i, w in enumerate(widths):
        if w < 0:
            continue
        out.append((y0 + i, int(round(cx - w)), int(round(cx + w)), k))
    return out


def wedge(tip_x, tip_y, height, k, lean=0):
    """An ear: a triangle one pixel wide at the tip, widening downward."""
    out = []
    for i in range(height):
        half = i // 2
        x = tip_x + int(round(lean * i))
        out.append((tip_y + i, x - half, x + half, k))
    return out


def curl(points, k=1):
    return [(y, x, x, k) for (x, y) in points]


# --- the pose tables ------------------------------------------------------------
#
# Every span is (row, x0, x1, ramp index). Parts are listed in draw order, so a
# head listed after a body is in front of it. Legs are separate because they are
# the only thing a pose changes.

def dog_parts(cocked=False):
    """`cocked` is the idle fidget: one ear up a pixel and the tail up two. It
    is built into the tables rather than applied afterwards, because shifting
    "everything above row 13" also shifts the top of the body and flattens the
    silhouette into a bar -- which is what the first attempt did."""
    fur = 1
    e = 1 if cocked else 0
    t = 2 if cocked else 0
    side = (
        wedge(9, 9 - e, 4, 2, lean=0.4)                              # the ear
        + blob(18.5, 14, [4.5, 6, 6.5, 6.5, 6.5, 6.5, 6, 5, 3.5], fur)   # body
        + curl([(24, 15), (25, 14 - t), (26, 13 - t), (27, 11 - t),
                (28, 9 - t), (28, 7 - t)], 2)                            # tail
        + blob(8.5, 12, [3, 4, 4.5, 4.5, 4.5, 4.5, 4, 3], fur)           # head
        + [(16, 2, 5, 2), (17, 2, 5, 2), (18, 3, 5, 3)]                  # snout
    )
    # No tail in the front view. Seen head-on a dog's tail is behind it, and
    # every attempt to show it either collided with the far ear or floated off
    # the silhouette as a stub the rim could not reach.
    down = (
        blob(15.5, 10, [3.5, 4.5, 5.5, 5.5, 5.5, 4.5, 3.5], 2)           # shoulders
        + wedge(10, 8, 6, 2, lean=-0.15) + wedge(21, 8 - e, 6, 3, lean=0.15)
        + blob(15.5, 14, [3.5, 5.5, 6.5, 6.5, 6.5, 6.5, 5.5, 4.5], fur)  # head
        + blob(15.5, 22, [2.5, 2.5], 2)                                  # muzzle
    )
    up = (
        wedge(10, 8, 6, 2, lean=-0.15) + wedge(21, 8 - e, 6, 3, lean=0.15)
        + blob(15.5, 11, [3.5, 5.5, 6.5, 6.5, 6.5, 5.5, 4.5], 2)         # skull
        + blob(15.5, 17, [3.5, 4.5, 5.5, 5.5, 5.5, 4.5, 3.5], fur)       # rump
        + curl([(20, 23), (21, 21 - t), (22, 19 - t), (23, 17 - t),
                (23, 15 - t)], 1)                                        # tail
    )
    return dict(side=side, down=down, up=up)


def cat_parts(cocked=False):
    fur = 1
    e = 1 if cocked else 0
    t = 2 if cocked else 0
    side = (
        wedge(9, 10 - e, 5, 2, lean=0.3)
        + blob(18.5, 16, [3.5, 5, 5.5, 5.5, 5.5, 5, 3.5], fur)
        + curl([(24, 18), (25, 16 - t), (26, 14 - t), (27, 12 - t),
                (28, 10 - t), (28, 8 - t), (27, 7 - t)], 2)
        + blob(9.5, 14, [2.5, 3.5, 3.5, 3.5, 3.5, 2.5], fur)
        + [(17, 4, 7, 2), (18, 5, 7, 3)]
    )
    # A cat facing you keeps its tail up and visible past its own shoulder --
    # which is the one place on the silhouette it does not collide with an ear.
    down = (
        curl([(21, 14), (22, 12 - t), (23, 10 - t), (23, 8 - t)], 2)
        + blob(15.5, 13, [2.5, 3.5, 4.5, 4.5, 3.5, 2.5], 2)
        + wedge(11, 10, 7, 2, lean=-0.1) + wedge(20, 10 - e, 7, 3, lean=0.1)
        + blob(15.5, 16, [3.5, 4.5, 5.5, 5.5, 5.5, 4.5, 3.5], fur)
        + blob(15.5, 22, [2.0, 2.0], 2)
    )
    up = (
        wedge(11, 10, 7, 2, lean=-0.1) + wedge(20, 10 - e, 7, 3, lean=0.1)
        + blob(15.5, 13, [3.5, 4.5, 5.5, 5.5, 4.5, 3.5], 2)
        + blob(15.5, 18, [3.5, 4.5, 5.5, 5.5, 4.5, 3.5], fur)
        + curl([(20, 23), (21, 21 - t), (22, 19 - t), (23, 17 - t),
                (23, 15 - t), (22, 13 - t), (21, 12 - t)], 1)
    )
    return dict(side=side, down=down, up=up)


# Legs, per pose: (x0, x1, top, bottom). A lifted paw is drawn SHORT -- it stops
# above APAW rather than being drawn somewhere new -- and the other leg of the
# pair stays planted, so the paw row of the frame as a whole never moves. That
# is the player's rule, and it is what stops the animal bobbing.
def _legpair(front_x, hind_x, w, top, pose):
    lifted = APAW - 2
    front = (front_x, front_x + w - 1, top, APAW)
    hind = (hind_x, hind_x + w - 1, top - 1, APAW)
    if pose == "step_a":
        front = (front_x + 1, front_x + w, top, lifted)
    elif pose == "step_b":
        hind = (hind_x - 1, hind_x + w - 2, top - 1, lifted)
    return [front, hind]


ANIMALS = {
    "dog": dict(fur=DOG_FUR, eye=DOG_EYE, stripes=False, parts=dog_parts,
                shadow_rx=10.0,
                side_legs=lambda p: _legpair(13, 21, 3, 22, p),
                face_legs=lambda p: _legpair(10, 19, 3, 24, p),
                eyes_down=[(12, 18), (19, 18)], eye_side=(6, 15),
                nose=[(15, 23), (16, 23)]),
    "cat": dict(fur=CAT_FUR, eye=CAT_EYE, stripes=True, parts=cat_parts,
                shadow_rx=8.5,
                side_legs=lambda p: _legpair(13, 21, 2, 23, p),
                face_legs=lambda p: _legpair(11, 19, 2, 24, p),
                eyes_down=[(13, 19), (18, 19)], eye_side=(7, 16),
                nose=[(15, 22), (16, 22)]),
}


class Cel:
    """A 32x32 animal cel. Same contract as Frame: body colours only, with the
    rim derived from the alpha mask afterwards, so the silhouette is closed
    however the legs happen to land."""

    def __init__(self):
        self.img = Image.new("RGBA", (AW, AH), CLEAR)

    def px(self, x, y, c):
        if 0 <= x < AW and 0 <= y < AH:
            self.img.putpixel((int(x), int(y)), tuple(c) + (255,))

    def row(self, y, x0, x1, c):
        for x in range(int(x0), int(x1) + 1):
            self.px(x, y, c)


def paint(c, spans, fur, stripes=False, hi=2, sh=2):
    """Lay a table of spans down and light it from the north-west.

    The two leftmost pixels of a row go a step lighter and the two rightmost a
    step darker, with the last column two steps darker. Doing the lighting
    generically rather than per pixel is the whole reason the tables above are
    readable; it is the same bargain sculpt() strikes for the player."""
    for (y, x0, x1, k) in spans:
        base = fur[max(0, min(len(fur) - 1, k))]
        c.row(y, x0, x1, base)
        if stripes and (y % 3) == 0 and x1 - x0 > 3:
            c.row(y, x0 + 1, x1 - 1, fur[min(len(fur) - 1, k + 2)])
        c.row(y, x0, min(x1, x0 + hi - 1), fur[max(0, k - 1)])
        c.row(y, max(x0, x1 - sh + 1), x1, fur[min(len(fur) - 1, k + 1)])
        c.px(x1, y, fur[min(len(fur) - 1, k + 2)])


def paint_legs(c, legs, fur):
    for (x0, x1, y0, y1) in legs:
        for y in range(y0, y1 + 1):
            c.row(y, x0, x1, fur[3])
            c.px(x1, y, fur[4])
        c.row(y1, x0, x1, fur[4])


def animal_cel(name, facing, pose):
    """One cel. Every facing is the same animal with its parts rearranged."""
    a = ANIMALS[name]
    fur = a["fur"]
    parts = a["parts"](pose == "fidget")
    c = Cel()

    if facing in ("left", "right"):
        paint_legs(c, a["side_legs"](pose), fur)
        paint(c, parts["side"], fur, a["stripes"])
        c.px(a["eye_side"][0], a["eye_side"][1], a["eye"])
    elif facing == "down":
        paint_legs(c, a["face_legs"](pose), fur)
        paint(c, parts["down"], fur, a["stripes"])
        for (x, y) in a["eyes_down"]:
            c.px(x, y, a["eye"])
        for (x, y) in a["nose"]:
            c.px(x, y, fur[4])
    else:                                       # up -- walking away from you
        paint_legs(c, a["face_legs"](pose), fur)
        paint(c, parts["up"], fur, a["stripes"])

    img = c.img
    if facing == "right":
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    rim(img)
    _animal_shadow(img, a["shadow_rx"])
    return img


def _animal_shadow(img, rx, ry=2.5):
    """The one contact shadow, in the tiles' own colour and alpha, centred under
    the animal. Centred rather than offset for the same reason the player's is:
    it can stand anywhere, including at the foot of a cliff."""
    cy = AGROUND - ry + 0.5
    for y in range(AH):
        for x in range(AW):
            if img.getpixel((x, y))[3]:
                continue
            u = (x - ACX) / rx
            v = (y - cy) / ry
            if u * u + v * v <= 1.0:
                img.putpixel((x, y), tuple(SHADOW) + (SHADOW_A,))
    return img


def build_animal(name):
    return {(f, p): animal_cel(name, f, p) for f in FACINGS for p in APOSES}


def animal_sheet(cels):
    sheet = Image.new("RGBA", (AW * len(APOSES), AH * len(FACINGS)), CLEAR)
    for r, f in enumerate(FACINGS):
        for col, p in enumerate(APOSES):
            sheet.paste(cels[(f, p)], (col * AW, r * AH))
    return sheet


def animal_contact(sheet, name, scale=5):
    """The sheet at 5x with the cell grid ruled over it. The grid is the point:
    the engine slices on exactly these lines."""
    pad_l, pad_t = 44, 16
    big = sheet.resize((sheet.width * scale, sheet.height * scale), Image.NEAREST)
    out = Image.new("RGBA", (big.width + pad_l + 8, big.height + pad_t + 8),
                    mix(C["bg"], BLACK, 0.35) + (255,))
    out.alpha_composite(big, (pad_l, pad_t))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    rule = C["line"] + (255,)
    for col in range(len(APOSES) + 1):
        x = pad_l + col * AW * scale
        d.line([(x, pad_t), (x, pad_t + big.height)], fill=rule)
    for r in range(len(FACINGS) + 1):
        y = pad_t + r * AH * scale
        d.line([(pad_l, y), (pad_l + big.width, y)], fill=rule)
    for col, p in enumerate(APOSES):
        d.text((pad_l + col * AW * scale + 2, 3), "%d %s" % (col, p),
               fill=C["muted"] + (255,), font=font)
    for r, f in enumerate(FACINGS):
        d.text((3, pad_t + r * AH * scale + 4), f, fill=C["muted"] + (255,),
               font=font)
    d.text((3, 3), name, fill=C["accent"] + (255,), font=font)
    return out


def animal_on_ground(cels, grounds, zoom=4):
    """Every facing on every walkable ground, at the zoom the game runs at."""
    cw, ch = 32, 32
    pad_l, pad_t = 48, 14
    out = Image.new("RGBA",
                    (pad_l + len(FACINGS) * cw * zoom + 8,
                     pad_t + len(grounds) * ch * zoom + 8),
                    mix(C["bg"], BLACK, 0.35) + (255,))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for r, (name, _i, gm, tile) in enumerate(grounds):
        for col, f in enumerate(FACINGS):
            cell = ground_patch(tile, cw, ch).convert("RGBA")
            cell.alpha_composite(cels[(f, "neutral")], (0, 0))
            out.alpha_composite(cell.resize((cw * zoom, ch * zoom), Image.NEAREST),
                                (pad_l + col * cw * zoom, pad_t + r * ch * zoom))
        d.text((3, pad_t + r * ch * zoom + 4), "%s\n%.0f" % (name[:11], gm),
               fill=C["muted"] + (255,), font=font)
    for col, f in enumerate(FACINGS):
        d.text((pad_l + col * cw * zoom + 3, 3), f, fill=C["muted"] + (255,),
               font=font)
    return out


def animal_ascii(cels, facing="left", pose="neutral"):
    """The silhouette as text. The only way to check a pose from a terminal, and
    it catches the failures that matter -- legs fused into a skirt by the rim, a
    tail off the frame, a head and a body merged into one lozenge."""
    img = cels[(facing, pose)]
    out = []
    for y in range(AH):
        line = ""
        for x in range(AW):
            p = img.getpixel((x, y))
            line += (" " if p[3] == 0 else
                     "." if p[3] < 255 else
                     "#" if luma(p) > 100 else "+")
        out.append("%2d|%s|" % (y, line))
    return "\n".join(out)


def write_animals(save, grounds):
    """Both animals, and the contract each one owes HJCritters, proved."""
    for name in sorted(ANIMALS):
        cels = build_animal(name)
        sheet = animal_sheet(cels)
        save(sheet, "%s.png" % name)
        save(animal_contact(sheet, name), "_%s_x5.png" % name)
        if grounds:
            save(animal_on_ground(cels, grounds), "_%s_ground.png" % name)

        print()
        print("%s.png  %dx%d  =  %d cols x %d rows of %dx%d"
              % (name, sheet.width, sheet.height, len(APOSES), len(FACINGS),
                 AW, AH))
        print("  rows %s" % FACINGS)
        print("  cols %s, walk order %s, idle shows col 0 and col 3"
              % (APOSES, WALK_ORDER))
        ok = True
        for f in FACINGS:
            paws, tops, xs = set(), [], []
            for p in APOSES:
                im = cels[(f, p)]
                body = [y for y in range(AH)
                        if any(im.getpixel((x, y))[3] == 255 for x in range(AW))]
                cols = [x for x in range(AW)
                        if any(im.getpixel((x, y))[3] == 255 for y in range(AH))]
                paws.add(max(body))
                tops.append(min(body))
                xs.append((min(cols), max(cols)))
            x0 = min(v for v, _ in xs)
            x1 = max(v for _, v in xs)
            # The rim sits a pixel outside the body, so the figure has to stop
            # one short of the frame or the silhouette is cut by the cell edge.
            inside = x0 >= 1 and x1 <= AW - 2 and min(tops) >= 1
            stable = len(paws) == 1
            ok = ok and stable and inside
            print("    %-6s x %2d..%2d  top %2d  paw row %s%s"
                  % (f, x0, x1, min(tops),
                     "%d stable" % sorted(paws)[0] if stable
                     else "MOVES %s" % sorted(paws),
                     "" if inside else "   TOUCHES THE FRAME EDGE"))
        px = [luma(p) for p in cels[("down", "neutral")].getdata() if p[3] == 255]
        print("    %d opaque px, luma %.0f..%.0f mean %.1f"
              % (len(px), min(px), max(px), sum(px) / len(px)))
        if not ok:
            raise SystemExit("ANIMAL CONTRACT FAILED: %s" % name)


if __name__ == "__main__":
    main()
