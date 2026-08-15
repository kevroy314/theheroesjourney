# Build, cache and deploy

```bash
npm run build        # export + content-hash + precompress + serve
npm run serve        # serving config only (skips the export)
npm run stop
BROTLI_QUALITY=5 npm run build     # while iterating
```

`run.sh` does five things in order: Godot export → content-hash every artefact
and rewrite `index.html` → precompress `.gz`/`.br` siblings → copy `web/` in →
recreate the container.

## Hosting

`build/` is bind-mounted read-only into an Alpine + `nginx-mod-http-brotli`
container on port 8070 (`Dockerfile`, `docker-compose.yml`, `web.conf`).

The public URL is served by the home reverse proxy at
`~/homie/nginx-proxy/nginx.conf` — an nginx server block behind the shared
Google oauth2-proxy, proxying to `host.docker.internal:8070` with
`proxy_buffering off` so the wasm streams.

```bash
cd ~/homie/nginx-proxy
docker compose exec nginx nginx -t          # validate
docker compose up -d --force-recreate       # apply (bind-mount caching)
```

> The hostname still says `fitrogue` from before the rename. Changing it is one
> server block plus a force-recreate.

## Caching

| What | Header | Why |
|---|---|---|
| `index.html` | `no-cache` | Cached but revalidated every load. 6 KB; a 304 is free. |
| `index.<12hex>.*` | `immutable, max-age=1y` | URL derived from the file's bytes, so a hit is never stale. |
| `sw.js`, `manifest.webmanifest`, `icons/*` | `no-cache` | Fixed names; a pinned service worker cannot be cleared from the server. |

**A rebuild reaches users** because index.html is revalidated on every load,
returns new HTML, and that HTML names new hashed URLs. Only changed bytes
download. Nothing is ever manually cache-cleared.

Two independent hashes: one for the engine set (`index.js`, `index.wasm`, both
audio worklets — the loader resolves worklets as
`${executable}.audio.worklet.js`, so they share a prefix) and one for the pck via
`mainPack`. That is what makes a code-only rebuild cost 226 KB instead of 40 MB.

Measured: cold load **10.7 MB** (was 43.6), warm reload **0 bytes** + one 304,
post-rebuild warm load = pck only.

## PWA

`web/` holds `manifest.webmanifest`, `sw.js`, `pwa.js`, `icons/`, copied into
`build/` unhashed. `npm run icons` regenerates the icons from
`data/themes/firstlight.json`, so the installed icon and the app agree.

The service worker is hand-written rather than Godot-generated, because the
generated one is cache-first on a version string and leaves users a reload
behind. Ours mirrors the server:

- documents → network-first (cached copy is the offline fallback)
- `index.<hash>.*` → cache-first (immutable, so a hit is always right)
- `/oauth2/*` → never intercepted
- `skipWaiting()` + `clients.claim()` — an update applies on the next load
- on activate, drop cached assets the current index.html no longer names
- never cache a redirected response: an expired OAuth session answers with a
  redirect to Google, and caching that as index.html pins the app to a login page

**Service workers need a secure context.** They do not register over plain HTTP
on the LAN address — install from `localhost` or the HTTPS hostname.

## Push notifications

Web Push works on Android and — since iOS 16.4 — on iPhone, but **only for a PWA
added to the home screen**. A Safari tab cannot receive push at all; `PushManager`
is simply absent there, which the settings screen reports honestly.

```
game (Notify.gd)  --JavaScriptBridge-->  web/push.js  --fetch /push/*-->  server/
                                                                            |
        service worker "push" event  <--  push service (FCM / APNs)  <-------+
```

- `server/` is a ~200-line Node service (`express` + `web-push`) holding
  subscriptions and a list of reminders per subscription. It never decides *what*
  to say — the game computes the whole schedule and replaces it wholesale, so
  there is no incremental state to drift.
- VAPID keys are generated on first run into `server/data/vapid.json`
  (gitignored). **Back that file up** — rotating the keys invalidates every
  existing subscription.
- nginx proxies `/push/*` to it over the compose network, so it is same-origin
  (no CORS, no second login) and inherits the OAuth protection in front of the
  site.
- Quiet hours are enforced server-side: a reminder landing inside them is
  deferred to the far end rather than dropped.
- 404/410 from the push service means the browser discarded the subscription;
  the server prunes it.

Defaults are off. Nothing is ever sent until the player turns it on in
**The Hearth**, every kind can be silenced individually, and quiet hours are
respected. A health app that nags is a health app people delete.

Verify the whole chain:

```bash
curl -s http://0.0.0.0:8070/push/health     # {"ok":true,"subscriptions":N}
curl -s http://0.0.0.0:8070/push/key        # VAPID public key
```

then subscribe from a browser, schedule a reminder in the past, and watch the
service worker deliver it.

## Gotchas

- `build/.gdignore` must exist or Godot re-imports its own exported PNGs into
  the pck.
- `docker compose up -d` alone leaves a stale bind-mounted `web.conf`; run.sh
  uses `--force-recreate`.
- nginx has no `.webmanifest` MIME type, and a bare `types {}` block replaces the
  whole map — use `default_type` in a `location =` block.
- `add_header` in a location replaces inherited headers; repeat `Cache-Control`
  and `Vary` in each one.
- `server/` and `tools/` carry a `.gdignore`. Without it Godot scans
  `server/node_modules`, treats its thousands of `.json` files as project
  resources and packs them into the pck.
- `exclude_filter="art/*,server/*,tools/*"` keeps unreferenced files out of the pck (it was worth
  3.5 MB). Include specific files only when something loads them.

## Not done

- **Custom Godot web template** (`disable_3d`, module trimming) could roughly
  halve the 39.5 MB wasm — the biggest cold-load win left. Needs an emscripten
  build of the engine.
- **HTTP/2** on the shared proxy — marginal at five requests, and that block is
  shared with many other apps.
