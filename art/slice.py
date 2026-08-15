#!/usr/bin/env python3
"""
Slice a uniform grid sheet into individual frames, and report how much the
frames actually differ from each other.

    ./slice.py sheet.png outdir --cols 2 --rows 2

ChatGPT will honour "equal cells, no gutters" reasonably well, so a fixed
cols x rows split works. It will NOT keep the subject registered between
frames - the drift report tells you how bad it is.
"""
import argparse
import os

import numpy as np
from PIL import Image


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sheet")
    ap.add_argument("outdir")
    ap.add_argument("--cols", type=int, required=True)
    ap.add_argument("--rows", type=int, required=True)
    a = ap.parse_args()

    im = Image.open(a.sheet).convert("RGB")
    cw, ch = im.width // a.cols, im.height // a.rows
    os.makedirs(a.outdir, exist_ok=True)

    frames = []
    for r in range(a.rows):
        for c in range(a.cols):
            f = im.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
            n = r * a.cols + c
            f.save(os.path.join(a.outdir, "frame_%02d.png" % n))
            frames.append(np.asarray(f).astype(int))
    print("%d frames of %dx%d -> %s" % (len(frames), cw, ch, a.outdir))

    # Drift report. A real animation loop differs only where the animated
    # element is, so "% of pixels changed" should be small and localised.
    base = frames[0]
    for i, f in enumerate(frames[1:], 1):
        d = np.abs(f - base).sum(2)
        changed = (d > 24).mean() * 100
        print("  frame %d vs frame 0: %.1f%% of pixels differ, mean delta %.1f"
              % (i, changed, d.mean()))


if __name__ == "__main__":
    main()
