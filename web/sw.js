/* Service worker for The Heroes' Journey.
 *
 * It exists to make the app installable and playable offline, and it is
 * deliberately shaped to match the server's caching model rather than fight it:
 *
 *   index.html            network-first  — the server marks it `no-cache` and it
 *                                          is the thing that points at every
 *                                          other URL, so it must never go stale.
 *                                          The cached copy is a fallback for
 *                                          when you are offline.
 *   index.<hash>.*        cache-first    — the URL is derived from the file's
 *                                          own bytes, so a hit can never be
 *                                          wrong. Different bytes, different URL.
 *   everything else       untouched      — including /oauth2/*, which must never
 *                                          be cached or intercepted.
 *
 * Updates apply on the next load, not the load after: skipWaiting() and
 * clients.claim() mean a new worker takes over immediately instead of sitting
 * in `waiting` until every tab closes. On activate we drop any cached asset the
 * current index.html no longer references, so storage tracks one build.
 */

const HTML_CACHE = "hj-html-v1";
const ASSET_CACHE = "hj-assets-v1";
const KEEP = [HTML_CACHE, ASSET_CACHE];

const HASHED = /\/index\.[0-9a-f]{12}\./;

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    await self.clients.claim();
    for (const key of await caches.keys()) {
      if (!KEEP.includes(key)) await caches.delete(key);
    }
    await pruneAssets();
  })());
});

/* Drop hashed assets from previous builds. If we are offline the fetch fails
 * and we simply keep what we have — a full cache is better than an empty one. */
async function pruneAssets() {
  try {
    const res = await fetch("./", { cache: "no-store" });
    if (!res.ok || res.redirected) return;
    const html = await res.text();
    const wanted = new Set(
      [...html.matchAll(/index\.[0-9a-f]{12}\.[A-Za-z0-9.]+/g)].map((m) => m[0])
    );
    if (wanted.size === 0) return;
    const cache = await caches.open(ASSET_CACHE);
    for (const request of await cache.keys()) {
      const path = new URL(request.url).pathname;
      const name = path.split("/").pop();
      if (HASHED.test(path) && !wanted.has(name)) await cache.delete(request);
    }
  } catch (err) {
    /* offline — keep the cache as-is */
  }
}

/* A response is only safe to store if it really is ours: a 200 from this origin
 * that was not redirected. `redirected` is the important one — when the OAuth
 * session expires the proxy answers with a redirect to the login page, and
 * caching that as index.html would lock the app onto a login screen. */
function cacheable(res) {
  return res && res.ok && res.type === "basic" && !res.redirected;
}

async function networkFirst(request) {
  const cache = await caches.open(HTML_CACHE);
  try {
    const res = await fetch(request);
    if (cacheable(res)) cache.put(request, res.clone());
    return res;
  } catch (err) {
    const hit = await cache.match(request) || await cache.match("./");
    if (hit) return hit;
    throw err;
  }
}

async function cacheFirst(request) {
  const cache = await caches.open(ASSET_CACHE);
  const hit = await cache.match(request);
  if (hit) return hit;
  const res = await fetch(request);
  if (cacheable(res)) cache.put(request, res.clone());
  return res;
}

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/oauth2/")) return;

  const isDocument =
    request.mode === "navigate" ||
    url.pathname === "/" ||
    url.pathname.endsWith("/index.html");

  if (isDocument) {
    event.respondWith(networkFirst(request));
  } else if (HASHED.test(url.pathname)) {
    event.respondWith(cacheFirst(request));
  }
});
