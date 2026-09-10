---
name: world-generator
description: Change tools/make_world.py or tools/make_tiles.py without silently breaking the world — the verification sequence in the order it has to run (npm run tiles, determinism by md5, decode the collision plane, flood-fill, byte-identical round trip, validate_data.py) and the traps each of which has already cost a cycle. Use when editing either generator, adding or moving a placement pass, declaring anything new on a prop, or when the world came out different and nobody asked it to. docs/MAP-EDITING.md is the other half — this is changing the generator, that is editing what it produced.
---

# Skill: world-generator

`docs/MAP-EDITING.md` covers editing the map **in Tiled**. This is the other
half: changing the code that produces it. Read that doc for the round trip's
rules — the `edits` layer, `hj_gen_planes`, `PLANE_KEYS`, the byte-identity
promise — because this skill assumes them rather than restating them.

The generator has been changed six times in two days and the same verification
sequence was rediscovered each time, sometimes late and once not at all.
Everything below is that sequence and what it caught.

## The pipeline, in the only order that works

```bash
npm run tiles                     # make_tiles.py && add_prop.py reapply
python3 tools/make_world.py       # reads the tiles.json that step wrote
npm run world:export              # data/world/overworld.json -> world/overworld.tmj
npm run check                     # tools/validate_data.py
```

`make_world.py` reads `assets/tiles/tiles.json` in `solid_ids()`,
`standing_planes()` and `catalogues()` — the last of which every placement pass
now goes through, so the atlas step is a hard prerequisite, not a habit. There is **no npm alias for `make_world.py` on
purpose** — it regenerates from scratch and overwrites anything imported from
Tiled.

Its two outputs are `data/world/overworld.json` and `assets/world/worldmap.png`.

## Run `npm run tiles`, never bare `make_tiles.py`

**Symptom:** an export or an import refuses with a message about an *object* —
a prop id at a cell that "is not in assets/tiles/tiles.json" — and says nothing
about a missing pipeline step.

**Cause:** `make_tiles.py` rebuilds the atlas and the catalogue from scratch.
Props appended by `tools/add_prop.py` live *past* the generated ones, so a bare
run leaves `tiles.json` short while `world/overworld.tmj` still references the
prop that fell off the end. The `npm run tiles` alias is
`make_tiles.py && add_prop.py reapply` and the reapply is the whole point of it.

`python3 tools/add_prop.py verify` is the direct check: it reports `MISSING` for
an authored prop the catalogue lost, `MOVED` for one whose index shifted (which
means every world file storing that plane byte now means something else), and
`PIXELS DIFFER` if the sprite no longer matches the registry.

## Determinism is a hard requirement

One `random.Random(20260901)`, created in `main()` and threaded through every
pass that needs it. Verify it, every time, by running twice and comparing:

```bash
python3 tools/make_world.py >/dev/null && md5sum data/world/overworld.json
python3 tools/make_world.py >/dev/null && md5sum data/world/overworld.json
```

The two digests must match. **A bare `random.random()` has broken this before:**
an earlier version seeded an RNG and then called the global one inside
`carve_road`, so two runs produced two different worlds while the docstring
promised reproducibility. Any new pass takes `rng` as a parameter. Any new
hashing uses `hashlib.md5`, not Python's `hash()`, which is salted per process.

`make_tiles.py` does this for you — its last line prints an md5 over every file
it wrote, in name order. `make_world.py` does not, so `md5sum` the output
yourself.

## One RNG stream, so an early change reshuffles everything after it

There is a single stream for the whole world. Changing **how many draws** any
earlier pass makes moves everything downstream, even where you touched nothing.
Fixing `stamp_town` changed the anomaly count from 30 to 29 and moved several of
them, purely because building placement consumed a different number of draws.

So: **expect the whole world to move**, and do not read a diff in the anomaly
list as evidence of a bug in the pass you were editing. Check the invariants
(reachability, seal, counts, the printed report) rather than the byte diff.
Per-chunk seeding from `hash(seed, cx, cy)` is the fix and is filed as part of
**#76**; until it lands this is a property of the tool, not a defect to work
around.

## The round trip must stay byte-identical

```bash
npm run world:export -- --discard-edits    # prints "round trip: byte-identical"
npm run world:check                        # what an import would change
```

The export self-checks: it takes a scratch copy of the map, blanks `edits`, puts
every generated object back at its `hj_gen` position, rebuilds props, clutter
and cliffs from `hj_gen_planes`, imports that, and compares to
`data/world/overworld.json`
byte for byte — same key order, same `indent=1`, same base64 of the same zlib
stream. `ROUND TRIP FAILED` names the diverging key, and it means the import
would lose whatever you just added to the world schema.

`--discard-edits` is right when regenerating from scratch and prints what it is
about to destroy first. It is **not** right in a tree with hand edits in the
`.tmj` — that file is the durable artefact and `overworld.json` can be rebuilt
from it, never the reverse.

Note `blocked_b64_deflate` is *recomputed* on both halves, never copied, by
`derive_blocked()` in `tools/world_to_tiled.py` — which `make_world.py` imports
so there is one collision rule and not two. So a green round trip is also
proving your placement change agrees with the importer's reading of it.

## Verify by decoding, never by assuming

A picture cannot tell you a prop was dropped, and `placed` props have no density
so the validator's "this prop never appears" warning cannot see them either.
Decode the planes and read them:

```python
import base64, json, zlib
w = json.load(open("data/world/overworld.json"))
W = w["w"]
props   = zlib.decompress(base64.b64decode(w["props_b64_deflate"]))
blocked = zlib.decompress(base64.b64decode(w["blocked_b64_deflate"]))
clutter = zlib.decompress(base64.b64decode(w["clutter_b64_deflate"]))
tiles   = json.load(open("assets/tiles/tiles.json"))
cat  = {p["plane"]: p for p in tiles["props"]["list"]}
clut = {p["plane"]: p for p in tiles["clutter"]["list"]}   # a SEPARATE numbering
```

Two things to check, and count both:

- **Every prop is solid-or-not as intended.** Compare `cat[v]["solid"]` against
  `bool(blocked[y*W + x])` for each non-zero cell. Remember the footprint:
  `derive_blocked` blocks `x+fx, y-fy` over `foot`, so a solid prop's anchor is
  not the only cell that comes back 1.
- **Nothing was dropped.** Count what the pass placed and check the same number
  decodes back. `furnish_house` once recomputed the internal wall, got it wrong,
  and `continue`d past every piece that landed on one — silently.

**Flood-fill to prove connectivity, and where it matters, sealing.**
`reachable(world, start)` in `make_world.py` is the primitive, and `main()`
runs two fills carrying three assertions, all of them `SystemExit` rather than
warnings:

| Fill | Asserts |
|---|---|
| from `spawn`, with solid prop footprints and cliffs in `world.blocked` | every named story anchor is reachable on foot; prints reachable cells as a % of walkable |
| from `spawn` again, with the **front door added to `blocked`** | **stranded** — no walkable cell inside the house footprint falls outside the fill (*a pocket behind a barrel is a cell the player can see, walk at, and never stand on*) |
| " | **sealed** — no cell *outside* the footprint falls inside it |

The second fill is why the seal is checked rather than trusted:
`HJWorld.walkable()` returns false on the door cell until the Grit is paid, so
that one cell **is** the entire Beat 4 gate. A gap anywhere else in the wall and
the tutorial economy is bypassed by walking round it — and the hole would never
be in your plan, it would be something a later pass did. That is exactly what
happened when the road carver drove seven columns of dirt through the east wall.
A new pass that paints terrain, places props or carves anything near a building
must run after nothing that can reopen it, and the fill is the proof.

If you add a building or an enclosure, add the equivalent fill. It costs a few
lines and it is the only honest way to know.

**A pocket is the scatter's mistake, and the scatter gives the cells back.**
`scatter_props` knows nothing about connectivity, so sooner or later a boulder
lands in the last one-cell gap of a yard and thirty-odd cells of the vale stop
being anywhere anyone can stand. main() has always died on that; what it never
had was an answer, so "it passes" meant "this seed did not do it" — and that
ran out the first time the RNG stream shifted. `unseal_pockets()` now removes
every SCATTERED SOLID prop on a pocket's boundary and asks again, and
`vale_pockets()` is the one function both the repair and the check use, so a
repair cannot report success against a question the check asks differently.
The check is still a `SystemExit`: a seal made of buildings and water is a
build failure and should be.

## Adding a material, or deciding not to

The question that comes up every time something new needs building: is this a
new material, or an arrangement of what exists?

**Reuse when the difference is position, arrangement or scale.** A bigger
footprint, a door on the other side, more windows, a different floor from the
five that exist. These cost nothing and carry a surprising amount — most of what
makes two buildings read differently is where they sit and how they are laid
out, not what they are made of.

**Generate when the difference is material or construction**, and reusing would
make two things that should read differently read the same. The tell is a
count: the tileset held **one** `roof` when the town needed fifteen buildings.
One roof across a whole town reads as a housing estate rather than a place that
grew, and no amount of clever placement fixes it, because the thing that is
wrong is not the arrangement.

**Do not generate a variant that appears once**, unless it is a landmark the
player will navigate by. A mill and a tavern earn unique treatment; a third
ordinary house earns a variant of an existing one.

The underlying design rule, which is what makes the judgement rather than a
preference: **shared architecture is what makes it one town, and material is
what makes them different buildings.** A consistent roof pitch, window shape and
cap-and-face construction should be visible everywhere; the mill is stone
because it takes weather and vibration, the tavern is timber-framed with plaster
infill because it was cheap and got extended twice. Material follows from what
the building *is* — its purpose and its age — and a material chosen for variety
alone reads as a palette swap, which is worse than reuse.

**Generate programmatically here, not with the image model.** The whole tileset
is built in `tools/make_tiles.py`: it is deterministic, free, and the autotiling
and precedence machinery absorbs a new material without complaint — the house
work added four in a day (`wall_timber`, `floor_tile`, `floor_plank`,
`floor_rug`). Reserve `game-art-pipeline` for something genuinely drawn, and
read its budget warning first, because every generation costs real quota.

## Declarations must live in the generator, not only in the manifest

**Symptom:** a field you added to `assets/tiles/tiles.json` is simply gone after
someone runs `npm run tiles`, and the feature it drove has quietly stopped
working — no error, because a missing key reads as "this prop doesn't do that".

**Cause:** `make_tiles.py` writes `tiles.json` from scratch. Anything hand-edited
into it is one regeneration from deleted. Seventy-four `sway` declarations
existed only in the manifest and had already been eaten once mid-session before
anyone noticed.

The rule: **anything the manifest carries must be emitted from source.** The
seam is `_p()` in `make_tiles.py` (~line 3109) — it takes `light` and `sway` as
keyword arguments that no code in that file reads and copies them into the
entry; a new block is three lines there and a paragraph in its docstring stating
the contract. Variants inherit from their base (~line 3430). Then teach the
contract to `data/schema.json` and `world_pass()` in `tools/validate_data.py`,
which checks each block key by key: a bad `sway` `mode`, a non-positive `speed`,
a `light` colour that is not `#RRGGBB` are hard errors, and an unknown key is a
warning saying nothing reads it. That last check is what catches the misspelling
that would otherwise be a lamp silently going out.

`world_pass()` validates three such blocks today — `light`, `sway` and `shaft`.
**Check each is actually emitted by `_p()` and not merely sitting in the
manifest**, because the validator reads `tiles.json` and so cannot tell the
difference. `make_tiles.py` takes no arguments, so compare the two sets instead
of running it:

```bash
grep -n 'entry\["' tools/make_tiles.py   # every key _p() emits
python3 -c "import json; d=json.load(open('assets/tiles/tiles.json'))['props']['list']; print(sorted({k for p in d for k in p}))"
```

Any key in the second list that `_p()` does not write is one `npm run tiles`
from gone.

Prove the fix the way the sway fix was eventually proved: **from a clean
checkout the generator produces zero rows, from the fixed source seventy-four.**

## Do not hide the generator's errors

**Symptom:** you keep re-reading a manifest that never changes, and the feature
you are adding does not appear no matter what you do.

**Cause:** the generator's output was redirected away. A `make_tiles.py` run sent
to `/dev/null` failed with a `SyntaxError` for several commands in a row while
the manifest under inspection stayed stale the whole time — the keyword
arguments had been inserted before the positional ones. Redirect **stdout** if
the report is noisy (`>/dev/null`); never redirect stderr, and check the exit
status. `&& md5sum ...` in the determinism check above does that for free.

## Props with behaviour must not also be solid

The dog and the cat were declared `solid=True` in `make_tiles.py`, which bakes a
1 into the `blocked` plane exactly where each animal lay — an invisible wall the
animal could walk off and never back onto. Both are `solid=False` now and both
home cells decode to 0.

The lesson generalises: **anything that moves, or that something else moves onto,
cannot be a solid prop.** It was first patched at runtime in
`Critters.gd.release_home_cells()`, which was the wrong place and is now a stub
kept only so its two call sites name the intent; the fix belongs in the
generator because the collision plane is generated.

## The structural limits

One of the two is now closed; the other is still open, will bite a placement
pass, and has no workaround worth taking.

**Footprints grow east and north, and `(2, k)` is a lie (#82).** The art is
centred on the anchor in a 64×96 slot, so a two-cell-wide prop can *block* its
second cell but cannot *reach* it with pixels. `bench`, `well`, `cart`,
`market_stall` and the fallen logs all declared two and drew one; every one has
been demoted to `(1, 1)`. Today the catalogue holds 231 props at `(1,1)` and 2
at `(1,2)` — growing north, which works because the slot is three cells tall.
**Do not declare a width of 2.** #82 proposes making the footprint symmetric
about the anchor (`x-(w-1)//2 … x+w//2`), which makes 1 and 3 drawable; it
touches `make_tiles.py`, `make_world.py`, `TileWorld.gd` and `validate_data.py`
together, and it is a regeneration, which is free now and stops being free once
props are hand-placed in Tiled.

**One prop per cell — CLOSED (#83).** There are two planes now. `props[y][x]`
is what OCCUPIES the cell and may be solid; `clutter[y][x]` is what does not —
it lies on the floor or sits on the thing standing there, and it is never
solid. So a cup stands on a counter, and a lane can carry grit *and* a
milestone.

Three things follow, and each has bitten something already:

* **They are numbered independently.** Props id 5 and clutter id 5 are
  different things. Anything that maps a plane byte to a catalogue entry has to
  say which plane it means — `plane_index()` in `make_world.py` answers it from
  the id, so a placement pass names a thing and never a plane.
* **The budget is 255 PER PLANE**, not 255 in total, and that is the whole
  reason it is a second plane rather than a wider byte. `python3
  tools/add_prop.py verify` prints both. Moving the ground scatter, the rug,
  the wall stain and the evidence-of-use set across took props from 254 to 185.
* **Collision cannot go wrong, by construction.** `derive_blocked()` is handed
  `props` and `cliffs` and never `clutter`, so a solid clutter entry would
  block nothing while claiming to — which is why `make_tiles.py` asserts none
  exists and `world_pass()` errors on one. `world_pass()` also finds an owner
  for every cell in `blocked`, so a clutter byte that ever reached collision
  would be an error and not a mystery.

Draw order within a cell comes from the entry's own `flat`: flat clutter under
the prop, everything else over it. Do not add a second word for that.

## `validate_data.py` is the gate

```bash
npm run check                        # == python3 tools/validate_data.py
python3 tools/validate_data.py --strict   # promotes warnings to errors
```

It reads the files on disk (never the `.tmj`) and runs in CI. For generator work
the passes that matter are `world_pass()` — required world keys, every region
naming a real area, every anomaly pointing at an area that exists, every
interactable `type` resolving against `data/content/interactables.json`, and the
`light`/`sway`/`shaft` contracts on every prop — and `reconcile()`, which checks
the schema's vocabulary against the engine's **in both directions**: a word the
schema lists that no source implements is an error, and so is a word the source
implements that the schema omits, because data using it would be rejected. That
is what stops the schema quietly describing something the code stopped doing.

`ERROR` means fixable inside `data/` and is fatal; `WARN` means the data is
consistent but something outside `data/` makes it dead.

`./test.sh` is the last gate before calling a change done (see the
`heroes-journey` skill) — it holds a lock, so check nobody else is mid-run.

## Where things are

| Thing | Where |
|---|---|
| Size, rings, biome thresholds, sectors, regions | constants at the top of `tools/make_world.py` |
| Terrain fields and biome choice | `build_fields()`, `slope_field()`, `biome()` |
| Roads, town, house, observatory, summit | `carve_road()`, `stamp_town()`, `stamp_house()`, `stamp_observatory()`, `stamp_summit()` |
| Prop scatter, town stock, house furniture | `scatter_props()`, `stock_town()`, `furnish_house()` |
| Connectivity | `reachable()`, `nearest_open()` |
| Anomaly placement and naming | `place_anomalies()`, `name_anomalies()` |
| Cliffs and terracing | `terrace()`, `cliff_plane()` |
| Packing, and the printed report | `encode_plane()`, `encode_elevation()`, the tail of `main()` |
| The collision rule, shared by all three tools | `derive_blocked()`, `props_by_plane()` in `tools/world_to_tiled.py` |
| Prop catalogue entries and their extra blocks | `_p()` and the `PROPS` list in `tools/make_tiles.py` |
| Restoring authored props | `tools/add_prop.py reapply` / `verify` |

The generator prints a report at the end — cell counts, reachability percentage,
props placed and how many are solid, cliff cells, the house dimensions and seal,
Spite's distance from the doorstep, anomalies per tier and sector, and the full
terrain histogram. **Read it.** Most regressions show up there before they show
up anywhere else, and it is cheaper than any of the checks above.

For the inside of a building — clearances, room purpose, furniture, the
tile-to-feet ruler — see the `interior-layout` skill, which is the worked
example of a hand-placed pass done properly.
