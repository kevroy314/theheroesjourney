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
    spite_cels = write_spite(save, grounds, cels)
    write_town(save, grounds, cels, spite_cels)

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
    """An ear: a triangle a pixel wide at the tip, widening downward, leaning
    `lean` pixels outward per row.

    It widens on the *first* step rather than the second. One pixel of fur plus
    a pixel of rim either side is a 3-pixel black-edged spike, and four rows of
    that is a horn, not an ear -- which is exactly what the first version drew.
    """
    out = []
    for i in range(height):
        half = (i + 1) // 2
        x = tip_x + int(round(lean * i))
        out.append((tip_y + i, x - half, x + half, k))
    return out


def curl(points, k=1, thick=2):
    """A tail: a four-connected line through the given points, two pixels thick
    at the root and one at the tip.

    Four-connected matters. A purely diagonal run of single pixels is not a line
    once the eight-connected rim has gone round it -- it is a row of beads with
    daylight between them, which is what the first version drew and what made
    the tail read as dirt on the lens."""
    path = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        x, y = x0, y0
        path.append((x, y))
        while (x, y) != (x1, y1):
            if x != x1:
                x += 1 if x1 > x else -1
                path.append((x, y))
            if y != y1:
                y += 1 if y1 > y else -1
                path.append((x, y))
    path.append(points[-1])
    out = []
    for i, (x, y) in enumerate(path):
        w = thick if i < len(path) * 0.5 else 1
        out.append((y, x, x + w - 1, k))
    return out


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
        + [(14, 11, 15, 2), (15, 11, 15, 2), (16, 11, 15, 2)]            # neck
        + blob(8.5, 12, [3, 4, 4.5, 4.5, 4.5, 4.5, 4, 3], fur)           # head
        + [(16, 2, 5, 2), (17, 2, 5, 2), (18, 3, 5, 3)]                  # snout
    )
    # No tail in the front view. Seen head-on a dog's tail is behind it, and
    # every attempt to show it either collided with the far ear or floated off
    # the silhouette as a stub the rim could not reach.
    down = (
        blob(15.5, 10, [3.5, 4.5, 5.5, 5.5, 5.5, 4.5, 3.5], 2)           # shoulders
        + wedge(11, 8, 5, 2, lean=-0.5) + wedge(20, 8 - e, 5, 3, lean=0.5)
        + blob(15.5, 14, [3.5, 5.5, 6.5, 6.5, 6.5, 6.5, 5.5, 4.5], fur)  # head
        + blob(15.5, 22, [2.5, 2.5], 2)                                  # muzzle
    )
    up = (
        wedge(11, 8, 5, 2, lean=-0.5) + wedge(20, 8 - e, 5, 3, lean=0.5)
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
        + [(15, 12, 16, 2), (16, 12, 16, 2), (17, 12, 16, 2)]            # neck
        + blob(9.5, 14, [2.5, 3.5, 3.5, 3.5, 3.5, 2.5], fur)
        + [(17, 4, 7, 2), (18, 5, 7, 3)]
    )
    # A cat facing you keeps its tail up and visible past its own shoulder --
    # which is the one place on the silhouette it does not collide with an ear.
    down = (
        curl([(21, 14), (22, 12 - t), (23, 10 - t), (23, 8 - t)], 2)
        + blob(15.5, 13, [2.5, 3.5, 4.5, 4.5, 3.5, 2.5], 2)
        + wedge(12, 9, 6, 2, lean=-0.3) + wedge(19, 9 - e, 6, 3, lean=0.3)
        + blob(15.5, 16, [3.5, 4.5, 5.5, 5.5, 5.5, 4.5, 3.5], fur)
        + blob(15.5, 22, [2.0, 2.0], 2)
    )
    up = (
        wedge(12, 9, 6, 2, lean=-0.3) + wedge(19, 9 - e, 6, 3, lean=0.3)
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
        if stripes and (y % 3) == 0 and x1 - x0 >= 6:
            c.row(y, x0 + 2, x0 + 3, fur[min(len(fur) - 1, k + 2)])
            c.row(y, x1 - 4, x1 - 3, fur[min(len(fur) - 1, k + 2)])
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


# --- Spite ----------------------------------------------------------------------
#
# The other person in the game, and the first one the player talks to. He is
# written before he is drawn -- data/content/spite.json and data/dialogue/
# spite.json are the brief -- so the only job here is not to contradict them.
#
# What the writing says, and what each line costs in pixels:
#
#   "Because I am what is left over when you talk yourself out of things. There
#   is a great deal of me. I would like there to be less."
#
# He is not a villain and he is not cute. He is the sneer, and the sneer is
# ashamed of itself. So: THIN, and composed SMALL inside his own portrait, with
# too much air above his head. A character who wants there to be less of him
# does not fill his frame.
#
#   "Four hundred and six. That's how many times you have opened that door."
#
# He is the one who remembers. He has been SITTING on your step for four
# hundred loops while you walked. So he carries nothing: no pack, no belt kit,
# no bedroll. The traveller is equipped; Spite is not going anywhere.
#
# The two alters, and this is the whole of the portrait spec:
#
#   kind  "the one who remembers you"          -- the face doing the OPEN thing
#   wary  "the one who remembers the endings"  -- the face doing the CLOSED thing
#
# Three deliberate inversions of the player, because the reason to draw a second
# character is to say something the first one cannot:
#
#   NO HOOD. The traveller is a hood with a suggestion of a face in it; you have
#   never seen who you are playing. Spite is a bare head and a whole face,
#   because he has nothing to keep the weather off and nowhere to be. The
#   silhouettes therefore differ at the crown, which is the first thing the eye
#   reads on a 32px figure.
#
#   ARMS IN. Every frame of the traveller has arms swinging OUTSIDE his own
#   outline -- the file above spends a paragraph on why. Spite walks with his
#   hands in his pockets, elbows out, arms inside the silhouette. Open versus
#   closed, said in the outline rather than in the face, so it survives the zoom.
#
#   THE SCARF, UNTIED. He wears the same object the traveller wears: the one
#   saturated garment, in the same WARM ramp, at the same place on the body. The
#   traveller has it wrapped twice at the throat. Spite has it hanging loose in
#   two uneven ends. Same colour, same cloth, worn as though abandoned -- which
#   is the shortest way to draw "I am part of you" without drawing your face.
#
# That last point is load-bearing for a different reason. The Warden is already
# "your face, thirty years further on", so a second character built out of the
# player's face would be the same trick twice. Spite is not the player's face.
# He is the player's coat.
#
# Authored, not generated, and the reasoning is the pipeline skill's own:
#
#   The skill's hard finding is that the model cannot hold an identity across
#   images. TWO PORTRAITS OF ONE MAN IN TWO MOODS IS EXACTLY THAT PROBLEM --
#   it is the sprite-sheet failure with two cells instead of twelve. Generating
#   `kind` and `wary` separately buys two different men, and "the same person,
#   twice" is the entire requirement. Here the two moods are one geometry table
#   plus a delta, so they cannot drift: same skull, same hair, same nose, same
#   scarf, by construction.
#
#   And every colour on him is mixed from data/themes/firstlight.json, the same
#   way the traveller and the animals are. A quantised render does not land in
#   those ramps, and a cast where one member is off-palette reads as a cast with
#   a guest in it.
#
# Quota spent: zero.

PORTRAITS = os.path.join(ROOT, "assets", "portraits")

PW = 56                              # the portrait's logical size...
PSCALE = 2                           # ...doubled to the 112 the screen asks for
MOODS = ["kind", "wary"]             # the alter ids in data/content/spite.json

# His hair. The brightest thing on him and the only place he outranks the
# traveller in value, so the head is what you see first at 3x on dark ground.
HAIR = [
    mix(C["muted"], C["text"], 0.42),   # 0  lit -- deliberately no brighter than
    mix(C["muted"], C["text"], 0.14),   # 1     the traveller's crown specular
    C["muted"],                         # 2  base
    mix(C["line"], C["muted"], 0.50),   # 3  shade
    mix(C["line"], C["bg"], 0.20),      # 4  the deep side, the brows, the fringe
]

# His skin is the traveller's SKIN with the blood out of it -- literally the
# same base mix pushed toward `muted`. Same person, worse week.
# It must also sit BELOW the hair in value. The first cut put the base at luma
# 160 against hair at 146, so in profile the face was the brightest thing on the
# figure and read as a beak on a grey skull -- the exact failure the traveller's
# draw_brow() records. Base 128 now: the hair is the pale cap, the face is the
# mid tone under it, and the head reads as a head from the side.
_SSKIN = mix(mix(_SKIN, C["muted"], 0.38), C["bg"], 0.22)
SSKIN = [
    mix(_SSKIN, C["text"], 0.22),       # 0  lit -- nose ridge, cheekbone
    _SSKIN,                             # 1  base
    mix(_SSKIN, C["bg"], 0.30),         # 2  the shaded side of the face
    mix(_SSKIN, C["bg"], 0.58),         # 3  under the jaw, in the collar
    mix(C["bg"], BLACK, 0.30),          # 4  eyes, mouth line
]

# The coat. The traveller's own COOL ramp, used from the dark end only, so the
# two of them are cut from one bolt of cloth and Spite is the darker cut.
COAT_LIT, COAT, COAT_DK, COAT_DEEP = 4, 5, 6, 7


# --- the overworld sprite -------------------------------------------------------
#
#   y  3..6    hair        a pale cap, 12 wide -- against the traveller's 16-wide
#                          hood, so the crowns differ before anything else does
#   y  7..13   face        uncovered. Seven rows: brow, eyes, cheek, nose, mouth,
#                          jaw, chin
#   y 14..16   neck        and the scarf's loop
#   y 17..19   shoulders   18 wide, against the traveller's 22, and rising into
#                          the neck rather than squaring off -- the hunch
#   y 20..32   coat        long, straight, no taper. Elbows push the outline out
#                          at 23..26: hands in pockets, said in the silhouette
#   y 33..44   legs        12 rows against the traveller's 15, because the coat
#                          is longer. He shows less leg, so he strides less
#   y 40..47   shadow
#
# He tops out at y3 where the traveller tops out at y1. Two rows shorter, and
# all of it taken out of the neck.

SP_HEAD_F = [
    (3, 12, 19), (4, 11, 20), (5, 10, 21), (6, 10, 21),
    (7, 10, 21), (8, 10, 21), (9, 10, 21), (10, 10, 21),
    (11, 10, 21), (12, 11, 20), (13, 12, 19),
]
SP_NECK_F = [(14, 13, 18), (15, 12, 19), (16, 11, 20)]

SP_BODY_F = [
    (17, 9, 22), (18, 7, 24), (19, 7, 24),
    (20, 7, 24), (21, 7, 24), (22, 7, 24),
    (23, 6, 25), (24, 6, 25), (25, 6, 25), (26, 6, 25),   # elbows
    (27, 7, 24), (28, 7, 24),
    (29, 8, 23), (30, 8, 23), (31, 8, 23), (32, 8, 23),
]
# The coat is most of him, so where it sits in value decides whether he is
# legible at all. COOL has a deliberate hole between 43 and 90 -- sand, ice,
# dune and snow all live in it -- so the body stays at 108 and 90 and only the
# skirt, the seams and the opening drop through to 43 and 30. Filling the lower
# half with COAT_DK cost 35% of the figure "lost" on grass; this is 21%.
SP_BODY_F_K = [COAT_LIT, COAT_LIT, COAT_LIT,
               COAT_LIT, COAT_LIT, COAT,
               COAT, COAT, COAT, COAT,
               COAT, COAT,
               COAT, COAT, COAT_DK, COAT_DK]
SP_HEM_F = [(33, 8, 14), (33, 17, 23)]


def sp_hair_front(f, dy, back=False):
    """The cap of hair. Parted and uneven on purpose: a clean edge all the way
    round reads as a helmet at this size, and he is not wearing one."""
    for (y, x0, x1) in SP_HEAD_F[:4]:
        f.row(y + dy, x0, x1, HAIR[2])
        f.row(y + dy, x0, x0 + 2, HAIR[1])
        f.px(x0, y + dy, HAIR[0])
        f.row(y + dy, x1 - 1, x1, HAIR[3])
    if back:
        # From behind there is no fringe and no face: hair to the nape, one
        # part, one cowlick. The head is a pale oval and nothing else -- which
        # is the whole of the up/down tell above the shoulders.
        for (y, x0, x1) in SP_HEAD_F[4:]:
            f.row(y + dy, x0, x1, HAIR[2])
            f.row(y + dy, x0, x0 + 2, HAIR[1])
            f.px(x0, y + dy, HAIR[0])
            f.row(y + dy, x1 - 1, x1, HAIR[3])
        f.px(12, 4 + dy, HAIR[1])                    # a cowlick off the crown
        f.px(19, 5 + dy, HAIR[3])
        f.row(12 + dy, 12, 19, HAIR[3])              # the nape, turning away
        f.row(13 + dy, 13, 18, HAIR[4])
        return
    # The fringe, parted: hair down the temples to the eye line, forehead bare
    # between them. Two dark bands across a 12-pixel head read as goggles; one
    # band with a gap in it reads as hair.
    f.row(7 + dy, 10, 13, HAIR[3])
    f.row(7 + dy, 18, 21, HAIR[4])
    f.px(13, 8 + dy, HAIR[4])
    f.px(18, 8 + dy, HAIR[4])
    f.col(10, 8 + dy, 10 + dy, HAIR[3])              # temples
    f.col(21, 8 + dy, 10 + dy, HAIR[4])


def sp_face_front(f, dy):
    """Seven rows of face. The traveller has never shown one, and that is the
    point: you have played four hundred runs without seeing who you are, and the
    first face in the game belongs to the part of you that sneers."""
    for (y, x0, x1) in SP_HEAD_F[4:]:
        f.row(y + dy, x0, x1, SSKIN[1])
        f.row(y + dy, x1 - 2, x1, SSKIN[2])          # lit from the north-west
    f.row(7 + dy, 14, 17, SSKIN[1])                  # the forehead, between the
    f.px(14, 7 + dy, SSKIN[0])                       # two halves of the fringe
    f.row(8 + dy, 12, 13, HAIR[3])                   # brows: two pixels each. A
    f.row(8 + dy, 18, 19, HAIR[3])                   # bar reads as goggles
    f.row(9 + dy, 12, 13, SSKIN[4])                  # eyes
    f.row(9 + dy, 18, 19, SSKIN[4])
    f.px(15, 10 + dy, SSKIN[0])                      # nose, the one lit skin
    f.px(16, 10 + dy, SSKIN[2])
    f.row(12 + dy, 15, 16, SSKIN[3])                 # the mouth. Two pixels, and
    f.px(17, 12 + dy, SSKIN[3])                      # a third at one corner --
    f.row(13 + dy, 14, 17, SSKIN[2])                 # a wider one is a moustache


def sp_scarf(f, dy, front=True):
    """The traveller's scarf, untied. Wrapped, it is what keeps his throat warm
    on the mountain; hanging, it is just cloth he has not taken off. Two ends of
    different lengths, because a tied scarf is even and this one is not."""
    f.row(15 + dy, 12, 19, WARM[1])
    f.row(15 + dy, 12, 13, WARM[0])
    f.row(16 + dy, 11, 20, WARM[2])
    f.row(16 + dy, 11, 12, WARM[1])
    f.row(16 + dy, 19, 20, WARM[3])
    if not front:
        return
    for y in range(17, 27):                          # the long end
        f.row(y + dy, 12, 13, WARM[2])
        f.px(12, y + dy, WARM[1])
    f.row(27 + dy, 12, 13, WARM[3])
    for y in range(17, 23):                          # the short one
        f.row(y + dy, 18, 19, WARM[3])
        f.px(18, y + dy, WARM[2])


def sp_coat_front(f, dy):
    """The coat, open, with nothing under it worth showing: a dark column down
    the middle. The lapels are the only lit line on the body, and they point at
    the face."""
    for y in range(19, 33):                          # the opening
        f.row(y + dy, 15, 16, cool(COAT_DEEP))
    for i in range(4):                               # lapels
        f.px(14 - i, 19 + i + dy, cool(COAT_LIT - 1))
        f.px(17 + i, 19 + i + dy, cool(COAT_DK))
    # Sleeves: a panel down each side one step darker than the coat, so the arms
    # read as arms without leaving the silhouette.
    for y in range(20, 28):
        f.row(y + dy, 7, 9, cool(COAT_DK))
        f.px(7, y + dy, cool(COAT))
        f.row(y + dy, 22, 24, cool(COAT_DEEP))
    f.row(28 + dy, 8, 9, LEATHER[2])                 # cuffs, going into pockets
    f.row(28 + dy, 22, 23, LEATHER[3])
    f.row(29 + dy, 9, 11, cool(COAT_DK))             # the pocket mouths
    f.row(29 + dy, 20, 22, cool(COAT_DEEP))


def sp_coat_back(f, dy):
    """From behind: one seam, no opening, no lapels, and the same sleeves. The
    warm note is only the loop at his neck, so the front shows colour down the
    chest and the back shows a collar -- the same device the traveller's pack
    plays, in reverse."""
    f.col(15, 19 + dy, 32 + dy, cool(COAT_DK))
    f.col(16, 19 + dy, 32 + dy, cool(COAT_DEEP))
    for y in range(20, 28):
        f.row(y + dy, 7, 9, cool(COAT_DK))
        f.px(7, y + dy, cool(COAT))
        f.row(y + dy, 22, 24, cool(COAT_DEEP))
    f.row(28 + dy, 8, 9, LEATHER[2])
    f.row(28 + dy, 22, 23, LEATHER[3])
    f.row(19 + dy, 10, 21, cool(COAT_LIT - 1))       # the yoke seam


def sp_legs_frontal(f, pose, dy):
    """Twelve rows of leg against the traveller's fifteen. Same contract: the
    planted boot ends on SOLE, the lifted one is drawn short."""
    def leg(x0, lift, out):
        top = 33 + dy
        bot = SOLE - lift
        for y in range(top, bot - 3 + 1):
            f.row(y, x0, x0 + 3, cool(COAT))
            f.px(x0, y, cool(COAT_LIT))
            f.px(x0 + 3, y, cool(COAT_DK))
        for y in range(bot - 2, bot + 1):
            f.row(y, x0 - out, x0 + 3, LEATHER[1])
            f.px(x0 - out, y, LEATHER[0])
        f.row(bot, x0 - out, x0 + 3, LEATHER[2])

    if pose == "neutral":
        leg(11, 0, 1)
        leg(17, 0, 0)
    elif pose == "step_left":
        leg(10, 0, 1)
        leg(18, 4, 0)
    else:
        leg(10, 4, 1)
        leg(18, 0, 0)


def sp_build_frontal(pose, facing_up):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    sculpt(f, SP_NECK_F, [COAT_DK] * 3, dy, hi=1, sh=1)
    sculpt(f, SP_BODY_F, SP_BODY_F_K, dy)
    sculpt(f, SP_HEM_F, COAT_DEEP, dy)
    sp_hair_front(f, dy, back=facing_up)
    if not facing_up:
        sp_face_front(f, dy)
    if facing_up:
        sp_coat_back(f, dy)
    else:
        sp_coat_front(f, dy)
    sp_scarf(f, dy, front=not facing_up)
    # The coat swings a column against the stride, as the traveller's cloak does.
    if pose == "step_left":
        f.col(24, 29 + dy, 32 + dy, cool(COAT_DEEP))
        f.row(33 + dy, 17, 24, cool(COAT_DEEP))
    elif pose == "step_right":
        f.col(7, 29 + dy, 32 + dy, cool(COAT_DK))
        f.row(33 + dy, 7, 14, cool(COAT_DEEP))
    sp_legs_frontal(f, pose, dy)
    return f


# --- his profile ----------------------------------------------------------------
#
# The traveller's side view is sold by a hood brim jutting two pixels forward.
# Spite has no brim, so his is sold by the two features a bare head has and a
# hood hides: a nose that breaks the outline, and a mass of hair behind the
# skull that the neck does not follow. Both are two-pixel steps, which is what
# the traveller's file measured as the minimum that survives 3x.

SP_HEAD_P = [
    (3, 12, 20), (4, 11, 21), (5, 11, 21), (6, 11, 21),
    (7, 10, 21), (8, 10, 21), (9, 9, 20), (10, 10, 20),
    (11, 10, 19), (12, 11, 19), (13, 12, 18),
]
SP_NECK_P = [(14, 13, 18), (15, 12, 19), (16, 11, 20)]
SP_BODY_P = [
    (17, 9, 21), (18, 8, 22), (19, 8, 22),
    (20, 8, 22), (21, 8, 22), (22, 8, 22),
    (23, 7, 22), (24, 7, 22), (25, 7, 22), (26, 7, 22),
    (27, 8, 23), (28, 8, 24),
    (29, 8, 24), (30, 8, 25), (31, 8, 25), (32, 8, 25),
]
SP_BODY_P_K = SP_BODY_F_K
SP_HEM_P = [(33, 8, 25)]


def sp_build_profile(pose):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    sculpt(f, SP_NECK_P, [COAT_DK] * 3, dy, hi=1, sh=1)
    sculpt(f, SP_BODY_P, SP_BODY_P_K, dy)
    sculpt(f, SP_HEM_P, COAT_DEEP, dy)

    # Hair: the whole skull, overhanging the neck at the back.
    for (y, x0, x1) in SP_HEAD_P:
        f.row(y + dy, x0, x1, HAIR[2])
        f.row(y + dy, x1 - 2, x1, HAIR[3])
        f.px(x1, y + dy, HAIR[4])
    for (y, x0, x1) in SP_HEAD_P[:3]:
        f.px(x0, y + dy, HAIR[0])
        f.px(x0 + 1, y + dy, HAIR[1])
    # The face: a notch four pixels wide cut out of the front of that hair, and
    # no wider. The traveller's file records that a lit wedge sticking out of a
    # pale dome is a bird's head at any zoom; the fix there was to stop lighting
    # the brim, and the fix here is to stop the skin before it becomes the
    # silhouette. Only the nose ridge -- one pixel, on the row the outline
    # already steps forward -- gets the lit tone.
    f.row(8 + dy, 10, 11, SSKIN[1])                  # brow and eye socket
    f.px(10, 8 + dy, SSKIN[4])                       # the eye
    f.row(9 + dy, 9, 11, SSKIN[1])                   # the nose, out one pixel
    f.px(9, 9 + dy, SSKIN[0])
    f.px(10, 10 + dy, SSKIN[2])                      # under it, in its own shade
    f.px(11, 10 + dy, SSKIN[1])
    f.px(10, 11 + dy, SSKIN[3])                      # the mouth
    f.px(11, 11 + dy, SSKIN[2])
    f.row(12 + dy, 11, 12, SSKIN[3])                 # jaw, into the collar
    f.px(13, 7 + dy, HAIR[4])                        # the fringe over the brow

    f.col(21, 19 + dy, 31 + dy, cool(COAT_DEEP))     # the coat's back seam
    if pose != "neutral":                            # its skirt, thrown back on
        for y in range(26, 33):                      # the step frames only
            t = int(round(3 * (y - 25) / 7.0))
            f.row(y + dy, 25, 25 + t, cool(COAT_DEEP))

    sp_scarf(f, dy, front=False)
    for y in range(17, 26):                          # one end, over the chest
        f.row(y + dy, 9, 10, WARM[2])
        f.px(9, y + dy, WARM[1])
    f.row(26 + dy, 9, 10, WARM[3])

    # The near arm, inside the outline, hand in the pocket: a panel with an
    # elbow that pushes the coat's back edge, not its front.
    # In a side view the near arm lies OVER the torso, toward the front, not
    # against the back seam -- the first cut had it at the back and it read as a
    # satchel, which is the one prop he must not have.
    # And it CATCHES light rather than losing it. Drawn a step darker than the
    # coat it lies on, an arm at this size is a black rectangle -- a hole, not a
    # limb. Lit panel, one dark seam behind it, one at the cuff.
    ax = {"neutral": 11, "step_left": 10, "step_right": 12}[pose]
    for y in range(20, 28):
        f.row(y + dy, ax, ax + 3, cool(COAT_LIT))
        f.px(ax, y + dy, cool(COAT_LIT - 1))
        f.px(ax + 4, y + dy, cool(COAT_DEEP))        # the seam behind the arm
    f.row(28 + dy, ax, ax + 3, LEATHER[2])           # cuff into the pocket
    f.row(29 + dy, ax + 1, ax + 2, cool(COAT_DEEP))

    # Legs, near and far, with a pixel of daylight between them at rest.
    if pose == "neutral":
        near, far, nlift, flift = 11, 16, 0, 0
    elif pose == "step_left":
        near, far, nlift, flift = 9, 18, 0, 3
    else:
        near, far, nlift, flift = 18, 9, 3, 0

    def leg(x0, lift, shade, toe):
        top = 33 + dy
        bot = SOLE - lift
        for y in range(top, bot - 3 + 1):
            f.row(y, x0, x0 + 3, cool(COAT + shade))
            f.px(x0, y, cool(COAT_LIT + shade))
        for y in range(bot - 2, bot + 1):
            f.row(y, x0 - toe, x0 + 3, LEATHER[1 + shade])
            f.px(x0 - toe, y, LEATHER[0 + shade])
        f.row(bot, x0 - toe, x0 + 3, LEATHER[2])

    leg(far, flift, 1, 0)
    leg(near, nlift, 0, 2)
    return f


def sp_build(facing, pose):
    if facing == "down":
        return sp_build_frontal(pose, False).img
    if facing == "up":
        return sp_build_frontal(pose, True).img
    return sp_build_profile(pose).img


def sp_build_all():
    cels = {}
    for fa in ("down", "up"):
        for po in FRAMES:
            cels[(fa, po)] = sp_build(fa, po)
    prof = recentre([sp_build("left", po) for po in FRAMES])
    for po, im in zip(FRAMES, prof):
        cels[("left", po)] = im
    for key in list(cels):
        contact_shadow(rim(cels[key]), rx=9.5, ry=4.0)
    lb = [cels[("left", po)].getbbox() for po in FRAMES]
    lc = (min(b[0] for b in lb) + max(b[2] for b in lb) - 1) / 2.0
    for po in FRAMES:
        cels[("right", po)] = cels[("left", po)].transpose(Image.FLIP_LEFT_RIGHT)
    rb = [cels[("right", po)].getbbox() for po in FRAMES]
    rc = (min(b[0] for b in rb) + max(b[2] for b in rb) - 1) / 2.0
    shift = int(round(lc - rc))
    if shift:
        for po in FRAMES:
            n = Image.new("RGBA", (FW, FH), CLEAR)
            n.paste(cels[("right", po)], (shift, 0))
            cels[("right", po)] = n
    return cels


# --- the dialogue portrait ------------------------------------------------------
#
# 112x112, because that is what DialogueScreen._portrait() reserves and has
# reserved since before there was any art -- the placeholder plate is already
# that size so the layout would not move when this landed.
#
# Drawn at 56 and doubled. That is the one decision here worth defending: 112
# native pixels would be a finer grain than anything else on the screen -- the
# world runs 32px tiles at ZOOM 3, so a world pixel is three logical pixels and
# a native portrait pixel would be one. At 56x2 a portrait pixel is two, which
# reads as "closer than the world" rather than as "a different game". It also
# keeps the face inside a budget an authored table can actually fill: 3,136
# cells, against the traveller's 773.
#
# COMPOSITION. He sits low and small with a lot of air over his head. That is
# not a mistake and it is not framing convention -- it is the line:
#
#   "There is a great deal of me. I would like there to be less."
#
# A character who says that does not get a heroic bust that fills its plate.
# Behind him, two faint vertical seams: the door he has his back to.
#
# THE TWO MOODS. One geometry table, one delta. Same skull, same hair, same
# nose, same scarf, same light, same framing -- so they cannot be two different
# men, which is exactly the failure mode a generated pair would have had. What
# changes is what a face actually changes:
#
#   kind   head level, eyes open three rows, brows level, mouth level and
#          slightly parted, shoulders down, collar down so the scarf shows.
#   wary   head sunk one row into shoulders raised two, upper lids down over a
#          row of each eye, brows ASYMMETRIC -- one up, one down, which is what
#          a sneer actually is and reads at 112px where a curled lip does not --
#          mouth pulled up at one corner, collar up over the jaw, face a step
#          colder.
#
# The head moving down while the shoulders move up is worth two rows of pixels
# and does most of the work: at a glance, before any feature resolves, `wary` is
# a man with his head pulled in and `kind` is a man with his head out.

# The skull. Twenty-two rows, twenty wide, crown at y12 -- which leaves eleven
# rows of empty door above his head. That headroom is the line, drawn:
#
#   "There is a great deal of me. I would like there to be less."
#
# A character who says that does not get a heroic bust that fills its plate.
P_HEAD = [
    (12, 22, 33), (13, 20, 35), (14, 19, 36), (15, 18, 37),
    (16, 18, 37), (17, 18, 37), (18, 18, 37), (19, 18, 37),
    (20, 18, 37), (21, 18, 37), (22, 18, 37), (23, 18, 37),
    (24, 18, 37), (25, 18, 37), (26, 19, 36), (27, 19, 36),
    (28, 20, 35), (29, 20, 35), (30, 21, 34), (31, 22, 33),
    (32, 23, 32), (33, 25, 30),
]
P_HAIRLINE = 20                      # the last row that is hair, not forehead
P_SHOULDER = 38                      # where the coat starts, four rows under the
                                     # jaw. The first cut left seven rows of bare
                                     # neck and he read as a totem pole.


class Plate:
    """A portrait canvas. Opaque, unlike a sprite cel -- a portrait is a picture
    with a background, not a cut-out."""

    def __init__(self, w, h, base):
        self.w, self.h = w, h
        self.img = Image.new("RGBA", (w, h), tuple(base) + (255,))

    def px(self, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
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


def sk(i):
    return SSKIN[max(0, min(len(SSKIN) - 1, i))]


def p_ground(p):
    """The door he has his back to. Two plank seams, a rail, and a lift in the
    value where the head will be -- so a dark coat has something to be dark
    against and he is somewhere rather than nowhere."""
    for y in range(p.h):
        t = 1.0 - abs(y - 22) / 44.0
        base = mix(C["bg"], C["panel"], 0.26 + 0.34 * max(0.0, t))
        for x in range(p.w):
            u = (x - 27.5) / 31.0
            p.px(x, y, mix(base, C["bg"], min(1.0, u * u * 1.7)))
    for x in (8, 46):
        p.col(x, 0, p.h - 1, mix(C["bg"], C["line"], 0.22))
        p.col(x + 1, 0, p.h - 1, mix(C["bg"], BLACK, 0.14))
    p.row(7, 9, 45, mix(C["bg"], C["line"], 0.16))          # a rail across it
    p.row(8, 9, 45, mix(C["bg"], BLACK, 0.14))


def p_coat(p, dy, collar_up):
    """Coat, collar and the untied scarf. Everything below the jaw.

    It runs off all three lower edges of the plate. A bust floating clear of its
    own frame is a cut-out; one that leaves the picture is a person sitting in
    front of you, which is where the conversation says he is."""
    yoke = [(38, 18, 37), (39, 15, 40), (40, 12, 43), (41, 9, 46),
            (42, 6, 49), (43, 3, 52)]
    for (y, x0, x1) in yoke:
        p.row(y + dy, x0, x1, cool(COAT))
        p.row(y + dy, x0, x0 + 5, cool(COAT_LIT))
        p.row(y + dy, x1 - 6, x1, cool(COAT_DK))
    for y in range(44, 56):
        p.row(y + dy, 0, p.w - 1, cool(COAT))
        p.row(y + dy, 0, 8, cool(COAT_LIT))
        p.row(y + dy, 44, p.w - 1, cool(COAT_DK))
    p.row(43 + dy, 3, 52, cool(COAT_LIT))                   # the shoulder's edge
    p.row(43 + dy, 40, 52, cool(COAT_DK))

    # The collar: two lapels with a hard seam either side, standing higher and
    # closer to the throat when he is closed. Drawn as widening wedges of the
    # same cool ramp they lie on, they vanished -- a lapel at this size is its
    # SEAMS, not its shading.
    top = 33 if collar_up else 37
    for i, y in enumerate(range(top, 56)):
        w = min(12, 1 + i)
        p.row(y + dy, 25 - w, 25, cool(COAT_LIT))
        p.px(25 - w, y + dy, cool(COAT_DEEP))
        p.px(25, y + dy, cool(COAT_DEEP))
        p.row(y + dy, 30, 30 + w, cool(COAT_DK))
        p.px(30 + w, y + dy, cool(COAT_DEEP))
        p.px(30, y + dy, cool(COAT_DEEP))

    # The neck: four rows, and dark. It is a hollow between two lapels, not a
    # column holding up a head.
    p.box(24, 34 + dy, 31, top + 1 + dy, sk(3))
    p.box(24, 34 + dy, 26, top + 1 + dy, sk(2))
    p.row(34 + dy, 24, 31, sk(4))                           # the jaw's shadow

    # The scarf: the traveller's own garment, untied. A loop round the throat
    # and two ends of different lengths, one longer than the plate, with the
    # coat's dark opening showing between them.
    #
    # Small. The first cut widened it a pixel a row and he was wearing a bib --
    # the accent is 6% of the traveller by area and it has to stay about that
    # here, or the one saturated thing in a cold palette becomes the subject.
    ly = top + 1
    for i, y in enumerate(range(ly, ly + 4)):
        w = 4 + min(i, 2)
        p.row(y + dy, 27 - w, 28 + w, WARM[1])
        p.row(y + dy, 27 - w, 29 - w, WARM[0])
        p.row(y + dy, 26 + w, 28 + w, WARM[2])
    for i, y in enumerate(range(ly + 4, 56)):               # the long end
        x0 = 22 - i // 5
        p.row(y + dy, x0, x0 + 4, WARM[2])
        p.row(y + dy, x0, x0 + 1, WARM[1])
        p.px(x0 + 4, y + dy, WARM[3])
    for y in range(ly + 4, min(56, ly + 11)):               # the short one
        p.row(y + dy, 30, 33, WARM[3])
        p.row(y + dy, 30, 31, WARM[2])


def p_head(p, dy, warm):
    """Skull, hair, nose and the flat of the face. Identical in both moods --
    every difference between them lives in the three functions below."""
    for (y, x0, x1) in P_HEAD:
        if y <= P_HAIRLINE:
            continue
        p.row(y + dy, x0, x1, sk(1 - warm))
        p.row(y + dy, x0, x0 + 2, sk(0 - warm))       # lit from the north-west
        p.row(y + dy, x1 - 3, x1, sk(2 - warm))
        p.px(x1, y + dy, sk(3 - warm))
    for (y, x0, x1) in P_HEAD:                        # the cap of hair
        if y > P_HAIRLINE:
            break
        p.row(y + dy, x0, x1, HAIR[2])
        p.row(y + dy, x0, x0 + 3, HAIR[1])
        p.row(y + dy, x0, x0 + 1, HAIR[0])
        p.row(y + dy, x1 - 4, x1, HAIR[3])
        p.px(x1, y + dy, HAIR[4])
    for (y, x0, x1) in P_HEAD:                        # temples, past the eye
        if not (P_HAIRLINE < y <= 26):
            continue
        p.row(y + dy, x0, x0 + 1, HAIR[3])
        p.row(y + dy, x1 - 1, x1, HAIR[4])
    # The fringe: an uneven edge, cut by nobody. A straight one is a helmet.
    for x, drop in ((19, 2), (20, 3), (21, 1), (23, 2), (24, 3), (26, 1),
                    (28, 2), (29, 1), (31, 2), (32, 3), (34, 1), (35, 2),
                    (36, 1)):
        for k in range(drop):
            p.px(x, P_HAIRLINE + 1 + k + dy, HAIR[3] if x < 27 else HAIR[4])
    # The nose: a lit ridge and a shaded flank, then a tip with two nostrils.
    # Drawn as two full-length columns it was a bar down the middle of the face.
    p.col(27, 24 + dy, 27 + dy, sk(0 - warm))
    p.col(28, 25 + dy, 28 + dy, sk(2 - warm))
    p.row(28 + dy, 26, 29, sk(0 - warm))
    p.px(25, 28 + dy, sk(3))                          # nostrils
    p.px(30, 28 + dy, sk(3))
    p.px(25, 29 + dy, sk(2 - warm))                   # and the crease beside
    p.px(30, 29 + dy, sk(2 - warm))                   # each -- a full row of
                                                      # shade here runs into the
                                                      # mouth and makes a muzzle
    # Cheekbone and jaw, so the head is a solid and not a disc. Along the edge,
    # not a patch in the middle of it.
    for y in range(25, 31):
        p.row(y + dy, 34, 36, sk(2 - warm))
    p.px(33, 27 + dy, sk(2 - warm))
    p.px(33, 28 + dy, sk(2 - warm))
    p.px(22, 29 + dy, sk(2 - warm))                   # under the cheekbones, so
    p.px(33, 29 + dy, sk(2 - warm))                   # the jaw is narrower than
    p.px(23, 30 + dy, sk(2 - warm))                   # the cheekbone above it
    p.px(32, 30 + dy, sk(2 - warm))
    p.row(32 + dy, 25, 30, sk(2 - warm))              # under the lip
    p.row(33 + dy, 26, 29, sk(3))                     # the chin, turning under


def p_eyes(p, dy, lid, warm):
    """Four pixels wide, three rows tall, two of pupil and one of white either
    side. The lid coming down over the top row is the whole of the difference
    between a man looking at you and a man who has already decided how it goes.
    """
    for x0 in (21, 31):
        p.row(23 + dy, x0 - 1, x0 + 4, sk(2 - warm))     # the socket
        p.box(x0, 24 + dy, x0 + 3, 25 + dy, sk(0))       # the whites
        p.box(x0 + 1, 24 + dy, x0 + 2, 25 + dy, sk(4))   # iris and pupil
        p.row(26 + dy, x0 - 1, x0 + 4, sk(1 - warm))     # lower lid, catching
        if lid:
            p.row(24 + dy, x0, x0 + 3, sk(3))
            p.px(x0 + 1, 24 + dy, sk(4))
            p.px(x0 + 2, 24 + dy, sk(4))
        else:
            p.px(x0 + 1, 24 + dy, C["text"])             # one pixel of catchlight


def p_brows(p, dy, base, tilt):
    """Two rows of hair over each eye, the lower one inset so the brow tapers
    instead of sitting there as a bar. `tilt` is per-brow: one of them a row
    higher than the other is a raised eyebrow, and that -- not a curled lip --
    is what a sneer looks like from across a doorstep."""
    for (x0, x1, t) in ((20, 25, tilt[0]), (30, 35, tilt[1])):
        y = base + t
        p.row(y + dy, x0, x1, HAIR[3])
        p.row(y + 1 + dy, x0 + 2, x1 - 2, HAIR[4])
        p.px(x0, y + dy, HAIR[2])


def p_mouth(p, dy, curl, warm):
    """A flat line and nothing under it. It is never a smile in either mood --
    `kind` is open, not happy -- so the whole expression is the corner.

    Two rows of it with a lit lower lip gave him teeth and a grin. One row, the
    darkest value only in the middle of it, and for the sneer the whole right
    half lifted a row rather than a hook stuck on the end."""
    if curl:
        p.row(30 + dy, 24, 31, sk(3))
        p.row(30 + dy, 26, 29, sk(4))
        p.px(31, 29 + dy, sk(3))                      # two pixels of corner,
        p.px(32, 29 + dy, sk(3))                      # up. Lifting the whole
        p.px(24, 31 + dy, sk(3))                      # right half instead put
                                                      # a moustache under his
                                                      # nose at 1:1
    else:
        p.row(30 + dy, 24, 31, sk(3))
        p.row(30 + dy, 26, 29, sk(4))
        p.px(24, 30 + dy, sk(2 - warm))
        p.px(31, 30 + dy, sk(2 - warm))
        p.row(31 + dy, 26, 29, sk(2 - warm))


# The delta, and the whole of it. Note what is NOT in here: the light. Both
# halves are the same man in the same doorway at the same hour, so dimming
# `wary` a step -- which the first cut did -- bought a corpse rather than a
# mood. Every difference below is geometry.
MOOD = {
    # head, shoulders, lid, brow row, brow tilt (left, right), curl
    "kind": dict(hdy=0, sdy=0, lid=0, brow=20, tilt=(0, 0), curl=0, warm=1),
    "wary": dict(hdy=1, sdy=-2, lid=1, brow=21, tilt=(0, -1), curl=1, warm=1),
}


def portrait(mood):
    m = MOOD[mood]
    p = Plate(PW, PW, C["bg"])
    p_ground(p)
    p_coat(p, m["sdy"], collar_up=bool(m["lid"]))
    p_head(p, m["hdy"], m["warm"])
    p_brows(p, m["hdy"], m["brow"], m["tilt"])
    p_eyes(p, m["hdy"], m["lid"], m["warm"])
    p_mouth(p, m["hdy"], m["curl"], m["warm"])
    return p.img.resize((PW * PSCALE, PW * PSCALE), Image.NEAREST)


# --- output ---------------------------------------------------------------------

def spite_contact(sheet, scale=4):
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


def side_by_side(cels, other, grounds, zoom=3):
    """Spite beside the traveller on every ground, at the zoom the game runs at.
    Two characters in one world is the only test that matters for a second
    character: he has to be legible AND he has to not be the first one."""
    cw, ch = 96, 80
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
        for c, fa in enumerate(FACINGS):
            cell = ground_patch(tile, cw, ch).convert("RGBA")
            cell.alpha_composite(other[(fa, "neutral")], (12, ch - 48))
            cell.alpha_composite(cels[(fa, "neutral")], (52, ch - 48))
            out.alpha_composite(cell.resize((cw * zoom, ch * zoom), Image.NEAREST),
                                (pad_l + c * cw * zoom, pad_t + r * ch * zoom))
        d.text((3, pad_t + r * ch * zoom + 4), "%s\n%.0f" % (name[:11], gm),
               fill=C["muted"] + (255,), font=font)
    for c, fa in enumerate(FACINGS):
        d.text((pad_l + c * cw * zoom + 3, 3), "%s   you / him" % fa,
               fill=C["muted"] + (255,), font=font)
    return out


def portrait_contact(plates):
    """Both moods at 1:1 on the real panel colour -- which is the check that
    matters, because a face that only works at 5x is not a portrait -- and again
    at 4x with the two overlaid in difference, which is where you see that they
    are one person."""
    pad, gap, zoom = 20, 24, 4
    w = pad * 2 + max(112 * 2 + gap, (112 * zoom) * 2 + gap)
    h = pad * 3 + 112 + 112 * zoom + 30
    out = Image.new("RGBA", (w, h), tuple(C["bg"]) + (255,))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, mood in enumerate(MOODS):
        x = pad + i * (112 + gap)
        panel = Image.new("RGBA", (112 + 8, 112 + 8), tuple(C["panel_alt"]) + (255,))
        ImageDraw.Draw(panel).rectangle([0, 0, 119, 119], outline=C["accent"] + (255,))
        out.alpha_composite(panel, (x - 4, pad - 4))
        out.alpha_composite(plates[mood], (x, pad))
        d.text((x, pad + 116), "%s  1:1 (112px, as shipped)" % mood,
               fill=C["muted"] + (255,), font=font)
    y = pad * 2 + 112 + 24
    for i, mood in enumerate(MOODS):
        big = plates[mood].resize((112 * zoom, 112 * zoom), Image.NEAREST)
        out.alpha_composite(big, (pad + i * (112 * zoom + gap), y))
        d.text((pad + i * (112 * zoom + gap), y - 12), mood,
               fill=C["muted"] + (255,), font=font)
    return out


def write_spite(save, grounds, player_cels):
    cels = sp_build_all()
    sheet = Image.new("RGBA", (FW * len(FRAMES), FH * len(FACINGS)), CLEAR)
    for r, fa in enumerate(FACINGS):
        for c, po in enumerate(FRAMES):
            sheet.paste(cels[(fa, po)], (c * FW, r * FH))
    save(sheet, "spite.png")
    save(spite_contact(sheet), "_spite_x4.png")
    if grounds:
        save(side_by_side(cels, player_cels, grounds), "_spite_ground.png")
        ws = walk_strip(cels, grounds)
        if ws is not None:
            save(ws, "_spite_walk.png")

    os.makedirs(PORTRAITS, exist_ok=True)
    written = []
    plates = {}
    for mood in MOODS:
        plates[mood] = portrait(mood)
        name = "spite_%s.png" % mood
        plates[mood].save(os.path.join(PORTRAITS, name))
        written.append(name)
    pc = portrait_contact(plates)
    pc.save(os.path.join(PORTRAITS, "_spite_portraits.png"))
    written.append("_spite_portraits.png")

    print()
    print("spite.png  %dx%d  =  %d cols x %d rows of %dx%d   (player's layout)"
          % (sheet.width, sheet.height, len(FRAMES), len(FACINGS), FW, FH))
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
        ok = ok and stable and abs(centre - CX) <= 0.5 and x0 >= 1 and x1 <= FW - 2
        print("  %-6s bbox x %d..%d  centre %.1f   figure y %d..%d   sole row %s"
              % (fa, x0, x1, centre, min(b[0] for b in body),
                 max(b[1] for b in body),
                 "%d stable" % feet.pop() if stable else "MOVES %s" % sorted(feet)))
    st, rows = legibility(cels, grounds) if grounds else (
        sprite_stats(cels[("down", "neutral")]), [])
    pst = sprite_stats(player_cels[("down", "neutral")])
    print()
    print("  figure: %d opaque px   luma min %.0f / p50 %.0f / p90 %.0f / max %.0f"
          "   MEAN %.1f  (traveller %.1f)"
          % (st["n"], st["lo"], st["p50"], st["p90"], st["hi"], st["mean"],
             pst["mean"]))
    def _w(im):
        cols = [x for x in range(FW)
                if any(im.getpixel((x, y))[3] == 255 for y in range(FH))]
        return max(cols) - min(cols) + 1
    print("  shoulders: %d px across against the traveller's %d, and %d rows of"
          " figure against %d -- narrower, and hunched"
          % (_w(cels[("down", "neutral")]), _w(player_cels[("down", "neutral")]),
             44 - 2, 44 - 0))
    if rows:
        worst = max(rows, key=lambda r: r[5])
        print("  %-13s %6s %8s %7s %7s %7s"
              % ("ground", "luma", "delta", "lit", "dark", "lost"))
        for name, gm, dl, lit, dark, lost in rows:
            print("  %-13s %6.1f %+8.1f %6.1f%% %6.1f%% %6.1f%%"
                  % (name, gm, dl, lit * 100, dark * 100, lost * 100))
        print("  worst ground: %s -- %.0f%% light, %.0f%% dark, %.0f%% lost"
              % (worst[0], worst[3] * 100, worst[4] * 100, worst[5] * 100))
    print()
    print("  portraits %dx%d (%d logical x%d): %s"
          % (PW * PSCALE, PW * PSCALE, PW, PSCALE, ", ".join(written)))
    diff = sum(1 for a, b in zip(plates["kind"].getdata(), plates["wary"].getdata())
               if a != b) / float(PW * PSCALE * PW * PSCALE)
    print("  kind vs wary: %.1f%% of pixels differ -- one man, two faces" % (diff * 100))
    if not ok:
        raise SystemExit("SPITE CONTRACT FAILED")
    return cels

# --- the townsfolk: one body, five deltas ---------------------------------------
#
# Spite is a bespoke geometry table: eleven hand-written rows of skull, sixteen
# of coat, and a drawing function per garment. That is the right amount of work
# for the second character in the game and the wrong amount for the fifteenth.
# #77 wants a town. So everything below is the same figure Spite is -- same
# Frame, same north-west light, same alpha-derived rim, same baked contact
# shadow, same fixed sole -- with the geometry DERIVED FROM SCALARS instead of
# typed out, so a townsperson is a dictionary and not a file.
#
# What a townsperson is:
#
#   a body      crown row, skull size, neck, a width profile from shoulder to
#               hem, leg width and stance. Nine numbers.
#   a palette   four ramps mixed from data/themes/firstlight.json the same way
#               COOL / WARM / LEATHER / SKIN are: cloth, trim, skin, hair.
#   a crown     one of five: cap, mop, bun, bald, horseshoe -- or a hood.
#   a garment   one of six: coat, cloak, dress, apron, vest, layers.
#   props       zero or more small functions, called per facing.
#
# and everything else -- four facings, three columns, the walk contract, the
# mirror, the recentre, the check sheets -- is shared and cannot be got wrong
# per character because no character gets to write it.
#
# THE VALUE DISCIPLINE IS THE PART THAT DOES NOT SURVIVE BEING GUESSED. The
# ground runs 34 (grass_tall) to 72 (snow) and COOL is built with a deliberate
# hole between 43 and 90 for exactly that reason. `cloth5()` below reproduces
# that hole for any hue: three steps above 95, two below 42, nothing in between,
# and the dark steps are solved for a target luma rather than mixed by a
# fraction, because a fraction that brackets a pale linen apron puts a dark
# green cloak straight into the sand. Small parts -- hair, brows, a jar -- use
# `hue5()`, which is an even ramp, because a feature that is 5% of the figure
# can afford to sit in the hole and the rim is what holds the silhouette anyway.

# The luma the deep folds aim at, either side of the ground band.
FOLD_L, DEEP_L = 40.0, 27.0


def _toward_bg(base, target):
    """The mix of `base` toward the background whose luma is `target`.

    Solved rather than guessed. mix() is linear, so luma is linear in t, and
    one formula lands every hue on the same value. Mixing by a fixed fraction
    instead is what puts a dark cloak in the middle of the sand while a pale
    apron clears it.
    """
    la, lb = luma(base), luma(C["bg"])
    if la <= lb:
        return base
    t = (target - la) / (lb - la)
    return mix(base, C["bg"], max(0.0, min(1.0, t)))


def cloth5(base, up=0.34):
    """A garment ramp, bracketed either side of the ground.

    0 lit / 1 base / 2 mid all sit above 95 luma; 3 fold / 4 deep sit below 42.
    Nothing lands in 43..90 where sand, ice, dune and snow live. Index 2 is the
    turn: mixed toward `line` rather than toward the background, so a shaded
    garment goes grey-blue like everything else in this world instead of just
    going dark.
    """
    return [mix(base, C["text"], up), base, mix(base, C["line"], 0.30),
            _toward_bg(base, FOLD_L), _toward_bg(base, DEEP_L)]


def hue5(base, up=0.40):
    """An even ramp for the small parts -- hair, beards, props, glass. Five
    steps with no hole in them, because a feature this size is read against the
    figure it sits on, not against the ground."""
    return [mix(base, C["text"], up), base,
            mix(base, C["line"], 0.38), mix(base, C["bg"], 0.55),
            mix(base, C["bg"], 0.78)]


def skin5(base):
    """A face ramp: lit, base, shaded, in-the-collar, and the near-black that
    draws an eye and a mouth line.

    The base must sit BELOW the character's hair, always. make_sprites' first
    cut of Spite put skin at 160 against hair at 146 and the profile read as a
    beak on a grey skull; `town_report()` measures this for every townsperson
    rather than trusting that the ramps were chosen carefully.
    """
    return [mix(base, C["text"], 0.24), base,
            mix(base, C["bg"], 0.28), mix(base, C["bg"], 0.56),
            mix(C["bg"], BLACK, 0.30)]


# --- geometry from scalars ------------------------------------------------------

def _row(y, w):
    """A span `w` wide, centred on CX = 15.5. Widths are forced even, because an
    odd one is a figure half a pixel off its own tile and the mirror will not
    match it."""
    w = max(2, w + (w % 2))
    x0 = 16 - w // 2
    return (y, x0, x0 + w - 1)


def oval(top, rows, w):
    """A skull: full width through the middle, two rows of taper at each end."""
    out = []
    for i in range(rows):
        d = min(i, rows - 1 - i)
        out.append(_row(top + i, w - (4 if d == 0 else 2 if d == 1 else 0)))
    return out


def taper(y0, y1, keys):
    """Widths named at fractions of a run of rows, interpolated between.

    This is the whole of the body plan. `keys` is [(t, width)] and a character's
    silhouette -- broad and tapering, round and barrelled, narrow over a wide
    skirt -- is six numbers in that list rather than sixteen typed spans.
    """
    n = max(1, y1 - y0 + 1)
    out = []
    for i in range(n):
        t = 0.0 if n == 1 else i / float(n - 1)
        w = keys[-1][1]
        for j in range(len(keys) - 1):
            a, b = keys[j], keys[j + 1]
            if a[0] <= t <= b[0]:
                u = 0.0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
                w = a[1] + (b[1] - a[1]) * u
                break
        out.append(_row(y0 + i, int(round(w))))
    return out


def profile_keys(P, depth=1.0):
    """Shoulder, chest, elbow, waist, hem -- as a taper() key list.

    One shape for every townsperson, and the six widths in it are what makes a
    bartender a wedge and a shopkeeper a barrel. `depth` squeezes it for the
    side view: a person is narrower seen edge-on, and drawing the profile at
    the same width as the front is the single commonest way a turned sprite
    stops being the same person.
    """
    def d(w):
        return max(6, int(round(w * depth)))
    return [(0.00, d(P["sh_w"]) - 8), (0.10, d(P["sh_w"])),
            (0.34, d(P["chest_w"])), (0.40, d(P["elbow_w"])),
            (0.60, d(P["elbow_w"])), (0.68, d(P["waist_w"])),
            (1.00, d(P["hem_w"]))]


def geometry(P, side=False):
    """Every span table one townsperson needs, from the scalars in P."""
    top = P["crown"]
    hh, hw = P["head_h"], P["head_w"]
    head = oval(top, hh, hw + (2 if side else 0))
    if side:
        # The skull carries its mass BEHIND the ear, and the face is a notch cut
        # out of the front of it. Shifting the whole oval one pixel forward and
        # letting the hair overhang the neck is what sells a bare head in
        # profile -- Spite's file spends a paragraph on the same two pixels.
        head = [(y, x0 - 1, x1) for (y, x0, x1) in head]
    ny = top + hh
    neck = [_row(ny + i, P["neck_w"] + 2 * i) for i in range(P["neck_rows"])]
    sy = ny + P["neck_rows"]
    hy = P["hem_y"]
    body = taper(sy, hy, profile_keys(P, P["depth"] if side else 1.0))
    if side:
        # Lean the whole column forward or back. A stoop is not a shorter
        # person, it is a person whose head is in front of their feet, and that
        # only exists in the side view.
        lean = P.get("lean", 0)
        if lean:
            n = len(body)
            body = [(y, x0 + int(round(lean * (1.0 - i / float(max(1, n - 1))))),
                     x1 + int(round(lean * (1.0 - i / float(max(1, n - 1))))))
                    for i, (y, x0, x1) in enumerate(body)]
            head = [(y, x0 + lean, x1 + lean) for (y, x0, x1) in head]
            neck = [(y, x0 + lean, x1 + lean) for (y, x0, x1) in neck]
    hem = [_row(hy + 1, P["hem_w"] + P.get("hem_flare", 0))]
    return {"head": head, "neck": neck, "body": body, "hem": hem,
            "sy": sy, "ny": ny, "hy": hy, "top": top}


def body_keys(P, n):
    """Which ramp step each torso row sits at.

    Light at the top, dark at the bottom, and the step down happens at the
    waist rather than gradually: the value break is what stops a figure being
    one barrel of cloth from the collar to the hem. Spite's SP_BODY_F_K is this
    table written out by hand; this is the rule it was written from.
    """
    out = []
    for i in range(n):
        t = i / float(max(1, n - 1))
        out.append(0 if t < 0.16 else (1 if t < 0.66 else 2))
    return out


# --- painting -------------------------------------------------------------------

def paint_spans(f, spans, ramp, keys, dy=0, hi=2, sh=3):
    """sculpt(), for a figure that is not made of COOL.

    Identical light -- the leftmost `hi` pixels a step lighter, the rightmost
    `sh` a step darker, the last column two -- over an arbitrary ramp. This is
    the one function that makes the whole town look like it is standing in the
    same weather as the traveller, so nothing below is allowed to paint a
    garment any other way.
    """
    if isinstance(keys, int):
        keys = [keys] * len(spans)

    def R(i):
        return ramp[max(0, min(len(ramp) - 1, i))]

    for (y, x0, x1), k in zip(spans, keys):
        yy = y + dy
        f.row(yy, x0, x1, R(k))
        f.row(yy, x0, min(x1, x0 + hi - 1), R(k - 1))
        f.row(yy, max(x0, x1 - sh + 1), x1, R(k + 1))
        f.px(x1, yy, R(k + 2))


# --- the crown ------------------------------------------------------------------
#
# The first thing the eye reads on a 32px figure, so it is the axis the cast is
# separated on. Nobody in town shares one: the traveller has a hood, Spite a
# parted cap, and the six below are a leaf hood, a mop, a bun, a bald dome, a
# horseshoe and a shorn crop. If a seventh townsperson needs a crown that is
# already taken, they need a different one.

def hu_hair_front(f, P, dy, back):
    G, hr = P["_g"], P["hair"]
    head, hl, kind = G["head"], P["hairline"], P["crown_kind"]
    rows = head if back else head[:hl]
    if kind == "bald":
        # A bald head still has a head from behind. The first cut drew nothing
        # here and the bartender walked away with no skull at all -- an error
        # no rule catches and one glance at the `up` row does.
        for (y, x0, x1) in head:
            f.row(y + dy, x0, x1, P["skin"][1])
            f.row(y + dy, x1 - 2, x1, P["skin"][2])
        f.row(head[0][0] + dy, head[0][1], head[0][2], P["skin"][0])
        y, x0, x1 = head[-1]
        f.row(y + dy, x0, x1, P["skin"][3])
        rows = []
    if kind == "horseshoe":
        # Bare from the front and hair round the back and sides. Drawn as the
        # temples only, because a horseshoe closed across the top is a wig.
        for (y, x0, x1) in head[max(0, hl - 1):hl + 4]:
            f.row(y + dy, x0, x0 + 2, hr[2])
            f.px(x0, y + dy, hr[1])
            f.row(y + dy, x1 - 2, x1, hr[3])
        if back:
            for (y, x0, x1) in head[max(0, hl - 1):]:
                f.row(y + dy, x0, x1, hr[2])
                f.row(y + dy, x0, x0 + 1, hr[1])
                f.row(y + dy, x1 - 1, x1, hr[3])
        return
    for (y, x0, x1) in rows:
        f.row(y + dy, x0, x1, hr[2])
        f.row(y + dy, x0, x0 + 2, hr[1])
        f.px(x0, y + dy, hr[0])
        f.row(y + dy, x1 - 1, x1, hr[3])
    if back:
        # From behind there is no face and no fringe: a mass, a part and a nape.
        f.px(head[1][1] + 1, head[1][0] + dy, hr[1])
        y, x0, x1 = head[-2]
        f.row(y + dy, x0, x1, hr[3])
        y, x0, x1 = head[-1]
        f.row(y + dy, x0, x1, hr[4])
    else:
        # The fringe, parted, with the forehead bare between the halves. Two
        # dark bands across a 12px head read as goggles; one band with a gap in
        # it reads as hair. (make_sprites records the same bug in Spite.)
        y, x0, x1 = head[hl]
        mid = (x0 + x1) // 2
        f.row(y + dy, x0, mid - 1, hr[3])
        f.row(y + dy, mid + 3, x1, hr[4])
        if kind == "mop":
            # A mop is the same cap with its edges refusing to line up. Drawn
            # level all the way round it is a helmet.
            for i, (yy, a, b) in enumerate(head[hl:hl + 3]):
                f.row(yy + dy, a, a + (1 if i != 1 else 2), hr[3])
                f.row(yy + dy, b - (1 if i != 1 else 2), b, hr[4])
            f.px(mid + 1, head[hl][0] + dy, hr[3])
    if kind == "bun":
        # A knob, two rows proud of the crown and set BACK -- offset toward the
        # right, which is behind her in the front view. Drawn centred and
        # narrowing to a point, which is what the first cut did, it is a
        # wizard's hat: three rows of taper on top of a head is a cone whatever
        # you meant by it.
        cy = head[0][0] - 1 + dy
        f.row(cy, 15, 20, hr[2])
        f.row(cy - 1, 16, 19, hr[1])
        f.px(16, cy - 1, hr[0])
        f.px(20, cy, hr[3])
        f.px(14, cy + 1, hr[1])                                 # a strand come loose
        f.px(13, cy + 2, hr[2])


def hu_face_front(f, P, dy):
    """Brow, eyes, nose, mouth, jaw. Seven rows on an adult, six on a child --
    and the child's sit LOWER in the skull, which is the whole of why a short
    adult is not a child."""
    G, sk, hr = P["_g"], P["skin"], P["hair"]
    head, top = G["head"], G["top"]
    hl = P["hairline"] if P["crown_kind"] not in ("bald", "horseshoe") else 0
    for (y, x0, x1) in head[hl:]:
        f.row(y + dy, x0, x1, sk[1])
        f.row(y + dy, x1 - 2, x1, sk[2])
    if P["crown_kind"] in ("bald", "horseshoe"):
        f.row(head[0][0] + dy, head[0][1], head[0][2], sk[0])   # the dome's shine
        f.row(head[1][0] + dy, head[1][1] + 1, head[1][1] + 3, sk[0])
        for (y, x0, x1) in head[1:P["hairline"] + 1]:           # and its far side,
            f.row(y + dy, x1 - 1, x1, sk[3])                    # so it is a ball

    ey = top + P["eye_y"]
    sep = P["eye_sep"]
    lx, rx = 16 - sep // 2 - 2, 16 + sep // 2
    tilt = P.get("brow_tilt", (0, 0))
    # Whichever of the two dark values is actually dark. A white-haired woman
    # drawn with hair-coloured brows has no brows, and a face with no brows at
    # 32px has no expression -- it is the one feature that reads at this size.
    brow = hr[3] if luma(hr[3]) < luma(sk[3]) else sk[3]
    for i, x in enumerate((lx, rx)):
        f.row(ey - 1 + tilt[i] + dy, x, x + 1, brow)            # two pixels each.
        f.row(ey + dy, x, x + 1, sk[4])                         # a bar is goggles
    f.px(15, ey + 1 + dy, sk[0])                                # the nose: one lit
    f.px(16, ey + 1 + dy, sk[2])                                # pixel and its shade
    my = ey + P["mouth_dy"]
    f.row(my + dy, 15, 16, sk[3])
    f.px(17, my + dy, sk[3])                                    # a third at ONE
    f.row(my + 1 + dy, 14, 17, sk[2])                           # corner; a wider
                                                                # mouth is a moustache
    if P.get("specs"):
        # Spectacles as the BOTTOM of two lenses and a bridge, never a rim all
        # the way round: a closed ring on a 12px head is goggles, which is the
        # same failure the two-pixel brows above exist to avoid. Bright pixels
        # outboard of each eye -- the first cut -- read as a startled stare.
        f.row(ey + 1 + dy, lx, lx + 1, sk[3])
        f.row(ey + 1 + dy, rx, rx + 1, sk[3])
        f.px(lx + 2, ey + dy, sk[3])
        f.px(rx - 1, ey + dy, sk[3])
    if P.get("beard"):
        # It has to come UP the jaw to the ears, not sit under the mouth. A
        # beard drawn as three rows on the chin is a goatee, and on a bald head
        # a goatee leaves the skull a featureless brown block -- which is what
        # the bartender was until this ran to the temples.
        jaw = head[-1][0]
        for (y, x0, x1) in head:
            if y < ey:
                continue
            if y <= my:
                f.row(y + dy, x0, x0 + 1, hr[3])
                f.row(y + dy, x1 - 1, x1, hr[4])
                continue
            f.row(y + dy, x0, x1, hr[2])
            f.row(y + dy, x0, x0 + 1, hr[1])
            f.row(y + dy, x1 - 2, x1, hr[3])
        f.row(my + dy, 13, 18, hr[3])                           # the moustache line
        f.row(my + dy, 15, 16, sk[4])                           # with the mouth in it
        f.row(jaw + 1 + dy, 13, 18, hr[2])                      # and it hangs two
        f.row(jaw + 2 + dy, 14, 17, hr[3])                      # rows past the jaw
        f.px(18, jaw + 1 + dy, hr[4])


# --- the garment ----------------------------------------------------------------

def hu_garment_front(f, P, dy, back):
    """Six garments over one body, because a town where everybody is wearing a
    coat is a town of one person at six heights."""
    G = P["_g"]
    cl, tr = P["cloth"], P["trim"]
    sy, hy = G["sy"], G["hy"]
    body = G["body"]
    n = len(body)
    kind = P["garment"]

    def band(t0, t1):
        return [(i, r) for i, r in enumerate(body) if t0 <= i / float(n) < t1]

    def sleeves(ramp, base=2):
        """Arms, INSIDE the silhouette -- a panel a step off the garment down
        each side, and a cuff. The traveller swings his arms outside his own
        outline and that is his; everyone in town has their hands down."""
        for _i, (y, x0, x1) in band(0.16, 0.62):
            f.row(y + dy, x0, x0 + 2, ramp[base])
            f.px(x0, y + dy, ramp[base - 1])
            f.row(y + dy, x1 - 2, x1, ramp[base + 1])
        if P.get("sleeveless"):
            for _i, (y, x0, x1) in band(0.40, 0.62):
                f.row(y + dy, x0, x0 + 2, P["skin"][1])
                f.px(x0, y + dy, P["skin"][0])
                f.row(y + dy, x1 - 2, x1, P["skin"][2])
        # Hands, and they are SKIN. Drawn in the boot ramp -- which is what the
        # first cut did, on the reasoning that a cuff is leather -- every
        # townsperson ended a sleeve in a dark blob and the whole cast read as
        # though it were wearing mittens.
        hand = band(0.60, 0.74)
        for _i, (y, x0, x1) in hand:
            f.row(y + dy, x0, x0 + 2, P["skin"][1])
            f.px(x0, y + dy, P["skin"][0])
            f.row(y + dy, x1 - 2, x1, P["skin"][2])
        if hand:
            y = hand[-1][1][0]
            f.row(y + dy, hand[-1][1][1], hand[-1][1][1] + 2, P["skin"][2])

    if back:
        f.col(15, sy + 2 + dy, hy + dy, cl[3])
        f.col(16, sy + 2 + dy, hy + dy, cl[4])
        f.row(sy + 2 + dy, body[2][1] + 1, body[2][2] - 1, cl[0])   # the yoke seam
    elif kind in ("coat", "layers", "apron"):
        for y in range(sy + 2, hy + 1):
            f.row(y + dy, 15, 16, cl[4])                            # the opening
        for i in range(4):                                          # lapels, which
            f.px(14 - i, sy + 2 + i + dy, cl[0])                    # are their SEAMS
            f.px(17 + i, sy + 2 + i + dy, cl[3])                    # and not shading
    elif kind == "cloak":
        f.row(sy + 2 + dy, body[2][1] + 1, body[2][2] - 1, cl[0])
        f.px(15, sy + 3 + dy, tr[1])                                # the one clasp
        f.px(16, sy + 3 + dy, tr[2])
    elif kind == "dress":
        f.row(sy + 2 + dy, body[2][1] + 2, body[2][2] - 2, cl[0])
        f.col(15, sy + 3 + dy, sy + 6 + dy, cl[3])                  # a short placket
        f.col(16, sy + 3 + dy, sy + 6 + dy, cl[4])

    sleeves(tr if kind == "vest" else cl)

    if kind == "dress":
        # A gathered skirt at this size is three dark columns and the eye does
        # the rest. Shading it instead gives a bell, not cloth.
        for _i, (y, x0, x1) in band(0.60, 1.01):
            for x in (x0 + 3, (x0 + x1) // 2, x1 - 3):
                f.px(x, y + dy, cl[3])
    elif kind == "apron":
        # Chest to hem in the pale ramp, four narrower than the body, two
        # straps. It is the brightest garment anybody in town owns and that is
        # deliberate: it reads across a street, and he is the cleanest man in
        # the dirtiest room.
        for _i, (y, x0, x1) in band(0.34, 1.01):
            f.row(y + dy, x0 + 6, x1 - 6, tr[1])
            f.row(y + dy, x0 + 6, x0 + 7, tr[0])
            f.row(y + dy, x1 - 7, x1 - 6, tr[2])
        bib = band(0.34, 0.42)
        if bib:
            y, x0, x1 = bib[0][1]
            for k in range(4):                                  # the neck straps,
                f.px(x0 + 7, y - 1 - k + dy, tr[2])             # straight up. Drawn
                f.px(x1 - 7, y - 1 - k + dy, tr[2])             # as a diagonal they
                                                                # read as a scratch
        f.row(hy + dy, body[-1][1] + 6, body[-1][2] - 6, tr[3])
        # A seam down the middle and a tie across the waist. Without them the
        # apron is 200 luma of nothing at all, which at 32px is a bib.
        for _i, (y, x0, x1) in band(0.34, 1.01):
            f.px(16, y + dy, tr[2])
        tie = band(0.56, 0.64)
        for _i, (y, x0, x1) in tie:
            f.row(y + dy, x0 + 5, x1 - 5, tr[3])
        if tie:
            y, x0, x1 = tie[0][1]
            f.row(y + 1 + dy, x0 + 5, x0 + 7, tr[2])
    elif kind == "vest":
        # A waistcoat is a PANEL on a shirt: inset three each side so the pale
        # sleeve shows all the way down, open down the middle, buttoned, and
        # cut away at the bottom over the belly. Drawn as the whole torso -- the
        # first cut -- it is not a waistcoat, it is a yellow man.
        for _i, (y, x0, x1) in band(0.06, 0.86):
            f.row(y + dy, x0 + 3, x1 - 3, cl[1])
            f.row(y + dy, x0 + 3, x0 + 4, cl[0])
            f.row(y + dy, x1 - 4, x1 - 3, cl[2])
        if not back:
            for _i, (y, x0, x1) in band(0.06, 0.86):
                f.row(y + dy, 15, 16, cl[4])                        # the opening
            for i in range(4):                                      # lapels
                f.px(14 - i, sy + 2 + i + dy, cl[0])
                f.px(17 + i, sy + 2 + i + dy, cl[3])
            for i in range(3):                                      # three buttons
                f.px(14, sy + 6 + i * 3 + dy, tr[0])
        y0 = sy + int(n * 0.86)
        f.row(y0 + dy, body[min(int(n * 0.86), n - 1)][1] + 3,
              body[min(int(n * 0.86), n - 1)][2] - 3, cl[3])        # its bottom edge
    elif kind == "layers":
        # Patches. He is wearing everything he owns and some of it is somebody
        # else's, so he is the only figure in the game carrying more than two
        # hues -- which is what "he picks things up" looks like from a field away.
        # The inner coat: a narrower panel in a second ramp, so the outer one
        # has an edge. One 26-wide slab of tan with a cross seam on it is a
        # cardboard box, which is exactly what the first cut looked like.
        # Lapped to one side, because a man wearing four coats does not do them
        # up down the middle. The asymmetry is the only thing in the figure that
        # is not mirrored, and it is what stops the outline reading as a crate.
        for _i, (y, x0, x1) in band(0.10, 1.01):
            f.row(y + dy, x0 + 6, x1 - 9, tr[1])
            f.row(y + dy, x0 + 6, x0 + 7, tr[0])
            f.px(x1 - 9, y + dy, tr[3])
        pa = P["patch"]
        f.box(body[3][1] + 2, sy + 5 + dy, body[3][1] + 5, sy + 8 + dy, pa[0][2])
        f.row(sy + 5 + dy, body[3][1] + 2, body[3][1] + 5, pa[0][1])
        f.px(body[3][1] + 5, sy + 8 + dy, pa[0][3])
        f.box(body[-4][2] - 5, hy - 5 + dy, body[-4][2] - 2, hy - 2 + dy, pa[1][2])
        f.row(hy - 5 + dy, body[-4][2] - 5, body[-4][2] - 2, pa[1][1])
        f.px(body[-4][2] - 2, hy - 2 + dy, pa[1][3])
        f.row(hy - 7 + dy, body[-6][1] + 2, body[-6][2] - 2, cl[3])
        # A rope at the waist. He is wearing four coats and nothing holding them
        # shut is a box with a cross on it, which is what the first cut was.
        belt = band(0.54, 0.62)
        for _i, (y, x0, x1) in belt:
            f.row(y + dy, x0 + 1, x1 - 1, P["boots"][2])
            f.row(y + dy, x0 + 1, x0 + 2, P["boots"][1])
        if belt:
            y, x0, x1 = belt[0][1]
            f.px(15, y + dy, P["trim"][0])
            f.px(16, y + dy, P["trim"][2])
    if P.get("shawl"):
        # A triangle over the shoulders to a point at the sternum. Widened a
        # pixel a row it is a bib; this stays under a tenth of her.
        sh = P["shawl"]
        # A WRAP, not a triangle. The first cut ran a wide V down the chest and
        # she was wearing a bib in one saturated colour -- the same failure
        # Spite's scarf records. It sits ON the shoulders, follows the arms
        # down, and comes to a small point at the sternum.
        rows = P.get("shawl_rows", 5)
        for i in range(rows + 3):
            y = sy + 1 + i
            b = body[min(i, n - 1)]
            wing = max(2, 5 - i // 2)
            f.row(y + dy, b[1], b[1] + wing, sh[1])
            f.row(y + dy, b[1], b[1] + 1, sh[0])
            f.row(y + dy, b[2] - wing, b[2], sh[2])
            f.px(b[2], y + dy, sh[3])
        for i in range(rows):                                   # the small point
            y = sy + 1 + i
            r = _row(y, max(2, 8 - i * 2))
            f.row(y + dy, r[1], r[2], sh[1])
            f.px(r[1], y + dy, sh[0])
            f.px(r[2], y + dy, sh[2])


def hu_legs(f, P, pose, dy):
    """Legs and boots. Same contract as every other figure in the file: the
    planted sole ends on SOLE in every frame, and the lifted foot is drawn
    short rather than drawn somewhere else."""
    cl, bt = P["trouser"], P["boots"]
    w, gap = P["leg_w"], P["leg_gap"]
    lx = 15 - gap // 2 - w + 1
    rx = 16 + gap // 2
    lift = P["stride"]

    def leg(x0, up, out):
        top = P["hem_y"] + 1 + dy
        bot = SOLE - up
        if bot - 3 < top:
            top = max(top - 1, bot - 3)
        for y in range(top, bot - 2):
            f.row(y, x0, x0 + w - 1, cl[1])
            f.px(x0, y, cl[0])
            f.px(x0 + w - 1, y, cl[2])
        for y in range(bot - 2, bot + 1):
            f.row(y, x0 - out, x0 + w - 1, bt[1])
            f.px(x0 - out, y, bt[0])
        f.row(bot, x0 - out, x0 + w - 1, bt[2])

    if pose == "neutral":
        leg(lx, 0, 1)
        leg(rx, 0, 0)
    elif pose == "step_left":
        leg(lx - 1, 0, 1)
        leg(rx + 1, lift, 0)
    else:
        leg(lx - 1, lift, 1)
        leg(rx + 1, 0, 0)


# --- the side view --------------------------------------------------------------
#
# The traveller's profile is sold by a hood brim two pixels proud; Spite's by a
# nose that breaks the outline and a mass of hair the neck does not follow.
# Everyone here gets the same two devices, derived: the skull is drawn two wider
# and one forward, the face is a NOTCH CUT OUT OF THE FRONT of it rather than a
# lit wedge stuck on, and the near arm is a lit panel lying over the torso.
# All three are failures make_sprites already recorded -- a lit wedge on a pale
# dome is a bird's head, an arm drawn a step darker than the coat is a hole
# rather than a limb, and an arm against the back seam is a satchel.

def _front_edge(head, y):
    for (yy, x0, _x1) in head:
        if yy == y:
            return x0
    return head[len(head) // 2][1]


def hu_profile(P, pose):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    G = geometry(P, side=True)
    P["_g"] = G
    cl, tr, sk, hr, bt = P["cloth"], P["trim"], P["skin"], P["hair"], P["boots"]
    head, body = G["head"], G["body"]
    sy, hy, top = G["sy"], G["hy"], G["top"]
    kind, crown = P["garment"], P["crown_kind"]

    paint_spans(f, G["neck"], cl, 2, dy, hi=1, sh=1)
    paint_spans(f, body, P["body_ramp"], body_keys(P, len(body)), dy)
    paint_spans(f, G["hem"], P["body_ramp"], 3, dy)

    # --- the skull
    bare = crown in ("bald", "horseshoe")
    for (y, x0, x1) in head:
        if bare:
            f.row(y + dy, x0, x1, sk[1])
            f.row(y + dy, x1 - 2, x1, sk[2])
        else:
            f.row(y + dy, x0, x1, hr[2])
            f.row(y + dy, x1 - 2, x1, hr[3])
            f.px(x1, y + dy, hr[4])
    if bare:
        f.row(head[0][0] + dy, head[0][1] + 1, head[0][2] - 1, sk[0])
        if crown == "horseshoe":
            for (y, x0, x1) in head[P["hairline"]:]:
                f.row(y + dy, x1 - 3, x1, hr[2])
                f.px(x1, y + dy, hr[3])
    else:
        for (y, x0, x1) in head[:3]:
            f.px(x0, y + dy, hr[0])
            f.px(x0 + 1, y + dy, hr[1])
        if crown == "bun":
            y = head[len(head) // 3][0]
            f.box(head[0][2] - 1, y + dy, head[0][2] + 2, y + 4 + dy, hr[2])
            f.row(y + dy, head[0][2] - 1, head[0][2] + 2, hr[1])
            f.px(head[0][2] + 2, y + 4 + dy, hr[4])

    # --- the face, as a notch. Four pixels wide and no wider: the fix for the
    # beak is to stop the skin before it becomes the silhouette.
    ey = top + P["eye_y"]
    jaw = head[-1][0]
    for y in range(ey - 1, jaw + 1):
        x0 = _front_edge(head, y)
        f.row(y + dy, x0, x0 + 2, sk[1])
        f.px(x0 + 2, y + dy, sk[2])
    ex = _front_edge(head, ey)
    f.px(ex, ey + dy, sk[4])                               # the eye
    ny = ey + 1
    nx = _front_edge(head, ny)
    f.row(ny + dy, nx - 1, nx + 1, sk[1])                  # the nose, out one px
    f.px(nx - 1, ny + dy, sk[0])
    f.px(nx, ny + 1 + dy, sk[2])                           # its own shade under it
    my = ey + P["mouth_dy"]
    f.px(_front_edge(head, my), my + dy, sk[3])
    f.px(_front_edge(head, my) + 1, my + dy, sk[2])
    if not bare:
        f.px(_front_edge(head, ey - 1) + 2, ey - 1 + dy, hr[4])     # fringe over brow
    if P.get("specs"):
        f.px(ex - 1, ey + dy, tr[0])
        f.row(ey + dy, ex + 2, ex + 4, tr[2])              # the temple, to the ear
    if P.get("beard"):
        for y in range(my, jaw + 3):
            x0 = _front_edge(head, min(y, jaw))
            f.row(y + dy, x0 - 1, x0 + 3, hr[2])
            f.px(x0 - 1, y + dy, hr[1])
        f.px(_front_edge(head, my), my + dy, sk[4])

    # --- the garment, edge on
    f.col(body[len(body) // 2][2] - 1, sy + 2 + dy, hy + dy, cl[4])   # the back seam
    if kind == "apron":
        for i, (y, x0, x1) in enumerate(body):
            if i / float(len(body)) < 0.34:
                continue
            f.row(y + dy, x0, x0 + 3, tr[1])
            f.px(x0, y + dy, tr[0])
        for i in range(4):
            f.px(body[3][1] + 1 + i, sy + int(len(body) * 0.34) - 3 + i + dy, tr[2])
    elif kind == "vest":
        for i, (y, x0, x1) in enumerate(body):
            if i / float(len(body)) < 0.10:
                continue
            f.row(y + dy, x0, x0 + 2, tr[1])
            f.px(x0, y + dy, tr[0])
    elif kind == "dress":
        for i, (y, x0, x1) in enumerate(body):
            if i / float(len(body)) < 0.60:
                continue
            f.px(x0 + 2, y + dy, cl[3])
            f.px(x1 - 3, y + dy, cl[3])
    elif kind == "layers":
        pa = P["patch"]
        f.box(body[3][1] + 1, sy + 5 + dy, body[3][1] + 4, sy + 9 + dy, pa[0][1])
        f.row(sy + 5 + dy, body[3][1] + 1, body[3][1] + 4, pa[0][0])
    elif kind == "cloak":
        f.row(sy + 2 + dy, body[2][1], body[2][2] - 1, cl[0])
    if P.get("shawl"):
        sh = P["shawl"]
        for i in range(P.get("shawl_rows", 7)):
            y = sy + 1 + i
            b = body[min(i, len(body) - 1)]
            f.row(y + dy, b[1], b[2] - i, sh[1])
            f.row(y + dy, b[1], b[1] + 1, sh[0])
            f.px(b[2] - i, y + dy, sh[2])

    # --- the near arm: a LIT panel over the torso, toward the front, with one
    # dark seam behind it. A step darker than the coat and it is a hole.
    ax = {"neutral": 0, "step_left": -1, "step_right": 1}[pose] + body[len(body) // 2][1] + 1
    a0, a1 = sy + 3, sy + int(len(body) * 0.66)
    arm = cl if kind != "apron" else tr
    for i, y in enumerate(range(a0, a1)):
        # Two wide at the shoulder, four at the forearm. A constant-width panel
        # in the lit tone is a plank; the taper is the elbow, and the elbow is
        # the only thing that makes it an arm at this size.
        w = 2 if i < 2 else (3 if i < 4 else 4)
        f.row(y + dy, ax, ax + w - 1, arm[1])
        f.px(ax, y + dy, arm[0])
        f.px(ax + w, y + dy, cl[4])
    if P.get("sleeveless"):
        for y in range(a0 + 4, a1):
            f.row(y + dy, ax, ax + 3, sk[1])
            f.px(ax, y + dy, sk[0])
    f.row(a1 + dy, ax, ax + 3, sk[1])                      # the hand, in skin
    f.px(ax, a1 + dy, sk[0])
    f.row(a1 + 1 + dy, ax, ax + 2, sk[2])

    # --- legs, near and far, with a pixel of daylight between them at rest
    w, lift = P["leg_w"], P["stride"]
    mid = (body[-1][1] + body[-1][2]) // 2
    if pose == "neutral":
        near, far, nl, fl = mid - w + 1, mid + 2, 0, 0
    elif pose == "step_left":
        near, far, nl, fl = mid - w - 1, mid + 4, 0, lift - 1
    else:
        near, far, nl, fl = mid + 4, mid - w - 1, lift - 1, 0

    def leg(x0, up, shade, toe):
        top_y = hy + 1 + dy
        bot = SOLE - up
        for y in range(max(top_y, bot - 3 + 1) if bot - 3 < top_y else top_y, bot - 2):
            f.row(y, x0, x0 + w - 1, P["trouser"][1 + shade])
            f.px(x0, y, P["trouser"][0 + shade])
        for y in range(bot - 2, bot + 1):
            f.row(y, x0 - toe, x0 + w - 1, bt[1 + shade])
            f.px(x0 - toe, y, bt[0 + shade])
        f.row(bot, x0 - toe, x0 + w - 1, bt[2])

    leg(far, fl, 1, 0)
    leg(near, nl, 0, 2)
    return f


# --- props ----------------------------------------------------------------------
#
# The cheapest way to tell two townspeople apart at ZOOM 3, and the only one
# that works while they are walking away from you. A prop is a function of
# (frame, character, facing, pose, dy) and it is drawn last, over the body,
# before the rim -- so it is allowed to break the outline, which is the point.

def prop_stick(f, P, facing, pose, dy):
    """Held upright in the outer hand. The only vertical line in the cast, and
    it survives being a third of a phone tile because it is two pixels wide and
    twenty tall."""
    hu = hue5(mix(C["accent"], C["bg"], 0.55))
    G = P["_g"]
    # In profile it goes THREE pixels clear of the body, because the head is
    # drawn two proud of the shoulders and the nose one further: at the body's
    # own edge -- where the first cut put it -- a child holding a stick is a
    # child with a pole through his face.
    x = {"down": G["body"][4][2], "up": G["body"][4][1] - 1,
         "left": G["body"][4][1] - 4}[facing]
    y0 = G["top"] - 3 + dy
    y1 = SOLE - 1
    f.col(x, y0, y1, hu[2])
    f.col(x + 1, y0, y1, hu[4])
    f.px(x, y0, hu[1])
    f.px(x, y0 + 1, hu[0])


def prop_jar(f, P, facing, pose, dy):
    """A jar of pebbles, held at the belly in both hands. One pebble per hole
    they have watched somebody close, which makes it the town objective's
    progress bar, in the world, held by a child.

    It only exists on the facings that can see it, so the jar going away when
    she turns her back is the up/down tell."""
    if facing == "up":
        return
    G = P["_g"]
    gl = hue5(mix(C["accent_2"], C["text"], 0.20))
    y = G["sy"] + int(len(G["body"]) * 0.45) + dy
    x = 13 if facing == "down" else G["body"][len(G["body"]) // 2][1] + 1
    f.box(x, y, x + 5, y + 4, gl[2])
    f.row(y, x + 1, x + 4, gl[1])
    f.row(y + 1, x, x + 1, gl[0])
    f.row(y + 4, x + 1, x + 4, gl[3])
    f.px(x + 2, y + 2, P["cloth"][3])                 # two pebbles in the bottom
    f.px(x + 4, y + 3, P["cloth"][4])


def prop_bundle(f, P, facing, pose, dy):
    """Everything he owns, on his back. From behind it is most of him; from the
    front it is two humps clearing his shoulders, which is exactly how a laden
    person reads when they are walking towards you."""
    G = P["_g"]
    sk = hue5(mix(C["accent"], C["bg"], 0.30))
    b = G["body"][1]
    y = G["sy"] + dy
    if facing == "up":
        # TWO LOBES EITHER SIDE OF HIS HEAD, not one box over it. There is no
        # depth here: a bundle drawn across the shoulders and up to the crown
        # simply covers the head, and the first cut of this walked away with no
        # skull at all. The head shows down the middle and the load is beside it.
        top = G["head"][4][0] + dy
        for x in (b[1] + 1, b[2] - 5):
            f.box(x, top, x + 4, y + 6, sk[2])
            f.row(top, x + 1, x + 3, sk[1])
            f.row(top - 1, x + 1, x + 2, sk[0])
            f.row(y + 6, x + 1, x + 3, sk[3])
            f.row(top + 4, x, x + 4, sk[3])                  # a cord round each
    elif facing == "down":
        for x in (b[1] + 1, b[2] - 3):
            f.box(x, y - 3, x + 2, y, sk[2])
            f.row(y - 3, x, x + 2, sk[1])
    else:
        # Side on it rides the shoulders, one row proud of them and no higher:
        # taken up to the crown it is a second head, which is what it looked
        # like beside the ear the first time.
        top = y - 1
        f.box(b[2] - 2, top, b[2] + 2, y + 9, sk[2])
        f.row(top, b[2] - 1, b[2] + 1, sk[1])
        f.px(b[2] - 1, top, sk[0])
        f.row(y + 9, b[2] - 1, b[2] + 1, sk[3])
        f.row(y + 4, b[2] - 2, b[2] + 2, sk[3])


def prop_towel(f, P, facing, pose, dy):
    """The cloth over one shoulder. Two pixels wide, eight long, in the apron's
    own ramp -- so the brightest thing on him is repeated once, small, and the
    figure has a rhythm instead of one bright slab."""
    G = P["_g"]
    tr = P["trim"]
    b = G["body"][2]
    x = b[1] + 2 if facing != "left" else b[2] - 4
    y = G["sy"] + 1 + dy
    for i in range(9):
        f.row(y + i, x, x + 1, tr[1])
        f.px(x, y + i, tr[0])
    f.row(y + 9, x, x + 1, tr[3])


PROPS = {"stick": prop_stick, "jar": prop_jar,
         "bundle": prop_bundle, "towel": prop_towel}


# --- assembly -------------------------------------------------------------------

def hu_frontal(P, pose, back):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    G = geometry(P, side=False)
    P["_g"] = G
    paint_spans(f, G["neck"], P["cloth"], 2, dy, hi=1, sh=1)
    paint_spans(f, G["body"], P["body_ramp"], body_keys(P, len(G["body"])), dy)
    paint_spans(f, G["hem"], P["body_ramp"], 3, dy)
    hu_hair_front(f, P, dy, back)
    if not back:
        hu_face_front(f, P, dy)
    hu_garment_front(f, P, dy, back)
    # The garment swings a column against the stride, as the traveller's cloak
    # and Spite's coat both do. Without it the legs walk and the body does not.
    b = G["body"][-1]
    if pose == "step_left":
        f.col(b[2], G["hy"] - 3 + dy, G["hy"] + dy, P["cloth"][4])
    elif pose == "step_right":
        f.col(b[1], G["hy"] - 3 + dy, G["hy"] + dy, P["cloth"][3])
    hu_legs(f, P, pose, dy)
    return f


def hu_build(P, facing, pose):
    if facing == "down":
        f = hu_frontal(P, pose, False)
    elif facing == "up":
        f = hu_frontal(P, pose, True)
    else:
        f = hu_profile(P, pose)
    dy = 0 if pose == "neutral" else 1
    for name in P.get("props", []):
        PROPS[name](f, P, facing if facing != "right" else "left", pose, dy)
    return f.img


def hu_build_all(P):
    """The sheet contract, once, for everybody: four facings, three columns,
    column 0 neutral, `right` a mirror of `left`, one recentre offset for all
    three profile poses so the figure does not twitch when it turns or steps."""
    cels = {}
    for fa in ("down", "up"):
        for po in FRAMES:
            cels[(fa, po)] = hu_build(P, fa, po)
    prof = recentre([hu_build(P, "left", po) for po in FRAMES])
    for po, im in zip(FRAMES, prof):
        cels[("left", po)] = im
    for key in list(cels):
        contact_shadow(rim(cels[key]), rx=P["shadow"], ry=P.get("shadow_y", 4.0))
    lb = [cels[("left", po)].getbbox() for po in FRAMES]
    lc = (min(b[0] for b in lb) + max(b[2] for b in lb) - 1) / 2.0
    for po in FRAMES:
        cels[("right", po)] = cels[("left", po)].transpose(Image.FLIP_LEFT_RIGHT)
    rb = [cels[("right", po)].getbbox() for po in FRAMES]
    rc = (min(b[0] for b in rb) + max(b[2] for b in rb) - 1) / 2.0
    shift = int(round(lc - rc))
    if shift:
        for po in FRAMES:
            n = Image.new("RGBA", (FW, FH), CLEAR)
            n.paste(cels[("right", po)], (shift, 0))
            cels[("right", po)] = n
    return cels


def prop_crown(f, P, facing, pose, dy):
    """A crown of leaves, cut and stitched by somebody who is eight. Three
    points, uneven, because an even one is a hat.

    It is the only jagged silhouette in the cast and it is the whole reason
    Pell reads as the captain from across the street rather than as the taller
    of two children."""
    G = P["_g"]
    lf = P["cloth"]
    head = G["head"]
    y = head[0][0] + dy
    x0, x1 = head[1][1], head[1][2]
    f.row(y, x0, x1, lf[1])
    f.row(y, x0, x0 + 1, lf[0])
    f.px(x1, y, lf[2])
    for i, (x, h) in enumerate(((x0 + 1, 2), ((x0 + x1) // 2, 3), (x1 - 2, 1))):
        for k in range(h):
            f.px(x, y - 1 - k, lf[1] if i != 2 else lf[2])
            f.px(x + 1, y - 1 - k, lf[2] if i != 2 else lf[3])


PROPS["crown"] = prop_crown


# --- the cast -------------------------------------------------------------------
#
# Every townsperson is TOWNSPERSON plus a handful of overrides. That is the
# whole claim of this section: Spite is 330 lines of bespoke geometry and these
# six are twenty lines each, and they are the same figure standing in the same
# light.
#
# The two axes they are separated on are the two that survive ZOOM 3: MASS
# (crown row and shoulder width -- a child beside a bartender is legible before
# anything else resolves) and CROWN (six shapes, none shared with the traveller's
# hood or Spite's parted cap). Colour is third and it is deliberately third,
# because on a phone at dusk it is the first thing to go.

TOWNSPERSON = dict(
    crown=3, head_w=12, head_h=11, hairline=4,
    neck_w=6, neck_rows=3,
    sh_w=18, chest_w=18, elbow_w=20, waist_w=17, hem_w=16, hem_y=32,
    eye_y=6, eye_sep=4, mouth_dy=3, brow_tilt=(0, 0),
    leg_w=4, leg_gap=2, stride=4,
    depth=0.86, lean=0, hem_flare=0,
    crown_kind="cap", garment="coat",
    shadow=9.5, shadow_y=4.0, props=(),
    boots=None, trim=None, trouser=None, body_ramp=None,
)

# Skins. Three of them, because a town of one complexion is a decision nobody
# made on purpose. All three sit BELOW their wearer's hair in value -- the beak
# on a grey skull is what happens when they do not, and town_report() measures
# it rather than trusting this comment.
SKIN_PALE = skin5(mix(mix(_SKIN, C["muted"], 0.30), C["bg"], 0.16))
SKIN_ASH = skin5(mix(mix(_SKIN, C["muted"], 0.45), C["bg"], 0.34))
SKIN_WARM = skin5(mix(mix(C["accent"], C["danger"], 0.40), C["bg"], 0.34))
SKIN_DEEP = skin5(mix(mix(C["accent"], C["danger"], 0.30), C["bg"], 0.60))

HAIR_STRAW = hue5(mix(C["warn"], C["muted"], 0.40))
HAIR_DARK = hue5(mix(C["accent"], C["bg"], 0.55))
HAIR_WHITE = hue5(mix(C["text"], C["muted"], 0.55))
HAIR_IRON = hue5(mix(C["muted"], C["bg"], 0.28))

LEAF = cloth5(mix(C["good"], C["line"], 0.22))       # the fort's own green
MOSS = cloth5(mix(C["good"], C["bg"], 0.34))
LILAC = cloth5(mix(mix(C["accent_2"], C["danger"], 0.35), C["line"], 0.30))
SHAWL = cloth5(mix(C["accent_2"], C["line"], 0.20))
SACK = cloth5(mix(C["accent"], C["bg"], 0.30))
RUST = cloth5(mix(C["danger"], C["line"], 0.30))
LINEN = cloth5(mix(C["text"], C["muted"], 0.34))
BRASS = cloth5(mix(C["warn"], C["line"], 0.32))
# The bartender is in the traveller's own cloth: COOL[3], the cloak's value, run
# through the same five-step bracket. He is the one townsperson who looks like
# he is from here, which is the joke -- he is the only one who is not.
SLATE = cloth5(mix(C["line"], C["muted"], 0.80))
SLATE_DK = cloth5(mix(mix(C["line"], C["muted"], 0.55), C["bg"], 0.15))
DRESS = cloth5(mix(mix(C["accent_2"], C["line"], 0.50), C["bg"], 0.06))
ROSE = cloth5(mix(mix(C["danger"], C["muted"], 0.25), C["line"], 0.18))
STOCKING = cloth5(mix(C["line"], C["bg"], 0.28))


def townsperson(**delta):
    P = dict(TOWNSPERSON)
    P.update(delta)
    P.setdefault("skin", SKIN_PALE)
    P.setdefault("hair", HAIR_DARK)
    if P["boots"] is None:
        P["boots"] = LEATHER
    if P["trim"] is None:
        P["trim"] = P["cloth"]
    if P["body_ramp"] is None:
        # A waistcoat is a panel ON a shirt, so the torso underneath it is the
        # shirt's ramp and not the waistcoat's. Painting the body in the
        # garment ramp and adding sleeves on top -- the first cut -- gave the
        # shopkeeper a yellow chest with two thin pale strips, which reads as
        # a yellow man rather than a man in a waistcoat.
        P["body_ramp"] = P["trim"] if P["garment"] == "vest" else P["cloth"]
    if P["trouser"] is None:
        # Trousers are NOT the coat. The first cut let them default to the
        # garment ramp and the shopkeeper came out a single yellow column from
        # collar to boot -- at 32 px a figure needs a value break at the waist
        # and a hue break at the hip or it is a bollard in a hat.
        P["trouser"] = SLATE_DK
    return P


TOWN = {}

# --- Pell. Eleven, in charge, and correct.
# Short and top-heavy: a child is not a small adult, it is a big head on a
# short body, so the skull stays 12 wide on 14-wide shoulders where an adult
# runs 12 on 18. Crown at y10 against the traveller's y1 -- 34 rows of figure
# against his 44, and that difference is readable before anything else is.
TOWN["kid_pell"] = townsperson(
    crown=11, head_h=10, head_w=12, hairline=4, eye_y=6, mouth_dy=2,
    neck_w=5, neck_rows=2,
    sh_w=14, chest_w=14, elbow_w=15, waist_w=14, hem_w=15, hem_y=36,
    leg_w=4, leg_gap=2, stride=3,
    crown_kind="cap", garment="cloak",
    cloth=LEAF, trim=cloth5(mix(C["accent"], C["bg"], 0.30)),
    trouser=SLATE_DK, hair=HAIR_DARK, skin=SKIN_WARM,
    props=("crown", "stick"), shadow=7.5, shadow_y=3.4,
)

# --- Bird. Younger, on the wall, keeping the count. Shorter again, a mop
# instead of a crown, dark hair against Pell's straw, and the jar -- which is
# the only pale object either of them carries, held where your eye lands.
TOWN["kid_bird"] = townsperson(
    crown=13, head_h=10, head_w=12, hairline=4, eye_y=6, mouth_dy=2,
    neck_w=5, neck_rows=2,
    sh_w=13, chest_w=13, elbow_w=14, waist_w=13, hem_w=14, hem_y=37,
    leg_w=4, leg_gap=2, stride=3,
    crown_kind="mop", garment="cloak",
    cloth=MOSS, trim=LEAF, trouser=SLATE_DK,
    hair=HAIR_STRAW, skin=SKIN_DEEP,
    props=("jar",), shadow=7.0, shadow_y=3.2,
)

# --- Mrs Ollard. The only triangle in the cast: a 24-wide hem under 16-wide
# shoulders, so she is a skirt with a person on top of it. Stooped -- `lean`
# puts her head in front of her feet in the side view, which is what a stoop
# actually is; drawing her shorter would only have made her a child.
# Her bun is the brightest crown in the game and it is meant to be: you are
# supposed to be able to spot her at a window from the other end of the street.
TOWN["busybody"] = townsperson(
    crown=9, head_h=10, head_w=12, hairline=4, eye_y=6,
    neck_w=6, neck_rows=3,
    sh_w=16, chest_w=16, elbow_w=17, waist_w=17, hem_w=24, hem_y=38,
    leg_w=4, leg_gap=2, stride=2, lean=2, depth=0.80,
    crown_kind="bun", garment="dress",
    cloth=DRESS, trim=ROSE, shawl=ROSE, shawl_rows=5,
    trouser=STOCKING, hair=HAIR_WHITE, skin=SKIN_ASH,
    shadow=12.0, shadow_y=4.2,
)

# --- Bram Hollis. The widest silhouette anyone has: 26 across the shoulders
# and 24 at the hem, a barrel rather than a wedge, and a bundle that clears the
# crown from behind. He is the only figure carrying four hues, which is the
# whole of "he picks things up" said in the outline.
TOWN["bram"] = townsperson(
    crown=3, head_h=11, head_w=14, hairline=4, eye_y=6,
    neck_w=7, neck_rows=2,
    sh_w=26, chest_w=26, elbow_w=26, waist_w=25, hem_w=24, hem_y=33,
    leg_w=5, leg_gap=2, stride=4, depth=0.80,
    crown_kind="mop", garment="layers", beard=True,
    cloth=SACK, trim=MOSS, patch=(RUST, SLATE), trouser=SLATE_DK,
    hair=HAIR_DARK, skin=SKIN_WARM,
    props=("bundle",), shadow=12.5, shadow_y=4.4,
)

# --- Tobin. A wedge: 26 across the shoulders down to 18 at the hem, where Bram
# goes 26 to 24. Bald, so his crown is the one smooth dome in a cast of hoods,
# caps, mops, buns and crowns -- and the apron is the brightest garment in the
# game at 203 luma, against a world that tops out at 72.
TOWN["tobin"] = townsperson(
    crown=2, head_h=11, head_w=13, hairline=3, eye_y=6,
    neck_w=8, neck_rows=2,
    sh_w=26, chest_w=25, elbow_w=26, waist_w=21, hem_w=18, hem_y=32,
    leg_w=5, leg_gap=2, stride=4, depth=0.90,
    crown_kind="bald", garment="apron", beard=True, sleeveless=True,
    cloth=SLATE, trim=LINEN, trouser=SLATE_DK, hair=HAIR_DARK, skin=SKIN_WARM,
    props=("towel",), shadow=12.0, shadow_y=4.4,
)

# --- Ansel Cobb. The only figure whose waist is wider than his chest, which is
# a belly and reads as one; the only horseshoe; and the only spectacles, drawn
# as two pixels of glint and a bridge because a rim all the way round a 12px
# head is goggles -- see hu_face_front.
TOWN["cobb"] = townsperson(
    crown=4, head_h=10, head_w=12, hairline=4, eye_y=6,
    neck_w=7, neck_rows=3,
    sh_w=19, chest_w=20, elbow_w=21, waist_w=23, hem_w=21, hem_y=31,
    leg_w=4, leg_gap=2, stride=4, depth=0.94,
    crown_kind="horseshoe", garment="vest", specs=True,
    cloth=BRASS, trim=LINEN, trouser=SLATE_DK, hair=HAIR_IRON, skin=SKIN_PALE,
    shadow=10.5, shadow_y=4.2,
)


# --- output and the check sheets ------------------------------------------------
#
# The sheets are the deliverable of the drawing step and the PNGs are just
# output. Three of them, and each catches a different class of error:
#
#   _<id>_x4.png     the cell grid ruled over the sheet -- the layout contract,
#                    visible. Catches a figure leaning out of its own box.
#   _town_lineup.png every townsperson beside the traveller and Spite, at 1:1
#                    AND at ZOOM 3, on the darkest, the middlest and the
#                    brightest ground. The 1:1 half is the one that matters.
#                    Catches two characters who turn out to be one character.
#   _town_ground.png all six on all eighteen walkable materials. Catches the
#                    one who dissolves into the sand.

def town_sheet(cels):
    sheet = Image.new("RGBA", (FW * len(FRAMES), FH * len(FACINGS)), CLEAR)
    for r, fa in enumerate(FACINGS):
        for c, po in enumerate(FRAMES):
            sheet.paste(cels[(fa, po)], (c * FW, r * FH))
    return sheet


def town_lineup(cast, grounds, zoom=3):
    """Everybody, side by side, on three grounds, small and then large.

    Side by side is the only test that matters once the cast is bigger than
    two: each of them has to be legible AND has to not be one of the others.
    """
    order = [k for k, _ in cast]
    cw, ch = 34, 52
    picks = [grounds[0], grounds[len(grounds) // 2], grounds[-1]] if grounds else []
    pad_l, pad_t = 52, 16
    n = len(order)
    w = pad_l + n * cw * zoom + 8
    h = pad_t + len(picks) * ch * zoom + (ch + 22) * 2 + 16
    out = Image.new("RGBA", (w, h), mix(C["bg"], BLACK, 0.35) + (255,))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    y = pad_t
    for name, _i, gm, tile in picks:
        strip = Image.new("RGB", (n * cw, ch))
        for c, key in enumerate(order):
            strip.paste(ground_patch(tile, cw, ch), (c * cw, 0))
        strip = strip.convert("RGBA")
        for c, key in enumerate(order):
            strip.alpha_composite(dict(cast)[key][("down", "neutral")],
                                  (c * cw + 1, ch - 48))
        out.alpha_composite(strip.resize((n * cw * zoom, ch * zoom), Image.NEAREST),
                            (pad_l, y))
        d.text((3, y + 4), "%s\n%.0f" % (name[:11], gm), fill=C["muted"] + (255,),
               font=font)
        y += ch * zoom
    for label, pick in (("1:1, as the game draws them", picks[len(picks) // 2] if picks else None),):
        if pick is None:
            break
        y += 10
        strip = Image.new("RGB", (n * cw, ch))
        for c in range(n):
            strip.paste(ground_patch(pick[3], cw, ch), (c * cw, 0))
        strip = strip.convert("RGBA")
        for c, key in enumerate(order):
            strip.alpha_composite(dict(cast)[key][("down", "neutral")], (c * cw + 1, ch - 48))
        out.alpha_composite(strip, (pad_l, y))
        d.text((3, y + 4), label[:12], fill=C["muted"] + (255,), font=font)
        y += ch + 6
        # ...and their backs, because half of what you see of an NPC is the
        # facing they are walking away in.
        strip = Image.new("RGB", (n * cw, ch))
        for c in range(n):
            strip.paste(ground_patch(pick[3], cw, ch), (c * cw, 0))
        strip = strip.convert("RGBA")
        for c, key in enumerate(order):
            strip.alpha_composite(dict(cast)[key][("up", "neutral")], (c * cw + 1, ch - 48))
        out.alpha_composite(strip, (pad_l, y))
        d.text((3, y + 4), "1:1 backs", fill=C["muted"] + (255,), font=font)
    for c, key in enumerate(order):
        d.text((pad_l + c * cw * zoom + 2, 3), key[:9], fill=C["muted"] + (255,), font=font)
    return out


def town_ground(cast, grounds, zoom=2):
    order = [k for k, _ in cast]
    cw, ch = 34, 52
    pad_l, pad_t = 52, 14
    n = len(order)
    out = Image.new("RGBA", (pad_l + n * cw * zoom + 8, pad_t + len(grounds) * ch * zoom + 8),
                    mix(C["bg"], BLACK, 0.35) + (255,))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for r, (name, _i, gm, tile) in enumerate(grounds):
        strip = Image.new("RGB", (n * cw, ch))
        for c in range(n):
            strip.paste(ground_patch(tile, cw, ch), (c * cw, 0))
        strip = strip.convert("RGBA")
        for c, key in enumerate(order):
            strip.alpha_composite(dict(cast)[key][("left", "neutral")], (c * cw + 1, ch - 48))
        out.alpha_composite(strip.resize((n * cw * zoom, ch * zoom), Image.NEAREST),
                            (pad_l, pad_t + r * ch * zoom))
        d.text((3, pad_t + r * ch * zoom + 4), "%s\n%.0f" % (name[:11], gm),
               fill=C["muted"] + (255,), font=font)
    for c, key in enumerate(order):
        d.text((pad_l + c * cw * zoom + 2, 3), key[:9], fill=C["muted"] + (255,), font=font)
    return out


def town_report(key, P, cels, grounds, player_cels):
    """Measured, not asserted -- the same four numbers `write_spite` prints,
    per townsperson, plus the one Spite's file learned the hard way: the face
    must not outrank the hair."""
    im = cels[("down", "neutral")]
    cols = [x for x in range(FW) if any(im.getpixel((x, y))[3] == 255 for y in range(FH))]
    rowsy = [y for y in range(FH) if any(im.getpixel((x, y))[3] == 255 for x in range(FW))]
    st = sprite_stats(im)
    worst = None
    if grounds:
        px = [luma(p) for p in im.getdata() if p[3] == 255]
        nn = float(len(px))
        for name, _i, gm, _t in grounds:
            lit = sum(1 for v in px if v - gm >= 15) / nn
            dark = sum(1 for v in px if gm - v >= 15) / nn
            lost = sum(1 for v in px if abs(v - gm) < 10) / nn
            if worst is None or lost > worst[3]:
                worst = (name, lit, dark, lost)
    ok = True
    feet = set()
    centres = []
    for fa in FACINGS:
        boxes = [cels[(fa, po)].getbbox() for po in FRAMES]
        for po in FRAMES:
            c = cels[(fa, po)]
            ys = [y for y in range(FH) if any(c.getpixel((x, y))[3] == 255 for x in range(FW))]
            feet.add(max(ys))
        x0, x1 = min(b[0] for b in boxes), max(b[2] for b in boxes) - 1
        centres.append((x0 + x1) / 2.0)
        ok = ok and x0 >= 1 and x1 <= FW - 2 and abs((x0 + x1) / 2.0 - CX) <= 0.5
    ok = ok and len(feet) == 1
    # The beak check, generalised. Spite's first cut put skin at 160 against
    # hair at 146 and the profile read as a bird's head; the rule that failure
    # teaches is not "skin darker than hair" -- a dark-haired man has a lighter
    # face and always will -- it is THE FACE MUST NOT BE THE BRIGHTEST THING ON
    # THE FIGURE. Measured off the rendered cel rather than off the ramps, so a
    # lit dome or a specular on a nose is caught too.
    face, hairv = luma(P["skin"][1]), luma(P["hair"][2])
    skins = {tuple(c) for c in P["skin"]}
    hottest = max(luma(q) for q in im.getdata() if q[3] == 255)
    skin_hi = max([luma(q) for q in im.getdata()
                   if q[3] == 255 and q[:3] in skins] or [0.0])
    ok = ok and skin_hi < hottest
    print("  %-10s %3d w  %2d rows  %4d px  luma %5.1f  face %3.0f/hair %3.0f  "
          "worst %-11s lit %2.0f%% dark %2.0f%% lost %2.0f%%  %s"
          % (key, max(cols) - min(cols) + 1, max(rowsy) - min(rowsy) + 1, st["n"],
             st["mean"], face, hairv,
             worst[0] if worst else "-", (worst[1] if worst else 0) * 100,
             (worst[2] if worst else 0) * 100, (worst[3] if worst else 0) * 100,
             "ok" if ok else "FAIL sole=%s centres=%s skin_hi=%.0f/%.0f"
             % (sorted(feet), centres, skin_hi, hottest)))
    return ok


def write_town(save, grounds, player_cels, spite_cels):
    built = []
    ok = True
    for key in TOWN:
        cels = hu_build_all(TOWN[key])
        built.append((key, cels))
        save(town_sheet(cels), "%s.png" % key)
        save(spite_contact(town_sheet(cels)), "_%s_x4.png" % key)
    print()
    print("the townsfolk -- one base (TOWNSPERSON) + %d deltas" % len(TOWN))
    for key, cels in built:
        ok = town_report(key, TOWN[key], cels, grounds, player_cels) and ok
    cast = [("you", player_cels), ("spite", spite_cels)] + built
    if grounds:
        save(town_lineup(cast, grounds), "_town_lineup.png")
        save(town_ground(built, grounds), "_town_ground.png")
    write_town_portraits()
    if not ok:
        raise SystemExit("TOWNSFOLK CONTRACT FAILED")


# --- the townsfolk portraits ------------------------------------------------------
#
# Two of the six get a face: the children, because they are the gate and the
# change of heart is the first person in the game the player talks round, and
# Mrs Ollard, because she is the most fully written character in Kevin's notes
# and half of what she is only exists in an expression. The other four get a
# sprite and DialogueScreen's lettered plate, which is a deliberate choice and
# not a shortfall -- four more faces at this quality is another pass, and a
# mediocre face is worse than an initial in a box.
#
# Everything here is Spite's method one level up. `pp_face()` is ONE head and
# the moods are a delta dictionary over it, so `posted` and `stood_down` cannot
# be two different children, in exactly the way `kind` and `wary` cannot be two
# different men. What is new is two techniques his two faces did not need:
#
#   THE GAZE. Moving a pupil one pixel inside an unchanged eye is the cheapest
#   expression in the whole toolkit and the only one that draws "not here".
#   Mrs Ollard's `adrift` is a gaze delta and almost nothing else -- the eyes
#   are the same eyes, open the same amount, looking a pixel past you.
#
#   THE PROP AS THE MOOD. The children's `posted` has the stick across the
#   bottom of the plate and `stood_down` does not. The gate is a literal object
#   in the picture and taking it away is the whole beat, which means the mood
#   reads at 1:1 before either face resolves. Where a mood is about a decision
#   rather than a feeling, move the object.
#
# Both faces are 56 logical pixels doubled to 112, for the reason Spite's are:
# a native 112 portrait is a finer grain than anything else on screen and reads
# as a different game.

PP_MOODS = {}                        # portrait stem -> [mood ids], for the report


def pp_oval(cx, top, rows, w):
    """A skull at portrait scale: three rows of taper at each end rather than
    the sprite's two, because at twenty pixels across a two-row taper is a
    tin."""
    out = []
    for i in range(rows):
        d = min(i, rows - 1 - i)
        ww = w - (6 if d == 0 else 3 if d == 1 else 1 if d == 2 else 0)
        x0 = int(round(cx - ww / 2.0))
        out.append((top + i, x0, x0 + ww - 1))
    return out


def pp_face(p, F, m):
    """One head: skull, hair, nose, brows, eyes, mouth. Identical between the
    moods of a character by construction -- every difference is in `m`."""
    sk, hr = F["skin"], F["hair"]
    dy = m.get("hdy", 0) + F.get("dy", 0)
    head = pp_oval(F["cx"], F["top"], F["rows"], F["w"])
    hl = F["hairline"]
    cx = F["cx"]

    for (y, x0, x1) in head[hl:]:                     # the flat of the face
        p.row(y + dy, x0, x1, sk[1])
        p.row(y + dy, x0, x0 + 1, sk[0])              # lit from the north-west
        p.row(y + dy, x1 - 2, x1, sk[2])
        p.px(x1, y + dy, sk[3])
    for (y, x0, x1) in head[:hl]:                     # the cap of hair
        p.row(y + dy, x0, x1, hr[2])
        p.row(y + dy, x0, x0 + 2, hr[1])
        p.row(y + dy, x0, x0 + 1, hr[0])
        p.row(y + dy, x1 - 3, x1, hr[3])
        p.px(x1, y + dy, hr[4])
    for (y, x0, x1) in head[hl:hl + 5]:               # temples, past the eye
        p.row(y + dy, x0, x0 + 1, hr[3])
        p.row(y + dy, x1 - 1, x1, hr[4])
    # The fringe: an uneven edge, cut by nobody. A straight one is a helmet.
    for i, x in enumerate(range(head[hl][1] + 1, head[hl][2], 2)):
        for k in range((i * 5 + F["top"]) % 3 + 1):
            p.px(x, F["top"] + hl + k + dy, hr[3] if x < cx else hr[4])

    ey = F["top"] + F["eye_y"]
    sep = F["eye_sep"]
    lx, rx = int(cx - sep / 2.0 - 3), int(cx + sep / 2.0)
    gaze = m.get("gaze", 0)

    # The nose: a lit ridge and a shaded flank. Two full columns is a bar down
    # the middle of the face -- make_sprites records that one on Spite.
    ny = ey + F["nose_y"]
    p.col(int(cx) - 1, ny - 2 + dy, ny + dy, sk[0])
    p.col(int(cx), ny - 1 + dy, ny + 1 + dy, sk[2])
    p.row(ny + 1 + dy, int(cx) - 2, int(cx) + 1, sk[0])
    p.px(int(cx) - 3, ny + 1 + dy, sk[3])
    p.px(int(cx) + 2, ny + 1 + dy, sk[3])

    # Cheekbone and jaw, along the edge and not as a patch in the middle.
    for (y, x0, x1) in head[hl + 4:]:
        p.row(y + dy, x1 - 2, x1, sk[2])
        p.px(x0, y + dy, sk[1])
    p.row(head[-1][0] + dy, head[-1][1], head[-1][2], sk[3])

    # Brows: two rows, the lower inset so they taper. `tilt` is per-brow, and
    # one of them a row off the other is an opinion where two level ones are
    # nothing at all.
    tilt = m.get("tilt", (0, 0))
    brow = hr[3] if luma(hr[3]) < luma(sk[3]) else sk[3]
    browd = hr[4] if luma(hr[4]) < luma(sk[3]) else sk[4]
    for i, (bx0, bx1) in enumerate(((lx - 1, lx + 4), (rx - 1, rx + 4))):
        by = ey - m.get("brow", 2) + tilt[i]
        p.row(by + dy, bx0, bx1, brow)
        if not F.get("brow_thin"):
            # Two rows is a man's brow at this size. One row plus the taper is
            # everyone else's, and the difference between them is most of why
            # a face reads as one sex rather than the other.
            p.row(by + 1 + dy, bx0 + 2, bx1 - 2, browd)
        else:
            p.px(bx0 + 1, by + 1 + dy, browd)
            p.px(bx1 - 1, by + 1 + dy, browd)
        p.px(bx0, by + dy, hr[2])

    # Eyes. Four wide, two of pupil, and the lid over the top row is the whole
    # of the difference between a person looking at you and a person who has
    # already decided how it goes.
    lid = m.get("lid", 0)
    for x0 in (lx, rx):
        p.row(ey - 1 + dy, x0 - 1, x0 + 4, sk[2])        # the socket
        p.box(x0, ey + dy, x0 + 3, ey + 1 + dy, sk[0])   # the whites
        p.box(x0 + 1 + gaze, ey + dy, x0 + 2 + gaze, ey + 1 + dy, sk[4])
        p.row(ey + 2 + dy, x0 - 1, x0 + 4, sk[1])        # lower lid, catching
        if lid:
            p.row(ey + dy, x0, x0 + 3, sk[3])
            p.box(x0 + 1 + gaze, ey + dy, x0 + 2 + gaze, ey + dy, sk[4])
        else:
            p.px(x0 + 1 + gaze, ey + dy, C["text"])      # one pixel of catchlight

    # The mouth. One row of dark, never two: anything lit under a dark mouth
    # line is teeth, and a raised half-mouth at 1:1 is a moustache. The whole
    # expression is two pixels of corner.
    my = ey + F["mouth_y"]
    curl = m.get("curl", 0)
    mw = F.get("mouth_w", 4)
    p.row(my + dy, int(cx) - mw, int(cx) + mw - 1, sk[3])
    p.row(my + dy, int(cx) - mw + 2, int(cx) + mw - 3, sk[4])
    if curl > 0:
        p.px(int(cx) - mw - 1, my - 1 + dy, sk[3])
        p.px(int(cx) + mw, my - 1 + dy, sk[3])
    elif curl < 0:
        p.px(int(cx) - mw - 1, my + 1 + dy, sk[3])
        p.px(int(cx) + mw, my + 1 + dy, sk[3])
    if m.get("open"):
        p.row(my + 1 + dy, int(cx) - mw + 2, int(cx) + mw - 3, sk[4])
    p.row(my + 2 + dy, int(cx) - mw + 1, int(cx) + mw - 2, sk[2])


def pp_shoulders(p, dy, y0, ramp, cx=28, clip=None):
    """A bust that runs off all three lower edges of the plate. One floating
    clear of its own frame is a cut-out; one that leaves the picture is a
    person sitting in front of you.

    SIX ROWS OF YOKE AND THEN FULL WIDTH, which is the shape Spite's p_coat
    uses. The first cut here widened four pixels a row all the way down and
    filled the bottom third of the plate with a pyramid -- shoulders are a
    slope for about a sixth of a bust and horizontal after that.
    """
    right = p.w - 1 if clip is None else clip
    for i in range(6):
        y = y0 + i + dy
        x0, x1 = max(0, int(cx) - 9 - 3 * i), min(right, int(cx) + 8 + 3 * i)
        p.row(y, x0, x1, ramp[1])
        p.row(y, x0, x0 + 4, ramp[0])
        p.row(y, x1 - 5, x1, ramp[2])
    for y in range(y0 + 6 + dy, p.h):
        p.row(y, 0, right, ramp[1])
        p.row(y, 0, 8, ramp[0])
        p.row(y, max(0, right - 10), right, ramp[2])
    p.row(y0 + 5 + dy, max(0, int(cx) - 24), min(right, int(cx) + 23), ramp[0])


# --- Mrs Ollard's plate -----------------------------------------------------------
#
# She is at somebody's window and the window is the backdrop: a lit rectangle
# behind her shoulder with a gap in the curtains, so the composition says what
# she is before she says anything. She fills her plate, unlike Spite, and that
# is also a quotation -- Spite wants there to be less of him and she has her
# whole face in the gap.

OLLARD_FACE = dict(cx=25, top=8, rows=22, w=21, hairline=5, brow_thin=True,
                   eye_y=11, eye_sep=6, nose_y=3, mouth_y=8, mouth_w=3)

# The delta. Note what is NOT here: the light. Both of her are the same woman in
# the same lane at the same hour, and dimming the second one buys an unwell
# person rather than a distracted one -- the exact error Spite's `wary` made and
# had taken back out.
OLLARD_MOOD = {
    #                                                    gaze: the pupil, one px
    "nosy":   dict(hdy=0, sdy=0, lid=0, brow=3, tilt=(0, 0), curl=1, gaze=0),
    "adrift": dict(hdy=1, sdy=1, lid=0, brow=4, tilt=(-1, -1), curl=0, gaze=-1,
                   open=True),
}
PP_MOODS["busybody"] = list(OLLARD_MOOD)


def pp_ollard_ground(p):
    """A wall, and the window she has just been at: a warm rectangle with the
    curtains not quite met. It sits behind her right shoulder rather than
    behind her head, so it is somewhere she was and not a halo."""
    for y in range(p.h):
        base = mix(C["bg"], C["panel"], 0.30 + 0.26 * (1.0 - abs(y - 24) / 48.0))
        for x in range(p.w):
            u = (x - 26.0) / 34.0
            p.px(x, y, mix(base, C["bg"], min(1.0, u * u * 1.5)))
    for y in range(6, 34):                                   # the sash
        p.row(y, 34, 53, mix(C["bg"], C["accent"], 0.16))
    p.box(36, 8, 51, 31, mix(C["bg"], C["line"], 0.55))      # curtains, drawn
    p.col(43, 8, 31, mix(C["bg"], C["accent"], 0.40))        # the gap in them,
    p.col(44, 8, 31, mix(C["bg"], C["accent"], 0.26))        # which is the only
                                                             # warm thing in it
    for x in (34, 53):
        p.col(x, 5, 34, mix(C["bg"], BLACK, 0.20))
    p.row(5, 34, 53, mix(C["bg"], C["line"], 0.22))
    p.row(34, 34, 53, mix(C["bg"], BLACK, 0.22))
    p.row(19, 36, 51, mix(C["bg"], BLACK, 0.16))             # the glazing bar


def portrait_ollard(mood):
    m = OLLARD_MOOD[mood]
    p = Plate(PW, PW, C["bg"])
    pp_ollard_ground(p)
    # Four rows of neck and no more. The first cut left nine and she read as a
    # totem pole -- the same number Spite's portrait had to come down to.
    p.box(21, 28 + m["sdy"], 29, 33 + m["sdy"], SKIN_ASH[3])
    p.box(21, 28 + m["sdy"], 23, 33 + m["sdy"], SKIN_ASH[2])
    p.row(28 + m["sdy"], 21, 29, SKIN_ASH[4])
    pp_shoulders(p, m["sdy"], 32, DRESS, cx=25)
    # The shawl over the coat, in the one warm ramp she owns, and small: the
    # accent is about a tenth of her and a wider one is a bib.
    for i, y in enumerate(range(34 + m["sdy"], p.h)):
        w = 7 + i * 3
        p.row(y, max(0, 25 - w), max(0, 30 - w), ROSE[1])
        p.row(y, min(p.w - 1, 20 + w), min(p.w - 1, 25 + w), ROSE[2])
        p.row(y, max(0, 25 - w), max(0, 26 - w), ROSE[0])

    pp_face(p, dict(OLLARD_FACE, skin=SKIN_ASH, hair=HAIR_WHITE), m)
    # The bun: a knob two rows proud of the crown and set BACK. Centred and
    # tapering it is a wizard's hat, which is what the sprite's first cut was.
    dy = m["hdy"]
    p.box(30, 9 + dy, 37, 16 + dy, HAIR_WHITE[2])
    p.row(9 + dy, 31, 36, HAIR_WHITE[1])
    p.row(8 + dy, 32, 35, HAIR_WHITE[0])
    p.row(16 + dy, 31, 36, HAIR_WHITE[3])
    p.px(37, 13 + dy, HAIR_WHITE[4])
    p.px(15, 16 + dy, HAIR_WHITE[1])                          # a strand come loose
    p.px(14, 18 + dy, HAIR_WHITE[2])
    p.px(14, 20 + dy, HAIR_WHITE[3])
    return p.img.resize((PW * PSCALE, PW * PSCALE), Image.NEAREST)


# --- the children's plate ---------------------------------------------------------
#
# Two of them, because there are two of them, and one speaker record covers
# both: Pell does the talking and Bird is behind the crate wall with the jar.
# Bird is CUT OFF AT THE CHIN by the wall, which is how you draw depth with no
# depth -- she is behind it, and a whole second head at the same size beside the
# first would read as twins rather than as a fort with two children in it.
#
# The mood is the stick. `posted` has it across the bottom of the plate;
# `stood_down` has it leaning at the edge, out of the way. That reads at 1:1
# before either face resolves, which is the only thing that matters here,
# because the beat this portrait exists for is a decision and not a feeling.

PELL_FACE = dict(cx=18, top=12, rows=21, w=19, hairline=5,
                 eye_y=11, eye_sep=5, nose_y=3, mouth_y=7, mouth_w=3)
BIRD_FACE = dict(cx=43, top=21, rows=18, w=16, hairline=5,
                 eye_y=10, eye_sep=4, nose_y=2, mouth_y=6, mouth_w=3)

FORT_MOOD = {
    "posted":     dict(hdy=0, sdy=0, lid=0, brow=3, tilt=(0, 0), curl=-1,
                       gaze=0, bird=dict(hdy=0, lid=1, brow=2, tilt=(0, 0),
                                         curl=0, gaze=0), stick=True),
    "stood_down": dict(hdy=1, sdy=0, lid=0, brow=4, tilt=(-1, 0), curl=0,
                       gaze=0, bird=dict(hdy=-1, lid=0, brow=3, tilt=(-1, -1),
                                         curl=1, gaze=0), stick=False),
}
PP_MOODS["fort"] = list(FORT_MOOD)


def pp_fort_ground(p):
    """The inside of the fort: leaf-mould walls, a crate wall at the right, and
    the slot they watch the lane through -- which is the one bright thing in the
    plate and is deliberately behind Pell's shoulder, so the way out is visible
    and she is in front of it."""
    for y in range(p.h):
        base = mix(C["bg"], mix(C["good"], C["bg"], 0.74), 0.30 + 0.30 * (1.0 - y / 56.0))
        for x in range(p.w):
            u = (x - 24.0) / 36.0
            p.px(x, y, mix(base, C["bg"], min(1.0, u * u * 1.4)))
    # leaf litter: a scatter, deterministic, so a rerun is byte-identical
    for y in range(0, 56, 2):
        for x in range((y * 7) % 5, 56, 5):
            p.px(x, y, mix(C["bg"], C["good"], 0.20 if (x + y) % 3 else 0.11))
    p.box(30, 0, 33, 55, mix(C["bg"], C["accent"], 0.14))     # a crate upright
    p.col(30, 0, 55, mix(C["bg"], BLACK, 0.20))
    p.col(33, 0, 55, mix(C["bg"], BLACK, 0.14))
    p.box(34, 0, 55, 55, mix(C["bg"], C["accent"], 0.10))     # the crate wall
    for y in (12, 26, 40):
        p.row(y, 34, 55, mix(C["bg"], BLACK, 0.18))
    p.box(6, 6, 15, 21, mix(C["bg"], C["accent_2"], 0.30))    # the slot, and the
    p.box(7, 7, 14, 20, mix(C["bg"], C["accent_2"], 0.44))    # lane through it
    p.row(21, 6, 15, mix(C["bg"], BLACK, 0.24))


def portrait_fort(mood):
    m = FORT_MOOD[mood]
    b = m["bird"]
    p = Plate(PW, PW, C["bg"])
    pp_fort_ground(p)

    # Bird first: she is behind everything, and the crate lid below cuts her off
    # at the chin, which is the depth.
    pp_face(p, dict(BIRD_FACE, skin=SKIN_DEEP, hair=HAIR_STRAW), b)
    p.box(32, 38, 55, 55, mix(C["bg"], C["accent"], 0.16))       # the crate lid,
    p.row(38, 32, 55, mix(C["bg"], C["accent"], 0.26))           # which cuts her
    p.row(39, 32, 55, mix(C["bg"], BLACK, 0.20))                 # off at the chin
    jy = 42
    p.box(38, jy, 48, jy + 12, cloth5(mix(C["accent_2"], C["text"], 0.20))[2])
    p.row(jy, 39, 47, cloth5(mix(C["accent_2"], C["text"], 0.20))[1])
    p.row(jy + 1, 38, 40, cloth5(mix(C["accent_2"], C["text"], 0.20))[0])
    for i, (px_, py_) in enumerate(((40, jy + 8), (43, jy + 9), (45, jy + 7),
                                    (41, jy + 10), (46, jy + 10))):
        p.px(px_, py_, LEAF[3] if i % 2 else LEAF[4])            # the pebbles
        p.px(px_ + 1, py_, LEAF[4])

    # Pell in front, with the leaf crown.
    p.box(14, 32 + m["sdy"], 22, 40 + m["sdy"], SKIN_WARM[3])
    p.box(14, 32 + m["sdy"], 16, 40 + m["sdy"], SKIN_WARM[2])
    p.row(32 + m["sdy"], 14, 22, SKIN_WARM[4])
    pp_shoulders(p, m["sdy"], 38, LEAF, cx=18, clip=31)
    pp_face(p, dict(PELL_FACE, skin=SKIN_WARM, hair=HAIR_DARK), m)
    dy = m["hdy"]
    cy = 12 + dy
    p.row(cy, 10, 26, LEAF[1])
    p.row(cy, 10, 12, LEAF[0])
    p.px(26, cy, LEAF[2])
    for x, h in ((12, 3), (18, 5), (24, 2)):                     # three points,
        for k in range(h):                                       # uneven. An even
            p.row(cy - 1 - k, x, x + 1, LEAF[1] if k < h - 1 else LEAF[0])
    p.px(18, cy - 6, LEAF[2])

    if m["stick"]:
        # The gate, in the picture. Across the plate at knee height, in front of
        # everything, and it is the whole of the mood.
        wood = hue5(mix(C["accent"], C["bg"], 0.55))
        for i, x in enumerate(range(0, 56)):
            y = 50 - i // 6
            p.px(x, y, wood[1])
            p.px(x, y + 1, wood[2])
            p.px(x, y + 2, wood[4])
    else:
        wood = hue5(mix(C["accent"], C["bg"], 0.55))
        p.col(2, 18, 55, wood[2])                                # leaning, done
        p.col(3, 18, 55, wood[4])
        p.px(2, 18, wood[1])
    return p.img.resize((PW * PSCALE, PW * PSCALE), Image.NEAREST)


TOWN_PORTRAITS = {"busybody": (OLLARD_MOOD, portrait_ollard),
                  "fort": (FORT_MOOD, portrait_fort)}


def town_portrait_contact(plates):
    """Every mood of every face at 1:1 on the real panel_alt colour inside the
    real accent frame -- which is the check that matters, because a face that
    only works at 4x is a drawing of a portrait -- and again enlarged, which is
    only for finding WHICH pixel is wrong after the small one has told you that
    something is."""
    rows = [(stem, mood) for stem in sorted(TOWN_PORTRAITS)
            for mood in TOWN_PORTRAITS[stem][0]]
    pad, gap, zoom = 20, 20, 3
    w = pad * 2 + max(len(rows) * (112 + gap), len(rows) * (112 * zoom + gap))
    h = pad * 3 + 112 + 112 * zoom + 34
    out = Image.new("RGBA", (w, h), tuple(C["bg"]) + (255,))
    d = ImageDraw.Draw(out)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    for i, (stem, mood) in enumerate(rows):
        x = pad + i * (112 + gap)
        panel = Image.new("RGBA", (120, 120), tuple(C["panel_alt"]) + (255,))
        ImageDraw.Draw(panel).rectangle([0, 0, 119, 119], outline=C["accent"] + (255,))
        out.alpha_composite(panel, (x - 4, pad - 4))
        out.alpha_composite(plates[(stem, mood)], (x, pad))
        d.text((x, pad + 116), "%s / %s  1:1" % (stem, mood),
               fill=C["muted"] + (255,), font=font)
    y = pad * 2 + 112 + 26
    for i, (stem, mood) in enumerate(rows):
        big = plates[(stem, mood)].resize((112 * zoom, 112 * zoom), Image.NEAREST)
        out.alpha_composite(big, (pad + i * (112 * zoom + gap), y))
        d.text((pad + i * (112 * zoom + gap), y - 12), "%s / %s" % (stem, mood),
               fill=C["muted"] + (255,), font=font)
    return out


def write_town_portraits():
    os.makedirs(PORTRAITS, exist_ok=True)
    plates = {}
    names = []
    for stem in sorted(TOWN_PORTRAITS):
        moods, fn = TOWN_PORTRAITS[stem]
        for mood in moods:
            plates[(stem, mood)] = fn(mood)
            name = "%s_%s.png" % (stem, mood)
            plates[(stem, mood)].save(os.path.join(PORTRAITS, name))
            names.append(name)
    town_portrait_contact(plates).save(os.path.join(PORTRAITS, "_town_portraits.png"))
    names.append("_town_portraits.png")
    print()
    print("  town portraits %dx%d (%d logical x%d): %s"
          % (PW * PSCALE, PW * PSCALE, PW, PSCALE, ", ".join(names)))
    for stem in sorted(TOWN_PORTRAITS):
        moods = list(TOWN_PORTRAITS[stem][0])
        a, b = plates[(stem, moods[0])], plates[(stem, moods[1])]
        diff = sum(1 for u, v in zip(a.getdata(), b.getdata()) if u != v)
        print("    %-9s %s vs %s: %.1f%% of pixels differ -- one face, two moods"
              % (stem, moods[0], moods[1],
                 100.0 * diff / float(PW * PSCALE * PW * PSCALE)))
    return names


if __name__ == "__main__":
    main()
