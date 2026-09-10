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

## The commands

```sh
npm run world:edit      # open world/overworld.tmj in Tiled
npm run world:export    # data/world/overworld.json  ->  world/overworld.tmj
npm run world:import    # world/overworld.tmj        ->  data/world/overworld.json
npm run world:check     # what an import would change, writing nothing
npm run check           # validate data/, including the world file
npm run world:shot      # a PNG of any rectangle of it — see "Looking at it"
```

Import is the one the game cares about — nothing you draw reaches the game until
you run it. `world:check` is `world:import -- --check` under a shorter name.

`npm run check` is a different thing and catches a different class of mistake:
it is `tools/validate_data.py`, it reads `data/world/overworld.json` and never
the `.tmj`, and it is what tells you an interactable is typed as something that
is in no catalogue. **The import will happily write a nonsense `type`**; only
this notices. Run it after any session in Tiled.

Tiled itself is not installed by the project. `npm run world:edit` finds it on
`PATH`, in `~/Applications/Tiled-*.AppImage`, or in Flatpak, and prints the three
ways to install it if there is none. Currently installed here:
`~/Applications/Tiled-1.12.2_Linux_x86_64.AppImage`.

## Looking at it

The playfield on a phone is about seven and a half tiles across, so an emulator
screenshot of the town is a screenshot of one doorway. `tools/worldshot.sh`
draws any rectangle of the overworld into one PNG:

```sh
./tools/worldshot.sh X Y W H OUT.png [HOUR] [--no-light]

./tools/worldshot.sh 95 95 76 81 .scratch/town-day.png 0.45     # the whole town
./tools/worldshot.sh 95 95 76 81 .scratch/town-night.png 0.9    # the same at night
./tools/worldshot.sh 132 126 20 14 .scratch/square.png 0.5 --no-light
```

`npm run world:shot -- 95 95 76 81 .scratch/town.png 0.45` is the same thing.

It is **the game's own renderer**, not a second one. `scripts/WorldShot.gd` boots
the engine, instantiates the real `HJTileWorld` into an off-screen SubViewport
and photographs it, so autotiling precedence, the overlay bleed, cliff faces,
Y-sorted props, the townsfolk and the lighting overlay are all exactly what the
phone would draw. If the shot is wrong, the game is wrong — which is the only
useful property a preview can have. Nothing about the tileset is reimplemented in
Python, and nothing has to be kept in step.

* `HOUR` is 0..1: 0 midnight, 0.25 dawn, 0.5 noon, 0.75 dusk. Default 0.5, the
  one hour at which the ambient ramp writes nothing at all.
* `--no-light` skips the overlay entirely — the raw art with no shader over it.
* One pixel per tile-pixel, so 32 px per cell: 76x81 cells is a 2432x2592 PNG.
* The player is parked on open ground in the middle of the rectangle, as a
  figure of known height to judge scale against. He is never indoors, because
  the renderer drops an interior floor over the *whole* frame when he is.

Two things to know before believing a shot:

* **A wide night shot under-lights its edges.** The shader carries
  `HJLighting.MAX_LIGHTS` (12) emitters a frame and the renderer keeps the ones
  nearest the middle of the view, which is generous for a seven-tile window and
  is not generous for a town with seventeen lamps in it. The tool prints both
  numbers every run. Shoot a quarter of the town at a time to see all of them.
* **It needs a GL context, so it is not `--headless`.** `--headless` gives Godot
  the dummy renderer: everything runs, nothing is drawn, and the viewport hands
  back null. The wrapper starts a throwaway `Xvfb`, uses it and kills it.

It never touches the save. Six of the nine stores are pointed at
`user://*_worldshot.*` scratch copies through the same `use_path()` override the
self-test uses, and the other three are covered by `Main._ready` skipping
`Game.boot()` altogether for a shot — the run is never loaded and nothing calls
`save_game()`.

## What is in the map

Layers come out in this order, and every name except `base`, `edits` and
`markers` is **a top-level key of the world file**, not a hardcoded string.

| # | Layer | Type | Yours? | What it is |
| --- | --- | --- | --- | --- |
| 1 | `base` | tile | **no** — locked | The generated terrain. Overwritten in full by the next export. |
| 2 | `edits` | tile | **yes** | Your overrides. A tile here wins over `base`; an empty cell means "leave the generated tile alone". |
| 3 | `regions` | object | yes | Region anchors, as point objects named by region id. Some carry a `rect` as well — see below. |
| 4 | `anomalies` | object | yes | Where the holes in reality are, with their tier and the area each opens. |
| 5 | `interactables` | object | yes | The door, the stove, the counter, the animals — points naming a catalogue entry. |
| 6 | `props` | object | **yes** | Every tree, barrel and bed in the world, as tile objects you can drag, retype, delete and add. **5,918** of them. |
| 6b | `clutter` | object | **yes** | The second prop plane: what lies on a cell, or on the prop standing there — grit in a lane, a rug, a cup on a counter. **2,435** of them, and never solid. Its own tileset (`clutter.tsj`), so the panel you pick from is the panel of things that do not collide. |
| 7 | `cliffs` | object | **yes** | Every cell of every terrace edge, as tile objects. Presence is all you say; the left/middle/right pieces are worked out for you. |
| 8 | `indoors` | object | yes | One point per building the player can walk into, carrying the footprint as `w`/`h` and the name the run header shows as `place`. |
| 9 | `markers` | object | yes | Every key the world file carries as a single `{x, y, …}`: `centre` and `spawn`. |
| — | *others* | object | yes | One layer per collection the world model grows. Add a whole new object layer and it becomes a new top-level key. |

`base` is locked in the editor because a lock is the honest representation of
what it is: paint there and the next export deletes it without asking. To change
generated terrain, paint the same cell in `edits` instead — that is what the
layer is for. You can still eyedrop from `base` (`I` in Tiled) to match a tile.

### `interactables`, and how a door is edited

An interactable placement is `{ x, y, type, label? }`, where `type` names an
entry in `data/content/interactables.json` — the catalogue that says what a
*kind* of thing is: its verb, its price, what it does. So the world says
**where**, and the catalogue says **what**, and dragging the stove somewhere
else or retyping it as a counter is a map edit with no code in it. Retyping
`dog` to `cat` genuinely produces a cat, with the cat's behaviour, because the
catalogue entry names the critter.

Edit the `type` **property** in the sidebar. Editing Tiled's own **Class** field
does nothing: the import never reads it, and the next export overwrites it with
the layer name. And a mistyped `type` is not caught here — the import writes it
happily and the affordance silently never appears in game. `npm run check` is
what catches it.

### `indoors` is a list of rectangles wearing points

`indoors` is a **list** of `{ x, y, w, h, place? }` — one per building the player
can walk into, walls and door cell included. It is what the Boon of the White
Room is scoped to, what `HJWorld.is_indoors` answers, and what suppresses the
sun and the sky wash in `Lighting.gd`. `place` is the name the run header shows;
an entry with no `place` means "Home", which is why the player's own house
carries none and the other thirteen do.

It used to be a single `{x, y, w, h}` and therefore a **marker**, because the
exporter classifies by shape and its only question is "is this a dict with a
numeric `x` and `y`". As a list of the same records it is a collection instead,
so it gets a layer of its own — but each object is still a **point** at the
rectangle's top-left, with the extent as two integer properties.

**So you still cannot resize one by dragging.** Converting a point to a
rectangle and pulling a corner changes Tiled's own width and height, which the
import does not read. Edit the `w` and `h` properties instead. And because
`indoors` is a list, it is reconciled on the exporter's numbering — see the note
on list collections below before you reorder or delete one.

Neither `indoors` nor `interactables` is in the schema's `world.required` list,
so deleting one loses it with no validator complaint — unlike `spawn` or
`centre`, which are caught.

**Objects are objects, not tiles.** A region anchor is a point you drag, not a
special tile id, so it can sit on any terrain and cannot be painted over by
accident. Its extra fields — biome, difficulty, whatever the schema grows — are
editable in Tiled's property sidebar. You can add objects the generator has
never heard of; they come through the import as new entries in the same
collection.

Three things about object *names*, because they are load-bearing in a way that
does not look it:

* A collection stored as a **dict** — `regions`, `markers` — is keyed by the
  object's name. Rename a region and you have made a different region and
  deleted the old one.
* A collection stored as a **list** — `anomalies`, `interactables` — has no
  names of its own, so the exporter numbers them `"0"`, `"1"`, `"2"`. The import
  throws those away, but the *export* reconciles on them, so reordering or
  deleting one shifts every object after it against the generator's records.
* **Two objects with the same name, or two without one, silently collapse to
  one** on the next export. If you duplicate an object, rename it.

**Leave anything starting `hj_` alone.** Those are the round trip's bookkeeping:

| property | on | is |
|---|---|---|
| `hj_schema` | the map | a complete description of the world file's shape and key order. Delete it and the import refuses to run |
| `hj_gen_planes` | the map | the props, clutter and cliffs the generator last produced |
| `hj_gen_x` / `hj_gen_y` | every object | where the generator last put it — the pin test |
| `hj_keys` | records with more than `x`/`y` | the record's original key order, which is half of why the round trip is byte-identical |
| `hj_json` | rarely | which fields were structured and had to be JSON-encoded into a string property |
| `hj_marker` | marker objects | written, and read by nothing. The importer routes markers by layer name |

An `hj_`-prefixed name can therefore never be a field of the world schema, since
the import skips every one of them.

## Props and cliffs

These used to be invisible. The world file carries them as byte planes —
`props_b64_deflate`, `clutter_b64_deflate`, `cliffs_b64_deflate`, one byte per
cell — and a byte is the one thing Tiled cannot show you, so 8,353 props shipped
as an opaque blob and you could not move a single barrel.

They are object layers now. **The plane is still what the game loads**; the
objects are the editing format, folded back into the plane on import. That split
is deliberate:

* `scripts/ui/TileWorld.gd` indexes the prop plane per cell inside `_draw`, every
  frame. A plane answers that in O(1) with no work at load time.
* 8,353 objects is about 480 KB of JSON. Parsing that at every launch, on a
  phone, to build a lookup one byte already answers, buys nothing.
* One byte per cell is the *runtime's* constraint — there is nowhere to draw two
  props on one cell. Making objects the source of truth would let you express a
  world the game cannot render. The import says which two objects are stacked and
  on which cell, and keeps the topmost.

### Two planes, and which one a thing goes on

There are **two** prop planes and they are numbered independently, so props id
5 and clutter id 5 are different things that may be on the same cell.

| | `props` | `clutter` |
| --- | --- | --- |
| what it holds | what **occupies** the cell — it stands up in the 96px slot | what does **not** — it lies on the floor, or sits on the thing standing there |
| may be solid | yes | **never** |
| examples | tree, barrel, counter, lamppost, window | grit, a wheel rut, a rug, the damp at a wall's foot, a cup, an open book |
| tileset | `props.tsj` | `clutter.tsj` |
| catalogue | `props.list` in `tiles.json` | `clutter.list` in the same file |

That is why one cup collides and another does not: it does not. **Nothing on the
clutter plane ever blocks**, and not as a rule anybody has to keep — the
collision plane is derived from `props` and `cliffs` and the deriver is never
handed `clutter` at all, so a clutter object you place on a doorway is a
decoration in a doorway and never an invisible wall.

Order within one cell is decided by the entry's own `flat`: flat clutter is
drawn **under** the prop (grit round the foot of a bush), everything else
**over** it (the cup on the counter). You do not set that per object; it is a
property of the art.

The two planes are also two budgets. A plane byte is one byte, so each
catalogue stops at 255 entries — `python3 tools/add_prop.py verify` prints how
many ids are left on each.

### Picking a prop by name, not by number

The export writes `world/props.tsj`, `world/clutter.tsj` and `world/cliffs.tsj`
from `assets/tiles/props.png`, `assets/tiles/clutter.png`,
`assets/tiles/cliffs.png` and the catalogue in `assets/tiles/tiles.json`. So a prop in Tiled is a **tile object**: you pick it
out of the tileset panel by its picture, its object Name is the catalogue id
(`tree_pine`, `well`, `barrel`), and the tileset carries `name`, `biome`,
`solid`, `foot_w` and `foot_h` as tile properties you can read in the sidebar.
The art is drawn at 64x96 exactly where the game draws it — bottom-centred on
the cell it stands on — so what you arrange is what you get.

On import the **tile decides the type**, because the picture is what you were
looking at when you placed it; the name is the fallback, so a plain object named
`barrel` by hand still lands. An object that resolves to neither stops the import
by name and id rather than vanishing from the world.

Nothing here is pinned to the current catalogue. `tiles.json` is read at run
time, both tilesets are rebuilt on every export, and a prop appended by the asset
pipeline is pickable immediately. A plane id with no catalogue entry — art that
was deleted out from under the world — **fails loudly** on both halves of the
trip rather than silently dropping the prop.

### Deleting a generated prop, and having it stay deleted

This is the hard part. With a plane, "absent" means nothing: regenerate and the
tree comes back. It works here for the same reason an erased tile works, and by
the same mechanism — a base, and overrides on top of it:

| | terrain | props, clutter and cliffs |
| --- | --- | --- |
| the generated layer | the `base` tile layer | `hj_gen_planes` on the map |
| your layer | the `edits` tile layer | the difference between the objects and that |

The map remembers the plane the generator last produced. Every cell where your
object layer disagrees with it is an override, and overrides are re-applied on
top of the next generation. So:

* **delete** a prop and the cell is *empty where the generator filled it* — a
  positive statement, not an absence, and it survives regeneration;
* **drag** a prop and you get two overrides, empty where it was and a prop where
  it now is. Moving it is the act of pinning it, exactly as for a region anchor;
* **add** one and the cell is filled where the generator left it empty;
* **retype** one — swap its tile — and the cell holds your prop instead.

No tombstone objects and no flags to tick. The tombstone *is* the absence, made
meaningful by the map remembering what the generator last said. The export
reports all four counts:

```
  clutter 2435 objects — 2 placed by hand, 2 deleted, 0 retyped
  props   5918 objects — 3 placed by hand, 1 deleted, 0 retyped
```

Overrides are addressed by cell, so a resize moves them with the `edits` layer
and under the same `--anchor`.

### Cliffs are editable, but you never touch the pieces

A cliff cell's value is 1, 2 or 3 — left end, middle, right end — depending on
whether the drop continues either side. That is not something you can keep
consistent by hand: nudge the end of a bluff and you have left a `middle` piece
hanging in the air.

So the cliff objects say only *there is a terrace edge on this cell*, and the
ends are re-derived on import from the run each cell is in, the same way
`make_world.py` derives them. Extend a bluff by one cell and the old end quietly
becomes a middle. It is why an unedited round trip is still byte-identical: the
re-derivation reproduces the generator's plane cell for cell.

What cliffs still cannot do is change the ground under them. A cliff drawn on
flat land is a wall with no elevation to justify it, and the hillshading will not
agree with it. Draw them along terrain that already steps.

### Collision stays correct, because it is derived

A prop's art is 64x96 and its collision is the `foot` cells at its base — a
fallen log is two cells wide, a well is four. `blocked_b64_deflate` is therefore
never edited and never carried across verbatim: it is **derived** from the
finished props and cliffs planes, by one function that `make_world.py`,
`world_to_tiled.py` and `tiled_to_world.py` all call. Place a boulder by hand and
it blocks; delete one and it stops blocking.

Deriving it also fixed a bug it inherited. The generator used to accumulate
`blocked` while scattering, and then placed the town props and the bedroom
furniture *afterwards* — so the well, the benches, the lampposts and the whole
bed were solid in the catalogue and walk-through in the game. Thirty-one cells,
now blocked.

## What happens to your edits when the generator is re-run

They survive. That is the whole design, and it is the reason there is a separate
`edits` layer rather than one editable grid.

```sh
python3 tools/make_world.py     # new terrain, new regions, new everything
npm run world:export            # base layer replaced; edits layer untouched
npm run world:import            # base + edits composited back for the game
```

Four rules, and between them they cover everything:

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
4. **Objects you deleted**, and this is the one that is asymmetric. A deleted
   **prop or cliff** survives a regeneration, because the empty cell is itself
   an override in the plane. A deleted **region, anomaly, interactable or
   marker** does not: there is no tombstone, so the next export re-adds it at
   the generator's position. Deleting one of those is only durable once you have
   imported and then not re-run `make_world.py`.

There is no separate "reseed just this region" mode because it would not buy
anything: the generator may rewrite as much or as little of the terrain as it
likes, and the overrides sitting on top survive wherever they are.

**A nudge pins an anchor even when it changes nothing.** The pin test is exact
pixel equality against `hj_gen_x` / `hj_gen_y`, while the import floors a point
to its cell. So dragging a region anchor one pixel is a no-op in the world file
*and* stops that anchor following the generator forever, with nothing on screen
to say so. Props are the opposite — they round to the nearest cell on both
sides, so a small nudge really is not an edit.

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
layer, puts every generated object back at its `hj_gen` position, rebuilds the
props, clutter and cliffs layers from `hj_gen_planes`, drops everything
hand-added, imports that, and compares against the real file:

```
world/overworld.tmj  256x256, 33 tiles in the set
  base    re-seeded from data/world/overworld.json (locked)
  edits   0 cells kept
  objects 0 pinned by hand, 0 new from the generator, 0 kept ...
  cliffs  478 objects — 0 placed by hand, 0 deleted, 0 retyped
  clutter 2435 objects — 0 placed by hand, 0 deleted, 0 retyped
  props   5918 objects — 0 placed by hand, 0 deleted, 0 retyped
  round trip: byte-identical (68849 bytes reproduced exactly)
```

That includes `blocked_b64_deflate`, which is *recomputed* rather than copied —
so the check is proving the collision rule agrees with the generator's, not just
that a blob survived the trip.

If that line ever says `ROUND TRIP FAILED` it names the key that diverged, exits
non-zero, and tells you not to edit until it is fixed — because something in the
world schema is not surviving the trip, and the import would lose it. That is
the check working, not a nuisance.

The zlib compression level is *measured* on export (whichever level reproduces
the generator's exact blob) rather than assumed, which is what makes the base64
match rather than merely decompress to the same bytes.

**What the map can hold that the world file cannot.** Byte-identity is only
promised for what the schema describes, and Tiled offers a good deal more than
that. None of the following survives an import, so do not encode meaning in it:
object rotation, an object's own width and height, tile flip flags, the Class
field on a point object, the name of an object in a list collection, per-object
colour or visibility, two props stacked on one cell (the topmost wins, and the
import says which two), and anything painted into `base`.

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
| `world/props.tsj` | yes | The props tileset, regenerated from `props.png` and `tiles.json` on every export. |
| `world/clutter.tsj` | yes | The clutter tileset, same, from `clutter.png`. |
| `world/cliffs.tsj` | yes | The cliff pieces, same. |
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
line. That is deliberate — 65,536 CSV integers per layer is a 270 KB diff that
is no more readable — but it does mean `git diff` will not show you what you
painted. `npm run world:import -- --check` will.

The props, clutter and cliffs, being objects, are the opposite: 8,831 of them
make `overworld.tmj` about **2.2 MB**, and a moved barrel is four readable lines of
diff. That is the price of being able to see them, and it is paid in the map,
not in the game — `data/world/overworld.json` is 61 KB, and it grows with the
prop count and with nothing else.

### Living with 8,000 objects in Tiled

- Turn the `props` layer off (the eye in the Layers panel) while you are painting
  terrain. Tiled draws every object in a visible layer, and 5,918 sprites of
  64x96 is enough to make panning stutter on a big view.
- **Select the layer before you select an object.** With `props` active, a
  rubber-band selection across a screen of forest selects a few hundred objects
  and Tiled's property sidebar will think about it.
- Deleting a prop is `Delete`, and deleting a *hundred* is fine — the export
  records it as a hundred one-cell overrides, which is what makes clearing a
  glade for a building stick across regeneration.
- A small nudge to a *prop* is not an edit. Prop positions round to the nearest
  cell, so pushing a tree a few pixels while dragging the map leaves it exactly
  where it was. A nudged region anchor is a different story — see above.
- Object *ids* are assigned in row-major cell order, so an unchanged layer
  re-exports to the same ids and the diff stays small.

## Nothing here is pinned to the current schema

The tileset is derived from `assets/tiles/tileset.png` and `tools/make_tiles.py`
at run time: tile size from `N`, names and walkability from `ORDER` and
`WALKABLE`, tile count from the atlas's own dimensions. There is no copy of the
tile list in the map tooling and no hardcoded tile count. There are 29 today;
adding a thirtieth changes nothing here.

The world file is *classified*, not named. Each top-level key is sorted by shape
into: the width, the height, the compressed tile grid, a collection of
`{x, y, ...}` records (→ an object layer), **any** dict with a numeric `x` and
`y` (→ a marker), a one-byte-per-cell plane (→ an object layer, or derived), or
something opaque (→ carried verbatim in `hj_schema` and written straight back).

That rule is deliberately loose, and `indoors` is where the looseness shows: a
`{x, y, w, h}` rectangle satisfies the marker test, so an entry becomes a point
with two extra properties rather than a shape you can drag a corner of. Cheap
and correct, and worth knowing before you try to resize a building.

A **structured** value inside such a record is carried too, as JSON in a string
property with its key listed in `hj_json`, and decoded again on the way back in.
`regions` uses it: a region is `{ x, y }` and may also carry a `rect` of
`{ x, y, w, h }` saying how far the place reaches. `HJWorld.place_id()` prefers
the smallest rect containing the cell and falls back to the nearest anchor, so a
valley can be a place without a circle round its middle claiming the mountain
too. Two regions carry one today: `the_town` and `the_house`.

The planes are the one exception, and only half an exception. *Which* plane is
the props plane is a fact about the art, not about the value — every plane in the
file is the same 65,536 bytes — so `PLANE_KEYS` in `world_to_tiled.py` names them
by key prefix. That is four words of hardcoding. Everything behind it, including
the atlas geometry, the cell size and the catalogue of what each byte means, is
read out of `assets/tiles/tiles.json` at run time.
An elevation field, difficulty rings, anomaly spawn points and the
interactables list all passed through this without a code change: anomalies and
interactables land as object layers you can drag, `indoors` grew from a marker
into a layer of its own the day it stopped being one building, a region grew a
nested `rect` with no new shape, and elevation rides along untouched. That is the claim this design makes, and it
is the evidence for it.

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
- **A prop id with no catalogue entry.** Both halves stop and name the id and
  the cell. That is the honest answer when art is deleted out from under a world
  that is already drawing it — dropping the prop would be a silent hole.
- **Two props on one cell.** One byte per cell *per plane*, so a cell takes one
  prop and one piece of clutter and no more. Two objects on one cell of the same
  layer: the import names both and the cell, and keeps the topmost. A prop and a
  piece of clutter on one cell is not a collision — it is the point.
- **A `props`, `clutter` or `cliffs` layer you delete.** The import refuses rather than
  emptying the plane. Re-export if that is really what you meant.
- **A resize.** Prop and cliff overrides move with the `edits` layer under
  `--resize` / `--anchor`, and are dropped with a note if the shift cannot be
  worked out. They are cell-addressed, so the same caveat applies: your edits
  were *around* something, and that something has a new address.
- **Flipped tiles.** Tiled can flip and rotate a placed tile; the game's grid is
  one flat id per cell with nowhere to put the flags, so the import strips them.
  A flipped tile imports as its unflipped self rather than as garbage.
- **Wang/terrain sets** live in `world/tileset.tsj` and are preserved across
  regeneration by name. They are yours to author in Tiled once the autotile sets
  land — nothing generates them, and nothing overwrites them.
