# Editing the map

The world is seeded by a generator and finished by hand. Both, always — the
generator lays down terrain nobody wants to draw by hand, and you fix the parts
it got wrong. The editor is [Tiled](https://www.mapeditor.org/); the two halves
are joined by `tools/world_to_tiled.py` and `tools/tiled_to_world.py`.

```
tools/make_world.py  ──►  data/world/overworld.json  ──►  world/overworld.tmj
                                    ▲                            │
                                    └──────── you edit ──────────┘
```

## The three commands

```sh
npm run world:edit      # open world/overworld.tmj in Tiled
npm run world:export    # data/world/overworld.json  ->  world/overworld.tmj
npm run world:import    # world/overworld.tmj        ->  data/world/overworld.json
```

Import is the one the game cares about — nothing you draw reaches the game until
you run it. `npm run world:import -- --check` says what an import *would* change
without writing anything.

Tiled itself is not installed by the project. `npm run world:edit` finds it on
`PATH`, in `~/Applications/Tiled-*.AppImage`, or in Flatpak, and prints the three
ways to install it if there is none. Currently installed here:
`~/Applications/Tiled-1.12.2_Linux_x86_64.AppImage`.

## What is in the map

| Layer | Yours? | What it is |
| --- | --- | --- |
| `base` | **no** — locked | The generated terrain. Overwritten in full by the next export. |
| `edits` | **yes** | Your overrides. A tile here wins over `base`; an empty cell means "leave the generated tile alone". |
| `regions` | yes | Region anchors, as point objects named by region id. |
| `markers` | yes | Single points the world file carries on its own — `spawn` today. |
| *others* | yes | One object layer per collection the world model grows: anomalies, props, whatever comes next. |

`base` is locked in the editor because a lock is the honest representation of
what it is: paint there and the next export deletes it without asking. To change
generated terrain, paint the same cell in `edits` instead — that is what the
layer is for. You can still eyedrop from `base` (`I` in Tiled) to match a tile.

**Objects are objects, not tiles.** A region anchor is a point you drag, not a
special tile id, so it can sit on any terrain and cannot be painted over by
accident. Its extra fields — biome, difficulty, whatever the schema grows — are
editable in Tiled's property sidebar. You can add objects the generator has
never heard of; they come through the import as new entries in the same
collection.

**Leave anything starting `hj_` alone.** Those are the round trip's bookkeeping:
the map's `hj_schema` property is a complete description of the world file's
shape, and `hj_gen_x` / `hj_gen_y` on each object is where the generator last
put it. Delete `hj_schema` and the import refuses to run.

## What happens to your edits when the generator is re-run

They survive. That is the whole design, and it is the reason there is a separate
`edits` layer rather than one editable grid.

```sh
python3 tools/make_world.py     # new terrain, new regions, new everything
npm run world:export            # base layer replaced; edits layer untouched
npm run world:import            # base + edits composited back for the game
```

Three rules, and between them they cover everything:

1. **Tiles.** `base` is thrown away and re-seeded. `edits` is never written by
   the generator, so every override is re-applied on top of the new terrain at
   the same cell.
2. **Objects the generator produces.** If an object is still sitting where the
   generator last put it, it follows the generator to its new position. If you
   have *dragged* it, it stays where you dragged it and stops following. There
   is no flag to tick — moving it is the act of pinning it.
3. **Objects you added.** Never touched. Objects the generator has *stopped*
   producing are also kept, so a region the world model drops does not silently
   vanish from a map you have been working on.

There is no separate "reseed just this region" mode because it would not buy
anything: the generator may rewrite as much or as little of the terrain as it
likes, and the overrides sitting on top survive wherever they are.

### The one thing that can go wrong

Overrides are addressed by cell. If the world changes *shape* — and it will, the
tall map is becoming a square one — the cell an override sat on may no longer be
the place you meant. So a size change stops the export dead:

```
the world is now 200x200 but world/overworld.tmj is 150x320.
Re-run with --resize to move the 50 hand-edited cells onto the new grid
(add --anchor REGION to align them to a region anchor that has moved), or
--discard-edits to throw them away.
```

`--anchor the_town` translates every override by however far `the_town` moved,
which is usually exactly right: your edits were *around* something, and that
something has a new address. The export says how far it shifted things and how
many cells fell off the edge before it writes anything.

### Starting over on purpose

```sh
npm run world:export -- --discard-edits
```

It prints the count of hand-painted cells and hand-placed objects it is about to
destroy first. Run `python3 tools/make_world.py` before it if you want a
genuinely clean seed — after an import, `data/world/overworld.json` contains
your earlier edits as ordinary terrain, and re-seeding from it keeps them.

`npm run world:export -- --dry-run` reports the same numbers and writes nothing.

## Round-trip fidelity

Export then import with no edits reproduces `data/world/overworld.json` **byte
for byte** — same key order, same `indent=1`, same trailing newline, same base64
of the same zlib stream. Not "an equivalent file": the same bytes.

Every export checks it. It takes a scratch copy of the map, blanks the `edits`
layer, puts every generated object back at its `hj_gen` position, drops
everything hand-added, imports that, and compares against the real file:

```
world/overworld.tmj  150x320, 17 tiles in the set
  base    re-seeded from data/world/overworld.json (locked)
  edits   0 cells kept
  objects 0 pinned by hand, 9 new from the generator, 0 kept ...
  round trip: byte-identical (3778 bytes reproduced exactly)
```

If that line ever says `ROUND TRIP FAILED` it names the key that diverged, exits
non-zero, and tells you not to edit until it is fixed — because something in the
world schema is not surviving the trip, and the import would lose it. That is
the check working, not a nuisance.

The zlib compression level is *measured* on export (whichever level reproduces
the generator's exact blob) rather than assumed, which is what makes the base64
match rather than merely decompress to the same bytes.

## Exporting twice in a row is safe

The import writes the *composite* of `base` and `edits`, so a naive re-export
would read that composite straight back into `base` and duplicate every
override into the generated terrain — after which erasing an override would do
nothing, because the tile underneath had become the edit.

So the export first composes the map it already has and compares it to
`data/world/overworld.json`. If they match, the file is this map's own output,
the generator has not run since, and there is nothing to seed:

```
  nothing to seed: data/world/overworld.json is this map's own composite,
  so base, edits and objects are all untouched.
```

No stamp file, no state to get stale. It also means a pinned object stays pinned
across an import, which it would not if `hj_gen` were re-derived from a file
that already contains the hand position.

## What gets committed

| Path | Commit? | Why |
| --- | --- | --- |
| `world/overworld.tmj` | **yes** | The only copy of your hand-drawn edits. |
| `world/tileset.tsj` | **yes** | Regenerated from the atlas, but carries hand-authored Wang/terrain sets that nothing else has. |
| `world/heroes.tiled-project` | yes | Tiled's project settings. Written once, then yours. |
| `world/open-in-tiled.sh` | yes | The launcher. |
| `world/*.tiled-session` | no — gitignored | Scroll position and selected layer. Per-machine noise. |
| `world/*.autosave` | no — gitignored | Tiled's crash recovery. |

`data/world/overworld.json` stays committed and generated as it always was; the
import writes it, `make_world.py` writes it, and neither is authoritative on its
own. **`world/overworld.tmj` is the durable artefact.** It carries the whole
world file inside it — the tile grid, the objects, and every schema key this
tooling does not understand — so `overworld.json` can be deleted and rebuilt
from the map alone. The reverse is not true: delete the `.tmj` and the edits are
gone.

The tile layers are stored as base64 + zlib, so a map diff is one long opaque
line. That is deliberate — 48,000 CSV integers per layer is a 200 KB diff that
is no more readable — but it does mean `git diff` will not show you what you
painted. `npm run world:import -- --check` will.

## Nothing here is pinned to the current schema

The tileset is derived from `assets/tiles/tileset.png` and `tools/make_tiles.py`
at run time: tile size from `N`, names and walkability from `ORDER` and
`WALKABLE`, tile count from the atlas's own dimensions. There is no copy of the
tile list in the map tooling, and no hardcoded 17.

The world file is *classified*, not named. Each top-level key is sorted by shape
into: the width, the height, the compressed tile grid, a collection of
`{x, y, ...}` records (→ an object layer), a single `{x, y}` (→ a marker), or
something opaque (→ carried verbatim in `hj_schema` and written straight back).
An elevation field, difficulty rings and anomaly spawn points all pass through
this without a code change; anomalies land as a `anomalies` object layer you can
drag, and elevation rides along untouched.

### What will actually break, and when

- **More than 256 tiles.** The generator writes one byte per cell. The import
  measures the byte width and follows it — one, two or four, little-endian — but
  it cannot invent the wider encoding on its own. If a tile id ever exceeds 255
  while the generator is still writing bytes, the import refuses with a message
  saying so. `make_world.py` has to widen first; `HJWorld.load_world` has to
  read the same width. Nothing else changes.
- **The atlas layout.** Tile id *n* is the *n*th cell of `tileset.png`, read
  left-to-right then top-to-bottom, exactly as `make_tiles.py` writes it. A
  17-wide strip and a 20×20 grid both work. An atlas with margins or spacing
  does not — say so and it becomes two lines in `build_tileset`.
- **A stale atlas.** If `make_tiles.py` names more tiles than the atlas holds,
  the export says so and tells you to re-run it. Ignore that and the map will
  reference tiles that do not exist.
- **Flipped tiles.** Tiled can flip and rotate a placed tile; the game's grid is
  one flat id per cell with nowhere to put the flags, so the import strips them.
  A flipped tile imports as its unflipped self rather than as garbage.
- **Wang/terrain sets** live in `world/tileset.tsj` and are preserved across
  regeneration by name. They are yours to author in Tiled once the autotile sets
  land — nothing generates them, and nothing overwrites them.
