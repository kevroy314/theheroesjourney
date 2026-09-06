# Contributing

## Setup

You need Godot 4.7 (headless is enough for tests) and Docker for serving.

```bash
export GODOT_BIN=/path/to/Godot_v4.7-stable_linux.x86_64
npm run import      # first checkout only: generates .godot/
npm run check       # validate data/ — no engine, seconds
npm test            # headless self-test
npm run verify      # both, in that order
npm run build       # export + serve on :8070
```

There are no npm dependencies — `package.json` is a discoverable entry point for
the shell scripts. The push server under `server/` is the one exception and has
its own.

## The loop

1. Change something.
2. `npm run check` first if you touched `data/` — it needs no engine and fails
   in seconds instead of after the self-test has downloaded one.
3. `npm test` — plays full journeys and builds every screen. It fails on any
   engine error, not just assertions, and that now includes the runtime ones.
4. For UI changes, **look at it in a browser or on the emulator**. Headless
   tests prove the model, not the pixels: the day the tutorial spine landed,
   every self-test passed and four bugs did not survive thirty seconds of
   looking at the screen. Screenshot with a clipped viewport (see
   `.claude/skills/heroes-journey`), or `npm run emu:shot` on a device (see
   `docs/TESTING-ON-DEVICE.md`).
5. `npm run build` and check the real thing.

If you edited the world in Tiled, `npm run world:import` and then
`npm run check` — the import will write a nonsense interactable `type` without
complaint and only the validator notices. See `docs/MAP-EDITING.md`.

`BROTLI_QUALITY=5 npm run build` while iterating — the default q11 pass over the
40 MB wasm takes ~145 s (it is cached by hash, so you pay it once per Godot
version).

## Branches and PRs

`main` is the deployable branch. Work happens on branches:

```
feat/<thing>      new capability
fix/<thing>       bug fix
docs/<thing>      documentation only
chore/<thing>     tooling, deps, build
```

Open a PR against `main`. Keep the PR description focused on *why*; the diff
already says what. Link the issue it closes (`Closes #12`).

A PR should:

- pass `npm test`
- include a test for any bug it fixes, **verified to fail before the fix** — a
  test that passes on the broken code is worth nothing
- update `docs/` when it changes an interface or a convention
- not mix a refactor with a behaviour change

## Issues

Use the templates. The **Bug report** template asks for the JSON blob from the
in-game debug panel (`dbg` bubble → Copy state) — it carries screen, run state,
node graph, meta and knob values, which is almost always enough to reproduce
without a conversation.

## Conventions

**Everything tunable is data.** A number in GDScript cannot be bent by a
ruleset, trinket, Wheel node or Palace adjacency. Put it in
`data/content/config.json` and read it with `Rules.value()`.

**Content is JSON.** New movement, area, item, room, echo, theme, ruleset,
buff, interactable, conversation, objective or animal → a file under `data/`.
Only a new *kind* of content needs code, and a new kind means one entry under
`types` in `data/schema.json` before anything else, so both validators pick it
up with no code change. See `docs/DATA.md`.

**There is one of everything.** One condition language (`Rules.passes` reads a
`when`), one effect applier (`Game.apply_effects`), one rule pipeline. Adding a
second way to change a number, ask a question or make something happen is the
thing every one of these systems is shaped to avoid — if a feature seems to need
one, that is the design question, not an implementation detail.

**Screens are built in code** so a theme swap can restyle everything. No baked
colours in `.tscn`. Colours come from `Palette.c(role)`, widgets from `HJUI`.

**GDScript is tab-indented** (see `.editorconfig`) with typed locals where the
type is not obvious. Comments explain *why*, never *what* — if a line needs a
comment to say what it does, rename something instead.

**Duty of care is not up for negotiation.** No item may complete a real-world
task for the player. No weight or calorie tracking. Scaling a movement down
always counts. Rewards fall off for repeat clears the same day. If a feature
would punish someone for being ill, it is the wrong feature.

## Writing

UI copy is second person, plain, dry, and never scolds. The app is a mirror, not
a warden. Read a few strings in `data/areas/*.json` before writing new ones.

## Where to look first

- `docs/ARCHITECTURE.md` — how the pieces fit
- `docs/DATA.md` — every JSON schema, and how to add a kind of content
- `docs/DESIGN.md` — the two registers, and why the Menu is not a room
- `docs/MAP-EDITING.md` — the world in Tiled, and what survives a regeneration
- `docs/FIRST-THIRTY.md` — the tutorial beat sheet and what each beat runs on
- `docs/DEPLOY.md` — build, cache, PWA, hosting
- `docs/TESTING-ON-DEVICE.md` — the Android emulator from WSL
- `.claude/skills/` — the traps this project has already hit, written up so
  nobody hits them twice
