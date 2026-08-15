---
name: godot-web-deploy
description: Build, cache, serve and deploy the Godot web export for The Heroes' Journey — content hashing, brotli precompression, the PWA (manifest + service worker), the nginx container, and the home reverse proxy behind Google OAuth. Use when touching run.sh, web.conf, docker-compose.yml, export_presets.cfg, anything under web/, or when load time or "my change didn't show up" is the problem.
---

# Skill: godot-web-deploy

## The shape of it

```
run.sh  ->  godot --export-release "Web" build/index.html
        ->  content-hash every artefact, rewrite index.html
        ->  precompress .gz/.br siblings
        ->  copy web/ (manifest, sw.js, pwa.js, icons) into build/
        ->  docker compose up -d --build --force-recreate
```

`build/` is bind-mounted read-only into an Alpine + `nginx-mod-http-brotli`
container on port 8070. The public URL is an nginx server block in
`~/homie/nginx-proxy/nginx.conf` behind the shared Google oauth2-proxy.

## The caching model — do not break this

| What | Header | Why |
|---|---|---|
| `index.html` | `no-cache` | Cached but revalidated every load. 6 KB; a 304 is free. It is the only thing that names the other URLs. |
| `index.<12hex>.*` | `public, max-age=31536000, immutable` | The URL is derived from the file's own bytes. Different bytes → different URL, so a hit can never be stale. |
| `sw.js`, `manifest.webmanifest`, `icons/*` | `no-cache` | Addressed by fixed name; a pinned service worker is the one cache you cannot clear from the server. |

**How a rebuild reaches users:** index.html is revalidated → 200 with new HTML →
new hashed URLs are cache misses → only changed assets download. Nothing is ever
manually cache-cleared.

Two hashes, deliberately: one shared by the engine set (`index.js`, `index.wasm`,
both audio worklets — the loader resolves worklets as
`${executable}.audio.worklet.js`, so they must share a prefix) and a separate one
for the pck via `mainPack`. That is what makes a code-only rebuild re-download
226 KB instead of 40 MB.

Numbers to keep honest against: cold load ~10.7 MB (down from 43.6), warm reload
**0 bytes** plus one 304, post-rebuild warm load = pck only.

## Gotchas

- **`build/.gdignore` must exist.** Without it Godot imports its own exported
  PNGs back into the project and ships them inside the pck.
- **`docker compose up -d` is not enough** — `web.conf` is bind-mounted and read
  only at startup. Use `--force-recreate` (run.sh does).
- **Stock `nginx:alpine` has `gzip_static` but no brotli.** Hence the Dockerfile:
  `alpine` + `nginx` + `nginx-mod-http-brotli`. Alpine includes `conf.d` at the
  *root* context, so the site config mounts to `/etc/nginx/http.d/default.conf`.
- **nginx has no `.webmanifest` MIME type**, and a bare `types {}` block in a
  server replaces the whole inherited map. Use
  `location = /manifest.webmanifest { default_type application/manifest+json; }`.
- **`add_header` in a location replaces inherited ones** — repeat
  `Cache-Control` and `Vary` in every location that sets any header.
- **Brotli q11 over 40 MB takes ~145 s.** run.sh skips compression when the
  hashed name already exists, so it is paid once per Godot version. Override
  with `BROTLI_QUALITY=5` while iterating.
- **`exclude_filter="art/*"`** keeps unreferenced art out of the pck. Include
  specific files only when something loads them.

## The PWA

`web/` holds `manifest.webmanifest`, `sw.js`, `pwa.js` and `icons/`, copied into
`build/` verbatim (not hashed). `tools/make_icons.py` regenerates the icons from
`data/themes/firstlight.json`, so icon and app never disagree on palette.

The service worker is written by hand rather than generated, because Godot's
generated one is cache-first on a version string and leaves users a full reload
behind. Ours mirrors the server model exactly:

- documents → **network-first** (cached copy is the offline fallback)
- `index.<hash>.*` → **cache-first** (immutable, so a hit is always correct)
- `/oauth2/*` → never intercepted
- `skipWaiting()` + `clients.claim()` so an update applies on the next load
- on activate, drop cached assets the current index.html no longer references

`cacheable()` refuses anything redirected — when the OAuth session expires the
proxy answers with a redirect to Google, and caching that as index.html would
pin the app to a login screen.

**Service workers need a secure context.** They do not register on the plain-HTTP
LAN address; use `localhost` or the HTTPS hostname. That is a browser rule, not
a bug.

## Verifying

```bash
curl -sI http://0.0.0.0:8070/ | grep -i cache-control          # no-cache
curl -s -H 'Accept-Encoding: br' -o /dev/null \
     -w '%{size_download} %{content_type}\n' http://0.0.0.0:8070/index.<hash>.wasm
```

Content-Type must stay `application/wasm` on every encoding —
`WebAssembly.instantiateStreaming` requires it. In the browser, confirm the
worker is live:

```js
navigator.serviceWorker.getRegistrations()   // active + state "activated"
caches.keys()                                // hj-html-v1, hj-assets-v1
```
