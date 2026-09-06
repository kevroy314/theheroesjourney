# Data reference

Everything the game *is* lives under `data/`. `Content.gd` merges files by
top-level key, so any file can be split or renamed. Adding content is adding
JSON; adding a *kind* of content is the only thing that needs code.

```
data/themes/*.json      palette, vocabulary, glyphs
data/rulesets/*.json    run-wide modifiers and hooks
data/movements/*.json   the movement library, grouped into purchasable packs
data/areas/*.json       the eight authored node graphs
data/echoes/*.json      the story, in fragments
data/dialogue/*.json    speakers, and the conversations they have
data/objectives/*.json  what you are trying to do, and how it is measured
data/content/           config, anomalies, items, trinkets, loot, spite,
                        achievements (the Wheel), rooms (the Mind Palace),
                        upgrades (traits), buffs, interactables, critters
data/world/*.json       the overworld, as packed tile planes — plus where the
                        interactables stand and where the house is
data/schema.json        the shape of all of the above — see Validation, below.
                        Not content: Content globs the subdirectories, not data/
```

Two of those directories are new enough to be worth saying out loud: a *kind* of
content gets its own directory when it has its own vocabulary and its own file
naming (`dialogue`, `objectives`), and lives in `content/` when it is a flat
catalogue the rest of the game references by id (`buffs`, `interactables`,
`critters`). Both are globbed the same way; the split is for people, not code.

## Modifiers — the schema everything shares

```jsonc
{ "key": "run.grit_mult", "op": "mul", "value": 1.12, "when": { "axis": "move" } }
```

**ops**, applied in this order: `set`, `add`, `mul`, `min` (floor), `max` (ceiling).

**conditions** (all listed must pass): `tier_gte`, `tier_lte`, `zone_gte`,
`phase`, `region`, `kind`, `axis`, `has_relic`, `hp_below`, `has_tag`,
`lacks_tag`.

**There is one condition language in this repo and this is it.** The same `when`
dictionary gates a modifier, an area node and a dialogue reply, evaluated by the
same `Rules.passes`, so `zone_gte` means the same thing on a trinket and in a
sentence somebody says to you. The single exception is a critter transition,
which asks about distances the run knows nothing about and so has a vocabulary
of its own — see Critters, below.

`"per_level": true` on a trait modifier multiplies by the purchased level.

`Rules.explain("key", ctx)` prints the base and every source that moved it.

## Hooks and effects

Rulesets and trinkets can fire effects on events:

```jsonc
"hooks": { "on_task_complete": [ { "type": "grit", "amount": 4, "silent": true } ] }
```

**hooks**: `on_run_start`, `on_area_enter`, `on_area_clear`, `on_task_complete`.

**effects**, all applied by `Game.apply_effects` and nothing else:

| type | carries | does |
|---|---|---|
| `grit` | `amount` | pays Grit into the run |
| `item` | — | a random item into the bag |
| `deadline` | `amount` in hours | moves the deadline |
| `log` | `text`, `kind` | says something in the toast strip |
| `buff` | `buff` (a buffs id) | applies a buff |
| `tag` | `tag`, optional `text`/`kind` | writes a run tag |

Any of them may carry `silent` to suppress the toast.

**One payer.** `Game.apply_effects` is the only implementation, so a ruleset
hook, a trinket, an interactable and a critter transition all make things happen
the same way, and adding a seventh verb is one `match` arm rather than four.
Dialogue and objectives speak a slightly wider vocabulary — see Story effects,
below — and hand the overlapping verbs straight back here rather than paying
them a second way.

`tag` is the case that shows why this is worth the discipline: the front door
being open is a run tag, so the gate needs no new field anywhere. `has_tag`
already reads them, and so can any screen.

## Movements

```jsonc
{
  "id": "pushup", "name": "Push-up", "axis": "move",
  "unit": "rep", "set": 5, "seconds_per_unit": 4,
  "scaling": ["Knee push-up", "Incline push-up", "Wall push-up"],
  "cue": "Hands under shoulders. Down slow, up slower."
}
```

- `axis` — one of `move · water · fuel · rest · mind · bond`, the six Wheel spokes.
- `set` — what "do a set" means for *this* movement. One node works for push-ups
  and for a five-minute walk because of this field.
- `seconds_per_unit` — drives the honesty gate. `units × seconds_per_unit` must
  elapse before Confirm unlocks, so a 5-minute walk really does gate 5 minutes.
- `scaling` — easier variants, offered on the task screen at no penalty.
- `confirm` — which gesture ends the task: `hold` or `tap_rapid`. Optional, and
  resolved most-specific-first by `HJGestures.for_movement`: the "always hold"
  accessibility setting, then this, then `confirm` on the **axis** in
  `achievements.json`, then `HJGestures.AXIS_DEFAULTS`. Hold for the soft and
  social axes, tap for the brisk ones — and a plank overriding to `hold` on a
  tapping axis is the case the per-movement key exists for. A gesture is a skin
  on the confirm, never a second way to finish a task.

Packs carry `cost` and `min_ring`, so the shop opens as you walk further out.

**The starter pack must keep at least one movement on every axis.** An anomaly
that asks for an axis with nothing unlocked would be unplayable; the self-test
asserts this.

## Areas

```jsonc
{
  "id": "the_house", "name": "The House",
  "intro": "…", "outro": "…", "truth": "unclear",
  "nodes": [
    { "id": "rep", "type": "task", "label": "The First Rep",
      "task": { "movement": "$choose:move", "units": 1 },
      "grit": 5, "next": ["set1"] },
    { "id": "set2", "type": "task", "loot": "common",
      "next": ["breadth", "depth"], "exclusive_next": true }
  ],
  "slots": [
    { "attach": "set1", "chance": 0.55,
      "table": [ {"type": "echo", "w": 3}, {"type": "cache", "grit": 8, "w": 3} ] }
  ]
}
```

**node types**: `task`, `free`, `threshold` (the way out), `echo`, `cache`,
`mirror`, `trinket`, `spite`, `warden`, `choice`.

`truth` on the area or anomaly is `true`, `false` or `unclear`. An anomaly is a
memory of a life adjacent to the player's, and this is the claim it makes about
itself — `AreaScreen` renders it above the intro, so it is the frame the player
is handed before they act. **Nothing checks the claim, and that is the point.**

**movement tokens**: `$choose:<axis>` asks the player to pick, `$same` reuses
their pick, `$other:<axis>` asks for a different one (falling back to the same
movement when the axis has only one unlocked — otherwise the node would be
uncompletable), or a literal movement id.

**units**: a number, or `$set` to read the chosen movement's set size.

`next` lists what a node opens. `exclusive_next` makes a fork close its
siblings — and downstream availability treats a *locked* predecessor as
satisfied, or everything after the fork would wait forever.

`grants` writes run tags when the node completes, which `has_tag` / `lacks_tag`
then read.

### Two kinds of fork

A node may carry `when`, the same condition dictionary a modifier carries. A
node whose `when` fails is closed off and counted as satisfied for everything
downstream — which is exactly the `exclusive_next` rule, arrived at from the
other direction. `select_next` is the flag that says who is doing the choosing:

| | who picks | how |
|---|---|---|
| `exclusive_next` | the player | they tap a branch; the siblings lock |
| `select_next` | the memory | `next` is tried **in order** and the first branch whose `when` passes opens |

**Every `select_next` fork needs a last branch with no `when` at all**, or a run
that matches none of them is offered nothing and the area dead-ends.

`slots` roll side nodes at generation time; `area.slot_bonus` adds guaranteed
extra rolls.

### Choice nodes — the survey

A `choice` node is the one card in the game that asks instead of demanding. It
takes the same run slot and the same screen as a task, and then throws away
everything a task screen exists to do: no movement, no timer, no plausibility
gate, no "I couldn't do this one". Those three exist to make a claimed push-up
believable, and there is nothing to make believable about a sentence you
finished about yourself. So a choice never goes through `Game.complete_task`.

```jsonc
{ "id": "muscle", "type": "choice", "label": "Your strength",
  "prompt": "I'm", "remember": "strength", "grit": 4, "next": ["nourish"],
  "options": [
    { "text": "weak of muscle",       "grants": ["self_weak"] },
    { "text": "strong of muscle",     "grants": ["self_strong"] },
    { "text": "unsure of my strength","grants": ["self_unsure"] }
  ] }
```

`prompt` is the sentence the memory starts and each option finishes it. An
answer lands in two deliberately different places:

| | where | lives for |
|---|---|---|
| `grants` on the option | run tags | this run — `has_tag` reads them immediately, which is how the survey ends in an action its own answers picked |
| `remember` on the node | `Meta.self_description[key]` | the save — tags die with the loop, and the point of asking is to still know next time |

An option may set `"input": "text"`, which renders a field as well as a button;
what the player typed is what gets remembered, instead of the tag.

**`grit` belongs on the node, not the option.** Paying differently for different
answers would price honesty, and the survey is the one place in this game that
must not do that. An option may override it, but only for a reason that is not
"this is the better answer".

## Themes

`colors` (bg, panel, panel_alt, line, text, muted, accent, accent_2, danger,
good, warn), `labels` (the game's whole vocabulary — grit, resolve, journey,
trinket, echo, streak, area), `glyphs` per node type, and `mountain_line`.

**Glyphs must stay in ASCII / Latin-1.** Godot's built-in font renders dingbats
and geometric shapes as tofu.

## Rooms (the Mind Palace)

```jsonc
{ "id": "gym", "name": "The Gym", "glyph": "»", "cost": 60, "screen": "gym",
  "adjacency": {
    "identity": { "desc": "+12% Grit from Move tasks",
                  "modifiers": [ { "key": "run.grit_mult", "op": "mul",
                                   "value": 1.12, "when": { "axis": "move" } } ] }
  } }
```

`screen` names the screen the room opens. Adjacency is evaluated on the grid
and folded into `Meta.active_modifiers()`.

### The reveal ladder

A price the player has no way to pay yet is noise, and a menu that shows the
whole game on the first run spoils it. So a room is either **revealed** — bought
or buyable, with its name and price — or **redacted**, a bar that says there is
more without saying what.

| key | meaning |
|---|---|
| `revealed_by_default` | visible from the first launch. The Atrium and the Hearth |
| `reveal_after` | the room whose purchase reveals this one |
| `starter` | placed on the grid from the start and cannot be moved. The Atrium |

`Meta.room_revealed()` is the whole rule: own it, be flagged, or have bought
what `reveal_after` names. **Reordering the unlock sequence is therefore a
content edit**, not a code change — the chain today runs Hearth → Stores → Gym →
Study → Identity → Workshop → Observatory.

## Buffs

A buff is a set of modifiers with an expiry and an icon. It is deliberately
**not** a second way to change a number: every effect in `buffs.json` is an
ordinary modifier, handed to `Rules` as a source alongside the ruleset, the
trinkets, the traits and the Palace, and resolved by the same five ops in the
same order. What is actually new here is expiry.

```jsonc
{ "id": "coffee", "name": "Coffee", "desc": "Faster on your feet for three hours.",
  "icon": "move", "hours": 3, "then": "coffee_crash",
  "apply_text": "Hot, and a little too strong.",
  "expire_text": "The coffee lets go of you.",
  "modifiers": [ { "key": "walk.step_time", "op": "mul", "value": 0.7 } ] }
```

| key | |
|---|---|
| `hours` | a **wall-clock** timer |
| `break_on` | a list of events; anyone may call `Buffs.trigger("outdoors")` |
| `then` | a second buff applied the instant this one ends |
| `icon` | a mark in `assets/icons`, drawn in the buff strip |
| `apply_text` / `expire_text` | what is said when it lands and when it lapses |

**Expiry is wall-clock and persisted**, because a run spans real days and
Android will kill a backgrounded app. Four hours away from a three-hour coffee
leaves exactly one hour of crash, whether or not the process lived to see it.

**A buff with neither `hours` nor `break_on` runs until something breaks it.**
The Boon of the White Room ends when you step outside, which is an event and not
a duration.

**`then` is settled from the expiry, not from now** — an app closed through the
whole of a coffee starts the crash on time rather than late. The chain is
bounded at `Buffs.MAX_CHAIN` because a `then` that loops would settle forever,
which no current data does and one typo would.

A buff the player cannot see is a number that changed for no reason, so
`HJUI.BuffStrip` draws `Buffs.active()` with a countdown on every screen that
wants it.

## Interactables

Something you can stand beside and act on. Two halves, deliberately apart:

| | lives in | says |
|---|---|---|
| the **catalogue** | `data/content/interactables.json` | what a *kind* of thing is: verb, price, effect |
| the **placements** | `data/world/overworld.json`, an `interactables` list | where they stand: `{ x, y, type, label? }` |

One catalogue entry serves every stove in the world, and the placement shape is
already what the Tiled round trip classifies as an object layer — so a designer
drags a door and retypes a stove as a counter with no code involved. See
[`MAP-EDITING.md`](MAP-EDITING.md).

```jsonc
{ "id": "front_door", "name": "The front door", "verb": "Open",
  "desc": "Shut, and it means it. Outside is a purchase.",
  "icon": "threshold", "reach": "adjacent", "cost_key": "interact.door_cost",
  "once": true, "spent_text": "It is already open.",
  "blocks_until_tag": "front_door_open",
  "effect": { "type": "tag", "tag": "front_door_open",
              "text": "The lock turns. The morning is out there." } }
```

- `reach` is `on` or `adjacent` — whether you stand on the cell or beside it.
- **`cost_key` names a config key, never a number**, so the price resolves
  through `Rules` and a trinket can bend it. Same treatment as `run.clear_bonus`.
- `effect` is one entry of the hook vocabulary above, applied by
  `Game.apply_effects`.
- `once` plus `spent_text` makes a thing that can only be done once.
- `blocks_until_tag` is how the front door is a **wall** rather than a button:
  `HJWorld.walkable()` returns false on its cell until that tag is set, so every
  path query respects it with no special case in the movement code. Grit buying
  the world is the lesson; making it a wall is what teaches it.
- `critter` names a species — see below.

## Critters

An animal that moves: a named state machine over the tile grid.
`scripts/game/Critters.gd` implements the goals and the conditions and knows
nothing about dogs or cats, so **the next animal is a data file**.

```jsonc
{ "id": "dog", "name": "the dog", "sprite": "dog", "start": "waiting",
  "states": {
    "waiting":   { "goal": "hold" },
    "following": { "goal": "approach", "target": "player",
                   "keep": 1, "trail": 2, "pace": 0.17, "recover": 10,
                   "say": "He gets up. He is coming with you." } },
  "transitions": [
    { "from": "waiting",   "on": "petted", "to": "following" },
    { "from": "following", "on": "petted", "to": "waiting" } ] }
```

**goals**: `hold`, `approach`, `retreat`, `wander`. A state's other keys tune it:

| key | |
|---|---|
| `target` | `player` or `home` — home is where the placement put it |
| `keep` | the distance it is trying to hold: a **ceiling** for `approach`, a **floor** for `retreat` |
| `trail` | aim at where the target was N moves ago. The lag is what makes a follower read as a companion instead of a mirror |
| `pace` | seconds per cell. `0.17` is exactly `walk.step_time`, the player's own, and anything larger is an amble. `critter.tick_seconds` is only how often the animal *reconsiders*, and is deliberately finer than any pace so no speed is quantised to it |
| `recover` | move attempts that may make no progress before it abandons the path and reappears at the edge of its band — what stops an animal wedged behind furniture being lost for the run |
| `restless` | how readily a `wander` gets up |
| `say` | one line, on entering the state |

**transitions** are an ordered list and **first match wins, so order is
priority.** `from` is a state id, a list of them, or `"*"`. `on` names an event
fired at the animal (`petted` today); a transition with no `on` is tested every
tick. `when` is a set of conditions — `dist_gte`, `dist_lte`, `held_gte`,
`stray_gte`, `has_tag`, `lacks_tag` — which is the one place in the data that
does *not* speak `Rules.passes`, because distance is a thing the run does not
know. `effect` is one entry of the hook vocabulary, so an escort that fails can
set a run tag without this system knowing what a quest is.

**Placement is not here.** An interactables record whose catalogue entry carries
a `critter` spawns one where it stands, reach follows the animal as it walks,
and `critter_event` (default `petted`) is what acting on it fires. That one key
is why petting the dog and petting the cat do opposite things with no branch
anywhere in the code, and why retyping the dog as a cat in Tiled is a data edit.

**The thresholds in each direction should differ.** The cat breaks off at 2,
runs to 6, comes back in to 4 and only sets off again at 5, so its resting band
is 3–4 and no two rules disagree at any distance. Matching the numbers produces
an animal that vibrates on the boundary.

## Dialogue

`data/dialogue/*.json` carries `speakers` and `dialogues`. A conversation is a
graph: each node is a few lines in order and then either a way on or a set of
replies.

```jsonc
{ "speakers": [
    { "id": "spite", "name": "Spite", "portrait": "spite", "accent": "warn" } ],
  "dialogues": [
    { "id": "spite_doorstep", "speaker": "spite", "start": "arrival", "once": true,
      "nodes": [
        { "id": "arrival", "lines": ["…", "…"], "mood": "wary", "replies": [
            { "text": "\"What do you want?\"", "goto": "want" },
            { "text": "Say nothing.", "goto": "silence" } ] },
        { "id": "want", "lines": ["…"], "mood": "wary",
          "effects": [ { "type": "objective",
                         "objective": "close_town_anomalies" } ],
          "replies": [ { "text": "\"Fine.\"", "goto": "gift" } ] },
        { "id": "gift", "lines": ["…"], "mood": "kind",
          "effects": [ { "type": "item", "item": "finder", "silent": true } ],
          "replies": [
            { "text": "\"I have been out past…\"", "goto": "smug",
              "when": { "zone_gte": 2 } },
            { "text": "Take it.", "goto": "end" } ] },
        { "id": "end", "lines": ["…"], "end": true } ] } ] }
```

**Node ids are unique within their own conversation, not across all of them** —
every graph is allowed an `end`. `Dialogue.problems()` checks that every
`start`, `next` and `goto` names a node in its own graph, which is the half of
the check the schema cannot see.

Two things it deliberately does not invent: a reply's `when` is the same
dictionary a modifier's `when` is, and a node's or reply's `effects` are handed
to `Objectives.apply_effects`, which delegates the paying ones straight back to
`Game.apply_effects`.

`mood` selects a portrait variant and is drawn from the Spite alter list.
`portrait` is a named seam: no art exists yet, and
`Dialogue.portrait_path()` turns it into
`assets/portraits/<portrait>_<mood>.png` the moment some does.

`once: true` means once across the whole save, not once per run — `seen` lives
in `user://dialogue.json`.

## Objectives

What you are trying to do, and whether it is done yet. The Hearth renders them.

```jsonc
{ "id": "close_town_anomalies",
  "title": "Close every anomaly in town",
  "desc": "Spite says the town is full of holes. …",
  "giver": "spite",
  "goal": { "type": "anomalies_in_ring", "ring": 0 },
  "reward": [ { "type": "resolve", "amount": 12 },
              { "type": "log", "kind": "good", "text": "The town is quiet. …" } ] }
```

**goal types**: `anomalies_in_ring` (with `ring`). One today; the list is
`vocabulary.objective_goals` and `Objectives.progress()` is its implementation.

Three things separate this from the Wheel, which is the closest existing system:

- an objective is **given**, not earned. Spite hands the first one over on the
  doorstep; nothing about your play unlocks it.
- **progress outlives the run.** The loop takes the world back and leaves the
  errand standing, which is the whole point of it.
- it is **displayed**. `active()` and `progress()` are a read API somebody else
  renders.

Progress is *derived*, not counted: `Objectives.note_closed()` records the cells
of every anomaly ever closed, harvested off `run_changed`. `run.anomalies_cleared`
is per-run and dies with the loop; `Meta.anomalies_closed` is a lifetime count
that cannot tell "the two in town" from "two out past the foothills". Neither can
answer "is the town finished", so the cells themselves are what is stored.

### Story effects

Dialogue lines, dialogue replies and objective rewards carry `effects`, a
slightly wider vocabulary than a hook's: `grit`, `deadline`, `resolve`, `item`,
`tag`, `objective`, `log`. `Objectives.apply_effects` is the one implementation,
and it hands `grit`, `deadline` and the unnamed `item` straight to
`Game.apply_effects` rather than paying them a second way. `objective` takes an
`objective` id and starts it.

## The world file

`data/world/overworld.json` is not loaded by `Content` — `World.gd` reads it,
and the file-side validator is the only thing that checks it. Two of its keys
are content rather than terrain:

| key | shape | |
|---|---|---|
| `indoors` | `{ x, y, w, h }` in cells | the footprint of the building the player wakes in, walls included |
| `interactables` | `[{ x, y, type, label? }]` | placements naming a catalogue entry |

`indoors` is what the Boon of the White Room is scoped to: walking is free
inside it and breaks on the first cell outside, and that same crossing unlocks
the Hearth and triggers the Spite encounter. It is a rectangle a designer can
edit rather than a rule derived from the floor material, so a second building is
a data change.

Both are **optional** and neither is in the schema's `world.required` list, so
deleting them loses them quietly — see the caveat in
[`MAP-EDITING.md`](MAP-EDITING.md#what-is-in-the-map).

Everything else — the packed planes, the regions, the anomalies, the props — is
[`MAP-EDITING.md`](MAP-EDITING.md)'s subject.

## Config keys

Every tunable number, with its base value in `data/content/config.json` and
every read through `Rules.value()`. `data/content/critters.json` carries a
`config` block of its own, merged into the same table.

```
run.grit_mult  run.resolve_rate  run.loop_keep  run.clear_bonus  run.repeat_falloff
streak.per_day  streak.cap_days
area.slot_bonus  area.reveal_sides  area.deadline_bonus_hours
task.partial_grit  task.min_seconds  task.hold_seconds  task.tap_count
task.tap_decay  task.time_gate_mult
loot.cache_mult  loot.echo_weight  loot.trinket_weight
shop.discount
spite.kind_weight
steps.reward_per_node  steps.multiplier_per_node  steps.starting_grant
steps.burn_penalty  steps.cost_mult
walk.step_time
interact.door_cost  interact.coffee_cost  interact.breakfast_cost
finder.range  finder.noise
critter.tick_seconds  critter.fidget_seconds  critter.path_budget
```

A key here is only legal if some `Rules.value()` call reads it — see
Vocabulary, below. `cost_key` and `scaled_by` are the two fields whose *value*
is a key resolved at runtime rather than a literal, so a key that appears only
there is still genuinely read.

## Validation

Everything above is a contract, and until recently nothing checked it. A typo in
a `when` clause, a `next` pointing at a node that does not exist, a modifier
`key` no code reads — each of those fails *silently*, and a rule that quietly
does nothing is indistinguishable from a rule that legally did nothing.

`data/schema.json` describes the shape of every content type. Two checkers read
it, with different reach:

| | `Content.validate()` | `tools/validate_data.py` |
|---|---|---|
| sees | the merged runtime view | the files on disk |
| runs | at load, every launch, including on a device | `python3 tools/validate_data.py`, and in CI |
| catches only it can | ids that collided while merging, a hand-dropped file on a device | anything needing the GDScript source, plus the world and tileset |
| needs Godot | yes | no |

Run the tool before you commit content. `./test.sh` fails on anything
`Content.validate()` reports, and so does CI; the CI `data` job also runs the
Python tool, which fails a bad edit in seconds instead of after the self-test
has downloaded an engine.

**Loud in the editor, fatal in CI, tolerant on a player's device.** A source
checkout gets `push_error` for every problem and a red self-test. An exported
build prints them and carries on — a player cannot fix our data file, and
refusing to start is a worse answer than a slightly wrong number.

### The three classes of check

1. **Keys.** Every required key present, and **no unknown keys** — that second
   half is the one that catches typos, because `"whn"` is only an error if
   unknown keys are errors. Keys beginning `_` are documentation and always
   allowed.

2. **References.** Every node `next` names a node in its own area; every slot
   `attach` likewise (it becomes the generated side node's `side_of`, which
   gates when the node opens); every `loot` names a table; every `movement` is a
   real movement or a legal `$` token; every Palace adjacency key names a room;
   every overworld region and anomaly points at a real area; every world
   `interactables` placement names a `type` in the catalogue; every catalogue
   `critter` names a species and every species' `sprite` has a PNG under
   `assets/sprites/`; every objective `giver` and dialogue `speaker` is a
   speaker; every prop `biome` is a real material *the world actually contains
   cells of*, and every prop `light` carries all three of `radius`, `color` and
   `flicker`.

   Two of these are checked by the Python tool alone rather than declared as
   schema `refs`, and the reason is worth knowing before you "tidy" them into
   the schema: `Content.gd` builds its id sets from `runtime` paths and does not
   merge a `critters` key, so a `refs` entry would resolve against an empty set
   and make the **in-game** validator reject every placement on a player's
   device. A check that is right on disk and wrong on a phone is worse than one
   that only runs on disk.

3. **Vocabulary.** Every modifier `op` is one of the five `Rules` applies, every
   `when` condition is one `Rules.passes` implements, every hook is one
   `Rules.hook` fires, and **every modifier `key` is one some `Rules.value()`
   call actually reads**. That last one needs a scan of the GDScript, so only
   the Python tool can do it.

The vocabulary lists in `data/schema.json` are not trusted on their own: the
Python tool re-derives each of them from the source it claims to describe — the
`match` arms of `Rules.passes`, `Game.use_item`, `Meta.wheel_met`, the keys of
`Main.SCREENS` — and fails if the two disagree in either direction. A schema
that has quietly stopped describing the code is worse than none, because it
validates confidently against the wrong words.

Modifiers and hooks are found by walking the data structurally rather than by
being declared per type, so a new content type that carries them is validated
for free instead of whenever someone remembers.

### Errors and warnings

`ERROR` means the data contradicts itself — a typo, a dangling reference, an
unknown key — and can be fixed inside `data/` alone. Fatal.

`WARN` means the data is consistent but something *outside* `data/` makes it
dead: a verb no code implements, a prop on a biome the world generator never
produces. Fixing those needs a code or art decision, so they are printed loudly
and do not fail the build. `--strict` promotes every warning to an error.

### Adding a content type

Add one entry to `data/schema.json` under `types`:

```jsonc
"quests": {
  "files":    { "dir": "content", "paths": ["quests[]"] },   // where it lives on disk
  "runtime":  ["quests[]"],                                  // where it lives on Content
  "required": ["id", "name", "giver"],
  "optional": ["desc", "modifiers"],
  "enum":     { "kind": "quest_kinds" },                     // a vocabulary list
  "refs":     { "giver": "npcs" }                            // an id set
}
```

Both checkers pick it up with no code change. A path is dot-separated:
`name` takes a field, `name[]` expands a list, `name{}` expands a dictionary's
values, and a bare `.` means the document itself. A `runtime` path's first
segment names a property on `Content`. Any type with an `id` contributes its ids
to a set named after the type, which `refs` can point at; `id_space` shares one
set between two types (anomalies and areas do this).

A vocabulary the engine implements as a `match` should also be reconciled
against the source in `tools/validate_data.py`, so it cannot drift.
