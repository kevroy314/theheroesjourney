#!/usr/bin/env python3
"""Draw the icon set as true pixel art.

Not vector, not downsampled vector — authored on a 16x16 grid with aliased
1px strokes, so it belongs to the same production as the room plates. Godot
displays them with TEXTURE_FILTER_NEAREST at integer multiples (16/32/48).

Shapes are white on transparent; the game tints them with the palette, so one
file serves every colour and both registers.

    python3 tools/make_glyphs.py        # writes assets/icons/*.png
"""
import os
from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "icons")
N = 16
W = (255, 255, 255, 255)
CLEAR = (0, 0, 0, 0)


def canvas():
    img = Image.new("RGBA", (N, N), CLEAR)
    return img, ImageDraw.Draw(img)


# --- resources ----------------------------------------------------------------

def grit():
    """A struck spark: the thing you make by hitting something."""
    img, d = canvas()
    d.line([(4, 12), (9, 4)], fill=W)          # the strike
    d.line([(10, 8), (13, 6)], fill=W)         # sparks
    d.line([(11, 11), (14, 10)], fill=W)
    d.line([(7, 3), (8, 1)], fill=W)
    return img


def resolve():
    """A sealed mark — the only closed shape in the set, because it is the one
    thing that survives a reset."""
    img, d = canvas()
    d.ellipse([2, 2, 13, 13], outline=W)
    d.line([(5, 8), (7, 10)], fill=W)
    d.line([(7, 10), (11, 5)], fill=W)
    return img


def streak():
    """Four strokes and a diagonal. How you count days in captivity."""
    img, d = canvas()
    for x in (2, 5, 8, 11):
        d.line([(x, 3), (x, 12)], fill=W)
    d.line([(1, 12), (13, 3)], fill=W)
    return img


# --- the six axes -------------------------------------------------------------

def move():
    img, d = canvas()
    d.line([(2, 10), (6, 6)], fill=W)
    d.line([(6, 6), (9, 10)], fill=W)
    d.line([(6, 14), (10, 10)], fill=W)
    d.line([(10, 10), (13, 14)], fill=W)
    d.ellipse([9, 1, 13, 5], outline=W)
    return img


def water():
    img, d = canvas()
    d.line([(8, 2), (4, 8)], fill=W)
    d.line([(8, 2), (12, 8)], fill=W)
    d.arc([3, 5, 13, 14], start=0, end=180, fill=W)
    return img


def fuel():
    """A bowl. The leaf read as a prohibition sign at 16px — a circle with a
    diagonal through it means "no" to everyone alive, whatever you intended."""
    img, d = canvas()
    d.line([(2, 6), (13, 6)], fill=W)
    d.arc([2, 1, 13, 13], start=0, end=180, fill=W)
    d.line([(6, 2), (6, 4)], fill=W)          # steam
    d.line([(9, 1), (9, 4)], fill=W)
    return img


def rest():
    img, d = canvas()
    d.ellipse([2, 2, 13, 13], outline=W)
    # Bite the crescent out, including the stroke it overlaps.
    d.ellipse([5, 0, 17, 12], outline=CLEAR, fill=CLEAR)
    return img


def mind():
    """A spiral, which is also the loop. The rhyme is intentional."""
    img, d = canvas()
    d.arc([6, 6, 10, 10], start=0, end=270, fill=W)
    d.arc([4, 4, 12, 12], start=270, end=180, fill=W)
    d.arc([2, 2, 14, 14], start=180, end=90, fill=W)
    return img


def bond():
    img, d = canvas()
    d.ellipse([1, 4, 9, 12], outline=W)
    d.ellipse([6, 4, 14, 12], outline=W)
    return img


# --- node marks ---------------------------------------------------------------

def task():
    img, d = canvas()
    d.rectangle([2, 2, 13, 13], outline=W)
    return img


def done():
    img, d = canvas()
    d.rectangle([2, 2, 13, 13], outline=W)
    d.line([(5, 8), (7, 10)], fill=W)
    d.line([(7, 10), (11, 5)], fill=W)
    return img


def threshold():
    """A doorway. The way out."""
    img, d = canvas()
    d.arc([3, 3, 12, 12], start=180, end=0, fill=W)
    d.line([(3, 8), (3, 14)], fill=W)
    d.line([(12, 8), (12, 14)], fill=W)
    d.line([(1, 14), (14, 14)], fill=W)
    return img


def echo():
    img, d = canvas()
    d.point((7, 8), fill=W)
    d.point((8, 8), fill=W)
    d.arc([4, 5, 11, 12], start=225, end=315, fill=W)
    d.arc([1, 2, 14, 15], start=225, end=315, fill=W)
    d.arc([4, 5, 11, 12], start=45, end=135, fill=W)
    d.arc([1, 2, 14, 15], start=45, end=135, fill=W)
    return img


def cache():
    img, d = canvas()
    d.rectangle([3, 6, 12, 13], outline=W)
    d.line([(6, 6), (6, 3)], fill=W)
    d.line([(9, 6), (9, 3)], fill=W)
    d.line([(6, 3), (9, 3)], fill=W)
    return img


def mirror():
    img, d = canvas()
    d.rectangle([4, 2, 11, 13], outline=W)
    d.line([(6, 5), (6, 9)], fill=W)
    return img


def charm():
    img, d = canvas()
    d.line([(8, 5), (12, 9)], fill=W)
    d.line([(12, 9), (8, 14)], fill=W)
    d.line([(8, 14), (4, 9)], fill=W)
    d.line([(4, 9), (8, 5)], fill=W)
    d.arc([6, 1, 10, 6], start=180, end=0, fill=W)
    return img


def spite():
    """One circle, split and the halves pushed apart. The fractured companion —
    it has to read as a *displaced* shape, not just a broken one."""
    img, d = canvas()
    d.arc([2, 1, 11, 11], start=90, end=270, fill=W)     # left half, raised
    d.line([(6, 1), (6, 11)], fill=W)
    d.arc([5, 4, 14, 14], start=270, end=90, fill=W)     # right half, dropped
    d.line([(9, 4), (9, 14)], fill=W)
    return img


def warden():
    """An hourglass — the only icon about time running rather than remaining."""
    img, d = canvas()
    d.line([(3, 2), (12, 2)], fill=W)
    d.line([(3, 13), (12, 13)], fill=W)
    d.line([(4, 2), (8, 7)], fill=W)
    d.line([(11, 2), (8, 7)], fill=W)
    d.line([(8, 7), (4, 13)], fill=W)
    d.line([(8, 7), (11, 13)], fill=W)
    return img


# --- meta ---------------------------------------------------------------------

def deadline():
    img, d = canvas()
    d.ellipse([2, 3, 13, 14], outline=W)
    d.line([(8, 6), (8, 9)], fill=W)
    d.line([(8, 9), (10, 10)], fill=W)
    d.line([(6, 1), (9, 1)], fill=W)
    return img


def loop():
    img, d = canvas()
    d.arc([2, 2, 13, 13], start=300, end=210, fill=W)
    d.line([(13, 2), (13, 6)], fill=W)
    d.line([(10, 5), (13, 5)], fill=W)
    return img


def light():
    """The mountain and the one window that never goes dark."""
    img, d = canvas()
    d.line([(1, 14), (6, 6)], fill=W)
    d.line([(6, 6), (9, 10)], fill=W)
    d.line([(9, 10), (12, 4)], fill=W)
    d.line([(12, 4), (15, 14)], fill=W)
    d.line([(1, 14), (15, 14)], fill=W)
    d.point((12, 2), fill=W)
    d.point((11, 2), fill=W)
    d.point((12, 1), fill=W)
    return img


ICONS = {
    "grit": grit, "resolve": resolve, "streak": streak,
    "move": move, "water": water, "fuel": fuel,
    "rest": rest, "mind": mind, "bond": bond,
    "task": task, "done": done, "threshold": threshold,
    "echo": echo, "cache": cache, "mirror": mirror,
    "charm": charm, "spite": spite, "warden": warden,
    "deadline": deadline, "loop": loop, "light": light,
}


def main():
    os.makedirs(OUT, exist_ok=True)
    sheet = Image.new("RGBA", (N * len(ICONS), N), CLEAR)
    for i, (name, fn) in enumerate(sorted(ICONS.items())):
        icon = fn()
        icon.save(os.path.join(OUT, "%s.png" % name))
        sheet.paste(icon, (i * N, 0))
    # A contact sheet at 6x, purely so a human can eyeball the whole set at once.
    sheet.resize((sheet.width * 6, sheet.height * 6), Image.NEAREST).save(
        os.path.join(OUT, "_contact_sheet.png"))
    print("wrote %d icons to %s" % (len(ICONS), OUT))


if __name__ == "__main__":
    main()
