# Procedural settlement generation: what to borrow, and what to refuse

> *"i cant help but wonder if there is already a robust procedural generation
> methodology for this stuff online we could benefit from."*

There is, and quite a lot of it is excellent. This document is a recommendation,
not a reading list: which technique for which of our six problems, what to
reject, and what specifically changes in `tools/make_world.py`.

The short version, before the reasoning:

**We have been generating a town by placing buildings and hoping a street
appears. Every source that works does it the other way round — it commits to the
*structure* first (water, then roads, then plots) and lets the buildings be
whatever fits.** Our two crossing streets are not a bad street network; they are
the absence of one, because nothing in the generator has ever asked where a
street should be. Four changes get us most of the way, and only one of them is
more than about eighty lines.

---

## 0. What we are actually starting from

Measured off the generated world, not estimated. **Snapshot: the tree at the
time of writing.** A concurrent pass is landing a brook, a pond, outbuildings
and the three unused roof materials as this is written, so some of the "now"
column is being closed while you read it — which is the point, and the rows are
kept because they are what the recommendation is a response to.

| | now |
|---|---|
| generator | 1,633 lines, pure Python + PIL. **numpy 2.4.2 is installed and unused** |
| runtime | **16.3 s** for 256×256; roughly 4 min at 1000², 17 min at 2000² |
| buildings in town | **7**, with 5 distinct footprints, none larger than 30 cells |
| what a building is | a rectangle of `roof` (solid) with one `door` cell on the street face. **The door opens into a wall.** There is no interior |
| roof materials used | **one** (`roof`). `roof_thatch`, `roof_slate`, `roof_pantile`, `wall_timber` and `wall_brick` exist in the tileset and appear nowhere in town |
| water near town | **none.** Nearest water is 55.3 tiles from centre; all 14,990 water cells are the rim ocean |
| rivers | **zero.** The whole world contains 3 bridge cells, all incidental |
| boundary props | `fence_rail`, `field_gate`, `leaf_wall`, `haystack` exist in `tiles.json` as of today, `density: 0.0`. **Nothing places them** |
| what the player sees | **7.5 × 7.6 tiles.** `ZOOM = 3`, 32 px tiles, ~720 px of map |

That last row is the one that should govern every choice below, and it is the
reason half the literature is inapplicable to us. **The player never sees the
town plan.** They see about 57 cells. A tensor-field street that curves
beautifully across two hundred tiles is, at our zoom, a staircase seen four
tiles at a time. What reads at 57 cells is: a wall on one side and a street on
the other, a doorstep, a corner, a fence running off the edge of the frame.
Frontage is everything and global elegance is nearly free to skip.

The second governing fact is `docs/MAP-EDITING.md`: **overrides are addressed by
cell.** A hand-placed barrel is "cell (137, 122) holds a barrel". So a
regeneration that moves the whole town by three tiles does not move the
designer's edits with it — it strands them. Almost none of the literature has
this constraint, and it is decisive against one very popular technique. §5.

---

## 1. The survey

One line on what each is good at, one on where it fails. Sources in §7.

### Street networks

| technique | good at | fails at |
|---|---|---|
| **Parish & Müller L-system** (2001) | dense road-dominated cities; blending grid/radial/coastal patterns; its `localConstraints` (prune → rotate → snap) is genuinely the canonical way to make a road hug a coastline | needs ~1,100 lines in the reference port for what we'd use on 20–40 segments; ±3° branch deviation quantises away entirely on a tile grid; buildings are leftovers of block subdivision, which is exactly our bug |
| **Tensor fields** (Chen 2008) | artist-directed city layouts where grid and radial patterns curve into one another | it is an *interactive tool* — remove the human painting the field and you are picking basis parameters blind. Streamline error accumulates; 1,500+ lines; produces curvature a 32 px tile cannot show |
| **Watabou / MFCG** | believable irregular medieval layouts in milliseconds, with a legible wall/gate/plaza structure | no terrain input at all — no heightmap, no water, radially symmetric about the origin by construction. ~1,900 lines of float polygon algebra that does not survive rasterisation |
| **Space colonisation** | organic self-avoiding branching that fills an irregular region; ~70 lines; attractor density *is* road density, an intuitive knob | it makes a **tree**. Zero loops, dead ends everywhere — the opposite of a road network |
| **Emilien, "Villages on Arbitrary Terrain"** (2012) | the only paper here actually about villages. Seeds a building, connects it by road, and the new road raises the interest of nearby land — the feedback loop that makes the causality right | the full pipeline is 4–20 minutes in C++ with **150 hand-tuned parameters per village type**, and no public implementation |
| **Wolverson's Rust town** | 264 readable lines that always terminate; the door→nearest-road A* with accretion is a legitimately good cheap trick | there is no road network algorithm in it. The wall is at literal `x = 30` and the street is one horizontal band at a random `y`. Buildings are blind rejection sampling with no retry limit |
| **Lechner agent-based** (2004) | three simple agents — extender, connector, builder — no grammar, maps straight onto a tile grid | underdocumented; less studied than the above |

### Plots and footprints

| technique | good at | fails at |
|---|---|---|
| **Recursive OBB split** (Vanegas 2012) | ~40 lines, and its rotate-on-orphan rule (`ξ = 1`) *guarantees* street frontage rather than filtering for it | still fundamentally rectangles; needs a sliver-merge pass, unconditionally |
| **Straight skeleton offset** (Vanegas, Citygen) | frontage is topological, so it cannot fail; the corner bisector is exactly the historically correct interlocking corner | O(n² log n) at best in practice, and *robustness*, not asymptotics, is the killer. The pure-Python library is documented by its own maintainer as incorrect for some inputs |
| **Voronoi plots** | irregular organic district boundaries for free | Watabou's own verdict on his own generator: *"a rather silly algorithm for creating alleys and buildings"* producing *"too many triangular buildings."* A Voronoi cell has no relationship to any street; there is no frontage concept in the diagram at all |
| **Axis-aligned BSP** | guaranteed non-overlap, natural corridor tree — the right answer for dungeon rooms, where rectilinearity is diegetic | splits are aligned to the *world* axes, so lots stop relating to the street the moment the street is not axis-aligned. OBB splitting is the same algorithm with one change and is strictly better |
| **CGA shape grammar** (Müller 2006) | facades and 3D mass models | overkill by an order of magnitude. Its operators exist to subdivide a wall into floors into windows. Top-down we render a footprint, a roof and a door |
| **Medieval burgage morphology** (Conzen; Tait; Haslam) | *this is the highest-value thing in the whole survey.* Real numbers for plot widths and depths, and the rule that makes corners look researched | it is a body of urban-history literature, not an algorithm; you have to do the translation yourself. §2 does it |

### Rivers and terrain

| technique | good at | fails at |
|---|---|---|
| **Flow accumulation** (sort by elevation descending, push flux downhill) | correct river networks in one pass; `sqrt(flux)` for width; confluences fall out for free | needs every cell to have a downhill neighbour, i.e. needs depression filling first — unless elevation is monotone |
| **Amit's distance-to-coast elevation** | monotone by construction, so **downhill from anywhere provably reaches water and there are no local minima at all** | mountains end up in the middle, because "distance from coast" *means* middle |
| **Priority-flood depression fill** (Barnes 2014) | O(n) on integers, under a hundred lines, strictly dominates the alternatives | ~15 s at 1000² in pure Python, and it does **not** vectorise — the numpy relaxation benchmarked 10× *slower* and failed to converge |
| **Hydraulic erosion** (Lague/Beyer, Talle) | plausible valleys and ridges | 60 s to 30 min in pure Python. And by the authors' own admission it gives you valleys, *not* rivers — you still need flow accumulation on top |
| **Settlement scoring** (mewo2's `cityScore`; Azgaar) | three terms — `sqrt(flux)`, edge penalty, spacing — and you have plausible town siting | needs flux, which we do not have yet |
| **Lowest bridging point** | the strongest single rule in settlement geography: the furthest-downstream crossable point of a river is where the important town grows | requires rivers first |

### Structure, gating and authored feel

| technique | good at | fails at |
|---|---|---|
| **Wave Function Collapse / model synthesis** | local texture consistency inside a region whose boundary and role were decided elsewhere | see §3. It is our headline rejection |
| **Spelunky's solution path** | the guarantee is a *contract on the interface between cells*, established before content exists — no test, no retry | needs a template library |
| **Dormans' cyclic generation** | mission graph first, space grown to fit it; explicitly closes open connections so the space cannot short-circuit the mission | graph grammars are a lot of machinery for one town |
| **Cogmind-style prefabs** | seeding (before generation) vs embedding (after); prefabs carry their own connectivity instructions | hand-authored content, which is the point |
| **Nystrom's bounded attempts** | *fixed number of attempts, variable outcome* — the loop always terminates and the room count is what varies | — |
| **Repair over rejection** | flood fill, find the violation, edit toward validity. Monotone, so it terminates | needs a violation you can localise |
| **Townscaper** | genuinely beautiful, and the method is a masterclass | does not transfer. Its organic quality lives in the *irregular relaxed quad grid*, not the solver. We have square cells and fixed-size sprites; there is nothing to deform |

---

## 2. The recommendation

Opinionated, per problem. Every one of these is a change to `make_world.py`.

### 2.1 Streets — Dijkstra over a cost field, with a road-reuse discount

**Take:** Emilien's road-reuse weight, plus Wolverson's door→nearest-road
accretion. **Refuse:** the L-system, the tensor field, the Voronoi.

We already have `carve_road`, and it is a greedy one-step-lookahead walk that
scores neighbours by `distance + climb + jitter`. It is a hill-climber, not a
path-finder, and it can only produce the road it happens to stumble into.
Replace it with a real Dijkstra over an explicit cost field:

```
cost(cell) = 1
           + slope_penalty  * |Δelevation|
           + water_penalty  * is_water        # ~1000, except at chosen fords (~3)
           + building_penalty * is_roof
cost(cell) *= 0.1  if the cell is already road
```

That last line is Emilien §4.3 and it is the single highest-value line in this
entire document. It makes the path-finder prefer to run along an existing lane
and branch off late, which is precisely how village roads look and is why our
current five radial spokes read as spokes. The rest of the cost field is what
makes a road bend around water instead of bridging it, and climb a pass instead
of a face — which `carve_road`'s docstring already claims and its greedy walk
cannot deliver.

Then: **every building's door gets an A\* to the nearest road tile, and the
resulting path is added to the road set** so the next door can path to *it*.
That accretion, thirty lines, is what turns a trunk road into a network of
lanes. It is also what makes "the door opens onto somewhere you can walk" true
by construction rather than by a test — and given that a test which could never
pass is how the town spent weeks as a paved crossroads, construction is worth a
great deal here.

A market is not a special case: it is a cell where several lanes meet, widened
by two. Widening at junctions is a post-pass over the road set, not a plan.

### 2.2 Plots — a BFS distance transform from the street, then burgage widths

**Take:** the offset-strip idea from Vanegas, computed as a grid BFS. **Refuse:**
the straight skeleton, Voronoi, axis-aligned BSP.

The skeleton method's guarantee is that each face of the skeleton touches
exactly one input edge, so every plot has frontage topologically rather than
probabilistically. On a *tile grid* that guarantee has a much cheaper form:

> **Multi-source BFS from every street tile.** Every cell within depth ≤ `d` of
> a street is the buildable strip. The core beyond it is backland — garden,
> yard, back lane, woodpile. Integer-exact, O(cells), trivially deterministic,
> no floating-point geometry, no robustness problems, about twenty lines.

Then walk each frontage laying out plots, and this is where the urban-history
literature earns its place. Real medieval plots are **startlingly regular in
width and irregular in depth**, and getting that backwards is the commonest way
a fantasy town looks wrong. The measured numbers:

| | real | at our 3 ft/tile ruler |
|---|---|---|
| unit of layout | 1 perch = 16.5 ft ≈ 5 m | **5.5 tiles** |
| typical width | 2–3 perches (10–15 m) | **11–16 tiles** |
| typical depth | 12 perches (60 m) | **66 tiles** |
| width : depth | about **1 : 6** | — |
| Edinburgh, measured | modal width 7.7 m, with subsidiary peaks at **¾ (5.8 m) and 1¼ (9.6 m)** of it | **8.4 tiles**, peaks at 6.3 and 10.5 |
| Conzen's depth typology | shallow ≤ 4, medium 4–7, deep > 7 (length : width) | — |

**Do the arithmetic before copying the numbers.** Our town is 44 tiles across; a
real burgage plot is 66 tiles deep. One authentic plot is longer than the whole
town. So take the *shape* of the distribution and scale the magnitude:

- keep the **quantised, multi-modal width** — sample from
  `{0.75, 1, 1, 1, 1.25, 1.5} × unit_width`, not from a uniform or a Gaussian,
  and occasionally emit a "pair", two plots sharing a one-tile alley. That
  single distribution choice is most of the difference between "medieval town"
  and "procedurally generated", and it costs one line;
- set `unit_width` per plan unit at **5–7 tiles**, which at 3 ft a tile is a
  15–21 ft frontage — a genuinely narrow medieval townhouse, and coincidentally
  about the width our existing buildings already are;
- **compress the depth ratio to roughly 1 : 3**, giving 15–20 tile plots. The
  1 : 6 ratio is unreachable at our scale and chasing it would put the back
  fence of one plot through the far side of the town.

Two more rules worth implementing because they are the ones nobody implements:

- **Corners taper and interlock.** Plot *width* stays constant along a frontage
  and plot *depth* shrinks toward the block corner, the two frontages' rear ends
  meeting in a stair-step. This is observed at Bridgnorth and Ludlow, and it is
  also exactly what the skeleton bisector produces at a convex corner — the
  historically correct answer and the geometrically principled one agree.
- **Leftovers are never holes.** Any strip that fails to front a street becomes
  a garden, a midden, a woodpile, a back lane. Parish & Müller *discard* these
  and leave gaps; that is a documented flaw, not a simplification.

And unconditionally: **a sliver-merge pass.** Every method in this space needs
one. Any plot below `A_min` unions into the neighbour with which it shares the
longest edge.

### 2.3 Buildings — asymmetric setback and six archetypes

**Take:** Citygen's per-edge setback and Martin Evans' additive footprints.
**Refuse:** CGA shape grammars.

Two changes, both small, both large in effect:

1. **The setback is asymmetric.** Zero at the street, deep at the rear. A
   uniform inset makes every building a shrunken copy of its lot, which is the
   classic tell. Medieval buildings sit *on* the frontage with the garden
   behind, so this is both correct and cheap.
2. **Six archetypes, not one rectangle.** Rectangle, L, T, U-with-courtyard,
   rectangle-plus-lean-to, long-hall — each parameterised by two to four
   integers and chosen by lot aspect ratio and building function. The additive
   construction (seed a rectangle, attach further rectangles at 90° with
   decaying probability) literally models accretion, which is how these
   buildings grew.

Ranked by what actually reads at 57 cells on screen:

| rank | variation | why |
|---|---|---|
| 1 | alignment to the street | the eye reads street-relative alignment instantly |
| 2 | footprint area and aspect spread | driven by plot width, which §2.2 already varies |
| 3 | **roof material** | `roof_thatch`, `roof_slate`, `roof_pantile` are drawn, in the atlas, and unused. Nearly free |
| 4 | setback jitter | one or two buildings pushed back a tile, one projecting |
| 5 | archetype | L vs rectangle |
| 6 | outbuildings | per-plot "repletion" — some plots hold a house and a shed and a wall, some a house and an empty garden, one is cleared |

That repletion parameter is Conzen's **burgage cycle** — backland fills in over
time and is periodically cleared to "urban fallow" — and it is the cheapest way
to make twenty-one buildings look like they were built across two centuries
rather than in one pass.

And **the buildings must stop being solid roof blocks.** Seven of them today are
a rectangle of impassable `roof` with a door cell that opens into a wall. The
house already proved the whole interior vocabulary — cap-and-face walls, four
floor materials, a sealed footprint, an `indoors` rect. #77 is right that the
fix is a `data/content/buildings.json` catalogue; this document only adds that
the catalogue should carry the footprint archetype and the roof material, so
that "the tavern" is a *kind* of shape and not only a name.

### 2.4 Rivers — flow accumulation, and we may already have the hard part

**Take:** mewo2's flux accumulation and Amit's monotonicity argument. **Refuse:**
hydraulic erosion.

The standard grid pipeline is priority-flood → D8 flow direction → flow
accumulation → threshold. Benchmarked in pure Python at 1000² that is about 29
seconds, of which the depression fill is half.

But look at `build_fields`. Elevation is multiplied by an `edge` term that ramps
it down over the outermost seven tiles, and pushed up by `reach²` toward the
sector characters. **Our elevation is already close to monotone-decreasing
toward the rim ocean**, which is the property Amit engineered deliberately by
setting elevation to distance-from-coast. If we tighten that into a guarantee —
blend a small radial term so the field never increases outward — then:

> every downhill walk from anywhere provably terminates in the rim ocean, and
> the entire depression-filling problem is deleted.

What remains is: pick springs (high tier, high moisture), walk steepest descent,
merge on collision, accumulate flow, `width = sqrt(flow)`. About 3 seconds at
1000², and it **cannot** produce a river that stops in a field — which is the
characteristic failure and the one that would embarrass us.

The price is that rivers become radial spokes running outward from the centre.
For a world whose entire structure is rings and sectors around a central town,
a hub town at the confluence of every river is not a bug. It is the shape the
design already has.

Then, and only then:

- **Fords and bridges are chosen before roads are pathed, not discovered
  during.** Score every river cell for crossability (narrow, low flux, gentle
  banks on both sides, not a delta), pick the crossings, and set
  `cost = 3` there against `cost = 1000` for the rest of the river. Roads then
  bend to reach the ford, which is the historically correct causality — the road
  goes to the crossing, the crossing does not appear where the road went.
- **The town's site becomes explicable.** The lowest bridging point of a river —
  the furthest-downstream cell where a crossing is feasible — is where the
  important town goes, because it is simultaneously reachable by road from both
  banks and the head of navigation. We do not need to move our town, which is
  fixed at the centre, but we should *place the river so the town sits at its
  lowest bridging point*, which is the same statement run backwards and is
  perfectly deterministic.

Skip hydraulic erosion. It costs minutes in pure Python and, by its own
practitioners' accounts, produces valleys rather than rivers — you still need
flow accumulation afterwards.

### 2.5 The boundary — generate the cage first, then fill it

This is the one where the game-design answer and the engineering answer are the
same answer, and where the current architecture is already most of the way
there.

**Generate the perimeter as a closed curve before any town exists.** Lay the
river first, choose the two river-facing sides, run the farmland fence as a
polyline from river-end to river-end, and punch exactly one gate in it. Only
then fill the interior with streets and plots. This is Dormans' mission-before-
space and Spelunky's solution-path-first: the constraint is the axiom of the
grammar, not a filter on its output. Enclosing a town you have already built is
the version that fails.

**Make crossability a property of the traversal graph, not an inference from
tile types.** Unexplored 2 does exactly this: where a river is uncrossable, the
adjacency simply is not created. Then a shallow-water art variant added six
months from now cannot silently open a hole in the boundary.

**The gate needs no new code.** `World.gd::_shut()` already reads
`blocks_until_tag` off the interactable catalogue and `walkable()` already
returns false, which is how the front door gates the tutorial. The children's
leaf wall is the same mechanism at a larger radius, gated on
`close_town_anomalies` instead of Grit. What is missing is not the gate — it is
the fence and the river that make the gate the only way through. And the props
for that (`fence_rail`, `field_gate`, `leaf_wall`) were added to `tiles.json`
today and have `density: 0.0`, so nothing places them.

**Prove it with three flood fills, not one.** We already have `reachable()` and
it already fails the build on unreachable anchors and on an unsealed house. Add:

| assertion | meaning | the failure it catches |
|---|---|---|
| gate-closed BFS from spawn ∩ outside = ∅ | you cannot leave | a one-tile gap in the fence |
| gate-open BFS from spawn ∩ outside ≠ ∅ | you *can* leave once the gate opens | the "provably enclosed" town that is also a prison — the assertion everyone forgets |
| gate-closed BFS reaches every door, NPC and shop | the town is usable while shut | a building walled off inside its own town |

Plus one more worth having: **the gate should be an articulation point** of the
walkable graph. Removing it disconnects town from world. Checking that directly
catches "there are two gates and you only knew about one".

Three hazards to write down before they bite:

- **The BFS must use the player's real movement relation.** #84 proposes
  eight-way movement. On a diagonal-capable grid a one-tile river is crossable
  at any kitty-corner pinch. Either forbid corner-cutting between two blocked
  orthogonals or make every river two tiles wide, and verify by calling the same
  predicate the movement code calls.
- **Every non-walk traversal is an edge too.** #39 proposes items that change how
  you move. Each is an edge type and each must be in the relation or explicitly
  excluded with a comment.
- **"Outside" is a set you can reach, not "the map edge."** Define it as the
  component containing a known far landmark and assert non-membership.

**Repair, do not reject.** When the enclosure assertion fails, the BFS already
holds the escape path — widen the river or extend the fence at the first
offending cell and re-run. Each repair strictly shrinks the escape set, so it
converges. Cap the loop, fall back to a canned perimeter, and *log which
predicate failed*. Dwarf Fortress ships `[LOG_MAP_REJECTS:YES]` for exactly this
reason, and its documentation warns that tightening rejection parameters can
produce "endless rejections". A generator whose worst case is a hang is worse
than one whose worst case is an ugly town.

### 2.6 Authored feel — irregularity has to have a cause

The best statement of the problem is Kate Compton's ten thousand bowls of
oatmeal: every bowl is mathematically unique and the user sees oatmeal.
Perceptual differentiation is the metric, not variety. And her diagnosis of what
fixes it is the actionable part:

> *"Humans seem to like perceiving evidence of process and forces, like the
> pushed up soil at the base of a tree, or the grass growing in the shelter of a
> gravestone."*

**The reason regularity reads as generated is not that it is regular — it is
that it is uncaused. Uniform jitter is equally uncaused.** So:

- **Wear paths.** Run Dijkstra between every door pair, the well and the gate;
  the most-trafficked cells become packed dirt. Cheap, and it reads as decades
  of use. It is also the single best fit for `AESTHETIC-EDA.md` §"evidence of
  use", which the house has and the town does not.
- **Regularity where a human would have imposed it.** Crop rows *should* be
  perfectly parallel — a farmer made them. Buildings *should* align to a street.
  The generated-looking failure is regularity where nobody would have
  straightened anything: identical tree spacing, evenly spaced lampposts.
  `stock_town` currently places four lamps at `(-13, -5, 5, 13)`.
- **Plan units.** Conzen's key observation is that a town is a patchwork of
  areas each internally regular and mutually misaligned, one per phase of
  growth. Three to six plot series with different unit widths, depths and
  orientations, meeting at visible seams, is a generator structure and not just
  a description.
- **A fringe.** The town edge should not look like the town centre — larger
  irregular plots, orchards, fewer road crossings. Watabou's `filterOutskirts`
  is forty lines that probabilistically deletes buildings far from populated
  edges, and it does a disproportionate share of the "looks like a real town"
  work.
- **Set pieces, sparingly.** Diablo's rule is at most one set piece per level.
  Three to five hand-authored landmarks — the gatehouse, the well square, the
  mill on the river — and everything else quiet. Compton again: not everyone can
  be a main character.
- **The gate is the town's organising axis.** We have exactly one, which is the
  strongest asymmetry available for free. Main street runs from it. The market
  is near it. A town that is legibly *oriented* cannot read as sampled.

And one thing from the Great Plateau, which is the canonical enclosed tutorial
area: **the cage must be legible from inside.** The player should be able to
stand in the market and see water on two sides and fence on the third. A
boundary you can only discover by walking into it feels like an invisible wall
even when it is a river. Then the guard at the gate is not a wall — he is the
only interesting thing about the boundary, and when he steps aside that is a
progression beat rather than a door unlocking.

---

## 3. What to reject, and why

### Wave Function Collapse. Emphatically.

WFC is the most popular technique in this space and it is wrong for us in four
independent ways, any one of which would be sufficient.

**It fails much more than its reputation suggests.** Paul Merrell — whose Model
Synthesis (2007) WFC is a rediscovery of, a fact Gumin credits in his own README
— published a direct comparison. His table is the most concrete indictment
available:

| input | size | model synthesis | WFC | **WFC success rate** |
|---|---|---|---|---|
| Summer | 100×100 | 3.7 s | 116 s | **0.2 %** |
| Summer | 200×200 | 25 s | — | **0 %** of 1,000 |
| Castle | 100×100 | 0.6 s | — | **0 % of 10,000 trials** |
| Knot Dense | 100×100 | 0.31 s | 16 s | 2.7 % |

Ten thousand attempts, zero successes. Gumin's own README concedes the
underlying reason — determining whether a tileset admits a solution is NP-hard —
and then says contradictions happen "surprisingly rarely", which is a claim
about *his* tilesets, not about ours, and one we could only test by building the
thing.

**It cannot express any constraint we actually care about.** "Every building has
a door reachable from the street," "the street reaches the gate," "the market
adjoins the main road," "there is exactly one tavern," "no orphan plots." All
global; all outside WFC's range. Karth & Smith re-encoded WFC in a real
constraint solver and added a *single* trivial global constraint; with WFC's
restart-only strategy it could not find a solution within a minute, while the
same solver with backtracking resolved it quickly. Gumin says the limitation
himself in information-theoretic terms: *"correlations of tiles in easy tilesets
quickly fall off with a distance."* That is not a bug to be fixed. It is what a
purely local model is.

**Restart-on-contradiction fights determinism-from-seed.** A generator that
restarts N times before succeeding is deterministic in principle, but N depends
on the tileset in ways nobody can bound, and any tileset change silently changes
it. We already require `md5sum` equality across two runs as a build gate.

**And it is the worst possible fit for the Tiled round trip.** This is the
argument the literature does not make because the literature does not have a
designer editing the output. WFC produces a *global solve*: change one tile's
adjacency rule, or one input pattern, and the entire output is different
everywhere. Our overrides are addressed by cell. A designer who has spent an
afternoon dressing the market would lose all of it the first time anyone touched
the tileset. §5 makes this general.

Note what the flagship commercial WFC user actually does. Caves of Qud
**segments the map by other means first**, runs WFC *inside* the segments, and
**adds doorways and connections afterwards to ensure connectivity**. Brian
Bucklew's two named problems are "the algorithm generates homogeneous output
lacking inherent structure" and detail overfitting. WFC is the middle third of a
sandwich, and the two slices of bread are the parts we do not have.

**Where it would legitimately help us, if anywhere:** decorating a region whose
boundary and role were decided elsewhere — building interiors, ground-cover
transitions, rubble. And even there, at our scale, a hand-written Wang-tile
autotiler is simpler, always terminates, and looks the same. We already have
autotiling.

### Tensor fields

Skip. They are an interactive design tool; without a human painting the field
you are guessing at basis parameters, and the smooth curvature you pay 1,500
lines for is invisible at 32 px tiles and 7.5 tiles of viewport.

### The straight skeleton

The right idea, the wrong medium. On a continuous polygon it is the only method
that *guarantees* frontage rather than filtering for it — but it is
O(n² log n) in practice, its numerical robustness is a research topic, and the
pure-Python library available is described by its own maintainer as incorrect
for some inputs. **The grid already has an exact, integer, twenty-line
equivalent: a BFS distance transform from the street cells.** Use that.

### Voronoi for plots

Watabou's own assessment of his own generator is the whole case: *"too many
triangular buildings."* A Voronoi cell is defined by proximity to a seed, not by
adjacency to a line, so there is no frontage concept in the diagram at all. Fine
for districts if we ever have enough of them; never for plots.

### Axis-aligned BSP

Right for dungeon rooms, where rectilinearity is diegetic. Wrong for a town,
because the splits align to the world axes rather than to the street, and the
eye reads street-relative alignment instantly. OBB splitting is the same
algorithm with one change and is strictly better.

### Hydraulic erosion

60 seconds to 30 minutes in pure Python, and it gives you valleys, not rivers.
Amit tried it and abandoned it. If the valleys look wrong after rivers land,
carve them from the river network directly — milliseconds, and exact control.

### Townscaper

Beautiful and inapplicable. Its organic quality lives in the irregular relaxed
quad grid, and its tiles are deformable corner meshes that exist to absorb that
irregularity. We have square cells and fixed-size sprites; there is nothing to
deform. The one transferable idea, generalised: **push irregularity into the
substrate, not the solver** — which on our grid means non-axis-aligned streets,
varied plot widths and jittered setbacks, not a cleverer tile solver.

---

## 4. How this fits what already exists

Nothing above throws anything away. Specifically:

| what we have | how it is used |
|---|---|
| two continuous noise fields | unchanged. `biome()` stays blind to sector — that decision is right and the rivers do not touch it |
| radial rings, angular sectors | **the reason the radial-river result is acceptable.** A monotone-outward elevation field is a small tightening of `build_fields`, not a new structure, and it makes rivers free |
| `elev` as a first-class plane | already exported byte-per-cell. Flow accumulation needs nothing new |
| `carve_road` | replaced by Dijkstra over a cost field. Same signature, same call sites, ~60 lines |
| `reachable()` | already a build gate. Grows two more assertions and an articulation-point check |
| `terrace` / `cliff_plane` | unchanged. Cliffs remain a second kind of boundary and are already provably unwalkable |
| `blocks_until_tag` in `World.gd::_shut()` | the town gate, with **no code change** — a catalogue entry and a placement |
| `stamp_town` | the one function that is genuinely rewritten. Street pass → BFS offset → plot series → footprints → doors |
| `stock_town` | keeps its job but stops placing lamps at fixed offsets; props hang off plots and junctions |
| deterministic seeding | see below — this is the part that must change *before* the world grows |

### Three things that must change in `make_world.py` regardless

**1. Per-feature seeding, before anything else.** There is one RNG stream, so
changing how many draws an early pass makes reshuffles everything after it —
fixing `stamp_town` moved the anomalies, as #76 records. Vanegas hit the same
problem and prescribes the same fix: **derive child seeds by hashing before
recursing.** `rng_for("river", i)`, `rng_for("plot", block_id, n)`. Then a change
to plot subdivision cannot move a mountain, and — the part that matters here —
cannot move a hand-placed barrel either. This is a prerequisite for the staged
plan, not a nicety.

**2. numpy, or a smaller world.** 16.3 s at 256² is roughly 4 minutes at 1000²,
and the noise fields are already the dominant cost. numpy is installed, and it
is 6–12× on the field passes. The `Noise` docstring's "runs anywhere with
nothing but PIL" is a real commitment and worth keeping if we can; but if the
world grows to #76's scale without it, the generator becomes something you run
and then go and do something else. Note the one counter-result: **do not try to
vectorise a depression fill** — the numpy version benchmarked 10× slower than
the pure-Python heap and did not converge. Priority queues do not vectorise.

**3. Buildings become placements, not painted tiles.** #77 already says this and
this document supports it for a second reason: an object in a `buildings` layer
survives the round trip with its identity, follows the generator until dragged,
and stays where it is dragged. A rectangle of `roof` painted into the base layer
is destroyed wholesale by the next export.

---

## 5. The hand-editing constraint, which the literature ignores

Every source above assumes the generator's output is the final artefact. Ours is
not: `docs/MAP-EDITING.md` promises that hand edits survive regeneration, and
that promise is the reason to prefer some techniques over others *independently
of how good their output is*.

The mechanism is a base layer that is thrown away and re-seeded, plus overrides
addressed **by cell**. So the question to ask of any technique is: **when a
parameter changes, how much of the output moves?**

| | how much moves when you change one thing | edits survive? |
|---|---|---|
| **Local / incremental** — accretion, A* with road reuse, BFS offset, per-plot footprints | only what is near the change. Change the tavern's archetype and the tavern changes | **yes** |
| **Recursive with hashed seeds** — OBB splitting, plot series | only the subtree below the change | **yes**, if the seeds are hashed rather than drawn from one stream |
| **Global solves** — WFC, tensor fields, Voronoi over the whole town, one RNG stream | everything, everywhere | **no** |

That table is the real argument against WFC for this project, and it is stronger
than any of the arguments in §3, because it does not depend on WFC being bad at
anything. A global solve is simply incompatible with by-cell overrides.

Three practical consequences:

- **Per-feature seeding is load-bearing** for editing, not only for debugging. It
  is what converts "recursive subdivision" from a global solve into a local one.
- **Prefer techniques whose output is describable as objects.** A building
  placement, a road polyline and a plot rectangle can all live in Tiled object
  layers, where they are draggable, retypable, and *pinned by dragging*. A
  Voronoi tessellation cannot.
- **Do this before the first serious editing session.** #76 makes the same
  observation about chunking and it applies doubly here: the `edits` layer is
  currently empty and no props are hand-placed. That stops being true the first
  afternoon the designer spends in Tiled, which makes this close to a
  now-or-much-harder decision.

---

## 6. A staged plan

Ordered by improvement per unit of work, given that a town exists today and #76
is coming.

| stage | work | why here |
|---|---|---|
| **0. Make the town's buildings real** | Interiors instead of solid `roof`; use the three unused roof materials; vary the footprint. Half a day — **in progress as this is written** | Seven buildings had doors that opened into a wall, and three roof materials were drawn and unused. The cheapest visible improvement in the whole document, and it needs no research at all |
| **1. Per-feature seeding** | `rng_for(name, *keys)` hashing `md5(seed, name, keys)`. A day | Prerequisite for everything after it and for #76. Until it lands, every change below reshuffles the world and strands hand edits |
| **2. Rivers** | Tighten `build_fields` to monotone-outward; springs, steepest descent, flux, `sqrt(flux)` width; score fords. ~150 lines, ~3 s | Unblocks the town boundary (#77), unblocks bridges, and gives the world the structural feature it most conspicuously lacks — there are three bridge cells in 65,536 |
| **3. Roads by Dijkstra with reuse** | Replace `carve_road`'s greedy walk. ~60 lines | Immediately fixes "roads are five radial spokes", makes roads bend round water and cross at fords, and is the smallest change with the largest visible effect |
| **4. The boundary and the proof** | River on two sides, fence polyline on the third, one gate; three flood-fill assertions plus articulation point; place `fence_rail` / `field_gate` / `leaf_wall`. ~200 lines | This is #77's blocker and the props landed today. Do it *before* the town is re-laid, per §2.5 — enclose first, fill after |
| **5. Plots and named buildings** | BFS offset, plot series with burgage widths, corner taper, six archetypes, `buildings.json`. The big one, ~400 lines | The full #77. Worth doing after 1–4 because it wants the river, the roads and the boundary to exist to lay out against |
| **6. Authored feel** | Wear paths from door-to-door Dijkstra; plan units; the outskirts filter; per-plot repletion. ~150 lines | Cheap per unit of effect, but only once there is a town for it to weather |
| **7. numpy on the field passes** | Only if #76's scale lands and generation time hurts | 6–12× where it matters, and a measured non-answer where it does not |

Two notes on sequencing. **Stage 4 must precede stage 5**, because enclosing a
town you have already built is the version that fails — the constraint has to be
the axiom, not a filter. And **stage 1 must precede everything**, because
without it each of stages 2–6 silently reshuffles the whole world and the
designer's first Tiled session is unrecoverable.

---

## 7. Sources

### Street networks

- [Parish & Müller, *Procedural Modeling of Cities* (SIGGRAPH 2001)](https://cgl.ethz.ch/Downloads/Publications/Papers/2001/p_Par01.pdf) · [tmwhere's reformulation](https://www.tmwhere.com/city_generation.html) · [t-mw/citygen reference implementation](https://github.com/t-mw/citygen)
- [Chen et al., *Interactive Procedural Street Modeling* (SIGGRAPH 2008)](https://www.sci.utah.edu/~chengu/street_sig08/street_sig08.pdf) · [ProbableTrain/MapGenerator](https://github.com/ProbableTrain/MapGenerator) · [Martin Evans on tensor-field roads](https://martindevans.me/game-development/2015/12/11/Procedural-Generation-For-Dummies-Roads/)
- [Watabou, Medieval Fantasy City Generator](https://watabou.itch.io/medieval-fantasy-city-generator) · [TownGeneratorOS source, GPL-3.0](https://github.com/watabou/TownGeneratorOS) · [Village Generator devlog](https://watabou.itch.io/village-generator/devlog/613514/plans) · [his own "rather arbitrary" note](https://watabou.itch.io/medieval-fantasy-city-generator/devlog/1579/some-answers-and-comments)
- [Emilien et al., *Procedural Generation of Villages on Arbitrary Terrain* (2012)](https://perso.liris.cnrs.fr/egalin/Articles/2012-villages.pdf)
- [Lechner, Watson & Wilensky, *Procedural City Modeling* (2004)](http://ccl.northwestern.edu/2004/ProceduralCityMod.pdf)
- [Runions et al., *Modeling trees with a space colonization algorithm*](http://algorithmicbotany.org/papers/colonization.egwnp2007.html)
- [Wolverson, Rust Roguelike Tutorial ch. 47 "Making the town"](https://bfnightly.bracketproductions.com/rustbook/chapter_47.html) · [town.rs, 264 lines](https://github.com/amethyst/rustrogueliketutorial/blob/master/chapter-47-town1/src/map_builders/town.rs)

### Plots and footprints

- [Vanegas et al., *Procedural Generation of Parcels in Urban Modeling* (Eurographics 2012)](https://www.cs.purdue.edu/cgvlab/papers/aliaga/eg2012.pdf)
- [Kelly & McCabe, *Citygen* (GDTW 2007)](https://www.citygen.net/files/citygen_gdtw07.pdf) · [thesis](http://www.citygen.net/files/Citygen-Thesis.pdf)
- [Martin Evans, *Building Footprints*](https://martindevans.me/game-development/2016/05/07/Procedural-Generation-For-Dummies-Footprints/) · [*Lots*](https://martindevans.me/game-development/2015/12/27/Procedural-Generation-For-Dummies-Lots/)
- [Müller et al., *Procedural Modeling of Buildings* (SIGGRAPH 2006)](https://dl.acm.org/doi/10.1145/1141911.1141931)
- [Andrew Manq, parcel subdivision walkthrough](https://andrewmanq.github.io/2020-02-22-parcel-subdivision/)

### Medieval town morphology

- [Whitehand, *Conzenian Urban Morphology and Urban Landscapes* (2007)](http://spacesyntaxistanbul.itu.edu.tr/papers/invitedpapers/Jeremy_whitehand.pdf)
- [Tait, *Configuration and dimensions of burgage plots in the burgh of Edinburgh* (PSAS 136, 2006)](http://journals.socantscot.org/index.php/psas/article/download/9686/9653)
- [Haslam, *Town-plan analysis and the limits of inference: Bridgnorth and Ludlow*](https://jeremyhaslam.wordpress.com/wp-content/uploads/2009/12/bridgnorth-and-ludlow-town-plans.pdf) — the corner-interlock rule
- [Burgage (Wikipedia)](https://en.wikipedia.org/wiki/Burgage) · [Rods, poles and perches](https://alnwickcivicsociety.org.uk/2020/09/11/rods-poles-and-perches/)

### Rivers and terrain

- [Amit Patel, *Polygon Map Generation*](http://www-cs-students.stanford.edu/~amitp/game-programming/polygon-map-generation/) · [*Terrain from Noise*](https://www.redblobgames.com/maps/terrain-from-noise/) · [mapgen4](https://www.redblobgames.com/maps/mapgen4/)
- [Martin O'Leary, *Generating fantasy maps* (Wayback)](https://web.archive.org/web/2020id_/http://mewo2.com/notes/terrain/) · [mewo2/terrain source](https://github.com/mewo2/terrain)
- [Barnes, Lehman & Mulla, *Priority-Flood* (2014)](https://arxiv.org/abs/1511.04463) · [RichDEM](https://github.com/r-barnes/richdem)
- [Undiscovered Worlds: Rivers](https://undiscoveredworlds.blogspot.com/2019/02/rivers.html) · [Carving the rivers](https://undiscoveredworlds.blogspot.com/2019/02/carving-rivers.html)
- [Azgaar: River systems](https://azgaar.wordpress.com/2017/05/08/river-systems/) · [Confluences](https://azgaar.wordpress.com/2017/05/27/confluences/) · [Settlements](https://azgaar.wordpress.com/2017/11/21/settlements/)
- [Nick McDonald, *Procedural Hydrology*](https://nickmcd.me/2020/04/15/procedural-hydrology/) · [Job Talle, *Simulating hydraulic erosion*](https://jobtalle.com/simulating_hydraulic_erosion.html) · [Sebastian Lague, Hydraulic-Erosion](https://github.com/SebLague/Hydraulic-Erosion)
- [Génevaux et al., *Terrain generation using procedural models based on hydrology* (2013)](https://www.cs.purdue.edu/cgvlab/www/resources/papers/Genevaux-ACM_Trans_Graph-2013-Terrain_Generation_Using_Procedural_Models_Based_on_Hydrology.pdf)
- [Lowest bridging point](https://en.wikipedia.org/wiki/Lowest_bridging_point) · [Dry point](https://en.wikipedia.org/wiki/Dry_point)

### WFC and model synthesis

- [Gumin, WaveFunctionCollapse](https://github.com/mxgmn/WaveFunctionCollapse)
- [Merrell, *Comparing Model Synthesis and Wave Function Collapse* (2021)](https://paulmerrell.org/wp-content/uploads/2021/07/comparison.pdf) — the failure-rate table
- [Merrell, Model Synthesis](https://paulmerrell.org/model-synthesis/) · [thesis](http://graphics.stanford.edu/~pmerrell/thesis.pdf)
- [Karth & Smith, *WaveFunctionCollapse is Constraint Solving in the Wild* (FDG 2017)](https://adamsmith.as/papers/wfc_is_constraint_solving_in_the_wild.pdf)
- [Boris the Brave, *WFC tips and tricks*](https://www.boristhebrave.com/2020/02/08/wave-function-collapse-tips-and-tricks/) · [*Model synthesis and modifying in blocks*](https://www.boristhebrave.com/2021/10/26/model-synthesis-and-modifying-in-blocks/) · [*Constraint-based tile generators*](https://www.boristhebrave.com/2021/10/31/constraint-based-tile-generators/)
- [Bucklew, *Dungeon Generation via Wave Function Collapse* (Roguelike Celebration 2019)](https://www.youtube.com/watch?v=fnFj3dOKcIQ) · [notes](https://christianjmills.com/posts/dungeon-generation-via-wavefunctioncollapse-notes/)
- [Stålberg, *Beyond Townscapers*](https://www.youtube.com/watch?v=Uxeo9c-PX-w) · [How Townscaper Works](https://www.gamedeveloper.com/blogs/how-townscaper-works-a-story-four-games-in-the-making) · [Boris the Brave's grid walkthrough](https://boristhebrave.com/docs/sylves/1/articles/tutorials/townscaper.html)

### Structure, verification and authored feel

- [Shaker, Togelius & Nelson, *Procedural Content Generation in Games*](http://pcgbook.com/) — free. Especially [ch. 3, constructive generation](http://pcgbook.com/chapter03.pdf), [ch. 5, grammars and L-systems](http://pcgbook.com/chapter05.pdf), [ch. 12, evaluating generators](http://pcgbook.com/chapter12.pdf)
- [Kate Compton, *So you want to build a generator…*](https://galaxykate0.tumblr.com/post/139774965871/so-you-want-to-build-a-generator) ([mirror PDF](https://golancourses.net/2022f/wp-content/uploads/2022/09/kate-compton-oatmeal.pdf)) — the ten thousand bowls of oatmeal
- [Darius Kazemi, *Spelunky Generator Lessons*](https://tinysubversions.com/spelunkyGen/)
- [Boris the Brave, *Dungeon Generation in Diablo 1*](https://www.boristhebrave.com/2019/07/14/dungeon-generation-in-diablo-1/) — set pieces, minisets, bounded retry
- [Dormans, *Adventures in Level Design* (2010)](https://pcgworkshop.com/archive/dormans2010adventures.pdf) · [Unexplored's cyclic dungeon generation](https://www.gamedeveloper.com/design/unexplored-s-secret-cyclic-dungeon-generation-) · [Generating World Maps for Unexplored 2](https://www.ludomotion.com/blogs/generating-world-maps/) — crossability as a graph-edge property
- [Bob Nystrom, *Rooms and Mazes*](https://journal.stuffwithstuff.com/2014/12/21/rooms-and-mazes/) — bounded attempts, connectors, uncarving
- [Brian Walker, *Procedural level design in Brogue and beyond*](https://www.youtube.com/watch?v=Uo9-IcHhq_w) · [written analysis](http://anderoonies.github.io/2020/03/17/brogue-generation.html)
- [Josh Ge, *Map Prefabs in Depth* (Cogmind)](https://www.gridsagegames.com/blog/2017/01/map-prefabs-in-depth/)
- [Dwarf Fortress Wiki: World rejection](https://dwarffortresswiki.org/index.php/DF2014:World_rejection) — the documented rejection-sampling trap
- [Bazzaz & Cooper, *Literally Unplayable: On Constraint-Based Generation of Uncompletable Levels* (FDG 2024)](https://dl.acm.org/doi/10.1145/3649921.3659844) — unreachability as a first-class constraint
- [The Level Design Book: Gates](https://book.leveldesignbook.com/process/layout/typology/gates) · [Problem Machine, *At The Gates*](https://problemmachine.wordpress.com/2014/02/12/at-the-gates/)
- [Radiator Blog, *Open world level design: BotW*](https://www.blog.radiator.debacle.us/2017/10/open-world-level-design-spatial.html) · [Lessons of the Great Plateau](https://eliterev.wordpress.com/2017/03/16/breath-of-the-wilds-quiet-guidance-and-the-lessons-of-the-great-plateau/)
- [GDMC, the AI Settlement Generation Challenge in Minecraft](https://arxiv.org/abs/2103.14950) — settlement generation on a discrete grid, judged by humans. Nobody wins with L-systems; everyone wins with A* over a slope-weighted cost
