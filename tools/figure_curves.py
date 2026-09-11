#!/usr/bin/env python3
"""A 32x48 overworld figure built entirely out of overlapping rounded forms.

    python3 tools/figure_curves.py

Standalone on purpose. It imports nothing from `tools/make_sprites.py`, shares
no ramp, no frame helper and no drawing function with it, and it was written
without reading that file's drawing code. Integration is somebody else's job
and integrating early is how four attempts at this came out looking like each
other.

THE ONE RULE, and it is the whole method:

    NO STRAIGHT EDGE LONGER THAN THREE PIXELS.

Concretely: take the finished figure, and for every row take the x of the
leftmost opaque pixel and the x of the rightmost. No value may repeat for more
than three rows running, on either side. `longest_run()` measures it and
`main()` raises on it, so it is a build failure rather than an intention.

WHAT THE REFERENCES ACTUALLY MEASURE. The brief said three. Three is not what
the references do, and the way to find out is to decode them rather than to
remember them. Longest run of an identical left- or right-edge x, measured off
the pixels of three frames on disk (all gitignored, none copied):

    Stardew, abigail-sheet.png crop (0,0,16,32), real alpha
        27 figure rows, 14 across. LONGEST 6 -- the left edge holds x=2 for
        rows 17-22, the side of her dress. Right edge 4.
        Run lengths {1:10, 2:7, 3:5, 4:1, 5:1, 6:1}.

    Chrono Trigger, chrono-trigger-0.png crop (31,0,45,24)
        24 rows, 14 across. LONGEST 4 -- both edges, rows 4-7, the side of his
        helmet. Run lengths {1:3, 2:7, 3:1, 4:1} per side. (His contour is
        (48,48,48) and so is the wall behind him, so a flood fill erodes it;
        these are with the outline grown back on. Eroded gives 4 as well.)

    Secret of Mana, som.png crop (112,124,128,156)
        31 rows, 16 across, grass keyed off. LONGEST 6 -- both edges, rows
        11-16, the widest part of her hair mass.
        Run lengths {1:17, 2:5, 3:5, 4:2, 6:2}.

Eroding each silhouette by a pixel -- measuring the colour instead of the
colour plus its outline -- changes none of the three maxima.

So the brief is wrong as a description and right as a direction. The MEDIAN run
in all three is one or two rows; three is about the seventy-fifth percentile;
and every one of the maxima is a single big form's apex -- a helmet, a dress, a
hair mass -- going flat because nothing else was overlapping it there. Holding
to three forbids exactly those and nothing else, so three is what this file
enforces. It is reachable here and it was not reachable in the other builder,
for a reason worth writing down: that one derives its outline by dilating the
figure 8-connected, which is a three-row minimum filter down each edge and so
adds two rows to every apex it finds -- a two-row apex measures four. Here the
contour is the silhouette's own boundary, eroded inward, so the number measured
is the number drawn.

HOW A FIGURE KEEPS ITS RUNS SHORT. Not by drawing curves. One big curve has the
longest run of all, at its own apex: a circle of diameter d holds its widest
column for about sqrt(2d) rows, so a single round 20-px form is flat for six of
them before anybody has drawn it badly. The answer is OVERLAPPING FORMS WHOSE
WIDEST ROWS ARE AT DIFFERENT HEIGHTS, so the outline is handed from one to the
next before any of them has time to go straight. Every part of this figure is
`lobe()` -- a superellipse -- and the parts are placed so that their apexes
interleave:

    hair mass      widest a third of the way down the skull
    the braid      a second hair form, on ONE side only, widest six rows lower
    skull          widest at the temple, under the hair's widest
    jaw            a smaller form overlapping the skull's bottom, so the chin
                   is round rather than cut off
    shoulders      two caps, one a row above the other, because a level pair
                   is a coat hanger
    chest          widest just under them
    waist          nothing draws the waist: it is where the chest's lower arc
                   and the hip's upper arc cross, which is a pinch
    hip            widest low, and the coat's hem flares past it
    sleeves        widest at the elbow, seven rows below the chest's widest --
                   this is the single thing that stops the torso reading as
                   one form
    cuffs          a bell at the wrist, proud of the sleeve
    thigh/calf/boot  three short forms per leg, so the ankle is a pinch and
                   the boot is a bulge

`BULGE` is the superellipse exponent and it is the one number that decides
whether the cast reads as carved or as moulded. At 2.0 every form is a true
ellipse and its widest row lasts five or six; at 1.0 they are diamonds. 1.25 is
what the measurement lands on: the widest row of a 21-px form lasts two.

WHERE TWO FORMS MEET, THE JOIN IS ABSORBED. Nothing is butted. Each part is
painted over the whole of its own footprint, in composite order, so the seam
between a sleeve and a chest is the sleeve's own curved edge lying on top of
the chest, not a boundary they share. The one line drawn deliberately at a join
is the contour under the jaw, because at forty per cent of the figure a head
with no line under it merges into the shoulders.

THE PALETTE IS THIS FILE'S OWN. The game's theme ramps were built desaturated
on purpose and both SNES references are high-chroma -- the Secret of Mana girl
carries a (232,80,184) dress against (248,216,160) skin -- so matching the
theme would have thrown away the half of the reference that is colour. Twenty
colours, four tones of nothing: three per material (lit / base / shade), one
contour, and four spent on two eyes. Counts and reasoning are in `PALETTE`.
"""
import math
import os

from PIL import Image

FW, FH = 32, 48
SOLE = FH - 1                    # the feet are on the bottom row
BULGE = 1.25                     # the superellipse exponent -- see the header
MAX_RUN = 3                      # the contract

OUT = "/home/kevin/fitrogue/.scratch/tries/curves"


# --- the palette ----------------------------------------------------------------
#
# Chosen, not inherited. Three tones per material and no more, which is what
# both SNES frames spend: the Chrono Trigger NPC is 24 colours INCLUDING the
# wall behind him and the Secret of Mana girl is 20 for a whole person. Three
# is enough for a lobe -- a lit cap, a body, a shadow -- and a fourth tone at
# this size is a blend, which is what makes a figure look moulded rather than
# carved.
#
# The hues are picked against the three grounds this gets rendered on (dark,
# light, mid-green) rather than against a mood board. Plum and copper are the
# two things a green field cannot swallow and a white page cannot bleach; the
# indigo skirt is the value anchor, dark on all three; the gold collar is the
# only saturated small object, at about four per cent of the figure, because
# one bright accent is a focus and two are a clown.
#
# CONTOUR IS NOT BLACK. Both references use a dark warm neutral -- (48,48,48)
# and (72,56,48) -- and pure black on a figure whose darkest garment tone is
# already 44 luma reads as a sticker cut out and laid on the grass.

CONTOUR = (44, 34, 46)

PALETTE = {
    #            lit               base              shade
    "skin":  [(253, 226, 190), (238, 183, 141), (191, 124, 100)],
    "hair":  [(249, 181, 88), (216, 121, 50), (150, 66, 42)],
    "coat":  [(199, 98, 132), (152, 55, 98), (95, 30, 69)],
    "skirt": [(114, 116, 180), (73, 70, 133), (43, 41, 86)],
    "boot":  [(153, 106, 68), (110, 71, 47), (69, 43, 33)],
    "gold":  [(247, 205, 100), (208, 154, 57), (147, 99, 41)],
}
SCLERA = (246, 240, 232)
IRIS = (46, 96, 122)


# --- forms ----------------------------------------------------------------------

def lobe(cx, cy, rx, up, dn, n=BULGE):
    """One soft form: a superellipse, centred on (cx, cy), `rx` wide either
    side, reaching `up` rows above the centre and `dn` below.

    Returned as {row: (x0, x1)} because rows are what a sprite is made of and
    because the union of two of these is then a one-liner.

    A pixel column belongs to the form when its own centre is inside it, which
    is what lets `cx` sit on a half-pixel and the two edges of one form move
    independently -- a form whose width is forced even steps its left edge only
    when its right edge steps too, which doubles the length of every apex.
    """
    rows = {}
    lo = int(math.floor(cy - up))
    hi = int(math.ceil(cy + dn))
    for y in range(lo, hi + 1):
        d = y - cy
        b = up if d <= 0 else dn
        t = abs(d) / float(max(0.5, b))
        if t >= 1.0:
            continue
        h = rx * (1.0 - t ** n) ** (1.0 / n)
        # The epsilon is not decoration. 6.4 - 3.4 is 3.0000000000000004 in
        # binary, so a form whose widest row lands exactly on a pixel boundary
        # loses that pixel to ceil() -- and losing the apex row turns a
        # two-row plateau into a four-row one, which is how the first cut of
        # this file failed its own check by two rows in three places.
        x0 = int(math.ceil(cx - h - 1e-9))
        x1 = int(math.floor(cx + h + 1e-9))
        if x1 >= x0:
            rows[y] = (x0, x1)
    return rows


def merge(*forms):
    """The union of a set of forms, row by row. This is what the eye reads; the
    individual forms are only how it got made."""
    out = {}
    for f in forms:
        for y, (x0, x1) in f.items():
            a, b = out.get(y, (x0, x1))
            out[y] = (min(a, x0), max(b, x1))
    return out


def clip(form, to, inset=0):
    """`form`, kept inside `to`. A collar that overhangs the shoulder it sits on
    is a bib, and a patch that overhangs the coat is a flag."""
    out = {}
    for y, (x0, x1) in form.items():
        if y not in to:
            continue
        a, b = to[y]
        x0, x1 = max(x0, a + inset), min(x1, b - inset)
        if x1 >= x0:
            out[y] = (x0, x1)
    return out


# --- painting --------------------------------------------------------------------

def paint(img, form, ramp, cap=0.50, sh=0.26, floor=1):
    """A form, lit as a form: a highlight capping its top-left and a shadow
    growing across its bottom-right.

    NOT a fixed band down each edge. A two-pixel stripe on either side of every
    row is a pair of parallel lines with a curve between them -- the shading
    says cylinder while the silhouette says sphere, and the eye believes the
    shading. Here both bands are fractions of the form's own height, so the
    light lands where the surface actually turns over, and a small form gets a
    small highlight rather than a highlight that is most of it.

    One light, from the top left, for every part of the figure. Two lights is
    two figures.
    """
    ys = sorted(form)
    if not ys:
        return
    y0, y1 = ys[0], ys[-1]
    px = img.load()
    for y in ys:
        x0, x1 = form[y]
        u = (y - y0) / float(max(1, y1 - y0))
        w = x1 - x0 + 1
        for x in range(x0, x1 + 1):
            if 0 <= x < FW and 0 <= y < FH:
                px[x, y] = ramp[1] + (255,)
        lw = int(round(w * cap * (1.0 - u) ** 1.35))
        for x in range(x0, min(x1, x0 + lw - 1) + 1):
            if 0 <= x < FW and 0 <= y < FH:
                px[x, y] = ramp[0] + (255,)
        sw = max(floor, int(round(w * sh * (0.40 + 0.80 * u))))
        for x in range(max(x0, x1 - sw + 1), x1 + 1):
            if 0 <= x < FW and 0 <= y < FH:
                px[x, y] = ramp[2] + (255,)


def dot(img, x, y, c):
    if 0 <= x < FW and 0 <= y < FH:
        img.load()[x, y] = tuple(c) + (255,)


def hline(img, y, x0, x1, c):
    for x in range(int(x0), int(x1) + 1):
        dot(img, x, y, c)


def contour(img, col=CONTOUR):
    """The outline, taken off the silhouette rather than drawn.

    Eroded INWARD -- every opaque pixel with a transparent four-neighbour, or
    one off the edge of the frame, becomes the contour -- so the silhouette
    the forms describe is the silhouette that ships, and the number
    `longest_run()` measures is the number the geometry was built to. Dilating
    outward instead would be a three-row minimum filter down each edge and
    would add two rows to every apex in the figure.

    One colour for the whole outline, which is what both references do; a
    contour that takes a darker step of each material is sixteen more colours
    and a jaw line that does not match the silhouette it runs into.
    """
    px = img.load()
    edge = []
    for y in range(FH):
        for x in range(FW):
            if px[x, y][3] != 255:
                continue
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if not (0 <= nx < FW and 0 <= ny < FH) or px[nx, ny][3] != 255:
                    edge.append((x, y))
                    break
    for (x, y) in edge:
        px[x, y] = tuple(col) + (255,)


def seam(img, form, col=CONTOUR):
    """A contour where two masses meet each other instead of the air.

    Only under the jaw, and only where `contour()` has not already drawn it: at
    forty per cent of the figure a head with no line under it merges into the
    shoulders and the whole top half is one blob. Drawn on the last row of the
    form and only where the pixel below it is opaque, so it can never double up
    into a two-pixel line.
    """
    ys = sorted(form)
    if not ys:
        return
    y = ys[-1]
    x0, x1 = form[y]
    px = img.load()
    for x in range(x0, x1 + 1):
        if 0 <= x < FW and y + 1 < FH and px[x, y][3] == 255 \
                and px[x, y + 1][3] == 255:
            px[x, y] = tuple(col) + (255,)


# --- the figure ------------------------------------------------------------------
#
# One person, invented here rather than borrowed: a woman in a heavy quilted
# coat with a copper braid over her left shoulder. She exists because of what
# the rule needs to be shown on, and every choice below is a form that has to
# bulge or pinch somewhere:
#
#   the braid       an asymmetric second hair mass. It is the cheapest thing in
#                   the figure and it does the most work -- it breaks the head's
#                   outline on one side only, which is worth more than any
#                   amount of symmetrical detail, and it is why the left and
#                   right edges of this figure never go flat together
#   a quilted coat  because a coat with a waist is two forms crossing, and the
#                   pinch between them is the thesis
#   belled cuffs    a bulge at the wrist under a narrower sleeve, so the arm
#                   has three widths down its length instead of one
#   tall boots      a bulge under an ankle pinch, which is the same trick again
#                   at the bottom of the figure where a pair of straight stubs
#                   would otherwise give the longest run on the whole sprite


def build_figure():
    """The figure, as named forms in one dict. The composite order lives in
    `render()`; this is only the geometry.

    EVERY CENTRE ROW IS AN INTEGER and every form's reach above its centre
    differs from its reach below. Both are contract, not style: a form whose
    apex falls between two rows gives those two rows the same edge and never
    reaches its own widest column, which turns a one-row apex into a two-row
    one; and a form with equal reach up and down pairs its rows off
    symmetrically, so every edge value appears exactly twice. The two
    together are worth more to the measured number than any amount of
    re-shaping, and the first cut of this file had neither.
    """
    # --- the head. Nineteen rows of a forty-six-row figure, 41%. The three
    # references sit at 46%, 52% and 57%; a quarter of the figure, which is
    # what a realistic proportion gives, reads as an adult from a distance and
    # as nothing at all up close.
    hair = lobe(15.4, 8, 9.8, 6.2, 8.6)
    skull = lobe(15.5, 12, 8.4, 7.0, 6.6)
    jaw = lobe(15.7, 18, 6.4, 4.6, 3.6)
    head = merge(skull, jaw)
    # The braid. One side only, and its widest row is six below the hair
    # mass's, so the left edge of the head is handed from one form to the
    # other halfway down. Two of these, symmetrically placed, are a pair of
    # ears. The lower half of it lies ON the coat rather than beside it --
    # a braid that stays outside the shoulder all the way down holds the same
    # edge for five rows, which is how this failed its own check the first
    # time.
    braid = lobe(7.2, 14, 3.5, 3.4, 4.4)
    braid_lo = lobe(8.4, 21, 3.0, 3.0, 4.0)
    # ...and a shorter fall of hair on the other side, deliberately unequal.
    fall = lobe(23.2, 12, 3.2, 3.4, 4.0)

    # --- the torso. Two shoulder caps a row apart, because a level pair is a
    # coat hanger. Then a chest, a core and a hip whose arcs cross: the waist
    # is not drawn anywhere, it is where the chest's lower arc and the hip's
    # upper arc are both on their way down.
    sh_l = lobe(10.2, 24, 5.2, 3.0, 4.2)
    sh_r = lobe(20.8, 25, 5.2, 3.2, 4.0)
    chest = lobe(15.5, 26, 9.8, 4.4, 6.2)
    core = lobe(15.5, 32, 7.8, 6.4, 5.6)
    hip = lobe(15.5, 37, 9.2, 5.2, 2.6)
    flare = lobe(15.5, 39, 10.0, 3.0, 1.6)
    torso = merge(sh_l, sh_r, chest, core, hip, flare)

    # --- the arms. THREE FORMS DOWN EACH, so the arm has three widths instead
    # of one: a sleeve widest at the elbow -- three rows below the chest's
    # widest, which is the single thing that stops the torso reading as one
    # form -- a forearm tucked in, and a cuff belling out again at the wrist.
    # A sleeve of one width is a stick, and a stick is a straight edge however
    # round its two ends are.
    arm_l = merge(lobe(6.8, 29, 3.4, 4.2, 4.6), lobe(7.6, 35, 2.9, 3.0, 3.4))
    arm_r = merge(lobe(24.4, 30, 3.3, 4.4, 4.2), lobe(23.6, 35, 2.8, 3.0, 3.2))
    cuff_l = lobe(6.9, 38, 3.3, 2.4, 2.0)
    cuff_r = lobe(24.5, 37, 3.2, 2.4, 2.0)
    hand_l = lobe(7.4, 40, 2.4, 1.8, 2.0)
    hand_r = lobe(24.0, 39, 2.3, 1.8, 2.0)

    # --- the legs. Three forms each as well, so the knee is a bulge, the
    # ankle a pinch and the boot a bulge -- a pair of straight stubs would
    # otherwise be the longest run on the whole sprite. The two legs are a row
    # out of step with each other, which is free and stops the bottom of the
    # figure being a mirror.
    def leg(cx, dy):
        return merge(lobe(cx, 41 + dy, 3.5, 1.8, 2.8),
                     lobe(cx - 0.3, 44 + dy, 2.9, 2.2, 2.4),
                     lobe(cx - 0.6, 46, 3.6, 2.0, 1.8))

    return dict(hair=hair, skull=skull, jaw=jaw, head=head, braid=braid,
                braid_lo=braid_lo, fall=fall, torso=torso, chest=chest,
                hip=hip, flare=flare, arm_l=arm_l, arm_r=arm_r,
                cuff_l=cuff_l, cuff_r=cuff_r, hand_l=hand_l, hand_r=hand_r,
                boot_l=lobe(10.6, 46, 3.6, 2.0, 1.8),
                boot_r=lobe(18.4, 46, 3.6, 2.0, 1.8),
                leg_l=leg(11.2, 0), leg_r=leg(19.0, 1))


def face(img, F):
    """Two eyes and two pixels of mouth. No nose, no brow, no cheek.

    In two of the three references the face is a flat bright field with dark
    punched into it and nothing else at all, and that maximum local contrast
    is the whole reason a face reads at 1:1. Every feature added to a head
    this size turns into something else: a full-width band is eyewear, a lit
    row under a dark mouth is teeth, a raised half-mouth is a moustache, a row
    of shade beside a nose is a muzzle.

    Two rows of eye, not three. Three is Stardew's and Stardew's face is
    fourteen rows of a twenty-seven-row figure with the eye in the middle of
    it; here the face below the fringe is seven rows, and a three-row eye in
    seven rows of face leaves no cheek, no chin and nothing for the mouth to
    sit on -- which is what the first cut looked like, a dark band across a
    head. The sclera is on the OUTER column: two eyes with their light pixel
    on the inside read as a nose bridge with a highlight on it, and the face
    comes out cross-eyed.
    """
    ey = 15
    for x0, mirror in ((11, False), (18, True)):
        hline(img, ey, x0, x0 + 2, CONTOUR)                 # the lash
        for x in range(x0, x0 + 3):
            j = (x0 + 2 - x) if mirror else (x - x0)
            dot(img, x, ey + 1, SCLERA if j == 0 else IRIS)
    hline(img, 19, 15, 16, PALETTE["skin"][2])              # the mouth, one row


def render():
    """One front-facing figure, 32x48, feet on the bottom row.

    THE COMPOSITE ORDER IS THE MODEL, so it is written out here in one place
    rather than emerging from wherever the calls happen to sit: the far side
    of the hair and the far arm first, then the legs, then the coat over the
    top of both, then the near arm, then the head, then the hair, then the
    face. Each part is painted over the whole of its own footprint, so every
    seam is one curved form lying on another rather than two forms meeting at
    a shared edge -- which is the whole of what "the join is absorbed" means.
    """
    img = Image.new("RGBA", (FW, FH), (0, 0, 0, 0))
    F = build_figure()
    P = PALETTE

    paint(img, F["fall"], P["hair"], cap=0.45, sh=0.20)
    paint(img, F["arm_r"], P["coat"], cap=0.35)
    paint(img, F["cuff_r"], P["coat"], cap=0.40)
    paint(img, F["hand_r"], P["skin"], cap=0.45)

    paint(img, F["leg_r"], P["skirt"], cap=0.35)
    paint(img, F["leg_l"], P["skirt"], cap=0.42)
    # The boot is its own form over the bottom of the leg rather than the end
    # of the leg: in all three references the foot is a separate lump under
    # the stub, and it is what stops two trouser columns reading as the legs
    # of a chair.
    paint(img, clip(F["boot_r"], F["leg_r"]), P["boot"], cap=0.35)
    paint(img, clip(F["boot_l"], F["leg_l"]), P["boot"], cap=0.42)

    paint(img, F["torso"], P["coat"], cap=0.42)
    # A value break at the hip, in the other ramp. Without one the figure is a
    # single column of cloth from the collar to the boot, which at this size
    # is a bollard in a hat.
    paint(img, {y: v for y, v in F["torso"].items() if y >= 40}, P["skirt"],
          cap=0.35)
    # The quilting: two seams following the form rather than ruled down it,
    # because at this size a lapel is its seams. They are the coat's own dark,
    # so they cost no colour.
    for y, (x0, x1) in sorted(F["torso"].items()):
        if 26 <= y <= 39:
            dot(img, x0 + int(round((x1 - x0) * 0.30)), y, P["coat"][2])
            dot(img, x0 + int(round((x1 - x0) * 0.70)), y, P["coat"][2])
    # The collar. ONE saturated small object and no more -- two of them and
    # the figure is a clown -- and it is clipped to the shoulders it sits on,
    # because a collar that overhangs them is a bib.
    paint(img, clip(lobe(15.5, 22, 6.2, 1.6, 2.4), F["torso"]), P["gold"],
          cap=0.40)

    paint(img, F["arm_l"], P["coat"], cap=0.42)
    paint(img, F["cuff_l"], P["coat"], cap=0.45)
    paint(img, F["hand_l"], P["skin"], cap=0.45)

    # The head goes on last of the masses, over the shoulders it sits on, so
    # the jaw is one form lying on another and not a join between two.
    paint(img, F["head"], P["skin"], cap=0.56, sh=0.17)
    # The hair over the whole crown, and the face is what is left below its
    # fringe. Painted the other way round -- as a cap laid on a dome -- it is
    # a helmet, which is a failure this game has already paid for once.
    paint(img, {y: v for y, v in F["hair"].items() if y <= 12}, P["hair"],
          cap=0.44, sh=0.20)
    # ...and down the sides past the eye, narrowing to the chin. Held at full
    # width all the way down, two solid bars beside a face are a pair of
    # headphones.
    for y, (x0, x1) in sorted(F["head"].items()):
        if y < 13:
            continue
        w = max(0, int(round(2.3 * (1.0 - (y - 13) / 8.0))))
        for x in range(x0, x0 + w):
            dot(img, x, y, P["hair"][1])
        for x in range(x1 - w + 1, x1 + 1):
            dot(img, x, y, P["hair"][2])
    paint(img, F["braid_lo"], P["hair"], cap=0.38, sh=0.22)
    paint(img, F["braid"], P["hair"], cap=0.42, sh=0.22)
    # Two ties on the braid, in the collar's gold, so the one accent colour
    # appears twice down the figure and it has a rhythm instead of one bright
    # slab.
    for y in (19, 24):
        if y in F["braid_lo"]:
            x0, x1 = F["braid_lo"][y]
            hline(img, y, x0 + 1, x1, P["gold"][1])

    face(img, F)
    seam(img, F["head"])
    contour(img)
    return img


# --- the check --------------------------------------------------------------------

def edges(img):
    px = img.load()
    out = []
    for y in range(FH):
        xs = [x for x in range(FW) if px[x, y][3] == 255]
        out.append((min(xs), max(xs)) if xs else None)
    return out


def longest_run(img):
    """The contract, measured: every run of rows sharing a left-edge x or a
    right-edge x, the longest of them, and a histogram of all of them.

    Reported as a list rather than a single number because a figure that fails
    usually fails in two or three places at once, and knowing WHICH form went
    flat is the difference between fixing it and nudging numbers.
    """
    e = edges(img)
    runs = []
    for i in (0, 1):
        cur, prev, start = 0, None, 0
        for y, row in enumerate(e + [None]):
            v = None if row is None else row[i]
            if v is not None and v == prev:
                cur += 1
            else:
                if cur:
                    runs.append((cur, "left" if i == 0 else "right",
                                 start, start + cur - 1, prev))
                cur, start = (1, y) if v is not None else (0, y)
            prev = v
    runs.sort(reverse=True)
    hist = {}
    for r in runs:
        hist[r[0]] = hist.get(r[0], 0) + 1
    return runs[0][0], runs, dict(sorted(hist.items()))


# --- output ------------------------------------------------------------------------

GROUNDS = [("dark", (26, 24, 34)), ("light", (232, 228, 216)),
           ("green", (86, 132, 66))]


def on(img, bg, zoom=1, pad=2):
    """The figure on one flat ground, at one zoom. Flat and not a texture: this
    is a legibility test and a texture would let a bad silhouette hide in it."""
    w, h = (FW + pad * 2) * zoom, (FH + pad * 2) * zoom
    out = Image.new("RGB", (w, h), bg)
    big = img if zoom == 1 else img.resize((FW * zoom, FH * zoom), Image.NEAREST)
    out.paste(big, (pad * zoom, pad * zoom), big)
    return out


def strip(img, zoom):
    """All three grounds in one picture, so the eye can compare them without
    moving between files."""
    tiles = [on(img, bg, zoom) for _n, bg in GROUNDS]
    w = sum(t.width for t in tiles)
    out = Image.new("RGB", (w, tiles[0].height), (0, 0, 0))
    x = 0
    for t in tiles:
        out.paste(t, (x, 0))
        x += t.width
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    img = render()

    run, runs, hist = longest_run(img)
    where = runs[0][1:]
    e = edges(img)
    rows = [y for y, v in enumerate(e) if v]
    wide = max(v[1] - v[0] + 1 for v in e if v)
    hues = len({p[:3] for p in img.getdata() if p[3] == 255})
    print("figure   rows %d..%d (%d)   %d px across   %d opaque pixels"
          % (rows[0], rows[-1], len(rows), wide,
             sum(1 for p in img.getdata() if p[3] == 255)))
    print("colours  %d opaque" % hues)
    print("run      LONGEST %d  (%s edge, rows %d-%d at x=%s)"
          % (run, where[0], where[1], where[2], where[3]))
    print("         run lengths %s" % hist)
    for r in runs:
        if r[0] > MAX_RUN:
            print("         OVER: %d rows, %s edge, rows %d-%d at x=%s"
                  % r)
    print("         references: Stardew 6, Secret of Mana 6, Chrono Trigger 4")
    print()
    for y, v in enumerate(e):
        if v:
            print("   %2d  %2d..%2d  %s%s" % (y, v[0], v[1], " " * v[0],
                                              "#" * (v[1] - v[0] + 1)))

    img.save(os.path.join(OUT, "figure.png"))
    strip(img, 1).save(os.path.join(OUT, "figure_1x.png"))
    strip(img, 6).save(os.path.join(OUT, "figure_6x.png"))
    print()
    print("wrote figure.png, figure_1x.png, figure_6x.png -> %s" % OUT)

    if run > MAX_RUN:
        raise SystemExit(
            "FIGURE CONTRACT FAILED: longest straight edge %d rows, max %d "
            "-- %d run(s) over: %s"
            % (run, MAX_RUN, sum(1 for r in runs if r[0] > MAX_RUN),
               "; ".join("%d rows %s %d-%d x=%s" % r
                         for r in runs if r[0] > MAX_RUN)))


if __name__ == "__main__":
    main()
