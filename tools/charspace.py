#!/usr/bin/env python3
"""A high-temperature 32x48 character sprite generator whose product is SPREAD.

    from tools import charspace
    p = charspace.sample(random.Random(7))      # a random point in the space
    im = charspace.draw(p)                      # 32x48 RGBA, feet on row 47

    c = charspace.parse_prompt("a cute girl next door, blonde hair big eyes")
    p = charspace.sample(rng, constraints=c)    # ...or a point the user asked for
    p = charspace.sample(rng, bias=liked)       # ...or one near what they liked

WHY THIS FILE EXISTS. Six rounds of hand-authored figures each came back
"closer, but not it", and the diagnosis every time was the same: not enough
variance to show by example what was wanted. So this is not an attempt at the
right character. It is an attempt at a SPACE wide enough to contain it, to be
swiped through dating-app style until the preferences fall out of the data.
Every design decision below is therefore resolved in favour of variance, and
a figure that is merely odd is a cheaper failure here than a figure that is
the two hundredth copy of the same person in a different hat.

THE CONSTRUCTION GRAMMAR IS ITSELF AN AXIS, and it is the axis that buys the
most. `tools/figure_silhouette.py`, `tools/figure_hairfirst.py`,
`tools/figure_facefirst.py` and `tools/figure_curves.py` are four genuinely
different theories of how a 32x48 person is built, each written on a blank
sheet, and each one hard-codes exactly one character. What is taken from them
here is the THEORY, re-expressed as a parameter, so that any of the four can
be drawn -- and, more usefully, so head construction and body construction and
limb construction and shading can come from DIFFERENT theories in the same
figure. The four files are not imported: each is a finished drawing of one
person with its numbers fused into its prose, and calling into them would give
four points rather than the continuum between them.

    span    (from figure_silhouette)  the outline is a width-vs-height profile
                                      and every feature is cut out of it, so
                                      nothing a feature does can push the
                                      silhouette around
    mass    (from figure_hairfirst)   the hair silhouette is authored first and
                                      the skull is fitted inside and behind it,
                                      so the head's outline is hair, not skull
    derive  (from figure_facefirst)   one eye is the atom, the face is derived
                                      from it, the head from the face, and the
                                      body is whatever rows are left over -- so
                                      the head's height is an OUTPUT
    lobe    (from figure_curves)      overlapping superellipses whose widest
                                      rows sit at different heights, so the
                                      outline is handed from form to form

WHERE THE DISTRIBUTION SITS, which is a separate question from where the space
reaches. The first swipe run scored 18 rights in 149 -- 12% -- on a uniform
sample, with the note "I think I've discovered I prefer when they have big
eyes, somewhat reasonable proportions, and realistic hair/clothes". Sampling
seventy axes uniformly puts every draw in a corner of a seventy-dimensional
box and almost every corner of that box is not a person, so `_PLAUSIBLE` is a
second, narrower value for each axis and `realism` is the dial between them.
It defaults to 0.75 and it is a PER-FIGURE roll, so three quarters of a sheet
is plausible people and the last quarter is genuinely strange -- the tails are
not deleted, because the 30% pure-random channel exists precisely so a taste
nobody predicted can still be found.

WHAT DRAW() PROMISES. Under 25 ms, because a server pre-generates thousands of
these; deterministic given its params, because a params dict is the only
record of a figure the user liked and it has to be redrawable from that alone;
and JSON-serialisable params, for the same reason. Any incidental randomness
inside `draw` is drawn from `params["seed"]` through `_j` below, which is a
hash rather than a stream, so adding a call site later cannot renumber the
ones that already exist and silently redraw every saved figure.

    python3 tools/charspace.py            # 200-figure spread report + sheet
"""
import colorsys
import json
import math
import os
import random
import zlib

from PIL import Image

FW, FH = 32, 48
SOLE = 47                   # the feet land on the bottom row of the cell
CX = 15.5                   # the centre line, between columns 15 and 16
CLEAR = (0, 0, 0, 0)


# ================================================================= the axes ====
#
# One table drives three things that would otherwise drift apart: the pure
# random sampler, the bias-annealed perturbation sampler, and the AXES dict the
# swipe UI shows. A numeric axis carries the sigma its perturbation uses, and a
# categorical axis carries the probability that a perturbation resamples it --
# so "how far is near" is stated once, per axis, where it can be tuned by
# somebody watching the swipes rather than buried in the sampler.

class _Ax(object):
    def __init__(self, kind, desc, lo=None, hi=None, sigma=None,
                 choices=None, p=0.5, mut=0.25, quant=None):
        self.kind = kind        # "num", "int", "cat" or "bool"
        self.desc = desc
        self.lo, self.hi = lo, hi
        # A sigma expressed as a fraction of the axis range, so widening an
        # axis later does not also quietly tighten its annealing.
        self.sigma = sigma if sigma is not None else 0.18
        self.choices = choices
        self.p = p              # for bools, the probability of True
        self.mut = mut          # for cats and bools, the resample probability
        self.quant = quant      # snap numeric draws to this grid, or None


def _n(desc, lo, hi, sigma=0.18):
    return _Ax("num", desc, lo=lo, hi=hi, sigma=sigma)


def _i(desc, lo, hi, sigma=0.25):
    return _Ax("int", desc, lo=lo, hi=hi, sigma=sigma)


def _c(desc, choices, mut=0.25):
    return _Ax("cat", desc, choices=list(choices), mut=mut)


def _b(desc, p=0.5, mut=0.25):
    return _Ax("bool", desc, p=p, mut=mut)


# The grammars, named once so the sampler and the four builders cannot disagree
# about what exists.
GRAMMARS = ("span", "mass", "derive", "lobe")

SPEC = [
    # --- construction -----------------------------------------------------
    ("grammar", _c("construction grammar for the body silhouette", GRAMMARS,
                   mut=0.35)),
    # The head can be built by a different theory than the body, which is the
    # cheapest hybridisation available and the one that most reliably produces
    # a figure none of the four source files could have drawn.
    ("head_grammar", _c("construction grammar for the head (may differ from "
                        "the body's, which hybridises the four theories)",
                        GRAMMARS, mut=0.35)),
    ("limb_style", _c("how arms and hands are constructed",
                      ("inset", "blocky", "lobed", "proud"))),
    ("leg_style", _c("how legs and feet are constructed",
                     ("stub", "lobed", "tapered"))),
    ("shading", _c("how a colour mass is lit",
                   ("none", "flat2", "flat3", "formlit", "banded"))),
    ("light", _c("light direction", ("NW", "NE", "N", "flat"))),

    # --- proportion -------------------------------------------------------
    ("height_rows", _i("total figure height in rows, crown to sole", 30, 46)),
    ("build", _n("slender (0) to broad (1); sets shoulder width", 0.0, 1.0)),
    ("head_frac", _n("head height as a fraction of total height "
                     "(ignored by the derive grammar, which outputs it)",
                     0.20, 0.50)),
    ("head_shoulder", _n("head width / shoulder width", 0.62, 1.35)),
    ("shoulder_slope", _n("square (0) to sloped (1) shoulders", 0.0, 1.0)),
    ("waist_pinch", _n("how far the waist pulls in below the chest",
                       0.0, 1.0)),
    ("hip_flare", _n("how far the garment flares out again at the hip",
                     0.0, 1.0)),
    ("leg_frac", _n("visible leg height as a fraction of total height",
                    0.10, 0.32)),
    ("leg_gap", _i("columns of air between the two legs", 0, 4)),
    ("neck", _i("rows of visible neck between jaw and shoulder", 0, 2)),

    # --- the head's mass --------------------------------------------------
    ("hair_shape", _c("silhouette of the hair mass",
                      ("round", "bob", "long", "spiky", "topknot", "wild",
                       "flat", "mohawk", "curls", "tail", "bald", "pigtails"),
                      mut=0.3)),
    ("hair_mass", _n("how far the mass stands proud of the skull", 0.0, 1.0)),
    ("hair_len", _n("how far the mass falls past the jaw", 0.0, 1.0)),
    ("hair_asym", _n("asymmetry of the mass, -1 heavy left to +1 heavy right",
                     -1.0, 1.0)),
    ("hair_rise", _i("rows the mass stands above the skull", 0, 6)),
    ("fringe", _c("the mass's edge across the forehead",
                  ("none", "step", "two_notch", "peak", "swept", "high"))),
    ("hair_shine", _b("a highlight on the crown", 0.6)),
    ("headwear", _c("what is on the head, if anything",
                    ("none", "none", "band", "cap", "brim", "hood", "wrap",
                     "helm", "horns", "crown", "ears"), mut=0.3)),
    ("headwear_carries", _b("the headwear, not the hair, owns the outline",
                            0.45)),

    # --- the face ---------------------------------------------------------
    ("face_w", _n("face window width as a fraction of the skull", 0.56, 0.92)),
    ("eye_w", _i("one eye's width in px", 2, 5)),
    ("eye_h", _i("rows of iris under the lash", 1, 4)),
    ("eye_gap", _i("bare skin between the two eyes", 1, 6)),
    ("eye_style", _c("how an eye is drawn",
                     ("dot", "sclera_out", "full_iris", "wide", "closed",
                      "beady"))),
    ("eye_hue", _n("iris hue, 0..1 round the wheel", 0.0, 1.0, sigma=0.10)),
    ("eye_y", _n("eyes high (0) or low (1) in the face", 0.0, 1.0)),
    ("brow", _c("brow treatment",
                ("none", "flat", "angled", "thick", "raised_one", "worried"))),
    ("nose", _c("nose treatment", ("none", "none", "dot", "shade", "long"))),
    ("mouth", _c("mouth treatment",
                 ("none", "line", "small", "wide", "open", "smirk"))),
    ("age", _n("young (0) to old (1); adds a brow line and pales the hair",
               0.0, 1.0)),
    ("facial_hair", _c("facial hair",
                       ("none", "none", "none", "stubble", "moustache",
                        "goatee", "beard", "long_beard", "chops"), mut=0.3)),

    # --- garments ---------------------------------------------------------
    ("top", _c("the main upper garment",
               ("tunic", "coat", "robe", "vest", "shirt", "armour", "dress",
                "poncho", "smock"), mut=0.3)),
    ("top_len", _n("where the upper garment's hem falls, waist (0) to "
                   "ankle (1)", 0.0, 1.0)),
    ("sleeve", _c("sleeve length and shape",
                  ("none", "short", "long", "puff", "banded"))),
    ("collar", _c("collar treatment",
                  ("none", "band", "wide", "high", "fur", "ruff", "v"))),
    ("belt", _c("belt treatment", ("none", "thin", "wide", "sash", "double"))),
    ("apron", _b("an apron over the front of the garment", 0.2)),
    ("cloak", _c("a cloak behind the figure",
                 ("none", "none", "none", "half", "full", "cape"), mut=0.3)),
    ("lower", _c("the lower garment",
                 ("trousers", "trousers", "skirt", "long_skirt", "shorts",
                  "bare"), mut=0.3)),
    ("boots", _c("footwear",
                 ("none", "low", "tall", "cuffed", "pointed", "wrapped"))),
    ("pattern", _c("a repeating mark on the main garment",
                   ("none", "none", "hem_band", "stripe", "quilt", "cross",
                    "trim", "dots", "patch"))),

    # --- carried things ---------------------------------------------------
    ("prop", _c("a carried object, which is allowed to break the silhouette",
                ("none", "none", "none", "staff", "satchel", "lantern",
                 "book", "sword", "basket", "pack", "broom", "hammer"),
               mut=0.3)),
    ("prop_side", _b("the prop is on the figure's right", 0.5)),
    ("accessory", _c("a worn accessory",
                     ("none", "none", "scarf", "necklace", "earring", "pouch",
                      "gloves", "bracers", "pauldron", "glasses"), mut=0.3)),

    # --- colour -----------------------------------------------------------
    ("palette", _c("how the garment hues relate to each other",
                   ("analogous", "complementary", "triad", "split",
                    "mono_accent", "dark_bright", "earth", "high_chroma",
                    "pastel", "muted", "two_tone", "chaos"), mut=0.3)),
    ("base_hue", _n("the hue everything else is placed against",
                    0.0, 1.0, sigma=0.12)),
    ("sat", _n("overall saturation", 0.0, 1.0)),
    ("value", _n("overall lightness of the garments", 0.0, 1.0)),
    ("sat_spread", _n("how far saturation varies between materials",
                      0.0, 1.0)),
    ("val_spread", _n("how far lightness varies between materials",
                      0.0, 1.0)),
    ("skin_hue", _n("skin hue within the human band", 0.0, 1.0, sigma=0.15)),
    ("skin_sat", _n("skin saturation", 0.0, 1.0)),
    ("skin_val", _n("skin lightness, and it is a genuinely wide range",
                    0.0, 1.0)),
    ("skin_exotic", _b("a non-human skin hue -- grey, green, blue, violet",
                       0.08, mut=0.15)),
    ("hair_hue", _n("hair hue, 0..1 round the wheel", 0.0, 1.0, sigma=0.12)),
    ("hair_val", _n("hair lightness: 0 is black, 1 is platinum. Its own axis "
                    "because blonde and black are the same hue at different "
                    "values, and one knob driving both can express neither",
                    0.0, 1.0)),
    ("hair_natural", _b("hair is a natural colour rather than anything",
                        0.72)),
    ("accent_hue_off", _n("where the one hot accent sits relative to base",
                          0.0, 1.0, sigma=0.15)),
    ("colour_blocks", _i("FLOOR on the number of distinct colour-blocked "
                         "elements; the references have 5-7 and the figures "
                         "this replaces had 3-4", 5, 10)),
    ("outline_mode", _c("the contour colour",
                        ("dark", "dark", "tinted", "light", "none"))),
    ("outline_place", _c("the contour sits inside the silhouette or grows it",
                         ("inside", "outside"))),
    ("quant", _c("colour grid the palette snaps to", ("1", "4", "8"))),
    ("shadow", _b("a baked contact shadow under the sole", 0.4)),
    ("jaw_seam", _b("one dark row under the chin so the head is not welded "
                    "to the shoulders", 0.7)),
]

AXES = dict((k, a.desc) for (k, a) in SPEC)
_AX = dict(SPEC)


# ========================================================== plausible priors ====
#
# THIS TABLE IS THE TUNING SURFACE, and it exists because the first swipe run
# came back at 12% -- eighteen rights in a hundred and forty-nine -- with the
# note "I think I've discovered I prefer when they have big eyes, somewhat
# reasonable proportions, and realistic hair/clothes". The axes were not wrong;
# the PRIOR was. Sampling sixty-nine axes uniformly puts almost every draw in a
# corner of a sixty-nine-dimensional box, and almost every corner of that box is
# not a person.
#
# So this is a second, narrower value for each axis that needs one, and it is
# deliberately a separate table rather than a change to the axis ranges: the
# ranges are what the space CAN reach and this is where it usually sits, and
# whoever tunes against the next thousand swipes needs to edit one block rather
# than hunt through sixty-nine declarations.
#
#   numeric / int axis  ->  (lo, hi), a sub-band of the full range
#   categorical axis    ->  a list, with repeats used as weights
#   boolean axis        ->  a probability
#
# An axis absent from this table is drawn from its full range either way, which
# is the right default for anything that is a taste rather than a plausibility:
# base_hue, skin_hue, the four grammars, the light direction.
#
# Where the weak per-axis signal from the 149 swipes pointed somewhere, it is
# followed and marked -- but n is 7 to 14 per value, so these are hints and the
# bands around them are wide enough to be argued out of by the next run.

_PLAUSIBLE = {
    # --- proportion. "Somewhat reasonable" is the whole of the note. -------
    "height_rows": (34, 42),          # swipe hint: 36 went 5/11 vs 12% base
    "build": (0.20, 0.70),
    # The references measure 0.52, 0.57 and 0.59 head-to-figure. A quarter is
    # the anatomically honest number and it reads as nothing at 1:1, and it is
    # also what starves the face window that a big eye has to sit in.
    "head_frac": (0.34, 0.46),
    "head_shoulder": (0.85, 1.15),
    "leg_frac": (0.16, 0.26),
    "shoulder_slope": (0.15, 0.70),
    "waist_pinch": (0.10, 0.70),
    "hip_flare": (0.05, 0.55),
    "leg_gap": (1, 3),
    "neck": (0, 1),

    # --- hair. The swipe hint here is the surprising one: hair_mass=0.0 went
    # 5/11, which is the opposite of what six rounds of hand-drawn figures
    # assumed. A thin temple also widens the face window, which is most of how
    # an eye gets to be big, so the two preferences agree.
    "hair_shape": ("round", "round", "bob", "bob", "long", "long", "tail",
                   "tail", "pigtails", "curls", "flat", "bald"),
    "hair_mass": (0.0, 0.35),
    "hair_len": (0.0, 0.70),
    "hair_asym": (-0.40, 0.25),       # swipe hint: -0.1 went 3/7
    "hair_rise": (0, 2),
    "fringe": ("none", "step", "two_notch", "swept", "swept", "peak"),
    "hair_natural": 0.92,
    "hair_val": (0.08, 0.95),
    "headwear": ("none",) * 7 + ("band", "cap", "brim", "hood", "wrap"),
    "headwear_carries": 0.30,

    # --- the face. BIG EYES, said in the only place it can be said: the eye
    # is wide, tall, close-set and sitting in a face window that is most of the
    # skull rather than a porthole in it.
    "face_w": (0.70, 0.88),
    "eye_w": (3, 5),
    "eye_h": (2, 3),
    "eye_gap": (2, 3),
    "eye_style": ("sclera_out", "sclera_out", "full_iris", "full_iris",
                  "wide", "dot"),
    "eye_y": (0.45, 0.95),
    "brow": ("none", "none", "flat", "angled", "raised_one", "worried"),
    "nose": ("none", "none", "none", "dot"),
    "mouth": ("line", "line", "small", "smirk", "wide", "none"),
    "age": (0.05, 0.55),
    "facial_hair": ("none",) * 6 + ("stubble", "moustache", "goatee", "beard"),

    # --- clothes. "Realistic" here means a garment that exists and a hem that
    # falls where a hem falls, not a narrower palette: the colour axes are a
    # taste and are left alone apart from their saturation and spread.
    "top": ("tunic", "tunic", "shirt", "shirt", "coat", "coat", "dress",
            "vest", "smock", "robe"),
    "top_len": (0.25, 0.80),
    "sleeve": ("long", "long", "short", "short", "none", "puff"),
    "collar": ("none", "none", "band", "v", "wide", "high"),
    "belt": ("none", "thin", "thin", "wide", "sash"),
    "apron": 0.10,
    "cloak": ("none",) * 8 + ("half", "cape"),
    "lower": ("trousers", "trousers", "trousers", "skirt", "skirt",
              "long_skirt", "shorts"),
    "boots": ("low", "low", "tall", "cuffed", "pointed", "none"),
    "pattern": ("none", "none", "none", "trim", "hem_band", "stripe", "quilt"),

    # --- carried things. Joke props and antennae get rare rather than deleted.
    # swipe hint: prop=staff went 4/10, which is the only prop with a signal.
    "prop": ("none",) * 6 + ("staff", "staff", "satchel", "book", "basket",
                             "lantern", "broom", "sword"),
    "accessory": ("none",) * 6 + ("scarf", "necklace", "pouch", "gloves",
                                  "bracers", "glasses"),

    # --- colour ------------------------------------------------------------
    "palette": ("analogous", "analogous", "earth", "earth", "muted",
                "complementary", "split", "triad", "dark_bright",
                "mono_accent", "pastel"),
    "sat": (0.12, 0.62),
    "value": (0.28, 0.78),
    "sat_spread": (0.10, 0.55),
    "val_spread": (0.0, 0.45),        # swipe hint: 0.0 went 3/8
    "skin_sat": (0.25, 0.80),
    "skin_val": (0.35, 0.95),         # swipe hint: 0.8 went 5/14
    "skin_exotic": 0.01,
    "colour_blocks": (5, 8),
    "outline_mode": ("dark",) * 5 + ("tinted", "light", "none"),
    "quant": ("4", "8", "8"),
    "shading": ("flat2", "flat2", "flat3", "flat3", "formlit", "banded"),
    "shadow": 0.5,
    "jaw_seam": 0.85,
    "limb_style": ("blocky", "blocky", "inset", "lobed", "proud"),
    "leg_style": ("stub", "stub", "tapered", "lobed"),
}

# Where the dial sits when nobody says otherwise. Three quarters of draws come
# out of the table above and a quarter out of the full ranges, so the weird
# corners stay reachable forever -- the brief is explicit that they must, and a
# tail that is cheap to swipe away is worth more than a prior that is certainly
# slightly wrong.
DEFAULT_REALISM = 0.75


def _check_plausible():
    """The plausible band has to live inside the axis it narrows.

    Checked at import because the failure is silent otherwise: `_draw_axis`
    uses the band directly, so a band that has drifted outside its axis emits
    out-of-range params that only `_perturb` would later clamp -- and the bug
    would show up as an annealed figure quietly differing from its parent.
    """
    for key, pl in _PLAUSIBLE.items():
        ax = _AX[key]
        if ax.kind in ("num", "int"):
            assert ax.lo <= pl[0] <= pl[1] <= ax.hi, (key, pl, ax.lo, ax.hi)
        elif ax.kind == "bool":
            assert 0.0 <= pl <= 1.0, (key, pl)
        else:
            bad = [c for c in pl if c not in ax.choices]
            assert not bad, (key, bad)


_check_plausible()


# ============================================================== the sampler ====

def _draw_axis(rng, key, ax, strict=False):
    """One value for one axis, from its full range or from its plausible prior.

    `strict` is decided once per FIGURE and not once per axis, which is the
    whole design of the realism dial. Rolled per axis at 0.75 a figure would
    take a quarter of sixty-nine axes off the rails -- seventeen wild choices
    each -- and every figure would be slightly broken while none would be
    interestingly strange. Rolled per figure, three quarters of the sheet is
    plausible people and the last quarter is genuinely, usefully weird.
    """
    pl = _PLAUSIBLE.get(key) if strict else None
    if ax.kind == "num":
        lo, hi = pl if pl else (ax.lo, ax.hi)
        return round(rng.uniform(lo, hi), 4)
    if ax.kind == "int":
        lo, hi = pl if pl else (ax.lo, ax.hi)
        return rng.randint(int(lo), int(hi))
    if ax.kind == "bool":
        return rng.random() < (pl if pl is not None else ax.p)
    return rng.choice(pl if pl else ax.choices)


def _random_params(rng, realism=None):
    realism = DEFAULT_REALISM if realism is None else realism
    strict = rng.random() < realism
    p = {}
    for (k, ax) in SPEC:
        p[k] = _draw_axis(rng, k, ax, strict)
    # The seed is not an axis -- it is not a preference the user can express --
    # but it has to live in the params dict, because the micro-jitter inside
    # `draw` reads it and a figure the user liked must redraw from its params
    # and nothing else. `realistic` is recorded for the same reason plus one
    # more: it lets the next swipe run measure whether the dial is set right,
    # by comparing the acceptance rate inside and outside the prior.
    p["seed"] = rng.randrange(1 << 30)
    p["realistic"] = strict
    return p


def _apply_constraints(rng, p, constraints):
    """Pin or band the axes a prompt asked for, leaving the rest alone.

    The value semantics are resolved against the axis's own KIND rather than
    against the shape of the value, so a two-element list means a band on a
    numeric axis and a two-way choice on a categorical one and neither can be
    mistaken for the other. Keys that are not axes -- `_matched` and anything
    else beginning with an underscore -- are metadata for the UI and are
    skipped here rather than crashing the sampler.
    """
    if not constraints:
        return p
    for key, val in constraints.items():
        if key.startswith("_"):
            continue
        ax = _AX.get(key)
        if ax is None:
            # An unknown axis is ignored rather than raised on: a prompt parser
            # is a guess about free text and it must never be able to take the
            # server down.
            continue
        if ax.kind in ("num", "int"):
            if isinstance(val, (list, tuple)):
                lo, hi = max(ax.lo, min(val)), min(ax.hi, max(val))
                if lo > hi:
                    lo = hi = max(ax.lo, min(ax.hi, val[0]))
                v = rng.uniform(lo, hi)
            else:
                v = max(ax.lo, min(ax.hi, val))
            p[key] = int(round(v)) if ax.kind == "int" else round(v, 4)
        elif ax.kind == "bool":
            p[key] = bool(val)
        else:
            p[key] = rng.choice(list(val)) if isinstance(val, (list, tuple)) \
                else val
    return p


def _perturb(rng, parent, temp=0.45):
    """A point NEAR `parent`. Numeric axes get a gaussian step sized by the
    axis's own range; categorical and boolean axes are resampled outright with
    their own probability, because there is no "near" for a hat.

    The default temperature was picked by measurement rather than by taste.
    Against five liked figures, a perturbed draw sits 0.12 away in silhouette
    where an unbiased draw sits 0.27 -- so a biased sample is visibly a relative
    of what the user liked and is never a copy of it (zero exact repeats in a
    hundred and twenty draws). Tighter than this and the session converges on
    round three and shows two hundred near-duplicates, which is the failure this
    whole file exists to avoid; looser and the bias does nothing measurable.
    """
    p = dict(parent)
    # A perturbation of a figure drawn from the plausible prior stays in it,
    # and a perturbation of a wild one stays wild: a relative of something the
    # user liked should be recognisably the same kind of thing.
    strict = bool(parent.get("realistic", False))
    for (k, ax) in SPEC:
        if k not in p:
            # A params dict saved by an older version of this file is missing
            # whatever axes have been added since, and it is far better to fill
            # those in at random than to refuse the parent outright.
            p[k] = _draw_axis(rng, k, ax, strict)
            continue
        if ax.kind in ("num", "int"):
            rng_span = ax.hi - ax.lo
            v = p[k] + rng.gauss(0.0, ax.sigma * rng_span * temp)
            v = max(ax.lo, min(ax.hi, v))
            p[k] = int(round(v)) if ax.kind == "int" else round(v, 4)
        elif ax.kind == "bool":
            if rng.random() < ax.mut * temp:
                p[k] = not p[k]
        else:
            if rng.random() < ax.mut * temp:
                p[k] = _draw_axis(rng, k, ax, strict)
    # A fresh seed every time, or every perturbation of one parent shares its
    # micro-jitter and the family comes out looking cloned in a way none of the
    # named axes accounts for.
    p["seed"] = rng.randrange(1 << 30)
    return p


def sample(rng, bias=None, mix=0.70, constraints=None, realism=None):
    """One point in the space.

    `bias` is a list of params dicts the user swiped right on. When it is
    given, `mix` of the draws are perturbations of a random one of them and the
    rest are fully random -- the 30% is not politeness, it is the only thing
    keeping the sampler able to find a region the first fifty swipes never
    happened to show. The pure-random path is the default and is what the first
    fifty swipes run on.

    `constraints` is what a typed prompt turns into: {axis: value} to pin an
    axis, or {axis: (lo, hi)} to band it. It is applied LAST, after the bias
    and after the realism prior, because a prompt is the one thing in this
    system the user said out loud and it outranks both of the things we
    inferred. Everything it does not mention is still randomised, which is what
    keeps a prompted sheet from collapsing to one character.

    `realism` is the dial: 0 draws every axis from its full range, which is the
    distribution the first swipe run saw and scored 12% on; 1 draws every axis
    from `_PLAUSIBLE`. It defaults to DEFAULT_REALISM.
    """
    if bias and rng.random() < mix:
        p = _perturb(rng, rng.choice(bias))
    else:
        p = _random_params(rng, realism)
    return _apply_constraints(rng, p, constraints)


# ============================================================== the prompt ====
#
# THE PROMPT BOX WAS COLLECTING TEXT AND THROWING IT AWAY. This is the half
# that turns "A cute girl next door, blonde hair big eyes" into axis
# constraints, and the contract it has to meet is narrow: understand a
# reasonable vocabulary, IGNORE everything else rather than erroring, and say
# which words it understood so the interface can show the user what landed.
#
# It is a lookup table and not a parser, deliberately. A prompt is three to ten
# words of free text typed into a swipe app; anything cleverer than n-gram
# matching would be a second system to debug, and the failure mode of a clever
# one -- confidently misreading a word -- is worse here than the failure mode of
# a dumb one, which is ignoring it.

# Hair is named by VALUE at least as often as by hue -- black, brown, blonde and
# white are one narrow warm hue band between them -- which is why `hair_val` is
# its own axis. Each entry bands both.
_HAIR_WORDS = {
    "black": (0.00, 0.10, 0.20, 0.80), "raven": (0.00, 0.10, 0.20, 0.80),
    "jet": (0.00, 0.08, 0.20, 0.80),
    "brown": (0.16, 0.38, 0.25, 0.65), "brunette": (0.16, 0.36, 0.25, 0.60),
    "chestnut": (0.22, 0.40, 0.15, 0.45), "mousy": (0.30, 0.50, 0.35, 0.75),
    "auburn": (0.28, 0.46, 0.00, 0.22), "ginger": (0.40, 0.60, 0.00, 0.18),
    "red": (0.32, 0.52, 0.00, 0.20), "redhead": (0.32, 0.52, 0.00, 0.20),
    "copper": (0.42, 0.60, 0.02, 0.22), "sandy": (0.60, 0.78, 0.45, 0.85),
    "blonde": (0.76, 0.96, 0.55, 1.00), "blond": (0.76, 0.96, 0.55, 1.00),
    "golden": (0.72, 0.92, 0.60, 1.00), "flaxen": (0.80, 0.98, 0.55, 0.95),
    "fair": (0.74, 0.95, 0.55, 1.00), "honey": (0.70, 0.88, 0.55, 0.95),
    "platinum": (0.92, 1.00, 0.30, 0.70), "silver": (0.88, 1.00, 0.30, 0.70),
    "grey": (0.78, 0.95, 0.30, 0.70), "gray": (0.78, 0.95, 0.30, 0.70),
    "white": (0.93, 1.00, 0.30, 0.70),
}
# ...and these are hair words even with no noun after them, because nobody
# describes a coat as brunette.
_HAIR_ONLY = ("blonde", "blond", "brunette", "redhead", "ginger", "auburn",
              "flaxen", "platinum", "raven", "mousy", "sandy", "honey")

# Unnatural hair: a hue anywhere on the wheel, and the natural flag off.
_DYE_WORDS = {"pink": 0.92, "blue": 0.60, "green": 0.33, "purple": 0.77,
              "violet": 0.79, "teal": 0.47, "lilac": 0.76, "lavender": 0.74,
              "orange": 0.07, "turquoise": 0.48, "mint": 0.40}

# Clothing colour. The value is (hue, sat_lo, sat_hi, val_lo, val_hi); a hue of
# None means the word is about chroma rather than about hue -- black, white and
# grey are positions on the other two axes.
_CLOTH_WORDS = {
    "red": (0.00, 0.55, 0.95, 0.35, 0.70), "crimson": (0.98, 0.60, 0.95,
                                                       0.25, 0.55),
    "orange": (0.07, 0.60, 0.95, 0.50, 0.85), "amber": (0.10, 0.55, 0.90,
                                                        0.55, 0.90),
    "yellow": (0.14, 0.55, 0.95, 0.65, 0.95), "gold": (0.12, 0.50, 0.85,
                                                       0.55, 0.90),
    "olive": (0.19, 0.30, 0.60, 0.30, 0.55), "green": (0.33, 0.40, 0.90,
                                                       0.25, 0.65),
    "teal": (0.47, 0.40, 0.85, 0.30, 0.65), "cyan": (0.50, 0.45, 0.90,
                                                     0.50, 0.85),
    "blue": (0.60, 0.45, 0.90, 0.30, 0.70), "navy": (0.62, 0.45, 0.85,
                                                     0.12, 0.30),
    "indigo": (0.70, 0.45, 0.85, 0.18, 0.45), "purple": (0.77, 0.45, 0.90,
                                                         0.22, 0.55),
    "violet": (0.79, 0.45, 0.90, 0.30, 0.65), "magenta": (0.88, 0.55, 0.95,
                                                          0.40, 0.75),
    "pink": (0.92, 0.30, 0.65, 0.65, 0.95), "brown": (0.07, 0.30, 0.60,
                                                      0.20, 0.45),
    "tan": (0.09, 0.25, 0.50, 0.50, 0.80), "cream": (0.11, 0.10, 0.25,
                                                     0.80, 0.97),
    "black": (None, 0.00, 0.14, 0.05, 0.18), "white": (None, 0.00, 0.12,
                                                       0.82, 0.98),
    "grey": (None, 0.00, 0.14, 0.35, 0.60), "gray": (None, 0.00, 0.14,
                                                     0.35, 0.60),
}

# Nouns that mean the colour beside them is a garment colour rather than a hair
# colour: "blue coat" and "blue hair" have to go to different axes.
_GARMENT_NOUNS = ("coat", "robe", "dress", "tunic", "shirt", "vest", "smock",
                  "poncho", "cloak", "cape", "skirt", "trousers", "pants",
                  "boots", "hat", "hood", "cap", "apron", "armour", "armor",
                  "scarf", "clothes", "outfit", "gown", "jacket")

# Everything else, as n-grams. Applied shortest first so that a longer phrase
# overrides the words inside it -- "long hair" beats "long", "girl next door"
# beats "girl" -- while the general sense of the shorter one still lands.
_VOCAB = {
    # --- age ---------------------------------------------------------------
    "young": {"age": (0.00, 0.25)},
    "youthful": {"age": (0.00, 0.25)},
    "cute": {"age": (0.00, 0.30), "eye_w": (4, 5), "eye_h": (2, 3),
             "head_frac": (0.36, 0.46), "face_w": (0.76, 0.88),
             "mouth": ("small", "line", "smirk")},
    "child": {"age": (0.00, 0.18), "height_rows": (30, 35),
              "head_frac": (0.42, 0.50), "facial_hair": "none"},
    "kid": {"age": (0.00, 0.18), "height_rows": (30, 35),
            "head_frac": (0.42, 0.50), "facial_hair": "none"},
    "teen": {"age": (0.05, 0.25), "height_rows": (34, 40)},
    "old": {"age": (0.72, 1.00)},
    "elderly": {"age": (0.78, 1.00)},
    "aged": {"age": (0.72, 1.00)},
    "ancient": {"age": (0.85, 1.00)},
    "middle aged": {"age": (0.45, 0.65)},
    # --- build and height ---------------------------------------------------
    "tall": {"height_rows": (42, 46)},
    "short": {"height_rows": (30, 35)},
    "stocky": {"build": (0.70, 1.00)},
    "burly": {"build": (0.75, 1.00)},
    "broad": {"build": (0.70, 1.00)},
    "stout": {"build": (0.70, 1.00)},
    "heavyset": {"build": (0.75, 1.00)},
    "slim": {"build": (0.00, 0.30)},
    "slender": {"build": (0.00, 0.30)},
    "slight": {"build": (0.00, 0.25)},
    "thin": {"build": (0.00, 0.25)},
    "lithe": {"build": (0.05, 0.35)},
    "lanky": {"build": (0.00, 0.25), "height_rows": (42, 46)},
    # --- the face -----------------------------------------------------------
    # A big eye is bought with WIDTH and with a wide face to put it in, not
    # with height: past three rows of iris the eye stops being an eye. The
    # gap stays at two or three, because two eyes an inch apart are one mask.
    "big eyes": {"eye_w": (4, 5), "eye_h": (2, 3), "eye_gap": (2, 3),
                 "face_w": (0.78, 0.90), "hair_mass": (0.0, 0.22),
                 "head_frac": (0.36, 0.48),
                 "eye_style": ("sclera_out", "full_iris")},
    "large eyes": {"eye_w": (4, 5), "eye_h": (2, 3), "eye_gap": (2, 3),
                   "face_w": (0.78, 0.90), "hair_mass": (0.0, 0.22)},
    "wide eyes": {"eye_w": (4, 5), "eye_h": (2, 3), "face_w": (0.78, 0.90),
                  "eye_style": "wide"},
    "doe eyes": {"eye_w": (4, 5), "eye_h": (2, 3), "face_w": (0.78, 0.90)},
    "small eyes": {"eye_w": (2, 3), "eye_h": (1, 2)},
    "narrow eyes": {"eye_w": (2, 3), "eye_h": (1, 2)},
    "beady eyes": {"eye_style": "beady", "eye_w": (2, 3)},
    "closed eyes": {"eye_style": "closed"},
    "smiling": {"mouth": ("smirk", "wide")},
    "happy": {"mouth": ("smirk", "wide"), "brow": ("none", "flat")},
    "serious": {"brow": ("angled", "flat"), "mouth": "line"},
    "stern": {"brow": "angled", "mouth": "line"},
    "worried": {"brow": "worried"},
    "glasses": {"accessory": "glasses"},
    "spectacles": {"accessory": "glasses"},
    "freckled": {"skin_val": (0.70, 0.95)},
    # --- facial hair --------------------------------------------------------
    "beard": {"facial_hair": ("beard", "long_beard")},
    "bearded": {"facial_hair": ("beard", "long_beard")},
    "moustache": {"facial_hair": "moustache"},
    "mustache": {"facial_hair": "moustache"},
    "goatee": {"facial_hair": "goatee"},
    "stubble": {"facial_hair": "stubble"},
    "clean shaven": {"facial_hair": "none"},
    "shaven": {"facial_hair": "none"},
    # --- hair shape ---------------------------------------------------------
    "bald": {"hair_shape": "bald"},
    "long hair": {"hair_len": (0.55, 1.00),
                  "hair_shape": ("long", "round", "tail", "bob")},
    "short hair": {"hair_len": (0.00, 0.20)},
    "curly": {"hair_shape": "curls"},
    "wavy": {"hair_shape": ("curls", "round")},
    "braid": {"hair_shape": "tail"},
    "braided": {"hair_shape": "tail"},
    "ponytail": {"hair_shape": "tail", "hair_len": (0.45, 1.00)},
    "pigtails": {"hair_shape": "pigtails"},
    "twintails": {"hair_shape": "pigtails"},
    "bob": {"hair_shape": "bob"},
    "spiky": {"hair_shape": "spiky"},
    "messy": {"hair_shape": ("wild", "spiky")},
    "mohawk": {"hair_shape": "mohawk"},
    "topknot": {"hair_shape": "topknot"},
    "bun": {"hair_shape": "topknot"},
    "fringe": {"fringe": ("step", "two_notch", "swept")},
    "bangs": {"fringe": ("step", "two_notch", "swept")},
    # --- skin ---------------------------------------------------------------
    "dark skin": {"skin_val": (0.10, 0.38)},
    "dark skinned": {"skin_val": (0.10, 0.38)},
    "brown skin": {"skin_val": (0.28, 0.52)},
    "pale skin": {"skin_val": (0.80, 1.00)},
    "pale": {"skin_val": (0.78, 1.00)},
    "tanned": {"skin_val": (0.45, 0.70)},
    "olive skin": {"skin_val": (0.45, 0.68), "skin_sat": (0.30, 0.55)},
    # --- headwear -----------------------------------------------------------
    "hat": {"headwear": ("brim", "cap")},
    "hood": {"headwear": "hood"},
    "hooded": {"headwear": "hood", "headwear_carries": True},
    "helmet": {"headwear": "helm"},
    "helm": {"headwear": "helm"},
    "cap": {"headwear": "cap"},
    "headband": {"headwear": "band"},
    "bandana": {"headwear": ("band", "wrap")},
    "headscarf": {"headwear": "wrap"},
    "crown": {"headwear": "crown"},
    "horns": {"headwear": "horns"},
    "horned": {"headwear": "horns"},
    "antlers": {"headwear": "horns"},
    # --- garments -----------------------------------------------------------
    "robe": {"top": "robe"},
    "coat": {"top": "coat"},
    "jacket": {"top": "coat", "top_len": (0.25, 0.55)},
    "dress": {"top": "dress", "lower": ("skirt", "long_skirt")},
    "gown": {"top": "robe", "lower": "long_skirt"},
    "tunic": {"top": "tunic"},
    "vest": {"top": "vest"},
    "shirt": {"top": "shirt"},
    "smock": {"top": "smock"},
    "poncho": {"top": "poncho"},
    "apron": {"apron": True},
    "armour": {"top": "armour", "boots": "tall"},
    "armor": {"top": "armour", "boots": "tall"},
    "cloak": {"cloak": ("half", "full")},
    "cape": {"cloak": "cape"},
    "skirt": {"lower": ("skirt", "long_skirt")},
    "trousers": {"lower": "trousers"},
    "pants": {"lower": "trousers"},
    "shorts": {"lower": "shorts"},
    "barefoot": {"boots": "none"},
    "boots": {"boots": ("low", "tall", "cuffed")},
    "belt": {"belt": ("thin", "wide")},
    "sash": {"belt": "sash"},
    "scarf": {"accessory": "scarf"},
    "gloves": {"accessory": "gloves"},
    "necklace": {"accessory": "necklace"},
    # --- carried ------------------------------------------------------------
    "staff": {"prop": "staff"},
    "stave": {"prop": "staff"},
    "sword": {"prop": "sword"},
    "book": {"prop": "book"},
    "lantern": {"prop": "lantern"},
    "lamp": {"prop": "lantern"},
    "basket": {"prop": "basket"},
    "broom": {"prop": "broom"},
    "hammer": {"prop": "hammer"},
    "satchel": {"prop": "satchel"},
    "bag": {"prop": "satchel"},
    "backpack": {"prop": "pack"},
    "pack": {"prop": "pack"},
    # --- roles, which are just several of the above at once ------------------
    "wizard": {"top": "robe", "headwear": ("brim", "hood"), "prop": "staff",
               "facial_hair": ("beard", "long_beard"), "age": (0.55, 1.00)},
    "witch": {"top": "robe", "headwear": "brim", "prop": "broom"},
    "mage": {"top": "robe", "prop": "staff"},
    "monk": {"top": "robe", "headwear": "hood", "belt": "sash"},
    "priest": {"top": "robe", "collar": ("band", "high")},
    "knight": {"top": "armour", "headwear": "helm", "prop": "sword",
               "boots": "tall"},
    "soldier": {"top": "armour", "prop": "sword"},
    "guard": {"top": "armour", "headwear": "helm", "prop": "staff"},
    "farmer": {"apron": True, "prop": ("basket", "broom"),
               "palette": ("earth", "muted"), "top": ("smock", "shirt")},
    "smith": {"apron": True, "prop": "hammer", "build": (0.60, 1.00)},
    "blacksmith": {"apron": True, "prop": "hammer", "build": (0.60, 1.00)},
    "scholar": {"prop": "book", "accessory": "glasses", "top": "robe"},
    "student": {"prop": "book", "age": (0.05, 0.30)},
    "merchant": {"prop": "satchel", "pattern": ("trim", "hem_band")},
    "traveller": {"prop": "pack", "cloak": ("half", "cape")},
    "traveler": {"prop": "pack", "cloak": ("half", "cape")},
    "noble": {"pattern": "trim", "collar": ("ruff", "fur"),
              "colour_blocks": (7, 10)},
    "peasant": {"palette": ("earth", "muted"), "pattern": "none",
                "top": ("smock", "shirt", "tunic")},
    "elf": {"headwear": "ears", "build": (0.00, 0.35), "age": (0.00, 0.35)},
    "elven": {"headwear": "ears", "build": (0.00, 0.35)},
    "orc": {"skin_exotic": True, "build": (0.70, 1.00)},
    "goblin": {"skin_exotic": True, "height_rows": (30, 34)},
    "troll": {"skin_exotic": True, "build": (0.80, 1.00)},
    "alien": {"skin_exotic": True},
    "monster": {"skin_exotic": True},
    # --- who ----------------------------------------------------------------
    # At 32x48 the only things that read as gender are hair length, the lower
    # garment and facial hair, so that is all these do. They are bands rather
    # than pins for the obvious reason.
    "girl": {"facial_hair": "none", "hair_len": (0.25, 1.00),
             "lower": ("skirt", "long_skirt", "trousers"), "age": (0.0, 0.35),
             "hair_shape": ("round", "bob", "long", "tail", "pigtails",
                            "curls")},
    "woman": {"facial_hair": "none", "hair_len": (0.20, 1.00),
              "lower": ("skirt", "long_skirt", "trousers"),
              "hair_shape": ("round", "bob", "long", "tail", "curls",
                             "flat")},
    "lady": {"facial_hair": "none", "hair_len": (0.20, 1.00),
             "lower": ("skirt", "long_skirt")},
    "female": {"facial_hair": "none", "hair_len": (0.20, 1.00)},
    "she": {"facial_hair": "none", "hair_len": (0.20, 1.00)},
    "boy": {"hair_len": (0.00, 0.30), "lower": ("trousers", "shorts"),
            "age": (0.0, 0.30)},
    "man": {"hair_len": (0.00, 0.35), "lower": "trousers"},
    "guy": {"hair_len": (0.00, 0.35), "lower": "trousers"},
    "male": {"hair_len": (0.00, 0.35)},
    "he": {"hair_len": (0.00, 0.35)},
    # --- register -----------------------------------------------------------
    # "Girl next door" is a statement about how UNREMARKABLE the clothes are,
    # which is the one thing in the prompt that maps to the palette axes rather
    # than to a garment.
    "girl next door": {"palette": ("analogous", "earth", "muted"),
                       "pattern": ("none", "none", "trim"),
                       "top": ("shirt", "tunic", "dress", "vest"),
                       "cloak": "none", "prop": ("none", "none", "satchel"),
                       "headwear": ("none",) * 4 + ("band",),
                       "sat": (0.12, 0.50), "val_spread": (0.0, 0.40),
                       "facial_hair": "none", "hair_len": (0.25, 1.00),
                       "lower": ("skirt", "trousers", "long_skirt")},
    "next door": {"palette": ("analogous", "earth", "muted"),
                  "pattern": ("none", "trim"), "cloak": "none"},
    "ordinary": {"palette": ("analogous", "earth", "muted"),
                 "pattern": "none", "prop": "none"},
    "plain": {"palette": ("earth", "muted"), "pattern": "none"},
    "everyday": {"palette": ("analogous", "earth", "muted")},
    "fancy": {"pattern": ("trim", "hem_band", "dots"),
              "colour_blocks": (7, 10)},
    "colourful": {"palette": ("high_chroma", "triad", "complementary"),
                  "sat": (0.65, 1.00)},
    "colorful": {"palette": ("high_chroma", "triad", "complementary"),
                 "sat": (0.65, 1.00)},
    "drab": {"palette": ("muted", "earth"), "sat": (0.0, 0.25)},
}

_PUNCT = ",.;:!?\"'()[]{}/\\-—’"


def _tokens(text):
    out = []
    for w in "".join(" " if c in _PUNCT else c for c in text.lower()).split():
        out.append(w[:-1] if w.endswith("s") and w[:-1] in _VOCAB else w)
    return out


def parse_prompt(text):
    """Free text to axis constraints.

    Returns a dict of {axis: value} to pin an axis and {axis: (lo, hi)} to band
    it, plus two metadata keys the sampler skips and the interface can show:
    `_matched`, the phrases that were understood, and `_ignored`, the words that
    were not. Unknown words never raise -- a prompt parser is a guess about free
    text typed into a swipe app and it must not be able to take the server down.

    Longer phrases are applied after shorter ones, so a specific reading beats a
    general one that overlaps it: "long hair" lands on top of "long", "girl next
    door" on top of "girl", and "blue hair" on top of the bare colour word's
    reading of "blue" as a garment colour.
    """
    toks = _tokens(text or "")
    out, matched, used = {}, [], set()

    def take(phrase, cons, idxs):
        out.update(cons)
        if phrase not in matched:
            matched.append(phrase)
        used.update(idxs)

    # n-grams shortest first, so the specific overrides the general.
    for n in (1, 2, 3):
        for i in range(len(toks) - n + 1):
            phrase = " ".join(toks[i:i + n])
            if phrase in _VOCAB:
                take(phrase, _VOCAB[phrase], range(i, i + n))

    # Colours, which need the word beside them to know which axis they are on.
    for i, w in enumerate(toks):
        nxt = toks[i + 1] if i + 1 < len(toks) else ""
        hairish = nxt in ("hair", "haired", "locks", "curls", "braid",
                          "ponytail")
        if w in _HAIR_WORDS and (hairish or w in _HAIR_ONLY):
            vlo, vhi, hlo, hhi = _HAIR_WORDS[w]
            cons = {"hair_natural": True, "hair_val": (vlo, vhi),
                    "hair_hue": (hlo, hhi),
                    # A named hair colour must not drag the clothes with it, so
                    # the garment hue is explicitly handed its freedom back.
                    "base_hue": (0.0, 1.0)}
            if "hair_shape" not in out:
                # Naming a hair colour means there is hair. Left alone, a tenth
                # of a bank asked for "blonde hair" came out bald -- and this
                # only fires when nothing more specific has already spoken, so
                # "curly blonde hair" still gets its curls.
                cons["hair_shape"] = ("round", "bob", "long", "tail",
                                      "pigtails", "curls", "flat", "wild",
                                      "spiky", "topknot")
            take(w + (" hair" if hairish else ""), cons,
                 range(i, i + 1 + (1 if hairish else 0)))
            continue
        if w in _DYE_WORDS and hairish:
            h = _DYE_WORDS[w]
            cons = {"hair_natural": False, "hair_hue": (h - 0.03, h + 0.03),
                    "hair_val": (0.45, 0.85), "base_hue": (0.0, 1.0)}
            if "hair_shape" not in out:
                cons["hair_shape"] = ("round", "bob", "long", "tail",
                                      "pigtails", "curls", "spiky", "wild",
                                      "mohawk", "topknot")
            take(w + " hair", cons, range(i, i + 2))
            continue
        if w in _CLOTH_WORDS and not hairish:
            hue, slo, shi, vlo, vhi = _CLOTH_WORDS[w]
            cons = {"sat": (slo, shi), "value": (vlo, vhi)}
            if hue is not None:
                cons["base_hue"] = (hue - 0.035, hue + 0.035)
                # An analogous or monochrome plan keeps the named colour the
                # colour of the figure; a triad would put it on the belt and
                # paint the coat something else, which is not what was asked.
                cons["palette"] = ("analogous", "mono_accent", "muted",
                                   "dark_bright")
            else:
                cons["palette"] = ("mono_accent", "muted", "dark_bright")
            span = 2 if nxt in _GARMENT_NOUNS else 1
            take(w + (" " + nxt if span == 2 else ""), cons,
                 range(i, i + span))

    out["_matched"] = matched
    out["_ignored"] = [w for i, w in enumerate(toks) if i not in used]
    return out


# ================================================================== jitter ====

def _j(seed, tag):
    """A deterministic 0..1 draw keyed by (seed, tag).

    A hash and not a stream, on purpose: with `random.Random(seed)` the value a
    call site gets depends on how many draws happened before it, so adding one
    line anywhere in `draw` would silently redraw every figure the user has
    already swiped right on. Keyed by tag, a new call site is a new stream and
    the old ones do not move.
    """
    h = (seed * 2654435761 + zlib.crc32(tag.encode("utf8"))) & 0xFFFFFFFF
    h ^= (h >> 13)
    h = (h * 1274126177) & 0xFFFFFFFF
    h ^= (h >> 16)
    return (h & 0xFFFFFF) / float(0xFFFFFF)


# ================================================================= palette ====

def _rgb(h, s, v, q=1):
    """HSV to a quantised RGB triple.

    Quantising to a coarse grid is not nostalgia. At 32x48 two colours four
    steps apart read as one blurry mass rather than as two flat blocks, and
    flat blocks with hard edges are what the reference sprites actually are --
    so `quant` is an axis, and 8 is the 5-bit-per-channel grid the SNES had.
    """
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)),
                                  max(0.0, min(1.0, v)))
    out = []
    for c in (r, g, b):
        n = int(round(c * 255))
        if q > 1:
            n = min(255, int(round(n / float(q))) * q)
        out.append(max(0, min(255, n)))
    return (out[0], out[1], out[2])


def _ramp(h, s, v, vs, ss, q):
    """Three tones -- lit, base, shade -- and never more.

    Three is what every one of the reference frames spends on a material: a
    flat mass costs two tones and a sculpted one costs five, and five at this
    size is a soft blend where the reference is a carved block. The lit step
    also desaturates and warms while the shade saturates and cools, which is
    what pigment does under a warm light and is most of the difference between
    a ramp that looks mixed and one that looks like three slider positions.
    """
    lit = _rgb(h + 0.020, s - 0.16 * ss, min(0.99, v + 0.24 * vs), q)
    base = _rgb(h, s, v, q)
    shd = _rgb(h - 0.035, min(1.0, s + 0.12 * ss), max(0.05, v - 0.30 * vs), q)
    return [lit, base, shd]


# Hue offsets from the base hue, per palette strategy, as many slots as any
# figure needs. The slots are consumed in a fixed order -- top, under, lower,
# boots, accent, cloak -- so that a strategy's intent survives a garment
# changing underneath it.
_HUE_PLAN = {
    "analogous":     (0.00, 0.06, -0.06, 0.11, -0.10, 0.03),
    "complementary": (0.00, 0.50, 0.04, 0.46, 0.52, -0.03),
    "triad":         (0.00, 0.333, 0.667, 0.02, 0.35, 0.70),
    "split":         (0.00, 0.42, 0.58, 0.03, 0.45, 0.55),
    "mono_accent":   (0.00, 0.00, 0.00, 0.00, 0.50, 0.00),
    "dark_bright":   (0.00, 0.03, -0.03, 0.05, 0.48, 0.00),
    "earth":         (0.00, 0.04, 0.08, 0.02, 0.06, -0.02),
    "high_chroma":   (0.00, 0.28, 0.62, 0.14, 0.78, 0.45),
    "pastel":        (0.00, 0.12, -0.12, 0.22, 0.40, 0.06),
    "muted":         (0.00, 0.08, -0.08, 0.15, 0.30, 0.00),
    "two_tone":      (0.00, 0.50, 0.00, 0.50, 0.00, 0.50),
    "chaos":         (0.00, 0.17, 0.41, 0.73, 0.29, 0.58),
}

# Saturation and value bands per strategy, as (sat_lo, sat_hi, val_lo, val_hi)
# for the garments. These are what actually separate a pastel figure from a
# muted one -- the hue plan alone leaves every strategy looking like the same
# person -- and they are the single biggest lever on how different two figures
# look from across a contact sheet.
_TONE_PLAN = {
    "analogous":     (0.30, 0.70, 0.35, 0.80),
    "complementary": (0.40, 0.85, 0.30, 0.80),
    "triad":         (0.45, 0.85, 0.35, 0.80),
    "split":         (0.40, 0.80, 0.35, 0.78),
    "mono_accent":   (0.25, 0.65, 0.25, 0.85),
    "dark_bright":   (0.30, 0.75, 0.12, 0.42),
    "earth":         (0.22, 0.52, 0.28, 0.66),
    "high_chroma":   (0.70, 0.98, 0.55, 0.95),
    "pastel":        (0.14, 0.36, 0.78, 0.98),
    "muted":         (0.10, 0.32, 0.30, 0.60),
    "two_tone":      (0.35, 0.80, 0.25, 0.85),
    "chaos":         (0.05, 1.00, 0.15, 0.98),
}


def _palette(P):
    """Every ramp the figure will use, mixed from the colour axes.

    The whole palette is derived rather than tabled because a table of hand-
    mixed palettes is exactly the thing that made the previous six rounds look
    samey: forty authored palettes is forty points, and the user needs the
    continuum between them to be able to point at a region.
    """
    seed = P["seed"]
    q = int(P["quant"])
    strat = P["palette"]
    plan = _HUE_PLAN[strat]
    s_lo, s_hi, v_lo, v_hi = _TONE_PLAN[strat]
    base = P["base_hue"]
    # `sat` and `value` slide within the strategy's own band rather than
    # replacing it, so a strategy stays recognisable while still covering
    # ground -- otherwise every strategy collapses onto the same two sliders.
    s0 = s_lo + (s_hi - s_lo) * P["sat"]
    v0 = v_lo + (v_hi - v_lo) * P["value"]
    ss, vs = 0.3 + 1.3 * P["sat_spread"], 0.35 + 1.1 * P["val_spread"]

    def slot(i, tag, dv=0.0, ds=0.0):
        # Per-slot jitter on top of the plan, because a plan applied exactly
        # gives six garments in a perfect chord and real clothes are not a
        # chord. The jitter is keyed by tag so it is stable across redraws.
        h = base + plan[i] + (_j(seed, "h" + tag) - 0.5) * 0.06
        s = s0 + ds + (_j(seed, "s" + tag) - 0.5) * 0.30 * ss
        v = v0 + dv + (_j(seed, "v" + tag) - 0.5) * 0.34 * vs
        return _ramp(h, max(0.0, min(1.0, s)), max(0.07, min(0.99, v)),
                     vs, ss, q)

    pal = {}
    pal["top"] = slot(0, "top")
    pal["under"] = slot(1, "under", dv=0.10)
    pal["lower"] = slot(2, "lower", dv=-0.12)
    pal["boot"] = slot(3, "boot", dv=-0.22, ds=-0.05)
    pal["cloak"] = slot(5, "cloak", dv=-0.06)
    # THE ONE HOT ACCENT, and it is the only colour on the figure allowed to be
    # louder than the face. Two of them and the figure is a clown, which is why
    # it gets its own slot rather than being another garment.
    ah = base + 0.25 + 0.5 * P["accent_hue_off"]
    pal["accent"] = _ramp(ah, min(1.0, 0.55 + 0.45 * P["sat"]),
                          0.62 + 0.30 * _j(seed, "acc"), vs, ss, q)
    pal["metal"] = _ramp(0.12, 0.45, 0.84, vs, 0.6, q)

    # SKIN. A genuinely wide band and not a polite one: hue from a cool pink
    # through to a deep red-brown, value from 0.22 to 0.97, and an 8% chance of
    # leaving the human band entirely, because the user cannot swipe right on a
    # region the sampler never visits.
    if P["skin_exotic"]:
        sh = _j(seed, "exotic")
        sk_s = 0.18 + 0.45 * P["skin_sat"]
    else:
        sh = 0.020 + 0.085 * P["skin_hue"]
        sk_s = 0.10 + 0.62 * P["skin_sat"] * (1.15 - 0.5 * P["skin_val"])
    sk_v = 0.22 + 0.75 * P["skin_val"]
    pal["skin"] = _ramp(sh, sk_s, sk_v, vs, ss, q)

    # HAIR. Natural hair is a narrow hue band with a wide value range; unnatural
    # hair is anywhere on the wheel. Old age pulls the value up and the
    # saturation down, which is the cheapest age cue on the figure and costs no
    # pixels at all.
    hval = P.get("hair_val", P["hair_hue"])
    if P["hair_natural"]:
        # Natural hair is a narrow warm hue band -- black, brown, auburn, red,
        # blonde and white are one sixth of the wheel between them -- with all
        # of the variety in VALUE. Saturation falls off at both ends because a
        # saturated near-black is a plum and a saturated near-white is a lemon.
        hh = 0.015 + 0.095 * P["hair_hue"]
        hv = 0.08 + 0.80 * hval
        hs = (0.22 + 0.58 * (1.0 - P["age"] * 0.7)) * (
            1.0 - abs(hval - 0.45) * 0.9)
        hs = max(0.05, hs)
    else:
        hh = P["hair_hue"]
        hs = 0.45 + 0.50 * P["sat"]
        hv = 0.20 + 0.72 * hval
    hv = min(0.96, hv + 0.42 * P["age"] ** 2)
    hs = max(0.03, hs * (1.0 - 0.75 * P["age"] ** 2))
    pal["hair"] = _ramp(hh, hs, hv, vs, ss, q)

    # A LEGIBILITY FLOOR, and it is the only place in this file where an axis
    # is overruled. Hair the same value as the skin under it does not read as
    # "subtle", it reads as a head with no features -- the face and the mass
    # stop being two shapes and become one blob, and every other axis on the
    # figure is then sitting on nothing. So the hair is pushed away from the
    # skin until there are forty luma between them, in whichever direction it
    # was already going. Hue is left alone, because hue is a preference and
    # this is a contrast requirement.
    if abs(_luma(pal["hair"][1]) - _luma(pal["skin"][1])) < 40:
        push = 0.26 if _luma(pal["hair"][1]) <= _luma(pal["skin"][1]) else -0.26
        hv2 = max(0.06, min(0.97, hv - push))
        pal["hair"] = _ramp(hh, hs, hv2, vs, ss, q)

    # THE EYE gets its own ramp because an iris colour is one of about four
    # things a 32px figure can say about a person that its silhouette cannot.
    # The iris is DARK, not mid-valued. At 0.52 it measured about the same luma
    # as a lit face and the eye read as a pale slab with a line over it; the
    # thing that makes an eye read at 1:1 is being the largest local contrast in
    # the frame, which means the iris has to lose to the sclera by a lot.
    pal["eye"] = [_rgb(0.12, 0.05, 0.96, q),
                  _rgb(P["eye_hue"], 0.62, 0.40, q),
                  _rgb(P["eye_hue"] - 0.02, 0.70, 0.20, q)]

    # THE CONTOUR. Never pure black -- both native frames use a dark warm
    # neutral, and pure black on a figure whose darkest garment is already 40
    # luma reads as a sticker cut out and laid on the grass.
    mode = P["outline_mode"]
    if mode == "light":
        pal["line"] = _rgb(base + 0.5, 0.10, 0.90, q)
    else:
        pal["line"] = _rgb(base + 0.55, 0.28 + 0.25 * P["sat"],
                           0.10 + 0.10 * _j(seed, "line"), q)
    # THE FEATURES DO NOT SHARE THE CONTOUR'S COLOUR. They did, and it was a
    # real bug rather than a stylistic slip: with `outline_mode` set to "light"
    # the lash row and the dot-eye came out near-white on a lit face, and every
    # figure in that fifth of the space had no eyes at all. The lash is the
    # darkest thing on the figure sitting directly against the brightest -- that
    # contrast is the entire reason an eye reads at 1:1 -- so it gets a colour
    # that is guaranteed dark whatever the contour is doing.
    pal["ink"] = _rgb(base + 0.55, 0.30, 0.11, q)

    # The same floor again, between the contour and the garment it runs along.
    # A dark outline round a dark coat is a coat-shaped hole, which is what the
    # `dark_bright` palette produced before this line existed.
    if mode != "none" and abs(_luma(pal["line"]) - _luma(pal["top"][1])) < 34:
        if _luma(pal["line"]) < 128:
            pal["top"] = _ramp(base + plan[0], s0, min(0.97, v0 + 0.26),
                               vs, ss, q)
        else:
            pal["top"] = _ramp(base + plan[0], s0, max(0.08, v0 - 0.26),
                               vs, ss, q)
    return pal


def _luma(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


# ================================================================== canvas ====

class Cel(object):
    """The frame, plus the two operations every part of this file needs.

    Kept as a PIL image with a loaded pixel access object rather than a dict,
    because `draw` has a 25 ms budget and a dict of tuples spends most of it in
    hashing.
    """

    def __init__(self):
        self.img = Image.new("RGBA", (FW, FH), CLEAR)
        self.p = self.img.load()

    def px(self, x, y, c, a=255):
        x, y = int(x), int(y)
        if 0 <= x < FW and 0 <= y < FH:
            self.p[x, y] = (c[0], c[1], c[2], a)

    def row(self, y, x0, x1, c):
        y = int(y)
        if not (0 <= y < FH):
            return
        for x in range(max(0, int(x0)), min(FW - 1, int(x1)) + 1):
            self.p[x, y] = (c[0], c[1], c[2], 255)

    def at(self, x, y):
        if 0 <= x < FW and 0 <= y < FH:
            return self.p[int(x), int(y)]
        return CLEAR


# =================================================================== spans ====
#
# Every grammar, however differently it thinks, hands back the same thing: a
# mass as {row: (x0, x1)}. That is the one representation a sprite actually has
# and it is what lets a head built by one theory sit on a body built by
# another -- the hybridisation this file is mostly for.

def _sp(w, cx=CX):
    w = max(1, int(round(w)))
    x0 = int(round(cx - w / 2.0))
    return (x0, x0 + w - 1)


def _merge(*forms):
    out = {}
    for f in forms:
        for y, (x0, x1) in f.items():
            a, b = out.get(y, (x0, x1))
            out[y] = (min(a, x0), max(b, x1))
    return out


def _band(form, y0, y1):
    return dict((y, v) for (y, v) in form.items() if y0 <= y <= y1)


def _lobe(cx, cy, rx, up, dn, n=1.25):
    """One superellipse, as rows.

    The reach above the centre is deliberately allowed to differ from the reach
    below, and the centre row is an integer: a form with equal reach pairs its
    rows off symmetrically so every edge value appears exactly twice, and a form
    whose apex falls between two rows gives those two rows the same edge and
    never reaches its own widest column. Both turn a one-row apex into a two-row
    flat, which is the thing the curves grammar exists to avoid.
    """
    rows = {}
    for y in range(int(math.floor(cy - up)), int(math.ceil(cy + dn)) + 1):
        d = y - cy
        b = up if d <= 0 else dn
        t = abs(d) / float(max(0.5, b))
        if t >= 1.0:
            continue
        h = rx * (1.0 - t ** n) ** (1.0 / n)
        # The epsilon is load-bearing: 6.4 - 3.4 is 3.0000000000000004 in
        # binary, so a form whose widest row lands on a pixel boundary loses
        # that pixel to ceil() and the apex flattens.
        x0 = int(math.ceil(cx - h - 1e-9))
        x1 = int(math.floor(cx + h + 1e-9))
        if x1 >= x0:
            rows[y] = (x0, x1)
    return rows


def _profile(keys, t):
    """A keyframed width profile, linear between keys."""
    for i in range(len(keys) - 1):
        (ta, wa), (tb, wb) = keys[i], keys[i + 1]
        if ta <= t <= tb:
            k = (t - ta) / (tb - ta) if tb > ta else 0.0
            return wa + k * (wb - wa)
    return keys[-1][1]


def _dome(w, n, top, cx=CX, dome=(0.44, 0.72, 0.88), chin=(0.62, 0.86),
          jitter=None):
    """A mass: domed at the top, full through the middle, tapered at the chin.

    A straight line across the top of a head is a bread bin with a face on it --
    the crown is the first thing a reader resolves on a 32px figure -- and the
    chin taper is what stops the head reading as a cylinder with features
    printed on the front of it.
    """
    out = {}
    for i in range(n):
        f = dome[i] if i < len(dome) else 1.0
        k = n - 1 - i
        if k < len(chin):
            f = min(f, chin[k])
        if jitter is not None and i < len(jitter):
            f = max(0.2, f + jitter[i])
        out[top + i] = _sp(w * f, cx)
    return out


# ============================================================ the four heads ====
#
# Each of these is one of the four source files' theory of a head, reduced to
# the part that is actually a theory and given parameters where that file had a
# hand-typed constant. They all return (mass, skull, jaw_row) -- and `derive`
# is allowed to move the jaw row, because "the head's height is an output" is
# the whole of what that grammar claims.

def _hair_profile(shape, i, n, seed):
    """Relative width of the hair mass at row i of n, by silhouette shape.

    This is the hairfirst grammar's authored span table turned into a family of
    them. The shapes are not variations on one curve -- `long` is widest at the
    bottom where `bob` is widest a fifth of the way down and `topknot` is
    narrowest at the crown -- because a mass that only varies in amount is the
    same character with more hair.
    """
    t = i / float(max(1, n - 1))
    if shape == "round":
        return 0.46 + 0.54 * math.sin(min(1.0, t * 1.9) * math.pi / 2.0)
    if shape == "bob":
        return min(1.0, 0.40 + 3.0 * t) if t < 0.2 else 1.0 - 0.10 * (t - 0.2)
    if shape == "long":
        return 0.40 + 0.60 * t                      # widening all the way down
    if shape == "spiky":
        base = 0.55 + 0.45 * min(1.0, t * 2.4)
        return base + 0.16 * (_j(seed, "spike%d" % i) - 0.5) * 2.0
    if shape == "topknot":
        # A knot above a narrow crown: the bump is the top three rows and the
        # mass proper does not start until under it.
        if t < 0.16:
            return 0.34 + 0.10 * math.sin(t * 20)
        return 0.30 + 0.70 * min(1.0, (t - 0.16) * 3.0)
    if shape == "wild":
        return 0.50 + 0.50 * min(1.0, t * 2.2) + 0.22 * (
            _j(seed, "wild%d" % i) - 0.5) * 2.0
    if shape == "flat":
        return 0.70 if t < 0.06 else 0.92 + 0.08 * t
    if shape == "mohawk":
        return 0.30 if t < 0.30 else 0.86
    if shape == "curls":
        # Scalloped: the edge steps in and out on a three-row period, which is
        # what separates curls from a helmet at this size.
        return (0.50 + 0.50 * min(1.0, t * 2.2)) - 0.10 * (i % 3 == 1)
    if shape == "tail":
        return 0.44 + 0.50 * min(1.0, t * 2.6)
    if shape == "pigtails":
        return 0.44 + 0.46 * min(1.0, t * 2.6)
    if shape == "bald":
        return 0.0
    return 0.8


def _mass_envelope(shape, i, n):
    """Domed at the crown, pulled in at the jaw, applied on top of whatever the
    shape profile said.

    Without it a nineteen-row head band fills with a full-width rectangle of one
    colour and the figure is wearing a crate: the shape profiles describe where
    the VOLUME is, and every one of them still has to be a head at the top and
    let go of the outline at the chin. The long falls are exempt below the jaw
    because that is the one shape whose whole claim is that it does not let go.
    """
    f = 1.0
    if i == 0:
        f *= 0.56
    elif i == 1:
        f *= 0.80
    elif i == 2:
        f *= 0.93
    if shape not in ("long", "tail", "wild"):
        k = n - 1 - i
        if k == 0:
            f *= 0.74
        elif k == 1:
            f *= 0.90
    return f


def _head_mass(P, L, seed):
    """The hairfirst theory: the mass is authored first and the skull is fitted
    inside and behind it, never on the outline."""
    top, jaw = L["crown"], L["jaw"]
    n = jaw - top + 1
    hw = L["head_w"]
    shape = P["hair_shape"]
    rise = P["hair_rise"] if shape != "bald" else 0
    asym = P["hair_asym"]
    mass = {}
    if shape != "bald":
        for i in range(n):
            f = _hair_profile(shape, i, n, seed) * _mass_envelope(shape, i, n)
            # The two edges are moved by different amounts, which is the
            # cheapest asymmetry there is and the one that stops a head reading
            # as a symmetrical lump. A hem ruled level all the way round is a
            # helmet read from underneath.
            wl = hw * 0.5 * max(0.12, f * (1.0 + 0.22 * asym))
            wr = hw * 0.5 * max(0.12, f * (1.0 - 0.22 * asym))
            mass[top + i] = (int(round(CX - wl)), int(round(CX + wr)))
    # The skull sits lower and narrower: `rise` rows of mass stand above it and
    # a temple of mass frames it either side, so nothing the skull does can
    # change the silhouette.
    # ONE TO FOUR PIXELS, not a fraction. Proportional temples were the bug
    # that turned every wide head into a six-pixel face in a twenty-two-pixel
    # wig: the frame of hair beside a face is about the same width at any head
    # size a face is legible at, exactly like the nose bridge between the eyes.
    temple = 1 + int(round(3.0 * P["hair_mass"]))
    sk_w = max(8, hw - 2 * temple) if shape != "bald" else hw
    sk_top = top + (rise if shape != "bald" else 0)
    skull = _dome(sk_w, jaw - sk_top + 1, sk_top)
    return mass, skull, jaw


def _head_span(P, L, seed):
    """The silhouette theory: the head is a band of one width-vs-height profile
    and the skull is a hole cut in it, so a feature can never push the outline
    out."""
    top, jaw = L["crown"], L["jaw"]
    n = jaw - top + 1
    hw = L["head_w"]
    peak = 0.22 + 0.40 * _j(seed, "peak")
    keys = [(0.00, 0.40 + 0.26 * _j(seed, "crown")),
            (0.06, 0.72), (0.16, 0.88), (peak, 1.00),
            (min(0.95, peak + 0.30), 0.94),
            (1.00, 0.58 + 0.30 * (1.0 - P["head_shoulder"] / 1.35))]
    mass = {}
    for i in range(n):
        f = _profile(keys, i / float(max(1, n - 1)))
        wl = hw * 0.5 * f * (1.0 + 0.15 * P["hair_asym"])
        wr = hw * 0.5 * f * (1.0 - 0.15 * P["hair_asym"])
        mass[top + i] = (int(round(CX - wl)), int(round(CX + wr)))
    temple = 1 + int(round(3.0 * P["hair_mass"]))
    sk_w = max(8, hw - 2 * temple)
    sk_top = top + max(1, P["hair_rise"] // 2)
    skull = _dome(sk_w, jaw - sk_top + 1, sk_top)
    return mass, skull, jaw


def _head_derive(P, L, seed):
    """The facefirst theory: one eye is the atom and everything is derived from
    it in one direction, so the head's HEIGHT is an output and the body is
    whatever rows are left over.

    This is the only grammar that moves the jaw, and that is the point of it: a
    child on this theory is the same face on a shorter body, with no per-figure
    number anywhere.
    """
    ew, gap = P["eye_w"], P["eye_gap"]
    cheek = 1 + (1 if ew >= 4 else 0)
    temple = 1 + int(round(2.0 * P["hair_mass"]))
    vol = 1 if P["hair_mass"] > 0.35 else 0
    face_w = 2 * ew + gap + 2 * cheek
    skull_w = face_w + 2 * temple
    # DERIVING IN ONE DIRECTION DOES NOT MEAN DERIVING WITHOUT A CEILING. With
    # a five-pixel eye, a six-pixel bridge and a four-pixel temple this summed
    # to a twenty-eight-pixel skull on a fourteen-pixel body, and what it drew
    # was a face on a crate. The atoms are squeezed back in the order they can
    # afford it -- the bridge first, then the cheek, then the temple -- because
    # the EYE is the thing this grammar refuses to shrink.
    room = min(22, L["sh_w"] + 6)
    while skull_w > room and (gap > 1 or cheek > 1 or temple > 1):
        if gap > 1:
            gap -= 1
        elif cheek > 1:
            cheek -= 1
        else:
            temple -= 1
        face_w = 2 * ew + gap + 2 * cheek
        skull_w = face_w + 2 * temple
    while skull_w > room and ew > 2:
        ew -= 1
        face_w = 2 * ew + gap + 2 * cheek
        skull_w = face_w + 2 * temple
    hair_w = skull_w + 2 * vol
    # The face's row budget, counted out one landmark at a time. Every row here
    # is bought by a feature and none of it is a proportion.
    brow_band = 1 + (1 if P["brow"] in ("thick", "raised_one") else 0)
    face_n = (1 + brow_band + 1 + 1 + P["eye_h"] + 1 + 1 + 2)
    forehead = 2 + int(round(2.0 * P["hair_mass"]))
    skull_n = face_n + forehead
    rise = P["hair_rise"] if P["hair_shape"] != "bald" else 0
    top = L["crown"]
    sk_top = top + rise
    jaw = sk_top + skull_n - 1
    # The head cannot eat the whole figure: if the derived head leaves fewer
    # than fourteen rows for a torso and a pair of legs, the body would be a
    # pair of feet under a portrait, so the head is squeezed back rather than
    # allowed to run off the bottom.
    if jaw > SOLE - 16:
        jaw = SOLE - 16
        sk_top = min(sk_top, jaw - 8)
    # ...and never more than 46% of the figure. The facefirst thesis is that a
    # child is the same face on a shorter body, so a HIGH head fraction is a
    # feature and not a bug -- Abigail measures 0.59 -- but a big eye on a short
    # figure was reaching 0.57 here and the note that started this retune says
    # "somewhat reasonable proportions" in as many words.
    cap = L["crown"] + int(round((SOLE - L["crown"] + 1) * 0.46)) - 1
    if jaw > cap:
        jaw = cap
        sk_top = min(sk_top, jaw - 8)
    skull = _dome(skull_w, jaw - sk_top + 1, sk_top)
    mass = {}
    if P["hair_shape"] != "bald":
        for y in range(top, jaw + 1):
            if y in skull:
                a, b = skull[y]
            else:
                a, b = _sp(hair_w * 0.6)
            mass[y] = (a - vol - (1 if P["hair_asym"] > 0.3 else 0),
                       b + vol + (1 if P["hair_asym"] < -0.3 else 0))
        for i in range(rise):
            a, b = skull[sk_top]
            k = rise - i
            mass[top + i] = (a + k // 2 - vol, b - k // 2 + vol)
    return mass, skull, jaw


def _head_lobe(P, L, seed):
    """The curves theory: overlapping superellipses whose widest rows sit at
    different heights, so the outline is handed from one form to the next before
    any of them has time to go flat."""
    top, jaw = L["crown"], L["jaw"]
    n = jaw - top + 1
    hw = L["head_w"]
    cy = top + n * 0.42
    # The skull's widest row is the EYE's row and not the crown's, which is not
    # where a real skull is widest -- but put it higher and the face has
    # narrowed to eleven pixels by the time the eyes are in it, and the outer
    # column of each eye lands in the contour. The face is the one place
    # anatomy loses to legibility.
    skull = _lobe(CX, top + n * 0.60, hw * 0.42, n * 0.58, n * 0.38)
    jawf = _lobe(CX + 0.1, jaw - 1, hw * 0.34, n * 0.22, 2.0)
    skull = _merge(skull, jawf)
    if P["hair_shape"] == "bald":
        return {}, dict((y, v) for (y, v) in skull.items() if y <= jaw), jaw
    hair = _lobe(CX + 0.9 * P["hair_asym"], cy, hw * 0.5,
                 n * 0.44, n * 0.62)
    # A second mass on ONE side only, widest several rows below the first, so
    # the two edges of the head never go flat together. Two of these placed
    # symmetrically are a pair of ears.
    # Clamped to the head's own half-width: hung further out than that it stops
    # being a fall of hair beside the face and becomes a second head.
    side = CX + (1.0 if P["hair_asym"] >= 0 else -1.0) * hw * 0.40
    fall = _lobe(side, top + n * 0.72, 1.8 + 1.6 * P["hair_mass"],
                 n * 0.3, n * 0.30 + 5.0 * P["hair_len"])
    mass = _merge(hair, fall)
    return mass, dict((y, v) for (y, v) in skull.items() if y <= jaw), jaw


_HEADS = {"span": _head_span, "mass": _head_mass,
          "derive": _head_derive, "lobe": _head_lobe}


# ============================================================ the four bodies ====

def _body_span(P, L, seed):
    """The silhouette theory of a torso: one width profile, keyframed where the
    measurement says something happens, and the widest row is the HANDS."""
    sh, hip = L["shoulder"], L["hip"]
    n = hip - sh + 1
    w = L["sh_w"]
    hand_t = 0.42 + 0.28 * _j(seed, "hand")
    keys = [(0.00, 0.82 + 0.16 * (1.0 - P["shoulder_slope"])),
            (0.10, 0.96),
            (max(0.18, hand_t - 0.22), 0.90 - 0.18 * P["waist_pinch"]),
            (hand_t, 1.00),
            (min(0.94, hand_t + 0.22), 0.92),
            (1.00, 0.84 + 0.30 * P["hip_flare"])]
    out = {}
    prev = None
    for i in range(n):
        ww = w * _profile(keys, i / float(max(1, n - 1)))
        # One pixel a side per row and no more. Nothing in any of the reference
        # silhouettes slopes; they step and then hold, and a two-pixel step
        # reads as a corner rather than as a contour.
        if prev is not None:
            ww = max(prev - 2, min(prev + 2, ww))
        out[sh + i] = _sp(ww)
        prev = ww
    return out


def _body_block(P, L, seed):
    """The hairfirst/facefirst theory of a torso: a stack of flat blocks with a
    shoulder slope on the first rows, because the whole claim of those two files
    is that the head says everything and the body's job is to not argue."""
    sh, hip = L["shoulder"], L["hip"]
    n = hip - sh + 1
    w = L["sh_w"]
    waist = w * (1.0 - 0.22 * P["waist_pinch"])
    hem = w * (0.92 + 0.34 * P["hip_flare"])
    slope = int(round(1 + 3 * P["shoulder_slope"]))
    out = {}
    for i in range(n):
        t = i / float(max(1, n - 1))
        if i < slope:
            ww = w - 2 * (slope - i)
        else:
            ww = waist + (hem - waist) * max(0.0, (t - 0.45) / 0.55)
        out[sh + i] = _sp(max(6, ww))
    return out


def _body_lobe(P, L, seed):
    """The curves theory of a torso: two shoulder caps a row out of step, a
    chest, a core and a hip whose arcs cross. The waist is not drawn anywhere --
    it is where the chest's lower arc and the hip's upper arc are both on their
    way down, which is a pinch nothing has to author."""
    sh, hip = L["shoulder"], L["hip"]
    n = max(6, hip - sh + 1)
    w = L["sh_w"] * 0.5
    off = 1.0 + 2.0 * P["shoulder_slope"]
    caps = _merge(_lobe(CX - w * 0.55, sh + 3, w * 0.55, 3.0, 4.2),
                  _lobe(CX + w * 0.55, sh + 3 + off, w * 0.55, 4.0, 3.2))
    chest = _lobe(CX, sh + n * 0.22, w, n * 0.22, n * 0.34)
    core = _lobe(CX, sh + n * 0.58, w * (1.0 - 0.26 * P["waist_pinch"]),
                 n * 0.34, n * 0.30)
    hipf = _lobe(CX, hip - 1, w * (0.94 + 0.34 * P["hip_flare"]),
                 n * 0.30, 2.4)
    body = _merge(caps, chest, core, hipf)
    return dict((y, v) for (y, v) in body.items() if sh <= y <= hip)


_BODIES = {"span": _body_span, "mass": _body_block,
           "derive": _body_block, "lobe": _body_lobe}


# =================================================================== limbs ====

def _side_limbs(P, L, torso, seed, style, y0, y1, aw, hand_n):
    """The same arms, but kept as (left, right) so the painter never fills the
    chest with sleeve."""
    arms = {"l": {}, "r": {}}
    hands = {"l": {}, "r": {}}
    for key, sgn in (("l", -1), ("r", 1)):
        for y in range(y0, y1 + 1):
            if y not in torso:
                continue
            tx0, tx1 = torso[y]
            if style == "inset":
                x0 = tx0 if sgn < 0 else tx1 - aw + 1
            elif style == "proud":
                x0 = (tx0 - 2) if sgn < 0 else (tx1 - aw + 3)
            else:
                x0 = (tx0 - 1) if sgn < 0 else (tx1 - aw + 2)
            tgt = hands[key] if y > y1 - hand_n else arms[key]
            tgt[y] = (x0, x0 + aw - 1)
    return arms, hands


def _limbs2(P, L, torso, seed):
    """Wrapper that returns per-side arms and hands for every style, including
    the lobed one, which builds its forms rather than stepping down the torso."""
    style = P["limb_style"]
    sh, hip = L["shoulder"], L["hip"]
    y0 = sh + 1 + L["shoulder_drop"]
    y1 = hip - 1 if P["lower"] not in ("skirt", "long_skirt") else \
        sh + int((hip - sh) * 0.62)
    y1 = max(y0 + 3, min(hip - 1, y1))
    aw = 2 + int(round(1.6 * P["build"]))
    if style != "lobed":
        return _side_limbs(P, L, torso, seed, style, y0, y1, aw, 2)
    arms = {"l": {}, "r": {}}
    hands = {"l": {}, "r": {}}
    for key, sgn in (("l", -1), ("r", 1)):
        cx = CX + sgn * (L["sh_w"] * 0.5 - aw * 0.30)
        mid = int((y0 + y1) / 2.0)
        # Three widths down the arm rather than one -- a sleeve widest at the
        # elbow and a cuff belling out at the wrist -- because a sleeve of one
        # width is a stick, and a stick is a straight edge however round its
        # ends are.
        arms[key] = _merge(
            _lobe(cx, mid - 1, aw * 0.75, max(1.5, (mid - y0) * 0.95),
                  max(1.5, (y1 - mid) * 0.55)),
            _lobe(cx + sgn * 0.4, max(mid + 1, y1 - 2), aw * 0.66,
                  max(1.5, (y1 - mid) * 0.7), 2.0))
        hands[key] = _lobe(cx + sgn * 0.5, y1, aw * 0.70, 1.8, 1.8)
    return arms, hands


def _legs(P, L, seed):
    """Two legs and two feet, or a skirt, or bare shins.

    The boot is a separate lump UNDER the stub rather than the end of it: in
    every reference the foot is its own form, and it is what stops two trouser
    columns reading as the legs of a chair.
    """
    ly, sole = L["leg_y"], SOLE
    style = P["leg_style"]
    gap = P["leg_gap"]
    lw = max(2, int(round((L["sh_w"] * 0.38) * (0.72 + 0.5 * P["build"]))))
    total = 2 * lw + gap
    x0 = int(round(CX - total / 2.0))
    boot_n = {"none": 0, "low": 2, "tall": max(3, (sole - ly) // 2),
              "cuffed": 3, "pointed": 2, "wrapped": max(2, (sole - ly) // 3)
              }[P["boots"]]
    legs = {"l": {}, "r": {}}
    feet = {"l": {}, "r": {}}
    for key, lx, out in (("l", x0, 1), ("r", x0 + lw + gap, 0)):
        # The two legs are a row out of step with each other, which is free and
        # stops the bottom of the figure being a mirror of itself.
        dy = 0 if key == "l" else int(_j(seed, "legstep") * 1.6)
        for y in range(ly, sole + 1):
            if style == "tapered":
                t = (y - ly) / float(max(1, sole - ly))
                w = max(2, int(round(lw * (1.0 - 0.25 * t))))
            else:
                w = lw
            a = lx + (lw - w) // 2
            legs[key][y] = (a, a + w - 1)
        if style == "lobed":
            # The lower lobe's centre sits on the sole with its reach BELOW it
            # clipped by the frame, because a superellipse excludes the row
            # where its parameter reaches one -- centred two rows up it stopped
            # at row 46 and a fiftieth of the space was standing one pixel off
            # the ground, which is invisible on a contact sheet and wrong in
            # the game.
            legs[key] = _merge(
                _lobe(lx + lw / 2.0 - 0.5, ly + (sole - ly) * 0.35, lw * 0.55,
                      (sole - ly) * 0.38, (sole - ly) * 0.30),
                _lobe(lx + lw / 2.0 - 0.8, sole - 1, lw * 0.5,
                      (sole - ly) * 0.35, 2.6))
        if boot_n:
            fy0 = sole - boot_n + 1 - dy
            for y in range(fy0, sole + 1 - dy):
                if y not in legs[key]:
                    continue
                a, b = legs[key][y]
                grow = 1 if y >= sole - 1 - dy else 0
                if P["boots"] == "pointed":
                    grow = 2 if y >= sole - dy else 0
                feet[key][y] = (a - (grow if out else 0),
                                b + (grow if not out else 0))
    return legs, feet


# ================================================================== painter ====

def _paint(cel, spans, ramp, P, cap=0.45, shf=0.26, style=None):
    """A mass, lit.

    The style is an axis rather than a house rule, because how a mass is lit is
    one of the loudest things about a sprite: `none` is a flat block with a
    contour, `flat2` is the reference's own two-tone garment, `formlit` puts the
    highlight where the surface actually turns over, and `banded` lights the
    top row and shades the bottom one, which reads as stacked plates. Four
    genuinely different looks off the same geometry.
    """
    if not spans:
        return
    style = style or P["shading"]
    light = P["light"]
    ys = sorted(spans)
    y0, y1 = ys[0], ys[-1]
    h = max(1, y1 - y0)
    # NW light puts the shade on the figure's right, NE on its left; N and flat
    # light it from straight on, which is a different figure entirely and is
    # why light direction is its own axis.
    sgn = -1 if light == "NE" else 1
    for y in ys:
        x0, x1 = spans[y]
        if x1 < x0:
            continue
        cel.row(y, x0, x1, ramp[1])
        if style == "none":
            continue
        w = x1 - x0 + 1
        u = (y - y0) / float(h)
        if style == "formlit":
            lw = int(round(w * cap * (1.0 - u) ** 1.35))
            sw = max(1, int(round(w * shf * (0.40 + 0.80 * u))))
        elif style == "banded":
            lw = w if y == y0 else 0
            sw = w if y == y1 else 1
        elif style == "flat3":
            lw = 2 if u < 0.34 else 0
            sw = 2 if w > 5 else 1
        else:                                        # flat2
            lw = 0
            sw = 2 if w > 5 else 1
        if light in ("N", "flat"):
            if y == y0 and style != "flat2":
                cel.row(y, x0, x1, ramp[0])
            if y == y1:
                cel.row(y, x0, x1, ramp[2])
            continue
        if sgn > 0:
            if lw:
                cel.row(y, x0, min(x1, x0 + lw - 1), ramp[0])
            if sw:
                cel.row(y, max(x0, x1 - sw + 1), x1, ramp[2])
        else:
            if lw:
                cel.row(y, max(x0, x1 - lw + 1), x1, ramp[0])
            if sw:
                cel.row(y, x0, min(x1, x0 + sw - 1), ramp[2])


def _contour(cel, col, place, tinted=False):
    """The outline, taken FROM the silhouette rather than drawn.

    Drawn by hand it is wrong the first time the geometry changes; derived, the
    line is closed whatever the masses did. `inside` erodes it out of the
    figure, so the silhouette the forms describe is the silhouette that ships;
    `outside` grows the figure by a pixel, which is what two of the four source
    files do and which reads heavier. Both are on the table because the weight
    of the line is a real preference and the user has never been shown both.
    """
    p = cel.p
    if place == "inside":
        edge = []
        for y in range(FH):
            for x in range(FW):
                if p[x, y][3] != 255:
                    continue
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if not (0 <= nx < FW and 0 <= ny < FH) or \
                            p[nx, ny][3] != 255:
                        edge.append((x, y))
                        break
        for (x, y) in edge:
            if tinted:
                # A contour that takes a darker step of the material it runs
                # along, rather than one flat colour for the whole figure. It
                # costs colours -- which is why both references refuse it -- but
                # it is a genuinely different look and the point here is to show
                # the user both.
                c = p[x, y]
                p[x, y] = (c[0] // 3, c[1] // 3, c[2] // 3 + 6, 255)
            else:
                p[x, y] = (col[0], col[1], col[2], 255)
        return
    grow = []
    for y in range(FH):
        for x in range(FW):
            if p[x, y][3] == 255:
                continue
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < FW and 0 <= ny < FH and p[nx, ny][3] == 255:
                        grow.append((x, y, p[nx, ny]))
                        break
                else:
                    continue
                break
    for (x, y, near) in grow:
        if tinted:
            p[x, y] = (near[0] // 3, near[1] // 3, near[2] // 3 + 6, 255)
        else:
            p[x, y] = (col[0], col[1], col[2], 255)


# ================================================================== the face ====

def _face_window(skull, y, tl, tr):
    if y not in skull:
        return None
    a, b = skull[y]
    x0, x1 = a + tl, b - tr
    return (x0, x1) if x1 >= x0 else None


def _draw_face(cel, P, L, pal, skull, mass, seed):
    """A flat bright field with dark punched into it, and as little else as the
    axes allow.

    Every extra mark on a head this size becomes a shape nobody intended and
    the unintended one wins: a full-width brow bar is a pair of goggles, a lit
    row under a dark mouth is a set of teeth, a row of shade beside a nose is a
    muzzle. So the face features are axes with `none` in every one of them, and
    a figure that spends its budget on eyes alone is a legitimate point in the
    space rather than an unfinished one.
    """
    if not skull:
        return
    ys = sorted(skull)
    jaw = ys[-1]
    sk_top = ys[0]
    n = len(ys)
    tl = tr = 0
    if mass:
        # The face window is measured off the skull and inset by however much
        # mass is framing it, so the chin taper narrows the face to a point
        # instead of the temples widening to meet it.
        a, b = skull[jaw]
        w_target = max(4, int(round((b - a + 1) * P["face_w"])))
        slack = max(0, (b - a + 1) - w_target)
        tl, tr = slack // 2, slack - slack // 2
    # THE FACE HANGS OFF THE JAW AND NOT OFF THE CROWN, and the hairline is
    # whatever is left over above it. Every reference does this -- the eye sits
    # about three rows off the chin whatever the head's height -- and the reason
    # is that a taller head is a taller HAIR MASS, not a longer forehead.
    #
    # Placed the other way round, which is how this was first written, the
    # `eye_y` axis distributed the pair across the whole face and a tall head
    # came out with FIVE ROWS of blank forehead above the brow. Decoded as text
    # that is unmistakable; at 1:1 it just reads as an oddly heavy face, and it
    # was the worst thing left on the sheet after the big-eye retune.
    chin = 1 + (1 if n >= 15 else 0)
    mouth_y = jaw - chin
    # AN EYE IS NOT A DOMINO. `eye_h` is rows of iris UNDER the lash, so four
    # is a five-row eye, and on a face of eight rows that is most of the head:
    # the first big-eye render came out as two vertical bars with a chin under
    # them. Capped at two fifths of the head, a big eye stays an eye.
    head_rows = max(3, jaw - sk_top + 1)
    eye_h = min(P["eye_h"], max(1, int(head_rows * 0.40)))
    # One row between the iris and the mouth, two on a tall head.
    drop = 1 + (1 if n >= 16 else 0)
    eye_y = mouth_y - drop - eye_h
    # `eye_y` the axis is now what it should always have been: how much BARE
    # FOREHEAD sits above the brow. Two rows reads young and open, four reads
    # heavy-browed, and the mass takes every row above that -- so the axis
    # changes the face without ever stretching it.
    fore = 2 + int(round(2.0 * P["eye_y"]))
    hairline = max(sk_top, min(eye_y - fore, jaw - 3))
    eye_y = max(hairline + 1, min(eye_y, mouth_y - 1 - eye_h))
    L["hairline"] = hairline
    L["eye_y"] = eye_y
    L["mouth_y"] = mouth_y
    L["temples"] = (tl, tr)

    sk = pal["skin"]
    for y in range(hairline, jaw + 1):
        win = _face_window(skull, y, tl, tr)
        if not win:
            continue
        cel.row(y, win[0], win[1], sk[0] if P["shading"] != "none" else sk[1])
        if P["shading"] != "none":
            side = win[1] if P["light"] != "NE" else win[0]
            cel.px(side, y, sk[1])

    win = _face_window(skull, eye_y, tl, tr)
    if not win:
        return
    fx0, fx1 = win
    fw = fx1 - fx0 + 1
    # TWO PIXELS OF CHEEK EACH SIDE, not one. A pair of eyes that reaches the
    # edge of the face is not a big eye, it is a mask -- which is exactly what
    # "big eyes" produced the first time it was wired up, a light band straight
    # across the head with two dark slits in it.
    ew = min(P["eye_w"], max(1, (fw - P["eye_gap"] - 4) // 2))
    gap = min(P["eye_gap"], max(1, fw - 2 * ew - 4))
    # ...and the pair never owns more than about three quarters of the face.
    while 2 * ew + gap > int(fw * 0.78) and ew > 1:
        ew -= 1
    band = 2 * ew + gap
    ex0 = fx0 + (fw - band) // 2
    line = pal["ink"]
    ey = pal["eye"]
    style = P["eye_style"]
    for side, x0 in ((0, ex0), (1, ex0 + ew + gap)):
        if style == "closed":
            # A closed eye is one dark row with its ends lifted, which is the
            # only way a shut eye reads at this size -- a filled block is a
            # bruise.
            cel.row(eye_y + 1, x0, x0 + ew - 1, line)
            cel.px(x0 if side == 0 else x0 + ew - 1, eye_y, line)
            continue
        if style == "dot":
            # Chrono Trigger's answer: a block of the figure's own contour
            # punched into a bright face. One colour, and it costs nothing
            # because the colour is already there.
            for k in range(min(2, eye_h)):
                cel.row(eye_y + k, x0, x0 + ew - 1, line)
            continue
        if style == "beady":
            cel.px(x0 + (0 if side else ew - 1), eye_y, line)
            cel.px(x0 + (0 if side else ew - 1), eye_y + 1, line)
            continue
        cel.row(eye_y, x0, x0 + ew - 1, line)         # the lash
        for k in range(eye_h):
            for i in range(ew):
                j = (ew - 1 - i) if side else i
                if style == "sclera_out":
                    # The sclera goes on the OUTER column: two eyes with a light
                    # pixel each on the inside read as a nose bridge with a
                    # highlight on it and the face comes out cross-eyed.
                    c = ey[0] if j == 0 else (ey[2] if k == eye_h - 1
                                              else ey[1])
                elif style == "wide":
                    c = ey[0] if (j == 0 or j == ew - 1) else ey[1]
                else:                                 # full_iris
                    # THE IRIS GROWS WITH THE EYE. Fixed at two pixels it left
                    # three columns of sclera in a five-pixel eye, and the two
                    # eyes together read as one bright band across the face --
                    # a bandit mask, which is what a big-eyed figure kept
                    # coming out as. The dark has to stay the majority of the
                    # eye at every width.
                    iw = 2 + (1 if ew >= 4 else 0) + (1 if ew >= 5 else 0)
                    pad = (ew - iw) // 2
                    c = ey[1] if pad <= j < pad + iw else ey[0]
                    if k == 0 and pad <= j < pad + iw:
                        c = ey[2]                     # the lid's own shadow
                cel.px(x0 + i, eye_y + 1 + k, c)

    _draw_brow(cel, P, pal, ex0, ew, gap, eye_y, fx0, fx1)
    _draw_nose(cel, P, pal, eye_y, mouth_y, eye_h)
    _draw_mouth(cel, P, pal, mouth_y, fx0, fx1)
    if P["age"] > 0.62:
        # One row of shade under each eye. It is the only age cue that reads at
        # 1:1 and does not turn into a pair of glasses.
        c = pal["skin"][2]
        cel.px(ex0, eye_y + eye_h + 1, c)
        cel.px(ex0 + 2 * ew + gap - 1, eye_y + eye_h + 1, c)


def _draw_brow(cel, P, pal, ex0, ew, gap, eye_y, fx0, fx1):
    kind = P["brow"]
    if kind == "none":
        return
    c = pal["hair"][2]
    bw = max(2, ew - 1)                # A BROW IS SHORTER THAN THE EYE UNDER
    # IT. At the eye's full width it is a bar, and a full-width horizontal bar
    # on a small head is a pair of goggles.
    by = eye_y - 2 if kind != "thick" else eye_y - 2
    lefts = (ex0, ex0 + ew + gap + (ew - bw))
    tilts = {"flat": (0, 0), "angled": (0, 0), "thick": (0, 0),
             "raised_one": (0, -1), "worried": (-1, 0)}[kind]
    for i, x in enumerate(lefts):
        y = by + tilts[i]
        cel.row(y, x, x + bw - 1, c)
        if kind == "thick":
            cel.row(y + 1, x, x + bw - 1, c)
        if kind == "angled":
            # One pixel of the inner end dropped, which is the whole of an
            # angry brow and costs nothing.
            cel.px(x + (bw - 1 if i == 0 else 0), y + 1, c)


def _draw_nose(cel, P, pal, eye_y, mouth_y, eye_h):
    kind = P["nose"]
    if kind == "none":
        return
    c = pal["skin"][2]
    ny = min(mouth_y - 1, eye_y + eye_h + 1)
    if kind == "dot":
        cel.px(15, ny, c)
    elif kind == "shade":
        cel.px(16, ny, c)
        cel.px(16, ny - 1, c)
    else:                                            # "long"
        for k in range(2):
            cel.px(16, ny - 1 + k, c)
        cel.px(15, ny + 0, c)


def _draw_mouth(cel, P, pal, my, fx0, fx1):
    kind = P["mouth"]
    if kind == "none":
        return
    cx = (fx0 + fx1) // 2
    # In the skin's own shade and never darker: anything lit below a dark mouth
    # line is a set of teeth, and a mouth drawn in the contour colour is a hole
    # punched through the chin.
    c = pal["skin"][2]
    if kind == "line":
        cel.row(my, cx, cx + 1, c)
    elif kind == "small":
        cel.px(cx, my, c)
    elif kind == "wide":
        cel.row(my, cx - 1, cx + 2, c)
    elif kind == "open":
        cel.row(my, cx, cx + 1, pal["ink"])
        cel.px(cx, my + 1, c)
    else:                                            # "smirk"
        cel.px(cx, my, c)
        cel.px(cx + 1, my - 1, c)


def _draw_facial_hair(cel, P, L, pal, skull, seed):
    kind = P["facial_hair"]
    if kind == "none" or not skull:
        return
    ys = sorted(skull)
    jaw = ys[-1]
    my = L.get("mouth_y", jaw - 1)
    tl, tr = L.get("temples", (0, 0))
    hr = pal["hair"]
    if kind == "stubble":
        for y in range(my, jaw + 1):
            win = _face_window(skull, y, tl, tr)
            if win:
                # A darker skin rather than hair, because stubble at this size
                # is a value and not a mass.
                cel.row(y, win[0], win[1], pal["skin"][2])
        return
    if kind == "moustache":
        win = _face_window(skull, my, tl, tr)
        if win:
            cel.row(my, win[0] + 1, win[1] - 1, hr[2])
        return
    if kind == "chops":
        for y in range(L.get("eye_y", my - 2) + 1, jaw + 1):
            win = _face_window(skull, y, tl, tr)
            if win:
                cel.px(win[0], y, hr[1])
                cel.px(win[1], y, hr[2])
        return
    if kind == "goatee":
        win = _face_window(skull, jaw, tl, tr)
        if win:
            cx = (win[0] + win[1]) // 2
            for y in range(my + 1, jaw + 2):
                cel.row(y, cx - 1, cx + 1, hr[1])
        return
    # A beard is a SECOND MASS and it is drawn from under the eye rather than
    # from under the mouth: hung off the mouth it is two rows tall and reads as
    # a chinstrap. A long one runs past the jaw and becomes part of the
    # silhouette, which is the whole reason it is on the list.
    drop = 3 if kind == "beard" else 5 + int(4 * _j(seed, "beardlen"))
    top = my - 1
    for y in range(top, jaw + 1):
        win = _face_window(skull, y, tl, tr)
        if win:
            cel.row(y, win[0], win[1], hr[1])
            cel.px(win[1], y, hr[2])
    a, b = skull[jaw]
    for i in range(drop):
        y = jaw + 1 + i
        t = i / float(max(1, drop))
        w = int(round((b - a + 1) * (0.9 - 0.55 * t)))
        x0 = int(round(CX - w / 2.0))
        cel.row(y, x0, x0 + w - 1, hr[1])
        cel.px(x0 + w - 1, y, hr[2])


# ================================================================== the hair ====

def _draw_hair(cel, P, L, pal, mass, skull, seed):
    """The mass, painted, with the face window left open below the hairline."""
    if not mass:
        return
    hr = pal["hair"]
    hairline = L.get("hairline", 10 ** 6)
    tl, tr = L.get("temples", (0, 0))
    ys = sorted(mass)
    for y in ys:
        x0, x1 = mass[y]
        win = _face_window(skull, y, tl, tr) if y >= hairline else None
        if win is None:
            cel.row(y, x0, x1, hr[1])
            sw = 2 if (x1 - x0) > 5 else 1
            if P["shading"] != "none":
                if P["light"] != "NE":
                    cel.row(y, x1 - sw + 1, x1, hr[2])
                else:
                    cel.row(y, x0, x0 + sw - 1, hr[2])
        else:
            # Below the brow the mass is TEMPLES: the window is open and
            # everything either side of it is still mass, down past the jaw.
            if win[0] - 1 >= x0:
                cel.row(y, x0, win[0] - 1, hr[1])
            if win[1] + 1 <= x1:
                cel.row(y, win[1] + 1, x1, hr[1])
                if P["shading"] != "none":
                    cel.px(x1, y, hr[2])
    if P["hair_shine"] and P["shading"] != "none":
        # Twenty rows of one flat colour is a bonnet however well the
        # silhouette is cut, and a crown highlight is the cheapest thing in the
        # file that says the mass is round.
        top = ys[0]
        for k in range(min(3, len(ys))):
            a, b = mass[top + k]
            cel.row(top + k, a + 2 + k, a + 3 + k, hr[0])
    _draw_fringe(cel, P, L, pal, mass, skull, seed)
    _draw_locks(cel, P, L, pal, mass, skull, seed)


def _draw_fringe(cel, P, L, pal, mass, skull, seed):
    """The mass's edge across the forehead.

    A clean edge all the way round is a helmet; the break has to be in RUNS
    three or four px wide, because a fringe sampled column by column comes out
    as a dotted speckle of hair and skin along the brow rather than as an
    uneven fringe.
    """
    kind = P["fringe"]
    if kind == "none" or not mass:
        return
    hairline = L.get("hairline")
    if hairline is None:
        return
    tl, tr = L.get("temples", (0, 0))
    win = _face_window(skull, hairline, tl, tr)
    if not win:
        return
    x0, x1 = win
    w = x1 - x0 + 1
    hr, sk = pal["hair"], pal["skin"]
    if kind == "step":
        cel.row(hairline, x0, x0 + w // 2, hr[1])
    elif kind == "two_notch":
        cel.row(hairline, x0, x0 + max(1, w // 3), hr[1])
        cel.row(hairline, x1 - max(1, w // 4), x1, hr[1])
    elif kind == "peak":
        cel.row(hairline, x0 + w // 2 - 1, x0 + w // 2 + 1, hr[1])
    elif kind == "swept":
        for i in range(w):
            if i < w * (0.3 + 0.5 * _j(seed, "sweep")):
                cel.px(x0 + i, hairline, hr[1])
    else:                                            # "high"
        cel.row(hairline - 1, x0 + 1, x1 - 1, sk[0])


def _draw_locks(cel, P, L, pal, mass, skull, seed):
    """What falls PAST the jaw onto the shoulders.

    The single cheapest thing that says "hair" rather than "hat" at this size,
    and the reason a jaw pinch does not read as a decapitation: the mass carries
    on over the shoulder either side of the neck that is not there. The two
    sides are never level.
    """
    if not mass or P["hair_len"] <= 0.02:
        return
    ys = sorted(mass)
    jaw = ys[-1]
    a, b = mass[jaw]
    hr = pal["hair"]
    # Capped in rows as well as in fraction: hair that keeps falling until it
    # reaches the boots is not long hair, it is a pair of curtains, and it
    # swallows every garment axis underneath it.
    n = min(14, int(round(P["hair_len"] * (SOLE - jaw) * 0.55)))
    if n <= 0:
        return
    asym = P["hair_asym"]
    nl = max(0, int(round(n * (1.0 + 0.5 * asym))))
    nr = max(0, int(round(n * (1.0 - 0.5 * asym))))
    # Four pixels is a lock. Wider than that and the two sides meet the arms
    # and the whole upper body becomes one mass of hair colour.
    tw = max(2, min(4, int(round((b - a + 1) * 0.28))))
    if P["hair_shape"] == "pigtails":
        # Two masses hanging clear of the head, which is a silhouette nothing
        # else in the shape list produces.
        for sgn, cnt in ((-1, nl), (1, nr)):
            cx = CX + sgn * ((b - a) * 0.5 + tw * 0.5)
            for i in range(cnt):
                y = jaw - 1 + i
                w = tw + (1 if 1 < i < cnt - 1 else 0)
                x0 = int(round(cx - w / 2.0))
                cel.row(y, x0, x0 + w - 1, hr[1])
                cel.px(x0 + w - 1, y, hr[2])
        return
    for i in range(max(nl, nr)):
        y = jaw + 1 + i
        if y > SOLE:
            break
        t = i / float(max(1, max(nl, nr)))
        if i < nl:
            w = max(1, int(round(tw * (1.0 - 0.5 * t))))
            cel.row(y, a, a + w - 1, hr[1])
        if i < nr:
            w = max(1, int(round(tw * (1.0 - 0.5 * t))))
            cel.row(y, b - w + 1, b, hr[2])


def _draw_headwear(cel, P, L, pal, mass, skull, seed):
    """What is on the head, if anything, and whether it or the hair owns the
    outline.

    `headwear_carries` is the axis that matters: a cap painted inside the hair's
    own silhouette is a colour change, and a hood or a brim that REPLACES the
    silhouette is a different character. The previous rounds only ever drew the
    first kind.
    """
    kind = P["headwear"]
    if kind == "none":
        return
    # THE HAT HAS TO BE A DIFFERENT MATERIAL FROM THE FACE UNDER IT, and at
    # this size material is colour. A tan cap over a tan face is not a subtle
    # hat, it is a forehead eight rows too tall -- one render had a figure whose
    # whole upper head read as a blank slab of skin for exactly this reason. So
    # the candidates are ranked by how far they are from the skin in luma and
    # the seed only chooses among the ones that actually contrast.
    sk = _luma(pal["skin"][1])
    cand = sorted((pal["accent"], pal["under"], pal["cloak"], pal["lower"]),
                  key=lambda r: -abs(_luma(r[1]) - sk))
    ramp = cand[0] if _j(P["seed"], "hatcol") > 0.45 else cand[1]
    if abs(_luma(ramp[1]) - sk) < 36:
        ramp = cand[0]
    if kind == "band":
        ramp = pal["accent"]
    ref = mass if mass else skull
    if not ref:
        return
    ys = sorted(ref)
    top, jaw = ys[0], ys[-1]
    n = len(ys)
    hairline = L.get("hairline", top + n // 2)
    carries = P["headwear_carries"]
    if kind == "band":
        y = max(top, hairline - 1)
        if y in ref:
            a, b = ref[y]
            cel.row(y, a, b, ramp[1])
            cel.row(y - 1, a + 1, b - 1, ramp[0]) if (y - 1) in ref else None
        return
    if kind == "ears":
        # Two small forms proud of the crown. Animal ears are a silhouette the
        # hair shapes cannot reach and they cost eight pixels.
        a, b = ref[top]
        for sgn in (-1, 1):
            cx = CX + sgn * (b - a) * 0.42
            for i in range(3):
                w = 3 - i
                x0 = int(round(cx - w / 2.0))
                cel.row(top - 1 - i, x0, x0 + w - 1, pal["hair"][1])
        return
    if kind == "horns":
        a, b = ref[top]
        for sgn in (-1, 1):
            cx = CX + sgn * (b - a) * 0.45
            for i in range(4):
                cel.px(cx + sgn * i * 0.6, top - i, pal["metal"][1])
                cel.px(cx + sgn * i * 0.6, top - i - 1, pal["metal"][2])
        return
    if kind == "crown":
        a, b = ref[top]
        for x in range(a + 1, b, 2):
            cel.px(x, top - 1, pal["metal"][0])
            cel.px(x, top, pal["metal"][1])
        cel.row(top + 1, a, b, pal["metal"][2])
        return
    # The covering hats: cap, brim, hood, wrap and helm all repaint the top of
    # the mass in their own ramp, and the ones that carry the outline reach past
    # it.
    cover = {"cap": 0.50, "brim": 0.46, "hood": 1.0, "wrap": 0.62,
             "helm": 0.70}[kind]
    last = top + int(round(n * cover))
    # A HAT THAT REACHES THE EYES IS NOT A HAT, IT IS A BAG. This was the single
    # worst thing in the first render: `hood` covered the whole head band and
    # what came out was a coloured tower with a body under it. The brim of
    # anything stops one row above the face window, and only the columns OUTSIDE
    # the window are allowed below that -- which is exactly what separates a
    # hood from a swimming cap anyway.
    last = min(last, hairline - 1, jaw)
    grow = (1 if carries else 0)
    tl, tr = L.get("temples", (0, 0))
    lowest = jaw if kind == "hood" else last
    for y in range(top - (1 if carries else 0), lowest + 1):
        if y in ref:
            a, b = ref[y]
        elif (y + 1) in ref:
            a, b = ref[y + 1]
            a, b = a + 1, b - 1
        else:
            continue
        if y > last:
            # Below the brim only the sides survive, so the face stays open.
            win = _face_window(skull, y, tl, tr)
            if not win:
                continue
            if win[0] - 1 >= a - grow:
                cel.row(y, a - grow, win[0] - 1, ramp[1])
            if win[1] + 1 <= b + grow:
                cel.row(y, win[1] + 1, b + grow, ramp[2])
            continue
        cel.row(y, a - grow, b + grow, ramp[1])
        if P["shading"] != "none":
            cel.px(b + grow, y, ramp[2])
            cel.px(a - grow, y, ramp[0])
    if kind == "brim":
        # A brim is a horizontal line WIDER than the head, which is the only
        # thing that makes a hat read as a hat from across a street. ONE row of
        # it: two rows of full-width dark over a face is not a brim, it is a
        # bucket, which is what the first cut drew.
        y = max(top + 1, min(last, jaw))
        a, b = ref.get(y, ref[jaw])
        cel.row(y, a - 2 - grow, b + 2 + grow, ramp[2])
    elif kind == "hood":
        # ...and past the jaw onto the shoulders, so the hood has weight hanging
        # off it rather than ending in mid-air at the chin.
        for i in range(3):
            y = jaw + 1 + i
            a, b = ref[jaw]
            cel.row(y, a - grow, a + 1, ramp[1])
            cel.row(y, b - 1, b + grow, ramp[2])
    elif kind == "wrap":
        # A knot, on one side only. Two of them are a pair of ears.
        y = min(last, jaw) - 1
        a, b = ref.get(y, ref[jaw])
        side = b if P["hair_asym"] >= 0 else a - 2
        cel.row(y, side, side + 2, ramp[0])
        cel.row(y + 1, side, side + 1, ramp[2])
    elif kind == "helm":
        # A nose guard: one column down the middle of the face, which is the
        # whole of a helmet at this size.
        y = min(last, jaw)
        cel.px(16, y + 1, ramp[2])
        cel.px(16, y + 2, ramp[2])


# ================================================================ garments ====

def _draw_garments(cel, P, L, pal, torso, seed):
    """The torso's clothing, as BLOCKS WITH EDGES.

    Nothing here is a garment unless it has an edge you could trace. A garment
    drawn as shading disappears at this size -- the reference dresses are two
    flat tones each and you can still say what they are -- so every layer is a
    field with a hard line at the bottom of it.
    """
    if not torso:
        return
    sh, hip = L["shoulder"], L["hip"]
    n = max(1, hip - sh)
    top = P["top"]
    # Where the main garment's hem falls. This is the single biggest change to
    # a figure's proportions that is not a change to its body: a vest ending at
    # the ribs and a robe ending at the ankle are not the same person.
    hem_t = {"tunic": 0.66, "coat": 0.86, "robe": 1.0, "vest": 0.48,
             "shirt": 0.58, "armour": 0.62, "dress": 1.0, "poncho": 0.74,
             "smock": 0.90}[top]
    hem_t = max(0.30, min(1.0, hem_t * (0.72 + 0.55 * P["top_len"])))
    hem = sh + int(round(n * hem_t))
    L["hem"] = hem
    waist = sh + int(round(n * (0.48 + 0.18 * P["top_len"])))
    L["waist"] = waist

    main = pal["top"]
    under = pal["under"]
    # The layer under the main garment, which is what carries the figure from
    # the hem to the boots when the main one stops early. Without it a vest is
    # a bare chest.
    _paint(cel, _band(torso, hem + 1, hip), pal["lower"], P)
    _paint(cel, _band(torso, sh, hem), main, P)
    if top in ("dress", "robe"):
        # A bodice over a skirt: two fields of the same garment with a hard
        # line between them, which is the cheapest way a long garment stops
        # being one column of cloth.
        _paint(cel, _band(torso, sh, waist), under, P)
    if top == "poncho":
        # A poncho is a shape with a point in it and no sleeves, and at this
        # size the point is the whole tell.
        for y in range(waist, hem + 1):
            if y in torso:
                a, b = torso[y]
                k = (y - waist)
                cel.row(y, a + k, b - k, main[1])
    if top == "armour":
        # Plate reads as horizontal bands with a lit top edge, which is a
        # different thing from cloth and costs nothing but the rows.
        for y in range(sh, hem + 1, 3):
            if y in torso:
                a, b = torso[y]
                cel.row(y, a, b, pal["metal"][0])
                if y + 1 in torso:
                    a, b = torso[y + 1]
                    cel.row(y + 1, a, b, pal["metal"][2])

    _draw_pattern(cel, P, L, pal, torso, sh, hem, seed)
    _draw_collar(cel, P, L, pal, torso, sh)
    _draw_belt(cel, P, L, pal, torso, waist, hem)
    if P["apron"]:
        # An apron is a lighter field inset from both edges with its own hem,
        # and it is the cheapest way to say a figure works for a living.
        for y in range(sh + 3, hem + 1):
            if y in torso:
                a, b = torso[y]
                cel.row(y, a + 2, b - 2, under[0])
                cel.px(b - 2, y, under[2])
        for y in (sh + 1, sh + 2):
            if y in torso:
                a, b = torso[y]
                cel.px(a + 4, y, under[1])
                cel.px(b - 4, y, under[1])
    # The hem itself: one row of the garment's own dark. A garment with no edge
    # at the bottom is a colour change, and a colour change is not a coat.
    if hem in torso and hem < hip:
        a, b = torso[hem]
        cel.row(hem, a, b, main[2])


def _draw_pattern(cel, P, L, pal, torso, sh, hem, seed):
    kind = P["pattern"]
    if kind == "none":
        return
    acc, main = pal["accent"], pal["top"]
    if kind == "hem_band":
        for k in range(2):
            y = hem - k
            if y in torso:
                a, b = torso[y]
                cel.row(y, a, b, acc[1 + k % 2])
    elif kind == "stripe":
        for y in range(sh + 2, hem + 1):
            if y in torso:
                a, b = torso[y]
                cel.px((a + b) // 2, y, acc[1])
                cel.px((a + b) // 2 + 1, y, acc[2])
    elif kind == "quilt":
        # Seams that FOLLOW the form rather than being ruled down it, because
        # at this size a lapel is its seams and nothing else.
        for y in range(sh + 2, hem + 1):
            if y in torso:
                a, b = torso[y]
                cel.px(a + int(round((b - a) * 0.30)), y, main[2])
                cel.px(a + int(round((b - a) * 0.70)), y, main[2])
    elif kind == "cross":
        for y in range(sh + 2, hem + 1):
            if y in torso:
                a, b = torso[y]
                t = (y - sh) / float(max(1, hem - sh))
                cel.px(a + int(round((b - a) * t)), y, acc[1])
    elif kind == "trim":
        for y in range(sh + 1, hem + 1):
            if y in torso:
                a, b = torso[y]
                cel.px(a, y, acc[1])
                cel.px(b, y, acc[2])
    elif kind == "dots":
        for y in range(sh + 3, hem, 3):
            if y in torso:
                a, b = torso[y]
                for x in range(a + 2, b - 1, 4):
                    cel.px(x, y, acc[0])
    else:                                            # "patch"
        y0 = sh + (hem - sh) // 2
        for y in range(y0, min(hem, y0 + 3)):
            if y in torso:
                a, b = torso[y]
                cel.row(y, a + 2, a + 4, acc[1])


def _draw_collar(cel, P, L, pal, torso, sh):
    kind = P["collar"]
    if kind == "none" or sh not in torso:
        return
    a, b = torso[sh]
    acc, under = pal["accent"], pal["under"]
    if kind == "band":
        cel.row(sh, a + 2, b - 2, acc[1])
    elif kind == "wide":
        cel.row(sh, a, b, acc[1])
        cel.row(sh + 1, a + 2, b - 2, acc[2])
    elif kind == "high":
        cel.row(sh - 1, a + 3, b - 3, acc[1])
        cel.row(sh, a + 3, b - 3, acc[2])
    elif kind == "fur":
        # Fur is an uneven edge, and uneven is the whole of the tell; a ruled
        # band is a scarf.
        for i, x in enumerate(range(a, b + 1)):
            cel.px(x, sh - (i % 2), under[0])
            cel.px(x, sh + 1 - (i % 2), under[2])
    elif kind == "ruff":
        cel.row(sh - 1, a + 1, b - 1, under[0])
        cel.row(sh, a, b, under[1])
        cel.row(sh + 1, a + 2, b - 2, under[2])
    else:                                            # "v"
        for i in range(3):
            cel.px(15 - i + 3, sh + i, under[0])
            cel.px(16 + i - 3, sh + i, under[0])


def _draw_belt(cel, P, L, pal, torso, waist, hem):
    kind = P["belt"]
    if kind == "none":
        return
    y = min(waist, hem)
    if y not in torso:
        return
    a, b = torso[y]
    acc = pal["accent"]
    metal = pal["metal"]
    if kind == "thin":
        cel.row(y, a, b, acc[2])
    elif kind == "wide":
        cel.row(y, a, b, acc[1])
        cel.row(y + 1, a, b, acc[2])
        cel.px(15, y, metal[0])
        cel.px(16, y, metal[1])
    elif kind == "sash":
        # A sash runs diagonally, which is the only belt that changes the
        # figure's internal geometry rather than ruling a line across it.
        for i in range(hem - waist + 3):
            yy = waist - 2 + i
            if yy in torso:
                aa, bb = torso[yy]
                x = aa + int(round((bb - aa) * (i / float(
                    max(1, hem - waist + 2)))))
                cel.px(x, yy, acc[1])
                cel.px(x + 1, yy, acc[2])
    else:                                            # "double"
        cel.row(y, a, b, acc[2])
        if y + 2 in torso:
            aa, bb = torso[y + 2]
            cel.row(y + 2, aa, bb, acc[2])


def _draw_lower(cel, P, L, pal, torso, legs, feet, seed):
    """Trousers, a skirt or bare shins, and whatever is on the feet."""
    kind = P["lower"]
    lower, boot, skin = pal["lower"], pal["boot"], pal["skin"]
    if kind in ("skirt", "long_skirt"):
        # A skirt replaces the legs with one mass, which is a completely
        # different silhouette from the knees down and is why it is an axis
        # rather than a recolour.
        hip = L["hip"]
        drop = int((SOLE - hip) * (0.55 if kind == "skirt" else 0.86))
        a, b = torso[hip] if hip in torso else _sp(L["sh_w"])
        w0 = b - a + 1
        skirt = {}
        for i in range(drop + 1):
            y = hip + i
            w = w0 * (1.0 + 0.55 * (i / float(max(1, drop))))
            skirt[y] = _sp(min(26, w))
        _paint(cel, skirt, pal["top"] if P["top"] in ("dress", "robe")
               else lower, P)
        y = hip + drop
        if y in skirt:
            a, b = skirt[y]
            cel.row(y, a, b, (pal["top"] if P["top"] in ("dress", "robe")
                              else lower)[2])
        # Two shins and two feet below the hem, so the figure is standing on
        # something rather than hovering on a cone.
        for key in ("l", "r"):
            for yy in range(y + 1, SOLE + 1):
                if yy in legs[key]:
                    p, q = legs[key][yy]
                    cel.row(yy, p, q, skin[1] if P["boots"] == "none"
                            else boot[1])
        for key in ("l", "r"):
            _paint(cel, dict((yy, v) for (yy, v) in feet[key].items()
                             if yy > y), boot, P)
        return
    cut = {"trousers": 1.0, "shorts": 0.45, "bare": 0.0}[kind]
    hipy = L["leg_y"]
    for key in ("l", "r"):
        seg = legs[key]
        if not seg:
            continue
        ys = sorted(seg)
        split = ys[0] + int(round(len(ys) * cut))
        _paint(cel, dict((y, v) for (y, v) in seg.items() if y < split),
               lower, P)
        _paint(cel, dict((y, v) for (y, v) in seg.items() if y >= split),
               skin, P)
        _paint(cel, feet[key], boot, P)
        if P["boots"] == "cuffed" and feet[key]:
            # A cuff is the line between the boot and the leg, so the boot is a
            # separate lump and not the bottom of the trouser painted brown.
            y = min(feet[key])
            a, b = feet[key][y]
            cel.row(y - 1, a, b, boot[0])
        if P["boots"] == "wrapped" and feet[key]:
            for y in sorted(feet[key])[::2]:
                a, b = feet[key][y]
                cel.row(y, a, b, boot[2])


def _draw_sleeves(cel, P, L, pal, arms, hands, seed):
    """The sleeve is a VALUE, not an edge.

    An arm drawn in the chest's own colour with one column of contour beside it
    is a wider chest with a line on it; what makes it an arm is that it is a
    different tone or a different material from the torso it lies on.
    """
    kind = P["sleeve"]
    main, skin = pal["top"], pal["skin"]
    for key in ("l", "r"):
        a = arms[key]
        if not a:
            continue
        ys = sorted(a)
        if kind == "none":
            _paint(cel, a, skin, P)
        elif kind == "short":
            n = max(1, len(ys) // 3)
            _paint(cel, dict((y, a[y]) for y in ys[:n]), main, P)
            _paint(cel, dict((y, a[y]) for y in ys[n:]), skin, P)
        elif kind == "puff":
            # A sleeve that is wider at the shoulder than at the wrist, which
            # gives the arm two widths instead of one.
            n = max(1, len(ys) // 3)
            puff = {}
            for i, y in enumerate(ys[:n]):
                x0, x1 = a[y]
                g = 1 if key == "r" else -1
                puff[y] = (x0 + (0 if key == "r" else -1),
                           x1 + (1 if key == "r" else 0))
            _paint(cel, puff, main, P, style="flat3")
            _paint(cel, dict((y, a[y]) for y in ys[n:]), main, P)
        elif kind == "banded":
            _paint(cel, a, main, P)
            for y in ys[::3]:
                x0, x1 = a[y]
                cel.row(y, x0, x1, pal["accent"][1])
        else:
            _paint(cel, a, main, P)
        _paint(cel, hands[key], skin, P)
        if P["accessory"] == "gloves":
            _paint(cel, hands[key], pal["boot"], P)


def _draw_cloak(cel, P, L, pal, torso, seed):
    """A cloak, drawn BEFORE the body so it reads as hanging behind it.

    The first cut of this was a rectangle two pixels wider than the torso at
    every row, and what it drew was not a cloak, it was a door: a flat slab with
    two straight sides and a square bottom, with a person standing in front of
    it. So this one is built the way a hanging cloth actually reads -- it
    SPRINGS from the shoulders, which means the top two rows are narrower than
    the shoulder and not wider, it widens as it falls, and its hem is a curve
    rather than a ruled line. It is the only garment that changes the outline at
    the shoulder and at the hem at the same time, which is what makes it worth
    the geometry.
    """
    kind = P["cloak"]
    if kind == "none" or not torso:
        return
    sh, hip = L["shoulder"], L["hip"]
    drop = {"half": 0.55, "full": 0.88, "cape": 0.32}[kind]
    last = sh + int(round((SOLE - sh) * drop))
    ramp = pal["cloak"]
    base = torso.get(sh, torso[min(torso)])
    sh_w = base[1] - base[0] + 1
    form = {}
    for i, y in enumerate(range(sh, last + 1)):
        t = i / float(max(1, last - sh))
        # Narrower than the shoulder for the first two rows, then out past it:
        # a cloth that is at its widest where it is pinned is a curtain rail.
        # TWO PIXELS OF CLOTH EITHER SIDE, and that is the whole cloak. The
        # first cut gave it the shoulder's width plus seven and drew a
        # twenty-seven-pixel slab from the collar to the ankle -- not a cloak, a
        # DOORWAY, with a person standing in front of it. What a cloak actually
        # is at this size is a rim of a second colour down the outside of the
        # figure and a hem below it; anything wider stops being worn.
        if i == 0:
            w = sh_w - 1
        elif i == 1:
            w = sh_w + 1
        else:
            w = sh_w + 2 + int(round(2 * t))
        form[y] = _sp(min(26, w))
    # The bottom corners are pulled in one pixel, because a ruled horizontal
    # edge wider than the figure is a shelf and the eye reads it as one.
    if last in form:
        a, b = form[last]
        form[last] = (a + 1, b - 1)
    _paint(cel, form, ramp, P)
    if last in form:
        a, b = form[last]
        cel.row(last, a, b, ramp[2])
    if kind != "cape":
        # A vertical break down the middle, so the back of the cloak is not one
        # unbroken field: at this size a fold is its seam and nothing else.
        for y in range(sh + 2, last):
            if y in form:
                cel.px(16, y, ramp[2])


def _draw_prop(cel, P, L, pal, torso, seed):
    """A carried object, and it is ALLOWED to break the silhouette.

    This is the one place the figure is permitted to stop being a column: a
    staff running the full height or a pack standing proud of the shoulders
    changes the shape a reader resolves from across a street more than any
    garment does.
    """
    kind = P["prop"]
    if kind == "none":
        return
    sgn = 1 if P["prop_side"] else -1
    sh, hip = L["shoulder"], L["hip"]
    base = torso.get(hip, _sp(L["sh_w"]))
    edge = base[1] + 2 if sgn > 0 else base[0] - 2
    wood = pal["boot"]
    metal = pal["metal"]
    acc = pal["accent"]
    if kind in ("staff", "broom", "hammer"):
        x = max(1, min(FW - 2, edge))
        y0 = L["crown"] + 2 if kind != "hammer" else sh
        for y in range(y0, SOLE + 1):
            cel.px(x, y, wood[1])
            cel.px(x + sgn, y, wood[2])
        if kind == "staff":
            for k in range(3):
                cel.px(x - 1 + k, y0 - 1, acc[1])
            cel.px(x, y0 - 2, acc[0])
        elif kind == "broom":
            for i in range(4):
                cel.row(SOLE - i, x - 2, x + 2, wood[0] if i % 2 else wood[1])
        else:
            cel.row(y0 - 1, x - 2, x + 2, metal[1])
            cel.row(y0 - 2, x - 2, x + 2, metal[0])
        return
    if kind == "satchel":
        y = hip - 3
        x = edge - (3 if sgn > 0 else 0)
        for k in range(4):
            cel.row(y + k, x, x + 3, wood[1])
        cel.row(y, x, x + 3, wood[0])
        # The strap crosses the chest, which is what makes a bag read as worn
        # rather than as a box floating at the hip.
        for i in range(sh + 1, y):
            t = (i - sh) / float(max(1, y - sh))
            xx = int(round(CX + sgn * (t * (x - CX))))
            cel.px(xx, i, wood[2])
        return
    if kind == "pack":
        for sgn2 in (-1, 1):
            a, b = torso.get(sh + 2, base)
            x = b + 1 if sgn2 > 0 else a - 2
            for y in range(sh, sh + 6):
                cel.row(y, x, x + 1, wood[1])
            cel.row(sh, x, x + 1, wood[0])
        return
    if kind == "lantern":
        x = edge
        y = hip - 1
        cel.row(y, x - 1, x + 1, metal[2])
        cel.row(y + 1, x - 1, x + 1, acc[0])
        cel.row(y + 2, x - 1, x + 1, acc[1])
        cel.row(y + 3, x - 1, x + 1, metal[2])
        cel.px(x, y - 1, metal[1])
        return
    if kind == "book":
        x = edge - (2 if sgn > 0 else 0)
        y = hip - 3
        for k in range(4):
            cel.row(y + k, x, x + 2, acc[1])
        cel.row(y, x, x + 2, acc[0])
        cel.px(x + (0 if sgn > 0 else 2), y + 2, pal["skin"][0])
        return
    if kind == "sword":
        x = edge
        for i in range(10):
            cel.px(x - i // 3 * sgn, sh + 4 + i, metal[1])
            cel.px(x - i // 3 * sgn + sgn, sh + 4 + i, metal[2])
        cel.row(sh + 3, x - 1, x + 1, wood[1])
        return
    if kind == "basket":
        y = hip
        x = edge
        for k in range(4):
            w = 4 - abs(k - 1)
            cel.row(y + k, x - w // 2, x + w // 2, wood[1])
        cel.row(y, x - 2, x + 2, wood[0])
        return


def _draw_accessory(cel, P, L, pal, torso, skull, seed):
    kind = P["accessory"]
    if kind in ("none", "gloves"):
        return
    sh = L["shoulder"]
    acc, metal = pal["accent"], pal["metal"]
    if kind == "scarf" and sh in torso:
        a, b = torso[sh]
        cel.row(sh, a, b, acc[1])
        cel.row(sh + 1, a + 1, b - 1, acc[2])
        # One tail, hanging on one side, because a scarf with two level tails
        # is a bib.
        for i in range(4):
            cel.px(a + 2, sh + 2 + i, acc[1])
            cel.px(a + 3, sh + 2 + i, acc[2])
    elif kind == "necklace" and sh + 1 in torso:
        a, b = torso[sh + 1]
        cel.px((a + b) // 2, sh + 2, metal[0])
        cel.px(a + 3, sh + 1, metal[1])
        cel.px(b - 3, sh + 1, metal[1])
    elif kind == "earring" and skull:
        ys = sorted(skull)
        y = L.get("eye_y", ys[-1] - 2) + 1
        if y in skull:
            a, b = skull[y]
            cel.px(b, y + 1, metal[0])
    elif kind == "pouch":
        y = L.get("waist", sh + 6)
        if y in torso:
            a, b = torso[y]
            cel.row(y + 1, a + 2, a + 4, pal["boot"][1])
            cel.row(y + 2, a + 2, a + 4, pal["boot"][2])
    elif kind == "bracers":
        pass                                          # handled with the hands
    elif kind == "pauldron" and sh in torso:
        # One shoulder only. A symmetrical pair reads as armour the figure is
        # wearing; one reads as a thing that happened to the figure.
        a, b = torso[sh]
        for k in range(3):
            cel.row(sh + k, b - 3 + k, b + 1 - k, metal[1])
        cel.row(sh, b - 3, b + 1, metal[0])
    elif kind == "glasses":
        y = L.get("eye_y")
        if y is None or not skull:
            return
        win = _face_window(skull, y, *L.get("temples", (0, 0)))
        if win:
            cel.px(win[0], y + 1, metal[2])
            cel.px(win[1], y + 1, metal[2])
            cel.row(y + 1, (win[0] + win[1]) // 2, (win[0] + win[1]) // 2 + 1,
                    metal[2])


# ================================================================ the figure ====

# The optional elements, each of which is one more distinct colour-blocked
# thing on the figure, paired with the value that switches it off and a default
# to switch it on with. Order matters: it is the order `_blocks` adds them in,
# and it runs cheapest-and-most-legible first, so a figure asked for five blocks
# gets a belt and boots before it gets an earring.
_OPTIONAL = (("boots", "none", ("low", "tall", "cuffed", "pointed")),
             ("belt", "none", ("thin", "wide", "sash")),
             ("collar", "none", ("band", "wide", "high", "fur")),
             ("pattern", "none", ("hem_band", "trim", "stripe", "quilt")),
             ("headwear", "none", ("band", "cap", "brim", "wrap")),
             ("prop", "none", ("staff", "satchel", "lantern", "book")),
             ("accessory", "none", ("scarf", "necklace", "pouch", "bracers")),
             ("cloak", "none", ("half", "cape")))


_OPT_ON = dict((k, d) for (k, _off, d) in _OPTIONAL)


def _blocks(P, seed):
    """Push the figure towards `colour_blocks` distinct colour-blocked elements.

    THE REFERENCES HAVE FIVE TO SEVEN AND OUR PREVIOUS ATTEMPTS HAD THREE TO
    FOUR, and that gap is most of why the old figures read as flat: a person
    made of a head, a shirt and a pair of legs has nothing for the eye to count.
    Left to the independent axes the count is a binomial centred wherever the
    per-axis `none` weights happen to put it, which is not a thing anybody can
    swipe on -- so this makes the count itself the axis and lets the individual
    choices fall out of it.

    Deterministic from the seed, so a figure still redraws from its params.
    """
    # Four blocks are on every figure and cannot be switched off -- the head
    # mass, the skin, the main garment and the lower garment -- so the count
    # starts there and `_OPTIONAL` moves it up.
    #
    # IT ONLY EVER ADDS. The first cut also removed, to hit the number exactly,
    # and what that did was strip the hat off half the figures in the space:
    # `colour_blocks` and `headwear` were both trying to own whether there is a
    # hat, and the one that ran last won. An element's own axis already has
    # `none` in it, so absence is expressible there; this axis is a FLOOR, which
    # is also the only direction the brief actually asked for -- the references
    # carry five to seven blocks and the figures this replaces carried three.
    on = [k for (k, off, _d) in _OPTIONAL if P[k] != off]
    want = P["colour_blocks"]
    have = 4 + len(on)
    if have >= want:
        return P
    P = dict(P)
    order = sorted((k for (k, off, _d) in _OPTIONAL),
                   key=lambda k: _j(seed, "blk" + k))
    for k in [a for a in order if a not in on]:
        if have >= want:
            break
        choices = _OPT_ON[k]
        P[k] = choices[int(_j(seed, "blkv" + k) * len(choices))]
        have += 1
    return P


def _landmarks(P):
    """Where everything is, before any grammar has an opinion about it."""
    rows = P["height_rows"]
    crown = SOLE - rows + 1
    head_h = int(round(rows * P["head_frac"]))
    # Capped in rows as well as in fraction: at 0.40 of a 46-row figure the head
    # is eighteen rows, and beyond that the face gets no wider while the mass
    # around it does, which is the difference between a big head and a wig.
    head_h = max(8, min(rows - 16, min(19, head_h)))
    jaw = crown + head_h - 1
    leg_h = int(round(rows * P["leg_frac"]))
    leg_h = max(4, min(rows - head_h - 6, leg_h))
    # THE COEFFICIENT WAS 0.17 AND IT SHOULD ALWAYS HAVE BEEN 0.42. At 0.17
    # the expression evaluated to five to ten for every figure in the space, so
    # `max(10, ...)` won every time: EVERY figure had a ten-pixel shoulder,
    # `build` was inert, and the face window that follows from it was five to
    # nine pixels -- which is why "big eyes" could not land however the eye
    # axes were set, the eye was being clamped to fit a porthole. The three
    # references measure a widest row of 0.52 of their height and a shoulder a
    # little under that; 0.42 puts a mid-build figure there.
    sh_w = 2 * int(round(rows * 0.42 * (0.66 + 0.62 * P["build"]) / 2.0))
    sh_w = max(10, min(22, sh_w))
    # The head may beat the shoulders -- every reference head does, and a figure
    # whose widest row is its shoulder is a wardrobe -- but by a bounded amount,
    # because a head eight pixels wider than the body it stands on is a lollipop
    # rather than a person.
    head_w = int(round(sh_w * P["head_shoulder"]))
    head_w = max(9, min(22, min(sh_w + 6, head_w)))
    # ...and never much wider than the head is tall. A head band nineteen rows
    # deep and twenty-two across is a crate however well its corners are
    # rounded, and all three reference heads measure taller than they are wide
    # -- Abigail is fourteen across sixteen rows, which is the +2 this allows.
    head_w = min(head_w, head_h + 2)
    return {"crown": crown, "jaw": jaw, "rows": rows, "head_h": head_h,
            "leg_h": leg_h, "sh_w": sh_w, "head_w": head_w}


def _finish_landmarks(P, L):
    """The body's rows, recomputed after the head has had its say -- because the
    derive grammar is allowed to move the jaw and the body is then whatever is
    left over, which is the whole of that grammar's claim."""
    jaw = L["jaw"]
    L["shoulder"] = min(SOLE - 8, jaw + 1 + P["neck"])
    L["shoulder_drop"] = 1 if P["hair_len"] > 0.3 else 0
    leg_h = max(4, min(SOLE - L["shoulder"] - 5, L["leg_h"]))
    L["leg_y"] = SOLE - leg_h + 1
    L["hip"] = L["leg_y"] - 1
    return L


def draw(params):
    """One 32x48 RGBA figure, feet on row 47, deterministic given `params`.

    The call order below IS the model and it is written out in one place rather
    than emerging from wherever the drawing happens to sit: the cloak is behind
    everything, the body is next, the head goes on LAST of the masses so the jaw
    is one form lying on another rather than a join between two, and the contour
    is derived from the finished alpha so it cannot be left open by any
    combination of axes.
    """
    P = params
    seed = P.get("seed", 0)

    P = _blocks(P, seed)
    if P["hair_shape"] == "bald":
        # Everything the head axes do assumes the reader recognises a
        # crown-shaped mass; take the mass away and a bare dome over a face is
        # an egg with features printed on it. So a bald figure with neither a
        # hat nor facial hair is given a substitute mass -- the substitute is
        # chosen from the seed, so the figure still redraws from its params
        # alone -- and the head itself shrinks, because without hair on it there
        # is no volume to account for the width.
        P = dict(P)
        if P["headwear"] == "none" and P["facial_hair"] in ("none", "stubble"):
            P["headwear"] = ("wrap", "cap", "band", "hood", "helm")[
                int(_j(seed, "baldfix") * 5)]
        P["head_shoulder"] = P["head_shoulder"] * 0.82
    pal = _palette(P)
    L = _landmarks(P)
    mass, skull, jaw = _HEADS[P["head_grammar"]](P, L, seed)
    L["jaw"] = jaw
    _finish_landmarks(P, L)
    torso = _BODIES[P["grammar"]](P, L, seed)
    if not torso:
        torso = _body_block(P, L, seed)
    arms, hands = _limbs2(P, L, torso, seed)
    legs, feet = _legs(P, L, seed)

    cel = Cel()
    _draw_cloak(cel, P, L, pal, torso, seed)
    if P["neck"] and skull:
        # THE NECK HAS TO EXIST IF THE AXIS SAYS IT DOES. It did not, and the
        # result was a head floating two rows above its own shoulders -- the
        # axis moved the shoulder down and nothing filled the gap. Narrow, and
        # in the skin's shade rather than its base, because a lit column between
        # two masses reads as a second chin.
        a, b = skull[jaw]
        nw = max(3, (b - a + 1) // 2)
        nx = int(round(CX - nw / 2.0))
        for i in range(P["neck"] + 1):
            cel.row(jaw + i, nx, nx + nw - 1, pal["skin"][1])
            cel.px(nx + nw - 1, jaw + i, pal["skin"][2])
    _draw_lower(cel, P, L, pal, torso, legs, feet, seed)
    _draw_garments(cel, P, L, pal, torso, seed)
    _draw_sleeves(cel, P, L, pal, arms, hands, seed)
    _draw_accessory(cel, P, L, pal, torso, skull, seed)
    # The skull is painted before the face so the face's own window can be cut
    # out of a field that already exists, which is what lets a chin taper pull
    # the face to a point instead of the temples widening to meet it.
    _paint(cel, skull, pal["skin"], P)
    _draw_face(cel, P, L, pal, skull, mass, seed)
    _draw_hair(cel, P, L, pal, mass, skull, seed)
    _draw_facial_hair(cel, P, L, pal, skull, seed)
    _draw_headwear(cel, P, L, pal, mass, skull, seed)
    _draw_prop(cel, P, L, pal, torso, seed)

    if P["jaw_seam"] and skull:
        # There is no neck in any of the references and there is rarely one
        # here, so the chin sits on the collar -- and two lit fields touching
        # read as one blob from across a street. One row of the figure's own
        # dark under the chin is the whole fix.
        a, b = skull[jaw]
        tl, tr = L.get("temples", (0, 0))
        cel.row(jaw + 1 + P["neck"], a + tl - 1, b - tr + 1, pal["ink"])

    if P["outline_mode"] != "none":
        _contour(cel, pal["line"], P["outline_place"],
                 tinted=(P["outline_mode"] == "tinted"))
    if P["shadow"]:
        # Without one the figure floats. Centred rather than offset, because it
        # can stand anywhere and a baked light direction is wrong three quarters
        # of the time.
        p = cel.p
        for y in range(SOLE - 2, FH):
            for x in range(FW):
                if p[x, y][3]:
                    continue
                if ((x - CX) / 10.0) ** 2 + ((y - SOLE - 0.5) / 3.0) ** 2 <= 1:
                    p[x, y] = (24, 18, 26, 110)
    return cel.img


# ================================================================ the check ====
#
# The acceptance test is diversity and nothing else, so it is measured rather
# than asserted. `main()` draws two hundred figures with two hundred seeds,
# reports the spread on every axis a number can be put on, and writes a contact
# sheet -- because the numbers can all look healthy while the sheet still shows
# one character in two hundred hats, and only the sheet can catch that.

def _mask(im):
    p = im.load()
    return frozenset((x, y) for y in range(FH) for x in range(FW)
                     if p[x, y][3] == 255)


def _stats(im):
    p = im.load()
    cols = {}
    rows = []
    for y in range(FH):
        xs = [x for x in range(FW) if p[x, y][3] == 255]
        if xs:
            rows.append((y, min(xs), max(xs)))
        for x in xs:
            cols[p[x, y][:3]] = cols.get(p[x, y][:3], 0) + 1
    if not rows:
        return None
    top, bot = rows[0][0], rows[-1][0]
    wide = max(b - a + 1 for (_y, a, b) in rows)
    sats = []
    best, best_n = None, -1
    for c, n in cols.items():
        h, sa, v = colorsys.rgb_to_hsv(c[0] / 255.0, c[1] / 255.0,
                                       c[2] / 255.0)
        sats.append(sa)
        # THE FIGURE'S HUE IS ITS BIGGEST COLOURED BLOCK, not the mean of its
        # colours. Averaging hue arithmetically is meaningless on a wheel --
        # red at 0.02 and red at 0.98 average to cyan -- and the first version
        # of this report did exactly that and claimed every figure was green.
        # Near-greys are skipped because their hue is noise.
        if sa > 0.18 and v > 0.12 and n > best_n:
            best, best_n = h, n
    return {"px": sum(len(range(a, b + 1)) for (_y, a, b) in rows),
            "opaque": sum(cols.values()),
            "height": bot - top + 1, "width": wide,
            "colours": len(cols),
            "hue": best if best is not None else 0.0,
            "sat": sum(sats) / len(sats),
            "top": top}


def _hist(vals, lo, hi, bins=12, width=44):
    b = [0] * bins
    for v in vals:
        k = int((v - lo) / float(hi - lo) * bins)
        b[max(0, min(bins - 1, k))] += 1
    m = max(1, max(b))
    out = []
    for i, n in enumerate(b):
        a = lo + (hi - lo) * i / float(bins)
        out.append("    %7.2f %-*s %d" % (a, width, "#" * int(
            round(n * width / float(m))), n))
    return "\n".join(out)


def measure(params):
    """The landmarks a given params dict actually produced, for the report.

    It re-runs the head builder rather than guessing from the pixels, because
    the derive grammar's whole claim is that the head's height is an OUTPUT and
    a report that quotes the requested `head_frac` back at you cannot see that.
    """
    P = params
    if P["hair_shape"] == "bald":
        P = dict(P)
        P["head_shoulder"] = P["head_shoulder"] * 0.82
    L = _landmarks(P)
    _mass, _skull, jaw = _HEADS[P["head_grammar"]](P, L, P.get("seed", 0))
    rows = float(SOLE - L["crown"] + 1)
    return {"head_rows": jaw - L["crown"] + 1,
            "head_frac": (jaw - L["crown"] + 1) / rows,
            "rows": rows, "sh_w": L["sh_w"], "head_w": L["head_w"]}


def main():
    import time
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(here, ".scratch", "charspace")
    os.makedirs(out, exist_ok=True)

    n = 200
    figs, stats, params = [], [], []
    t0 = time.time()
    for i in range(n):
        rng = random.Random(1000 + i)
        p = sample(rng)
        im = draw(p)
        figs.append(im)
        params.append(p)
        s = _stats(im)
        if s:
            s["grammar"] = p["grammar"]
            s["head_grammar"] = p["head_grammar"]
            s["head_frac"] = s["height"] and (
                p["head_frac"])
            stats.append(s)
    dt = (time.time() - t0) / n
    print("drew %d figures, %.2f ms each" % (n, dt * 1000))

    masks = [_mask(im) for im in figs]
    uniq = len(set(masks))
    # Pairwise silhouette distance on a sample, because 200x200 masks is 20k
    # set operations and the number does not get better for spending them all.
    import itertools
    pairs = list(itertools.islice(itertools.combinations(range(n), 2), 4000))
    jac = []
    for (i, k) in pairs:
        a, b = masks[i], masks[k]
        u = len(a | b)
        jac.append(1.0 - (len(a & b) / float(u)) if u else 0.0)
    print("distinct opaque masks: %d / %d" % (uniq, n))
    print("mean pairwise silhouette difference (Jaccard): %.3f  "
          "(min %.3f, max %.3f)" % (sum(jac) / len(jac), min(jac), max(jac)))

    def col(k):
        return [s[k] for s in stats]

    for key, lo, hi in (("opaque", 0, 900), ("height", 24, 48),
                        ("width", 8, 32), ("colours", 1, 32),
                        ("hue", 0.0, 1.0), ("sat", 0.0, 1.0)):
        v = col(key)
        print("\n%s   mean %.2f  min %.2f  max %.2f" % (
            key, sum(v) / float(len(v)), min(v), max(v)))
        print(_hist(v, lo, hi))

    hf = [measure(p)["head_frac"] for p in params]
    print("\nhead_frac AS DRAWN  mean %.3f  min %.3f  max %.3f"
          % (sum(hf) / len(hf), min(hf), max(hf)))
    print(_hist(hf, 0.15, 0.45))

    # Reported off the EFFECTIVE params, after `_blocks` has added or removed
    # optional elements to hit the requested count: reporting the sampled ones
    # would quote a headwear distribution the figures do not actually have.
    eff = [_blocks(p, p["seed"]) for p in params]
    # MEASURED OFF THE PIXELS, not off the params. The params-level count is a
    # count of intentions -- an accessory can be drawn behind a sleeve and never
    # reach the frame -- and the question the reference number answers is how
    # many colour fields a reader can actually pick out. So this asks which
    # material ramps ended up owning at least eight opaque pixels.
    ramps = ("skin", "hair", "top", "under", "lower", "boot", "accent",
             "metal", "cloak", "eye")
    nb = {}
    for im, e in zip(figs, eff):
        px = im.load()
        cnt = {}
        for y in range(FH):
            for x in range(FW):
                q = px[x, y]
                if q[3] == 255:
                    cnt[q[:3]] = cnt.get(q[:3], 0) + 1
        pl = _palette(e)
        k = sum(1 for r in ramps
                if sum(cnt.get(tuple(t), 0) for t in pl[r]) >= 8)
        nb[k] = nb.get(k, 0) + 1
    print("\ndistinct colour-blocked elements ON THE PIXELS "
          "(references have 5-7, our previous figures had 3-4):")
    print("   %s" % "  ".join("%d=%d" % kv for kv in sorted(nb.items())))
    for key in ("grammar", "head_grammar", "palette", "hair_shape",
                "headwear", "top", "lower", "prop", "shading", "outline_mode"):
        c = {}
        for p in eff:
            c[p[key]] = c.get(p[key], 0) + 1
        print("\n%-14s %s" % (key, "  ".join(
            "%s=%d" % kv for kv in sorted(c.items()))))

    # HUE COVERAGE. Twelve bins round the wheel, and the question is not what
    # the average is -- there is no such thing -- but whether any bin is empty,
    # because an empty bin is a colour the user can never swipe right on.
    bins = [0] * 12
    for s2 in stats:
        bins[min(11, int(s2["hue"] * 12))] += 1
    print("\ndominant-hue coverage, 12 bins: %s   empty bins: %d"
          % (" ".join(str(b) for b in bins), sum(1 for b in bins if b == 0)))
    # The dominant block on a figure is very often its skin or its hair, both of
    # which live in the same warm sixth of the wheel -- so that histogram is
    # honest about what the reader SEES and says nothing about the garments.
    # This one asks the palette directly.
    gb = [0] * 12
    for pp in params:
        c = _palette(pp)["top"][1]
        h = colorsys.rgb_to_hsv(c[0] / 255., c[1] / 255., c[2] / 255.)[0]
        gb[min(11, int(h * 12))] += 1
    print("main-garment hue coverage, 12 bins: %s   empty bins: %d"
          % (" ".join(str(b) for b in gb), sum(1 for b in gb if b == 0)))

    # DETERMINISM, because a params dict is the only record of a figure the
    # user liked and it has to redraw from that alone -- including after a
    # round trip through JSON, which is how the server will store it.
    same = 0
    for pp in params[:40]:
        a = draw(pp).tobytes()
        b = draw(json.loads(json.dumps(pp))).tobytes()
        same += (a == b)
    print("deterministic redraw after a JSON round trip: %d/40" % same)

    # ANNEALING. With a bias list the sampler should stay near it most of the
    # time and still reach anywhere -- so the test is that biased draws are
    # measurably closer to the bias than random draws are, and that they are
    # not IDENTICAL to it, which would be the failure this file exists to avoid.
    liked = params[:5]
    bmask = [_mask(draw(pp)) for pp in liked]
    rng2 = random.Random(99)
    near, far = [], []
    for _ in range(60):
        m = _mask(draw(sample(rng2, bias=liked)))
        near.append(min(1.0 - len(m & q) / float(len(m | q)) for q in bmask))
    for _ in range(60):
        m = _mask(draw(sample(rng2)))
        far.append(min(1.0 - len(m & q) / float(len(m | q)) for q in bmask))
    print("annealed draws: mean distance to nearest liked %.3f "
          "(unbiased %.3f); identical to a liked figure: %d/60"
          % (sum(near) / len(near), sum(far) / len(far),
             sum(1 for d in near if d == 0.0)))

    # The contact sheet. 100 figures at 3x on a mid-value ground, because a
    # sprite that only holds together on black is a sprite that has not been
    # tested.
    z, pad = 3, 3
    cw, ch = FW * z + pad, FH * z + pad
    cols, rowsn = 10, 10
    sheet = Image.new("RGBA", (cols * cw + pad, rowsn * ch + pad),
                      (96, 110, 92, 255))
    for i in range(cols * rowsn):
        im = figs[i].resize((FW * z, FH * z), Image.NEAREST)
        sheet.alpha_composite(im, (pad + (i % cols) * cw,
                                   pad + (i // cols) * ch))
    path = os.path.join(out, "spread.png")
    sheet.save(path)
    print("\nwrote %s" % path)

    with open(os.path.join(out, "params.json"), "w") as fh:
        json.dump(params, fh, indent=1)
    print("wrote %s" % os.path.join(out, "params.json"))

    # --- the prompt, checked against the one he actually typed ---------------
    #
    # The question a prompted sheet has to answer is not "did the constraints
    # apply" -- that is a one-line assertion -- but "did applying them collapse
    # the space". So both sheets are drawn and both distributions are printed
    # side by side: the constrained axes should move a long way and everything
    # else should not move at all.
    prompt = "A cute girl next door, blonde hair big eyes"
    cons = parse_prompt(prompt)
    print("\n=== prompt: %r" % prompt)
    print("understood: %s" % ", ".join(cons["_matched"]))
    print("ignored:    %s" % ", ".join(cons["_ignored"]))

    def bank(n, constraints, tag):
        ps, ims = [], []
        for i in range(n):
            r = random.Random(7000 + i)
            q = sample(r, constraints=constraints)
            ps.append(q)
            ims.append(draw(q))
        sheet_of(ims, os.path.join(out, tag + ".png"))
        return ps, ims

    def sheet_of(ims, path):
        zz, pd = 3, 3
        cwd, chd = FW * zz + pd, FH * zz + pd
        sh = Image.new("RGBA", (10 * cwd + pd, 10 * chd + pd),
                       (96, 110, 92, 255))
        for i in range(min(100, len(ims))):
            sh.alpha_composite(ims[i].resize((FW * zz, FH * zz),
                                             Image.NEAREST),
                               (pd + (i % 10) * cwd, pd + (i // 10) * chd))
        sh.save(path)

    pp, _pi = bank(100, cons, "prompted")
    up, _ui = bank(100, None, "unprompted")

    def band(ps, key, fn=None):
        v = [fn(q) if fn else q[key] for q in ps]
        return "%.3f..%.3f (mean %.3f)" % (min(v), max(v),
                                           sum(v) / float(len(v)))

    print("\n%-22s %-34s %s" % ("", "PROMPTED (n=100)", "UNPROMPTED (n=100)"))
    for label, key, fn in (
            ("head_frac as drawn", None, lambda q: measure(q)["head_frac"]),
            ("eye_w", "eye_w", None),
            ("eye_h", "eye_h", None),
            ("hair_hue", "hair_hue", None),
            ("hair_val", "hair_val", None),
            ("height_rows", "height_rows", None),
            ("build", "build", None),
            ("base_hue (garment)", "base_hue", None)):
        print("  %-20s %-34s %s" % (label, band(pp, key, fn),
                                    band(up, key, fn)))
    for label, key in (("hair_natural", "hair_natural"),
                       ("skin_exotic", "skin_exotic"),
                       ("realistic", "realistic")):
        print("  %-20s %-34s %s"
              % (label, "%d%% true" % (100 * sum(1 for q in pp if q[key])
                                       / len(pp)),
                 "%d%% true" % (100 * sum(1 for q in up if q[key]) / len(up))))
    for key in ("hair_shape", "top", "lower", "headwear", "prop", "palette"):
        def cnt(ps):
            c = {}
            for q in ps:
                e = _blocks(q, q["seed"])
                c[e[key]] = c.get(e[key], 0) + 1
            return " ".join("%s=%d" % kv for kv in sorted(c.items()))
        print("  %-20s %s\n  %-20s %s" % (key + " (prompted)", cnt(pp),
                                          key + " (unprompted)", cnt(up)))
    # Collapse check: if the constraints are too tight the prompted bank stops
    # being a space and becomes one character, and the silhouette spread is
    # where that shows first.
    for tag, ps in (("prompted", pp), ("unprompted", up)):
        ms = [_mask(draw(q)) for q in ps]
        pr = list(itertools.islice(itertools.combinations(range(len(ms)), 2),
                                   3000))
        d = [1.0 - len(ms[i] & ms[k]) / float(len(ms[i] | ms[k]))
             for (i, k) in pr]
        print("  %-12s distinct masks %d/%d, mean pairwise difference %.3f"
              % (tag, len(set(ms)), len(ms), sum(d) / len(d)))
    print("wrote %s and %s" % (os.path.join(out, "prompted.png"),
                               os.path.join(out, "unprompted.png")))


if __name__ == "__main__":
    main()
