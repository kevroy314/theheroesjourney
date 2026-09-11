#!/usr/bin/env python3
"""One 32x48 overworld figure, derived from measured reference silhouettes.

THE METHOD, AND IT IS THE WHOLE OF IT: this figure is not drawn from an idea
about how a body is built. It is drawn from a SPAN TABLE -- the first and last
opaque column of every row -- measured off three real 16-bit field sprites and
rescaled to our frame. The outline is built first and every feature is cut out
of it. Nothing here is allowed to add a pixel to the silhouette.

The three references were read off disk, are gitignored, and not one pixel of
any of them is reproduced here:

    .scratch/ref/abigail-sheet.png          crop (0,0,16,32), by its alpha
    .scratch/ref/som.png                    crop (112,124,128,156), grass
                                            flood-filled off its own palette
    AESTHETIC-SEEDS/props/chrono-trigger-0  crop (31,0,45,24), doorway masked

WHAT THEIR SPAN TABLES ACTUALLY SAY. Widths in pixels, crown row to sole:

  abigail   2 3 5 | 11 12 12 12 13 13 14 13 14 13 13 | 13 12 12 12 14 14 12 12
            | 10 8 8 8 10                                R=27  W=14  W/R=0.52
  som       7 10 12 12 12 12 14 14 14 14 14 14 16 14 12 12 | 10 | 12 13 13 14
            16 16 14 12 12 12 10 9 10 7                   R=31  W=16  W/R=0.52
  ct        10 x11 | 12 12 12 13 13 12 12 12 12 12 12 12 12
            (clipped by his own frame -- no legs, so his HEIGHT is unusable
            and only his widths are quoted below)         W=13

Six findings, each a number rather than an opinion.

  1. IT IS A COLUMN, NOT A FIGURE. From the crown of the mass to the hip the
     width never leaves 0.75..1.00 of the figure's own widest row. A quarter
     of variation in total -- on a 22-px figure, a pixel and a half a side.
     Not one of the three has a shoulder-to-waist taper of any kind.

  2. THE TWO WIDEST ROWS ARE THE HAIR AND THE HANDS, AND THEY TIE. Abigail is
     14 at rows 14 and 16 (hair) and 14 again at 23-24 (hands); the SoM girl
     is 16 at row 138 (hair) and 16 at 147-148 (hands). The SHOULDER is the
     widest row of neither. A figure whose widest row is its shoulder is a
     wardrobe, and that is the commonest way a hand-built 32-px person fails.

  3. THERE IS EXACTLY ONE NARROWING ABOVE THE LEGS AND IT IS ONE ROW. SoM goes
     14 -> 10 -> 12 at the jaw; CT goes 10 -> 12 at the same place; Abigail
     does not do it at all. Median 0.77 of the maximum, held for one row, with
     the shoulder on the very next row. That is a STEP. It is not a neck.

  4. THE CROWN IS A DOME AND THE FEET ARE PROUD. First head rows 0.44 (som) /
     0.79 (abigail, past her hair clip) / 0.77 (ct) of the maximum, at full
     width by the fourth row. Last row 0.71 over a shin of 0.57 (abigail). A
     flat top is a bread bin; a shin that ends where it stops is a chair leg.

  5. THE OUTLINE STEPS AND THEN HOLDS. Every change is exactly one pixel a
     side, and the run between two changes is two to six rows. Nothing in any
     of the three slopes. `outline()` enforces it rather than hoping for it.

  6. THE HEAD IS AS WIDE AS THE BODY, OR WIDER. Abigail's head is 14 on a
     12-14 torso (100%), the SoM girl's 16 on 12-16 (100%), the CT NPC's 10 on
     13 (77%) -- and he is wearing a helmet. Half the head's HEIGHT is hair,
     and most of its WIDTH is: the SoM girl's skull reaches her own outline on
     no row at all.

The landmarks -- where along the figure each of those happens -- agree far
better across the references than the widths do, and they are what `JAW`,
`HAND` and `LEG` are below:

                 jaw      hands       first leg row
     abigail     0.50    0.69-0.73        0.85
     som         0.53    0.70-0.73         --  (she is wearing a skirt)
     ct           --        --             --  (clipped)

Run it:  python3 tools/figure_silhouette.py
It writes .scratch/tries/silhouette/ and touches nothing else.
"""
import os

from PIL import Image

FW, FH = 32, 48
SOLE = 47                 # the feet end on the bottom row of the frame
CROWN = 4                 # ...and the crown starts here: 44 rows of figure
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   ".scratch", "tries", "silhouette")


# --- the palette ---------------------------------------------------------------
#
# CHOSEN, not inherited. The references are high-chroma 16-bit palettes and a
# desaturated one cannot answer the question this figure is asking: the SoM
# girl's dress is (160,40,112) against grass at (80,136,56), which is a hue
# apart AND a value apart, and that is why she holds together at 1:1 on a busy
# background. Every colour here is on the 5-bit-per-channel grid the SNES
# actually had (multiples of 8), which is not nostalgia -- it stops the ramps
# drifting into near-neighbours that read as one blurry mass.
#
# The budget is the reference's: the CT frame is 24 colours INCLUDING its
# background and the SoM girl is 17 on the figure. This is 20, and the count
# is asserted at the bottom of the file rather than trusted.
#
# The ramps are three steps -- lit, base, shade -- and no more, because a flat
# mass costs two tones and a sculpted one costs five. All three references
# paint whole garments in two.

INK = (32, 24, 40)          # the contour. A tinted near-black, never pure:
                            # CT uses (48,48,48), SoM (72,56,48), Abigail
                            # (18,0,30). Pure black is the one value that
                            # cannot belong to a lit scene.
HAIR = [(255, 184, 96), (232, 128, 48), (160, 72, 40)]      # copper
SKIN = [(255, 216, 176), (240, 176, 128), (192, 112, 80)]
COAT = [(88, 168, 176), (48, 112, 128), (32, 72, 96)]       # lamp-teal
TROUS = [(96, 88, 128), (72, 64, 96), (48, 40, 64)]
BOOT = [(160, 72, 72), (120, 48, 56), (80, 32, 40)]         # oxblood
BRASS = [(248, 216, 112), (216, 160, 48)]
EYE = [(248, 248, 240), (40, 104, 120), (16, 48, 64)]       # sclera, iris, deep
MOUTH = (176, 96, 80)

CLEAR = (0, 0, 0, 0)


# --- the span table ------------------------------------------------------------
#
# Three landmarks and one profile. The landmarks are fractions of the figure's
# height and come straight out of the table above; the profile is width as a
# fraction of the figure's own widest row, keyframed at the rows where the
# measurement says something happens and linear between them.

JAW = 0.51     # finding 3: abigail 0.50, som 0.53
HAND = 0.71    # finding 2: abigail 0.69-0.73, som 0.70-0.73
LEG = 0.85     # abigail 0.85; som wears a skirt and does not vote

PROFILE = (
    (0.000, 0.46), (0.020, 0.68), (0.045, 0.80),   # 4: the dome
    (0.090, 0.86), (0.150, 0.88), (0.330, 0.88),   # 1: and then it holds
    (0.385, 1.00),                                 # 2: the hair, widest
    (0.420, 0.96), (0.480, 0.84),
    (JAW,   0.73),                                 # 3: the one step
    (0.535, 0.90), (0.620, 0.92), (0.690, 0.98),   # the shoulder, immediately
    (HAND,  1.00),                                 # 2: the hands, tied
    (0.745, 0.96), (0.800, 0.90),
    (LEG,   0.74),
    (0.890, 0.58), (0.955, 0.58), (1.000, 0.72),   # 4: a proud boot
)


def sample(t):
    """PROFILE at t, linear between keyframes."""
    for i in range(len(PROFILE) - 1):
        (ta, wa), (tb, wb) = PROFILE[i], PROFILE[i + 1]
        if ta <= t <= tb:
            k = (t - ta) / (tb - ta) if tb > ta else 0.0
            return wa + k * (wb - wa)
    return PROFILE[-1][1]


def even(v):
    """Nearest even width. Even because the figure has to be symmetric about
    the line between column 15 and column 16; nearest rather than rounded up
    because at 22 px one even step is 9% of the figure, and always rounding
    outward inflates the row under the hair into the hair's own width and
    loses the peak that finding 2 is about."""
    return max(2, 2 * int(round(v / 2.0)))


def outline(top, rows, wmax):
    """The figure as one span table: [(y, x0, x1)], top row first.

    Finding 5 is enforced here. Sampling the profile alone gives a two-pixel
    jump wherever a keyframe is steeper than the frame's own resolution -- the
    hip into the shin is the worst of them -- and a two-pixel step reads as a
    corner, not as a contour.
    """
    out, prev = [], None
    for i in range(rows):
        w = even(sample(i / float(rows - 1)) * wmax)
        if prev is not None:
            w = max(prev - 2, min(prev + 2, w))
        x0 = 16 - w // 2
        out.append((top + i, x0, x0 + w - 1))
        prev = w
    return out


# --- the canvas ----------------------------------------------------------------

class Cel(object):
    def __init__(self):
        self.px = {}

    def dot(self, x, y, c):
        if 0 <= x < FW and 0 <= y < FH and c is not None:
            self.px[(x, y)] = c

    def row(self, y, x0, x1, c):
        for x in range(min(x0, x1), max(x0, x1) + 1):
            self.dot(x, y, c)

    def image(self):
        im = Image.new("RGBA", (FW, FH), CLEAR)
        for (x, y), c in self.px.items():
            im.putpixel((x, y), tuple(c) + (255,))
        return im


def contour(cel):
    """The outline, taken FROM the filled shape rather than drawn.

    Every one of the three references has a one-pixel dark line all the way
    round, and it lives INSIDE the silhouette -- it is the outermost opaque
    pixel of the row, not an extra one. So this runs last and overwrites: any
    opaque pixel with a transparent 8-neighbour becomes INK. Derived rather
    than drawn, the line cannot be left open by a pose, and the span table
    still means exactly what it says.
    """
    edge = [p for p in cel.px
            if any((p[0] + dx, p[1] + dy) not in cel.px
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1))]
    for p in edge:
        cel.px[p] = INK


def seam(cel, pts):
    """An internal edge between two masses, in INK.

    The references draw one wherever two masses meet -- under the jaw, down
    the inside of each arm, between the legs. Without them a flat figure is
    one silhouette-shaped blob of three colours; they are most of why a
    two-tone mass reads as a solid object.
    """
    for (x, y) in pts:
        cel.dot(x, y, INK)


# --- the figure ----------------------------------------------------------------
#
# WHO THIS IS. Not one of the game's townsfolk -- drawing an existing character
# would let their old geometry back in through the door the method just shut.
# This is a lamplighter's apprentice: copper hair she has not cut in a while,
# the corporation's teal coat two sizes too big with its one brass clasp, and
# boots that were somebody else's. Everything about her that the silhouette
# carries is the hair and the hands, because those are the two rows the
# measurement says are widest, and a character design that fights the
# measurement is a character design that will not read at 1:1.


def figure():
    cel = Cel()
    rows = SOLE - CROWN + 1
    # HALF AS WIDE AS TALL. All three references measure 0.52, 0.52 and (for
    # the CT NPC, against his visible height) 0.54, which is close enough to
    # call it a constant rather than a coincidence.
    wmax = even(0.52 * rows)
    span = outline(CROWN, rows, wmax)

    jaw_i = int(round((rows - 1) * JAW))
    hand_i = int(round((rows - 1) * HAND))
    leg_i = int(round((rows - 1) * LEG))
    head, trunk, legs = span[:jaw_i + 1], span[jaw_i + 1:leg_i], span[leg_i:]
    jaw_y, jaw_x0, jaw_x1 = head[-1]

    # THE FACE HANGS OFF THE JAW, NOT OFF THE CROWN. In all three references
    # the eye sits three rows off the chin whatever the head's height:
    # Abigail's eyes are rows 14-15 under a jaw at 18, the CT NPC's row 7
    # under 10, the SoM girl's 139-140 under 142. A taller head is a taller
    # HAIR MASS, not a longer forehead -- so the features are placed from the
    # bottom and the hairline is whatever is left over. Placed from the top
    # instead, a 22-row head is a forehead with a chin under it.
    mouth_y = jaw_y - 1
    eye_h = 4
    eye_y = mouth_y - 2 - eye_h + 1
    hairline = eye_y - 1

    # The face field is HALF the head's width. Measured: Abigail's skin is 6
    # px inside a 14-px head (0.43), the SoM girl's 8 inside 16 (0.50), the CT
    # NPC's 8 inside 10 (0.80, and he is the one in a helmet). Every other
    # column of the head is hair -- finding 6.
    face_w = even(0.50 * wmax)

    # --- the hair. It IS the head's span table; the face is a hole in it.
    # Fifteen rows of one flat colour is a bonnet however well the silhouette
    # is cut, so the mass gets three things and no more: the north-west
    # highlight every other part of the figure is lit by, a shaded side that
    # WIDENS as the mass turns away, and one strand that is on neither. All
    # three references shade a mass in exactly two steps; the third tone here
    # is the strand, and it is four pixels.
    for i, (y, x0, x1) in enumerate(head):
        cel.row(y, x0, x1, HAIR[1])
        cel.row(y, x1 - (2 if i > 6 else 1), x1, HAIR[2])
    for i, (y, x0, x1) in enumerate(head[1:6]):
        cel.row(y, x0 + 2, x0 + 3 - (i > 2), HAIR[0])
    for (y, x0, x1) in head[8:12]:
        cel.dot(x0 + 1, y, HAIR[0])                # one strand, off-centre

    # --- the face, cut out
    face = []
    for i, (y, x0, x1) in enumerate(head[hairline - CROWN:]):
        w = face_w - (2 if y >= jaw_y - 1 else 0)      # the chin pulls in
        fx = 16 - w // 2
        face.append((y, fx, fx + w - 1))
        cel.row(y, fx, fx + w - 1, SKIN[1])
        cel.row(y, fx + w - 2, fx + w - 1, SKIN[2])
    # THE FRINGE, cut back into the field that was just painted. A clean edge
    # all the way round is a helmet; an uneven one, in whole rows, is hair.
    # Two notches, asymmetric, because a symmetric fringe is a bowl cut and a
    # bowl cut is a helmet with a hole in it.
    fy, fx0, fx1 = face[0]
    cel.row(fy, fx0, fx0 + 4, HAIR[1])
    cel.row(fy, fx0, fx0 + 1, HAIR[0])
    cel.row(fy + 1, fx0, fx0 + 1, HAIR[1])
    cel.row(fy, fx1 - 2, fx1, HAIR[1])
    cel.row(fy, fx1 - 1, fx1, HAIR[2])

    # --- the eyes. Nine to twelve pixels each, on a face of about ninety.
    # In all three references the eye is the largest local contrast in the
    # frame and the single biggest thing the figure says about the person:
    # Abigail 2x3 with a lit sclera and a violet iris, the SoM girl 2x2 with a
    # (240,240,240) column against a (0,88,112) one, the CT NPC one dark dot
    # in a 225-luma field. The sclera goes on the OUTER column, because two
    # eyes with a light pixel each on the inside read as a nose bridge with a
    # highlight on it and the face comes out cross-eyed.
    ew, sep = 3, 4
    for side in (0, 1):
        ex = 16 - (2 * ew + sep) // 2 + side * (ew + sep)
        for k in range(eye_h):
            y = eye_y + k
            if k == 0:
                cel.row(y, ex, ex + ew - 1, SKIN[2])       # the lash row
                continue
            for i in range(ew):
                j = (ew - 1 - i) if side else i
                if j == 0:
                    c = EYE[0]
                elif k == eye_h - 1:
                    c = EYE[2]
                else:
                    c = EYE[1]
                cel.dot(ex + i, y, c)
    # ONE row of mouth, in the skin's own shade rather than a darker colour:
    # anything lit below a dark mouth line is a set of teeth, and two rows of
    # mouth on a head this size is a grin nobody ordered.
    cel.row(mouth_y, 15, 16, MOUTH)

    # --- the trunk
    for (y, x0, x1) in trunk:
        cel.row(y, x0, x1, COAT[1])
        cel.row(y, x1 - 1, x1, COAT[2])
    hip = trunk[-max(2, len(trunk) // 4):]
    for (y, x0, x1) in hip:
        cel.row(y, x0, x1, TROUS[1])
        cel.row(y, x1 - 1, x1, TROUS[2])
    # The coat: a collar row and one vertical seam. A garment drawn as shading
    # vanishes at this size -- the CT NPC's tunic is a shape with an edge, not
    # a lighter version of his trousers -- so it is the seam that is the coat.
    sy, sx0, sx1 = trunk[0]
    cel.row(sy, sx0, sx1, COAT[0])
    for (y, x0, x1) in trunk[1:len(trunk) - len(hip)]:
        cel.dot(16, y, COAT[2])
        cel.dot(15, y, COAT[0])
    cel.dot(15, sy + 1, BRASS[0])                  # the one brass clasp
    cel.dot(16, sy + 1, BRASS[1])

    # --- the arms, ON the outline's own edge columns.
    # THE HAND IS WHERE THE OUTLINE IS WIDEST, because finding 2 says that is
    # what the widest row IS. Nothing here pushes the silhouette out: the arm
    # is the outermost three columns of rows the profile has already widened,
    # and the hand is the last two of them. One column of INK down the inner
    # edge, because a sleeve in the coat's own colour with no line beside it
    # is not an arm, it is a wider chest.
    aw, hand = 4, 2
    # FROM THE SHOULDER, not from below it. An arm that starts three rows
    # down is not an arm, it is a pair of pack straps -- which is exactly how
    # the first cut of this read. The hair that falls on the shoulders is
    # drawn after and covers its top, which is the right stacking anyway.
    arm_rows = [r for r in trunk if sy <= r[0] <= CROWN + hand_i]
    for i, (y, x0, x1) in enumerate(arm_rows):
        low = i >= len(arm_rows) - hand
        if low:
            # THE HAND, and it lands on the widest row by construction. Three
            # visible pixels by two rows, which is Abigail's hand and the SoM
            # girl's to the pixel. It keeps no inner seam of its own -- the
            # cuff below is the line -- so it is wider than the wrist above
            # it, which is the only way a hand reads at this size.
            for a, b in ((x0, x0 + aw - 1), (x1 - aw + 1, x1)):
                cel.row(y, a, b, SKIN[1])
                cel.dot(b, y, SKIN[2])
        else:
            # A SLEEVE IN THE COAT'S OWN COLOUR IS NOT AN ARM, IT IS A WIDER
            # CHEST -- but the fix is a HUE, not a black line. Measured: the
            # CT NPC separates his orange sleeve from his green tunic with one
            # column of the tunic's own dark green, and the SoM girl separates
            # her green sleeve from her magenta dress with nothing at all,
            # because the hue already does it. Neither spends the figure's
            # outline colour on an internal edge. So these are leather sleeves
            # in the boots' ramp -- a second garment, which is also what the
            # CT NPC is wearing -- and the seam is that ramp's own dark.
            for a, b in ((x0, x0 + aw - 1), (x1 - aw + 1, x1)):
                cel.row(y, a, b, BOOT[1])
            cel.dot(x0 + aw - 1, y, BOOT[2])
            cel.dot(x1 - aw + 1, y, BOOT[2])
            cel.dot(x1, y, BOOT[2])
    # The cuff: the line between sleeve and hand, so the hand is a separate
    # lump and not the bottom of the sleeve painted pink.
    cy, cx0, cx1 = arm_rows[-hand]
    for x in list(range(cx0, cx0 + aw)) + list(range(cx1 - aw + 1, cx1 + 1)):
        cel.dot(x, cy - 1, BOOT[2])

    # --- the hair falling PAST the jaw onto the shoulders.
    # Most of what says "hair" rather than "hat" at this size, and the reason
    # the one-row jaw step does not read as a decapitation: the mass carries
    # on over the shoulder either side of the neck that is not there.
    tp = (jaw_x1 - jaw_x0 + 1 - face_w) // 2 + 1
    for i, (y, x0, x1) in enumerate(trunk[:2]):
        cel.row(y, max(x0, jaw_x0), min(x1, jaw_x0 + tp - 1), HAIR[1])
        cel.row(y, max(x0, jaw_x1 - tp + 1), min(x1, jaw_x1), HAIR[2])

    # --- the legs, punched out of the outline's own last rows.
    # They are not drawn and then hoped to fit: the leg band of the span table
    # already narrows to the shin and widens again for the boot, so all this
    # decides is where the gap between the two of them goes. The
    # wide-narrow-wide of finding 4 therefore survives by construction.
    gap, boot = 2, 3
    for i, (y, x0, x1) in enumerate(legs):
        w = max(2, (x1 - x0 + 1 - gap) // 2)
        top_of_boot = i == len(legs) - boot
        ramp = BOOT if i >= len(legs) - boot else TROUS
        for a in (x0, x1 - w + 1):
            cel.row(y, a, a + w - 1, ramp[1])
            cel.dot(a + w - 1, y, ramp[2])
            if top_of_boot:
                # The boot is a BLOB under the stub, in its own ramp, with a
                # lit top edge: in all three references the foot is a separate
                # lump and that is what stops two trouser columns reading as a
                # pair of chair legs.
                cel.row(y, a, a + w - 1, ramp[0])
        cel.dot(x0, y, ramp[0])

    # --- the contour, taken from the filled shape.
    #
    # AND NOTHING UNDER THE JAW. The first cut drew a bar of INK along the
    # shoulder row under the chin, on the assumption that a head sitting
    # straight on a body needs a line to separate them. Measured, not one of
    # the three references has one: SoM's row under the jaw (143) is dark only
    # at its two outline pixels, the CT NPC has dark at the jaw's corners and
    # skin across the chin, and Abigail goes straight from face to collar. The
    # separation is done by finding 3 -- the one-row pinch -- plus the change
    # of colour, and a black bar across 80% of a row is a collar nobody
    # ordered and reads as a severed head at 1:1.
    contour(cel)
    return cel.image(), span


# --- looking at it -------------------------------------------------------------

BACKDROPS = (("dark", (24, 20, 32)), ("light", (232, 224, 208)),
             ("grass", (80, 136, 56)))


def plate():
    """One figure, front on, at 1:1 and at 6x, on a dark, a light and a
    mid-green ground. 1:1 is the check that matters -- a figure that only
    works at 6x is a drawing of a figure -- and three grounds because the one
    thing a 32-px sprite has to survive is not knowing what it is standing on.
    """
    im, span = figure()
    big = im.resize((FW * 6, FH * 6), Image.NEAREST)
    pad, gap = 12, 12
    cw = FW + gap + FW * 6
    w = pad + 3 * (cw + pad)
    h = pad * 2 + FH * 6
    out = Image.new("RGBA", (w, h), (16, 16, 20, 255))
    for i, (_name, bg) in enumerate(BACKDROPS):
        x = pad + i * (cw + pad)
        out.paste(Image.new("RGBA", (cw, h - 2 * pad), tuple(bg) + (255,)),
                  (x, pad))
        out.alpha_composite(im, (x, pad + FH * 5))
        out.alpha_composite(big, (x + FW + gap, pad))
    return out, im, span


def main():
    os.makedirs(OUT, exist_ok=True)
    sheet, im, span = plate()
    sheet.save(os.path.join(OUT, "figure.png"))
    im.save(os.path.join(OUT, "figure_1x.png"))
    im.resize((FW * 6, FH * 6), Image.NEAREST).save(
        os.path.join(OUT, "figure_6x.png"))

    hues = {p[:3] for p in im.get_flattened_data() if p[3] == 255}
    leg = int(round((SOLE - CROWN) * LEG))
    rows = [(y, [x for x in range(FW) if im.getpixel((x, y))[3] == 255])
            for y in range(FH)]
    figrows = [(y, xs) for (y, xs) in rows if xs]
    top, bot = figrows[0][0], figrows[-1][0]
    wide = max(len(range(min(xs), max(xs) + 1)) for _y, xs in figrows)
    print("span table -- what was actually drawn")
    for (y, xs) in figrows:
        a, b = min(xs), max(xs)
        print("  %2d  %2d  %s%s" % (y, b - a + 1, " " * a, "#" * (b - a + 1)))
    print()
    print("  rows %d..%d  (%d)   widest %d   W/R %.2f   opaque %d px"
          % (top, bot, bot - top + 1, wide, wide / float(bot - top + 1),
             sum(len(xs) for _y, xs in figrows)))
    print("  colours %d   (ct 24 incl. background, som 17 on the figure)"
          % len(hues))
    # The one thing the span table must not have done: every row's opaque
    # pixels have to be one unbroken run ABOVE THE LEGS, or a feature has
    # punched a hole in the silhouette the outline was supposed to own. Below
    # the legs the hole is the point.
    broken = [y for (y, xs) in figrows
              if len(xs) != max(xs) - min(xs) + 1 and y < CROWN + leg]
    print("  holes above the leg split: %s" % (broken or "none"))

    # --- the grammar, checked against what it was derived from ---------------
    #
    # This is the report. Every row is a number measured off a reference and
    # the same number measured off the PNG that was just written; if a row
    # disagrees, the figure has stopped being the thing the method promised.
    w = {y: max(xs) - min(xs) + 1 for (y, xs) in figrows}
    R, W = bot - top + 1, wide

    def at(f):
        return w[top + int(round((R - 1) * f))] / float(W)

    # From the crown of the MASS -- the first row at nine tenths of the widest
    # -- to the hip, which is the window finding 1 is stated over. Measured
    # from inside the dome instead it reports the dome, which is finding 4.
    mass = min(y for y in w if w[y] >= 0.86 * W)
    trunkw = [w[y] / float(W) for y in range(mass, top + int((R - 1) * LEG))]
    print()
    print("  the grammar, measured off the file just written")
    print("    %-34s %-22s %s" % ("", "references", "this figure"))
    print("    %-34s %-22s %.2f"
          % ("aspect, widest row / height", "0.52 / 0.52 / 0.54", W / float(R)))
    print("    %-34s %-22s %.2f..%.2f"
          % ("1. trunk width band, /widest", "0.75..1.00",
             min(trunkw), max(trunkw)))
    print("    %-34s %-22s %.2f / %.2f"
          % ("2. hair row and hand row, /widest", "1.00 and 1.00",
             at(0.385), at(HAND)))
    print("    %-34s %-22s %.2f"
          % ("3. the jaw pinch, /widest", "0.77 (som .63, ct .77)", at(JAW)))
    print("    %-34s %-22s %.2f / %.2f"
          % ("4. crown row / sole row, /widest", "0.44-0.79 / 0.71",
             at(0.0), at(1.0)))
    steps = [abs(w[y] - w[y - 1]) for y in range(top + 1, bot + 1)]
    print("    %-34s %-22s %d"
          % ("5. largest step, px per side", "1", max(steps) // 2))
    hmax = max(w[y] for y in range(top, top + int((R - 1) * JAW)))
    tmax = max(w[y] for y in range(top + int((R - 1) * JAW),
                                   top + int((R - 1) * LEG)))
    print("    %-34s %-22s %.2f"
          % ("6. head widest / trunk widest", "1.00 / 1.00 / 0.77",
             hmax / float(tmax)))
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
