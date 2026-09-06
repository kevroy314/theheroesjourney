---
name: interior-layout
description: Lay out and furnish the inside of a building in The Heroes' Journey — rooms, walls, doorways, furniture, evidence of use — so it reads as a place someone lives rather than a box with props in it. Covers the tile-to-feet ruler every clearance is measured against, the order to place things in, the prop-footprint limits that will bite, and how to verify by decoding the collision plane instead of by squinting at a picture. Use when building a house, tavern, shop, hut or any interior, or when changing one that already exists.
---

# Skill: interior-layout

The starting house was rebuilt from scratch because the first version was "too
small and the rooms don't really make any sense in terms of layout". Everything
below is what that rebuild cost to learn. The worked example is `house_plan()`
in `tools/make_world.py`; read it alongside this, because it is the only
interior that exists and its docstring carries the per-decision reasoning.

## Calibrate the tile before you decide anything

**One tile is about three feet.** The derivation is the front door: it is one
cell, a real door is 36 in, so a cell is 36 in. That single fact turns every
later argument from taste into arithmetic:

- 36 in is also the code minimum for a circulation path, so **one clear tile is
  exactly one walkway** and two clear tiles is a generous one.
- A bed one cell by two is a 3 × 6 ft single. A table one by two is 3 × 6 ft,
  which seats four.
- A room 8 × 6 tiles is 24 × 18 ft. That is a large room, not a small one. The
  instinct to make rooms bigger is usually wrong; the instinct to make the
  *furniture* bigger was right, and is why the sprites were redrawn.

A skill that says "leave enough room" without a ruler is useless. Quote every
clearance in tiles and say what it is in feet.

## The procedure

**1. Decide what each room is for, before drawing a wall.** A room reads as
having a purpose or it reads as storage. The failure in the first house was one
17 × 5 hall holding one of everything, which is the shape of a storage unit.
The fix is not to spread the everything out — it is to give the clutter a room
that is *supposed* to be full of it. The English three-cell cottage is the
template that solved this: a hall you enter, a heated room where the cooking
happens, a private chamber, and an **unheated service room** at the low end past
the entrance. The pantry exists so the barrels have somewhere to be barrels.

Adapt the shape, keep the principle. A tavern is common room / kitchen / cellar
/ rooms above. A shop is shopfront / back room / living quarters.

**2. Wall it, and floor each room differently.** §5 of `docs/AESTHETIC-EDA.md`:
interiors are a different material vocabulary, and *each room has its own
floor*. The change of material is what tells the player they have gone
somewhere, before they have seen a stick of the furniture. Put the good boards
in the parlour and cold stone in the service room; that is characterisation for
free. A rug is a fifth material and does a different job — see step 6.

A doorway is a **gap**, not a `door` tile. The wall's overlay set draws its face
into the opening, which reads as a lintel overhead. A `door` tile in an internal
wall is a second front door.

**3. Place one anchor per room, and let everything else serve it.** Parlour: the
bed. Kitchen: the range, and the table that faces it. Hall: the door you come in
by, plus the reading corner under the window. Pantry: the shelves. If you cannot
name a room's anchor, go back to step 1 — you have not decided what it is for.

**4. Draw the circulation, and keep it empty.** Circulation is a *path*, and it
must not run through the furniture. The middle of the hall is left open not
because open floor looks nice but because it is the route from the front door to
every other room in the house. Work out which cells carry traffic first, then
place around them. In the kitchen this is also a working rule: both doorways are
at the south end, so nobody crossing the house walks through the cook.

**5. Case goods against walls. Only tables float.** Every bookshelf, dresser,
chest, shelf, counter and cask has its back on a wall cell. Tables, chairs and
rugs are the only things allowed in open floor. This is the single rule that
separates a furnished room from a warehouse floor — a bookshelf in the middle of
a room is a bug, not a style.

**6. Build working relationships, not just adjacency.** Two pieces near each
other are decor; two pieces in sequence are a kitchen. The house's run is
**cold store → sink → range**, with a tile of landing counter each side of both
the sink and the range. The numbers, checked:

| Guideline | The real figure | Ours |
|---|---|---|
| NKBA work triangle, total | ≤ 26 ft, each leg 4–9 ft | two legs of 2 tiles = 6 ft each, 12 ft total |
| NKBA countertop frontage (Guideline 25) | 158 in ≈ 13.2 ft | 5 counter cells = 15 ft |
| NKBA landing beside sink / cooktop | 24 in and 18 in / 12 in and 15 in | 1 tile = 36 in each side |

**`house_plan()`'s docstring cites "the NKBA rule for a single-wall kitchen:
cold store, sink, range within 12 ft". That phrasing is not an NKBA guideline** —
NKBA states the triangle as ≤ 26 ft total with each leg 4–9 ft. The layout is
compliant with the real rule and comfortably so; the citation is loose. Cite the
figure above, not the docstring. Look up whatever you cite in a new room.

Rugs are the other relationship device: a rug makes a group of furniture read as
one zone rather than three objects, and to do that **it has to reach under the
front of every piece in the group**. One beside the bed where the player's feet
land, one under the reading corner.

**7. Let doors and windows constrain everything.** Nothing solid stands on a
doorway landing cell, on either side. Nothing solid stands on the floor cell in
front of a window — a window with a chest under it is a window nobody can look
out of, and it looks like a mistake. A bed's headboard goes on a solid wall, not
under a window, and **not in the column of a doorway**: you do not lie with your
feet pointing out of the door.

Clearances the house meets, all in tiles, all against the 3 ft ruler:

| Where | Clear tiles | Why |
|---|---|---|
| Both sides of every internal doorway | 1 | one walkway |
| In front of the front door | 2 | you arrive here and turn |
| Each side of the bed, and its foot | 1 | you have to make it |
| Every used side of a table | 1 | the chair ring |
| Between the kitchen run and the table | 2 | someone passes behind the cook |
| Down the middle of the pantry | 2 | reaches every shelf |
| Floor cell in front of every window | 1 (nothing solid) | see above |

**8. Place evidence of use last, and deliberately.** From the liveness list in
`docs/AESTHETIC-EDA.md`, which calls it the big one: *a level should imply an
event that already happened.* It is the cheapest narrative device available and
the old house used none of it. In the current house: four chairs at the kitchen
table and a fifth pushed back and turned away, **with the cell it was pulled out
of left empty** — the gap is the whole trick, a `chair_pulled` against a full
table says nothing. Boots by the front door with the dog beside them. A book
face-down on the boards under the reading lamp. A candle by the bed and a bed
nobody made.

Do this last, on purpose, so it lands in the gaps the layout produced rather
than dictating them. All the evidence-of-use props (`cup`, `bottle`,
`book_open`, `boots`, `candle`) are non-solid, so they can never strand a cell.

**9. Verify by decoding. Never by looking.** A picture cannot tell you that a
chair was silently dropped, and the old `furnish_house` did exactly that — it
recomputed the internal wall, got it wrong, and `continue`d past everything that
landed on one. `placed` props have no density, so the validator's "this prop
never appears" warning cannot see them either. Three checks, in order:

```bash
python3 tools/make_world.py            # raises on anything it cannot place
python3 tools/validate_data.py         # or: npm run check
```

then decode the planes and read them:

```python
import base64, json, zlib
w = json.load(open("data/world/overworld.json"))
W = w["w"]
props   = zlib.decompress(base64.b64decode(w["props_b64_deflate"]))
blocked = zlib.decompress(base64.b64decode(w["blocked_b64_deflate"]))
cat = {p["plane"]: p for p in json.load(open("assets/tiles/tiles.json"))["props"]["list"]}
r = w["indoors"]                        # the house's rectangle, written by make_world
for y in range(r["y"], r["y"] + r["h"]):
    for x in range(r["x"], r["x"] + r["w"]):
        v = props[y * W + x]
        if v and cat[v]["solid"] != bool(blocked[y * W + x]):
            print("wrong solidity", cat[v]["id"], x, y)
```

That currently reports 79 props indoors (73 furniture + 6 windows) and zero
mismatches. Count what you placed and check the count comes back.

`make_world.py` then does the two flood fills itself, and both are build
failures rather than warnings:

- **Stranded**: flood-fill from the spawn with the furniture solid. Every
  walkable cell inside the footprint must be reachable from the bed. *A pocket
  behind a barrel is a cell the player can see, walk at, and never stand on* —
  and a hand-placed layout is exactly where that happens, because you are
  reasoning about a picture and the collision plane is reasoning about bytes.
- **Sealed**: flood-fill again with the *front door treated as solid*. Nothing
  outside the footprint may be reachable. `HJWorld.walkable()` returns false on
  the door cell until the Grit is paid, so that one cell is the entire Beat 4
  gate; a gap anywhere else in the wall and the tutorial economy is bypassed by
  walking round it. The hole would never be in your plan — it would be something
  a later pass did, which is precisely what happened when the road carver drove
  seven columns of dirt through the east wall.

## Where the code is

| Thing | Where |
|---|---|
| The geometry — rooms, walls, doorways, windows, furniture, spawn | `house_plan()` in `tools/make_world.py` |
| Painting floors and walls from that plan | `stamp_house()`, same file |
| Placing furniture, and refusing to lose a piece | `furnish_house()`, same file |
| Wiring, flood fills, Spite, the yard | `main()` in `tools/make_world.py` |
| Furniture sprites | `b_furniture()` in `tools/make_tiles.py` |
| Cap and face primitives | `_slab()`, `_face()`, `_legs()`, same file |
| The room preview | `interior_demo()` → `assets/tiles/_comp_interior.png` |
| The footprint check | `furniture_sheet()` → `assets/tiles/_furniture_x3.png` |

**`house_plan()` is the single source of the geometry, and nothing may recompute
a wall position.** Every other pass reads the dict it returns. The reason is not
tidiness: the previous code worked the internal wall out in `stamp_house` and
worked it out *again, differently and wrongly*, in `furnish_house`, and a chair
ended up inside a wall. If you need a wall position somewhere new, read it from
the plan.

Two pictures, and they answer different questions:

- **`_comp_interior.png`** is the room, drawn the way the game will draw it. It
  is the frame every judgement about the furniture has to be made in, because a
  chair is only the right size *in a room*.
- **`_furniture_x3.png`** is the check that was missing. Every placed prop is
  drawn over the cells it actually blocks, footprint picked out in gold, and the
  art's bounding box measured against it in pixels underneath. If the art does
  not reach the edges of the bright rectangle, the prop is too small — and no
  amount of looking at a sprite on its own will tell you that. This is how the
  whole set was caught at roughly half size: a table 25 px wide in a 32 px cell,
  a chest 17 px, a barrel 15. **The rule is that a one-cell piece is drawn 29–31
  px wide and at least 32 px tall.** Anything taller than a table then grows
  upward past its cell, which is what reads as height.

## Drawing a new piece of furniture

Interior furniture uses the **`timber`** ramp, not `wood`. They are the same hue
and that is the point: `wood` tops out at luma 78, which is fine for a fencepost
on grass and is why a table on a board floor of the same hue read as a stain.
`timber` sits at mean 68 / spread 54 so a prop reaches the 110–135 crown §2.6
asks for. Tree trunks and gate rails keep `wood`.

Build the piece as **cap plus face** (§2): `_slab()` for every horizontal
surface, lit along its north edge and falling to base at the south, and
`_face()` for the vertical front, lit west, dark east, with a deep line along
the floor that stops it floating. A tabletop drawn as one flat colour reads as a
rectangle; drawn as a ramp it reads as a plane with a thickness, and that is the
whole difference between furniture and a sticker.

To bring in art from outside, use `tools/add_prop.py add` — it regrades into the
same ramps, appends to the catalogue, and refuses to move an existing plane id.

## Traps

**Prop footprints grow east and north, and only `(1, k)` is honest (#82).** The
art is centred on the anchor cell in a 64 × 96 slot, so a `(2, k)` prop can
block its second cell but **cannot reach it with pixels** — the art stops
halfway. `bench`, `well`, `cart`, `market_stall` and the fallen logs all
declared two cells and drew one; every one has been demoted to `(1, 1)`. The bed
and the table are `(1, 2)`, growing *north*, which works because the slot is
three cells tall. Until #82 lands (symmetric footprints, making 1 and 3
drawable), **do not declare a width of 2** — it is a prop that lies about its
size, and the player finds out by not being able to walk somewhere.

**One prop per cell: a cup cannot stand on a counter (#83).** `props[y][x]` is
one byte. So two of the four canonical evidence-of-use props — the cup on the
counter and the open book on the table — currently sit on the *floor* beside the
thing they belong on, which says something rather different about who lives
here. Do not work around it with a `counter_with_cup` variant; that multiplies
the catalogue combinatorially and the whole point of the authored catalogue is
that it is finite. Place the clutter on the floor and wait for the clutter
plane.

**Run `npm run tiles`, never bare `make_tiles.py`.** The atlas is rebuilt from
scratch and `add_prop.py`'s authored props live past the generated ones, so a
bare run leaves `tiles.json` short and the Tiled map referencing a prop no
catalogue can read. `npm run tiles` is `make_tiles.py && add_prop.py reapply`.
Then `python3 tools/make_world.py`, in that order — `make_world` reads the
`tiles.json` that `make_tiles` writes.

**`interior_demo()` is a hand transcription of `house_plan()`.** It holds the
plan as an ASCII grid and the furniture as a second literal list, kept separate
because `make_world.py` reads the `tiles.json` that `make_tiles.py` writes and
an import would be circular. Nothing reads it back, so nothing will catch the
drift — **change the plan and you must change the transcription**, or the
picture you are checking your layout against is a picture of the old layout.

**`python3 tools/make_world.py` is not a convenience command and has no npm
alias on purpose.** It regenerates from scratch and overwrites anything imported
from Tiled.

**The world must be reproducible.** One `random.Random(20260901)` is threaded
through everything; the previous version seeded an RNG and then called the bare
global `random.random()` inside the road carver, so two runs produced two
different worlds while the docstring promised otherwise. A hand-placed interior
must contain no randomness at all. Re-run the generator twice and diff the
output.

**Stamp, carve roads, then stamp again.** Roads go in last so nothing paints
over them, and the building is re-stamped afterwards so no later pass can open
the wall up again. Aim the road at `door_outside`, never at the building's
centre: `carve_road` lays dirt in a plus around every cell it walks.

**Interior props must not be `scatter`able.** They are `biome: "placed"` in the
catalogue and are put down by hand. A procedural hole in the kitchen would make
Beat 2 unfindable, so the house footprint is passed to `place_anomalies` as
`forbid`.

## What is not solved

Be honest about these rather than faking round them.

- **There is no hearth, fireplace or sink sprite.** The kitchen's "sink" is a
  `counter` standing under a window and its "dresser" is a `bookshelf`; the
  `stove` is the only heat source and the only warm light in the building. A
  room whose design depends on an open fire cannot be built yet.
- **Nothing can stand on anything** (#83), so a pot on the stove, a cup on the
  counter and a book on the table are all unavailable.
- **Nothing is two cells wide** (#82), so a market stall, a four-poster, a long
  bar or a dining table for eight is not expressible.
- **No smoke**, because there is no chimney or brazier prop for it to attach to.
  The idle-motion mode exists and is a free slot the moment the art does.
