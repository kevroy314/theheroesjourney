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

## Android (sideloaded, over-the-air)

The native build is not on any store: the phone downloads its own updates from
this machine. That is two static files served by the same container that serves
the game, and one carve-out in the reverse proxy.

### Building a release

```bash
npm run android                                 # APK + AAB, then publish
./build_android.sh --apk-only --no-publish      # quick loop, skips the AAB
RELEASE_NOTES="Overworld walking" ./build_android.sh
```

One command, and the last thing it does is call `tools/publish_release.py` with
the version it just built — so the numbers in the APK and in `releases.json`
come from the same place and cannot disagree. Everything below about *cutting*
a release is what that call does; you only run it by hand to re-publish a build
you already have.

It exports twice, because `gradle_build/export_format` in `[preset.2]` is the
only thing that decides APK vs AAB and there is no CLI override. The script
flips that field, exports, flips it back, and restores it from a trap if it is
interrupted — so an aborted build never leaves the committed preset saying
"AAB". The APK is what the phone sideloads; the AAB is archived beside it and
never served, and exists only so a Play submission later does not need a
different key.

**Nothing is trusted to exit codes.** Godot has historically returned 0 after a
failed Android export and left a zero-byte file behind, so each export is
checked four ways: exit status, the log scanned for `ERROR:` / `FAILURE: Build
failed`, the artefact existing and being over a megabyte, and its first two
bytes being `PK`. The APK is then run through `apksigner verify --print-certs`,
because a signature that verifies against the wrong key is silent right up until
a phone refuses the update.

| Output | Typical size |
|---|---|
| `dist/android/HeroesJourney-<name>-<code>.apk` | 77 MB |
| `dist/android/HeroesJourney-<name>-<code>.aab` | 29 MB |

`dist/`, not `build/`: `build/` is bind-mounted as the nginx html root, so an
APK parked there is served off the LAN address with no login at all — quietly
routing around the keyed `/releases/` path the updater is supposed to use. Same
reasoning that keeps `releases/` out of `build/`, pointed the other way.

The APK is that big because `gradle_build/compress_native_libraries=false`
leaves the 71 MB `lib/arm64-v8a/libgodot_android.so` stored rather than
deflated — which is what lets Android mmap it instead of unpacking a second
copy at install time. The AAB compresses it because Play recompresses per
device anyway. Only `arm64-v8a` is built.

### Versioning

**The single source of truth is `version` in `package.json`.** It already
existed, it is already what the repo calls itself, and package.json is already
documented as the one discoverable entry point for the build commands — so the
version lives next to them instead of in a new file nobody thinks to look at.

```bash
python3 tools/version.py                 # 0.2.0 200
python3 tools/version.py --bump patch    # 0.2.0 -> 0.2.1, and sync
python3 tools/version.py --set 1.0.0
```

The Android **version code is never authored, only derived**:

```
code = major * 10000 + minor * 100 + patch     # 0.2.0 -> 200, 1.4.12 -> 10412
```

There is exactly one number a human edits, which is what makes it impossible for
the name and the code to drift apart — the failure mode the literals in
`export_presets.cfg` already had, where the preset said `0.1.0`/`1` while
package.json said `0.2.0`. `tools/version.py` refuses a minor or patch over 99,
because the packing only stays monotonic while the lower two fields fit their
digit budget and a non-monotonic code is an update a phone silently will not
take.

`--sync` (which `build_android.sh` runs on every build, before anything is
compiled) writes the version into two **generated** files:

| File | Field | Read by |
|---|---|---|
| `export_presets.cfg` `[preset.2]` | `version/code`, `version/name` | the APK manifest |
| `project.godot` | `application/config/version_code` | `scripts/autoload/Updater.gd` |
| `project.godot` | `application/config/version` | anything that displays it |

All three are outputs. Editing them by hand is pointless rather than dangerous —
the next build overwrites them. `version_code` in `project.godot` is the one
that actually bites: the in-app updater compares it against `releases.json` to
decide whether there is something newer, so if it lags the number baked into the
APK the phone downloads an update, installs it, still reads the old code, and
offers the same update again forever.

`--set` refuses to move the version backwards unless you add `--force`, because
a phone will not install a code lower than the one it already has — the only
time that is safe is correcting a version that was never published.

### Signing

> **Losing the release key means never being able to update an installed app
> again.** Not "it is inconvenient" — Android refuses any update whose signature
> differs from the installed one, so the only recovery is telling every user to
> uninstall and lose their save. Back both files up, somewhere that is not this
> machine.

Two files, both **outside the repo**, both `0600`, in `~/.config/heroesjourney/`:

| File | What |
|---|---|
| `heroesjourney-release.jks` | PKCS#12, RSA 4096, alias `heroesjourney`, valid to **2066** |
| `android-keystore.env` | the path, the alias and the password, nothing else |

They are outside the tree on purpose. `releases/` shows why gitignoring a thing
is not the same as protecting it: `git clean -xfd` deletes ignored files, and
unlike a published APK a signing key cannot be rebuilt. `.gitignore` still
carries `*.jks`, `*.keystore` and `android-keystore.env` as belt-and-braces for
a copy that lands in the repo by accident.

The env file defines exactly the three names Godot looks for:

```
GODOT_ANDROID_KEYSTORE_RELEASE_PATH=/home/kevin/.config/heroesjourney/heroesjourney-release.jks
GODOT_ANDROID_KEYSTORE_RELEASE_USER=heroesjourney
GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD=...
```

Godot falls back to those env vars whenever the preset's `keystore/release`
fields are blank, which is why they must **stay** blank — MacroPad's approach of
putting the password in `build.gradle.kts` works only because that repo is
private, and this one is not. `build_android.sh` refuses to run if a
`keystore/release` path ever appears in `export_presets.cfg`. Override the
location for a different machine with `HEROES_KEYSTORE_ENV=/path/to/env`.

The certificate is 25+ years and RSA 4096 so the same key can be handed to Play
later; Play rejects anything expiring before 2033. Verify a build's identity at
any time with:

```bash
# ls | tail, not a bare glob — more than one build-tools version is installed
# and the extra path lands in argv as a bogus subcommand.
"$(ls -1 "$ANDROID_HOME"/build-tools/*/apksigner | sort -V | tail -1)" \
    verify --print-certs releases/HeroesJourney-0.2.0-200.apk
# Signer #1 certificate SHA-256 digest: 91000c20789d2b08a8b605f052d8f3053d1e86efcb9c4c8aeb61185e212aa582
```

That digest is the app's identity forever. If a future build prints a different
one, **do not publish it** — it will not install over anything already out
there.

Two things that follow from this:

- **The debug-signed APK already sideloaded on the phone cannot be upgraded to a
  release build.** Different key, so Android rejects it with
  `INSTALL_FAILED_UPDATE_INCOMPATIBLE`. It has to be uninstalled first, which
  erases its save data. Do this once, now, before there is anything worth
  keeping — a release-signed build installed today upgrades cleanly forever
  after.
- Godot's template signs **v2 only** (no v1, which is fine at minSdk 26; no v3,
  which is what would have allowed rotating the key later). Treat the key as
  permanent rather than rotatable.

### Launcher icons

`npm run icons` (`tools/make_icons.py`) emits both the PWA set into `web/icons/`
and the four Android cuts into `assets/icons/android/`, all from
`data/themes/firstlight.json`. `build_android.sh` regenerates them every build,
so the launcher icon can never fall behind the theme.

| Preset field | File | Notes |
|---|---|---|
| `launcher_icons/main_192x192` | `icon-192.png` | the legacy square icon; byte-identical to the PWA's `icon-192.png` |
| `launcher_icons/adaptive_background_432x432` | `adaptive-background.png` | flat sky-and-floor bands, full bleed |
| `launcher_icons/adaptive_foreground_432x432` | `adaptive-foreground.png` | mountains and the light, transparent |
| `launcher_icons/adaptive_monochrome_432x432` | `adaptive-monochrome.png` | alpha-only silhouette for Android 13 themed icons |

The adaptive pair is the PWA icon cut in half along the parallax seam: composite
them and you get exactly `web/icons/icon-192.png` scaled up. The foreground is
drawn full-bleed rather than shrunk into the 66% safe zone — the ridges are
*supposed* to run off the sides, and letting the mask trim their skirts is what
makes the layers recompose. `make_icons.py` asserts that the one thing that must
survive every mask shape, the light at (0.72, 0.445), is inside the safe zone.

The monochrome cut cannot use the bloom (Android throws the colours away and
tints the alpha, so a glow becomes a blob), so the light is punched *through*
the mountain as a ring of empty alpha instead.

These four PNGs are read off disk at export time, not out of the pck, so
`[preset.2]`'s `exclude_filter` keeps `assets/icons/android/*` out of the APK's
data.

### Cutting a release

```bash
python3 tools/publish_release.py \
    --apk path/to/app-release.apk \
    --version-name 0.3.0 --version-code 7 \
    --notes "Overworld walking"
```

`--notes` falls back to `$RELEASE_NOTES`. `--aab path/to/app-release.aab`
archives the bundle beside the APK; it is never served.

The script is the only writer of `releases/`. It streams the sha256 (the APK is
tens of MB), copies the file into place under a temporary name and renames — so
a phone mid-download never sees a truncated APK — then merges the index.
Running it twice is a no-op; re-running it for a version code that already
exists **replaces** that entry instead of adding a second one, and keeps the
old notes if `--notes` is omitted. Only the last five builds stay on disk.

### Where things land

| Path | What |
|---|---|
| `releases/releases.json` | index the updater polls: `version_name`, `version_code`, `file`, `sha256`, `size_bytes`, `notes`, `published_at` (ms), newest first |
| `releases/HeroesJourney-<name>-<code>.apk` | the build itself |
| `releases/.gdignore` | without it Godot imports `releases.json` as a resource and packs a 60 MB APK into the pck |

`releases/` is gitignored and bind-mounted read-only into the container at
`/usr/share/nginx/html/releases`. It is deliberately **not** inside `build/`:
`build/` is disposable output that gets deleted whenever an export goes wrong,
and a signed APK cannot be rebuilt byte-for-byte.

### The URL the phone hits

```
https://fitrogue.home.kevinhorecka.com:1403/releases/releases.json
https://fitrogue.home.kevinhorecka.com:1403/releases/HeroesJourney-0.3.0-7.apk
```

with the shared secret in an `X-Release-Key` header, or `?key=<secret>` when the
URL has to be typed into the phone's browser — which is how the *first* install
happens, before there is an app to send headers.

Everything else on the host keeps Google OAuth. These two paths cannot, because
a phone cannot complete a Google redirect from a background download; the
macropad app has exactly this problem and solves it the same way.

### The secret

It lives in **one** place: the `location ~ "^/releases/..."` block in
`~/homie/nginx-proxy/nginx.conf`. The block to paste, and why it belongs there
rather than in this repo's `web.conf`, is in
[`docs/android-release-nginx.conf`](android-release-nginx.conf) — the short
version is that `web.conf` runs inside the container, which never sees
oauth2-proxy, so only the proxy can decline to apply it.

**This is already applied.** The live secret is at
`~/homie/credentials/heroes-release-key.txt` (mode 0600, outside the repo,
alongside the other credentials the home proxy uses). The copy of the block in
`docs/android-release-nginx.conf` keeps a placeholder, because that file is in
git.

To regenerate from scratch:

```bash
openssl rand -hex 32          # generate; never commit the real value
cd ~/homie/nginx-proxy
docker compose exec nginx nginx -t
docker compose up -d --force-recreate
```

Verified working through the public host — no key and a wrong key both 403, the
header and query forms both 200, the APK arrives as
`application/vnd.android.package-archive`, and everything outside the two
allow-listed filenames still falls through to Google OAuth.

**Rotating** means changing a string the installed APK also knows, so do it in
this order or you lock the phone out of its own updates: add the new key as a
second `if` in the block → publish a build that uses it → install that build →
delete the old `if`. The key appears in the proxy's access log whenever `?key=`
is used rather than the header.

### Published, but the phone does not see it

Work down the chain; each step tells you which half of it is broken.

```bash
# 1. Did it publish?  The index and the file must agree.
cat releases/releases.json && ls -la releases/

# 2. Does the container serve it?  (bypasses the proxy entirely)
curl -sI http://0.0.0.0:8070/releases/releases.json
curl -sI http://0.0.0.0:8070/releases/HeroesJourney-0.3.0-7.apk   # expect
                       # Content-Type: application/vnd.android.package-archive

# 3. Does the proxy?  403 = wrong/missing key.  302 = the location block is
#    not matching, so the request fell through to the OAuth-guarded `location /`.
curl -sI 'https://fitrogue.home.kevinhorecka.com:1403/releases/releases.json?key=SECRET'
```

Common causes, in the order they actually happen:

- **404 at step 2, file present on disk.** The `releases/` bind-mount was added
  after the container last started. `npm run serve` (`--force-recreate`).
- **302 at step 3.** The location block is missing, or the filename does not
  match its allowlist regex — a version name with a space or a `+` in it
  publishes fine and is unreachable. `publish_release.py` rejects those, so this
  means the block was edited.
- **403 at step 3.** Key mismatch, or the app is sending the header to a proxy
  that has been reloaded with a new one.
- **Phone times out, laptop works.** DNS for `*.home.kevinhorecka.com` points at
  the public IP, so the phone leaves and re-enters the network; if the router
  does not hairpin, the phone must be on mobile data or use the LAN address.
- **Certificate error on the phone.** The wildcard cert in
  `~/homie/nginx-proxy/certs` is Let's Encrypt and Android trusts it — but an
  expired one fails hard for a background downloader with no way to click
  through.
- **`git clean -xfd`.** `releases/` is gitignored, so this deletes every hosted
  build. The index heals itself (entries whose APK is gone are dropped on the
  next publish); the APKs do not.

## Gotchas

- `build/.gdignore` must exist or Godot re-imports its own exported PNGs into
  the pck.
- `android/build/.gdignore` must exist for the same reason, and it is the worse
  of the two: Godot stages the whole exported pck at
  `android/build/src/main/assets/` and the launcher icons at
  `android/build/res/mipmap*/`, then re-imports all of it as `res://` resources
  on the next pass. That packs the previous build inside the next one, collides
  UIDs with `res://icon.png`, and hard-fails the export the moment gradle cleans
  the staging directory. `build_android.sh` creates it; `[preset.2]` also
  excludes `android/*` from the pck as a second line of defence, because plugin
  gradle output under `android/plugins/*/build/` gets swept in the same way.
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
