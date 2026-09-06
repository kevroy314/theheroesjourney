# What this genre actually puts on screen

A survey of the reference screenshots in `AESTHETIC-SEEDS/` (not committed —
they are other people's games). The point is **not** to copy them. It is to
enumerate what a top-down pixel world of this kind is *made of*, so we can see
what we are missing and invent our own versions.

The short answer to "why does our world feel scattered and theirs feels alive":
**they have four layers of visual information where we have one.** We draw
terrain. They draw terrain, plus a scatter layer, plus objects with height, plus
light. Every one of those layers is doing work.

---

## 1. Ground is never one tile repeated

**What we do:** one 32×32 tile per material, autotiled at the edges. A field of
grass is the same 32 pixels 400 times.

**What they do:** a base tile, then a *sparse scatter layer* of tiny detail
props on top — pebbles, tufts, fallen leaves, single flowers, cracks. Core
Keeper's floor is maybe 8% covered in scatter and it completely destroys the
grid. Necesse's grass carries small orange flowers and grass tufts at maybe one
per twelve tiles.

The scatter is **not** autotiled and **not** aligned to the tile grid — it is
placed at sub-tile offsets, which is exactly what breaks the right-angle
feeling. It is also cheap: eight 8×8 sprites scattered at 1-in-12 does more for
"this is a place" than eight more terrain materials.

> **Asset need:** a scatter set per biome — 6–10 tiny sprites each (8×8 to
> 16×16), placed at sub-tile offsets, non-colliding, purely decorative.

## 2. Objects have height, terrain does not

Every reference draws a hard distinction:

- **Terrain** is flat, lit from directly above, no cast shadow.
- **Objects** — walls, trees, barrels, fences, lamp posts — have a visible
  *top face* and a *side face*, and they cast a small contact shadow.

Necesse's buildings are the clearest case: a wall is a light stone cap with a
darker vertical face below it, so the building reads as an extrusion from the
ground rather than a painted rectangle. That single two-tone treatment is what
gives a top-down scene its depth, and until recently our world had none of it.
The wall sets are drawn that way now — `tools/make_tiles.py` renders a lit cap
and a driven-down face from the same hue, with a two-pixel joint where they
meet, and that joint is what makes the cap sit *on* the face rather than beside
it.

Y-sorting is necessary but not sufficient. The sprite has to *look* like it
stands up.

> **Asset need:** wall sets drawn as cap + face, not as a floor tile in a
> different colour. Contact shadows under every standing prop.

## 3. Light is the atmosphere, and it is radial and coloured

This was the single biggest gap, and it is what the user clocked. It is now
built: an ambient day/night ramp plus a per-emitter light list, both in
`scripts/ui/Lighting.gd` and one shader pass. See DESIGN.md.

Core Keeper's entire mood is one mechanic: **darkness is the default state and
light is a warm radial gradient from a source.** Not a brightness multiplier — a
*colour* ramp. Gold at the source, deep amber mid-falloff, black at the edge.
A second source in a different hue (the blue pool) instantly reads as a
different kind of place, with no other art changing.

Necesse does the same thing at lower contrast: braziers and lamp posts each drop
a warm pool onto the ground, and the pools are what make a paved plaza look
inhabited rather than tiled.

The implications for us are large and cheap:

- A lit window in our house projects a warm wedge onto the ground outside.
- A street lamp in town makes the town read as *town* at a glance.
- Dawn (our starting hour) is the best possible lighting: long, warm, low, with
  everything not lit sitting in cool blue shadow.
- Day/night becomes an atmosphere dial, not just a clock.

> **Asset need:** none, and there never was one. This is a shader and a light
> list, and the art declares a source by adding
> `"light": { "radius", "color", "flicker" }` to a prop in
> `assets/tiles/tiles.json`. Six props carry one: the lamppost, the street lamp,
> the floor lamp, the stove, the candle and the lit window.

## 4. Roads have edges

Necesse's paths are not a colour change — they have a **kerb**: a distinct edge
piece where the paving meets the grass, one or two pixels of raised stone. Our
roads currently terminate by simply stopping.

This also fixes the "roads dead-end in walls" complaint from a different angle:
a road with an edge treatment reads as *deliberate* even where it stops.

## 5. Interiors are a different material vocabulary

Every interior in the references uses floor materials the exterior never uses —
wood plank, patterned tile, rug — and the change of material is what says "you
are inside". Necesse goes further: each *room* inside a building has its own
floor.

The house obeys this now. It is 19×15 with real walls, a sealed footprint whose
only exit is the front door, and **four rooms on four floor materials** — the
parlour on plank, the kitchen on tile, the hall on boards, an unheated pantry on
stone, and a rug beside the bed so the first cell you stand on is not the same
cell as the last one. Three wall runs with four doorways between them, so the
space has to be walked rather than seen.

The pantry is the load-bearing one and it came out of the layout research rather
than the art research: a room holding one of everything reads as a storage unit,
and the historical fix is the three-cell cottage's unheated service room. Give
the clutter a room that is *supposed* to be full of clutter and the other three
stop being it.

The geometry lives in one function, `house_plan()` in `tools/make_world.py`, and
every other pass reads that description rather than recomputing it. The old code
worked the internal wall out twice, differently, which is how a chair came to be
placed inside a wall and silently dropped.

## 6. Props come in variants, and the variants are the point

Chrono Trigger's stone floor is not one block stamped repeatedly — the blocks
are different sizes and the seams do not line up. Necesse has at least four
crop types visibly different at a glance, and its sunflowers are planted in
irregular clumps rather than a rectangle.

The rule the references follow: **anything that appears more than ten times in
a screen needs at least three variants.** Trees, rocks, grass tufts, fence
posts, floor boards.

Our world places **7,587 props drawn from a catalogue of 233**, across 12
biomes — about 33 placements per entry, where it used to be several hundred. 94
of the 233 are `_v2` / `_v3` variants of something else, which is this rule
being obeyed rather than described.

## 7. The portal is a big object, not a tile

Chrono Trigger's gate is a **large circular swirl** several tiles across, with
concentric distortion, a bright core, and the character visibly standing inside
it as it takes them. It is unmistakably a hole in the world.

That is the reference for our anomalies, and it argues for the "walk into it and
get pulled in" behaviour rather than "step on it and press a button".

## 8. The world map is painted, not tiled

Chrono Trigger's overworld: mountains are hand-drawn masses with ridge highlights
and shading, coastlines are organic with a sand fringe, forests are clumps of
individually-placed trees. Landmarks are unique painted objects at a larger
scale than the terrain around them.

This is the answer to "the walking view feels like a bunch of disjoint right
angles" — at map scale, *stop tiling*. Our `WorldMapScreen` already draws rather
than tiles; the lesson is to push it further and make landmarks unique.

---

## UI: what "solid" means

Two references, and they agree.

**EverQuest** — the one the user named. Panels are **carved stone**: opaque,
textured, with a chiselled inset border. They butt against the screen edge and
against each other rather than floating. Crucially, **different content types
get different materials** — stone for chrome, parchment for prose. Body text is
plain, high-contrast, unglowing, and completely legible.

**The Terraria-like inventory** — opaque slate panels inside a metal frame with
corner ornaments. Bevel is 2–3px: light on the top-left, dark on the bottom-
right. Slots are *inset* with their own reversed bevel. Saturated accent colour
appears only on data — numbers and item icons — never on the chrome.

What both avoid, and what we currently do: **a translucent tinted rectangle over
the game.** Our panels have a purple cast because they are `panel` at partial
alpha over a cool backdrop, so the world colour bleeds through and muddies them.

The fix is a material, not a colour tweak:

| | now | wanted |
|---|---|---|
| fill | translucent, world bleeds through | opaque |
| border | 1px flat line | 2px bevel, light TL / dark BR |
| texture | none | subtle noise or hatch |
| prose | same panel as chrome | its own material (parchment/vellum) |
| accent | on borders and chrome | on data only |

---

## What "makes a world feel alive" — the consensus advice

Gathered from what these games actually do, plus the level-design and pixel-art
literature (sources at the bottom). Every item is cheap relative to its effect:

1. **Idle motion.** Something on screen is always moving — grass sway, water
   shimmer, a flickering flame, smoke from a chimney. The pixel-art guidance is
   blunt about this: *static sprites make a world feel paused.* A perfectly
   still world reads as a screenshot.
2. **Light that has a source.** A glow with a visible lamp under it is
   atmosphere; a glow with nothing under it is a bug.
3. **Evidence of use — this is the big one.** The environmental-storytelling
   literature is unanimous: a level should imply *an event that already
   happened*. A chair pulled out from a table. A cup left on the counter. A
   worn dirt path through the grass where people actually walk. Boots by the
   door. This is the cheapest possible narrative device and we currently use it
   nowhere. Our waking room should tell you something about who slept there.
4. **Props reflect their owner.** NPC placement, possessions and surroundings
   should encode occupation and personality without a line of dialogue. Spite's
   corner of the world should look like Spite before he speaks.
5. **Scale variety.** A world where every prop is one tile is a grid. One
   three-tile tree changes the read of a whole screen.
6. **Sparse asymmetry.** Regular spacing reads as generated. Clumping and gaps
   read as grown.
7. **Palette cycling for time of day.** The pixel-art guidance specifically
   recommends palette fading/cycling over re-drawing assets for day/night — one
   ramp, applied globally, costs nothing per asset and is how this genre has
   always done it.
8. **Layered depth.** Parallax is a side-scroller trick, but the underlying
   principle transfers: distinct near/mid/far bands of detail density. At map
   scale, distant terrain should be simpler than what is underfoot.
9. **Consequence you can see.** A closed anomaly should *visibly* close.

### Living props: the dog and the cat

Two animals in the house, both with a `Pet` action, and they are deliberately
the cheapest possible rehearsal for the entity and mob systems (#34, #36):

- **The dog.** Pet it and it follows you — a leader/follower path, re-evaluated
  each step, with a lag so it trails rather than mirrors. That is the same
  primitive an escort quest or a companion needs.
- **The cat.** Pet it and it *flees*, then slowly stalks you: retreat to a
  minimum distance, then approach to a preferred distance and hold, breaking
  off if you get too close. That is the same primitive a wary mob needs —
  Necesse's animals and our future Time Wraiths both want exactly this.

Between them they cover follow, flee, approach-and-hold, and state transitions
driven by a player action. Getting them working in one room, where the space is
small and bugs are obvious, is worth more than speculating about mob AI in the
abstract.

That rehearsal is done, and it came out better than the brief. Both animals are
**data** — a state machine per species in `data/content/critters.json`, over a
vocabulary of four goals and six conditions in `scripts/game/Critters.gd`, which
knows nothing about dogs or cats. The escort in #78 is three states and four
transitions in the same shape and needs no new code; `CritterSim.gd` builds and
runs exactly that as a headless proof.

The one lesson worth carrying forward: **the thresholds in each direction must
differ.** The cat breaks off at 2, runs to 6, comes back in to 4 and only sets
off again at 5, so its resting band is 3–4 and no two rules disagree at any
distance. Matching the numbers produces an animal that vibrates on the boundary.
And `dozing` deliberately does *not* break on proximity, because a cat that
flees at two cells has an unreachable Pet verb — the wariness is something you
teach it.

### Sources

- [Environmental Storytelling in Video Games](https://gamedesignskills.com/game-design/environmental-storytelling/)
- [Storytelling — The Level Design Book](https://book.leveldesignbook.com/process/env-art/storytelling)
- [Level Art: Environmental Storytelling — Frozenbyte Wiki](https://wiki.frozenbyte.com/index.php/Level_Art:_Environmental_Storytelling)
- [Pixel art backgrounds: build worlds that feel alive](https://www.sprite-ai.art/blog/pixel-art-backgrounds)
- [Top-down game pixel art: sprite design and animation](https://www.sandromaglione.com/articles/pixel-art-top-down-game-sprite-design-and-animation)
- [Modding:Maps — Stardew Valley Wiki](https://stardewvalleywiki.com/Modding:Maps) (tile properties as behaviour, not just visuals)

---

## The asset backlog this implies

Ordered by effect per unit of work, and this is a live list rather than a
record — the top of it has been worked through.

| Priority | Asset | Count | State |
|---|---|---|---|
| 1 | Light sources + shader | — | **done.** Ambient ramp + light list; 6 emitting props |
| 2 | Interior walls (cap + face) | ~16 | **done.** `wall_timber`, `wall_stone`, drawn as cap + face |
| 3 | Interior floors | 4–6 | **done.** plank, boards, tile, rug |
| 5 | Door + lit window | 4 | **done.** `window_lit` emits; the front door is a real gate |
| 6 | Prop variants for the top props | ×3 each | **done.** 94 of the 233 catalogue entries are `_v2` / `_v3` |
| 10 | Furniture set for a real house | ~15 | **done.** bed, table, chairs, stove, counter, shelves, chest, crate |
| 11 | Dog and cat, 4-dir idle + walk | 2 | **done.** `assets/sprites/dog.png`, `cat.png`, driven by the critter state machines |
| 12 | "Evidence of use" props | ~8 | **done.** pulled-out chair, cup, boots, open book, bottle |
| 4 | Ground scatter, per biome | 6–10 × 6 | **open (#51).** Props sit on the cell grid; there is no sub-tile scatter layer, which is the whole point of this one |
| 7 | Road kerb pieces | ~8 | **open.** Paths still meet grass with no edge |
| 8 | The portal, as a large animated object | 1 | **open (#72).** Still a tile |
| 9 | Task-type icons | ~8 | **open.** The six axes have marks; the task *types* do not |

`tools/make_tiles.py`, `make_sprites.py` and `add_prop.py` already exist and the
five-tool contract through `tiles.json` holds, so most of what is left is
prompt-and-place rather than new pipeline. The done rows are here rather than
deleted because they are the evidence that the contract holds: every one of them
was an asset change with no renderer change behind it, except the light list,
which was always going to be code.
