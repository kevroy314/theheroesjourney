#!/usr/bin/env python3
"""Swipe left or right on generated character art, dating-app style.

Six rounds of this project's character work each put four to six figures in
front of Kevin and asked "is this it?". Six samples of a space with millions of
points in it; the answer was always "closer, but not it", and his diagnosis was
that the problem was never any one figure, it was that we had never explored:

    "the biggest issue has been not enough diversity in characteristics,
     colors, etc. so I want a very high temperature on this process so I can
     show you by example what I'm looking for."

So this is a throughput instrument, not a gallery. The gallery next door
(`curate_server.py`) is for deliberate verdicts on a handful of considered
candidates; this is for a few hundred snap judgements, and the whole design
follows from that one difference. Nothing may ever make the swiper wait:
a background thread keeps a deep queue of pre-rendered figures, because he
swipes faster than anything can draw.

    python3 tools/swipe_server.py --port 8096

A run is: type a short character prompt, hit Generate, swipe until you know,
then call the run passed or failed.

  - RIGHT means good, LEFT means not good.
  - FAIL means we never got there and something fundamental is wrong; you pick
    the reasons from checkboxes, and those reasons are the most valuable thing
    this tool produces — they say which axis of the space was missing, which is
    a fix to the generator rather than to any figure.
  - PASS means there is something here; the rights become the seed for a walk
    cycle round.

Temperature anneals: the first `ANNEAL_AFTER` draws are independent samples at
full temperature, and after that roughly `EXPLORE` of them still are while the
rest are perturbations of what has been swiped right. Pure exploration first
because collapsing early onto one preference is exactly the anchoring failure
that wasted the previous rounds; a floor of pure randomness forever because a
generator that only shows you more of what you already liked cannot tell you
about the part of the space you have not seen.

Everything is written to `.scratch/swipe/<run>/` as it happens — one JSON line
per swipe — so killing the server never loses a judgement.

Standard library plus PIL only.
"""
import argparse
import base64
import io
import json
import os
import queue
import random
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, ".scratch", "swipe")
SAFE = re.compile(r"^[a-z0-9_-]{1,48}$")

## How deep the queue of pre-rendered figures runs. He swipes faster than any
## generator draws, so the only defence is a lead measured in hundreds.
QUEUE_DEPTH = 400
## Swipes at full temperature before any biasing begins.
ANNEAL_AFTER = 50
## The share of draws that stay pure random forever, so the stream can always
## still surprise. A generator that only echoes your last preference is a
## mirror, not an explorer.
EXPLORE = 0.30

## The reasons a run can fail. Each names an AXIS of the space rather than a
## fault in a figure, because that is the thing we can act on — "none of them
## were old" is a missing axis, "figure 43 was ugly" is not.
FAIL_REASONS = [
    ("age", "Not enough range of age — everyone looks the same age"),
    ("body", "Not enough range of body type, height or build"),
    ("sex", "Not enough range of sex or gender presentation"),
    ("skin", "Skin tones too narrow"),
    ("hair", "Hair too samey — mass, length, colour or style"),
    ("face", "Faces too samey, or not readable"),
    ("garment", "Clothing too samey, or too simple"),
    ("accessory", "Not enough hats, props, accessories, carried things"),
    ("palette", "Colours too samey, too muddy, or too saturated"),
    ("silhouette", "Silhouettes all the same shape"),
    ("detail", "Too little detail — reads as a blob"),
    ("busy", "Too much detail — reads as noise at game size"),
    ("proportion", "Proportions wrong — head size, limb length"),
    ("style", "Drawing style is wrong for the game, whatever the content"),
    ("notchar", "They do not read as characters/people at all"),
]

_lock = threading.Lock()


# --- the generator -------------------------------------------------------------

def load_generator():
    """`charspace` if it exists, otherwise a placeholder that says so.

    The generator is being written in parallel with this file. Rather than fail
    to start, the server runs with a stand-in so the interface can be used and
    judged on its own; the stand-in draws an obvious placeholder so nobody
    mistakes it for a candidate.
    """
    try:
        import sys
        sys.path.insert(0, os.path.join(ROOT, "tools"))
        import charspace                                   # noqa: PLC0415
        return charspace
    except Exception:                                      # noqa: BLE001
        return None


class Stream:
    """A background thread that keeps a deep queue of rendered figures.

    The queue is the entire point. Drawing happens on a thread that is always
    running ahead; the HTTP handler only ever pops something already finished,
    so a swipe is never waiting on a generator.
    """

    def __init__(self, run, seed, gen, prompt=""):
        self.run = run
        self.gen = gen
        # Parsed once, here, rather than per draw: the prompt does not change
        # during a run, and `parse_prompt` is the generator's business, not the
        # server's. A generator that does not implement it simply gets None,
        # which is how this shipped before the prompt did anything at all.
        self.prompt = prompt
        self.constraints = None
        self.understood = []
        if prompt and hasattr(gen, "parse_prompt"):
            try:
                parsed = gen.parse_prompt(prompt)
                if isinstance(parsed, tuple):
                    self.constraints, self.understood = parsed
                else:
                    self.constraints = parsed
            except Exception:                                # noqa: BLE001
                self.constraints = None
        self.rng = random.Random(seed)
        self.q = queue.Queue(maxsize=QUEUE_DEPTH)
        self.served = 0
        self.liked = []                      # params swiped right, for annealing
        self.n = 0
        self.stop = threading.Event()
        self.t = threading.Thread(target=self._fill, daemon=True)
        self.t.start()

    def _bias(self):
        """What to steer towards, or None while still exploring."""
        with _lock:
            if self.served < ANNEAL_AFTER or not self.liked:
                return None
            if self.rng.random() < EXPLORE:
                return None
            return list(self.liked)

    def _fill(self):
        while not self.stop.is_set():
            try:
                params = self._sample()
                img = self.gen.draw(params)
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                self.n += 1
                item = {
                    "id": "f%05d" % self.n,
                    "params": params,
                    "png": base64.b64encode(buf.getvalue()).decode("ascii"),
                }
                # A timeout rather than a blocking put, so the thread notices
                # the run ending instead of parking forever on a full queue.
                self.q.put(item, timeout=0.5)
            except queue.Full:
                continue
            except Exception as exc:                        # noqa: BLE001
                # One bad sample must not kill the stream; a generator being
                # explored at high temperature will produce invalid corners.
                time.sleep(0.01)
                self.bad = str(exc)

    def _sample(self):
        """One draw, honouring the prompt when the generator understands one."""
        if self.constraints:
            try:
                return self.gen.sample(self.rng, bias=self._bias(),
                                       constraints=self.constraints)
            except TypeError:
                # An older generator without the keyword. Better a figure that
                # ignores the prompt than a run that cannot draw at all.
                pass
        return self.gen.sample(self.rng, bias=self._bias())

    def take(self, k):
        out = []
        for _ in range(k):
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                break
        with _lock:
            self.served += len(out)
        return out

    def reset_taste(self):
        """Forget what has been liked so far and go back to exploring.

        Kevin's first run showed why this is needed: his hit rate ran 29% in
        the first third, 6% in the second and 2% in the last, because his taste
        was *forming while he swiped*. Annealing then steered the stream toward
        the early, pre-taste likes and away from where he was actually going —
        the tool was fighting him. This is the button that says "ignore
        everything I said before now".
        """
        with _lock:
            self.liked = []
            self.served = 0
            self.taste_reset = getattr(self, "taste_reset", 0) + 1

    def mode(self):
        with _lock:
            if self.served < ANNEAL_AFTER or not self.liked:
                return "exploring (%d/%d)" % (self.served, ANNEAL_AFTER)
            return "following your taste (%d likes)" % len(self.liked)

    def like(self, params):
        with _lock:
            self.liked.append(params)
            # Bounded: annealing should follow recent taste, and an unbounded
            # list makes every later draw an average of everything ever liked.
            del self.liked[:-12]


RUNSTATE = {"stream": None, "run": None, "prompt": "", "gen": None}


# --- persistence ---------------------------------------------------------------

def run_dir(run):
    return os.path.join(RUNS, run)


def append(run, row):
    d = run_dir(run)
    os.makedirs(d, exist_ok=True)
    # One JSON object per line, flushed on every swipe: a killed server loses
    # nothing, and the file is readable while it is still being written.
    with open(os.path.join(d, "swipes.jsonl"), "a") as fh:
        fh.write(json.dumps(row) + "\n")
        fh.flush()


def write_meta(run, meta):
    d = run_dir(run)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "run.json")
    cur = {}
    if os.path.exists(path):
        try:
            cur = json.load(open(path))
        except ValueError:
            cur = {}
    cur.update(meta)
    tmp = path + ".tmp"
    json.dump(cur, open(tmp, "w"), indent=1, sort_keys=True)
    os.replace(tmp, path)
    return cur


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>Character Swipe</title>
<style>
:root{--bg:#14161c;--panel:#1c1f28;--line:#2b3040;--text:#e8e6df;--muted:#8b90a0;
      --yes:#4fbf6a;--no:#d2565a;--accent:#e0a63c}
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
body{margin:0;background:var(--bg);color:var(--text);overflow:hidden;
     font:15px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
     height:100dvh;display:flex;flex-direction:column}
header{padding:10px 14px;border-bottom:1px solid var(--line);display:flex;
       gap:12px;align-items:center;flex-wrap:wrap;background:var(--panel)}
h1{font-size:14px;margin:0;letter-spacing:.08em;text-transform:uppercase}
input[type=text]{flex:1;min-width:180px;background:var(--bg);color:var(--text);
      border:1px solid var(--line);border-radius:6px;padding:7px 10px;font:inherit}
button{font:inherit;cursor:pointer;background:var(--bg);color:var(--text);
       border:1px solid var(--line);border-radius:7px;padding:7px 13px}
button:hover{border-color:var(--accent)}
button.p{background:var(--accent);color:#14161c;border-color:var(--accent);font-weight:600}
.tally{color:var(--muted);font-variant-numeric:tabular-nums;margin-left:auto}
.tally b{color:var(--text)}
.tally .y{color:var(--yes)} .tally .n{color:var(--no)}
main{flex:1;position:relative;overflow:hidden;touch-action:none}
.card{position:absolute;left:50%;top:50%;width:min(74vw,360px);
      transform:translate(-50%,-50%);background:var(--panel);border:2px solid var(--line);
      border-radius:16px;padding:16px;display:flex;flex-direction:column;
      align-items:center;gap:10px;box-shadow:0 18px 48px rgba(0,0,0,.55);
      will-change:transform;user-select:none}
.card canvas{image-rendering:pixelated;background:#0f1116;border-radius:10px;width:100%;
             height:auto;aspect-ratio:1/1.1}
.cap{color:var(--muted);font-size:11px;text-align:center;min-height:2.4em}
.stamp{position:absolute;top:18px;font-size:26px;font-weight:800;letter-spacing:.1em;
       padding:4px 12px;border-radius:8px;border:3px solid;opacity:0;pointer-events:none}
.stamp.y{right:16px;color:var(--yes);border-color:var(--yes);transform:rotate(12deg)}
.stamp.n{left:16px;color:var(--no);border-color:var(--no);transform:rotate(-12deg)}
footer{padding:10px 14px;border-top:1px solid var(--line);display:flex;gap:10px;
       align-items:center;justify-content:center;background:var(--panel);flex-wrap:wrap}
footer .hint{color:var(--muted);font-size:12px}
.big{font-size:20px;padding:9px 22px}
.sheet{position:absolute;inset:0;background:rgba(10,11,15,.93);display:none;
       overflow:auto;padding:22px}
.sheet.on{display:block}
.sheet .inner{max-width:620px;margin:0 auto}
label.chk{display:flex;gap:10px;align-items:flex-start;padding:9px 11px;
          border:1px solid var(--line);border-radius:8px;margin-bottom:7px;cursor:pointer}
label.chk:hover{border-color:var(--accent)}
label.chk input{margin-top:3px;width:17px;height:17px}
.empty{position:absolute;left:50%;top:50%;transform:translate(-50%,-50%);
       color:var(--muted);text-align:center;width:80%}
</style></head><body>
<header>
  <h1>Swipe</h1>
  <input type="text" id="prompt" placeholder="a short character prompt — e.g. 'weathered fisherman, cold coast'">
  <button class="p" id="go">Generate</button>
  <button id="taste" title="Forget what I have liked so far and explore again">Reset taste</button>
  <span class="hint" id="mode" style="color:var(--muted);font-size:12px"></span>
  <span class="hint" id="understood" style="color:var(--muted);font-size:12px"></span>
  <span class="tally"><span class="y"><b id="ny">0</b> right</span> ·
    <span class="n"><b id="nn">0</b> left</span> · <b id="nq">0</b> queued</span>
</header>
<main id="stage">
  <div class="empty" id="empty">Type a prompt and hit Generate.<br>
    Then swipe, or use <b>&larr;</b> / <b>&rarr;</b>.</div>
</main>
<footer>
  <button class="big" id="no">&larr; No</button>
  <button class="big" id="yes">Yes &rarr;</button>
  <span class="hint">arrows or drag &nbsp;·&nbsp; <b>Z</b> undo</span>
  <button id="fail">Fail run</button>
  <button id="pass">Pass run</button>
</footer>

<div class="sheet" id="failsheet"><div class="inner">
  <h2>What was fundamentally wrong?</h2>
  <p class="hint">Each of these names an axis of the space, not a bad figure —
     that is what makes them fixable. Tick everything that applies.</p>
  <div id="reasons"></div>
  <p><textarea id="failnote" rows="3" style="width:100%;background:var(--bg);
     color:var(--text);border:1px solid var(--line);border-radius:8px;padding:9px;
     font:inherit" placeholder="anything else (optional)"></textarea></p>
  <button class="p big" id="failsubmit">Submit</button>
  <button id="failcancel">Cancel</button>
</div></div>

<div class="sheet" id="donesheet"><div class="inner" id="doneinner"></div></div>

<script>
const S = {run:null, deck:[], ny:0, nn:0, card:null, hist:[], busy:false};
const stage = document.getElementById('stage');

function api(path, body) {
  return fetch(path, {method:'POST', headers:{'Content-Type':'application/json'},
                      body:JSON.stringify(body||{})}).then(r=>r.json());
}

function paint(cv, b64) {
  const img = new Image();
  img.onload = () => {
    // Nearest-neighbour at an integer scale: a 32x48 figure blown up by a
    // fractional factor grows seams and half-pixels, which is the one thing
    // that would make every candidate look equally bad.
    const z = Math.max(2, Math.floor(Math.min(cv.width/img.width, cv.height/img.height)));
    const ctx = cv.getContext('2d');
    ctx.imageSmoothingEnabled = false;
    ctx.clearRect(0,0,cv.width,cv.height);
    const w = img.width*z, h = img.height*z;
    ctx.drawImage(img, (cv.width-w)/2, (cv.height-h)/2, w, h);
  };
  img.src = 'data:image/png;base64,' + b64;
}

function show() {
  document.getElementById('nq').textContent = S.deck.length;
  if (S.card) { S.card.remove(); S.card = null; }
  if (!S.deck.length) {
    document.getElementById('empty').style.display = S.run ? 'block' : 'block';
    document.getElementById('empty').innerHTML = S.run
      ? 'Drawing…' : 'Type a prompt and hit Generate.<br>Then swipe, or use <b>&larr;</b> / <b>&rarr;</b>.';
    if (S.run) top_up(true);
    return;
  }
  document.getElementById('empty').style.display = 'none';
  const item = S.deck[0];
  const el = document.createElement('div');
  el.className = 'card';
  el.innerHTML = '<canvas width="640" height="704"></canvas>' +
                 '<div class="cap">' + (item.caption||'') + '</div>' +
                 '<div class="stamp y">YES</div><div class="stamp n">NO</div>';
  stage.appendChild(el);
  paint(el.querySelector('canvas'), item.png);
  S.card = el;
  drag(el);
  if (S.deck.length < 12) top_up(false);
}

function decide(dir) {          // dir: +1 right/yes, -1 left/no
  if (!S.deck.length || S.busy) return;
  const item = S.deck.shift();
  S.hist.push(item);
  if (dir > 0) { S.ny++; } else { S.nn++; }
  document.getElementById('ny').textContent = S.ny;
  document.getElementById('nn').textContent = S.nn;
  if (S.card) {
    const c = S.card; S.card = null;
    c.style.transition = 'transform .22s ease-out, opacity .22s ease-out';
    c.style.transform = 'translate(' + (dir>0?'60vw':'-60vw') + ',-50%) rotate(' +
                        (dir>0?18:-18) + 'deg)';
    c.style.opacity = '0';
    setTimeout(()=>c.remove(), 230);
  }
  api('/swipe', {run:S.run, id:item.id, verdict: dir>0 ? 'right':'left'});
  show();
}

function undo() {
  if (!S.hist.length) return;
  const item = S.hist.pop();
  S.deck.unshift(item);
  api('/undo', {run:S.run, id:item.id}).then(r => {
    S.ny = r.right; S.nn = r.left;
    document.getElementById('ny').textContent = S.ny;
    document.getElementById('nn').textContent = S.nn;
  });
  show();
}

function top_up(urgent) {
  if (!S.run || S.busy) return;
  S.busy = true;
  api('/next', {run:S.run, want: urgent ? 24 : 24}).then(r => {
    S.busy = false;
    if (r.mode) document.getElementById('mode').textContent = r.mode;
    if (r.items && r.items.length) {
      S.deck = S.deck.concat(r.items);
      if (!S.card) show(); else document.getElementById('nq').textContent = S.deck.length;
    } else if (urgent) {
      setTimeout(()=>top_up(true), 350);     // generator still warming up
    }
  }).catch(()=>{ S.busy=false; });
}

function drag(el) {
  let x0=null, dx=0;
  const y = el.querySelector('.stamp.y'), n = el.querySelector('.stamp.n');
  const down = e => { x0 = (e.touches?e.touches[0]:e).clientX; el.style.transition='none'; };
  const move = e => {
    if (x0===null) return;
    dx = (e.touches?e.touches[0]:e).clientX - x0;
    el.style.transform = 'translate(calc(-50% + '+dx+'px),-50%) rotate('+(dx/18)+'deg)';
    y.style.opacity = dx > 0 ? Math.min(1, dx/90) : 0;
    n.style.opacity = dx < 0 ? Math.min(1, -dx/90) : 0;
    if (e.cancelable) e.preventDefault();
  };
  const up = () => {
    if (x0===null) return;
    const d = dx; x0 = null; dx = 0;
    if (Math.abs(d) > 70) { decide(d > 0 ? 1 : -1); return; }
    el.style.transition = 'transform .18s'; el.style.transform = 'translate(-50%,-50%)';
    y.style.opacity = 0; n.style.opacity = 0;
  };
  el.addEventListener('mousedown', down); el.addEventListener('touchstart', down, {passive:true});
  window.addEventListener('mousemove', move); el.addEventListener('touchmove', move, {passive:false});
  window.addEventListener('mouseup', up); el.addEventListener('touchend', up);
}

document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;
  if (e.key === 'ArrowRight') decide(1);
  else if (e.key === 'ArrowLeft') decide(-1);
  else if (e.key.toLowerCase() === 'z') undo();
  else return;
  e.preventDefault();
});
document.getElementById('yes').onclick = ()=>decide(1);
document.getElementById('no').onclick = ()=>decide(-1);

document.getElementById('go').onclick = () => {
  const p = document.getElementById('prompt').value.trim();
  api('/start', {prompt:p}).then(r => {
    S.run = r.run; S.deck = []; S.hist = []; S.ny = 0; S.nn = 0;
    document.getElementById('ny').textContent = 0;
    document.getElementById('nn').textContent = 0;
    if (r.warning) alert(r.warning);
    const u = document.getElementById('understood');
    u.textContent = (r.understood && r.understood.length)
      ? 'applying: ' + r.understood.join(', ')
      : (S.run ? 'prompt not applied' : '');
    show(); top_up(true);
  });
};

// --- fail sheet
const reasons = document.getElementById('reasons');
fetch('/reasons').then(r=>r.json()).then(rs => {
  reasons.innerHTML = rs.map(r =>
    '<label class="chk"><input type="checkbox" value="'+r[0]+'"><span>'+r[1]+'</span></label>'
  ).join('');
});
document.getElementById('taste').onclick = () => {
  api('/taste', {run:S.run}).then(r => {
    document.getElementById('mode').textContent = r.mode || '';
    S.deck = [];                 // drop the queued stream, it was steered
    show(); top_up(true);
  });
};
document.getElementById('fail').onclick = ()=>document.getElementById('failsheet').classList.add('on');
document.getElementById('failcancel').onclick = ()=>document.getElementById('failsheet').classList.remove('on');
document.getElementById('failsubmit').onclick = () => {
  const picked = [...reasons.querySelectorAll('input:checked')].map(i=>i.value);
  api('/finish', {run:S.run, outcome:'fail', reasons:picked,
                  note:document.getElementById('failnote').value}).then(done);
};
document.getElementById('pass').onclick = () => api('/finish', {run:S.run, outcome:'pass'}).then(done);

function done(r) {
  document.getElementById('failsheet').classList.remove('on');
  const d = document.getElementById('donesheet');
  document.getElementById('doneinner').innerHTML =
    '<h2>Run ' + r.outcome.toUpperCase() + '</h2><p>' + r.summary +
    '</p><p class="hint">Written to ' + r.path + '</p>' +
    '<button class="p big" onclick="location.reload()">New run</button>';
  d.classList.add('on');
}
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass                       # the swiper moved on; nothing to do

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._send(200, PAGE, "text/html; charset=utf-8")
        elif path == "/reasons":
            self._send(200, json.dumps(FAIL_REASONS))
        else:
            self._send(404, "{}")

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._body()

        if path == "/start":
            gen = load_generator()
            run = time.strftime("run-%Y%m%d-%H%M%S")
            seed = int(time.time() * 1000) & 0xFFFFFFFF
            warning = None
            if gen is None:
                warning = ("charspace.py is not ready yet — the generator is "
                           "still being written. The interface works; the "
                           "figures will be placeholders until it lands.")
                self._send(200, json.dumps({"run": run, "warning": warning}))
                return
            if RUNSTATE["stream"] is not None:
                RUNSTATE["stream"].stop.set()
            prompt = str(body.get("prompt", ""))
            RUNSTATE["stream"] = Stream(run, seed, gen, prompt)
            RUNSTATE["run"] = run
            RUNSTATE["prompt"] = prompt
            st = RUNSTATE["stream"]
            write_meta(run, {"run": run, "prompt": prompt,
                             "seed": seed, "started": time.time(),
                             "constraints": st.constraints,
                             "understood": st.understood,
                             "anneal_after": ANNEAL_AFTER, "explore": EXPLORE})
            # Saying what was understood is the honest half of a prompt box.
            # It silently did nothing for a whole session, which is worse than
            # having no box at all — at least an absent box makes no promise.
            if prompt and not st.constraints:
                warning = ("The prompt was not understood, so this run is "
                           "unconstrained. Nothing in it was applied.")
            self._send(200, json.dumps({"run": run, "warning": warning,
                                        "understood": st.understood}))
            return

        st = RUNSTATE["stream"]
        if path == "/next":
            if st is None:
                self._send(200, json.dumps({"items": []}))
                return
            want = max(1, min(48, int(body.get("want", 24))))
            items = st.take(want)
            # `params` stays on the server: the page only needs a picture and an
            # id, and shipping a parameter dict per card would multiply the
            # payload for something the browser never reads.
            with _lock:
                st.pending = getattr(st, "pending", {})
                for it in items:
                    st.pending[it["id"]] = it["params"]
            self._send(200, json.dumps({"mode": st.mode(), "items": [
                {"id": i["id"], "png": i["png"]} for i in items]}))
            return

        if path == "/swipe":
            if st is None:
                self._send(200, '{"ok":false}')
                return
            cid = str(body.get("id", ""))
            verdict = str(body.get("verdict", ""))
            params = getattr(st, "pending", {}).get(cid)
            if verdict == "right" and params is not None:
                st.like(params)
            append(RUNSTATE["run"], {"id": cid, "verdict": verdict,
                                     "t": time.time(), "params": params})
            self._send(200, '{"ok":true}')
            return

        if path == "/taste":
            if st is not None:
                st.reset_taste()
                append(RUNSTATE["run"], {"verdict": "taste_reset", "t": time.time()})
            self._send(200, json.dumps({"mode": st.mode() if st else ""}))
            return

        if path == "/undo":
            # The log is append-only on purpose — an undo is an event, not an
            # erasure, so the record still says what happened.
            append(RUNSTATE["run"], {"id": str(body.get("id", "")),
                                     "verdict": "undo", "t": time.time()})
            rows = read_swipes(RUNSTATE["run"])
            self._send(200, json.dumps({"right": rows["right"], "left": rows["left"]}))
            return

        if path == "/finish":
            run = RUNSTATE["run"] or str(body.get("run", ""))
            outcome = str(body.get("outcome", "fail"))
            counts = read_swipes(run)
            meta = write_meta(run, {
                "outcome": outcome,
                "reasons": body.get("reasons", []),
                "note": str(body.get("note", "")),
                "finished": time.time(),
                "right": counts["right"], "left": counts["left"],
            })
            if st is not None:
                st.stop.set()
            summary = ("%d swiped right, %d left." % (counts["right"], counts["left"]))
            if outcome == "fail" and meta.get("reasons"):
                summary += " Reasons: " + ", ".join(meta["reasons"]) + "."
            self._send(200, json.dumps({"outcome": outcome, "summary": summary,
                                        "path": run_dir(run)}))
            return

        self._send(404, "{}")


def read_swipes(run):
    """Counts, with undo applied. The log keeps every event; this is the view."""
    right = left = 0
    seen = []
    p = os.path.join(run_dir(run), "swipes.jsonl")
    if not os.path.exists(p):
        return {"right": 0, "left": 0}
    for line in open(p):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("verdict") == "undo":
            for i in range(len(seen) - 1, -1, -1):
                if seen[i]["id"] == row.get("id"):
                    if seen[i]["verdict"] == "right":
                        right -= 1
                    else:
                        left -= 1
                    del seen[i]
                    break
            continue
        seen.append(row)
        if row.get("verdict") == "right":
            right += 1
        else:
            left += 1
    return {"right": right, "left": left}


class DualStackServer(ThreadingHTTPServer):
    """Listens on IPv4 and IPv6 at once.

    Windows resolves `localhost` to ::1 before 127.0.0.1, and WSL forwards each
    family separately. An IPv4-only listener is therefore reachable at
    http://127.0.0.1:PORT from Windows and *times out* at http://localhost:PORT
    — which looks exactly like a dead server to the person typing the URL, and
    cost us a round trip to work out. Binding :: with V6ONLY off answers both.
    """

    address_family = socket.AF_INET6
    daemon_threads = True

    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except (AttributeError, OSError):
            pass                      # a v4-only host; the v4 path still works
        super().server_bind()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8096)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    os.makedirs(RUNS, exist_ok=True)
    try:
        srv = DualStackServer(("::", args.port), Handler)
    except OSError:
        # No IPv6 on this box. Fall back rather than refuse to start.
        srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("swipe: http://%s:%d  (runs under %s)" % (args.host, args.port, RUNS))
    srv.serve_forever()


if __name__ == "__main__":
    main()
