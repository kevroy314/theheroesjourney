#!/usr/bin/env python3
"""Draw the player walk cycle as true pixel art.

The pipeline skill's hard finding is that the image model cannot hold an
identity across frames — sprite sheets come back as labelled contact sheets with
wandering column pitch and a silhouette that redraws every frame. So the
character is authored, the same way tools/make_glyphs.py authors the icons.

The subject is the traveller who wakes in the Waking Room every loop: small,
hooded, no face. At 24x32 a face is four pixels of mud and reads as damage, so
the hood carries a dark void where the face would be and the *silhouette* does
all the work — hood, shoulders, cloak hem, two legs.

Two decisions worth stating up front, because a loader depends on them:

  Column 0 is the neutral pose, not the first step. A character standing still
  shows column 0, so idle needs no lookup table and no special case. The walk
  therefore plays 1, 0, 2, 0 — step-left, neutral, step-right, neutral.

  `right` is a horizontal mirror of `left`. The character is symmetric apart
  from the shoulder the satchel strap crosses, and mirroring that is invisible
  at this size; a separately drawn right-facing set would only be an extra
  chance for the two to drift apart.

Colours are read from data/themes/firstlight.json and mixed. Nothing here is a
free-floating hex — see RAMP.

    python3 tools/make_sprites.py      # writes assets/sprites/*.png
"""
import json
import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "sprites")
THEME = os.path.join(ROOT, "data", "themes", "firstlight.json")

FW, FH = 24, 32                      # one frame
FACINGS = ["down", "up", "left", "right"]
FRAMES = ["neutral", "step_left", "step_right"]
WALK_ORDER = [1, 0, 2, 0]            # columns, in playback order

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


# The character's whole ramp, derived from the theme.
#
# The cloak sits on `line` pulled towards `muted` rather than on `line` itself.
# That was measured against the tiles: the ground tiles run 36-93 luma and raw
# `line` lands at 55, inside the grass and the flagstone. The player has to be
# the lightest thing on the ground plane or he vanishes on the tile he spends
# chapter 4 standing in. Pulled to `muted` the cloak sits at ~85-120, clear of
# everything walkable.
RAMP = {
    "outline": mix(C["bg"], BLACK, 0.45),          # near-black, all round
    "hood_lit": mix(C["line"], C["muted"], 0.70),  # light from above
    "cloak": mix(C["line"], C["muted"], 0.38),
    "cloak_shade": C["line"],
    "cloak_deep": mix(C["line"], C["bg"], 0.45),
    "face_void": mix(C["bg"], C["line"], 0.25),    # under the hood, no features
    # Darker than the hem, deliberately. At 0.55 the boot resolved to the same
    # RGB as cloak_deep and the legs vanished into the skirt whenever the
    # outline was not between them.
    "boot": mix(C["bg"], C["line"], 0.32),
    "boot_lit": mix(C["line"], C["muted"], 0.20),
    "strap": mix(C["accent"], C["bg"], 0.35),      # the one warm pixel he owns
}


# --- drawing ------------------------------------------------------------------

class Frame:
    """A 24x32 cel. Draws body colours only; the outline is added afterwards
    from the alpha mask, so the silhouette is guaranteed closed no matter what
    the pose does."""

    def __init__(self):
        self.img = Image.new("RGBA", (FW, FH), CLEAR)

    def px(self, x, y, c):
        if 0 <= x < FW and 0 <= y < FH:
            self.img.putpixel((x, y), c + (255,))

    def row(self, y, x0, x1, c):
        for x in range(x0, x1 + 1):
            self.px(x, y, c)

    def rows(self, spans, c):
        for y, x0, x1 in spans:
            self.row(y, x0, x1, c)

    def col(self, x, y0, y1, c):
        for y in range(y0, y1 + 1):
            self.px(x, y, c)


def outline(frame, c):
    """Ring the silhouette in near-black.

    This is the single most important pass in the file. The tiles are quiet by
    design and several of them sit at the same luma as the cloak's shadow side;
    without a hard dark edge the character dissolves into the ground the moment
    he stops moving. Derived from the alpha mask rather than drawn, so it can
    never disagree with the pose.
    """
    src = frame.img
    ring = Image.new("RGBA", (FW, FH), CLEAR)
    px = src.load()
    for y in range(FH):
        for x in range(FW):
            if px[x, y][3]:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < FW and 0 <= ny < FH and px[nx, ny][3]:
                    ring.putpixel((x, y), c + (255,))
                    break
    ring.alpha_composite(src)
    return ring


# --- the poses ----------------------------------------------------------------
#
# Proportion is the whole job at this size. The first pass gave the hood the
# same width as the shoulders and ran one flat value from collar to hem; it read
# as a postbox. What fixed it:
#
#   * a 3px step at the shoulder on each side — hood 10 wide, shoulders 16 —
#     so there is a neck in the silhouette even though there is no neck drawn;
#   * a value that darkens from crown to hem, which is the only thing giving
#     the cloak volume once the outline has taken the edges;
#   * a waist. Hood 10, shoulders 16, waist 12, skirt 14 is what makes the
#     outline read as a body rather than as a container.
#
# Shared vertical structure, so he keeps his proportions when he turns:
#
#   y 2..11   hood            y 12..15  shoulders
#   y 16..19  waist           y 20..25  cloak skirt
#   y 26..30  legs            y 31      free for the outline
#
# `dy` shifts the upper body down by one pixel on the step frames. The feet
# never move vertically, so the character does not pop when he stops walking —
# a bob applied to the whole figure looks better in isolation and worse in the
# game, because idle is the pose you see most.

LIT, CLOAK = "hood_lit", "cloak"
SHADE, DEEP = "cloak_shade", "cloak_deep"


def paint(f, spans, dy=0):
    """spans is (y, x0, x1, ramp-key). Painted in order, so a later span
    overdraws an earlier one — shading is layered on top of silhouette."""
    for y, x0, x1, key in spans:
        f.row(y + dy, x0, x1, RAMP[key])


# Hood and shoulders, front and back. Identical apart from what is under the
# hood, because the same person turning round should not change size.
HEAD_FRONTAL = [
    (2, 9, 14, LIT), (3, 8, 15, LIT), (4, 7, 16, LIT), (5, 7, 16, LIT),
    (6, 7, 16, CLOAK), (7, 7, 16, CLOAK), (8, 7, 16, CLOAK),
    (9, 7, 16, SHADE), (10, 8, 15, SHADE), (11, 9, 14, DEEP),
]
FACE_VOID = [
    (6, 10, 13, "face_void"), (7, 9, 14, "face_void"),
    (8, 9, 14, "face_void"), (9, 10, 13, "face_void"),
]
BODY_FRONTAL = [
    (12, 5, 18, LIT), (13, 4, 19, CLOAK), (14, 4, 19, CLOAK),
    (15, 5, 18, CLOAK),
    (16, 6, 17, CLOAK), (17, 6, 17, CLOAK), (18, 6, 17, SHADE),
    (19, 6, 17, SHADE),
    (20, 5, 18, SHADE), (21, 5, 18, SHADE), (22, 5, 18, SHADE),
    (23, 5, 18, DEEP), (24, 5, 18, DEEP), (25, 5, 18, DEEP),
]
# Arms are the outer two columns in shadow: enough to keep the torso from
# being one field, not so much that the outline gains a notch.
ARMS_FRONTAL = [
    (15, 5, 6, SHADE), (15, 17, 18, SHADE),
    (16, 6, 7, SHADE), (16, 16, 17, SHADE),
    (17, 6, 7, SHADE), (17, 16, 17, SHADE),
    (18, 6, 7, DEEP), (18, 16, 17, DEEP),
    (19, 6, 7, DEEP), (19, 16, 17, DEEP),
    (20, 5, 6, DEEP), (20, 17, 18, DEEP),
]


def legs_frontal(f, pose, dy):
    """Two legs seen from front or back. The lifted leg is drawn two pixels
    short: at this size a raised foot reads better as an absence than as a
    foot drawn somewhere new."""
    boot, lit, deep = RAMP["boot"], RAMP["boot_lit"], RAMP["cloak_deep"]

    def planted(x0):
        f.row(26 + dy, x0, x0 + 2, deep)
        f.row(27, x0, x0 + 2, boot)
        f.row(28, x0, x0 + 2, boot)
        f.row(29, x0, x0 + 2, lit)
        f.row(30, x0 - 1, x0 + 2, boot)      # the foot, one pixel proud

    def lifted(x0):
        f.row(26 + dy, x0, x0 + 2, deep)
        f.row(27, x0, x0 + 2, boot)
        f.row(28, x0, x0 + 2, lit)

    if pose == "neutral":
        planted(8)
        planted(13)
    elif pose == "step_left":
        planted(7)                            # left leg swung out and planted
        lifted(14)
    else:
        lifted(7)
        planted(14)


def build_frontal(pose, facing_up):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    paint(f, HEAD_FRONTAL, dy)
    if facing_up:
        # Seen from behind: no opening, one seam down the back of the cowl.
        f.col(11, 5 + dy, 10 + dy, RAMP[SHADE])
        f.col(12, 5 + dy, 10 + dy, RAMP[SHADE])
    else:
        paint(f, FACE_VOID, dy)
    paint(f, BODY_FRONTAL, dy)
    paint(f, ARMS_FRONTAL, dy)
    if facing_up:
        f.col(11, 16 + dy, 24 + dy, RAMP[SHADE])          # centre fold
    else:
        for i in range(6):                                # strap across chest
            f.px(8 + i, 14 + i + dy, RAMP[DEEP])
        f.px(14, 20 + dy, RAMP["strap"])                  # buckle at the hip
        f.px(14, 21 + dy, RAMP["strap"])
    # Cloak sway: the hem swings against the stride, one column deep.
    if pose == "step_left":
        f.col(18, 22, 25, RAMP[SHADE])
    elif pose == "step_right":
        f.col(5, 22, 25, RAMP[SHADE])
    legs_frontal(f, pose, dy)
    return f


# The profile is narrower — 9 wide at the hood, 13 at the shoulder — and the
# hood's brow pushes one pixel further forward than anything else on the
# figure. That brow, plus the cloak trailing off the back, is what tells you at
# a glance this is a side view and not a narrow front view.
HEAD_PROFILE = [
    (2, 9, 14, LIT), (3, 8, 15, LIT), (4, 7, 15, LIT),
    (5, 6, 15, LIT), (6, 6, 15, CLOAK), (7, 6, 15, CLOAK), (8, 6, 15, CLOAK),
    (9, 7, 15, SHADE), (10, 8, 15, SHADE), (11, 9, 14, DEEP),
]
# The opening is a two-pixel slit set into a straight front edge. Cutting a
# wider notch out of a brow that already juts gave the hood a beak — two
# indentations one above the other read as a jaw, not as a cowl.
HOOD_NOTCH = [
    (7, 6, 7, "face_void"), (8, 6, 7, "face_void"),
]
BODY_PROFILE = [
    (12, 7, 16, LIT), (13, 6, 17, CLOAK), (14, 6, 17, CLOAK),
    (15, 7, 17, CLOAK),
    (16, 7, 16, CLOAK), (17, 7, 16, CLOAK), (18, 7, 16, SHADE),
    (19, 7, 16, SHADE),
    (20, 7, 17, SHADE), (21, 7, 17, SHADE), (22, 7, 17, SHADE),
    (23, 7, 17, DEEP), (24, 7, 17, DEEP), (25, 7, 17, DEEP),
]


def build_profile(pose):
    f = Frame()
    dy = 0 if pose == "neutral" else 1
    paint(f, HEAD_PROFILE, dy)
    paint(f, HOOD_NOTCH, dy)
    paint(f, BODY_PROFILE, dy)
    f.col(16, 13 + dy, 22 + dy, RAMP[SHADE])              # back seam of the cloak
    # Trailing cloak, thrown further back on the step frames.
    trail = 23 if pose == "neutral" else 25
    for y in range(19, trail):
        f.row(y + dy, 18, 18 if pose == "neutral" else 19, RAMP[DEEP])

    # The near arm, swinging opposite the near leg.
    ax = 8 if pose == "step_left" else (10 if pose == "step_right" else 9)
    for y in range(15, 21):
        f.row(y + dy, ax, ax + 1, RAMP[SHADE])
    f.px(ax, 21 + dy, RAMP["strap"])                      # a glove clasp

    boot, lit, deep, shade = (RAMP["boot"], RAMP["boot_lit"],
                              RAMP["cloak_deep"], RAMP[SHADE])
    # A pixel of daylight between the legs even at rest: two 3px legs touching
    # read as one thick one, and the stance is half of what says "standing".
    if pose == "neutral":
        near, far = 8, 12
    elif pose == "step_left":
        near, far = 7, 13
    else:
        near, far = 13, 7
    # Far leg first, in shadow, so the near one overlaps it and the stride has
    # depth instead of reading as two legs side by side.
    f.row(26 + dy, far, far + 2, deep)
    f.row(27, far, far + 2, deep)
    f.row(28, far, far + 2, deep)
    f.row(29, far, far + 2, shade)
    f.row(30, far, far + 2, deep)
    f.row(26 + dy, near, near + 2, deep)
    f.row(27, near, near + 2, boot)
    f.row(28, near, near + 2, boot)
    f.row(29, near, near + 2, lit)
    f.row(30, near - 1, near + 2, boot)

    # The profile is drawn one pixel right of where it wants to live, because
    # the trailing cloak only exists on one side. Shift it back so `left` and
    # its mirror `right` share a centre — otherwise the character twitches
    # sideways every time the player turns round.
    centred = Image.new("RGBA", (FW, FH), CLEAR)
    centred.paste(f.img, (-1, 0))
    f.img = centred
    return f


def build(facing, pose):
    if facing == "down":
        f = build_frontal(pose, False)
    elif facing == "up":
        f = build_frontal(pose, True)
    else:
        f = build_profile(pose)
    img = outline(f, RAMP["outline"])
    if facing == "right":
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    return img


# --- output -------------------------------------------------------------------

def contact(sheet, scale=4):
    """A 4x preview with the cell grid ruled over it. The grid is the point:
    the sheet is what the engine slices, so the eye should be checking that
    every figure sits inside its own 24x32 box, not admiring the art."""
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


def main():
    os.makedirs(OUT, exist_ok=True)

    cels = {(fa, po): build(fa, po) for fa in FACINGS for po in FRAMES}

    # Per-facing strips: 3 columns of 24x32, frame order == FRAMES.
    for fa in FACINGS:
        strip = Image.new("RGBA", (FW * len(FRAMES), FH), CLEAR)
        for i, po in enumerate(FRAMES):
            strip.paste(cels[(fa, po)], (i * FW, 0))
        strip.save(os.path.join(OUT, "walk_%s.png" % fa))

    # The sheet the engine slices. Strictly regular: 3 columns x 4 rows of
    # 24x32, no padding, no margin, no per-cell offset of any kind.
    sheet = Image.new("RGBA", (FW * len(FRAMES), FH * len(FACINGS)), CLEAR)
    for r, fa in enumerate(FACINGS):
        for c, po in enumerate(FRAMES):
            sheet.paste(cels[(fa, po)], (c * FW, r * FH))
    sheet.save(os.path.join(OUT, "player.png"))
    contact(sheet).save(os.path.join(OUT, "_player_x4.png"))

    # Prove the grid rather than assert it: every cel must be inside its box,
    # and the feet must land on the same row in every frame or the character
    # bobs when he should not.
    print("player.png  %dx%d  =  %d cols x %d rows of %dx%d"
          % (sheet.width, sheet.height, len(FRAMES), len(FACINGS), FW, FH))
    print("rows %s / cols %s / walk order %s"
          % (FACINGS, FRAMES, WALK_ORDER))
    for fa in FACINGS:
        boxes = []
        for po in FRAMES:
            bb = cels[(fa, po)].getbbox()
            boxes.append(bb)
        feet = {b[3] for b in boxes}
        x0, x1 = min(b[0] for b in boxes), max(b[2] for b in boxes) - 1
        print("  %-6s bbox x %d..%d  y %d..%d   centre %.1f   feet row %s"
              % (fa, x0, x1,
                 min(b[1] for b in boxes), max(b[3] for b in boxes) - 1,
                 (x0 + x1) / 2.0,
                 "stable" if len(feet) == 1 else "MOVES %s" % sorted(feet)))
    print("wrote %d cels to %s" % (len(cels), OUT))


if __name__ == "__main__":
    main()
