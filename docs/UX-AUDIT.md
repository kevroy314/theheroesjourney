# UX audit — The Heroes' Journey

Method: every screen in `SCREENS` (`scripts/Main.gd`) visited in a headed Edge
browser at 420x860 against the running build on `:8070`, driven over CDP, with
the debug God-mode grid and the "Do" cheats used to reach gated screens. Every
screenshot was looked at. Filenames below refer to
`/tmp/claude-1000/-home-kevin-fitrogue/9ce70b83-a5c0-4916-a5ea-0f107fa5d8a4/scratchpad/`.

Severity: **S1** = the player gets stuck, loses work, or concludes the app is
broken. **S2** = the player misreads the screen and takes the wrong action.
**S3** = friction and polish.

---

## The five worst things

### 1. Every surface is a card, so nothing reads as a button — and half the cards are dead. (S1)

`HJUI.TapCard` squashes under the thumb on press *before* anything checks
whether it does something. `AreaGraph.gd:229` only connects `tapped` when the
node is available. So on the **area** screen a player taps "A Set", feels the
card give under their finger, and gets nothing — no toast, no shake, no reason.
I did this and captured before/after: `16-after-event.png` → `16b-tap-locked.png`
are pixel-identical.

The same pattern repeats everywhere a bordered panel is not a control:

| Screen | Looks tappable | Actually tappable | Shot |
|---|---|---|---|
| area | every node card | only the accent-dashed ones | `16b-tap-locked.png` |
| task (picker) | the whole accent-bordered card | only the inner "Choose" | `17b-card-tap.png` |
| stores | the 9 accent_2 "ON YOU" cards | only Rest Token | `33-stores.png` |
| gym | 33 `panel_alt` movement rows | none | `31-gym.png` |
| journey | 8 chapter cards | none | `11-journey.png` |
| codex | the found entries (accent_2 border) | none | `36-codex.png` |
| palace | the 6 empty grid cells | none, unless "Rearrange" is on | `39-empty-cell.png` |

**What a player does wrong:** taps a chapter card on the Journey screen expecting
to travel there, taps a movement name in the Gym expecting to read more, taps a
locked area node expecting to be told why — and gets silence in all three cases.

*One-line fix:* inert panels lose the border and the press animation; the accent
border and the squash become the exclusive property of things that fire.

### 2. Two irreversible actions are one unconfirmed tap, in the thumb zone. (S1)

- **area** — the bottom row is `Journey | Bag | Abandon`, three equal-width
  buttons flush across the thumb zone (`z-walkit.png`). I tapped Abandon and the
  run ended immediately, no dialog (`41-abandon.png`). It is the third of three
  buttons a player uses constantly.
- **hearth** — "Wipe save" is the last item in the settings scroll
  (`35c-hearth.png`), full-width danger, directly under a "Select" button.
  `HearthScreen.gd:76` wipes `Meta` with no confirmation. Flick to the bottom of
  settings and your thumb lands on it.

**What a player does wrong:** reaches for "Bag" one-handed, lands on "Abandon",
loses the session. Or scrolls settings to see what's at the bottom and destroys
four loops of history.

*One-line fix:* both need a hold-to-confirm (the pattern already exists on the
task screen) and Abandon needs to leave the three-button row.

### 3. A live run locks you out of the entire rest of the app — including the pause. (S1)

Every `Game.goto` in `scripts/screens/` was traced. Mid-run the reachable set is
closed: `area ↔ journey`, `area ↔ inventory`, `area → overworld → worldmap → area`,
`task → area`. There is **no route from a run to the Mind Palace, the Hearth, the
Gym, the Stores, the Codex, the Wheel or the title.** The only exit is "Abandon".

The Hearth is where "Pause everything" lives — the control that exists for
injury, illness, travel and grief. It is unreachable exactly when a 24-hour
deadline is running, which is the only moment anyone needs it.

**What a player does wrong:** gets ill on day two of a run, opens the app to
freeze the clock, finds no way to settings, and either abandons the run or
watches the deadline burn.

*One-line fix:* the run header's title becomes a tap target back to the Palace,
or the area screen's bottom row swaps "Abandon" for "Home".

### 4. On the area screen the primary action is unmarked, and the one button styled as primary is clipped and leads to a screen that cannot work on web. (S1)

- The actual next action is "tap an available node". Nothing says so. The nodes
  are chalk boxes among eight other chalk boxes (`12-area.png`).
- The only `primary` button is "Walk it", and at 420x860 it is **vertically cut
  off** by the scroll viewport — the bottom third of the button and its rounded
  corners are gone (`z-walkit.png`, zoom of `12-area.png`). It only renders whole
  once the intro paragraph is dismissed (`16-after-event.png`).
- Following it lands on **overworld**, which on a desktop browser reads
  "the sensor errored", shows `STEPS LEFT 0`, and offers no way to get steps and
  no explanation (`13b-overworld.png`). `Steps.needs_permission()` is
  Android-only, so the web build shows no prompt and no recovery.

**What a player does wrong:** reads the one orange button as "what to do next",
taps it, lands in a room they cannot move in, and has to find the "Map" button
(top right, where Back lives everywhere else) to escape.

### 5. There are four "where am I" screens and only one of them is carrying its weight. (S1 as an information-architecture problem)

Full opinion in **Cross-cutting §3**. Short version: `area` earns its place;
`overworld` is a mode of `area`, not a screen; `worldmap` earns nothing and
should be cut or folded in; `journey` is a strip, not a screen.

---

## Per screen

### title — `10-title.png`
The best screen in the app. One large primary ("Wake up" / "Carry on"), two
ghosts under it, three status chips. Nothing here is confusing.

- **S3** The three chips (Resolve / Streak / Loops) are `panel_alt` cards, the
  same material as tappable cards elsewhere. A player will try tapping "Loops"
  to find out what a loop is. Nothing happens, and there is nowhere else to find
  out either.
- **S3** "Settings & updates" leads to the Hearth, which on web has no updates
  section at all (`HearthScreen.gd:_updates` returns early unless
  `OS.has_feature("android")`) and shows no version number. On the platform the
  player is actually using, half the button's label is a lie.

### palace (Mind Palace) — `38-palace.png`, `38b-palace.png`, `39-empty-cell.png`, `39b-room-tap.png`
This is the hub and it is the third-worst screen for "what now".

- **S1** On a fresh save `Meta.ensure_palace()` places one starter room, the
  **Atrium**, which has no `screen` — tapping it fires a toast
  ("Bare, and yours…", `39b-room-tap.png`) and nothing else. So the first-ever
  view of the game's home base is an empty 3x3 grid whose single occupant is
  inert. **A player taps the only thing on the board, gets a sentence, and has
  no idea the grid is a menu at all.**
- **S2** The rooms *are* the navigation (Gym → gym screen, `39c-gym-from-room.png`)
  but they are drawn as translucent plates over the room art with an ASCII glyph
  and a 21px label. Nothing distinguishes "this is a door to a screen" from "this
  is a decoration on a diorama".
- **S2** The empty cells are TapCards with no handler outside arrange mode. Tap
  one and nothing happens, silently (`39-empty-cell.png`).
- **S2** The screen's primary CTA ("Carry on" / "Wake up") is an orange
  full-width button that is visually identical to the four orange full-width
  "Build — N Resolve" buttons stacked immediately above it (`38b-palace.png`).
  **A player scrolling to the bottom cannot tell the "start the game" button from
  the shop.**
- **S2** Buying a room silently enters a carrying mode. The instruction panel
  ("Carrying X — tap an empty space to set it down") is rendered at the *top* of
  the scroll body, and you tapped Build at the bottom. `arranging` and `holding`
  are `static var`s, so the carrying state also survives leaving and re-entering
  the screen.
- **S3** The market card text is clipped by the bottom edge mid-sentence
  ("next to the Observatory — Grit converts to Resolve 20%…", `38-palace.png`).
- **S3** Room glyphs are `» @ ^ $ § + ¤ ~`. See Icons.

### journey — `11-journey.png`
Clear about where you are, offers nothing to do.

- **S2** Eight chapter cards, all inert, all styled as cards. **A player taps
  "The Town" expecting to see or travel to it.** Nothing.
- **S2** State is carried by three ASCII marks — `+` done, `@` here, `?` locked.
  `done.png` exists and is used on the area screen; there is no locked mark at
  all. Three glyphs a player must learn from nothing.
- **S2** The axis mix is text: "Move · Bond", "Water · Fuel". All six axis icons
  exist and appear nowhere on this screen.
- **S3** A ~350px dead gap between the list and the primary button.
- **S3** "Back" goes to `area` mid-run and `palace` otherwise — same button, two
  destinations, no signal which.

### area — `12-area.png`, `16-after-event.png`, `19-after-confirm.png`, `40-area2.png`
The most important screen. See worst-things #1, #2, #4.

- **S2** Node labels clip. "The Glass by the Bed" renders its subtitle as
  "A glass of water. I abso" with the descender row cut through
  (`19-after-confirm.png`) — `AreaGraph.gd` sets `custom_minimum_size.y` to
  92–110px and the text does not get to grow.
- **S2** "Something Here / not yet" (hidden) and "the other way" (permanently
  locked out by an exclusive fork) are styled almost identically —
  `27-a.png`. **A player will keep waiting for "Something New" to open when the
  branch is closed forever.**
- **S2** The header says the deadline twice, two different ways: subtitle
  "due tomorrow 17:30" and chip "LEFT 23h 59m".
- **S3** Three trailing text blocks compete under the graph: a trinket line, the
  mountain line ("Far off, past the window…"), and then the CTA. The mountain
  line also appears on title and worldmap — it is decorative and it is pushing
  the primary button off the screen.
- **S3** Entry nodes of type `free` (e.g. "The Kitchen", `40-area2.png`) get no
  icon and no glyph — an empty 32px gap where every other card has a mark.

### overworld — `13b-overworld.png`, `13c-overworld-steps.png`, `13d-walk-right.png`
Worst screen in the app for "where am I / what now".

- **S1** Dead on web: `source` resolves to `error`, the subtitle reads
  "the sensor errored", `STEPS LEFT` is 0 and stays 0. No prompt, no cheat, no
  explanation of what a step is or where to get one. `blocked` only fires a
  toast after you try to move.
- **S1** No way back to the area list. The top-right button says "Map" and goes
  to `worldmap`; from there "List" goes to `area`. **Two taps through two
  screens with names that describe UI modes, not places, to undo one tap.**
- **S2** The top-right slot is "Back" on eleven other screens. Here the same
  position, size and `quiet` style is a *forward* navigation. A player who has
  learned the pattern will tap it to leave and get sent somewhere new.
- **S2** Nodes are unlabelled orange rings (`13c-overworld-steps.png`). You
  cannot tell "The First Rep" from "The Door" without walking onto it.
- **S2** The act button keeps naming a node after you have walked off it — I
  walked three tiles away and it still read "Do: Open your eyes"
  (`13d-walk-right.png`).
- **S2** The disabled state ("Walk to something") has no fill and no border — it
  reads as a caption floating on the floor tiles, not as a button that will
  become the primary action.
- **S3** The d-pad is four drawn arrowheads with no labels and no indication that
  holding walks continuously rather than stepping once.

### worldmap — `14-worldmap.png`
Second-worst for "where am I". It is a picture.

- **S2** No title telling you which chapter or area you are in — the header says
  "The Way Up" and then repeats the mountain line from the title screen.
- **S2** The current chapter's nodes are an illegible cluster of ~14 rings in the
  bottom 15% of the map; the "you are here" pulse is drawn in the same cluster.
  Nothing is labelled, by design. **The screen cannot answer any question a
  player would open it to ask.**
- **S2** No back. Two co-equal bottom buttons, "Walk" (primary) and "List"
  (ghost), naming UI modes rather than destinations.
- **S3** Not pannable or zoomable, so the deliberate "no labels" rule leaves it
  with zero interactive content.

### task — picker: `17-task-picker.png` · active: `18-task-active.png`, `18b-task-ready.png`, `24-boon.png`
This is the screen where the real-world work happens and its hierarchy is
inverted.

- **S1** While the plausibility gate counts down, the confirm button is disabled
  — grey, no border, no fill — and reads "Go on, then". The only bordered,
  button-shaped control on the screen is **"I couldn't do this one"**
  (`18-task-active.png`). **The failure path is the most button-shaped thing on
  the screen, for the whole duration of the exercise.**
- **S1** Once a movement is chosen there is no exit. `_build_active` calls
  `HJUI.header(label, text)` with no `on_back`. You can complete, or you can
  declare that you couldn't. **A player who opened the wrong node is forced to
  log a failure to get out.** You also cannot change your movement choice.
- **S1** "Hold to confirm" renders as **"Hold to conArm"** — Pixelify's `fi`
  ligature reads as a capital A at button size. Verified at 4x in `z-confirm.png`.
  The gate label above it reads "ConArm unlocks in 38s" (`21-set-task.png`), and
  the Workshop's "Refinery" reads "ReAnery" (`z-refinery.png`). This is on the
  single most important button in the game.
- **S2** The picker: 16 identical accent-bordered cards, alphabetical, each with
  a `ghost` "Choose". **Zero primary buttons on a screen whose entire purpose is
  to make one choice**, while the Workshop has eight. Nothing is recommended,
  nothing is "what you did last time".
- **S2** The picker's "Back" calls `Game.skip_task()`, which clears the pending
  node and always lands on `area`. Enter a task by walking to it in the overworld
  and "Back" teleports you into the list view.
- **S3** Unit bugs visible in `17-task-picker.png`: "Jog — 1 minutes",
  "Loaded carry — 1 second".
- **S3** When a node has no `text` the header subtitle is empty and the panel
  keeps its height, leaving a bar of empty chrome (`24-boon.png`).
- **S3** ~250px of dead space between the gate bar and the confirm button.

### boon — `25-b.png`
- **S2** Three cards, each with a full-width orange "Take". **Three primaries and
  no default.** The screen is almost entirely orange.
- **S2** The cards are not tappable; only the button inside them is.
- **S2** The header ("A Charm Offers Itself") was completely covered by a toast at
  the moment the screen appeared — see cross-cutting §7.
- **S3** `charm.png` exists and is not used here.

### event — `15b-task.png`, `22-a.png`, `23-cache.png`, `28-threshold.png`
- **S2** The same full-screen modal is used for a story beat ("You are awake, and
  horizontal, and those are two different problems") and for
  **"You pocket what's there. +8 Grit."** (`23-cache.png`). A whole screen and a
  tap for one number. **A player learns within three of these to tap Continue
  without reading, which is exactly the habit that kills the Echo system.**
- **S2** The title sits unpanelled at the very top edge over the backdrop art and
  is routinely half-covered by a toast (`22-a.png`, `23-cache.png`).
- **S3** The chapter-transition footer ("The House · due tomorrow 17:40") is
  muted grey over a bright section of the art and is unreadable (`28-threshold.png`).
- **S3** "Echo 2 of 16 — kept in the Codex" is a pointer to a screen the player
  cannot reach from here (and cannot reach at all mid-run — see worst-things #3).

### summary — `41-abandon.png`
Good screen. Clear outcome, clear numbers, clear next step.

- **S2** Three stacked full-width buttons ("The Wheel — 22 to claim" ghost,
  "Wake up again" primary, "The Mind Palace" ghost). The primary is in the
  middle, which is the position a thumb reaches last.
- **S3** At 1x DPR the pixel face's digits are genuinely ambiguous — I read
  "Chapter 2 of 8 / 164 / 20% / +20 / 372" as "8 of 8 / 164 / 80% / +80 / 378"
  until I zoomed (`41-zoom.png`). On a 3x phone this is fine; in the desktop
  browser build it is not. Worth knowing before anyone reports a "wrong number".

### codex — `36-codex.png`
Fine, and honest — the gaps are the point.
- **S3** 16 identical "— — —" rows of dead scroll; found entries carry an accent_2
  border that makes them look tappable when they are not.

### wheel — `37-wheel.png`, `z-wheelchips.png`
- **S1** The axis chips are broken. The captions wrap and the orphaned second
  line lands *on the value row next to the icon*, so the six chips read
  "MOV / E 8", "WAT / ER 1", "FUE / L 0", "RES / T 0", "MIN / D 0", "BON / D 0"
  (`z-wheelchips.png`). Six chips of pure noise directly under the wheel they are
  supposed to explain.
- **S2** The wheel drawing itself has no legend. Six labelled spokes with small
  rings on them, no fill, no "you are here", not tappable. **A player will tap a
  spoke expecting to filter the list below.**
- **S2** The "READY TO CLAIM" heading is a 25px muted label sitting behind the
  chip row; the claimable and locked lists are otherwise the same cards.
- **S2** A wall of full-width orange "Claim" buttons — one per unclaimed node.

### inventory (Bag) — `30-inventory.png`
- **S1** "Warp Stone — Walk straight to the door, abandoning whatever is left in
  the room" has a full-width orange "Use" that is byte-identical to the Hourglass
  and Tonic ones. **A player will tap Use on the Warp Stone thinking it is a
  shortcut and forfeit the rest of the area, with no confirmation.**
- **S2** Five to six identical orange "Use" buttons in one scroll; the unusable
  ones become greyed "Use (only at home)" which reads as broken rather than
  contextual.
- **S3** No item icons at all, despite `cache`, `rest`, `deadline`, `mirror`,
  `echo` marks existing.
- **S3** The screen's no-run branch (`back → palace`) is **unreachable** — nothing
  in the app routes to `inventory` except the area screen's "Bag".

### stores — `33-stores.png`
- **S2** The same nine items are listed **twice on one screen**: "ON YOU"
  (name + count) then "SHELVES" (name + description + Buy). And the "ON YOU"
  block is a third copy of the Bag screen. **A player scrolling past "Hourglass
  ×2" and then "Hourglass · held 2" will think they are two different things.**
- **S2** The "ON YOU" cards all carry an accent_2 border but only home-usable
  items have a button; the other eight are inert lookalikes.
- **S3** Nine full-width orange "Buy" buttons.

### gym — `31-gym.png`, `39c-gym-from-room.png`
- **S2** The axis filter row is seven text buttons compressed to the frame edges
  ("All / Move / Water / Fuel / Rest / Mind / Bond"), the last one flush against
  the right margin. All six axis icons exist and are not used.
- **S2** 33 movements, each a four-line prose block inside a `panel_alt` card,
  none tappable. It is the wiki, the shop and the unlock list at once, with no
  search and no collapse. **A player looking up "what is a bird dog" scrolls
  through a wall of identical grey blocks.**
- **S3** "a set is 1 glass", "a set is 1 night" — the set framing does not fit
  the non-rep axes.

### workshop — `32-workshop.png`
- **S2** Eight-plus identical full-width orange "Buy — N Resolve" buttons in one
  scroll. There is no ordering, no recommendation, no "you can afford these
  three". **A player buys whatever is at the top.**
- **S2** "Refinery" renders "ReAnery" (`z-refinery.png`).

### hearth — `35-hearth.png`, `35b-hearth.png`, `35c-hearth.png`
- **S1** "Wipe save", no confirmation — see worst-things #2.
- **S2** Contradictory state: the card says **"On. 2 reminders queued."** and the
  button under it says **"Turn on reminders"** (`35-hearth.png`).
  `Notify.describe()` and the `on` calculation in `_notifications` disagree.
  **A player taps "Turn on reminders" believing they are off, and either nothing
  changes or a permission prompt they already answered reappears.**
- **S2** "Pause everything" — the duty-of-care control — is a `ghost` button
  identical in weight to the theme "Select" buttons below it, with no
  confirmation and no indication of how to undo it.
- **S2** Theme and ruleset cards change height depending on whether they are
  selected (the selected one loses its "Select" button), so the list reflows
  under your thumb every time you choose.
- **S3** Quiet-hours are a button that increments one hour per tap. Going from
  22:00 to 21:00 is 23 taps.
- **S3** Section headers (REMINDERS / WHEN LIFE HAPPENS / THEME / RULESET) are
  21px muted text sitting directly on the backdrop art, at roughly 2:1 contrast.

### observatory — `34-observatory.png`
Honest and useful. Two problems.
- **S2** The log rows render `→` as a tofu box: "20 Grit ▯ +12 Resolve"
  (`z-arrow.png`). `ObservatoryScreen.gd:79` is the only place in player-facing
  text that leaves ASCII/Latin-1 — the exact trap `SKILL.md` documents.
- **S3** Fourteen numeric rows in plain text, no marks, on a screen called "the
  instruments". `grit`, `resolve`, `streak` and the six axis icons all exist.

---

## Cross-cutting

### 1. Affordance

The rule the app currently follows is "a bordered rounded panel means content";
the rule the player infers is "a bordered rounded panel means tap me". They are
in direct conflict on eight screens (table in worst-things #1). The press
animation makes it worse: `TapCard._squash` runs on every press regardless of
whether a handler is connected, so **dead cards give haptic-style feedback and
then do nothing** — the strongest possible false affordance.

Conversely, three things that *are* interactive do not look it:
- **overworld**, the disabled act button (no border, no fill, grey text on tiles).
- **palace**, the room plates (translucent, no border in the ordinary state).
- **wheel**, nothing — the wheel drawing is the only thing that looks
  interactive and it is the one thing that is not.

### 2. Where am I / what now — ranked worst first

1. **overworld** — cannot move, cannot read the map, cannot get back to the list.
2. **worldmap** — no place name, no labels, two buttons naming UI modes.
3. **palace** — the hub, and on a fresh save its only content is an inert room.
4. **area** — knows where you are; does not say what to tap; its one primary is
   clipped and misleading.
5. **wheel** — broken captions, unexplained diagram.
6. **stores** — the same list twice.
7. **task (active)** — knows what; no way out except failure.
8. **journey** — knows where; nothing to do.

`title`, `summary`, `event`, `boon`, `observatory`, `codex`, `inventory`,
`gym`, `workshop`, `hearth` all answer "where am I" adequately; their problems
are hierarchy, not orientation.

### 3. Redundancy — the four maps

You asked for a straight opinion. Here it is.

**`area` earns its place, completely.** It is the only screen that shows what is
open, what is done, what is closed, and what a node will cost you. Everything
else is derived from it.

**`overworld` does not earn a *screen*, but the idea earns a *mode*.** Reaching a
node by spending real steps is a genuinely different decision from picking one
off a list — that part is real. But as built it shows *strictly less* than the
area screen (unlabelled rings vs. labelled cards with costs), it cannot answer
"what's available", and on web it cannot function at all. It is the same
information twice, minus the labels. It should be a toggle on the area screen —
same header, same step chip, swap the graph for the tilemap — not a destination
you navigate to and then have to navigate back from through a third screen.

**`worldmap` does not earn its place.** It is reachable from exactly one button
on one screen. It has no place names by design, no labels on its rings, no zoom,
no pan, and no title telling you which chapter you are in. Its only unique
message is "the world is bigger than this room", which the chapter list already
says in words. Cut it, or reduce it to a small always-visible strip at the top of
the overworld showing the chapter's progress along the road.

**`journey` does not earn a screen either, but its content is the one thing
missing elsewhere.** Eight chapters, the arc, the axis mix. That is a header
strip or a one-line "Chapter 2 of 8 ▸" tap-out from the area header, not a
full-screen list of eight inert cards with a 350px hole in it.

**Mind Palace earns its place as the hub** — every meta screen hangs off it and
the adjacency puzzle is real content. But it is currently a menu wearing a
diorama costume, and the costume is winning: the doors do not look like doors,
the empty cells look like doors, and the shop is stapled underneath in the same
visual language as the exit.

**Verdict:** two of the five are load-bearing (`area`, `palace`). One is a mode
misfiled as a screen (`overworld`). One is a strip misfiled as a screen
(`journey`). One is decoration (`worldmap`).

### 4. Navigation consistency

Good: eleven screens put a `quiet` 120x62 "Back" at top-right (palace, journey,
gym, workshop, stores, hearth, observatory, codex, wheel, inventory, task-picker).
That is a real convention and it holds.

It then breaks in five ways:

- **overworld** puts a *forward* action ("Map") in the Back slot, same size, same
  style. **S2**
- **area, worldmap, event, boon, summary, task-active, title** have no Back at
  all. On `area` this is the lockout in worst-things #3. On `task-active` it is a
  hard dead end.
- **journey**'s Back has two destinations depending on run state; **inventory**'s
  has two; **hearth**'s has two (`_from_palace`). Same pixel, three different
  meanings across the app.
- **worldmap** is reachable from exactly one place and leaves by two buttons that
  name modes ("Walk", "List") rather than places.
- **task-picker**'s "Back" is not a back — it calls `skip_task()` and always
  lands on `area`, discarding where you came from.

Dead ends: `task-active` (exit only by completing or failing). Unreachable
states: `inventory`'s no-run branch.

### 5. Icons

`assets/icons/` ships 21 marks (plus `_contact_sheet.png`, which should not be in
the export at all).

**Never used anywhere: `light.png`.** That is the only orphan — 20 of 21 are
referenced. The problem is not unused icons, it is that the used ones appear in
only three places (`HJUI.chip`, `AreaGraph` node marks, `WheelScreen` chips) while
the same concepts are spelled out in words on a dozen other screens.

**Bare text doing an icon's job:**

| Screen | Text doing the work | Mark that exists |
|---|---|---|
| journey | "Move · Bond", "Water · Fuel" per chapter | all six axis marks |
| journey | `+` done, `@` here, `?` locked | `done`; nothing for locked |
| gym | seven-word filter row, squeezed to the edges | six axis marks |
| gym | axis name repeated in every one of 33 rows | six axis marks |
| observatory | "By axis" — six text rows | six axis marks |
| observatory | "Tasks completed", "Resolve earned" | `task`, `resolve` |
| summary | "Grit gathered", "Resolve earned/banked" | `grit`, `resolve` |
| palace | room cells use `» @ ^ $ § + ¤ ~` | `mind`, `cache`, `rest`, `charm`, `echo` are the same vocabulary |
| workshop / stores / palace / hearth | every button spells "Resolve" | `resolve` |
| inventory / stores | nine items, no marks at all | `cache`, `rest`, `deadline`, `mirror`, `echo` |
| overworld | "Steps left" — the only chip with no icon | **none exists** |

**Icons used where they do not help:**

- **area** — every task node carries the `task` mark, and ~60% of nodes are
  tasks. A mark that appears on the majority carries no information; it just eats
  32px of a card that is already clipping its text. The marks that *do* work here
  are `threshold`, `cache`, `echo`, `charm`, `warden`, `spite`.
- **area** — a completed node says "done" four times: `done` icon, green title,
  green border, and the subtitle "done" (`16-after-event.png`).
- **wheel** — the icon is the only functioning part of each chip and the wrapped
  caption beside it actively destroys it (`z-wheelchips.png`).

**Concepts that recur and have no mark:** steps / the step budget (the entire
economy of the overworld); locked / "not yet"; "the other way" (a fork closed
forever, currently indistinguishable from "not yet"); chapter; pause; scaling
("easier:"); and the Palace rooms themselves — Gym, Stores, Workshop, Hearth,
Observatory, Codex and Wheel all fall back to ASCII punctuation.

### 6. Density and hierarchy

Full-width `primary` (orange) buttons visible in a single scroll:

| Screen | Primaries | Actual number of "next actions" |
|---|---|---|
| workshop | 8+ | 1 |
| stores | 9 Buy + Use | 1 |
| wheel | one per claimable node | 1 |
| inventory | 5–6 | 0–1 |
| palace | 4 Build + Widen + Carry on | 1 |
| boon | 3 | 1 |
| **task (picker)** | **0** | **1** |

`primary` currently means "this control does a thing", not "this is what to do
next", which is the same as meaning nothing. The picker — the one screen that
exists solely to take a single choice — is the one screen with no primary at all.

Text density:
- **gym**: 33 × 4-line prose blocks, no search, no collapse.
- **stores**: every item twice.
- **codex**: 16 blank rows.
- **area**: intro paragraph + graph + trinket line + mountain line + CTA + three
  buttons, in 860px. The mountain line appears on three screens and pushes the
  CTA off the bottom of the second one.
- **hearth**: four unlabelled-by-contrast sections, a destructive action, and
  two purchase lists in one scroll.

### 7. Toasts land on the header

`Main.gd` anchors toasts `PRESET_TOP_WIDE` at `offset_top = 16` — deliberately,
to keep the thumb zone clear. The cost is that every toast covers the screen
title and the Back button for its lifetime. Captured on five screens:
`05-after-cheats.png` (covers "The Mind Palace" and Back), `22-a.png` (covers the
Echo's title), `25-b.png` (covers "A Charm Offers Itself"), `27-a.png` (two
stacked, covering the run header), `39b-room-tap.png`.

**What a player does wrong:** taps a Palace room, gets a toast describing it, and
in the same second loses the ability to see or hit "Back". *One-line fix:* inset
the toast stack below the header panel's height rather than above it.

### 8. The debug bubble ships visible

`Debug.bubble_visible` defaults to `true` and `Main.gd` adds `HJDebugOverlay`
unconditionally. In every screenshot here there is a floating "dbg" circle
sitting on top of the content — on the Palace it covers the Back button
(`01-palace-clean.png`), on the picker it covers a price (`17-task-picker.png`),
on the Wheel it covers the "READY TO CLAIM" heading. If this is intentional for
now, fine; if the owner's complaint is "if there's a click-me on the screen it
should be clear", this is the one click-me that should not be on the screen at
all.
