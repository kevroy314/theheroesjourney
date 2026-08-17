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

**32 x 32**, opaque, one PNG per tile in `assets/tiles/`.

| Tile | File | Walkable |
|---|---|---|
| Interior floorboards (the Waking Room) | `floor_boards.png` | yes |
| Flagstone | `floor_stone.png` | yes |
| Short grass | `grass_short.png` | yes |
| Tall grass (chapter 4) | `grass_tall.png` | yes |
| Trodden road | `path_dirt.png` | yes |
| Door | `door.png` | yes |
| Plaster wall | `wall_plaster.png` | **no** |
| Stone wall | `wall_stone.png` | **no** |
| Water | `water.png` | **no** |
| Rock | `rock.png` | **no** |
| Off-map filler | `void.png` | **no** |

`WALKABLE` in `tools/make_tiles.py` is the same list and the contact sheet
labels each cell from it, so the art and this table cannot drift apart.

`assets/tiles/tileset.png` is all eleven in one horizontal strip, **352 x 32**,
no margin and no spacing. Index *i* starts at x = 32*i:

| 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 |
|---|---|---|---|---|---|---|---|---|---|----|
| floor_boards | floor_stone | grass_short | grass_tall | path_dirt | door | wall_plaster | wall_stone | water | rock | void |

`assets/tiles/_sheet_x4.png` is a 4x labelled preview — each cell shows the tile
repeated 2x2 so the seam is visible. It is a debug asset, not a game asset.

Every tile tiles seamlessly against itself on all four edges. The tool proves it
on a 4x4 repeat and prints the numbers; a joint is only accepted when its step
sits inside the distribution of the tile's own internal steps.

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

- The tiles keep a narrow internal value range: 20-40 luma points for every
  material, 3 for the void, and 56 for the door — which is a landmark and is
  meant to be found. They carry their
  difference in hue. The character's cloak is deliberately the lightest thing on
  the ground plane so he never dissolves into the tall grass.
- The character has a hard near-black outline derived from his own alpha mask.
  That outline is what keeps him legible over any tile; do not tint it away.
- `export_presets.cfg` excludes `art/*` but not `assets/*`, so these ship in the
  pck as soon as they exist. The whole set is ~53 KB including the two debug
  previews.
