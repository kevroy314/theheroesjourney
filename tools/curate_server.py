#!/usr/bin/env python3
"""A labelling gallery for generated candidates of any kind, served over HTTP.

Generators are cheap and judgement is not. Everything in this project's art is
authored in code -- figures in `make_sprites.py`, props and materials in
`make_tiles.py`, whole scenes through `worldshot.sh` -- so producing sixty
candidates costs minutes and no image quota, while deciding which six are good
costs a person's attention. This server exists to spend as little of that as
possible per candidate: three keys, and a batch of forty is ninety seconds.

It is deliberately kind-agnostic. A candidate is an id, a recipe and one or
more pictures; whether it is a townsperson, a barrel, a tavern frontage or a
mob makes no difference here. Adding a new kind means writing a generator that
emits the manifest below -- it does not mean touching this file.

    .scratch/candidates/<batch>/manifest.json
    {
      "batch":  "props",            # url segment, [a-z0-9_-]
      "kind":   "prop",             # shown as a label; free text
      "layout": "grid"|"wide"|"compare",
      "note":   "one line on what varies across this batch",
      "candidates": [
        {"id": "p001",
         "recipe": {"axis": "value", ...},        # rendered as chips
         "images": [{"label": "game size", "b64": "..."}, ...]}
      ]
    }

`layout` is a hint about picture size, not a different interface: `grid` for
sprites and props, `wide` for buildings and scenes that need the room, and
`compare` for a straight A-or-B between two variants of one thing.

Verdicts live beside the manifest in `verdicts.json` and are written on every
keypress, so killing the server never loses a decision. `tools/curate.py`
reads them back.

    python3 tools/curate_server.py --port 8095

Binds 0.0.0.0 on purpose. WSL2 only forwards a listener to the Windows host
when it binds the wildcard address -- a server on 127.0.0.1 works perfectly
from inside WSL and times out from everywhere else, which is a maddening way
to lose an hour.

Standard library only, so it runs anywhere the generators do.
"""
import argparse
import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = os.path.join(ROOT, ".scratch", "candidates")
SAFE = re.compile(r"^[a-z0-9_-]{1,40}$")

_lock = threading.Lock()


# --- batches on disk ------------------------------------------------------------

def batch_dir(name):
    return DIR if name == "_root" else os.path.join(DIR, name)


def read_manifest(name):
    """One batch, normalised.

    The first generator written wrote a flat manifest with `big` and `small`
    keys straight in `.scratch/candidates/`, and there are verdicts against it
    already. Rather than migrate a file a person has spent attention on, that
    shape is accepted and converted here -- the cost is this function, and the
    alternative is throwing away judgements.
    """
    path = os.path.join(batch_dir(name), "manifest.json")
    try:
        with open(path) as fh:
            man = json.load(fh)
    except (OSError, ValueError):
        return None

    out = []
    for c in man.get("candidates", []):
        if "error" in c:
            continue                       # a build that threw is not a candidate
        images = c.get("images")
        if not images:
            images = [{"label": k, "b64": c[k]}
                      for k in ("small", "big") if c.get(k)]
        if not images:
            continue
        out.append({"id": c["id"], "recipe": c.get("recipe", {}), "images": images})
    return {
        "batch": name,
        "kind": man.get("kind", "candidate"),
        "layout": man.get("layout", "grid"),
        "note": man.get("note", ""),
        "candidates": out,
    }


def batches():
    """Every batch on disk, newest manifest first."""
    found = []
    if os.path.isfile(os.path.join(DIR, "manifest.json")):
        found.append("_root")
    if os.path.isdir(DIR):
        for entry in sorted(os.listdir(DIR)):
            if SAFE.match(entry) and os.path.isfile(
                    os.path.join(DIR, entry, "manifest.json")):
                found.append(entry)
    rows = []
    for name in found:
        man = read_manifest(name)
        if man is None:
            continue
        v = load_verdicts(name)
        rows.append({
            "batch": name, "kind": man["kind"], "note": man["note"],
            "total": len(man["candidates"]),
            "judged": sum(1 for c in man["candidates"] if v.get(c["id"])),
            "keep": sum(1 for c in man["candidates"] if v.get(c["id"]) == "keep"),
            "mtime": os.path.getmtime(os.path.join(batch_dir(name), "manifest.json")),
        })
    rows.sort(key=lambda r: -r["mtime"])
    return rows


def verdict_path(name):
    return os.path.join(batch_dir(name), "verdicts.json")


def load_verdicts(name):
    try:
        with open(verdict_path(name)) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_verdicts(name, v):
    # Write-then-rename. The interesting failure is being killed halfway through
    # the write and coming back to a truncated file with an afternoon of
    # judgements in it.
    d = batch_dir(name)
    os.makedirs(d, exist_ok=True)
    tmp = verdict_path(name) + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(v, fh, indent=1, sort_keys=True)
    os.replace(tmp, verdict_path(name))


# --- the page -------------------------------------------------------------------

CSS = r"""
:root {
  --bg:#14161c; --panel:#1c1f28; --line:#2b3040; --text:#e8e6df; --muted:#8b90a0;
  --keep:#6ec177; --reject:#d2686a; --maybe:#d9a441; --accent:#e0a63c;
}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);
     font:14px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace}
a{color:var(--accent)}
header{position:sticky;top:0;z-index:5;background:var(--panel);
       border-bottom:1px solid var(--line);padding:10px 16px;
       display:flex;gap:16px;align-items:center;flex-wrap:wrap}
h1{font-size:15px;margin:0;letter-spacing:.06em;text-transform:uppercase}
.note{color:var(--muted)}
.count{color:var(--muted)} .count b{color:var(--text);font-variant-numeric:tabular-nums}
.keys{color:var(--muted);margin-left:auto}
kbd{background:var(--bg);border:1px solid var(--line);border-radius:4px;
    padding:1px 6px;color:var(--text)}
button{font:inherit;cursor:pointer;background:var(--bg);color:var(--text);
       border:1px solid var(--line);border-radius:6px;padding:5px 10px}
button:hover{border-color:var(--accent)}
main{display:grid;gap:14px;padding:16px}
main.grid{grid-template-columns:repeat(auto-fill,minmax(230px,1fr))}
main.wide{grid-template-columns:repeat(auto-fill,minmax(430px,1fr))}
main.compare{grid-template-columns:1fr 1fr;max-width:1400px;margin:0 auto}
.card{background:var(--panel);border:2px solid var(--line);border-radius:10px;
      padding:10px;display:flex;flex-direction:column;gap:8px}
.card.sel{border-color:var(--accent)}
.card.keep{border-color:var(--keep)}
.card.reject{border-color:var(--reject);opacity:.42}
.card.maybe{border-color:var(--maybe)}
.art{display:flex;gap:10px;align-items:flex-end;justify-content:center;
     background:#0f1116;border-radius:6px;padding:8px;min-height:110px;flex-wrap:wrap}
.shot{display:flex;flex-direction:column;align-items:center;gap:3px}
.shot span{font-size:10px;color:var(--muted)}
img{image-rendering:pixelated;max-width:100%}
.id{color:var(--muted);font-size:12px;display:flex;justify-content:space-between}
.chips{display:flex;flex-wrap:wrap;gap:4px}
.chip{font-size:11px;background:var(--bg);border:1px solid var(--line);
      border-radius:4px;padding:1px 6px;color:var(--muted)}
.chip b{color:var(--text);font-weight:500}
.row{display:flex;gap:6px}.row button{flex:1}
.k{border-color:#2f5a35}.k:hover{background:#1d3320}
.x{border-color:#5c2f31}.x:hover{background:#331d1e}
.m{border-color:#5c4a1f}.m:hover{background:#332a12}
table{border-collapse:collapse;width:100%;max-width:900px}
td,th{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line)}
th{color:var(--muted);font-weight:500;font-size:12px;text-transform:uppercase}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;min-width:90px}
.bar i{display:block;height:100%;background:var(--keep)}
"""

INDEX = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Curation</title><style>__CSS__</style></head><body>
<header><h1>Curation</h1><span class="note">pick a batch</span></header>
<main style="display:block;padding:16px">
<table><tr><th>batch</th><th>kind</th><th>what varies</th><th>judged</th><th>keep</th><th></th></tr>
__ROWS__
</table>
<p class="note" id="empty"></p>
</main></body></html>
"""

PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__BATCH__ · Curation</title><style>__CSS__</style></head><body>
<header>
  <h1><a href="/">&larr;</a> __BATCH__</h1>
  <span class="note">__NOTE__</span>
  <span class="count"><b id="done">0</b>/<b id="total">0</b> judged
    &nbsp;·&nbsp; <b id="nkeep">0</b> keep &nbsp;·&nbsp; <b id="nmaybe">0</b> maybe</span>
  <button id="jump">Next unjudged</button>
  <button id="hide">Hide rejected</button>
  <span class="keys"><kbd>K</kbd> keep <kbd>X</kbd> reject <kbd>M</kbd> maybe
    <kbd>&larr;</kbd><kbd>&rarr;</kbd> move</span>
</header>
<main id="grid" class="__LAYOUT__"></main>
<script>
const DATA = __DATA__, BATCH = "__BATCH__";
let verdicts = __VERDICTS__, sel = 0, hiding = false;

const chip = (k, v) => '<span class="chip">' + k + ' <b>' + v + '</b></span>';

function render() {
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  DATA.forEach((c, i) => {
    const v = verdicts[c.id] || '';
    if (hiding && v === 'reject') return;
    const el = document.createElement('div');
    el.className = 'card' + (v ? ' ' + v : '') + (i === sel ? ' sel' : '');
    el.innerHTML =
      '<div class="art">' + c.images.map(im =>
        '<div class="shot"><img src="data:image/png;base64,' + im.b64 +
        '" alt="' + c.id + ' ' + (im.label || '') + '">' +
        (im.label ? '<span>' + im.label + '</span>' : '') + '</div>').join('') +
      '</div>' +
      '<div class="id"><span>' + c.id + '</span><span>' + (v || '—') + '</span></div>' +
      '<div class="chips">' +
        Object.keys(c.recipe).map(k => chip(k, c.recipe[k])).join('') +
      '</div>' +
      '<div class="row"><button class="k">keep</button>' +
      '<button class="m">maybe</button><button class="x">reject</button></div>';
    el.querySelector('.k').onclick = () => judge(i, 'keep');
    el.querySelector('.m').onclick = () => judge(i, 'maybe');
    el.querySelector('.x').onclick = () => judge(i, 'reject');
    el.onclick = e => { if (e.target.tagName !== 'BUTTON') { sel = i; render(); } };
    grid.appendChild(el);
  });
  const vals = Object.values(verdicts);
  document.getElementById('total').textContent = DATA.length;
  document.getElementById('done').textContent = vals.length;
  document.getElementById('nkeep').textContent = vals.filter(v => v === 'keep').length;
  document.getElementById('nmaybe').textContent = vals.filter(v => v === 'maybe').length;
  const cur = grid.querySelector('.sel');
  if (cur) cur.scrollIntoView({ block: 'nearest' });
}

function judge(i, verdict) {
  const id = DATA[i].id;
  // The same verdict twice clears it, so a misfire is one keypress to undo
  // rather than a decision you are stuck with.
  if (verdicts[id] === verdict) delete verdicts[id]; else verdicts[id] = verdict;
  fetch('/verdict', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ batch: BATCH, id: id, verdict: verdicts[id] || null })
  }).catch(() => {});
  if (i === sel) sel = Math.min(DATA.length - 1, sel + 1);
  render();
}

document.addEventListener('keydown', e => {
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  const k = e.key.toLowerCase();
  if (k === 'k') judge(sel, 'keep');
  else if (k === 'x') judge(sel, 'reject');
  else if (k === 'm') judge(sel, 'maybe');
  else if (e.key === 'ArrowRight') { sel = Math.min(DATA.length - 1, sel + 1); render(); }
  else if (e.key === 'ArrowLeft') { sel = Math.max(0, sel - 1); render(); }
  else return;
  e.preventDefault();
});

document.getElementById('jump').onclick = () => {
  let n = DATA.findIndex((c, i) => i > sel && !verdicts[c.id]);
  if (n < 0) n = DATA.findIndex(c => !verdicts[c.id]);
  sel = n < 0 ? 0 : n;
  render();
};
document.getElementById('hide').onclick = e => {
  hiding = !hiding;
  e.target.textContent = hiding ? 'Show rejected' : 'Hide rejected';
  render();
};
render();
</script></body></html>
"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        pass                                   # a line per asset click is noise

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _index(self):
        rows = batches()
        if not rows:
            html = (INDEX.replace("__CSS__", CSS).replace("__ROWS__", "")
                    .replace('id="empty"></p>',
                             'id="empty">No batches yet. Run a generator, '
                             'e.g. <code>python3 tools/candidates.py</code>.</p>'))
            self._send(200, html, "text/html; charset=utf-8")
            return
        out = []
        for r in rows:
            pct = 0 if not r["total"] else int(100.0 * r["judged"] / r["total"])
            label = "candidates" if r["batch"] == "_root" else r["batch"]
            out.append(
                '<tr><td><a href="/b/%s">%s</a></td><td>%s</td><td class="note">%s</td>'
                '<td>%d/%d</td><td>%d</td>'
                '<td><div class="bar"><i style="width:%d%%"></i></div></td></tr>'
                % (r["batch"], label, r["kind"], r["note"] or "&mdash;",
                   r["judged"], r["total"], r["keep"], pct))
        html = (INDEX.replace("__CSS__", CSS)
                     .replace("__ROWS__", "\n".join(out))
                     .replace('id="empty"></p>', 'id="empty"></p>'))
        self._send(200, html, "text/html; charset=utf-8")

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self._index()
            return
        if path.startswith("/b/"):
            name = path[3:].strip("/")
            if not (name == "_root" or SAFE.match(name)):
                self._send(404, "{}")
                return
            man = read_manifest(name)
            if man is None:
                self._send(404, "<h1>No such batch</h1>", "text/html; charset=utf-8")
                return
            with _lock:
                page = (PAGE.replace("__CSS__", CSS)
                            .replace("__DATA__", json.dumps(man["candidates"]))
                            .replace("__VERDICTS__", json.dumps(load_verdicts(name)))
                            .replace("__LAYOUT__", man["layout"])
                            .replace("__NOTE__", man["note"] or man["kind"])
                            .replace("__BATCH__", name))
            self._send(200, page, "text/html; charset=utf-8")
            return
        if path.startswith("/verdicts/"):
            name = path[len("/verdicts/"):].strip("/")
            if not (name == "_root" or SAFE.match(name)):
                self._send(404, "{}")
                return
            with _lock:
                self._send(200, json.dumps(load_verdicts(name)))
            return
        self._send(404, "{}")

    def do_POST(self):
        if self.path != "/verdict":
            self._send(404, "{}")
            return
        n = int(self.headers.get("Content-Length", 0))
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self._send(400, '{"ok":false}')
            return
        name = str(body.get("batch", "_root"))
        cid = str(body.get("id", ""))
        verdict = body.get("verdict")
        if not cid or not (name == "_root" or SAFE.match(name)):
            self._send(400, '{"ok":false}')
            return
        with _lock:
            v = load_verdicts(name)
            if verdict in ("keep", "reject", "maybe"):
                v[cid] = verdict
            else:
                v.pop(cid, None)
            save_verdicts(name, v)
            kept = sum(1 for x in v.values() if x == "keep")
        self._send(200, json.dumps({"ok": True, "keep": kept}))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8095)
    ap.add_argument("--host", default="0.0.0.0")
    args = ap.parse_args()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("curate: http://%s:%d  (batches under %s)" % (args.host, args.port, DIR))
    srv.serve_forever()


if __name__ == "__main__":
    main()
