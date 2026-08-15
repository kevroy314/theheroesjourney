#!/usr/bin/env python3
"""
Turn a ChatGPT "pixel art" render into a real, indexed, game-ready pixel asset.

ChatGPT returns a high-resolution raster that only *imitates* pixel art: soft
edges, compression noise, ~20k unique colours. Godot wants the opposite - a
small indexed image drawn up with nearest-neighbour filtering.

    ./postprocess.py in.png out_prefix [--width 360] [--colors 32]

Writes:
    <out_prefix>_master.png   the true low-res art. This is the asset of record.
    <out_prefix>_x2.png       nearest-neighbour upscale, for eyeballing

Two traps this script exists to avoid:

1. This art is ~90% near-black, so a plain median cut spends almost its whole
   palette on shadow. Quantising in gamma-lifted space allocates colours by
   perceived difference instead.

2. The accent - the light on the mountain - is a handful of pixels. Median cut
   throws away rare colours, so the most important thing in the picture
   silently disappears. --keep force-pins colours into the palette; the
   theme's accent is pinned by default.
"""
import argparse

import numpy as np
from PIL import Image

# from data/themes/firstlight.json - the colours that must survive quantisation
KEEP_DEFAULT = ["#E9A94E", "#8FBFD8", "#EFE7DA"]


def hex2rgb(s):
    s = s.lstrip("#")
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("prefix")
    ap.add_argument("--width", type=int, default=360,
                    help="logical pixel width of the master")
    ap.add_argument("--colors", type=int, default=32)
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--gamma", type=float, default=2.2)
    ap.add_argument("--keep", nargs="*", default=KEEP_DEFAULT,
                    help="hex colours to force into the palette")
    a = ap.parse_args()

    im = Image.open(a.src).convert("RGB")
    h = round(im.height * a.width / im.width)
    small = im.resize((a.width, h), Image.BOX)   # BOX averages the fake pixels

    keep = [hex2rgb(c) for c in a.keep]
    lut = [round(255 * (i / 255) ** (1 / a.gamma)) for i in range(256)] * 3

    # adaptive palette, chosen in lifted space, then un-lifted
    n_adaptive = max(2, a.colors - len(keep))
    q = small.point(lut).quantize(colors=n_adaptive, method=Image.MEDIANCUT,
                                  dither=Image.NONE)
    inv = [round(255 * (i / 255) ** a.gamma) for i in range(256)]
    pal = q.getpalette()[: n_adaptive * 3]
    palette = [tuple(inv[c] for c in pal[i * 3:i * 3 + 3])
               for i in range(n_adaptive)] + keep

    # remap by nearest palette entry, in lifted space so shadows separate
    px = np.asarray(small).astype(float)
    P = np.array(palette, dtype=float)
    lift = lambda x: (x / 255.0) ** (1 / a.gamma)
    d = ((lift(px)[:, :, None, :] - lift(P)[None, None, :, :]) ** 2).sum(3)
    idx = d.argmin(2)
    out = P[idx].astype(np.uint8)

    master = Image.fromarray(out)
    master.save(a.prefix + "_master.png")
    master.resize((a.width * a.scale, h * a.scale),
                  Image.NEAREST).save(a.prefix + "_x%d.png" % a.scale)

    used = sorted(set(idx.ravel().tolist()))
    print("master %dx%d -> %s_master.png" % (a.width, h, a.prefix))
    print("%d of %d palette entries used:" % (len(used), len(palette)))
    for i in used:
        c = palette[i]
        print("  #%02X%02X%02X %8d px%s" % (
            c[0], c[1], c[2], (idx == i).sum(),
            "   <- pinned" if i >= n_adaptive else ""))


if __name__ == "__main__":
    main()
