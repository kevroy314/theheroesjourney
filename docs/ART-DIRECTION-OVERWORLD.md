# Art direction: the overworld

> "The tiles we have and the character just don't look good. Maybe the character
> model needs a rework and definitely we need a more mature set of tiles to make
> the map feel real. There's no sense of depth."

This is the diagnosis and the specification. It is not art. Every number below
was measured off the shipped assets and the shipped `data/world/overworld.json`,
not estimated.

---

# Part 1 — Diagnosis

## 1.0 What the player is actually looking at

`OverworldScreen` gives the map whatever the header, the chips, the action
button and the d-pad leave: roughly **720 x 730 logical pixels**. `TileWorld`
draws at `ZOOM = 3`, so a 32px tile is 96 logical pixels.

**The player sees 7.5 x 7.6 tiles. About 57 cells. That is the entire frame.**

That number is the root of everything else in this document. At 57 cells a
screen, a tileset of flat material fills is not a texture — it is fifty-seven
enormous squares. Every design decision in `make_tiles.py` was made looking at a
32x32 image or a 4x contact sheet. None of them were made looking at 57 cells at
96px each.

Everything described below was read off frames composited from the real world
grid, the real `tileset.png` and the real `player.png` at `ZOOM = 3` — i.e.
exactly what the device shows, not what the contact sheet shows. Reproduce them
by pasting `tileset.png` regions per `overworld.json` cell into a 8 x 8 tile
window and scaling 3x nearest; the useful anchors are `waking_room`, `the_town`,
`tall_grass`, `foothills`, `summit`, and any cell on the coast.

## 1.1 Fault one: the world is empty. This is the biggest fault and it is not on your list.

I swept every position the player can legally stand in (32,117 of them) and
counted how many distinct materials appear in the 8x8 window around them.

```
viewports sampled (character standing on walkable ground): 32117
  showing exactly 1 material :  16061   50.0%
  showing <= 2 materials     :  27402   85.3%
  mean distinct materials per screen: 1.70
```

**Half of all screens in this game are one texture repeated 57 times.** Not one
biome — one *tile*, laid 57 times, with nothing else in frame. 85% of screens
show two or fewer.

There is no props layer. There is no scatter. `assets/tiles/` contains seventeen
PNGs and every one of them is a ground material; there is not a single rock, no
bush, no stump, no flower, no fencepost, no signpost, no cart, no barrel, no
crate, no well, no gravestone, no boulder, no fallen log. `grep -r "prop\|decor\|
scatter"` across `scripts/` returns nothing. The concept does not exist in the
codebase.

A mature top-down game does not spend its tile budget on materials. It spends it
on *things standing on* materials. Stardew Valley, Zelda: A Link to the Past,
Tibia, CrossCode — walk in any of them and every screen has six to fifteen
objects in it. That is what stops the ground reading as wallpaper. Ours has
zero.

**The clearest example is the first screen of the game.** Render the view at the
`waking_room` anchor and you get: a large empty brown floor, a flat grey band
across the top, a flat grey band across the bottom with a door in it, one grey
figure, and nothing else. **The room the player wakes up in has no bed.** No
chair, no table, no window, no rug, no lamp, no chest. The story is "you wake and
cross a bedroom floor", and there is nothing in the bedroom.

The same shot shows the wall problem in isolation: `wall_plaster` is a flat band
with no thickness, no top edge, no base shadow and no different treatment from
the floor it abuts. It reads as a grey *stripe painted on the floor*, not as a
wall you are standing next to.

This is the single cheapest, largest win available, and it is not a tile problem
at all.

## 1.2 Fault two: no transitions — confirmed, and the worst edge is the most common one

Confirmed exactly as hypothesised. Every material meets every other material
along a hard 32px staircase. At 96 screen pixels per tile the staircase is
enormous and rectilinear, and the eye reads it as *authored geometry* — as if
someone drew the coastline with a mouse in MS Paint at 45 degrees.

I counted every material boundary in the shipped world:

```
distinct material adjacencies present: 50 pairs
total boundary edges: 4,922 (5.1% of all interior edges)

  sand         | water          771  15.7%     <- the single most common edge in the game
  grass_short  | scree          585  11.9%
  grass_short  | sand           547  11.1%
  grass_short  | grass_tall     424   8.6%
  forest       | sand           404   8.2%
  forest       | grass_short    393   8.0%
  scree        | snow           310   6.3%
  grass_short  | path_dirt      234   4.8%
  forest       | path_dirt      158   3.2%
  path_dirt    | snow           108   2.2%
  ... 40 more pairs, 20% of edges between them
```

Two things fall out of that table.

**The shoreline is the most-seen edge in the game** — 21.8% of the world is
water, 7.7% is sand, and `sand | water` is 15.7% of all boundaries. There is no
beach, no foam, no wet sand, no shallows. The sea ends and the sand begins on a
96-pixel step.

**The top ten pairs are 80% of all boundaries.** You do not need transitions for
fifty pairs. This matters enormously for the cost estimate in Part 2.

## 1.3 Fault three: no depth, and here is the number

Confirmed, and sharper than "nothing has a shadow". Measure the luma histogram
of one real in-game frame against one of the game's own backdrops:

```
                                    min   p1   p50   p99   max
one in-game overworld frame          11    34    53    81   122
assets/backdrops/areas/the_town      11    11    24    95   232
assets/backdrops/areas/summit         9     9    21   162   179
assets/tiles/tileset.png (all 17)     9     9    55    92   118
```

**The overworld frame lives entirely inside a 47-point band centred on
mid-grey.** No blacks. No lights. Nothing below 34, nothing above 122, half the
frame between 34 and 53.

The backdrops — which are excellent, and are this game's established visual
identity — have a *dark* median (21–28) and a long bright tail to 232. That is
what depth is, in 2D: a wide value range where the light lands on the near/top
surfaces and the recesses go genuinely dark. The overworld has thrown that range
away and there is nothing left to build depth out of.

`make_tiles.py`'s "Quiet" rule — "each tile keeps its own value range narrow,
roughly 25 luma points" — is a correct rule about *one material's internal
texture* that has been applied to the *entire scene*. See §2.6; this is fixable
without breaking the thing the rule was protecting.

The mechanical consequences, all confirmed:

- **Nothing has a face.** Elevation is 100% a colour change. `grass_short` ->
  `scree` -> `snow` are three flat fills; the mountain has no cliffs, no ledges,
  no visible side to anything.
- **Nothing casts a shadow.** Not the character, not the trees, not the
  buildings, not the rocks. The character is composited straight onto the tile
  and floats.
- **The elevation data exists and is thrown away.** `make_world.py` builds a
  full `elev` field, uses it to threshold biomes and to hillshade the drawn
  map — and then does not write it to `overworld.json`. The keys are `w`, `h`,
  `tiles_b64_deflate`, `regions`, `spawn`. The game has no idea how high
  anything is. The drawn map has depth *because it renders that field*; the
  tilemap has none *because it doesn't*. Same data, one uses it.

## 1.4 Fault four: props are tiles — confirmed, and it is worse in the town

Confirmed. `stamp_town()` fills a 4-6 x 3-5 rectangle with the `roof` tile and
puts a `door` tile in the bottom edge. `stamp_house()` draws a rectangle of
`wall_plaster` with `floor_boards` inside.

Rendered, the town is unreadable. In the shot I generated at the town anchor
there are three surfaces on screen — grey brick, brown brick, and brown planks —
and **none of them reads as ground.** The paved street (`floor_stone`) is drawn
as horizontal brick courses with continuous mortar lines, which the eye reads as
a *vertical wall*. The roof (`roof`) is drawn as shingle courses, which also
reads as a vertical wall. The player stands in the middle of what looks like the
inside of a chimney.

The summit is the same failure in its purest form: the shot at the summit anchor
is a full screen of `floor_stone` with an amber door at the top, and it reads
unambiguously as *a brick wall you are standing on*, not as a stone platform.
Horizontal courses with unbroken mortar lines are a wall convention. Top-down
paving is irregular polygonal slabs with broken joints, and never a continuous
straight mortar line running the width of the screen.

Buildings have no footprint, no facade, no eave, no shadow, no relationship to
the ground they stand on. Numerically:

```
roof | water     66 edges     buildings standing in the sea
roof | sand      34 edges
door | water      6 edges     doors opening onto open water
door | rock       2
door | snow       1
```

## 1.5 Fault five (unlisted): you cannot see what is solid

This is a gameplay bug wearing an art costume.

```
                                  dLuma   dRGB
grass_short  vs  forest             5.1    4.3     walkable vs SOLID
grass_short  vs  grass_tall         0.8    0.6     two different chapters
path_dirt    vs  roof               0.7    4.5     the road vs a building
roof         vs  floor_stone        3.4   16.9
```

`forest` is **solid** and `grass_short` is **walkable**, and they differ by 4.3
RGB points on average. On a phone, outdoors, at 3x, you cannot tell where the
wall is. `make_tiles.py`'s comment on `wall_plaster` — "the player must never
have to think about whether a tile is walkable" — is the right rule, and it was
applied to the interior walls and then not applied to the 3,617 forest tiles
that are 7.5% of the world.

`grass_short` and `grass_tall` are the same colour to within 0.6 RGB points.
Chapter 4's whole identity is a texture difference invisible at arm's length.

## 1.6 Fault six: the character

Honest read, at 1:1 and at 3x on eight different ground tiles.

**Silhouette.** Hood 10 wide, shoulders 16, waist 12, skirt 14, and 4 pixels of
leg under it. The step at the shoulder is real and does its job. But the whole
figure below the hood is one continuous barrel, and the outline that results
reads as **a chess pawn, a bollard, a fire hydrant** — not a person. There are no
arms in the silhouette (they are two columns of shadow *inside* it), no hands,
and the legs are too short a fraction of the figure to register as legs. From
outside the outline, it is a lump with a smaller lump on top.

**Facing.** Down and up are the same silhouette. The only difference is a dark
patch where the face is and a diagonal strap line. At 3x, standing still, on a
phone, **you cannot tell which way he is facing.** For a game whose entire verb
is "walk in one of four directions", that is a functional failure.

**Colour.** Ten colours in the whole sheet, nine opaque, and eight of them are
one blue-grey ramp from `line` to `muted`. He owns exactly **two amber pixels**
(the belt buckle). He has no skin, no hair, no cloth colour, no boots that are a
different material from the cloak. He is a greyscale figure in a grey-green-brown
world.

**Contrast — and this is where the documented claim is false.** `make_sprites.py`
says the cloak is pulled to `muted` so "the player has to be the lightest thing
on the ground plane". Measured:

```
player frame 0: 403 opaque px, luma 11..122, MEAN 54.0
ground means:  forest 50.2  grass_tall 54.5  grass_short 55.3  path_dirt 57.6
               floor_stone 61.6  sand 73.4  snow 80.3
```

**His mean value is 54.0. The grass he spends chapter 4 on is 55.3.** He is not
the lightest thing on the ground plane; he is exactly the same value as it. Only
his hood crown reaches 118, and that is 48 pixels out of 403 — 12% of him. On
sand (73) and snow (80) he is a *dark* blob. On `floor_stone` he is nearly
invisible: both are blue-grey at the same value, and only the black outline
separates them.

The outline is doing 100% of the work. That is why he reads as a cut-out sticker
pasted on the ground rather than as someone standing on it.

**No shadow.** He floats. On sand and snow this is glaring.

**Frame count.** 3 columns played `1,0,2,0` is fine and the "neutral in the
middle" decision is correct. Frame count is not the problem.

**Verdict: rework, not fix.** The proportions, the palette, the read of the
facings and the absence of a shadow are all wrong at once, and they are wrong in
ways that interact. You cannot fix the facing problem without changing the
silhouette; you cannot fix the contrast without changing the ramp; and the ramp
is what makes the silhouette flat. Redraw him. See §2.4.

## 1.7 Minor, but real on a device: the pixel grid is not on the pixel grid

`project.godot` is `720 x 1280`, `stretch/mode = canvas_items`,
`aspect = keep_width`. On a 1080-wide phone — which is most of them — the canvas
is scaled by **1.5**. On top of `ZOOM = 3` that is an effective **4.5x**, a
non-integer scale, so every source pixel is rendered 4 or 5 device pixels wide,
alternating. The character's 1px outline is thicker on one side than the other
and the tile grid lands on half-pixel boundaries.

It is not why the art looks bad, but it is why it looks *slightly wrong* in a way
that is hard to name, and the owner played it on a device. On a 1440-wide phone
(2.0x, 6.0 effective) it is clean. Fix is in §3, Stage 0.

## 1.8 What is right, and must not be broken in the fixing

- **`worldmap.png` works, and it tells you why.** It is the same grid, and it
  reads as a place. Two reasons: (a) at 4px per tile the 32px staircase is one
  map pixel and disappears, and (b) **it renders the elevation field as a
  hillshade.** The map has depth for exactly the reason the tilemap doesn't.
- **The backdrops are the identity.** `assets/backdrops/areas/*.png` are 32-colour
  pixel art with a dark median, warm lamplight against cool night, real
  atmospheric depth. That is what the overworld should feel like a piece of. Any
  adopted tileset has to survive comparison with them on the same phone.
- **The seams work.** The wrapping `px()` is genuinely clever and the numeric
  seam verification is worth keeping. Nothing below asks you to give it up.
- **Palette derivation.** No hex is hardcoded; a theme swap moves the art. That
  is worth real money and it is the single strongest argument against adopting a
  third-party tileset wholesale.
- **The world generator is good.** Two noise fields, thresholded biomes, no zone
  borders, a road that follows the terrain. The problem is not the world. The
  problem is how it is drawn.

---

# Part 2 — Specification

## 2.1 Transitions: a **precedence overlay on the world grid**

### The choice

> **I specced the dual grid first and the research overturned it.** The
> correction is recorded here rather than quietly removed, because the reason it
> loses is specific to this game and someone will otherwise re-propose it.

Five candidates, with verified numbers:

| Approach | Tiles per material | For our 7 | Inner corners | 3-way junctions | Boundary sits on the logic grid |
|---|---|---|---|---|---|
| 4-bit cardinal (Wang edge) set | 16 | 112 | **no** — blocky junctions | no | yes |
| 4-bit corner set / marching squares | 16 | 112 | yes | no | yes |
| 8-bit "blob", reduced from 256 | **47** (+1 empty) | **329** | yes | only with per-triple art | yes |
| Explicit per-pair transition tiles | 256 per *ordered pair* | unworkable | yes | no | yes |
| Dual-grid (corners of the dual cell) | **16** | 112 | yes | yes, free | **NO — off by half a tile** |
| **Precedence overlay (16 edge + 16 corner)** | **32** | **224** | **yes** | **yes, free** | **yes** |

**Take the precedence overlay.** It is the 2000-vintage, still-canonical answer
(David Michael's *Handling Terrain Transitions*, GameDev.net), it is what
Factorio and Battle for Wesnoth actually ship, and it is the only option that
gets corner-correct transitions *and* keeps the visual material boundary exactly
where the walkable boundary is.

### Why not the dual grid, specifically

The dual grid is genuinely elegant: offset the display grid by half a tile, each
display cell sits on the corner shared by four world cells, four booleans,
sixteen tiles. It is Oskar Stålberg's trick, popularised by jess::codes, and
there are two good MIT Godot addons for it (`pablogila/TileMapDual`,
`jess-hammer/dual-grid-tilemap-system-godot`).

Three things kill it here, and the first is decisive:

1. **The boundary is displaced half a tile — 16 world px, 48 screen px at our
   zoom — and our materials carry walkability.** `water`, `forest`, `rock` and
   the walls are SOLID. Under a dual grid, half of every water cell along a
   beach is drawn as sand. At 96px per tile that is a 48-pixel band of ground
   the player can see, walk toward, and be stopped by. Stålberg says this himself:
   *"keep both concepts around… Most gameplay will still happen on the main grid.
   The dual grid is mostly for field-like background tilesets."* Ours is not a
   background tileset; it is the collision map.
2. **It is not equivalent to the 47-blob, which is what I claimed.** Per
   BorisTheBrave, a dual grid is marching squares on the dual cell: every corner
   comes out at an identical radius, there is much less shape variety, and it
   **cannot create curves larger than half a tile width**.
3. Godot has no built-in support (proposal
   [godot-proposals#10567](https://github.com/godotengine/godot-proposals/issues/10567),
   76 reactions, no PR) — irrelevant to us since we render by hand, but it means
   no ecosystem to lean on.

With a precedence overlay the intrusion depth is **an art decision, not a
structural one**: draw the fringe 6–10px into the neighbouring cell and the lie
about walkability stays under a third of a tile.

### How it works, precisely

Michael's decomposition, verbatim on the counts:

> "there are only **16 possible edge transitions, and 16 possible corner
> transitions. By using combinations of edge and corner transitions you can
> create all of the necessary 256 variations with only 32 total tiles.**"

⚠️ Note the arithmetic that the popular write-ups get wrong: the 8-neighbour
space is **256**, and the blob reduction is **47 of 256** (not 255) — cr31's
original constraint is that a corner bit only matters when both its adjacent
side bits are set. The 16+16 split covers all 256 with 32 overlay tiles because
it draws two passes instead of one.

So, per cell:

```
1. draw the cell's own material fill                       (1 draw)
2. for each DISTINCT higher-precedence material among its 8 neighbours,
   lowest precedence first:
      draw that material's edge tile   for the 4-bit side mask     (1 draw)
      draw that material's corner tile for the diagonals whose two
      adjacent sides are unset                                     (0-1 draws)
```

The overlays are RGBA with a hard alpha edge — no soft blur, nearest filtering
must stay lossless. Each is the higher material's own texture spilling a short
way into the lower cell, plus a 2–3px lip along the boundary that is what makes
sand read as *beach* and grass read as *turf*.

**Factorio's refinement, worth taking:** author the 32 shapes **once as
greyscale alpha masks** and composite each material's own fill through them at
build time. FFF #214: *"The alpha mask is a greyscale or single channel image
which is multiplied with the actual texture… masks, that are shared by multiple
terrains."* In our PIL pipeline that is **one mask generator plus seven
short per-material lip functions**, emitting 224 pre-composited PNGs. Nobody
draws 224 of anything.

### The priority stack, and why it makes this cheap

Assign every material a rank ("precedence", in Michael's terminology). A cell
draws its own fill, then every **higher-ranked** neighbouring material overlays
it, lowest first. Because the overlays compose in a fixed total order, three-
and four-way junctions resolve for free — including the 141 places in the
shipped world where three or four materials meet — with no per-triple art.

This is not an invention. Michael, on the game *Artifact*, 2000:

> "The first part of our solution was to assign a **'precedence'** to the
> various terrain types… **this precedence does not reflect the relative
> elevations of the terrain but is instead based on which terrains look best
> when overlapping other terrains.**"
>
> "for each map cell, you check all adjacency possibilities for terrain types
> that overlap the terrain of the cell… **you need only consider any adjacent
> jungles, forests, and mountains, since those are the only terrain types that
> have a higher precedence.**"

Battle for Wesnoth ships the same idea as a numeric `layer` field (−1000 base,
−80 under-unit overlays, 0 overlays); Portponky's Better Terrain addon calls it
"Match vertices" and picks *"the highest neighboring terrain type… highest in
the terrain list"*. Independent arrival by three shipped systems is about as
much validation as this kind of decision gets.

Ranks, chosen from our actual adjacency data — and note Michael's warning that
this is a *look* ordering, not an elevation ordering:

```
0  water          (bottom; never needs an edge set)
1  sand
2  grass_short
3  scree
4  snow
5  grass_tall
6  forest
7  path_dirt      (a road is laid *on* the ground, so it is on top)
```

I validated this against the shipped map:

```
natural-terrain boundary edges: 4223
resolved by the 8-entry priority order: 4223 (100.0%)
ties needing a special case: none
```

**One 8-entry list and seven edge sets cover every natural terrain boundary in
the game.** Not fifty pair-specific transition sets. Seven.

Under a priority stack the *higher-ranked* material owns the edge. That gives a
clean build order, and the workload is remarkably evenly spread — there is no
one set you can write and be done:

```
edge set        edges  % of natural boundaries  cumulative
  forest          892          21.1%              21.1%
  sand            771          18.3%              39.4%
  grass_short     601          14.2%              53.6%
  path_dirt       595          14.1%              67.7%
  scree           585          13.9%              81.6%
  grass_tall      469          11.1%              92.7%
  snow            310           7.3%             100.0%
                 ----
                 4223  (85.8% of all 4,922 boundary edges;
                        the remaining 14.2% are architectural — §2.3)
```

**One caveat, which is standard and accepted everywhere.** Under a precedence
scheme a material's overlay looks the same regardless of what is beneath it:
grass gets the same turf lip against water as against sand. Factorio, Wesnoth
and LPC all live with this. The one place it looks wrong here is
`grass_short | water` with no beach between (54 edges, 1.1%) — fix it in the
generator by forcing a one-cell `sand` ring at any grass/water contact, which is
four lines in `make_world.py` and also happens to be how real coastlines work.

### The commitment, in tiles a person actually draws

| | count | notes |
|---|---:|---|
| Base material fills | 8 | already exist; re-graded per §2.6 |
| Fill variants (break the 32px repeat) | 8 | one alternate per material, chosen by a hash of (x,y) |
| **Overlay sets, 7 materials x (16 edge + 16 corner)** | **224** | *generated from 32 shared masks* — see below |
| Cliff / wall set (§2.2) | 16 | |
| Outdoor props and landmarks (§2.3) | ~30 | |
| Interior furniture (§2.3) | ~10 | bed, chair, table, chest, rug, barrel, crate… |
| Architecture: roofs, facades, doors (§2.3) | ~24 | |
| **Total sprites** | **~320** | vs 17 today |

**The 224 is not 224 drawings, and this is the load-bearing argument for keeping
the PIL pipeline.** The 32 mask shapes are geometry — an edge and a corner in
sixteen orientations — written once as a `masks()` generator. Each material then
needs one short function saying *how it finishes*: a fringe of blades for grass,
a foam line and a wet band for sand, a ragged chip line for scree, a drift lip
for snow, a swept verge for path. Compose fill through mask, stamp the lip along
the boundary, emit.

**One generator plus seven ~25-line functions.** In Aseprite the same 224 tiles
are 40–80 hours of drawing; the whole point of having a programmatic pipeline is
that this is the case where it wins by an order of magnitude. We have been using
it for the character, where it loses (§2.4), and not for this, where it wins.

### What the generator stores, and what it costs at runtime

Nothing new on disk. At load, `HJWorld` precomputes **one byte per cell per
material rank present in its neighbourhood** — in practice a single
`PackedByteArray` of `(side_mask, corner_mask, overlay_material)` triples for
the 8.9% of cells that need one, and a null entry for the rest:

```
for each cell:
    for each distinct higher-precedence material among its 8 neighbours:
        emit (overlay_material, 4-bit side mask, 4-bit corner mask)
```

Measured against the shipped map:

```
natural-terrain cells: 47006
  0 higher-precedence neighbour materials:  42824   91.10%   <- one draw, no overlay
  1                                          4087    8.69%
  2                                            94    0.20%
  3                                             1    0.00%
mean overlay materials per cell: 0.091
```

**91.1% of cells need exactly one draw call.** Mean draws per cell is **1.18**.
A 57-cell window is ~67 `draw_texture_rect_region` calls per frame against 57
today. The overlay list for the whole map is ~4,300 entries — about **17 KB
resident**, versus 340 KB for the dual-grid layer planes. It is cheaper at
runtime as well as more correct.

### Data format change: none

`overworld.json` is untouched — the overlay list is derived at load from the
existing tile plane. No format change, no regeneration of saved worlds, no tile
renumbering. **The transition work touches zero saved data.**

### A note on why we are not moving to Godot's TileMap

We render in one `_draw`. It would be tempting to migrate to `TileMapLayer` and
use Godot 4's built-in terrain system instead of writing any of the above. Do
not. The built-in system is a **scoring heuristic, not a matcher** —
`_get_best_terrain_pattern_for_constraints()` accrues a penalty per violated
constraint and takes the lowest total, so a missing case silently yields the
least-bad tile; `terrain_fill_constraints()` is greedy, commits as it goes and
never backtracks. Consequences are documented and open:

- [#73903](https://github.com/godotengine/godot/issues/73903) different results depending on the order you place tiles
- [#76493](https://github.com/godotengine/godot/issues/76493) paints tiles from unrelated terrains
- [#70218](https://github.com/godotengine/godot/issues/70218) masks impossible to express in 3x3-minimal
- [#80635](https://github.com/godotengine/godot/issues/80635) too slow to update per frame (~16 ms for three 10x8 layers)
- [proposal #5575](https://github.com/godotengine/godot-proposals/issues/5575) (262 reactions) and
  [#7670](https://github.com/godotengine/godot-proposals/issues/7670) — the latter, by the author of the
  Terrain Autotiler addon: *"it shipped with an algorithm that isn't built to handle the complexity of
  the underlying system… a significant regression from Godot 3.x's autotiles."*

Godot 3's `FallbackMode.FALLBACK_AUTO` and `update_bitmask_region()` have no
Godot 4 equivalent. The official forum position from the same author is that
Godot 4 autotiling *"is not very accurate and so it is not intended to be used
at runtime."* **Our hand-rolled precedence overlay is deterministic, order-
independent and a pure function of the 8 neighbours. Keep it.**

(If you ever do migrate the tilemap for other reasons, the addon to use is
**Portponky/better-terrain** — The Unlicense, 741★, actively maintained — whose
"Match vertices" mode is this same precedence idea. **Terrain Autotiler** is
`dandeliondino/terrain-autotiler` and is **archived, unmaintained since April
2024**; read it for the analysis, do not depend on it.)

## 2.2 Depth

Four separate mechanisms. They are independent; do them in this order.

### (a) The value range — do this first, it is free

See §2.6. Nothing below produces depth if the whole scene lives in a 47-point
band. Re-grading the palette costs a few hours and improves every other item on
this list.

### (b) Contact shadows

Every object that stands on the ground gets a shadow ellipse under its base:
**a flat, hard-edged, aliased ellipse, one colour, no gradient**, drawn on the
ground layer before the object. Not a soft blur — that is not this game's
language and it will not survive nearest filtering.

- Character: 14 x 5 px, centred on the feet, drawn immediately before the sprite.
- Props: width = 60–80% of the prop's footprint, height = 35% of that.
- Buildings: a hard 4px band along the south and east edges of the footprint,
  cast onto the ground tiles outside it.

Colour: not black. Multiply-toward-`bg` — implement as a single opaque colour
per ground material, or, cheaper and good enough, one shadow colour at 45%
alpha over everything.

**Hard constraints, from Slynyrd's top-down tile guidance and worth obeying
literally:** shadows *"must be conservative in design to limit conflict with
sprites and other tiles… it's best to limit them to **one or two wall faces**,
minding light source, and **they should not exceed a tile in length**."*

**Direction: pick centred, not offset.** The dynamic-looking choice is to cast
south-east from a north-west light, matching the hillshade convention
`make_world.py` already uses for the drawn map — and that is what the buildings
and cliffs should do, because they are fixed and their shadows can be authored
against their neighbours. But for *props and the character*, take Slynyrd's
game-design answer: *"It's most practical for game design to **center the shadow
directly under** the tree, so that it doesn't run into other assets, but I like
to cast it off to one side for a more dynamic look."* A scattered prop lands
anywhere, including one cell from a cliff or a wall, and an offset shadow will
sooner or later fall across something it should not. **Centred for anything the
generator places; offset south-east for anything authored in position.**

Engine cost: ~15 lines. `draw_texture_rect_region` of a shadow sprite, or
`draw_colored_polygon` for the character. This is the cheapest depth in the
document and it is why the character currently floats.

### (c) Cliffs — the elevation field, finally used

Write the elevation field into `overworld.json` as a second byte plane,
quantised to **6 terrace bands** over the land range:

```
"elev_b64_deflate": <48000 bytes, band 0..5, 255 for sea>
```

Quantisation modelled against the real field:

```
bands= 4:  703 south-facing cliff faces  (1.5% of cells)
bands= 6:  954                           (2.0%)   <- pick this
bands= 8: 1227                           (2.6%)
bands=12: 1832                           (3.8%)
```

At 6 bands: **~1.3 cliff faces per 57-cell screen.** Enough that most screens
have one; not so many that the mountain becomes a staircase.

A cliff reads as three things stacked, which is the standard top-down /
three-quarter convention and the only one that works at this scale:

1. **The top plate.** The higher terrace's own ground material, unchanged,
   with a 2px lit lip along its southern edge.
2. **The face.** A drawn *vertical* surface occupying the full 32px of the cell
   *below* the drop — striated rock, lit from the north-west so the west third
   is lighter and the east third darker. This is where the value range gets
   spent: the face must go genuinely dark, below anything on the ground plane.
3. **The cast shadow.** A 4–6px band on the ground below the face, in the same
   shadow colour as everything else.

**A wall is a cliff with a one-band drop, and it should use the same machinery.**
`wall_plaster` and `wall_stone` get a top plate, a 1-tile-tall face drawn on the
cell below, and a base shadow — the same 16-case set with a different face
material. That is what turns the grey stripe in the waking room into a wall, and
it costs nothing beyond the cliff set you are already building.

The cliff set has its own small logic — **16 tiles**:
face, face-left-end, face-right-end, inner-corner-left, inner-corner-right, top
lip, top lip corners, and a two-band-drop variant. Walkability is unchanged
(cliff faces are drawn on cells that are already `scree`/`rock` and already
solid, or become solid).

Engine cost: one extra byte plane in `HJWorld` (~40 lines), one extra draw pass
after the ground and before the props (~30 lines).

**This is the item that most directly answers "there's no sense of depth", and
the data for it already exists and is currently discarded.**

### (d) Y-sorting and tall props

Yes, we need it, and it is cheap because `TileWorld` draws immediately rather
than through the scene tree.

Godot 4's `y_sort_enabled` is a `CanvasItem` **property** — the Godot 3 `YSort`
node was removed and folded into `Node2D` by
[PR #42282](https://github.com/godotengine/godot/pull/42282) — and it sorts
*child CanvasItems*, not draw commands issued inside one `_draw`. So it does
nothing for us. Three further facts make writing it ourselves clearly right
rather than merely necessary:

- Y-sorting only relates nodes on the **same `z_index`**, and traversal stops at
  the first `Node2D` without y-sorting enabled.
- **Separate `TileMapLayer`s do not sort against each other.** A cliff-top layer
  and a props layer would stack by layer order regardless of Y.
- A y-sorted `TileMapLayer` **loses quadrant batching** (`rendering_quadrant_size`
  does not apply), which is the performance argument for the node-based route.

Worth knowing that the cheapest alternative is also legitimate: **Stardew Valley
does not Y-sort at all.** Its map layers are fixed and named — `Back`,
`Buildings`, `Paths`, `Front`, `AlwaysFront` — where `Front` holds *"objects that
are drawn on top of things behind them, like most trees… drawn on top of the
player if the player is North of them but behind the player if the player is
south of them."* If the sort ever becomes a problem, that is the fallback. It
will not; we have ~15 objects on screen.

Do it manually:

```
1. draw the ground layers for the visible window          (as today, +overlays)
2. collect visible props into an array of {anchor_y, sprite, cell}
3. append the character as one entry with anchor_y = its feet row
4. sort by anchor_y (stable; tie-break on x)
5. draw the array in order, each with its shadow immediately before it
```

Sorting ~15 entries per frame is nothing. **~35 lines of GDScript in
`_draw_character`'s place.** This is the whole cost of "the character walks
behind a tree", and without it no prop can be taller than one tile.

Once you have it, props are allowed to be taller than their footprint. Spec:

- A prop's art may be **1, 2 or 3 tiles tall** and 1 or 2 tiles wide.
- The **anchor** is the bottom-centre of the art, and it is placed at the bottom
  edge of its **base cell** — the same rule the character already follows
  ("align the bottom of the 32px cell with the bottom of the tile").
- Art extends *upward and outward* from the base cell freely; it never affects
  collision.
- **Collision is the base cell only** (or a declared 1x1 / 2x1 footprint),
  never the art bounds. A tree is solid where its trunk is; you walk behind its
  crown.

## 2.3 Props and buildings as objects

### What a prop is

```
prop := { id, base_cell: Vector2i, sprite: Rect2i, anchor: bottom-centre,
          footprint: Vector2i (1x1 default), solid: bool }
```

Stored as a **third byte plane** in `overworld.json`:

```
"props_b64_deflate": <48000 bytes, 0 = nothing, 1..N = prop id>
```

48,000 mostly-zero bytes deflates to a couple of KB. It keeps the existing
design property that the drawn map and the walked map come from one source and
cannot disagree, and it needs no new hash function shared between Python and
GDScript.

Multi-cell props occupy their base cell in the plane; the renderer reads the
prop's declared size from a table.

### Density

To kill the "50% of screens are one texture" number you want **6–12 props per
57-cell screen**, i.e. a density of **0.12–0.20 per walkable cell**, roughly
**4,500–7,500 prop instances** over the 37,115 land cells. Per-biome tables, e.g.:

| biome | props | density |
|---|---|---|
| grass_short | tuft, flower cluster, small stone, stump, log, single tree | 0.14 |
| grass_tall | tall clump, thistle, fencepost, gate | 0.18 |
| forest | (canopy is the fill) trunk gaps, fallen log, mushroom ring | 0.10 |
| sand | driftwood, shell, weed, tidal pool | 0.10 |
| scree | boulder, cairn, scrub, dead tree | 0.16 |
| snow | drift, ice shard, cairn, marker pole | 0.08 |
| path_dirt | milestone, wheel rut stone, signpost, wayside shrine | 0.06 |
| water | (offshore) rock, reed bed at the shore edge | 0.05 |
| floor_boards | **bed, chair, table, chest, rug, lamp, window** | placed, not scattered |
| floor_stone | barrel, crate, well, cart, market stall, lamp post | placed, not scattered |

Interiors are not scattered — they are furnished by hand in `stamp_house()` and
`stamp_town()`. **The waking room needs a bed before it needs anything else in
this document.** Six or seven furniture sprites and twenty lines in
`stamp_house()` fix the first screen of the game.

**Landmarks are props too.** The 0.5% of props that are unique — a standing
stone, a broken cart, a shrine, a well — are what make a place *somewhere* rather
than *grass*. Place a handful deliberately per region rather than by density.

Sprite budget: ~30 props gets you all of the above with 3–4 per biome. Each is a
small `blob()`-family function; `make_tiles.py` already has the primitive.

### Buildings

Stop stamping `roof` rectangles. A building is a **prop with a footprint**:

- **Footprint** — the solid cells, WxH, on the ground plane. The ground under it
  is *paving*, not roof.
- **Facade** — the south wall, drawn at 1.5–2 tiles tall above the footprint's
  south row, with a door, a window, and a lit window pane if it is night. This
  is the single change that makes a town read as a town: **a building you see
  the front of.**
- **Roof** — above the facade, overhanging the footprint by ~4px on the east and
  west, with a visible eave line and a ridge.
- **Shadow** — cast south-east onto the paving, 6px.
- **Y-sorted** with its anchor at the base of the facade, so the character walks
  *in front of* the near wall and *behind* buildings north of him.

`stamp_town()` becomes: choose building sizes, place them along street lines,
pave the streets, emit props. Three or four building variants (cottage, shop,
two-storey, barn) x a couple of roof colours is enough for the town we have
(265 `roof` cells today, i.e. ~12 buildings).

**Also fix `floor_stone`.** Redraw it as irregular polygonal paving with broken
joints, no continuous mortar line, and a slight per-slab value variation. As
drawn it is a brick wall, and it is what the summit and the whole town are
standing on.

## 2.4 The character

**Rework. Not a fix.**

**First, a size finding I did not have when I wrote §1.6.** The convention in
top-down pixel RPGs is that a character is **one tile wide by about two tiles
tall**, with the head a third to a half of the figure. Shipped data points:

| game / source | tile | character | ratio |
|---|---|---|---|
| Slynyrd, Pixelblog 22 (the rule of thumb) | — | — | **1 x 2 tiles** |
| Slynyrd, Pixelblog 55 (2025, worked example) | 16 | 26 x 32 | 1.6 x 2.0 |
| LPC style guide | 32 | 32 x 48 base (64 x 64 frame) | 1.0 x 1.5 |
| RPG Maker MV/MZ | 48 | 48 x 48 | 1.0 x 1.0 |
| Kenney Micro Roguelike | 8 | 8 x 8 | 1.0 x 1.0 |
| **The Heroes' Journey, today** | **32** | **24 x 32** | **0.75 x 1.0** |

**He is at the very bottom of the range — three-quarters of a tile wide and
exactly one tile tall, against a convention of one-by-one-and-a-half to
one-point-six-by-two.** That is not a stylistic choice that happens to read as a
bollard; it is *why* it reads as a bollard. There is no room for legs in 30 rows
once the hood takes 10, and there never was.

Specifics:

| | now | spec |
|---|---|---|
| Frame | 24 x 32 (0.75 x 1.0 tiles) | **28 x 48** (0.9 x 1.5 tiles) — LPC's ratio, the closest convention to our 32px tile |
| Figure height | 30 rows | ~46 rows, **redistributed**: head 12, torso 17, legs 17 |
| Head | 10 rows (33%) | 12 of 46 (~26%) — still stylised, no longer bobble-headed |
| Legs | 4 rows (13%) | **17 rows (37%)** — the single biggest silhouette fix |
| Arms | inside the silhouette | **outside it** — the arm must break the body outline, at least on the profile and step frames |
| Colours | 10, one grey ramp | **14–16, three ramps**: cloak (cool), skin/face (warm), and one saturated accent garment |
| Mean luma | 54 (= the grass) | **68–75** for the lit side, with the shaded side going to 25–30 |
| Facings | up/down identical | **must differ at a glance** — see below |
| Shadow | none | 16 x 6 ellipse, centred, always |
| Frames | 3 (`1,0,2,0`) | **keep 3, consider 4.** See below. |

**The frame count is fine and the pattern is not homemade.** `1,0,2,0` with
neutral in the middle column is exactly RPG Maker MV/MZ's character convention
(3 columns x 4 rows, middle column at rest). Slynyrd's 2025 guidance is that
*"the perfect balance of economy and smoothness can be captured in **6 frames**"*
for a small sprite, so there is headroom if the walk ever feels stiff — but at
0.17 s per tile and a 3-frame cycle, it does not. **Do not spend the rework on
frames; spend it on proportion and colour.**

**Going to 48 rows tall has one engine consequence**, and it is the same one the
props create: his head now overlaps the tile above him, so he must be drawn in
the Y-sorted object pass (§2.2d) rather than unconditionally last. Build Stage 1
before Stage 4 and this is free.

**Making up and down distinguishable** is the one hard constraint and it is
solved with colour, not shape: the *front* shows a face (two eyes' worth of dark
under a lit brow, plus a warm skin note), the *back* shows the hood's cowl seam
and the satchel. At 24px wide, three warm pixels of face is enough. Right now
there is nothing warm anywhere, so the two views collapse.

**Contrast rule.** The character's *lit* value must sit at least 20 luma points
above the brightest walkable ground he can stand on. That ground is currently
`snow` at mean 80 (max 118). So his hood/shoulder highlight needs to reach
**~130–150**, and §2.6 gives the room to do that without the tiles following him
up. His shadow side goes *below* the ground, so he is bracketed on both sides of
the ground value rather than sitting inside it. That, plus the black outline
(keep it), is what makes a figure sit on a plane instead of being pasted onto it.

**Where to draw him.** Not in Python span tables. `make_sprites.py` is 428 lines
of `(y, x0, x1, key)` tuples, and the comments record the iterations honestly —
"it read as a postbox" — which is what happens when you cannot see the figure
while you are drawing it. A 28x48 x 12-frame character is an afternoon in
Aseprite or Libresprite and a week in span tables. **Draw him in an
editor, export the sheet, and keep a tiny Python step that verifies the
contract** (cell grid, feet row, centring, binary alpha, palette membership)
rather than generating the pixels. The determinism argument that justifies
authoring tiles in PIL does not apply to a single hand-made 12-frame sheet.

Note the pipeline skill's constraint still holds and is not in tension with
this: the image model cannot hold identity across frames, so this is a *human*
drawing job, not a generation job. That is the correct conclusion, and it is
different from "therefore write it in Python".

**Palette derivation.** Keep it — but derive the *sheet's palette* from the theme
at build time and index the drawn PNG through it, rather than computing every
pixel. A 16-colour indexed PNG plus a theme-driven palette map preserves the
theme-swap property at zero cost to the drawing.

## 2.5 Build or adopt

**Recommendation: build the tiles. Redraw the character. Do not adopt a
third-party tileset.**

Not out of sentiment. The reasoning:

**Adopting does not fix the actual defect list.** Look at what is wrong: no
props, no transitions, no elevation faces, no shadows, no Y-sorting, no value
range, unreadable walkability, buildings with no facade. Of those eight, exactly
*one* — transitions — is something a downloaded tileset hands you. The other
seven are renderer and generator work you would still have to do, on top of the
integration cost. You would spend a week integrating Kenney or LPC and still have
50% of screens showing one texture, still have no shadows, still have a
floating character, and still have no depth. **The tiles are not why there is no
depth. The absence of everything else is.**

**The palette is load-bearing and adopted art fights it.** `firstlight.json` is
not decoration — it is the app's whole design system, it drives the UI, the
glyphs, the frames, the icons and the eight backdrops, it is themeable, and a
second theme is an unlock the game sells. Every mature free tileset is authored
in its own palette at its own value range: Kenney's top-down packs are bright,
high-key and flat; LPC is daylight fantasy. Recolouring 300 tiles into a dark
`#12131C`-based palette *by hand* is not "little time" — it is most of the work
of drawing them, done worse, and it produces art that no longer matches its own
internal lighting. And it silently kills the theme-swap property that the whole
`assets/` pipeline is built around.

**The generator is bespoke and needs a bespoke set.** This world is two noise
fields, eight materials on a linear priority order, an elevation ramp, and a
road that follows terrain. An asset pack is drawn for a hand-authored map. The
mapping between "what the pack contains" and "what this generator emits" is
itself a job.

**And the decisive point: in PIL, the expensive part of a tileset is cheap.**
The reason mature tilesets run to hundreds of tiles of drudgery is that a human
draws 32 transition cases per material by hand. We compose them from 32 shared
masks and seven short lip functions (§2.1). The PIL pipeline is *badly* suited
to a character (§2.4) and *unusually well* suited to overlay sets, terraces and
scatter — the exact three things missing. **We have been using it for the one
thing it is bad at and not for the three things it is good at.**

### The surveyed alternatives, with licences verified

I had the free/CC0 landscape checked properly rather than from memory. The
result strengthens the recommendation rather than complicating it.

| pack | licence (verified) | tile | verdict for us |
|---|---|---|---|
| **Kenney** (Roguelike/RPG, Tiny Town, 1-Bit, Micro Roguelike…) | **CC0**, site-wide, no attribution required | 16x16 (17px stride in the 2015 packs; unspaced `_packed` twins in newer ones), 8x8 for Micro | Cleanest licence there is, and **the wrong scale** — 16px against our 32px tile. High-key, flat, cartoon lighting. Almost no terrain transition coverage |
| **LPC Terrains** (bluecarrot16) | ⚠️ **CC-BY-SA 4.0 / 3.0 only** — no GPL, no permissive alternative | **32x32** — our exact tile size | The only free set that actually solves our problem: 2,048 tiles built as *precedence overlays*, plus a 15,562-tile pre-baked variant, covering grass/dirt/rock/stone/cobble/mud/water/snow/ice/lava/sand/beach/bog. **And it is the one we cannot take.** See below |
| **Ninja Adventure** (Pixel-Boy & AAA) | **CC0** (itch metadata field set) | 16x16 | Wrong scale. Genuinely good, ships Godot 3 and 4 demos |
| **DawnLike** | **CC-BY 4.0** — attribution, *no* ShareAlike | 16x16, no spacing | Wrong scale, roguelike vocabulary rather than overworld |
| **Tiny Swords** (Pixel Frog) | ⚠️ **No longer CC0.** "may not redistribute, resell, or repackage… even if modified" (a legacy `CC0 Licensed` build is still downloadable) | 64x64 | Wrong scale, wrong genre |
| **Sprout Lands**, **Cute Fantasy RPG** | ⚠️ **free tiers are NON-COMMERCIAL ONLY**; commercial needs the $3–4 tier | 16x16 | Easy to trip over. Wrong scale |
| **Modern Interiors / LimeZu** | Paid; commercial OK, **attribution mandatory**; free version's terms not stated on the page | 16 / 32 / 48 | Interiors only |

**The one that would have worked is the one we cannot use.** LPC Terrains is
32x32, precedence-overlay-structured, and covers every material we have. It is
**CC-BY-SA-only**. That means (a) every recolour, edit and re-atlas we make is
derivative art we must publish under CC-BY-SA, and (b) there is a documented
live conflict with app-store DRM: OpenGameArt's own FAQ states that *"Apple's
App Store in particular has been found to have usage terms that conflict with
the terms of the GNU GPL, the GNU LGPL, CC-BY-SA, and CC-BY."* The whole reason
to adopt was "a large jump in quality for little time"; recolouring 2,048
ShareAlike tiles into `firstlight` and then publishing the results is neither
little time nor a small legal footprint on a Play Store build.

Note also what the survey says about scale: **every CC0 top-down set is 16x16 or
8x8.** Adopting one means either halving our tile size — which reduces the
57-cell viewport to 57 cells of half the detail, or doubles the cell count and
shrinks everything — or upscaling pixel art, which is not a thing you do. That
alone rules out the clean-licence options.

### What to take from elsewhere anyway

- **Study, don't copy.** LPC Terrains' overlay structure and Slynyrd's cliff
  construction (Pixelblog 43: build the *face* first as a four-way-loopable
  texture, then derive the 45° corner from it, then derive the top plate and
  base row from the corner) are worth an hour each before writing `edge_sand()`
  and the cliff set. Those are methods, not pixels.
- **The character is the one place adoption is genuinely viable.** The
  **Universal LPC Spritesheet Character Generator**
  (`LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator`) is 64x64
  frames over a 32x48 base — the exact ratio §2.4 asks for — with 4 directions
  and a 9-column walk row. Its **art is licensed per asset**, and filtering the
  generator to **CC0 + OGA-BY** entries (~9,100 of ~13,900) gives you a figure
  with **no ShareAlike obligation and no DRM conflict** — OGA-BY explicitly
  permits encryption in DRM-protected games. Attribution is still required for
  the OGA-BY parts. **That is a legitimate fallback if the redraw stalls**, and
  it is a much better one than I implied before I had the numbers. The
  generator *code* is GPLv3; that governs the tool, not its output.
- **Do not** take the `jamesplease/dual-grid-tilemap-system-godot-gdscript`
  repo, which has **no licence file** — all rights reserved by default.

### The recommendation, restated

**Build the tiles in PIL. Redraw the character by hand, with the LPC generator
as a licensed fallback. Adopt no tileset.**

## 2.6 Palette: the narrow range is half the problem, and the fix does not break it

**The constraint is right about the wrong thing.**

"Each tile keeps its own value range narrow — roughly 25 luma points" is a
correct rule about **texture inside one material**. A busy tile does ruin the
interface and the sprite, and the flagstone and grass are correctly quiet.

What went wrong is that the same number was applied **between** materials and
**across the scene**. The result is that all seventeen tile *means* land between
38 and 80, and one whole frame occupies 34–81. There is no scene-level range
left, and depth in 2D *is* scene-level range.

Compare `assets/backdrops/areas/the_town.png`: 32 colours, median luma 24, p99
95, max 232. It is *darker* than our tileset on average and it looks like a
place, because the darks are genuinely dark and a handful of things are
genuinely bright.

**The fix, and it does not touch the "quiet" rule:**

1. **Keep each material's internal range at 20–30 points.** Unchanged.
2. **Drop the ground plane's median.** Move every ground material's *mean* down
   by 12–20 luma points — grass to ~40, forest to ~34, path to ~44, scree to
   ~30. The scene becomes mostly dark, as the backdrops are, and this alone
   makes everything on top of it read.
3. **Spend the recovered headroom on three things only**: the character's lit
   side (130–150), lit windows and the door (the door already sits at 107 max
   and is correctly a landmark — leave it), and the top lip of cliffs and the
   north-west face of props.
4. **Send the shadows genuinely dark.** Cliff faces to luma 18–26 — below
   *everything* on the ground plane. That is where the depth comes from, and it
   costs the interface nothing because shadows are small.
5. **Separate materials by hue and saturation, not value.** `path_dirt` and
   `roof` differ by 0.7 luma today; push the road warm and desaturated and the
   roof warm and saturated. `grass_short` and `grass_tall` need a real
   difference — make tall grass a full 8 points darker and a step more
   saturated, not a texture variation.
6. **Solid must be darker than walkable.** Non-negotiable, and it is a rule, not
   a preference: `forest`, `rock` and `wall`s go a clear **12+ luma points**
   below the walkable ground they border. Right now `forest` is 5.1 points from
   `grass_short` and it is a wall. If a rule ever conflicts with this one, this
   one wins.

Net effect on the UI: the panels sit on `panel`/`panel_alt` which are already
above the new ground means, so contrast against the UI *improves*. The sprite's
legibility improves for the same reason.

---

# Part 3 — The staged plan

Hours are one person, including the iteration the existing tool comments show
this kind of work actually takes. They are honest, not optimistic.

### Stage 0 — free wins, half a day (3–5 h)

Do these before anything else; they cost almost nothing and change how every
later judgement is made.

1. **Re-grade the palette** per §2.6: ground means down 12–20, solids 12+ below
   their neighbours, hue separation for the four colliding pairs. Edits inside
   the existing `mix()` calls in `make_tiles.py`. *(2 h)*
2. **Character contact shadow.** ~15 lines in `TileWorld._draw_character`. He
   stops floating. *(0.5 h)*
3. **Redraw `floor_stone`** as irregular paving with broken joints, so the town
   and the summit stop reading as brick walls. *(1 h)*
4. **Integer device scale.** Either add a `stretch/scale_mode = "integer"` /
   snap the camera and zoom to whole device pixels, or accept 4.5x knowingly.
   Test on a 1080-wide device. *(0.5–1 h)*

**Visible gain: large, disproportionate to the cost.** After Stage 0 the world is
darker, the character sits on the ground, and walls look like walls.

### Stage 1 — props. The biggest single win. (12–17 h)

The 50%-empty-screen number is the worst thing in this document and this stage
is what fixes it.

1. `props_b64_deflate` byte plane in `make_world.py` + per-biome density tables
   + deliberate landmark placement + **furnish the waking room and the house by
   hand**. *(3–4 h)*
2. ~30 outdoor prop sprites + ~10 furniture sprites in `make_tiles.py`, 1–3
   tiles tall, `blob()`-family. *(6–9 h)*
3. `HJWorld` reads the plane; `TileWorld` gets the **Y-sorted object pass** with
   per-prop shadows (§2.2d). ~50 lines GDScript. *(2–3 h)*
4. Prop footprint collision, base cell only. *(1 h)*

**After Stage 1 the mean distinct-things-per-screen goes from 1.70 to ~8–13.**
That is the difference between wallpaper and a place. If only one stage ever
happens, make it this one.

### Stage 2 — transitions (14–20 h)

1. `masks()` generator: 16 edge + 16 corner alpha shapes, plus a
   `overlay(fill_fn, lip_fn, mask)` compositor. *(4–5 h)*
2. Seven `lip_*()` functions — sand/foam first, it is 15.7% of all boundaries.
   *(6–10 h)*
3. `HJWorld` builds the overlay list at load (~4,300 entries, 17 KB). *(2 h)*
4. `TileWorld` draws fill + up to two overlay passes per cell, lowest
   precedence first. *(2–3 h)*

Sequence the seven by the coverage table in §2.1. Do **`sand` first** anyway
even though `forest` is marginally bigger — 21.8% of the world is sea, the shore
is the most-looked-at edge in the game, and a beach with foam is the most
convincing single thing you can put on screen. Then `forest`, then
`grass_short`: **those three are 53.6% of all natural boundaries.** Ship them,
look at it on the phone, and judge before writing the other four.

### Stage 3 — elevation and cliffs (8–12 h)

1. `elev_b64_deflate` byte plane, 6 terrace bands, in `make_world.py`. *(2 h)*
2. 16-tile cliff set: face, ends, corners, top lip, cast shadow. *(4–6 h)*
3. `HJWorld` reads it; `TileWorld` draws the cliff pass between ground and
   props. *(2–3 h)*
4. Optional and cheap once the plane exists: a subtle per-cell hillshade tint on
   the ground layer, exactly as `draw_map()` already does. *(1 h)*

### Stage 4 — the character (9–14 h)

Deliberately last. Everything above changes what he has to read against, and
redrawing him first means redrawing him twice.

1. Redraw 28x48 x 12 frames in Aseprite/Libresprite per §2.4. *(5–8 h)*
2. Replace `make_sprites.py`'s generation with a **contract verifier** — cell
   grid, feet row, centring, binary alpha, palette membership — and a theme
   palette re-index. *(2–3 h)*
3. `TileWorld` frame constants, and move the character into the Y-sorted
   object pass — at 48 rows he overlaps the tile above. *(1–2 h)*
4. Update `docs/OVERWORLD-ART.md`. *(1 h)*

### Stage 5 — buildings as objects (10–16 h)

The town is 265 cells of the 48,000-cell world. Real, but it is one screen. Do
it after the other four unless the town is about to carry a chapter.

1. `stamp_town()` emits building props with footprints and paved streets. *(3 h)*
2. 3–4 building variants: footprint, facade with door and lit window, roof with
   eave and ridge, cast shadow. ~24 sprites. *(6–10 h)*
3. Footprint collision + Y-sort (already built in Stage 1). *(1 h)*

---

## Totals and what to do if there is less time than that

```
Stage 0  free wins            3–5 h    disproportionate
Stage 1  props               12–17 h   the biggest single win
Stage 2  transitions         14–20 h
Stage 3  cliffs               8–12 h   the direct answer to "no depth"
Stage 4  character            9–14 h
Stage 5  buildings           10–16 h
                             ----------
                             56–84 h
```

**If you can only do ten hours: Stage 0 and half of Stage 1.** Darker ground, a
shadow under the character, a bed in the waking room, and twelve prop sprites
scattered by a density table will change the owner's verdict more than a
purchased tileset would.

**If you can only do one thing: props.** Half of all screens in this game
currently contain one texture and nothing else, and no tileset, however mature,
fixes that.

## What this document deliberately does not do

- It does not change the tile ids in `ORDER`. Every addition below is an
  *append* or a new byte plane; nothing renumbers a saved world.
- It does not abandon seamlessness. Base fills keep the wrapping `px()` and the
  numeric seam test. Edge and prop sprites are not tiled against themselves and
  do not need it.
- It does not abandon palette derivation. Every colour above is still a mix of
  `firstlight.json` entries; the character sheet becomes indexed through a
  theme-derived palette rather than computed pixel by pixel.
- It does not ask the image model for anything that has to line up on a grid.
  The pipeline skill's finding stands.

---

# Appendix — sources, and corrections to my own first draft

## Corrections made after research

Recorded rather than hidden, because each one was a plausible-sounding claim
that turned out to be wrong:

1. **I first specced a dual grid and it is the wrong choice here** (§2.1). It is
   not equivalent to the 47-tile blob set — it is marching squares on the dual
   cell, with less shape variety and no curve wider than half a tile — and its
   half-tile displacement is disqualifying in a game where materials carry
   walkability.
2. **The blob reduction is 47 of 256, not 255.**
3. **The overlay decomposition is 16 edge + 16 corner = 32 tiles covering all
   256 cases**, which is both cheaper and better-attested than anything I had.
4. **The character is undersized against convention** (0.75 x 1.0 tiles vs
   1.0 x 1.5 to 1.6 x 2.0) — a diagnosis I did not have in §1.6 and which
   explains the bollard silhouette better than proportion alone.
5. **Tiny Swords is no longer CC0**; **Sprout Lands and Cute Fantasy free tiers
   are non-commercial**; **LPC is per-asset licensed**, not uniformly
   CC-BY-SA/GPL, and OGA-BY is its largest bucket — which makes the LPC
   character generator a *usable* fallback and LPC Terrains an unusable one.

## Primary sources

**Autotiling and transitions**
- cr31 (Christopher Hendry), the origin of the 47-tile blob set —
  https://www.cr31.co.uk/stagecast/wang/blob.html
- BorisTheBrave, *Tileset Roundup* and *Classification of Tilesets* —
  https://www.boristhebrave.com/2013/07/14/tileset-roundup/ ·
  https://www.boristhebrave.com/2021/11/14/classification-of-tilesets/
- BorisTheBrave, *Quarter-Tile Autotiling* (the "dual grid cannot create curves
  larger than half a tile width" finding) —
  https://www.boristhebrave.com/2023/05/31/quarter-tile-autotiling/
- **David Michael, *Tile/Map-Based Game Techniques: Handling Terrain
  Transitions*, GameDev.net, 2000** — the precedence + 16-edge/16-corner method
  this spec adopts —
  https://www.gamedev.net/articles/programming/general-and-gameplay-programming/tilemap-based-game-techniques-handling-terrai-r934/
- Factorio FFF #214 (shared greyscale alpha masks) and #199 (the design problem)
  — https://www.factorio.com/blog/post/fff-214 · https://factorio.com/blog/post/fff-199
- Battle for Wesnoth, `TerrainGraphicsWML` numeric layer precedence —
  https://wiki.wesnoth.org/TerrainGraphicsWML
- Tiled manual, terrain set definitions and counts —
  https://doc.mapeditor.org/en/stable/manual/terrain/
- Oskar Stålberg's original dual-grid posts, including his own "gameplay happens
  on the main grid" caveat — https://x.com/OskSta/status/1448248658865049605 ·
  https://x.com/OskSta/status/1448265809269338117
- jess::codes, *Draw fewer tiles — by using a Dual-Grid system!* —
  https://www.youtube.com/watch?v=jEWFSv3ivTg

**Godot**
- `CanvasItem.y_sort_enabled` docs; `TileMapLayer.y_sort_origin`,
  `x_draw_order_reversed`, `rendering_quadrant_size`
- PR #42282, removal of the `YSort` node —
  https://github.com/godotengine/godot/pull/42282
- Terrain-system defects: [#70218], [#73903], [#76493], [#64769], [#87929],
  [#89844], [#97299], [#80635]; proposals
  [#5575](https://github.com/godotengine/godot-proposals/issues/5575) and
  [#7670](https://github.com/godotengine/godot-proposals/issues/7670)
- Portponky/better-terrain (The Unlicense) —
  https://github.com/Portponky/better-terrain

**Art direction**
- Slynyrd Pixelblog 43 (top-down cliffs and walls, drop-shadow constraints) —
  https://www.slynyrd.com/blog/2023/3/26/pixelblog-43-top-down-tiles-part-2
- Slynyrd Pixelblog 21 (top-down objects, grounding shadows) and 44 (the
  centred-vs-offset shadow trade) —
  https://www.slynyrd.com/blog/2019/9/18/pixelblog-21-top-down-objects ·
  https://www.slynyrd.com/blog/2023/5/22/pixelblog-44-top-down-trees
- Slynyrd Pixelblog 22 and 55 (character sizing, frame counts) —
  https://www.slynyrd.com/blog/2019/10/21/pixelblog-22-top-down-character-sprites ·
  https://www.slynyrd.com/blog/2025/3/24/pixelblog-55-top-down-character-animation
- Slynyrd Pixelblog 3 (3/4 projection; "uniformity takes priority over realism") —
  https://www.slynyrd.com/blog/2018/3/14/pixelblog-3-graphical-projections-1
- Stardew Valley map layers (`Back`/`Buildings`/`Paths`/`Front`/`AlwaysFront`) —
  https://stardewvalleywiki.com/Modding:Maps
- LPC style guide — https://lpc.opengameart.org/static/LPC-Style-Guide/build/styleguide.html

**Licences**
- Kenney, site-wide CC0 — https://kenney.nl/support
- OpenGameArt FAQ (commercial use; the App Store / CC-BY-SA DRM conflict; "you
  must follow only one of the licenses") — https://opengameart.org/content/faq
- LPC Terrains (CC-BY-SA only) — https://opengameart.org/content/lpc-terrains
- Universal LPC Spritesheet Character Generator —
  https://github.com/LiberatedPixelCup/Universal-LPC-Spritesheet-Character-Generator

**A source-hygiene note worth keeping.** `redblobgames.com/articles/autotile/claude/`
and `/gemini/` rank highly on autotiling searches and are **AI-generated pages
that Amit Patel hosts as hallucination examples** — his parent page says *"If
ChatGPT told you to come to this page that I wrote… it made it up!"* Several
other high-ranking autotiling "guides" are in the same category. None were used
here; everything above traces to primary sources.
