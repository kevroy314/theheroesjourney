# Overworld art

Tiles and the player sprite for the top-down mode. Both are authored with PIL,
not generated — the image model cannot hold an identity across frames (see
`.claude/skills/game-art-pipeline`), so anything that has to line up on a grid
is drawn in code.

Both tools read the palette from `data/themes/firstlight.json` (`colors`, the
reality register). No hex value is hardcoded in either tool; every colour in
both sets is a mix of two theme colours, so a theme swap moves the art with it.

```
python3 tools/make_tiles.py       # -> assets/tiles/
python3 tools/make_sprites.py     # -> assets/sprites/
```

Both are deterministic — every RNG is seeded, and re-running produces
byte-identical PNGs. Both print a verification table; read it, don't assume it.

Everything is aliased, binary-alpha pixel art. Render with
`TEXTURE_FILTER_NEAREST` at integer zoom or it turns to mush.

## Tiles

Everything in `assets/tiles/` comes out of `tools/make_tiles.py` in one run.
**1,722 sprites from about twenty generators** — the point of a programmatic
pipeline is that transition sets and scatter are cheap, and this is where it
wins. `docs/ART-DIRECTION-OVERWORLD.md` is the measured brief this answers; read
it before changing any of the numbers below.

| set | count | file | what it is |
|---|---:|---|---|
| base materials | 25 | `tileset.png` | one seamless 32x32 fill per material |
| fill variants | 75 | `tileset_var.png` | 3 alternates each, chosen by `hash(x,y)` |
| **overlays** | **1536** | `overlays.png` | 16 materials x (16 edge + 16 corner) x 3 seeds |
| cliffs | 16 | `cliffs.png` | terrace lip, face, cast shadow |
| props | 70 | `props.png` | things that stand on the ground |

`assets/tiles/tiles.json` is the machine-readable manifest for all five sets —
order, walkability, precedence, atlas layouts, the prop table with densities and
collision footprints. **Prefer it to parsing Python.** `tools/make_world.py`
still reads `ORDER` out of `make_tiles.py` and that still works; both describe
the same list.

### Base materials

**32 x 32**, opaque, one PNG per material, and all of them in one horizontal
strip in `tileset.png`. **Sheet index is the id stored in the world grid.**
Index *i* starts at x = 32*i. Appending is safe; reordering silently rewrites
every map ever generated.

| id | tile | walkable | mean luma | id | tile | walkable | mean luma |
|---:|---|---|---:|---:|---|---|---:|
| 0 | `floor_boards` | yes | 42 | 13 | `snow` | yes | 72 |
| 1 | `floor_stone` | yes | 46 | 14 | `bridge` | yes | 44 |
| 2 | `grass_short` | yes | 42 | 15 | `forest` | **no** | 21 |
| 3 | `grass_tall` | yes | 34 | 16 | `roof` | **no** | 28 |
| 4 | `path_dirt` | yes | 46 | 17 | `ocean` | **no** | 15 |
| 5 | `door` | yes | 52 | 18 | `dune` | yes | 68 |
| 6 | `wall_plaster` | **no** | 26 | 19 | `hardpan` | yes | 50 |
| 7 | `wall_stone` | **no** | 22 | 20 | `jungle` | **no** | 18 |
| 8 | `water` | **no** | 26 | 21 | `undergrowth` | yes | 36 |
| 9 | `rock` | **no** | 28 | 22 | `mud` | yes | 39 |
| 10 | `void` | **no** | 8 | 23 | `cliff` | **no** | 29 |
| 11 | `sand` | yes | 62 | 24 | `ice` | yes | 66 |
| 12 | `scree` | yes | 44 | | | | |

Ids 0–16 are unchanged from the first tileset. **17–24 are appended**, for the
concentric-biome world: ocean and desert and jungle and mountain, on top of the
grass/forest/scree/snow that already existed. Nothing was renumbered.

`WALKABLE` in `tools/make_tiles.py` is derived from the same `MATERIALS` table
the art is drawn from, so the art and this table cannot drift apart. Note that
`scripts/ui/World.gd` carries its own `SOLID` list of ids and it does **not**
yet know about 17, 20 or 23; those three are solid and have to be added there.

**Value structure.** Each material declares a hue and a target mean luma;
`at_luma()` grades it, and `normalise()` shifts the finished fill until the
declared mean is literally true. So the column above is measured, not intended.
Two rules govern it, and the tool checks and prints both:

- Each material's own internal range stays **20–30 luma points**. A busy tile
  ruins the interface and the sprite. Unchanged from the first tileset.
- **A SOLID material sits at least 12 luma below every walkable material it
  borders.** This is a rule, not a preference — `forest` and `grass_short` used
  to differ by 5.1 and one of them is a wall. They now differ by 21.0. The tool
  prints the margin for every pair that actually meets and fails loudly.

The scene is not quiet even though each tile is. Ground medians sit low (p50 37
across the set) and the recovered headroom above 90 is spent on three things
only: **surf, prop crowns and cliff lips** — plus the character, when he is
redrawn. Nothing else may spend it.

Every base fill tiles seamlessly against itself on all four edges, by
construction: every drawing operation goes through a `px()` that wraps modulo
32. The tool proves it on a 4x4 repeat and prints the numbers; a joint is only
accepted when its step sits inside the distribution of the tile's own internal
steps.

`tileset_var.png` is **3 alternate fills per material**, laid out with variant
*v* of material *i* at (32*i, 32*v). Pick one with a hash of the cell
coordinates; `v == 0` means use `tileset.png`. Ignoring the file entirely is
valid and changes nothing but the repeat.

### Transitions: the precedence overlay

Materials do not meet on a 32-pixel staircase any more. Each has a **rank**, and
a cell draws its own fill and then lets every higher-ranked neighbouring
material spill into it.

```
 0 ocean   3 mud    6 hardpan   9 grass_short  12 forest  15 cliff
 1 water   4 sand   7 snow     10 grass_tall   13 jungle  16 path_dirt
 2 ice     5 dune   8 scree    11 undergrowth  14 rock
```

Rank 0 never needs an edge set, so the atlas holds the sixteen materials of
ranks 1–16. Everything outside this list — the floors, the walls, the door, the
roof, the bridge, the void — is architectural: it neither overlays nor is
overlaid, and it is handled by the cliff/wall set instead.

**The algorithm, per cell.** This is the whole consumer contract:

```
draw the cell's own fill
for each DISTINCT higher-ranked material among the 8 neighbours, lowest first:
    side   = bits for {N,E,S,W} where that cardinal neighbour holds it
    corner = bits for {NE,SE,SW,NW} where that diagonal holds it
             AND NEITHER of the two adjacent sides does
    if side:   draw overlays[mat][edge][side][v]
    if corner: draw overlays[mat][corner][corner][v]
```

with `v = hash(x, y, mat) % 3`. Because the overlays compose in one fixed total
order, three- and four-way junctions resolve for free with no per-triple art.
On the shipped map 91% of cells need no overlay at all and the mean is 1.18
draws per cell. `overlay_plan()` in `make_tiles.py` is the reference
implementation; the preview compositions are rendered with it, so what you see
in `_comp_*.png` is what the rule produces.

**Atlas layout.** `overlays.png` is **16 columns x 96 rows** of 32px tiles,
512 x 3072.

```
row = slot*6 + variant*2 + kind        slot = rank - 1
col = mask                             kind = 0 edge, 1 corner
```

Mask 0 is blank in both kinds, so column 0 is empty by design and the index
arithmetic needs no special case. Side bits are N=1, E=2, S=4, W=8; corner bits
are NE=1, SE=2, SW=4, NW=8.

**Why the silhouettes are not straight lines.** Every intrusion depth is a
seeded 1-D midpoint displacement — fractal, so big lobes carry smaller lobes
carry single-pixel roughness — **pinned to the same depth at both ends of its
run**. The pinning is what makes it legal: two adjacent cells may hold different
variants and the boundary still joins, because every variant leaves and arrives
at the same depth. Between the pins a tongue may push 18 pixels into the
neighbouring cell or pull back to 2. Mean intrusion is 6–10px depending on
material.

Three further devices do the rest, and they matter more than the profile:

- **Scatter** — detached pixels of the material ahead of its own front, thinning
  with distance. This is the single biggest silhouette-breaker at 3x: it turns
  an outline into a gradient of belonging.
- **Bites** — pixels removed just behind the front, so the front is not a clean
  fill boundary either.
- **Corner rounding** — where two sides of an overlay meet, a lobe is added over
  the re-entrant right angle the union would otherwise leave. Inner corners are
  where a Wang set announces itself; there is no mitred corner in the set.

Each material then finishes differently, and the finish is what makes a
boundary mean something: sand and water get a **bright broken surf line with
spray and a wet band behind it** (the shoreline is the most-looked-at edge in
the game); grass and undergrowth get blades that break the outline on every
side; forest, jungle, rock and cliff get a dark rim and a **hard cast shadow
thrown south and east** onto whatever is beneath; scree gets a ragged chip line
with no continuous edge at all; snow a lit drift lip; the road a swept verge
with gravel. One light source, north-west, everywhere.

The texture inside an overlay is the *same* 32x32 fill the full tile uses, at
the same phase, so grass spilling into sand is continuous with the grass next
door rather than restarting at the cell boundary.

**Alpha.** Two values in the whole set: 255, and 118 for the shadow bands.
Hard edges only, no blur, so nearest filtering stays lossless.

### Cliffs

16 pieces in `cliffs.png`, laid out 4 x 4; index = row*4 + col in the order
`lip_mid, lip_left, lip_right, lip_solo, face_a, face_b, face_c, face_mid,
face_left, face_right, corner_left, corner_right, shadow_mid, shadow_left,
shadow_right, shadow_solo`.

A drop reads as three cells stacked, which is the only construction that works
at this scale:

```
cell above the drop     the upper terrace's own ground + lip_*      (2-5px lit rock)
cell below the drop     face_*                                      (a full 32px vertical face)
cell below that         shadow_*                                    (4-9 rows at alpha 118)
```

The face's grooves run **vertically**. That is the whole trick: horizontal
courses read as a wall you are standing *on* — which is why the summit used to
look like brickwork — and vertical grooves read as a wall you are standing
*under*. It is lit from the north-west, darkens downward, and its base goes to
luma 10, below anything on the ground plane. That is where the value range is
spent.

**A wall is a cliff with a one-band drop and should use this same machinery.**
`wall_plaster` and `wall_stone` get a lip, a face on the cell below and a base
shadow; that is what turns the grey stripe in the waking room into a wall.

`_comp_cliffs.png` shows two terraces drawn this way. The elevation field this
needs already exists in `make_world.py` and is currently discarded.

### Props

**70 objects.** The measured fault this fixes is that half of all screens in the
game show one texture repeated fifty-seven times and the room the player wakes
in has no bed.

`props.png` is **8 columns of 64 x 96 slots**. Slot *i* is at
`(64*(i%8), 96*(i//8))`; the byte-plane value for prop *i* is **i + 1**, and 0
means nothing is there. `tiles.json` carries the full table: id, index, biome,
density, `solid`, `foot`.

**Anchoring — the contract.** Every prop's anchor is the **bottom-centre of its
slot, (32, 96)**, and the anchor is placed at the bottom-centre of the prop's
**base cell**. To draw prop *p* standing in cell (cx, cy):

```
dst_x = cx*32 + 16 - 32          dst_y = cy*32 + 32 - 96
```

Art extends upward and outward from the base cell freely and **never affects
collision. Collision is the `foot` cells anchored at the base cell** — 1x1
unless the table says 2x1 or 2x2. A tree is solid where its trunk is; you walk
behind its crown. Y-sort on the base cell's bottom edge, and draw props in that
order together with the character.

The contact shadow is **baked into the sprite**, centred under the base, in the
one shadow colour at the one alpha the rest of the set uses — so the consumer
needs no separate shadow pass. Centred, not offset: a scattered prop lands
anywhere, including a cell from a cliff, and an offset shadow will sooner or
later fall across something it should not. Anything authored in position —
buildings, cliffs — offsets south-east instead.

Every prop that stands up also carries a hard near-black rim derived from its
own silhouette. That is what lets one sprite sit on grass and on snow without
being redrawn for each.

`biome` is the material a prop scatters on and `density` is instances per
walkable cell of that biome; `biome: "placed"` means **do not scatter it** —
interiors are furnished by hand and landmarks are put somewhere on purpose.
Current densities, which the tool prints:

| biome | props | density | per 57-cell screen |
|---|---:|---:|---:|
| grass_short | 9 | 0.191 | 10.9 |
| undergrowth | 6 | 0.159 | 9.1 |
| dune | 5 | 0.143 | 8.2 |
| grass_tall | 5 | 0.126 | 7.2 |
| forest | 5 | 0.120 | 6.8 |
| sand | 5 | 0.116 | 6.6 |
| scree | 5 | 0.115 | 6.6 |
| hardpan / snow | 4 / 3 | 0.068 | 3.9 |
| mud | 1 | 0.055 | 3.1 |
| path_dirt | 4 | 0.038 | 2.2 |
| water | 1 | 0.022 | 1.3 |
| ice | 1 | 0.014 | 0.8 |
| **placed** | **16** | — | by hand |

The sixteen placed props are the town and the interiors: `barrel`, `crate`,
`well`, `cart`, `market_stall`, `lamppost`, `bench`, `standing_stone`, and
`bed`, `table`, `chair`, `bookshelf`, `chest`, `floor_lamp`, `plant_pot`,
`rug`. **The waking room needs the bed before it needs anything else.**

### Debug previews

Underscore-prefixed files in `assets/tiles/` are debug assets, not game assets.

- `_sheet_x4.png` — every base fill at 4x, repeated 2x2 so the seam is visible,
  labelled with walkability and measured mean luma.
- `_overlays_x3.png` — all 32 cases of all 16 overlay materials over a
  contrasting ground.
- `_props_x2.png` — every prop on its own biome, numbered by plane value.
- `_comp_*.png` — **seven 12x12-tile compositions at 3x, rendered by the same
  overlay rule the game must implement**: `shore`, `forest_edge`, `scree_slope`,
  `desert`, `jungle`, `crossroads`, `cliffs`. These exist because the first
  tileset's whole failure was that it was designed at 32x32 and never looked at
  at 57 cells on screen. Look at them before and after any change.

## Player sprite

**24 wide x 32 tall** per frame, transparent background, in `assets/sprites/`.

`player.png` is the sheet to slice. **72 x 128 = 3 columns x 4 rows of 24 x 32.**
Zero margin, zero spacing, no per-cell offset. Cell (col *c*, row *r*) is the
rect `(c*24, r*32, 24, 32)`.

|  | col 0 | col 1 | col 2 |
|---|---|---|---|
| **row 0** | down neutral | down step_left | down step_right |
| **row 1** | up neutral | up step_left | up step_right |
| **row 2** | left neutral | left step_left | left step_right |
| **row 3** | right neutral | right step_left | right step_right |

**Column 0 is the neutral pose, not the first step.** A character standing still
shows column 0, so idle needs no special case. The walk cycle is therefore

```
1, 0, 2, 0        step_left, neutral, step_right, neutral
```

Playing `0, 1, 2` instead gives a limp — there is no neutral between the two
steps.

`right` is a horizontal mirror of `left`. The figure is symmetric apart from the
shoulder the satchel strap crosses, and at this size that is invisible.

Per-facing strips are also written: `walk_down.png`, `walk_up.png`,
`walk_left.png`, `walk_right.png`, each **72 x 32**, three columns in the same
order. `_player_x4.png` is a 4x preview with the cell grid ruled over it — debug
only.

### Geometry the loader can rely on

- The figure is horizontally centred in its cell in every facing: bounding box
  centre is x = 11.5 for all four. Turning does not move the character.
- The feet are at a fixed row in every frame: the sole is row 30, its outline
  row 31. Nothing bobs vertically when the character stops walking — the step
  frames compress the upper body by one pixel instead. Align the bottom of the
  32px cell with the bottom of the tile the character is standing on.
- Vertical extent is rows 1..31 inclusive; row 0 is empty.
- Nine opaque colours plus fully transparent. Alpha is binary — 0 or 255, no
  soft edge anywhere — so nearest filtering is lossless.

## Notes

- Each material keeps a narrow internal value range — 19-33 luma points, 2 for
  the void and 91 for the door, which is a landmark and is meant to be found.
  Materials carry their difference in **hue**, not brightness; the exception is
  the solid-vs-walkable rule, where brightness is the whole point and 12 luma is
  the floor. `grass_short` and `scree` are two luma apart and read as different
  ground because one is green and one is blue-grey.
- The character has a hard near-black outline derived from his own alpha mask,
  and every standing prop now has the same. That outline is what keeps a sprite
  legible over any tile; do not tint it away. **The claim that his cloak is the
  lightest thing on the ground plane was false when it was written and is more
  false now** — he means 54, `sand` is 62, `dune` 68 and `snow` 72. §2.4 of
  `docs/ART-DIRECTION-OVERWORLD.md` has the redraw spec; his lit side needs to
  reach 130-150.
- `export_presets.cfg` excludes `art/*` but not `assets/*`, so all of this ships
  in the pck as soon as it exists. The whole set is ~1.8 MB, of which
  `overlays.png` is 350 KB and the debug previews are 750 KB — strip the
  `_`-prefixed files from the export if that matters.
- **Determinism is checked, not assumed.** Every RNG is seeded through
  `rng_for()`, which hashes with md5 rather than Python's per-process-salted
  `hash()`. The tool prints one md5 over every file it wrote, in name order;
  two consecutive runs produce the same digest and byte-identical files.

## The world

There is one map, not eight. `tools/make_world.py` builds a single 150x320-tile
landscape and writes two things from the same source:

```
data/world/overworld.json      the grid the game walks on
assets/world/worldmap.png      the drawn map, rendered from that same grid
```

**The drawn map is a rendering of the tile grid, not a separate picture of it.**
A hand-painted map beside a hand-built tilemap is two descriptions of one place
that will disagree within a week, and the player is who finds out. Flat biome
colour plus a hillshade taken from the elevation field's own gradient — the way
a paper relief map is made — because the 32px tile detail is only noise at 4px.

Everything derives from two noise fields, elevation and moisture. Biomes are
thresholds on those fields, which is what buys "no zone boundaries" for free: a
shore is wherever elevation crosses sea level, not a line somebody drew.

Chapters are **regions**, not zones. Each has an anchor cell and a `CHARACTER`
entry — a soft radial nudge to the two fields, so the Tall Grass is wetter than
its surroundings and the Long Road drier. The change happens over thirty tiles
and nobody can point at where it starts. Nothing stops you walking to the summit
on day one; you will simply find the door shut.

`tiles_b64_deflate` is base64 of **plain `zlib.compress`**. Godot's
`FileAccess.COMPRESSION_DEFLATE` is zlib-wrapped despite the name — verified by
round-tripping every pairing. Raw deflate (`wbits=-15`) decompresses to zero
bytes and does not error. If you change the encoding, re-test it.

Tile ids are indices into `ORDER` in `tools/make_tiles.py`, which
`make_world.py` reads rather than copies. **Appending a tile is safe; reordering
silently rewrites every world ever generated.** Ids 17-24 were appended for the
biome rings; nothing was renumbered. `assets/tiles/tiles.json` carries the same
list plus the overlay, cliff and prop tables, and is the better thing to read.

The overlay, elevation and prop layers need no change to `overworld.json`'s
existing plane: overlays are derived at load from the tile plane it already has.
Cliffs want an `elev_b64_deflate` plane and props a `props_b64_deflate` plane —
both additive, both described in §2.2c and §2.3 of the art direction.
