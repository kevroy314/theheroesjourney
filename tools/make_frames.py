#!/usr/bin/env python3
"""Draw the two node frames, one per register.

The node list had been rounded rectangles, which is the vocabulary of a settings
screen. Diegetically the boxes are:

  reality  — chalk. You scratch the plan onto the floorboards of a room you know
             you are going to lose. Broken strokes, jitter, corners that
             overshoot the way a hand-drawn box does. The loop wipes it.
  palace   — a plate. Something cut, planed and screwed to the wall of a place
             you built to outlast the reset. Clean edge, slight bevel, kept.

Both are 9-slice frames, white on transparent, tinted by the palette. The chalk
one is meant to be used with TILE stretch so the broken edge repeats instead of
smearing.

    python3 tools/make_frames.py        # writes assets/frames/*.png
"""
import os
import random
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "frames")

SIZE = 48          # 16px corners, 16px tiling middle
MARGIN = 16
W = (255, 255, 255, 255)


def chalk(seed=7):
    """A hand-scratched box: broken strokes, jitter, overshooting corners."""
    rng = random.Random(seed)
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    inset = 5

    def stroke(x0, y0, x1, y1, horizontal):
        """A dashed, jittered line — chalk skips."""
        length = (x1 - x0) if horizontal else (y1 - y0)
        pos = 0
        while pos < length:
            run = rng.randint(3, 7)
            gap = rng.choice([0, 0, 1, 1, 2])
            for i in range(run):
                if pos + i >= length:
                    break
                jitter = rng.choice([0, 0, 0, 1, -1])
                if horizontal:
                    d.point((x0 + pos + i, y0 + jitter), fill=W)
                    if rng.random() < 0.35:
                        d.point((x0 + pos + i, y0 + jitter + 1), fill=W)
                else:
                    d.point((x0 + jitter, y0 + pos + i), fill=W)
                    if rng.random() < 0.35:
                        d.point((x0 + jitter + 1, y0 + pos + i), fill=W)
            pos += run + gap

    # Overshoot past each corner — the giveaway that a person drew it.
    over = 3
    stroke(inset - over, inset, SIZE - inset + over, inset, True)
    stroke(inset - over, SIZE - inset, SIZE - inset + over, SIZE - inset, True)
    stroke(inset, inset - over, inset, SIZE - inset + over, False)
    stroke(SIZE - inset, inset - over, SIZE - inset, SIZE - inset + over, False)

    # Chalk dust.
    for _ in range(26):
        x = rng.randint(2, SIZE - 3)
        y = rng.randint(2, SIZE - 3)
        near_edge = (
            abs(x - inset) < 3 or abs(x - (SIZE - inset)) < 3
            or abs(y - inset) < 3 or abs(y - (SIZE - inset)) < 3
        )
        if near_edge and rng.random() < 0.7:
            img.putpixel((x, y), (255, 255, 255, rng.randint(60, 140)))
    return img


def plate():
    """Cut, planed, screwed to the wall. Kept."""
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # Solid body, so it reads as a physical object rather than an outline.
    d.rectangle([2, 2, SIZE - 3, SIZE - 3], fill=(255, 255, 255, 44))
    d.rectangle([2, 2, SIZE - 3, SIZE - 3], outline=(255, 255, 255, 210))
    # A lit top edge and a shadowed bottom: one light source, from above.
    d.line([(3, 3), (SIZE - 4, 3)], fill=(255, 255, 255, 130))
    d.line([(3, SIZE - 4), (SIZE - 4, SIZE - 4)], fill=(255, 255, 255, 70))
    # Two fixings, top-left and bottom-right, in the corner regions so 9-slice
    # keeps them at the corners instead of tiling them along the edges.
    for cx, cy in ((7, 7), (SIZE - 8, SIZE - 8)):
        d.point((cx, cy), fill=(255, 255, 255, 190))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, img in (("chalk", chalk()), ("plate", plate())):
        img.save(os.path.join(OUT, "%s.png" % name))
        img.resize((SIZE * 4, SIZE * 4), Image.NEAREST).save(
            os.path.join(OUT, "_%s_x4.png" % name))
    print("wrote frames to %s (size %d, margin %d)" % (OUT, SIZE, MARGIN))


if __name__ == "__main__":
    main()
