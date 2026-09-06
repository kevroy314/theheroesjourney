#!/usr/bin/env python3
"""Draw the town plan: the concept art, rendered FROM the plan rather than beside it.

    python3 art/town_concept.py        ->  art/town_plan.png

Kevin's note on the town was "think carefully about the town layout and how to
fit things together naturally... not just some grid of buildings. concept art it
first if that helps", and it did. This is that concept art -- but it imports
`vale_plan()` out of tools/make_world.py rather than restating it, for the
reason the interior demo does NOT and is called out for it in the
interior-layout skill: a hand transcription of a layout is a picture of the
layout you used to have, and nothing will ever tell you it has drifted.

So this file holds no coordinates. It holds a legend.
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import make_world as MW                                     # noqa: E402

PX = 9                                                      # pixels per tile
BOX = (68, 86, 172, 194)                                    # x0, y0, x1, y1

INK = {
    "ground":  (206, 200, 184),
    "water":   (128, 164, 186),
    "bank":    (168, 186, 190),
    "hedge":   (74, 104, 78),
    "paved":   (186, 178, 162),
    "dirt":    (196, 172, 130),
    "bridge":  (150, 116, 78),
    "wall":    (60, 54, 50),
    "roof_thatch":  (196, 166, 96),
    "roof_slate":   (122, 134, 148),
    "roof_pantile": (188, 108, 84),
    "roof":         (150, 118, 84),
    "shed":    (170, 150, 120),
    "house":   (214, 150, 90),
    "door":    (30, 26, 24),
    "gate":    (206, 60, 60),
    "text":    (28, 24, 22),
}

## The point of the drawing. Everything else on it is context for these.
LEGEND = [
    ("mill",        "the mill and grocery -- stone and slate, on the pond"),
    ("commonhouse", "the commonhouse, inn and bank -- brick, the best-built thing here"),
    ("innkeeper",   "the innkeeper's, next door to the inn (twins in the yard)"),
    ("busybodies",  "the busybodies' -- hard on the pavement, facing the square"),
    ("store",       "the general store -- the owner sleeps in the back"),
    ("tavern",      "the seedy tavern, with its yard behind"),
    ("tavernkeep",  "the tavern owner's house, next door"),
    ("tinkerer",    "the tinkerer's workshop and its yard of failures"),
    ("mayor",       "the mayor's -- the only front garden in the parish"),
    ("empty_house", "the empty house. No lamp. Bramble across the path"),
    ("farmhouse",   "the farmhouse, older than the road, alone in its fields"),
    ("neighbour_w", "the guy next door, who works at the bar"),
    ("neighbour_e", "the girl next door, who runs the tinkerer's"),
    ("across",      "the nonbinary across the street, who works at the store"),
]


def main():
    plan = MW.vale_plan()
    w = (BOX[2] - BOX[0]) * PX
    h = (BOX[3] - BOX[1]) * PX
    img = Image.new("RGB", (w, h + 26 * (len(LEGEND) // 2 + 4)), INK["ground"])
    d = ImageDraw.Draw(img)

    def cell(x, y, colour):
        px, py = (x - BOX[0]) * PX, (y - BOX[1]) * PX
        if 0 <= px < w and 0 <= py < h:
            d.rectangle([px, py, px + PX - 1, py + PX - 1], fill=colour)

    for c in plan["water"]:
        cell(c[0], c[1], INK["water"])
    for c in plan["barrier"]:
        cell(c[0], c[1], INK["hedge"])
    for c, material in plan["streets"].items():
        if c in plan["water"]:
            continue
        cell(c[0], c[1], INK["paved"] if material == "floor_stone" else INK["dirt"])
    for c in plan["bridges"]:
        cell(c[0], c[1], INK["bridge"])
    for s in plan["sheds"]:
        for c in s["foot"]:
            cell(c[0], c[1], INK["shed"])

    # The player's house is drawn as itself, not as one of the fifteen: it is
    # fixed, it is where the game starts, and the whole layout is arranged round
    # its front door.
    home = MW.house_plan(MW.region_cells())
    for y in range(home["y0"], home["y0"] + home["h"]):
        for x in range(home["x0"], home["x0"] + home["w"]):
            cell(x, y, INK["house"])
    cell(*home["door"], colour=INK["door"])

    order = {b["id"]: i for i, b in enumerate(plan["buildings"])}
    for b in plan["buildings"]:
        for c in b["foot"]:
            cell(c[0], c[1], INK.get(b["roof"], INK["roof"]))
        for c in b["ring"]:
            cell(c[0], c[1], INK["wall"])
        cell(*b["door"], colour=INK["door"])
    cell(*plan["gate"], colour=INK["gate"])
    for c in plan["fort_wall"]:
        cell(c[0], c[1], INK["hedge"])

    # Numbers, drawn last so nothing paints over them.
    def label(text, x, y, colour=INK["text"]):
        d.text(((x - BOX[0]) * PX, (y - BOX[1]) * PX), text, fill=colour)

    for b in plan["buildings"]:
        label("%d" % (order[b["id"]] + 1), b["x"] + 1, b["y"] + 1, (250, 245, 235))
    label("HOME", home["x0"] + 1, home["y0"] + 1, (40, 30, 20))
    label("GATE", plan["gate"][0] - 5, plan["gate"][1] - 3, INK["gate"])
    label("the Wend", 78, 122)
    label("the Wend", 108, 182)
    label("mill pond", 106, 116)
    label("the leat", 118, 128)
    label("field fence", 112, 93)
    label("the thorn", 163, 150)
    label("market square", 132, 136)
    label("High Street", 128, 130)
    label("Home Lane", 88, 152)
    label("Town Bridge", 112, 147)
    label("North Bridge", 128, 98)

    y = h + 8
    d.text((8, y), "THE VALE  --  town plan, generated from vale_plan() in "
                   "tools/make_world.py", fill=INK["text"])
    y += 18
    for i, (bid, note) in enumerate(LEGEND):
        d.text((8, y), "%2d  %-12s %s" % (i + 1, bid, note), fill=INK["text"])
        y += 14
    y += 6
    for note in (
            "Water first: the Wend (west and south) and the field fence (north) "
            "and the thorn (east) close the vale.",
            "The fort gate on High Street is the only way out, and it is shut "
            "until the town's anomalies are.",
            "The mill leat runs through the middle: the house is on the west "
            "bank, the town on the east, two bridges between.",
            "Roofs say what a building is -- thatch is old and self-built, "
            "slate takes weather, pantile was paid for."):
        d.text((8, y), note, fill=INK["text"])
        y += 14

    out = os.path.join(ROOT, "art", "town_plan.png")
    img.save(out)
    print("wrote %s (%dx%d)" % (out, img.size[0], img.size[1]))


if __name__ == "__main__":
    main()
