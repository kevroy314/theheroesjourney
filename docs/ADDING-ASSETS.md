# Adding assets

How a picture of a thing becomes a thing in the world.

Everything in `assets/tiles/` is drawn in code by `tools/make_tiles.py` — 1,722
sprites out of about twenty generators, which is the right trade for tiles and
transition sets and is a bad trade for *one more prop*. Adding a well used to
mean writing a builder, regenerating the whole set, and hand-checking the
manifest. This is the other route: bring a picture, get a prop.

```
python3 tools/add_prop.py add --src <png> --id <name> --biome <material> [dials]
```

The route it closes, and the one worked example in the repo:

```
python3 tools/add_prop.py add \
    --src art/area_road_v1.png --crop 645,335,296,345 \
    --id tree_windswept --biome scree --density 0.006 --solid \
    --size 32x46 --palette bark,wood --luma-lo 10 --luma-hi 60 \
    --coverage 0.42 --min-blob 0.004 \
    --preview-on snow grass_short
```

That is the dead tree standing beside the road in `art/area_road_v1.png`, cut
out of the plate, graded into the theme, rimmed, shadowed, and appended as
**plane id 71**. `python3 tools/make_world.py` then scatters 41 of them across
the scree. Total elapsed: 1.4 seconds of tool time, no image quota, about ten
minutes of looking at previews and turning two dials.

---

## The loop, in the order you would actually do it

### 1. Decide what the prop *is* before you make a picture of it

Four fields go in the catalogue and all four are decisions, not details:

| field | what it means | how to choose |
|---|---|---|
| `--id` | the catalogue name, and the object name in Tiled | lowercase, specific: `tree_windswept`, not `tree2` |
| `--biome` | the material the generator scatters it on, or `placed` | **it must be a material the world actually contains** |
| `--density` | chance per walkable cell of that material | 0.004 for a landmark, 0.02 for filler, 0.07 for ground cover |
| `--solid` / `--foot` | the collision footprint, in cells | a tree is solid where its trunk is; you walk behind its crown |

The `--biome` trap is real and the tool now checks it for you. `hardpan` is a
legal material in the tileset and the current generator produces **zero** cells
of it; a prop declared on hardpan is correctly drawn, correctly registered, and
will never appear. The verify step prints the cell count:

```
  world         7355 scree cells in data/world/overworld.json
```

Zero is a failed check. Either pick a material that exists, or use
`--biome placed` and put it somewhere on purpose in Tiled
(see `docs/MAP-EDITING.md`).

### 2. Get a picture

**Cheapest first: you may already have one.** There are sixteen 941x1672 plates
in `art/`, and they are full of objects nobody has ever been able to use — a
lantern, a grindstone, a market stall, the dead tree above. `--crop x,y,w,h`
takes a box out of any source image. This costs no quota and the art is already
in the game's style, which means less grading work downstream.

Otherwise, generate. **This spends the owner's ChatGPT image quota**, so the
tool makes you say so twice:

```
python3 tools/add_prop.py add --generate art/props/well.txt --spend-quota \
    --id well_covered --biome path_dirt ...
```

It shells out to `art/chatgpt_gen.py`, which drives the logged-in Edge session
over CDP — see `.claude/skills/game-art-pipeline` for the mechanics and for why
there is exactly one copy of them. Start the browser, leave a ChatGPT tab open,
and pass `--tab` if you want a specific conversation.

**Write the prompt for the cutter, not for yourself.** Everything the next stage
does badly is something the prompt can prevent. What the measurements below say
to ask for:

> One object, centred, whole, with a wide margin of empty space on all four
> sides. Nothing else in frame. A completely flat, uniform background in a
> colour clearly different in hue *and* in brightness from the object.
> **No ground plane, no shadow, no cast light — the object floating on the
> background.** No lettering, no numbers, no writing of any kind. Chunky pixel
> art, hard aliased edges, a limited palette, light from the upper left.

The two clauses that matter most are the shadow and the background contrast. A
soft studio shadow is the single biggest source of error in the cutout and there
is no reliable way to remove it afterwards (§ *Background removal*, below). A
dark object on a dark background cannot be separated at all.

### 3. Dry-run it and look at the picture

```
python3 tools/add_prop.py add --src art/props/well_gen.png --id well_covered \
    --biome path_dirt --density 0.004 --solid --dry-run \
    --preview-on snow grass_short
```

`--dry-run` conditions, grades, verifies and writes a preview, and does not
touch the catalogue. The preview is `art/props/_preview_<id>.png`: the prop
standing on each biome you named, twice, at the game's **3x zoom**, next to a
hand-drawn prop of that biome for scale — and then the sprite alone at 1x, 2x
and 3x, because 1:1 is where a sprite is actually judged.

**Look at the 1x strip.** Everything reads at 3x. The question is whether it is
still a well at 1:1 on a phone.

The verify block prints the art-direction checks as numbers. Every threshold is
calibrated against the 70 props already in the game, so "fails a check" means
"unlike anything else in this world", not "unlike my taste":

```
  size          33x39 px  (catalogue median 23x18, largest 41x50)
  rim           100% of the silhouette boundary is rimmed (every hand-drawn prop: 100%)
  contact       lowest opaque row y=95 of 95; 17 shadow px
  value         min 28  mean 47  p99 78  max 78  (nothing drawn exceeds 118)
  vs scree        ground mean 44: highlight +34, shadow +16
  colours       6 distinct (hand-drawn props: median 5, most 11)
  world         7355 scree cells in data/world/overworld.json
```

A failed check stops the append. `--force` overrides it, and is the right answer
about one time in ten.

### 4. Turn the dials

There are four that matter, in this order:

**`--size WxH`** — the box the art is fitted into inside the 64x96 slot.
Default `32x36`. The median hand-drawn prop is 23x18 and the largest is
`tree_broad` at 41x50; anything bigger than that will swallow the cell it
stands on.

**`--luma-lo` / `--luma-hi`** — the value band the prop is graded into,
defaulting to 14..124. This is the dial that most often needs moving, because
an AI render arrives with its own exposure and the tool has no idea whether the
subject is *meant* to be dark. The worked example needed `--luma-lo 10
--luma-hi 60`: the source is a tree silhouetted against a bright sky, so its
own values are pale, and the default band graded it up into a white feather.
§2.6 of `docs/ART-DIRECTION-OVERWORLD.md` reserves 130–150 for the character;
nothing drawn exceeds 118, so treat 120 as the ceiling.

**`--palette` / `--ramps`** — which of `make_tiles.py`'s eighteen prop ramps the
sprite is quantised into. Left alone, the tool picks the `--ramps` (default 3)
that best explain the picture, by matching pursuit. It picks by *colour*, so a
blue-grey silhouette gets `snowpile + stone + pale` and looks like ice. When the
answer is obvious, state it: `--palette bark,wood`. Fewer ramps is almost always
better — 12 available colours produced 6 used, which is exactly the hand-drawn
median.

**`--bg-tol` and `--crop`** — see below.

Two more worth knowing: `--coverage` (default 0.5) is how much of a target pixel
the subject must cover to be opaque — lower it to about 0.42 to keep thin
branches and railings; and `--keep "#E9A94E"` pins a theme colour into the
palette the way `art/postprocess.py` does, for a subject whose whole point is
one accent (a lit window, a flame).

### 5. Register it

Drop `--dry-run`. The tool appends to `assets/tiles/props.png` and
`assets/tiles/tiles.json`, saves the finished 64x96 sprite to
`art/props/<id>.png`, and records everything in `art/props/authored.json`.

```
register
  appended      tree_windswept at index 70, plane id 71 (atlas 9 rows)
  registry      art/props/authored.json
```

### 6. Put it in the world

Appending to the catalogue does not put anything in the world. Two ways in:

* **scattered** — `python3 tools/make_world.py` re-runs the generator, which
  reads the densities straight out of `tiles.json`. The worked example went from
  0 to 41 instances on that one run. Note that this regenerates the whole world;
  hand edits survive as overrides, per `docs/MAP-EDITING.md`.
* **placed by hand** — `python3 tools/world_to_tiled.py`, open `world/`
  in Tiled, and the new prop is already in the tileset panel with its picture
  and its name. The exporter rebuilds the tilesets from `tiles.json` on every
  run, so nothing needs telling about it.

### 7. Commit

`assets/tiles/props.png`, `assets/tiles/tiles.json`, and all of `art/props/`.
The last one is not optional: `art/props/authored.json` and the sprites beside
it are the only thing that survives the next `make_tiles.py` run (see
*Appending is the only safe edit*, below).

---

## Background removal, and how well it actually works

This is the hard part of the whole pipeline and it is worth being straight about
it. `art/cutout.py` has the long version; this is the summary and the numbers.

**What it does.** It fits a smooth quadratic **model** of the background per
channel to the border ring — robustly, discarding outliers and refitting, so a
subject that touches the frame does not drag the fit — and thresholds each pixel
on its residual from that prediction, in gamma-lifted space. Then it takes the
connected component of the eligible pixels that touches the border. Modelling
the background rather than picking a background colour is what lets the
tolerance stay tight enough not to leak into the subject while still tracking a
background that varies by 40 levels corner to corner, which every AI render's
does. The binary edge is decided at 64x96 by area coverage, not at full
resolution, so the aliasing lands where the shape is.

**How well.** Measured against ground truth: six of the game's own props
upscaled 8x, softened, JPEG'd, and composited onto a gradient-plus-vignette
background, so the true silhouette is known exactly.

| | IoU vs. truth | over-segmented | under-segmented |
|---|---|---|---|
| plain background | **0.94 – 0.98** | +2 – 5% | 0% |
| background + a soft studio shadow | **0.86 – 0.97** | +3 – 16% | 0% |

The 0% under-segmentation is the useful property: across every case and every
tolerance tested, it **never ate part of the subject**. All the error is the
other way — a pixel or two of halo, and the render's own shadow being kept.

On real input — the dead tree in `art/area_road_v1.png`, a genuine ChatGPT plate
— it modelled 96% of the border ring as background at the default tolerance and
recovered the silhouette cleanly enough to use unretouched.

**Where it fails, honestly:**

* **Dark subject on a dark background.** Not a tuning problem, an information
  problem. A tolerance loose enough to catch the background eats the subject. A
  first test with a dark tree on a night-blue background scored 0.32.
* **The render's own drop shadow.** `--drop-shadow` tries: a cast shadow is the
  background multiplied down, so it lies on the ray from black through the
  background colour, and pixels on that ray in the bottom of the subject's
  bounding box are reclassified. It is opt-in, it refuses if it would remove
  more than a third of the subject, and **on the measurements it is not a net
  win** — best mean IoU 0.891 with it on against 0.929 with it off, across six
  parameter settings. A grey stone object on a warm grey background *is*, to
  this test, exactly a shadow. Prevent it in the prompt.
* **Cluttered scenes.** It wants one subject on a flat-ish field. Cropping a
  well out of a busy market square does not work and will not; that is a
  segmentation problem, not a background-removal one.
* **Enclosed background** — the gap under a gate, the mouth of a well — is kept
  as subject by default, because an interior highlight that happens to match the
  background is far more common than a real hole. `--fill-holes 0.02` punches
  them.

**What would be better.** Learned matting — `rembg`/U²-Net, or SAM — is the
actual state of the art and would handle every case above. It is a ~180MB ONNX
download; this machine has numpy and PIL. If that ever changes, `cutout.cutout()`
is one function with one return signature and swapping it is an afternoon.

---

## When the generated image is unusable

Sometimes it is. Read this before spending a second generation, because the
second generation on the same prompt usually produces the same problem.

| what you see | what happened | what to do |
|---|---|---|
| `only 43% of the border reads as background` | the subject fills the frame, or the background is busy | `--crop` a tighter box that has clean background on all four sides; then raise `--bg-tol` to 0.14 |
| `nothing survived: the whole image read as background` | the subject is the same value as the background | lower `--bg-tol` to 0.06. If that does not fix it, the image is unusable — regenerate with a contrasting background |
| the cutout keeps a dark skirt around the base | the render has a studio shadow | crop it off, or accept it — at 64x96 it is a few pixels. Do **not** reach for `--drop-shadow` first |
| holes punched through the middle of the subject | part of the subject matches the background exactly | lower `--bg-tol`; if the subject is genuinely two-tone with one tone matching the background, regenerate on a different background colour |
| thin things (railings, branches, rope) disappear | they are below the sampling limit at 64x96 | `--coverage 0.42`, `--min-blob 0.004`, and a bigger `--size`. If it still fails, the object is too fine for this scale — that is a real answer |
| it reads as a grey blob at 1:1 | too many colours, or no value structure | `--palette` two ramps, widen `--luma-lo/--luma-hi` |
| it looks pasted in, right value, wrong colour | auto-chosen ramps | name them: `--palette stone,metal` |
| the silhouette is unrecognisable at 1:1 | the object is too complex for 32 px | **throw it away.** Prompt for a simpler, more iconic version of the same object — a *shape*, not a scene. This is a prompt fix and it is the one worth spending a second generation on |

Everything above is free to retry — the source PNG is on disk and the whole
pipeline is 1.4 seconds. Only the last row costs quota.

---

## Appending is the only safe edit

Prop **plane ids are stored in world data and in hand edits**. Slot index in
`props.png` is the plane id minus one. Renumbering the catalogue silently
rewrites every map ever generated and every object anyone has placed in Tiled.
So the tool appends, and it will not do anything else:

1. **It refuses to start on a catalogue that has already moved.** Before any
   work — and specifically before `--generate` can spend quota — it checks that
   every entry has `index == position` and `plane == index + 1`, that ids are
   unique, that the slot geometry is still 64x96 anchored at (32, 96), and that
   `props.png` is exactly `cols x rows` slots. Any mismatch is a hard stop with
   the offending entry named.
2. **It refuses to add an id that already exists.** Two plane ids for one thing
   is how a catalogue rots. `--replace` redraws an existing authored prop *in
   place*, keeping its index and plane id.
3. **It proves the append after making it and before writing it.** The new
   manifest is compared entry-by-entry against the old one with the new slot
   excluded, and every pre-existing atlas slot is compared **pixel for pixel**
   against the bytes it started from. If either differs, nothing is written.
4. **The atlas grows a row when it needs one.** Nine rows, 72 slots, 71 used.
   Slot 72 is free; prop 73 grows the atlas to ten rows, which the manifest
   records and every consumer already handles.

Consumers hold up the other end: `tools/world_to_tiled.py` and
`tools/tiled_to_world.py` fail by name and id on a plane with no catalogue
entry rather than dropping the prop, and rebuild both tilesets from `tiles.json`
on every export — so an appended prop is pickable in Tiled immediately, with no
step in between.

### `make_tiles.py` will delete your props, and that is fine

`tools/make_tiles.py` owns `props.png` and `tiles.json` and rewrites both from
scratch. That must stay true — it is why the whole tileset is reproducible. So a
run of it wipes every appended prop, and the recovery is one command:

```
python3 tools/make_tiles.py      # props.png back to 70 slots
python3 tools/add_prop.py verify # MISSING  tree_windswept (was plane 71)
python3 tools/add_prop.py reapply
```

`reapply` re-appends every prop in `art/props/authored.json`, in recorded order,
from the saved sprites — byte-exact, no source image, no second generation.
Verified: `props.png` and `tiles.json` come back **byte-identical** to before the
regeneration.

It refuses rather than guesses in the two cases that matter:

* the drawn catalogue is no longer the size the registry was built against
  (someone added a prop to `make_tiles.py`), because re-appending would hand the
  authored props *different plane ids* than the world already stores. The
  message says so and tells you the two ways out;
* a saved sprite has changed on disk since it was appended — a silent edit does
  not get into the atlas.

`python3 tools/add_prop.py verify` checks all of it and exits non-zero, so it
belongs in any pre-commit hook you ever write. `list` prints the whole catalogue
with the authored ones marked.

---

## What still needs a human eye

The tool checks everything that is measurable, and none of these are:

* **Is it recognisable at 1:1?** The rim check, the value check and the colour
  count all pass on a sprite that is a handsome dark blob. Look at the 1x strip.
* **Does it read as the right kind of object?** The worked example is a
  legitimate windswept tree at 3x and reads more like a shrub at 1:1, because
  its trunk is two pixels wide. A hand-drawn builder would have thickened the
  trunk. That judgement is not automatable.
* **Is the light coming from the north-west?** Every drawn prop in this game is
  lit from the upper left, without exception. An AI render lit from the right
  will pass every check and be wrong in the scene. Ask for it in the prompt and
  check the preview.
* **Is the scale right against its neighbours?** That is what the hand-drawn
  neighbour in each preview panel is for.
* **Is the density right?** Nothing measures "too many wells". `make_tiles.py`
  prints props-per-57-cell-screen; §2.3 wants 6–12 in total.

## Where this pipeline breaks down

* **Anything bigger than one prop.** The slot is 64x96 and the anchor is fixed.
  A building is not a big prop — §2.3 wants a footprint, a facade and a roof as
  separate pieces with their own y-sort — and this tool cannot make one.
* **Multi-cell footprints** are declarable (`--foot 2x2`) but not verifiable: the
  tool cannot tell whether the art you gave it actually covers two cells, and
  nothing checks that the shadow and the footprint agree.
* **Animation.** There is none, here or anywhere in the tileset. The image model
  cannot hold an identity across frames at all (see the skill file), so an
  animated prop means one canonical still and a shader in Godot.
* **Tiles, as opposed to props.** A tile has to be seamless against itself and
  against three variants and 32 overlay masks. Nothing about this pipeline
  produces that, and generation is the wrong tool for it: `make_tiles.py` gets
  1,536 overlay tiles out of one parameterised generator, and no amount of
  prompting competes with that.
* **Interior furniture** works mechanically — `--biome placed` — but the
  interiors are furnished by hand in `make_world.py`, so a new chair also needs
  a line there, which this tool does not write.
* **Themes.** The grading reads `data/themes/firstlight.json` through
  `make_tiles.py`, so an authored prop moves with a theme edit exactly as a
  drawn one does — but only when it is re-run. `duskfall.json` is not wired up
  for tiles at all yet.

## The files

| path | what |
|---|---|
| `tools/add_prop.py` | the pipeline: ingest, condition, grade, register, verify |
| `art/cutout.py` | background removal, standalone and documented |
| `art/props/authored.json` | the registry: every authored prop, its plane id, its dials |
| `art/props/<id>.png` | the finished 64x96 sprite, the thing `reapply` restores |
| `art/props/_preview_<id>.png` | the last preview rendered for that prop |
| `art/chatgpt_gen.py` | the generator driver (unchanged, called as a subprocess) |
| `art/postprocess.py` | the backdrop quantiser. Not used here — it has no alpha, no anchor, and quantises to an adaptive palette rather than the game's ramps — but the gamma-lifted distance and the pinned-accent idea are both taken from it |
