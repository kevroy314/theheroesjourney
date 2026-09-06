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
    write_spite(save, grounds, cels)

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


if __name__ == "__main__":
    main()
