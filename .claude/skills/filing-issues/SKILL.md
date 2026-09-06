---
name: filing-issues
description: File, revise and close a GitHub issue on The Heroes' Journey in this repo's house style — the user's own words quoted, a proposed method naming files and functions that were verified to exist, dependencies both ways, and what the Tiled round trip has to carry. Use when filing an issue, when a batch of feedback needs turning into issues, when an existing issue turns out to be wrong, or when closing one after shipping. Prevents issues that send the next person to a renamed function, and closings that record no evidence.
---

# Skill: filing-issues

Fifty-one issues (#33–#83) were filed in two sittings and they are all the same
shape, because the same instructions were pasted into agent prompts each time.
This is that paste. The point is not tidiness — it is that these issues are the
**design record**, they are read by an agent months later with no context, and
several have already been the only surviving explanation of a decision.

Read three before writing one: **#49** (long, all sections, the fullest example),
**#82** (short, a found bug, still has the editor section), **#76** plus its
comment (the correction move).

## The shape

Seven elements. Forty-five of the fifty-one carry the last three verbatim as
`## Dependencies` and `## Editor interaction`; the exceptions are retrospective
records of work already done, not proposals.

**1. The title is a claim, not a task.** Declarative, and it says the finding
rather than the chore. `A cup cannot stand on a counter: the world needs a
clutter plane`. `The house is not a house`. `Prop footprints should be symmetric
about the anchor, not grow east`. Never `Add clutter plane`, never `Fix
footprints`. The `<observation>: <consequence>` colon form is the workhorse and
carries about half of them.

**2. An opening heading that states the finding**, in this issue's own terms.
There is no fixed word for it — `## The problem`, `## The numbers`,
`## Why this is first`, `## The map shows you everything, at one scale,
forever`. A generic `## Overview` is the tell that nobody worked out what the
issue is actually about.

**3. The problem in the user's own words, quoted**, wherever those words exist —
31 of 51 bodies carry a blockquote and it is usually the first thing after the
heading. Quote, do not paraphrase: *"it's not clear I'm about to be asked to do
some fitness"* is the whole of #54's case and a summary of it is not. Attribute
where it came from (`From the feedback:`, `From Kevin, on the intended run
length:`, or a doc with its section). Where there is no quote, substitute
**what is actually there today, verified** — #49 and #63 both open by grepping
the current code and reporting what it does, which is the same job: establishing
that the problem is real before proposing anything.

**4. `## Proposed method`** (or `## Method`), naming **real files and real
functions**, and this is the load-bearing one:

> **Verify every path, function and constant before you write it down.** An
> issue naming a renamed function sends the next person somewhere that is not
> there, and they will trust it because it is written in an issue.

`grep` for it. Open the file. Quote the line number when it matters
(`scripts/ui/Screen.gd` `backdrop()` (line ~138)). Say explicitly when a check
came back empty — *"`grep 'func phase'` across `scripts/` returns nothing"* is a
fact with a shelf life, and it is why #33's proposal is still trustworthy.
Sketch data in a fenced `jsonc` block in the real schema's shape, not in
pseudocode.

Prefer to name the existing mechanism the change should reuse. Almost every
issue here lands on one — *"`reward` is the existing modifier schema again"*,
*"`grants` already appends to `HJRun.tags`"*, *"`when` is the existing condition
dictionary, handed verbatim to `Rules.passes()`"*. An issue that proposes a
second way to do something the repo already does once is usually wrong, and
saying which mechanism it reuses is how you find that out while it is still
cheap.

**5. `## Dependencies`, in both directions.** What must land first — hard or
soft, said which — and what this **blocks or reshapes**. Reference by number and
title (`**#33 world clock** — hard`). "None" is a real and useful answer:
*"None. **Blocks** NPC schedules, mobs with day/night behaviour, and anything
temporal."* If a dependency can be worked around, say how far:
*"Lighting can be built with a hardcoded dawn while #33 lands, but it is not
finished until the phase drives it."*

**6. `## Editor interaction` — the standing requirement.** Every issue gets one,
and anything touching world content must say **what the Tiled round trip has to
carry**. This is the element most often missing elsewhere and the reason the
section is mandatory rather than conditional.

Answer three questions:

| | |
|---|---|
| Does this round-trip **for free**? | `tools/world_to_tiled.py` classifies the world file **by shape, not by name**: a top-level list of `{x, y, …}` records becomes its own draggable object layer with the scalars as native typed sidebar properties. So most new collections need no tooling change — say so, and say why you chose that shape. |
| What is **authored** vs **derived**? | A light on a prop is a fact about the kind of lamp and belongs in `assets/tiles/tiles.json`; a standalone light is a placement and belongs in the world file. Player state — where someone has walked — is neither and must **not** round-trip at all. |
| What does the **validator** need to learn? | Usually a `data/schema.json` entry plus a reference check in `tools/validate_data.py`. A mistyped `type` in Tiled imports happily and is silently invisible in game; the validator is the only thing that catches it. |

Read `docs/MAP-EDITING.md` before writing this section — the round trip's real
constraints (one byte per cell, no tombstone for a deleted object, `PLANE_KEYS`,
byte-identical export) are documented there and the section should cite them
rather than re-derive them. A section that just says "no editor impact" is only
acceptable when the issue genuinely touches no world content, and it should say
which — #63 spends its whole editor section explaining why fog must *not* be in
the world file, which is the useful version of "no impact".

**7. Labels and milestone.** `enhancement` on a proposal, `bug` on something
broken; those two carry every issue from #33 on. The one milestone is **First
thirty minutes** — apply it only if the work is named by `docs/FIRST-THIRTY.md`
Beats 0–7 or is a UX fix the first thirty minutes are judged on. Most issues
have no milestone and that is correct.

```bash
gh issue create --title "..." --body-file /tmp/body.md --label enhancement \
  --milestone "First thirty minutes"
```

`gh issue view` currently fails in this repo with a Projects-classic GraphQL
deprecation error. Read through the REST API instead:

```bash
gh api repos/:owner/:repo/issues/49 --jq '.title, .body'
gh api repos/:owner/:repo/issues/49/comments --jq '.[].body'
```

## Closing an issue

How an issue closes is as distinctive here as how it opens, and the closing
comment is often the only record of what was learned. Three kinds:

**A closing comment.** Opens `Done.`, `Done in <sha>.` or `Fixed in <sha>.`,
then immediately **names the files that shipped** — *"Done.
`assets/shaders/world_light.gdshader`, `scripts/ui/Lighting.gd`,
`scripts/ui/LightOverlay.gd`."* Then, and this is the part that earns the
comment:

- **What the issue got wrong.** #59: *"The diagnosis here was right about the
  symptom and slightly off about the cause: the buttons did not *disappear*
  after the first anomaly — `OverworldScreen.build()` never built any."* #53
  shipped as two halves rather than the proposed one collection. #63 shipped
  4×4-block sparse chunks instead of the per-cell bitset the issue asked for,
  and says what that saved (80KB → 542 bytes). Write the divergence, not a claim
  of compliance.
- **What was decided and why**, where the reasoning is not obvious from the
  diff. #49's whole closing is an argument for one shader quad over
  `CanvasModulate` plus additive sprites, because darkening first crushes the
  ground before the light touches it. That argument exists nowhere else.
- **Numbers, measured.** *"CPU gather 218µs/frame, down from 2.4ms."* *"the dog
  stays in a 1–4 band across a 38-step walk."* Paste the actual command output
  where there is any (#42 pastes two `validate_data.py` runs).
- **The seams left behind.** *"`time_of_day` defaults to 0.27 and is marked as
  the seam for #33."* *"Fading is correct but not yet *visible* as a difference,
  because anomalies do not move until #73."* Say what is unfinished rather than
  letting a closed issue imply it is not.

**A revision comment, when the issue is wrong but the topic is still live.**
This is the right move and it is not the obvious one — do not close and refile.
#76 sized the world from the step budget, which was the wrong input, and got an
answer 61× too big. It was fixed by a comment opening **"Revising the central
recommendation in this issue"**, which quotes the push-back, gives the new
answer, and then walks the original bullet by bullet saying what each becomes
(*"Chunking drops from blocker to desirable"*) — **plus a retitle**, from *"The
world is ~100x too small, and the map format will not survive fixing it"* to
*"World scale: size from content density, not from the step budget"*.

Revise-and-retitle when the *question* is still the right question and only the
answer moved. Close and refile when the question itself dissolved. The test: if
the issue's number is already cited by other issues — #76 is cited by #81, #82
and #83 — closing it orphans those references, and a corrected issue at the same
number keeps them pointing somewhere true. When a second issue takes over part
of the scope, say so in both: #81 opens *"This issue owns the economy. **#76**
owns the map size, and its recommendation is revised down substantially in the
light of this."*

**A cross-linking comment on an issue that has not moved.** Headed
`## Touched by the <source> pass — <what changed>`. It states first that the
issue is **still unimplemented, and re-verifies that** (*"`grep 'func phase'`
across `scripts/` returns nothing"*), then records what changed *around* it —
who now depends on it, which half of it another issue has taken over, what a
sibling settled that this one had left open. It ends by saying whether the
proposal above needs revising. Use this when a later batch of work reshapes an
open issue's context without touching its content; it is what stops an old issue
quietly becoming a lie.

## Voice

Same voice as the codebase and `docs/`: dry, specific, and willing to say a
thing is wrong. Bold the sentence that carries the argument, one per section at
most. Tables for anything enumerable — cost models, render states, what the
round trip carries. Prose for the reasoning. Never "we should consider"; say
what to do and why, and if the answer is not known, say that instead and say
what would settle it.

Related: the `heroes-journey` skill for the conventions an issue's proposal must
respect, `new-system` for what a system-shaped issue is proposing, and
`docs/MAP-EDITING.md` for the editor section.
