#!/usr/bin/env python3
"""A base overworld figure for The Heroes' Journey, drawn face first.

STANDALONE ON PURPOSE. This file imports nothing from `make_sprites.py` and
was written without reading its drawing code. Wiring it into the cast is a
separate job and must not be allowed to shape the drawing.

THE METHOD, and it is the only thing here worth keeping if the drawing is
wrong. Every figure this project has drawn so far picked a proportion first --
"three and a half heads", "the head is 45% of the figure" -- and then fitted a
face into whatever the head turned out to be. Decode the results and the face
is always the part that lost: ten pixels across, six rows deep, a letterbox of
skin at the bottom of a slab of hair. Abigail's face is two thirds of her
head's width and nearly half its height. The proportion was never the problem.

So this file names no proportion at all. It names an EYE, and every other
number is derived from it, in one direction, with no arrows pointing back:

    ONE EYE, 4 x 3, with a lash over it
    -> eye band   two eyes and the nose bridge between them       10 px wide
    -> face       the band plus one cheek column each side        12 px wide
    -> skull      the face plus a temple of hair each side        16 px wide
    -> hair mass  the skull plus a px of volume each side         18 px wide
    -> face rows  forehead, brow band, gap, lash, eye, cheek,
                  mouth, chin                                     13 rows
    -> skull rows the face plus the hair-covered forehead over it 16 rows
    -> head rows  the skull plus the hair standing above it       19 rows
    -> THE BODY   the 43 rows of figure, minus the 19 the head took

`heads` comes out at 2.26 on this figure. The Chrono Trigger and Secret of
Mana frames measure 2.4 and 2.6, so this is a little top-heavy of the band --
and that is the honest cost of the method, reported rather than tuned away.
Tuning it back would mean shrinking the face, which is the one thing this file
is not allowed to do. Everything I would give up to get there (a row of chin,
a row of forehead, the second brow row) is a row the face is using.

WHERE IT PAYS OFF TWICE. The face is a constant, not a fraction. Scale this
figure down to a child's 34 rows and the head stays 19 -- 56% of the figure
instead of 44% -- with no per-character number anywhere, because a child's eye
really is the same size as an adult's and a big head on a short body is what
"child" looks like. A base that derives the head from a fraction has to be
told that, and gets it backwards if nobody remembers to.

Run it:  python3 tools/figure_facefirst.py
"""
import os

from PIL import Image

# --- the frame ------------------------------------------------------------------
#
# The one thing here that is not mine to choose. 32x48, the centre line between
# columns 15 and 16, the planted sole on a fixed row in every frame, and the
# contact shadow allowed to spread to the bottom of the cell. Widths are even
# so the figure is not half a pixel off its own tile.

FW, FH = 32, 48
CX = 15.5
SOLE = 44                    # the row the boot ends on
GROUND = 47                  # the shadow's last row
CLEAR = (0, 0, 0, 0)
SHADOW_A = 118


def row_span(w):
    w = max(2, int(w) + (int(w) % 2))
    x0 = int(CX + 0.5) - w // 2
    return x0, x0 + w - 1


# --- the palette ----------------------------------------------------------------
#
# MINE, not the game theme's. First Light's ramps are a dusk palette with the
# chroma deliberately washed out of them, and the measurement that decided this
# is simple: the Secret of Mana girl's face is a flat field at 219 luma with an
# iris at 71 sitting in it, a ratio of three inside four pixels, and Abigail's
# sclera is 252 against a 145 face. Run through First Light the same face tops
# out at 174 and the sclera at 217 -- the eye is a smudge before it is drawn,
# and no amount of geometry gets it back. So the skin field here is 214 luma
# and the darkest thing on the figure is the eye.
#
# What is kept from the game's look rather than the reference's: the outline is
# one dark WARM colour used everywhere and not black (SoM's is (72,56,48), CT's
# (48,48,48) -- a pure black rim reads as a sticker cut out and laid on the
# grass), there is no pure white anywhere, and the one saturated garment is
# about a twentieth of the figure so the palette stays a dusk palette with a
# hot pixel in it rather than a cartoon.
#
# Twenty colours. Both reference frames are twenty to twenty-four INCLUDING
# their backgrounds, and the reason to stay there is not thrift: a figure made
# of forty near-neighbours reads as a soft blend where the reference reads as
# flat blocks with hard edges.

OUTLINE = (38, 28, 32)       # 30 luma, warm. The rim, the lash and the pupil

SKIN = [(246, 209, 172),     # 214  the face. A FLAT BRIGHT FIELD
        (222, 172, 132),     # 181  the one shaded column, and the ear
        (176, 116, 88)]      # 131  the mouth, and under the jaw

HAIR = [(226, 146, 84),      # 161  the crown highlight
        (178, 96, 52),       # 116  copper. The mass
        (108, 56, 40)]       #  70  the shaded side, and the brow

# THE EYE IS THE LARGEST INVESTMENT ON THE FIGURE and it gets its own ramp.
# Abigail spends five colours and twelve pixels on hers out of twenty-nine and
# two hundred and eighty-five -- 17% of her palette on 4% of her pixels. This
# spends three plus the shared outline -- 32 px of 851, 3.8% -- and they are
# the only three colours on the figure that are not a step of some other ramp.
EYE = [(248, 242, 228),      # 242  sclera. The brightest pixel on the figure
       (58, 146, 148),       # 118  iris. THE CHARACTER TRAIT -- see fc_eyes
       (26, 78, 92)]         #  67  iris, in the lid's shadow

COAT = [(96, 148, 126),      # 134  lit
        (58, 104, 92),       #  92  the mass
        (34, 62, 60)]        #  56  the shaded side and the seam

TROUSER = [(112, 92, 100), (74, 60, 70)]    # 96 / 64
BOOT = [(74, 48, 38), (44, 29, 26)]         # 53 / 33  a full step under the
                                            # trousers, or the leg is one
                                            # column from hip to floor and the
                                            # boot is not a boot
SASH = [(226, 118, 74), (162, 72, 52)]      # 145 / 96  the one saturated thing
BRASS = (232, 186, 92)                      # 185  three buttons and a buckle

SHADOW = (22, 18, 26)


def luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


# --- the geometry, derived in one direction -------------------------------------
#
# Read this top to bottom. Nothing below is allowed to feed back into anything
# above it, which is the entire difference between this file and the ones that
# came before it.

EYE_W = 4          # ONE eye, in px. The atom. Our frame is twice the linear
                   # size of the 16x32 references and all three of them draw a
                   # 2px eye, so four is the same eye at this scale
EYE_H = 3          # rows of iris under the lash. Two read as an eye
                   # and three read as a PERSON: swept against 2 and 4
                   # at 1:1, 3x and 10x, and three is where the iris
                   # stops being a mark and becomes an object with a
                   # lid over it. Abigail's eye is three of her seven
                   # face rows; four of this face's thirteen is close to the
                   # same share at twice the scale
EYE_SEP = 2        # bare skin between the two of them. Two in every reference
                   # AT HALF THIS SCALE, and it stays two here on purpose: the
                   # gap is a nose bridge and a nose bridge is not a fraction
                   # of the head, it is about two pixels wide at any size a
                   # face is legible at
IRIS_W = 2         # px of iris, CENTRED in the eye, sclera either side
CHEEK = 1          # skin outside each eye before the hair starts
TEMPLE = 2         # columns of hair down each side of the face
HAIR_VOL = 1       # px the hair mass stands proud of the skull
HAIR_RISE = 3      # ...and rows it stands above it
HAIR_DROP = 2      # ...and rows it falls past the jaw onto the shoulders
BROW_W = 3         # A BROW IS SHORTER THAN THE EYE UNDER IT. At the eye's full
                   # width it is a bar, and a full-width horizontal bar on a
                   # small head is a pair of goggles
BROW_GAP = 1       # bare forehead rows between the brow and the lash
MOUTH_GAP = 2      # cheek rows between the eye and the mouth
MOUTH_W = 2        # TWO. A mouth at a third of the face's width -- the
                   # share Abigail's 2px mouth has on her 6px face -- is
                   # a four-px bar here and reads as a grimace. The
                   # mouth is the one feature that does NOT scale with
                   # the head: past two px it stops being a mouth and
                   # starts being an expression nobody asked for
CHIN = 2           # rows between the mouth and the jaw
BROW_BAND = 2      # rows the brow is allowed to sit in. TWO, and this is the
                   # one row in the budget bought by an expression rather than
                   # by an anatomy. The only expression that reads at this size
                   # is one brow higher than the other; drawn with a single
                   # brow row the raised one has fringe directly above it and
                   # comes out as a NOTCH IN THE HAIR, not as a brow -- which
                   # is exactly what the first cut drew, and it took decoding
                   # the cel as text to see it
BARE = 1           # bare forehead ABOVE the brow band. Without it the raised
                   # brow has fringe directly over it and stops being a brow
FOREHEAD = 3       # rows of hair-covered skull above that. THE ONLY FREE
                   # NUMBER IN THE HEAD, and the head's height is what it
                   # buys. Raise it and you get more hair, not more face

EYE_BAND = 2 * EYE_W + EYE_SEP                 # 10
FACE_W = EYE_BAND + 2 * CHEEK                  # 12
SKULL_W = FACE_W + 2 * TEMPLE                  # 16
HAIR_W = SKULL_W + 2 * HAIR_VOL                # 18

FACE_N = (BARE + BROW_BAND + BROW_GAP + 1 + EYE_H
          + MOUTH_GAP + 1 + CHIN)                               # 13
SKULL_N = FACE_N + FOREHEAD                                        # 16
HEAD_N = SKULL_N + HAIR_RISE                                       # 19

CROWN = 2                                      # the topmost row of hair
SKULL_Y = CROWN + HAIR_RISE                    # 5
JAW = SKULL_Y + SKULL_N - 1                    # 20
SHOULDER = JAW + 1                             # 21  THERE IS NO NECK -- not
                                               # one of the three references
                                               # has a gap between jaw and
                                               # shoulder, and three rows of
                                               # bare neck is a totem pole

ROWS = SOLE - CROWN + 1                        # 43 rows of figure
LEG_N = int(round(ROWS * 0.19))                # 8 -- Abigail is 5 in 27
TORSO_N = SOLE - SHOULDER + 1 - LEG_N          # 16
HIP = SHOULDER + TORSO_N - 1                   # 36
LEG_Y = HIP + 1                                # 37

# THE BODY IS WHAT IS LEFT, and its width is the only thing on the figure that
# is not derived from the face -- because it is the one axis a cast varies on.
# Twenty across the torso plus a px of arm proud each side is 22, and all three
# references are about half as wide as they are tall (14/27, 12/24, 16/31).
# Eighteen across the torso plus a px of arm proud each side is twenty, and
# the head's hair mass is eighteen -- so the head TIES the torso and loses to
# the shoulders by two, which is the CT NPC's 10-on-12 exactly. Twenty was the
# first number here and it made a fridge: torso over height at 0.47 against
# the references' 0.39 to 0.42.
TORSO_W = 18
ARM_W = 3

# The face's landmarks, counted down from the hairline.
HAIRLINE_Y = SKULL_Y + FOREHEAD                #  8  the first row of skin
BROW_Y = HAIRLINE_Y + BARE + BROW_BAND - 1     # 10  the LOWER of the two
LASH_Y = BROW_Y + 1 + BROW_GAP                 # 12
EYE_Y = LASH_Y + 1                             # 13
MOUTH_Y = EYE_Y + EYE_H + MOUTH_GAP            # 18

DOME = (8, 4, 2)      # px off the width at the crown: 8, 12, 14, then full
CHIN_T = (4, 2)       # ...and off the last two, counted UP from the jaw,
                      # so the chin narrows downward. The first cut had
                      # this pair the other way round and every head
                      # came out wider at the jaw than at the cheek --
                      # a lantern jaw nobody had asked for, and invisible
                      # until the cel was decoded as text


def spans(w, n, top):
    """A mass: full width through the middle, domed at the top, tapered at the
    chin. A straight line across the top of a head is a container -- the first
    thing a reader resolves on a 32px figure is the crown, and a flat one is a
    bread bin with a face on it."""
    out = []
    for i in range(n):
        d = DOME[i] if i < len(DOME) else 0
        k = n - 1 - i
        if k < len(CHIN_T):
            d = max(d, CHIN_T[k])
        x0, x1 = row_span(w - d)
        out.append((top + i, x0, x1))
    return out


SKULL = spans(SKULL_W, SKULL_N, SKULL_Y)
HAIRM = spans(HAIR_W, HEAD_N, CROWN)
EYE_X0, EYE_X1 = row_span(EYE_BAND)            # 11 .. 20


# --- the canvas -----------------------------------------------------------------

class Cel:
    def __init__(self):
        self.img = Image.new("RGBA", (FW, FH), CLEAR)
        self.p = self.img.load()

    def px(self, x, y, c, a=255):
        if 0 <= x < FW and 0 <= y < FH:
            self.p[int(x), int(y)] = tuple(c) + (a,)

    def row(self, y, x0, x1, c):
        for x in range(int(x0), int(x1) + 1):
            self.px(x, y, c)

    def box(self, x0, y0, x1, y1, c):
        for y in range(int(y0), int(y1) + 1):
            self.row(y, x0, x1, c)

    def at(self, x, y):
        return self.p[int(x), int(y)] if 0 <= x < FW and 0 <= y < FH else CLEAR


def mass(f, sp, base, shade, cols=2, dy=0):
    """A flat fill and one band of shade down its lit-away side.

    Two tones, not five. The Secret of Mana girl's whole dress is two. Four
    tones in bands that narrow with the row is a soft gradient however hard
    each individual edge is, and that softness is most of what makes a figure
    drawn in this palette look unlike the ones it is trying to look like.
    """
    for (y, x0, x1) in sp:
        f.row(y + dy, x0, x1, base)
        f.row(y + dy, max(x0, x1 - cols + 1), x1, shade)


# --- THE FACE -------------------------------------------------------------------
#
# Everything above exists to put this in the right place at the right size.

def fc_eyes(f, gaze=0):
    """Two eyes, four px by two, with a lash over each.

    WHICH OF THE THREE SOLUTIONS, AND WHY. The references do not agree, and
    the disagreement is the interesting part:

      Chrono Trigger  a 2x2 block of the figure's own OUTLINE colour punched
                      into a 168-225 luma face. No sclera. One colour, and it
                      costs nothing because the colour is already there.
      Secret of Mana  2x2, the outer column (240,240,240) and the inner
                      (0,88,112). Two colours, flat, maximum contrast, no lid.
      Stardew         2 wide and THREE rows: a near-black lash at (18,0,30),
                      then a sclera column and an iris column, each drawn
                      twice -- once in the lid's shadow and once lit. Five
                      colours and twelve pixels for two eyes, out of a figure
                      with twenty-nine colours and two hundred and eighty-five
                      pixels. Seventeen per cent of her palette on four per
                      cent of her pixels.

    THIS TAKES STARDEW'S, for one reason that survives being argued with: it
    is the only one of the three where the eye carries a COLOUR, and an iris
    colour is one of about four things a 32px figure can say about a person
    that its silhouette cannot. CT's eye says nothing about who he is; SoM's
    teal is the same teal on the next villager. Abigail's are violet and that
    is a fact about Abigail.

    WHAT IS CHANGED FROM IT. The iris is CENTRED in the eye rather than pushed
    to the inner column. Stardew's arrangement -- sclera outside, iris inside
    -- is a face looking very slightly at its own nose, which is invisible at
    her scale and is not at ours; and a centred iris can be MOVED, which is the
    cheapest expression in the whole toolkit. `gaze` of +1 is a figure looking
    off to its left, and it costs no pixels and no colours.

    THE LASH IS THE FIGURE'S OWN OUTLINE COLOUR, not a fifth eye tone. It is
    already in the palette, it is the darkest thing on the figure, and it sits
    directly against the brightest -- 30 luma over 242, adjacent, which is a
    ratio of eight in two pixels. That contrast is the whole reason the eye
    reads at 1:1, and it is worth more than the extra tone Stardew spends on
    shading the sclera.

    Cost: 32 px and three colours, plus the rim's, which was already paid.
    """
    pad = (EYE_W - IRIS_W) // 2
    for x0 in (EYE_X0, EYE_X1 - EYE_W + 1):
        f.row(LASH_Y, x0, x0 + EYE_W - 1, OUTLINE)
        for k in range(EYE_H):
            for i in range(EYE_W):
                j = i - gaze
                iris = pad <= j < pad + IRIS_W
                # THE LID'S SHADOW FALLS ON THE TOP ROW OF THE IRIS, not the
                # bottom. That is what Abigail's two greens are doing -- her
                # (9,53,27) sits over her (31,107,89) -- and swept against the
                # other way round and against a flat iris, it is the only one
                # of the three that reads as an eye in a socket rather than a
                # bead stuck on the front of the head. The sclera stays one
                # flat bright tone either side of it, which is what keeps the
                # two dark rows from merging with the lash into a bar.
                f.px(x0 + i, EYE_Y + k,
                     (EYE[2] if k == 0 else EYE[1]) if iris else EYE[0])


def fc_brows(f, tilt=(0, 0)):
    """Two short bars of the hair's own dark, above the eyes with bare
    forehead between.

    ASYMMETRY IS THE CHEAPEST EXPRESSION AND THE MOST RELIABLE. Both brows
    moved together read as surprise or as nothing; ONE brow a row higher reads
    as an opinion, and it reads at 1:1 where a curled lip does not. The default
    here is (0, -1) -- she is not convinced.

    In the HAIR ramp rather than the skin's, so a white-haired character gets
    white brows for free and it costs no colour anybody is not already paying
    for.
    """
    f.row(BROW_Y + tilt[0], EYE_X0, EYE_X0 + BROW_W - 1, HAIR[2])
    f.row(BROW_Y + tilt[1], EYE_X1 - BROW_W + 1, EYE_X1, HAIR[2])


def fc_mouth(f):
    """One row, four px, in the skin's own shade and never darker.

    ANYTHING LIT BELOW A DARK MOUTH LINE IS TEETH, so there is one row and
    nothing under it. And the mouth is the skin's third step at 131 luma on a
    214 face -- a ratio of 0.6, which is what Abigail's (86,59,105) on her
    (219,124,136) is. Drawn in the outline colour it is a hole punched through
    the chin, which is the first thing this face got wrong.
    """
    x0, x1 = row_span(MOUTH_W)
    f.row(MOUTH_Y, x0, x1, SKIN[2])


def fc_face(f):
    """The skin field, then the hair that frames it, then the features.

    A FLAT BRIGHT FIELD WITH DARK PUNCHED INTO IT AND NOTHING ELSE. No nose,
    no cheek shading, no chin dimple: in two of the three references the face
    carries exactly two features and the third carries one. Every extra mark
    at this size becomes a shape you did not intend, and the unintended one
    wins -- a row of shade beside a nose is a muzzle, a lit lower lip is a set
    of teeth, and a raised half-mouth is a moustache.
    """
    fc_brows(f, tilt=(0, -1))
    fc_eyes(f)
    fc_mouth(f)
    # The jaw's underside, so the chin is a chin and not the flat bottom of a
    # cylinder. Two px either side of the mouth's width and no more: a FULL
    # row of shade under a face is a beard, which is the same class of error
    # as the goggles and costs the same nothing to avoid.
    y, x0, x1 = SKULL[-1]
    f.row(y, x0 + 2, x1 - 2, SKIN[1])


def fc_skin(f):
    """The field the face sits in: one flat bright tone and a single shaded
    column, and that is the whole of it."""
    for (y, x0, x1) in SKULL:
        f.row(y, x0, x1, SKIN[0])
        f.px(x1, y, SKIN[1])


def fc_hair(f, back=False):
    """The hair as its own mass with its own silhouette, not a cap painted on
    a dome.

    It is wider than the skull, it rises above it, it falls past the jaw onto
    the shoulders -- which is the single cheapest thing that says "hair"
    rather than "hat" at this size -- and its edge over the forehead is UNEVEN.
    A clean edge all the way round is a helmet; a fifteen-row mass with a ruled
    line across the bottom of it is a motorcycle helmet with a face in it.

    ONE break and no more, and it is a STEP IN THE MIDDLE rather than a notch
    at one end: the fringe hangs a row lower over the left of the face than
    over the right. Two breaks placed symmetrically are a pair of ears, and a
    notch cut out of the middle of a fringe is a widow's peak nobody asked
    for. It hangs on the LEFT because the raised brow is on the right and a
    raised brow needs bare forehead over it -- the two asymmetries are the
    same asymmetry, which is why the face reads as one decision and not two.
    """
    hspan = {y: (x0, x1) for (y, x0, x1) in HAIRM}
    last = JAW if back else HAIRLINE_Y - 1
    for (y, x0, x1) in HAIRM:
        if y > last:
            break
        f.row(y, x0, x1, HAIR[1])
        f.row(y, x1 - 1, x1, HAIR[2])
        if y - CROWN < 3:
            # A HIGHLIGHT ON THE CROWN. Nineteen rows of one flat colour is a
            # bonnet however well the silhouette is cut, and this is the
            # cheapest thing in the file that says the mass is round.
            f.row(y, x0 + 2, x0 + 3, HAIR[0])
    if back:
        # THE BACK OF A HEAD IS ALL HAIR AND NOTHING ELSE, which is what the
        # `up` frame of every reference sheet shows -- Abigail's has two skin
        # pixels in it, both of them ears. So the eye, which is this figure's
        # largest single investment, buys nothing at all from behind, and
        # every claim it makes about who this is has to be made a SECOND TIME
        # by something that survives the turn: the hair's hue, the shape of
        # its mass, and the one saturated colour at the collar. That is the
        # honest answer to "what does the eye do facing away" -- it does not
        # exist, and the figure has to be recognisable without it.
        #
        # TWO PIXELS OF EAR and nothing else. Abigail's back frame contains
        # exactly two skin pixels and they are her ears; everything else is
        # hair. A parting drawn down the middle looks like a scar and a
        # highlight drawn as a column looks like a zip -- both were tried.
        for y in (EYE_Y, EYE_Y + 1):
            hx0, hx1 = hspan[y]
            f.px(hx0, y, SKIN[1])
            f.px(hx1, y, SKIN[2])
        return
    # The temples: a constant frame of hair down each side of the face. They
    # are what the 12-px face width is measured from, so they do NOT taper --
    # the skull's own jaw taper pulls them in over the last two rows and that
    # is enough. Held wide all the way down they would be a pair of headphones.
    for (y, x0, x1) in SKULL:
        if y < HAIRLINE_Y:
            continue
        hx0, hx1 = hspan[y]
        f.row(y, hx0, x0 + TEMPLE - 1, HAIR[1])
        f.row(y, x1 - TEMPLE + 1, hx1, HAIR[2])
    # The step. Whole rows at fixed columns, because a character has to come
    # out the same every run, and off-centre so the two halves of the fringe
    # are not a pair.
    y, x0, x1 = SKULL[HAIRLINE_Y - SKULL_Y]
    f.row(HAIRLINE_Y, x0, x0 + TEMPLE + 4, HAIR[1])
    # ...and past the jaw onto the shoulders, which is the single cheapest
    # thing that says "hair" rather than "hat" at this size.
    for i in range(HAIR_DROP):
        y = SHOULDER + i
        jx0, jx1 = SKULL[-1][1], SKULL[-1][2]
        f.row(y, jx0 - HAIR_VOL, jx0 + TEMPLE - 1, HAIR[1])
        f.row(y, jx1 - TEMPLE + 1, jx1 + HAIR_VOL, HAIR[2])


# --- and the body it is standing on ---------------------------------------------
#
# Deliberately the least interesting part of the file. It is a stack of flat
# blocks -- torso, two arms, two hands, two legs, two boots -- because that is
# what the reference figures are, and because everything the figure has to say
# it says with the head. What the body owes the face is (a) to not be wider
# than it has to be, (b) to have a value break at the hip so it is not one
# barrel of cloth, and (c) to put the one saturated colour on the figure up at
# the collar where the eye is already looking.

HEM_Y = HIP - 3          # the coat ends here and the trousers start


def fc_body(f, back=False):
    tx0, tx1 = row_span(TORSO_W)
    mass(f, [(y, tx0, tx1) for y in range(SHOULDER, HEM_Y)], COAT[1], COAT[2],
         cols=3)
    f.row(SHOULDER, tx0, tx1, COAT[2])
    # The one vertical line on the torso. Without it a coat and a smock are
    # the same rectangle -- at this size a lapel is its seam and nothing else.
    for y in range(SHOULDER + 3, HEM_Y):
        f.px(15, y, COAT[2])
        f.px(16, y, COAT[2] if back else COAT[0])
    # THE ONE SATURATED THING, at the throat, about a twentieth of the figure.
    # Up here rather than at the hem because it is where the reader is already
    # looking, and because a hot colour under a face is the oldest trick there
    # is for making the face the subject.
    f.row(SHOULDER + 1, tx0 + 2, tx1 - 2, SASH[0])
    f.row(SHOULDER + 2, tx0 + 3, tx1 - 3, SASH[1])
    if not back:
        # A COAT SEEN FROM BEHIND HAS NO BUTTONS ON IT. Obvious written down
        # and invisible in the render until the back frame is put beside the
        # front one, which is the whole reason to draw the back at all.
        for y in (SHOULDER + 5, SHOULDER + 8):
            f.px(16, y, BRASS)
    # The coat's hem, one row of its own dark. A garment with no edge at the
    # bottom is a colour change, and a colour change is not a coat.
    f.row(HEM_Y - 1, tx0, tx1, COAT[2])
    # The value break at the hip. The bottom of the torso IS the top of the
    # trousers, which is what the Chrono Trigger NPC does, and it costs no
    # colour that is not already on the figure.
    mass(f, [(y, tx0, tx1) for y in range(HEM_Y, HIP + 1)],
         TROUSER[0], TROUSER[1], cols=3)
    if not back:
        f.px(16, HEM_Y, BRASS)


def fc_arms(f):
    """Two arms, three px wide, of which ONE is proud of the torso.

    Proud by three -- an arm swinging clear of the body -- puts a hole of air
    in the middle of a figure whose whole claim is that it is made of solid
    blocks. Proud by nothing makes the arm an invisible stripe of the coat.
    One px plus a column of the figure's own contour on the inside is exactly
    what the reference does, and the contour is already in the palette.
    """
    tx0, tx1 = row_span(TORSO_W)
    y0 = SHOULDER + HAIR_DROP
    y1 = HEM_Y - 1
    # left arm: lit on its outer column, contour on the inner.  right arm:
    # contour on the inner, shade on the outer. The light is the same
    # north-west light the head is under, which is most of what stops the two
    # halves of a symmetrical figure reading as a paper doll.
    for ax0, lit, inner in ((tx0 - 1, tx0 - 1, tx0 + 1),
                            (tx1 - 1, None, tx1 - 1)):
        for y in range(y0, y1 - 1):
            f.row(y, ax0, ax0 + ARM_W - 1, COAT[1])
            f.px(ax0 + ARM_W - 1, y, COAT[2])
            if lit is not None:
                f.px(lit, y, COAT[0])
            f.px(inner, y, OUTLINE)
        for y in range(y1 - 1, y1 + 1):
            f.row(y, ax0, ax0 + ARM_W - 1, SKIN[1])
            f.px(ax0 + ARM_W - 1, y, SKIN[2])
            f.px(inner, y, OUTLINE)


def fc_legs(f):
    """Two stubs and two boot blobs. The boot is a separate lump under the
    stub, one px proud on the outside, because two trouser columns with square
    ends are a pair of chair legs."""
    lw, gap = 4, 2
    sx0, sx1 = row_span(2 * lw + gap)
    for x0, out in ((sx0, 1), (sx1 - lw + 1, 0)):
        for y in range(LEG_Y, SOLE - 2):
            f.row(y, x0, x0 + lw - 1, TROUSER[0])
            f.row(y, x0 + lw - 2, x0 + lw - 1, TROUSER[1])
        for y in range(SOLE - 2, SOLE + 1):
            f.row(y, x0 - out, x0 + lw - 1, BOOT[0])
            f.px(x0 + lw - 1, y, BOOT[1])
        f.row(SOLE, x0 - out, x0 + lw - 1, BOOT[1])


# --- closing the silhouette -----------------------------------------------------

def rim(img, col=OUTLINE):
    """A hard rim derived FROM THE ALPHA MASK, not drawn.

    Drawn by hand it is wrong the first time the pose changes; derived, the
    silhouette is closed whatever happens above. Eight-connected, one colour
    for the whole figure -- one per material was sixteen extra colours all by
    itself, and both reference frames use exactly one.
    """
    out = img.copy()
    src, dst = img.load(), out.load()
    for y in range(FH):
        for x in range(FW):
            if src[x, y][3]:
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < FW and 0 <= ny < FH and src[nx, ny][3] == 255:
                        dst[x, y] = col + (255,)
                        break
                else:
                    continue
                break
    return out


def contact_shadow(img, rx=10.0, ry=4.0):
    """One flat, hard-edged, aliased ellipse in one colour at one alpha,
    CENTRED under the sole rather than offset, because the figure can stand
    anywhere and a light direction baked into the shadow is a light direction
    that is wrong three quarters of the time. Without it the figure floats."""
    out = img.copy()
    dst = out.load()
    cy = GROUND - ry + 0.5
    for y in range(FH):
        for x in range(FW):
            if dst[x, y][3]:
                continue
            u = (x + 0.5 - 16.0) / rx
            v = (y + 0.5 - cy) / ry
            if u * u + v * v <= 1.0 and y <= GROUND:
                dst[x, y] = SHADOW + (SHADOW_A,)
    return out


def figure(gaze=0, tilt=(0, -1), back=False):
    """One front-facing cel. The composite order IS the model, so it is
    written out here rather than left to emerge from where the calls sit."""
    f = Cel()
    fc_legs(f)
    fc_body(f, back=back)
    fc_arms(f)
    # The head goes on LAST, over the shoulders it sits on, so the jaw is an
    # edge between two masses and not a join between two tapers. Skin, then
    # the hair that frames it, and the FEATURES LAST -- drawn before the hair
    # they are painted over by the fringe, which is how the first cut of this
    # lost one eyebrow entirely and did not notice for an hour.
    fc_skin(f)
    fc_hair(f, back=back)
    if not back:
        fc_face(f)
    return contact_shadow(rim(f.img))


# --- looking at it --------------------------------------------------------------
#
# 1:1 is the check that matters. A face that only works at 6x is not a face,
# it is a drawing of one. The enlargement is for finding WHICH pixel is wrong
# after the small one has told you THAT one is.

def backdrop(kind, w, h):
    """A busy ground, not a flat swatch. A figure judged on a flat background
    is a figure that has not been judged."""
    base, alt = {
        "dark": ((26, 30, 34), (18, 21, 25)),
        "light": ((196, 190, 172), (176, 170, 152)),
        "green": ((58, 84, 56), (44, 68, 44)),
    }[kind]
    im = Image.new("RGBA", (w, h))
    p = im.load()
    for y in range(h):
        for x in range(w):
            n = (x * 7 + y * 13 + ((x * x + y * 3) % 11)) % 17
            t = n / 17.0
            p[x, y] = tuple(int(round(base[i] + (alt[i] - base[i]) * t))
                            for i in range(3)) + (255,)
            if (x * 5 + y * 3) % 23 == 0:
                p[x, y] = tuple(int(c * 0.82) for c in p[x, y][:3]) + (255,)
    return im


def on(bg, cel, scale, reps=1):
    w, h = FW * reps, FH
    plate = backdrop(bg, w, h)
    for i in range(reps):
        plate.alpha_composite(cel, (i * FW, 0))
    return plate.resize((w * scale, h * scale), Image.NEAREST)


def strip(cel, scale, reps=1, pad=4):
    tiles = [on(b, cel, scale, reps) for b in ("dark", "light", "green")]
    w = sum(t.width for t in tiles) + pad * (len(tiles) - 1)
    out = Image.new("RGBA", (w, tiles[0].height), (12, 12, 16, 255))
    x = 0
    for t in tiles:
        out.alpha_composite(t, (x, 0))
        x += t.width + pad
    return out


def face_plate(scale=12, reps=1, bgs=("green",)):
    """The subject of the file, alone. At 12x to count the pixels and at 1:1,
    repeated on three grounds, because 1:1 on a BUSY background is the only
    check that decides whether any of this worked."""
    cel = figure()
    crop = cel.crop((4, CROWN - 2, 28, JAW + 3))
    w, h = crop.size
    pad = 2
    tiles = []
    for b in bgs:
        plate = backdrop(b, w * reps, h)
        for i in range(reps):
            plate.alpha_composite(crop, (i * w, 0))
        tiles.append(plate.resize((w * reps * scale, h * scale), Image.NEAREST))
    out = Image.new("RGBA", (sum(t.width for t in tiles) + pad * (len(tiles) - 1),
                             tiles[0].height), (12, 12, 16, 255))
    x = 0
    for t in tiles:
        out.alpha_composite(t, (x, 0))
        x += t.width + pad
    return out


def stats(cel):
    px = [q for q in cel.getdata() if q[3] == 255]
    hues = {q[:3] for q in px}
    alph = sorted({q[3] for q in cel.getdata()})
    ls = sorted(luma(q) for q in px)
    return dict(n=len(px), hues=len(hues), alpha=alph,
                lo=ls[0], hi=ls[-1], mean=sum(ls) / len(ls))


def ascii_face(cel):
    """The face as text, with a legend. The only way to check a pixel from a
    terminal, and the fastest way to count what a feature actually cost."""
    keys, order = {}, []
    out = []
    for y in range(CROWN, JAW + 1):
        line = ""
        for x in range(4, 28):
            q = cel.getpixel((x, y))
            if q[3] != 255:
                line += "."
                continue
            if q[:3] not in keys:
                keys[q[:3]] = "0123456789abcdefghijklmnop"[len(order)]
                order.append(q[:3])
            line += keys[q[:3]]
        out.append("%2d %s" % (y, line))
    out.append("   " + "".join(str(x % 10) for x in range(4, 28)))
    for c in order:
        out.append("   %s #%02X%02X%02X luma %3d" % (keys[c], c[0], c[1], c[2],
                                                     luma(c)))
    return "\n".join(out)


OUT = "/home/kevin/fitrogue/.scratch/tries/facefirst"


def main():
    os.makedirs(OUT, exist_ok=True)
    cel = figure()
    cel.save(os.path.join(OUT, "figure.png"))
    strip(cel, 1, reps=3).save(os.path.join(OUT, "figure_1x.png"))
    # ZOOM 3 is what the game actually runs at -- 32px tiles at zoom 3, so one
    # sprite pixel is three device pixels. 1:1 is the strict check and 6x is
    # the diagnostic, but THIS is the size a player sees.
    strip(cel, 3).save(os.path.join(OUT, "figure_3x_gamesize.png"))
    strip(cel, 6).save(os.path.join(OUT, "figure_6x.png"))
    face_plate(12).save(os.path.join(OUT, "face_12x.png"))
    face_plate(1, reps=5, bgs=("dark", "light", "green")).save(
        os.path.join(OUT, "face_1x.png"))
    face_plate(3, reps=3, bgs=("dark", "light", "green")).save(
        os.path.join(OUT, "face_3x_gamesize.png"))
    strip(figure(back=True), 6).save(os.path.join(OUT, "back_6x.png"))
    gz = Image.new("RGBA", (FW * 3, FH), CLEAR)
    for i, g in enumerate((-1, 0, 1)):
        gz.alpha_composite(figure(gaze=g), (i * FW, 0))
    plate = backdrop("green", FW * 3, FH)
    plate.alpha_composite(gz)
    plate.resize((FW * 3 * 6, FH * 6), Image.NEAREST).save(
        os.path.join(OUT, "gaze_6x.png"))

    s = stats(cel)
    print("figure  %d opaque px  %d colours  alpha %s" % (s["n"], s["hues"],
                                                          s["alpha"]))
    print("        luma %.0f..%.0f mean %.1f" % (s["lo"], s["hi"], s["mean"]))
    print("        head %d rows of %d -- %.2f heads, derived not chosen"
          % (HEAD_N, ROWS, ROWS / float(HEAD_N)))
    print("        face %d x %d px inside a head %d x %d -- %.0f%% of its width"
          % (FACE_W, FACE_N, HAIR_W, HEAD_N, 100.0 * FACE_W / HAIR_W))
    eye_px = 2 * EYE_W * (EYE_H + 1)
    print("        eyes %d px (%.1f%% of the figure), %d colours of %d"
          % (eye_px, 100.0 * eye_px / s["n"], 3, s["hues"]))
    print()
    print(ascii_face(cel))
    print()
    print("wrote %s" % OUT)


if __name__ == "__main__":
    main()
