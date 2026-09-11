#!/usr/bin/env python3
"""A 32x48 overworld figure, drawn hair first.

Standalone on purpose. Nothing here imports from `tools/make_sprites.py` and
nothing here was written with that file open: it is five thousand lines of the
figure we are trying to get away from, and a builder written next to it comes
out as that builder with different numbers in it. Integration is somebody
else's later job and must not be allowed to shape the drawing.

THE METHOD, AND IT IS THE WHOLE OF IT
-------------------------------------
The hair is the character, and it is drawn first. `HAIR` below is an authored
silhouette -- a literal list of (x0, x1) spans, one per row, typed out the way
you would draw it on squared paper. It exists before there is a skull, a body,
a garment or a palette. Then:

    1. the skull is fitted INSIDE and BEHIND it, three px narrower each side
       and four rows lower at the crown. It is never on the outline. In the
       front view it is not visible at all except through the face window.
    2. the face is a WINDOW cut in the mass -- ten to twelve px wide inside a
       mass that is twenty-five across -- and it is the only skin above the
       shoulders. Nothing is drawn on it but two eyes and two px of mouth.
    3. the body is fitted UNDER it. The shoulders are two px narrower than the
       hair each side and the hands come back to within a pixel of it, so the
       widest thing in the picture is hair and it gets there twenty rows
       before anything else does.

MEASURED ON WHAT CAME OUT (`python3 tools/figure_hairfirst.py` prints it):
49%, 50% and 43% of each figure's outline pixels are its mass, against the
reference's 46.7%; 50-55% of the opaque pixels, against 37.5%; 19 to 20
colours each, against the reference's 20-to-29 range.

WHY, MEASURED RATHER THAN REMEMBERED
------------------------------------
`.scratch/ref/abigail-sheet.png`, Stardew Valley, 64x448 RGBA, 16x32 frames,
front idle at crop (0, 0, 16, 32). Decoded, never copied, never committed.

    figure rows 5..31, 27 rows, 285 opaque px
    hair rows 5..19 -- FIFTEEN of the twenty-seven
    107 of the 285 opaque pixels are hair                       37.5%
    35 of the 75 pixels ON THE OUTLINE are hair                 46.7%
    the face is a window 5 rows tall and 8 px wide, x4..x11, inside a mass
      that is 14 px wide -- so 57% of the head's width is hair either side
    the hair's widest row is 14 px. Her shoulders are also 14. THE HAIR TIES
      WITH THE WHOLE BODY for the widest thing in the frame, and it gets
      there eight rows sooner

And the outline is broken. Her left edge runs x1 x1 x1 x2 x1 x1 x1 x1 x2 down
rows 8..16 and her right x11 x12 x12 x13 x13 x13 x14 x13 x14 over the same
rows: nine steps in fifteen rows and no two alike. There is also a teal
ornament with a yellow pin standing three rows clear of the crown on her left
and nothing answering it on her right. That asymmetry is not decoration -- it
is the difference between hair and a helmet, and no shape function produces
it, because any curve smooth enough to write in three lines is monotonic and a
monotonic edge on a head is a helmet. So the spans are typed.

For scale: `AESTHETIC-SEEDS/props/chrono-trigger-0.png` at (31, 0, 45, 24) is
14x24 with the head 42% of the figure and one flat (48,48,48) outline;
`.scratch/ref/som.png` at (112, 124, 128, 156) is 16x32, the head 17 of 30
rows, one flat (72,56,48) outline, a face at 219 luma with two dark pixels in
it, and a dress in exactly two tones.

THE PALETTE IS CHOSEN HERE AND NOT INHERITED
--------------------------------------------
The game's own ramps are deliberately desaturated -- built to sit under a dusk
and to stay clear of the ground's luma band -- and the references are not. The
SoM girl's face is 219 luma against a 64-luma eye; her dress is two tones and
both of them hold a colour you could name. So these figures are mixed here,
high chroma, nineteen or twenty colours each including the outline and the
contact shadow, which is the reference's own budget. One warm dark outline for the whole figure rather
than one per material, because that is what both native frames do and because
per-material contours cost a dozen colours by themselves.

A BALD CHARACTER IS THE EXCEPTION AND NEEDS A SUBSTITUTE
--------------------------------------------------------
Everything above says the reader recognises a crown-shaped mass. Take the mass
away and there is nothing left to recognise: a bare dome over a face is an egg
with features printed on it, at any zoom, in any palette. So `kettle` below is
bald and is given three masses instead of one -- a knotted headscarf over the
crown with a hard band across the brow, two tails of it falling behind the
ear, and a beard that is as much of his outline as the scarf is. The bare
skull left between them is three rows of forehead and the eyes, and it is
never the silhouette. There is no code path in this file that draws a bare
dome, and `kettle` measures 43% of his outline in substitute mass against
`ember`'s 49% in hair -- the same figure, by the same number.

    python3 tools/figure_hairfirst.py [outdir]
"""
import os
import sys

from PIL import Image

W, H = 32, 48
SOLE = 47                     # feet on the bottom row of the cell
CLEAR = (0, 0, 0, 0)


# --- 1. THE HAIR ----------------------------------------------------------------
#
# Typed, not generated. Each entry is one row of the mass from its topmost row
# down to the jaw, as (x0, x1) inclusive. Read them as a picture: that is what
# they are, and the irregularities in them are the character.
#
# The three masses differ in the way three people's hair differs -- where the
# volume sits, how far down it comes, and how it is broken -- and NOT in a
# parameter. `ember` is a wide high mass parted on her left with the weight
# over her right ear; `tide` is a long centre-parted fall that starts narrow
# and keeps widening all the way past the elbow; `kettle` is not hair at all.

HAIR = {
    # Ember. Twenty-two rows from crown to jaw, widest at row 12 -- eight rows
    # above her own shoulders. Fourteen steps in the left edge and eleven in
    # the right, and they do not line up.
    "ember": [
        (12, 19),   #  3   the crown, and it leans: the apex sits left of CX
        (10, 21),   #  4
        (8, 23),    #  5
        (7, 25),    #  6   the right side gets there first and stays ahead --
        (6, 26),    #  7   the whole mass is swept over that shoulder
        (5, 27),    #  8
        (5, 27),    #  9
        (4, 28),    # 10
        (6, 28),    # 11   a two-px bite out of the left, one row deep
        (4, 28),    # 12   widest. 25 px, and every one of them is hair
        (4, 28),    # 13
        (4, 26),    # 14   ...and a two-px bite out of the right, three rows
        (4, 26),    # 15      later and lower down, so they are not a pair
        (5, 28),    # 16
        (5, 28),    # 17
        (4, 27),    # 18   the fringe is at 18; below this the face is open
        (4, 27),    # 19
        (6, 27),    # 20
        (5, 26),    # 21
        (5, 26),    # 22
        (6, 25),    # 23
        (7, 24),    # 24   the jaw
    ],
    # Tide. The opposite reading of the same principle: almost no volume at the
    # crown and all of it below, a centre-parted fall that is still widening at
    # the shoulder. Her mass is 32 rows of a 44-row figure.
    "tide": [
        (13, 18),   #  4
        (11, 20),   #  5
        (10, 21),   #  6
        (9, 22),    #  7
        (8, 23),    #  8
        (8, 23),    #  9
        (7, 24),    # 10
        (7, 24),    # 11
        (7, 25),    # 12
        (6, 25),    # 13
        (6, 25),    # 14
        (6, 25),    # 15
        (6, 26),    # 16
        (6, 26),    # 17
        (5, 26),    # 18
        (5, 26),    # 19
        (5, 26),    # 20
        (5, 27),    # 21
        (5, 27),    # 22
        (5, 27),    # 23
        (5, 27),    # 24
    ],
    # Kettle. NOT HAIR: a rag knotted over a bald head, and the tell is that a
    # rag is cut and hair is not. Fifteen rows, a clean edge, one crease where
    # it is pulled over the ear, and it stops dead at the brow instead of
    # breaking into a fringe.
    "kettle": [
        (11, 20),   #  4
        (9, 22),    #  5
        (7, 24),    #  6
        (6, 25),    #  7
        (5, 26),    #  8
        (5, 26),    #  9
        (4, 27),    # 10
        (4, 27),    # 11
        (4, 27),    # 12
        (4, 27),    # 13
        (4, 27),    # 14
        (4, 27),    # 15
        (5, 27),    # 16
        (5, 26),    # 17
        (5, 26),    # 18   the band. A ruled line, and that is the point
    ],
}

# What falls PAST the jaw, onto and over the shoulders, as (y, x0, x1). This is
# the single cheapest thing that says "hair" rather than "hat" at this size,
# and the two sides are never level: a hem ruled all the way round is the same
# helmet read from underneath.
LOCKS = {
    "ember": [
        (25, 5, 9), (26, 5, 9), (27, 6, 9),                  # the short side
        (25, 21, 26), (26, 21, 26), (27, 21, 26),            # ...and the long
        (28, 21, 25), (29, 22, 25), (30, 22, 24), (31, 23, 24),
    ],
    "tide": [(y, 5, 9) for y in range(25, 33)] +
            [(33, 6, 9), (34, 6, 8)] +
            [(y, 22, 26) for y in range(25, 31)] +
            [(31, 22, 25), (32, 23, 25)],
    # The two ends of the knot, hanging behind ONE ear. Cloth, and it hangs in
    # straight pieces of it, because cloth does and hair does not.
    "kettle": [(19, 4, 7), (20, 4, 7), (21, 4, 7), (22, 4, 7),
               (23, 5, 7), (24, 5, 7), (25, 5, 6),
               (19, 25, 27), (20, 25, 27), (21, 26, 27)],
}

# The fringe. RUNS across the face window, as (from, to, delta) in fractions
# of its width: +1 hangs the mass one row lower over that run and -1 lifts it
# and shows a row more forehead.
#
# Runs and not per-column values, which is how this was first written: a
# fringe sampled column by column comes out as a dotted line of hair and skin
# along the brow, and at 1:1 that is not an uneven fringe, it is a speckle --
# the same class of error as drawing a brow as a bar and getting goggles. Hair
# separates into LOCKS, and a lock is three or four px wide.
#
# One row is the whole range either way. A fringe that reaches the lash row is
# a figure peering out from under itself, which reads as a hood; two rows of
# lift is a receding hairline. `kettle` has none at all, because a cut edge is
# exactly what makes his mass read as cloth instead of hair.
FRINGE = {
    "ember": ((0.00, 0.30, 1), (0.30, 0.55, 0), (0.55, 0.80, 1),
              (0.80, 1.00, 0)),
    "tide": ((0.00, 0.22, 1), (0.22, 0.44, 0), (0.44, 0.58, -1),
             (0.58, 0.82, 0), (0.82, 1.00, 1)),
    "kettle": (),
}

# --- 2. the people --------------------------------------------------------------
#
# Three, and they are not anybody's townsfolk. Each one is a hair silhouette
# with a person fitted underneath it, which is the order this file exists to
# argue for; the writing is one line each because at 32x48 one line is all the
# art can carry.

CHARACTERS = {
    # "She has been up a tree." The loudest thing in any street she is on, and
    # it is not her clothes.
    "ember": dict(
        mass_top=3, jaw=24, sh=25, hip=38, ly=39,
        skull_w=18, temple=(3, 3), brow=18, eye=19, eye_w=3, eye_gap=2,
        sh_w=20, waist_w=20, hem_w=22, leg_w=5, leg_gap=2,
        hair=("#FFB05C", "#D66C30", "#8C382A"),
        skin=("#FFE2C4", "#F7C89E", "#CE8E74"),
        eyes=("#FAF6EE", "#2E7888", "#173F52"),
        cloth=("#6EBE96", "#3A8C70", "#205852"),
        under=("#F2E6CE", "#C9B294", "#8A7660"),
        trouser=("#5A5C9C", "#3C3E6A", "#26284A"),
        boots=("#8C5A3A", "#6C442E", "#48301F"),
        line="#2A1C2A",
        garment="tunic", overhang=3,
    ),
    # "She is listening to something you cannot hear." Almost no crown and all
    # the mass below it -- the same principle, drawn upside down.
    "tide": dict(
        mass_top=4, jaw=24, sh=25, hip=38, ly=39,
        skull_w=16, temple=(3, 3), brow=18, eye=19, eye_w=3, eye_gap=2,
        sh_w=18, waist_w=16, hem_w=22, leg_w=4, leg_gap=2,
        hair=("#6F6FCF", "#3B3A85", "#20204F"),
        skin=("#F6D9C4", "#E0B294", "#A8735E"),
        eyes=("#FAF6EE", "#C4762E", "#6B3A18"),
        cloth=("#E8D2B0", "#C4A47C", "#8A6B52"),
        under=("#D46A8C", "#A44468", "#6C2A46"),
        trouser=("#C4A47C", "#8A6B52", "#5C4736"),
        boots=("#4A4A5C", "#33333F", "#1F1F28"),
        line="#241C30",
        garment="dress", overhang=4,
    ),
    # "He is bald and he is not an egg." The exception, and the whole reason
    # the exception needs its own entry: three masses, none of them hair.
    "kettle": dict(
        mass_top=4, jaw=25, sh=26, hip=38, ly=39,
        skull_w=18, temple=(2, 2), brow=19, eye=20, eye_w=3, eye_gap=2,
        sh_w=22, waist_w=22, hem_w=22, leg_w=5, leg_gap=2,
        # THE RAG IS THE LOUDEST THING ON HIM AND THAT IS THE POINT. The first
        # cut mixed it a warm off-white a few luma off his own skin, and it
        # came out as a bald head with a shadow on it -- the exact egg this
        # figure exists to refuse, produced by a palette rather than by a
        # shape. A substitute silhouette only substitutes if it is a different
        # MATERIAL, and at 32x48 material is colour.
        hair=("#E2705A", "#A83A34", "#6B1F24"),          # the rag
        skin=("#D9A578", "#B47F56", "#7C5038"),
        eyes=("#FAF6EE", "#3E7A46", "#1F4028"),
        cloth=("#4E7A5E", "#33563F", "#1E3427"),
        under=("#EDE3CB", "#C6B896", "#8B8067"),
        trouser=("#4E5A5E", "#37413F", "#232B29"),
        boots=("#7A5636", "#573C25", "#38271A"),
        line="#2A1A1C",
        garment="apron", overhang=2,
        # The beard is the SECOND substitute mass, and it is pale against a
        # dark rag so the two do not merge into one lump with a face in it.
        beard=("#E8E2D2", "#B9B2A0", "#7C7566"), beard_top=22, ears=True,
    ),
}


# --- the canvas -----------------------------------------------------------------

def rgb(s):
    return (int(s[1:3], 16), int(s[3:5], 16), int(s[5:7], 16))


class Cel:
    def __init__(self):
        self.img = Image.new("RGBA", (W, H), CLEAR)
        self.p = self.img.load()

    def px(self, x, y, c):
        if 0 <= x < W and 0 <= y < H:
            self.p[int(x), int(y)] = tuple(c) + (255,)

    def row(self, y, x0, x1, c):
        for x in range(int(x0), int(x1) + 1):
            self.px(x, y, c)

    def box(self, x0, y0, x1, y1, c):
        for y in range(int(y0), int(y1) + 1):
            self.row(y, x0, x1, c)

    def at(self, x, y):
        return self.p[x, y] if 0 <= x < W and 0 <= y < H else CLEAR


def mass_spans(key, spec):
    """The hair, as absolute (y, x0, x1). Step zero, before anything else."""
    top = spec["mass_top"]
    return [(top + i, x0, x1) for i, (x0, x1) in enumerate(HAIR[key])]


def skull_spans(spec, mass):
    """The head, FITTED INSIDE THE MASS. Four rows lower at the crown, three px
    narrower each side, with a dome on the top of it and a real chin under it.

    It is derived from the mass rather than the other way round, which is the
    one structural claim this file makes. Nothing about the skull can change
    the outline, because the mass is always outside it -- so the dome up here
    is only ever seen through the face window, and the CHIN is the only part of
    it the reader meets.
    """
    jaw = spec["jaw"]
    top = mass[0][0] + 4
    w = spec["skull_w"]
    n = jaw - top + 1
    crown = (6, 4, 2)
    # Eight px off the last row, four off the one above it. This is the whole
    # of the chin, and without it the face is a letterbox of skin with two
    # eyes floating in it and a ruled line under them -- which is what the
    # first cut of this looked like, and it read as a mask rather than a head.
    chin = (8, 4, 1)
    out = []
    for i in range(n):
        k = n - 1 - i
        d = crown[i] if i < len(crown) else 0
        if k < len(chin):
            d = max(d, chin[k])
        ww = max(4, w - d)
        x0 = 16 - ww // 2
        out.append((top + i, x0, x0 + ww - 1))
    return out


def body_spans(spec):
    """The torso, fitted UNDER the hair. One width with a shoulder slope on
    the first row, because the locks land there and a lock landing on a
    vertical wall of cloth reads as hair growing out of a box."""
    sh, hip = spec["sh"], spec["hip"]
    out = []
    for y in range(sh, hip + 1):
        t = (y - sh) / float(max(1, hip - sh))
        if y == sh:
            w = spec["sh_w"] - 4
        elif y == sh + 1:
            w = spec["sh_w"] - 2
        else:
            w = spec["waist_w"] + int(round((spec["hem_w"] - spec["waist_w"])
                                            * max(0.0, (t - 0.45) / 0.55)))
        w = max(6, w + (w % 2))
        out.append((y, 16 - w // 2, 16 - w // 2 + w - 1))
    return out


# --- the drawing ----------------------------------------------------------------

def draw_legs(c, spec, pal):
    tr, bt = pal["trouser"], pal["boots"]
    w, gap = spec["leg_w"], spec["leg_gap"]
    total = 2 * w + gap
    x0 = 16 - total // 2
    for lx, out in ((x0, 1), (x0 + w + gap, 0)):
        for y in range(spec["ly"], SOLE - 3):
            c.row(y, lx, lx + w - 1, tr[1])
            c.row(y, lx + w - 2, lx + w - 1, tr[2])
        c.row(SOLE - 4, lx, lx + w - 1, tr[2])
        for y in range(SOLE - 3, SOLE + 1):
            o = out if y > SOLE - 3 else 0
            c.row(y, lx - o, lx + w - 1, bt[1])
            c.px(lx + w - 1, y, bt[2])
        c.row(SOLE, lx - out, lx + w - 1, bt[2])


def draw_body(c, spec, pal, body):
    """What the torso is wearing, as BLOCKS with edges.

    Three garments, and every one of them is two flat fields meeting at a hard
    line. A garment drawn as shading disappears at this size -- the SoM girl's
    whole dress is two tones and you can still say what it is -- so the rule
    here is that nothing is a garment unless it has an edge you could trace.
    """
    cl, un, tr = pal["cloth"], pal["under"], pal["trouser"]
    kind = spec["garment"]
    hip, sh = spec["hip"], spec["sh"]
    line = pal["line"]
    waist = sh + int(round((hip - sh) * 0.55))
    for (y, x0, x1) in body:
        base = cl
        if kind == "tunic" and y > waist + 1:
            base = tr                                  # trousers under it
        elif kind == "dress" and y <= waist:
            base = un                                  # a bodice, then a skirt
        c.row(y, x0, x1, base[1])
        c.row(y, x1 - 1, x1, base[2])
    x0, x1 = body[2][1], body[2][2]
    y0 = sh + spec["overhang"]
    if kind == "tunic":
        # A yoke: one band of the trim across the shoulders with a hard line
        # under it, and a second at the waist. Two edges, and between them the
        # tunic is one flat colour -- which is the reference's whole method.
        # A collar and not a stripe. Run the full width of the chest -- which
        # is how this was first drawn -- two pale rows under a jaw are a
        # bib, and the figure reads as wearing a towel.
        c.row(y0, 12, 19, un[1])
        c.row(y0 + 1, 13, 18, un[2])
        c.row(waist, x0, x1, un[1])                    # ...and a belt
        c.row(waist + 1, x0, x1, un[2])
    elif kind == "dress":
        c.row(waist, x0, x1, line)                     # the waist, one line
        for (y, bx0, bx1) in body:
            if y > waist + 1:
                # Two folds in the skirt, off centre, so it is cloth hanging
                # rather than a cone.
                c.px(bx0 + 3, y, cl[0])
                c.px(bx1 - 5, y, cl[2])
        c.row(sh + 1, x0 + 3, x1 - 3, un[0])           # a collar
    elif kind == "apron":
        for y in range(y0 + 2, hip + 1):
            for (yy, bx0, bx1) in body:
                if yy == y:
                    c.row(y, bx0 + 3, bx1 - 3, un[1])
                    c.px(bx1 - 3, y, un[2])
        for y in range(y0, y0 + 2):
            c.px(15 - 3, y, un[1])
            c.px(15 + 4, y, un[1])


def draw_arms(c, spec, pal, body):
    """The sleeve lies INSIDE the torso and only the hand reaches the hair's
    own width. Abigail's arms are inside her 12-px torso until her hands push
    it to 14, and that step at the wrist is the only place the body is allowed
    to tie with the mass.

    AN ARM IN THE CHEST'S OWN COLOUR IS NOT AN ARM. The first cut drew the
    sleeve in the garment's base with one column of the outline between them,
    and what came out was a wider chest with a line on it: at this size an arm
    is a value, not an edge. So the sleeve is the garment's SHADE, three px
    wide, the full height of the torso, and the hand steps one px proud of it.
    """
    cl, sk = pal["cloth"], pal["skin"]
    y0 = spec["sh"] + 2
    y1 = spec["hip"] - 1
    if spec["garment"] == "dress":
        # A hand at the widest row of a skirt is a flipper. Hers rest at the
        # waist, which is also where the skirt starts and so where the
        # silhouette still has a side for them to be at.
        y1 = spec["sh"] + int(round((spec["hip"] - spec["sh"]) * 0.55)) + 2
    for (y, bx0, bx1) in body:
        if not (y0 <= y <= y1 - 2):
            continue
        c.row(y, bx0, bx0 + 2, cl[2])
        c.row(y, bx1 - 2, bx1, cl[2])
    for (y, bx0, bx1) in body:
        if not (y1 - 1 <= y <= y1):
            continue
        c.row(y, bx0 - 1, bx0 + 2, sk[1])
        c.px(bx0 - 1, y, sk[0])
        c.row(y, bx1 - 2, bx1 + 1, sk[1])
        c.px(bx1 + 1, y, sk[2])


def draw_skull(c, spec, pal, skull):
    sk = pal["skin"]
    for (y, x0, x1) in skull:
        c.row(y, x0, x1, sk[1])
        c.row(y, x1 - 1, x1, sk[2])


def draw_mass(c, key, spec, pal, mass, skull):
    """The mass, painted. Three tones: base, one shaded band down the
    north-east side like every other surface here, and a highlight on the
    crown -- twenty rows of one flat colour is a bonnet however well the
    outline is cut.

    Below the brow the mass is TEMPLES: the face window is open and everything
    either side of it is still mass, down to and past the jaw.
    """
    hr = pal["hair"]
    brow = spec["brow"]
    for (y, x0, x1) in mass:
        if y < brow:
            c.row(y, x0, x1, hr[1])
            c.row(y, x1 - 2, x1, hr[2])
        else:
            wx0, wx1 = face_window(spec, skull, y)
            if wx0 - 1 >= x0:
                c.row(y, x0, wx0 - 1, hr[1])
            if wx1 + 1 <= x1:
                c.row(y, wx1 + 1, x1, hr[1])
                c.row(y, x1 - 1, x1, hr[2])
    for (y, x0, x1) in LOCKS[key]:
        c.row(y, x0, x1, hr[1])
        c.row(y, max(x0, x1 - 1), x1, hr[2])
    top = mass[0][0]
    if key == "kettle":
        # THE BAND. One ruled row of the cloth's own dark along the brow, and
        # a crease where the rag is pulled over the ear. Cloth is cut; hair is
        # not; this is the whole of the tell and it costs two rows.
        y = mass[-1][0]
        c.row(y, mass[-1][1], mass[-1][2], hr[2])
        c.row(y - 1, mass[-1][1], mass[-1][1] + 3, hr[0])
        c.px(mass[-1][1] + 1, y - 4, hr[0])
        c.px(mass[-1][1] + 2, y - 5, hr[0])
    else:
        for k in range(4):
            x = mass[k + 1][0] and mass[k + 1][1] + 2 + k
            c.row(top + 1 + k, x, x + 2 - (1 if k > 1 else 0), hr[0])
    # ...and one strand that breaks the crown, off to ONE side. Two of them,
    # placed symmetrically, is a pair of ears -- which is the same class of
    # error as drawing a brow as a bar and getting goggles.
    if key == "ember":
        c.px(mass[0][1] + 1, top - 1, hr[1])
        c.px(mass[0][1] + 2, top - 1, hr[1])
        c.px(mass[0][1] + 2, top - 2, hr[0])


def face_window(spec, skull, y):
    """The window, as a fixed inset from the SKULL'S OWN ROW.

    Measured off the skull rather than fixed in frame coordinates, so the chin
    taper narrows the face to a point instead of the temples widening to meet
    it. Two rows of chin under the mouth, for free, and the hair beside the jaw
    thickens as the jaw pulls in -- which is what hair does.
    """
    tl, tr = spec["temple"]
    for (yy, x0, x1) in skull:
        if yy == y:
            return x0 + tl, x1 - tr
    return 16 - 6, 16 + 5


def draw_face(c, key, spec, pal, skull):
    sk, hr, ey = pal["skin"], pal["hair"], pal["eyes"]
    brow = spec["brow"]
    for (y, x0, x1) in skull:
        if y < brow:
            continue
        wx0, wx1 = face_window(spec, skull, y)
        if wx1 < wx0:
            continue
        c.row(y, wx0, wx1, sk[0])
        c.px(wx1, y, sk[1])
        c.px(wx1 - 1, y, sk[1])
    # The fringe, per column. Drawn after the field, so a lifted column shows
    # forehead and a dropped one shows mass, with no special case either way.
    wx0, wx1 = face_window(spec, skull, brow)
    span = max(1, wx1 - wx0 + 1)
    for (a, b, d) in FRINGE[key]:
        for x in range(wx0 + int(round(a * span)), wx0 + int(round(b * span))):
            if d > 0:
                c.px(x, brow, hr[1])
            elif d < 0:
                c.px(x, brow - 1, sk[0])
    if spec.get("ears"):
        # An ear, on the skull's own edge and never proud of it. A bald head
        # is the figure most tempted to put skin outside its own silhouette,
        # and skin outside the silhouette is a beak.
        for (y, x0, x1) in skull:
            if spec["eye"] <= y <= spec["eye"] + 1:
                c.px(x0, y, sk[2])
                c.px(x1, y, sk[2])
    # THE EYES. The largest identity carrier a 32px figure has: Abigail spends
    # a fifth of her whole face on them. Sclera on the OUTER column -- centred,
    # two eyes with a light pixel each on the inside read as a bridge with a
    # highlight on it and the face comes out cross-eyed.
    ew, gap = spec["eye_w"], spec["eye_gap"]
    ey0 = spec["eye"]
    ex0 = 16 - (2 * ew + gap) // 2
    for n, x in enumerate((ex0, ex0 + ew + gap)):
        for k in range(3):
            y = ey0 + k
            if k == 0:
                c.row(y, x, x + ew - 1, ey[2])
                continue
            for i in range(ew):
                j = (ew - 1 - i) if n else i
                # ONE pixel of sclera, on the top row of the iris only. A full
                # column of it down a three-px eye is two white pixels each
                # side of a small face, and at 1:1 that is not an eye, it is a
                # pair of headlights -- the figures came out doll-eyed and it
                # was the first thing wrong with them at the size that counts.
                c.px(x + i, y, ey[0] if (j == 0 and k == 1) else
                     (ey[2] if k == 2 else ey[1]))
    if spec.get("beard"):
        bd = spec["beard"]
        # A beard is the bald man's SECOND substitute mass, and it is drawn
        # from under the eye rather than from under the mouth: hung off the
        # mouth it is two rows tall and reads as a chinstrap.
        for (y, x0, x1) in skull:
            if y < spec["beard_top"]:
                continue
            c.row(y, x0, x1, bd[1])
            c.row(y, x1 - 1, x1, bd[2])
        c.row(spec["jaw"] + 1, 11, 20, bd[1])
        c.row(spec["jaw"] + 2, 12, 19, bd[1])
        c.row(spec["jaw"] + 2, 18, 19, bd[2])
        c.row(spec["jaw"] + 3, 14, 17, bd[2])
    else:
        # One row of mouth, two px, and dark enough to be seen: skin shade on
        # a lit face is a smudge at 1:1, which is what the first cut drew.
        # One row only -- anything lit below a dark mouth line is teeth.
        mo = tuple((sk[2][i] + pal["line"][i] * 2) // 3 for i in range(3))
        c.row(spec["jaw"] - 1, 15, 16, mo)


def outline(c, col):
    """One flat dark line round the whole silhouette, taken from the alpha
    mask rather than drawn, so the outline is closed whatever the masses did.
    One colour for the entire figure -- both native frames do exactly that,
    and a contour per material is a dozen colours spent on an edge."""
    src = Image.new("RGBA", (W, H))
    src.paste(c.img)
    s = src.load()
    for y in range(H):
        for x in range(W):
            if s[x, y][3]:
                continue
            near = False
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < W and 0 <= ny < H and s[nx, ny][3]:
                        near = True
            if near:
                c.px(x, y, col)


def shadow(c, rx=11.5, ry=3.2):
    """A baked contact shadow, centred under the sole. Without one the figure
    floats, and centred rather than offset because it can stand anywhere."""
    cx, cy = 15.5, SOLE + 0.5
    for y in range(H):
        for x in range(W):
            if c.at(x, y)[3]:
                continue
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                c.p[x, y] = (24, 18, 26, 120)


def figure(key):
    """One front-facing 32x48 figure, feet on the bottom row.

    The order of these eight calls IS the model, which is why they are written
    out here in one place instead of emerging from wherever the drawing
    happens to sit. Read it downwards: the hair exists at line one and the
    skull is a function OF it.
    """
    spec = CHARACTERS[key]
    pal = {k: tuple(rgb(v) for v in spec[k]) if isinstance(spec[k], tuple)
           and isinstance(spec[k][0], str) else spec[k]
           for k in ("hair", "skin", "eyes", "cloth", "under", "trouser",
                     "boots")}
    pal["line"] = rgb(spec["line"])
    if spec.get("beard"):
        spec = dict(spec)
        spec["beard"] = tuple(rgb(v) for v in spec["beard"])

    mass = mass_spans(key, spec)                 # 1. the hair
    skull = skull_spans(spec, mass)              # 2. fitted inside it
    body = body_spans(spec)                      # 3. fitted under it

    c = Cel()
    draw_legs(c, spec, pal)
    draw_body(c, spec, pal, body)
    draw_arms(c, spec, pal, body)
    draw_skull(c, spec, pal, skull)
    draw_mass(c, key, spec, pal, mass, skull)
    draw_face(c, key, spec, pal, skull)
    # THE JAW LINE. There is no neck in any of the three references and there
    # is none here, so the chin sits directly on the collar -- and with two
    # lit fields touching, the head and the body read as one blob from the
    # street. One row of the figure's own outline colour under the chin is the
    # whole fix, and it costs a colour that is already on the figure.
    wx0, wx1 = face_window(spec, skull, spec["jaw"])
    c.row(spec["jaw"] + 1, wx0 - 1, wx1 + 1, pal["line"])
    bare = c.img.copy()          # before the outline, for the edge measure
    outline(c, pal["line"])
    shadow(c)
    return c.img, dict(mass=mass, skull=skull, body=body, pal=pal, spec=spec,
                       bare=bare)


# --- looking at it --------------------------------------------------------------

GROUNDS = [("dark", (38, 34, 46)), ("mid-green", (74, 108, 62)),
           ("light", (206, 198, 178))]


def hair_fraction(key):
    """What fraction of the figure is mass, by area and ON THE OUTLINE.

    The outline number is the one that matters: it is what a reader resolves
    from across a street, and it is what the reference is measured by
    (Abigail: 46.7% of her edge pixels are hair). It has to be taken BEFORE
    `outline()` runs, or every edge pixel is the contour and the answer is
    zero -- which is what the first cut of this measure reported, correctly
    and uselessly. So it asks which material OWNS each silhouette pixel.
    """
    img, meta = figure(key)
    pal = meta["pal"]
    hairset = {tuple(c) for c in pal["hair"]}
    if meta["spec"].get("beard"):
        hairset |= {tuple(c) for c in meta["spec"]["beard"]}
    p = meta["bare"].load()

    def op(x, y):
        return 0 <= x < W and 0 <= y < H and p[x, y][3] == 255

    tot = hair = out = out_hair = 0
    for y in range(H):
        for x in range(W):
            if not op(x, y):
                continue
            tot += 1
            ish = p[x, y][:3] in hairset
            hair += ish
            if any(not op(x + dx, y + dy)
                   for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                out += 1
                out_hair += ish
    data = (img.get_flattened_data() if hasattr(img, "get_flattened_data")
            else list(img.getdata()))
    hues = len({q[:3] for q in data if q[3] == 255})
    rows = [y for y in range(H) if any(op(x, y) for x in range(W))]
    mrows = [y for y in range(H)
             if any(op(x, y) and p[x, y][:3] in hairset for x in range(W))]
    return dict(px=tot, hair=hair, area=100.0 * hair / tot, hues=hues,
                outline=out, out_hair=out_hair, edge=100.0 * out_hair / out,
                rows=len(rows), mass_rows=len(mrows))


def sheet(keys):
    """One page: every figure at 1:1 and at 6x, on dark, mid-green and light.

    1:1 IS THE CHECK. A figure that only works at 6x is a drawing of a figure;
    the enlargement is for finding WHICH pixel is wrong after the small one has
    told you THAT something is.
    """
    z = 6
    pad, gap = 10, 8
    cell_w = W * z
    top = 14
    small_h = H + 6
    w = pad * 2 + len(keys) * (cell_w + gap) - gap
    h = top + small_h * len(GROUNDS) + gap + (H * z + 4) * len(GROUNDS)
    out = Image.new("RGBA", (w, h), (22, 20, 26, 255))
    imgs = {k: figure(k)[0] for k in keys}

    y = top
    for gname, gcol in GROUNDS:
        for i, k in enumerate(keys):
            x = pad + i * (cell_w + gap)
            strip = Image.new("RGBA", (W * 3 + 8, H + 4), gcol + (255,))
            for j in range(3):
                strip.alpha_composite(imgs[k], (2 + j * (W + 2), 2))
            out.alpha_composite(strip, (x, y))
        y += small_h
    y += gap
    for gname, gcol in GROUNDS:
        for i, k in enumerate(keys):
            x = pad + i * (cell_w + gap)
            plate = Image.new("RGBA", (W, H), gcol + (255,))
            plate.alpha_composite(imgs[k])
            out.alpha_composite(plate.resize((W * z, H * z), Image.NEAREST),
                                (x, y))
        y += H * z + 4
    return out


def main():
    outdir = (sys.argv[1] if len(sys.argv) > 1
              else "/home/kevin/fitrogue/.scratch/tries/hairfirst")
    os.makedirs(outdir, exist_ok=True)
    keys = list(CHARACTERS)
    for k in keys:
        img, _ = figure(k)
        img.save(os.path.join(outdir, "%s.png" % k))
        img.resize((W * 6, H * 6), Image.NEAREST).save(
            os.path.join(outdir, "%s_x6.png" % k))
    sheet(keys).save(os.path.join(outdir, "_hairfirst.png"))
    print("hair-first -- three 32x48 figures, feet on row %d" % SOLE)
    print("  %-8s %5s %6s %7s %8s %9s %6s %6s"
          % ("who", "px", "hair", "of area", "edge px", "of edge", "rows",
             "hair"))
    for k in keys:
        m = hair_fraction(k)
        print("  %-8s %5d %6d %6.1f%% %8d %8.1f%% %6d %6d   %d hues"
              % (k, m["px"], m["hair"], m["area"], m["outline"], m["edge"],
                 m["rows"], m["mass_rows"], m["hues"]))
    print("  %-8s %5d %6d %6.1f%% %8d %8.1f%% %6d %6d   %d hues"
          % ("Abigail", 285, 107, 37.5, 75, 46.7, 27, 22, 29))
    print("wrote %s" % outdir)


if __name__ == "__main__":
    main()
