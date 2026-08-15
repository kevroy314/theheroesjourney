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

## Post-processing traps

- The render is **not** pixel art (20k+ unique colours, soft edges). To get
  crisp pixels, `Image.BOX`-downsample to the logical size, then re-quantize.
- **Naive median-cut destroys dark art.** A 90%-near-black image spends its
  whole palette on shadow and silently deletes the one warm accent — the most
  important pixel in the picture. Quantize in gamma-lifted space and *force-pin*
  the theme's key colours (read them from `data/themes/*.json`) into the palette.
- Always compare before/after at 1:1 and confirm the accent survived.

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
