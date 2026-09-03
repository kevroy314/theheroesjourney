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
data/content/           config, anomalies, items, trinkets, loot, spite,
                        achievements (the Wheel), rooms (the Mind Palace),
                        upgrades (traits)
data/world/*.json       the overworld, as packed tile planes
data/schema.json        the shape of all of the above — see Validation, below.
                        Not content: Content globs the subdirectories, not data/
```

## Modifiers — the schema everything shares

```jsonc
{ "key": "run.grit_mult", "op": "mul", "value": 1.12, "when": { "axis": "move" } }
```

**ops**, applied in this order: `set`, `add`, `mul`, `min` (floor), `max` (ceiling).

**conditions** (all listed must pass): `tier_gte`, `tier_lte`, `zone_gte`,
`phase`, `region`, `kind`, `axis`, `has_relic`, `hp_below`.

`"per_level": true` on a trait modifier multiplies by the purchased level.

`Rules.explain("key", ctx)` prints the base and every source that moved it.

## Hooks and effects

Rulesets and trinkets can fire effects on events:

```jsonc
"hooks": { "on_task_complete": [ { "type": "grit", "amount": 4, "silent": true } ] }
```

**hooks**: `on_run_start`, `on_area_enter`, `on_area_clear`, `on_task_complete`.
**effects**: `grit`, `item`, `deadline`, `log` — each takes `amount`, plus
optional `silent`.

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

Packs carry `cost` and `min_ring`, so the shop opens as you walk further out.

**The starter pack must keep at least one movement on every axis.** An anomaly
that asks for an axis with nothing unlocked would be unplayable; the self-test
asserts this.

## Areas

```jsonc
{
  "id": "waking_room", "name": "The Waking Room",
  "intro": "…", "outro": "…",
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
`mirror`, `trinket`, `spite`, `warden`.

**movement tokens**: `$choose:<axis>` asks the player to pick, `$same` reuses
their pick, `$other:<axis>` asks for a different one (falling back to the same
movement when the axis has only one unlocked — otherwise the node would be
uncompletable), or a literal movement id.

**units**: a number, or `$set` to read the chosen movement's set size.

`next` lists what a node opens. `exclusive_next` makes a fork close its
siblings — and downstream availability treats a *locked* predecessor as
satisfied, or everything after the fork would wait forever.

`slots` roll side nodes at generation time; `area.slot_bonus` adds guaranteed
extra rolls.

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

## Config keys

```
run.grit_mult  run.resolve_rate  run.loop_keep  run.clear_bonus  run.repeat_falloff
streak.per_day  streak.cap_days
area.slot_bonus  area.reveal_sides  area.deadline_bonus_hours
task.partial_grit  task.min_seconds  task.hold_seconds
loot.cache_mult  loot.echo_weight  loot.trinket_weight
shop.discount
spite.chance  spite.kind_weight
```

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
   gates when the node opens); every world region and anomaly `area` resolves; every
   `loot` names a table; every `movement` is a real movement or a legal `$`
   token; every Palace adjacency key names a room; every overworld region and
   anomaly points at a real area; every prop `biome` is a real material *the
   world actually contains cells of*.

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
