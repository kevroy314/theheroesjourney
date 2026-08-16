---
name: game-art-pipeline
description: Generate game art assets by driving ChatGPT's web UI through a headed Edge browser over CDP, then post-process them for Godot. Covers the working download recipe (cookie-gated URLs), what the model can and cannot keep consistent across frames, quantization traps, and how to wire the result into the game. Use when asked to make, iterate on, or slice visual assets for The Heroes' Journey.
---

# Skill: game-art-pipeline

No image-generation API key is available. Assets are produced by driving the
user's **logged-in ChatGPT web session** in a headed Edge browser over CDP, so
their existing subscription and image quota apply.

**Budget discipline: every generation costs the user real quota. Plan the prompt,
generate once or twice, and stop.** Spend effort on the prompt, not on iterating
pixels.

## The tools

- `tools/../art/chatgpt_gen.py` — `./chatgpt_gen.py prompt.txt out.png [tab-substring]`
- `art/postprocess.py` — downsample + quantize to a limited palette
- `art/slice.py` — cut a grid sheet into frames
- `art/prompt_*.txt` — the prompts that produced the current assets; start from these

## The mechanics that actually work

Start the browser with `~/.claude/skills/edge-cdp-browser/scripts/start.sh`, then
find the ChatGPT tab rather than opening a new session — the user often has a
conversation already primed with style context:

```bash
curl -s "http://172.23.112.1:9223/json/list" | jq '.[] | {id,url,title}'
```

Three things are fiddly, and these are the answers:

1. **Typing.** The composer is a ProseMirror `contenteditable` at
   `#prompt-textarea`. `fill()` mangles it and `type()` submits on every
   newline. Click it, then `page.keyboard.insert_text(prompt)`.
2. **Completion.** Snapshot the `img` elements under
   `[data-testid^="conversation-turn"]` *before* sending, then poll for a new
   one, wait for `button[data-testid="stop-button"]` to disappear, and re-read
   `src` — the image streams in and the early src is a low-res placeholder.
   Typical wait 25–35 s.
3. **Download.** The asset URL
   (`https://chatgpt.com/backend-api/estuary/content?id=file_…&p=fs&sig=…`) is
   cookie-gated, so curl from WSL gets nothing. Fetch it *inside the page* and
   base64 it back out:

```python
res = pg.evaluate("""async (u) => {
  const r = await fetch(u, {credentials: 'include'});
  const bytes = new Uint8Array(await r.arrayBuffer());
  let bin = ''; const CH = 0x8000;
  for (let i = 0; i < bytes.length; i += CH)
    bin += String.fromCharCode.apply(null, bytes.subarray(i, i + CH));
  return {status: r.status, b64: btoa(bin)};
}""", src)
```

`p=fs` is the full-size original and the `sig` is bound to it — other `p=` values
403. There is no higher-resolution variant to chase.

## What the model can and cannot do

This is the finding that should shape every asset decision:

- **It cannot hold an identity across frames.** Character sprite sheets come back
  as *labelled contact sheets*, not grids: row counts vary, column pitch wanders
  ±10%, a "32x32" caption is fiction (sprites are ~120px of soft anti-aliased
  pseudo-pixels), and the silhouette visibly redraws between frames. Do not
  expect to slice one automatically.
- **It can hold a scene while varying one lighting property.** A locked
  composition asking only for a changing light produced 2×2 cells that were
  pixel-equal outside the animated window (0.1–0.2% of pixels differing, frame
  registration within ~1px).

So: use generation for **lit and atmospheric loops**, not walk cycles. For
character animation, generate one canonical pose and animate by
transform/shader in Godot, or hand-author frames from that single reference.

Asking for a 2×2 grid forces square cells, which breaks a portrait composition —
generate the still at 1024×1536 and the animated insert as a separate strip,
compositing in Godot.

## Composing a plate the UI has to sit on

Sixteen plates in, this is the part that decides whether an asset is usable, and
it is worth more prompt words than the subject is.

**Brief the composition from where the panels actually are on that screen**, not
from a house rule. The first set was briefed "content in the top third, quiet
band below", which is right for a screen whose panels sit low — and wrong for
the Journey screen, whose list starts at the very top. The sky, mountain and
lantern all landed behind the list and only the road survived.

The brief that has worked everywhere since is a **vignette**:

> Put the interesting content in a band across the upper third and down the left
> and right edges. Frame the view like a vignette: objects standing at the left
> and right margins, the depth of the room visible between them. The centre
> column and the lower half are one continuous quiet surface — floor, road,
> ground — with no fine detail, no bright highlights and no busy texture.

That survives contact with both layouts this game has: a narrow centred graph
(sides stay open all the way down) and a full-width list (only the header band
and the floor show). It is also just a better picture.

Three more that hold:

- **State the aspect the screen is, not the aspect you want.** Asking for 2:3
  was ignored in every round; the model returns 9:16 regardless. Since the
  screen is 9:16 that was luck. Ask for 9:16 and stop cropping 66px off each
  side under `KEEP_ASPECT_COVERED`.
- **"No text" needs saying explicitly, and then it holds.** Shop tags, wall
  charts, ledger pages and pinboards all came back convincingly blank once the
  prompt said "no lettering, no numbers, no writing of any kind".
- **Continuity is a paragraph, not a hope.** A short CONTINUITY block naming the
  shared materials — "heavy dark timber beams, plank walls, one oil lamp as the
  only light, another door off the same hall" — kept five separately generated
  rooms reading as one building.

## Post-processing traps

- The render is **not** pixel art (20k+ unique colours, soft edges). To get
  crisp pixels, `Image.BOX`-downsample to the logical size, then re-quantize.
- **Naive median-cut destroys dark art.** A 90%-near-black image spends its
  whole palette on shadow and silently deletes the one warm accent — the most
  important pixel in the picture. Quantize in gamma-lifted space and *force-pin*
  the theme's key colours (read them from `data/themes/*.json`) into the palette.
- **Pin the register's own accents, not the default list.** `KEEP_DEFAULT` is the
  cold reality palette. Quantising a warm Mind Palace interior against it throws
  away the flame, which is the one thing in the picture that must survive:
  `--keep "#F2B84B" "#D9A05B" "#F8ECD4"` for `palace_colors`.
- Always compare before/after at 1:1 and confirm the accent survived.
- Quantising at `--colors 32` posterizes smooth gradients into blotches, visible
  in skies and lamp pools. It is consistent across the whole set, so it now reads
  as house style; fixing it means an ordered dither on the remap and re-running
  *every* existing plate, not just the new one.

## Wiring into Godot

Backdrops go in as a full-rect `TextureRect` behind the panels:
`expand_mode = EXPAND_IGNORE_SIZE`, `stretch_mode = STRETCH_KEEP_ASPECT_COVERED`,
and **`texture_filter = TEXTURE_FILTER_NEAREST`** — the default linear filter
turns pixel art to mush.

A 2:3 asset on a 9:16 screen crops ~66px from each side under
`KEEP_ASPECT_COVERED`; compose with that in mind.

Because screens are built in code so themes can restyle them, the natural home
for an asset path is a key in the theme JSON alongside `colors` — then a theme
swap swaps the art too.

Prefer animating in-engine (a shader pulsing a colour, a slow scroll) over
shipping frames: it loops seamlessly, costs no payload, and the export already
carries ~40MB of wasm.

**Keep art out of the export until something references it.** `export_presets.cfg`
has `exclude_filter="art/*"`; unreferenced PNGs were adding 3.5MB to the pck.
