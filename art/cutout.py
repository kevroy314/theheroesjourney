#!/usr/bin/env python3
"""
Take the background out of a single-subject render.

This is the hard half of turning "a picture of a well" into "a sprite of a
well", and it is worth being explicit about why the obvious answers do not
work here.

WHAT THE INPUT ACTUALLY IS
    ChatGPT hands back a soft, opaque, high-resolution raster. Even when the
    prompt says "plain background" the background is never one colour: it is a
    slow gradient with a vignette, plus JPEG-ish ringing, plus — almost always
    — a soft drop shadow the model added under the subject because it thinks it
    is lighting a photograph. There is no alpha channel to trust.

WHAT DOES NOT WORK
    * A global colour threshold ("everything within N of #F0EEE8 is background")
      dies on the gradient: a tolerance loose enough to catch the dark corner is
      loose enough to eat the subject's light side.
    * Corner-seeded flood fill on raw RGB distance leaks through any pixel where
      the subject touches a background-coloured highlight, and then removes half
      the subject.
    * Edge detection plus contour filling gets the outline right and the
      interior wrong the moment the subject has an internal hole or a bright
      panel.
    * Learned matting (rembg / u2net / SAM) is the actual state of the art and
      would be better than this, but it is a ~180MB ONNX download and this
      machine has numpy and PIL and nothing else. See docs/ADDING-ASSETS.md.

WHAT THIS DOES, AND WHY IT IS THE RIGHT SHAPE FOR THIS INPUT
    1. Fit a smooth background MODEL rather than pick a background COLOUR. A
       quadratic surface in (x, y) per channel, fitted robustly to the border
       ring, predicts the gradient and the vignette. The threshold is then
       applied to the residual from that prediction, so it can be tight —
       which is what stops the leak — while still tracking a background that
       varies by 40 levels corner to corner.
    2. Threshold in gamma-lifted space, for the same reason art/postprocess.py
       quantises there: this art is dark, and a linear RGB distance cannot tell
       two dark colours apart.
    3. Take the connected component of the eligible set that touches the border,
       not the whole eligible set. A background-coloured highlight inside the
       subject is eligible but unreachable, so it survives.
    4. Optionally subtract the render's own drop shadow: pixels whose CHROMA
       matches the background but whose VALUE is lower are the model's studio
       shadow, not the subject. We bake our own contact shadow later and must
       not inherit a second, softer, wrongly-angled one.
    5. Clean up with 3x3 close/open and a component-size filter, then hand back
       a float coverage mask so the caller can decide the binary edge at the
       TARGET resolution, where a half-covered pixel is a real decision rather
       than a rounding error.

    Everything runs at a reduced working resolution (default 512 on the long
    side). The target is 64x96; 512 is still 8x supersampling, and it makes the
    flood fill cost a second instead of ten.

usage:
    ./cutout.py in.png out.png [--tol 0.10] [--drop-shadow] [--debug dbg.png]
"""
import argparse
import sys
from collections import deque

import numpy as np
from PIL import Image

GAMMA = 2.2


def lift(a):
    """Perceptual-ish space. Same trick, same reason, as art/postprocess.py."""
    return np.clip(a, 0.0, 1.0) ** (1.0 / GAMMA)


# --- the background model -----------------------------------------------------

def _basis(h, w):
    """Quadratic basis over normalised coordinates: 1, x, y, x^2, y^2, xy."""
    ys, xs = np.mgrid[0:h, 0:w]
    x = (xs / max(1.0, w - 1.0)) * 2.0 - 1.0
    y = (ys / max(1.0, h - 1.0)) * 2.0 - 1.0
    return np.stack([np.ones_like(x), x, y, x * x, y * y, x * y], axis=-1)


def fit_background(rgb, ring, rounds=3):
    """Least-squares quadratic per channel over the border ring, refitted twice
    with outliers dropped.

    The refit is what makes this survive a subject that touches an edge: the
    pixels where the subject crosses the ring are large residuals on the first
    pass and are simply not in the second.
    """
    h, w, _ = rgb.shape
    B = _basis(h, w)
    sel = ring.copy()
    coef = None
    for _ in range(rounds):
        A = B[sel]                      # (n, 6)
        Y = lift(rgb[sel])              # (n, 3)
        if A.shape[0] < 24:
            break
        coef, *_ = np.linalg.lstsq(A, Y, rcond=None)
        pred = A @ coef
        res = np.sqrt(((Y - pred) ** 2).sum(1))
        med = np.median(res)
        mad = np.median(np.abs(res - med)) + 1e-6
        keep = res < med + 2.5 * 1.4826 * mad
        if keep.all():
            break
        idx = np.argwhere(sel)
        drop = idx[~keep]
        sel[drop[:, 0], drop[:, 1]] = False
        if sel.sum() < 64:
            break
    if coef is None:
        flat = lift(rgb[ring]).mean(0)
        return np.broadcast_to(flat, (h, w, 3)).copy()
    return B @ coef                     # (h, w, 3), already in lifted space


# --- morphology and components, in numpy because scipy is not installed -------

def _shifts(m):
    """The four 4-connected shifts of a boolean mask, padded with False."""
    up = np.zeros_like(m);    up[:-1] = m[1:]
    dn = np.zeros_like(m);    dn[1:] = m[:-1]
    lf = np.zeros_like(m);    lf[:, :-1] = m[:, 1:]
    rt = np.zeros_like(m);    rt[:, 1:] = m[:, :-1]
    return up, dn, lf, rt


def dilate(m):
    out = m.copy()
    for s in _shifts(m):
        out |= s
    return out


def erode(m):
    out = m.copy()
    for s in _shifts(~m):
        out &= ~s
    return out


def close_open(m, n=1):
    for _ in range(n):
        m = erode(dilate(m))
    for _ in range(n):
        m = dilate(erode(m))
    return m


def components(mask):
    """Label 8-connected components of a boolean mask. BFS with a deque; at the
    512px working resolution this is a fraction of a second."""
    h, w = mask.shape
    lab = np.zeros((h, w), np.int32)
    flat = mask.ravel()
    lf = lab.ravel()
    nid = 0
    nb = (-w - 1, -w, -w + 1, -1, 1, w - 1, w, w + 1)
    for start in np.flatnonzero(flat):
        if lf[start]:
            continue
        nid += 1
        lf[start] = nid
        q = deque((int(start),))
        while q:
            p = q.popleft()
            px = p % w
            for d in nb:
                n = p + d
                if n < 0 or n >= flat.size:
                    continue
                nx = n % w
                if abs(nx - px) > 1:        # wrapped a row
                    continue
                if flat[n] and not lf[n]:
                    lf[n] = nid
                    q.append(n)
    return lab, nid


def flood_from_border(eligible):
    """The connected component(s) of `eligible` that touch the image border."""
    lab, n = components(eligible)
    if n == 0:
        return np.zeros_like(eligible)
    border = set(lab[0].tolist()) | set(lab[-1].tolist()) \
        | set(lab[:, 0].tolist()) | set(lab[:, -1].tolist())
    border.discard(0)
    if not border:
        return np.zeros_like(eligible)
    return np.isin(lab, list(border))


# --- the operation ------------------------------------------------------------

class CutoutError(RuntimeError):
    pass


def _strip_studio_shadow(rgb, bg_lifted, fg, tol, band, cap, say):
    """Remove the render's own soft ground shadow from the subject mask.

    A cast shadow is the background MULTIPLIED down: its colour lies on the ray
    from black through the background colour. So project each pixel onto that
    ray and keep the perpendicular residual; a shadowed background has a tiny
    residual at any darkness, while a subject that is genuinely a different
    colour does not.

    Two guards, because the test is ambiguous for an achromatic subject on an
    achromatic background (a grey stone well on warm grey is, to this test,
    exactly a shadow):

      * only the bottom `band` of the subject's bounding box may be
        reclassified — a studio shadow is on the ground, at the base;
      * if that would still remove more than `cap` of the subject, refuse and
        keep the shadow, loudly. Better a prop with a dark plinth the owner can
        see than a prop with its legs deleted.
    """
    bgl = np.clip(bg_lifted, 0, 1) ** GAMMA               # back to linear-ish
    num = (rgb * bgl).sum(2)
    den = (bgl * bgl).sum(2) + 1e-6
    k = num / den                                          # best scale factor
    perp = np.sqrt(((rgb - k[:, :, None] * bgl) ** 2).sum(2) / 3.0)
    cand = (perp <= tol) & (k >= 0.25) & (k <= 0.97)

    rows = np.flatnonzero(fg.any(1))
    if rows.size:
        y0, y1 = rows[0], rows[-1]
        cut = int(y1 - (y1 - y0) * band)
        cand[:cut] = False

    removed = (fg & cand).sum() / max(1, fg.sum())
    if removed > cap:
        say("drop shadow: REFUSED. %.0f%% of the subject reads as shadowed "
            "background, which means the subject's colour is too close to the "
            "background's. Keeping it; trim the base by hand or regenerate on "
            "a background of a different hue." % (100 * removed))
        return fg
    say("drop shadow: removed %.1f%% of the subject mask at the base"
        % (100 * removed))
    out = close_open(fg & ~cand, 1)
    return out if out.any() else fg


def cutout(src, tol=0.10, work=512, ring_frac=0.02, drop_shadow=False,
           shadow_tol=0.035, shadow_band=0.45, shadow_max=0.35,
           fill_holes=0.0, min_blob=0.02, smooth=1, report=None):
    """Return (rgb float32 HxWx3 in 0..1, coverage float32 HxW in 0..1).

    `src` is a PIL image. The result is at the working resolution, not the
    target: downsampling to 64x96 is the caller's job because the caller knows
    where the anchor goes.
    """
    im = src.convert("RGBA")
    if im.width > work or im.height > work:
        s = work / float(max(im.width, im.height))
        im = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))),
                       Image.BOX)
    arr = np.asarray(im).astype(np.float32) / 255.0
    rgb, a = arr[:, :, :3], arr[:, :, 3]
    h, w = a.shape
    say = report if report is not None else (lambda *_: None)

    # 0. If the source already has a real alpha channel, believe it. A PNG that
    #    someone cut out by hand, or a generation that actually honoured
    #    "transparent background", is strictly better than anything below.
    if (a < 0.5).mean() > 0.02:
        say("alpha: source already has %.1f%% transparent pixels; using it"
            % (100.0 * (a < 0.5).mean()))
        cov = a
    else:
        r = max(2, int(round(min(h, w) * ring_frac)))
        ring = np.zeros((h, w), bool)
        ring[:r] = ring[-r:] = True
        ring[:, :r] = ring[:, -r:] = True

        bg = fit_background(rgb, ring)                    # lifted space
        d = np.sqrt(((lift(rgb) - bg) ** 2).sum(2) / 3.0)
        eligible = d <= tol

        ring_hit = eligible[ring].mean()
        say("background model: residual p50 %.4f p95 %.4f on the border ring; "
            "%.0f%% of the ring is within tol=%.3f" %
            (float(np.median(d[ring])), float(np.percentile(d[ring], 95)),
             100 * ring_hit, tol))
        if ring_hit < 0.5:
            raise CutoutError(
                "only %.0f%% of the border reads as background at tol=%.3f. "
                "Either the subject fills the frame, or the background is not "
                "flat enough to model. Try --bg-tol higher, or crop tighter "
                "with --crop, or generate again on a plainer background."
                % (100 * ring_hit, tol))

        back = flood_from_border(eligible)
        fg = ~back

        if drop_shadow:
            fg = _strip_studio_shadow(rgb, bg, fg, shadow_tol, shadow_band,
                                      shadow_max, say)

        if fill_holes > 0:
            # Enclosed background — the gap under a gate, the mouth of a well.
            # Off by default: an interior highlight that happens to match the
            # background is far more common than a real hole.
            holes, n = components(eligible & ~back)
            if n:
                sizes = np.bincount(holes.ravel())
                big = np.flatnonzero(sizes >= fill_holes * fg.sum())
                big = big[big > 0]
                if big.size:
                    say("holes: punched %d enclosed region(s)" % big.size)
                    fg &= ~np.isin(holes, big)

        if smooth:
            fg = close_open(fg, smooth)

        if min_blob > 0 and fg.any():
            lab, n = components(fg)
            sizes = np.bincount(lab.ravel())
            sizes[0] = 0
            keep = np.flatnonzero(sizes >= min_blob * sizes.max())
            dropped = n - keep.size
            if dropped:
                say("despeckle: dropped %d component(s) under %.0f%% of the "
                    "subject" % (dropped, 100 * min_blob))
            fg = np.isin(lab, keep)

        if not fg.any():
            raise CutoutError("nothing survived: the whole image read as "
                              "background. Lower --bg-tol.")
        say("subject: %.1f%% of the frame, bbox %dx%d" %
            (100.0 * fg.mean(),
             int(np.ptp(np.flatnonzero(fg.any(0)))) + 1,
             int(np.ptp(np.flatnonzero(fg.any(1)))) + 1))

        # A one-pixel feather at the working resolution, so that the coverage
        # average into the target grid sees a real edge rather than a step. The
        # binary decision happens at 64x96, not here.
        cov = fg.astype(np.float32)
        edge = dilate(fg) & ~erode(fg)
        cov[edge & fg] = 0.75
        cov[edge & ~fg] = 0.25

    return rgb, cov


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--tol", type=float, default=0.10)
    ap.add_argument("--work", type=int, default=512)
    ap.add_argument("--drop-shadow", action="store_true")
    ap.add_argument("--shadow-tol", type=float, default=0.035)
    ap.add_argument("--fill-holes", type=float, default=0.0)
    ap.add_argument("--min-blob", type=float, default=0.02)
    a = ap.parse_args()

    rgb, cov = cutout(Image.open(a.src), tol=a.tol, work=a.work,
                      drop_shadow=a.drop_shadow, shadow_tol=a.shadow_tol,
                      fill_holes=a.fill_holes,
                      min_blob=a.min_blob, report=lambda s: print("  " + s))
    out = np.concatenate([rgb, cov[:, :, None]], axis=2)
    Image.fromarray((out * 255).astype(np.uint8), "RGBA").save(a.out)
    print("wrote", a.out)


if __name__ == "__main__":
    try:
        main()
    except CutoutError as e:
        sys.exit("cutout failed: %s" % e)
