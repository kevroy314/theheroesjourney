# Testing on a device

The shipped target is Android, and the web preview cannot run the game loop —
it has no step counter behind it. So the emulator is where a build is actually
looked at before it goes to the phone. Getting one is stranger than it should
be, for one reason: **the emulator cannot run inside WSL.** It needs WHPX, which
is a Windows hypervisor feature, so qemu lives on the Windows host.

That would normally mean driving everything through `adb.exe` — `wslpath` on
every argument, CRLF mangling every binary you pipe out, no Linux path that
means anything. None of that is necessary, because adb is a client/server
protocol and **the client is the half that touches local files**. Put a native
Linux adb in WSL, point it at the Windows adb server, and the whole toolkit
works with Linux paths intact.

```
WSL                          Windows
  adb (Linux 37.0.1) ──tcp──► forwarder ──► adb server ──► emulator(s)
  npm run emu:install           :5038         :5037          qemu
```

`adb install dist/android/HeroesJourney-0.2.14-214.apk` works because the client
reads that file and streams it over the wire. `adb exec-out screencap -p > x.png`
gives you a PNG, not a PNG with every `\n` doubled.

The forwarder binds the **WSL gateway address only**, never `0.0.0.0`. An open
adb port is full shell and install rights on every attached device, and there is
no reason to offer that to the LAN.

The mechanics live in the `android-device` skill
(`~/.claude/skills/android-device/`); this document is how they are used against
*this* repo, and what is true here that is not true generally.

## The commands

`package.json` wraps the skill's scripts, so the front door is npm and the
script is the fallback when you need an argument npm does not pass.

| Command | Underneath | What |
|---|---|---|
| `npm run emu:up` | `up.sh` | bring the bridge up. Idempotent; run after any WSL restart |
| `npm run emu:doctor` | `doctor.sh` | check every link in the chain, with a fix per failure |
| `npm run emu:start` | `avd.sh start heroes-1 5554` | boot the device, wait for `boot_completed`, print the serial |
| `npm run emu:stop` | `avd.sh stop heroes-1` | shut it down |
| `npm run emu:fresh` | `avd.sh reset heroes-1` | cold boot with the data partition wiped |
| `npm run emu:install` | `install.sh heroes` | install the newest APK from `dist/android/` or `releases/` |
| `npm run emu:launch` | `ux.sh app …` | **broken — see Troubleshooting.** Use `ux.sh app start <pkg>` |
| `npm run emu:shot` | `ux.sh shot` | PNG to `~/android/out/`, path printed |
| `npm run emu:ui` | `ux.sh ui` | view hierarchy — **thin for this app**, see Visual work |
| `npm run emu:log` | `ux.sh log` | logcat |
| `npm run emu:wipe` | `adb … pm clear` | **broken — see Troubleshooting.** Use the raw `adb` line |

Anything not wrapped goes through the scripts directly. They source `env.sh`
themselves, so they work from a non-interactive shell:

```bash
S=~/.claude/skills/android-device/scripts
$S/ux.sh tap 540 1893          # drive the app
$S/ux.sh rec 10                # 10s mp4
$S/net.sh reverse 8070         # multiplayer wiring
$S/install.sh --all heroes     # both devices
```

Output — screenshots, recordings, UI dumps — lands in `~/android/out/`, or
`$ANDROID_TEST_OUT` if you set it.

## First time

```bash
npm run emu:up          # forwarder + Windows adb server; safe to re-run
npm run emu:doctor      # should be all OK before you go further
npm run emu:start       # boots heroes-1 on console port 5554
npm run android         # build a signed APK  (--apk-only --no-publish is faster)
npm run emu:install
~/.claude/skills/android-device/scripts/ux.sh app start com.kevinhorecka.heroesjourney
npm run emu:shot
```

A healthy `emu:doctor` looks like this:

```
windows host reachable             OK  172.23.112.1
linux adb                          OK  /home/kevin/android-sdk/platform-tools/adb
windows adb                        OK  /mnt/c/…/Sdk/platform-tools/adb.exe
adb versions match                 OK  37.0.1-15733141
forwarder                          OK  172.23.112.1:5038
ADB_SERVER_SOCKET                  OK  tcp:172.23.112.1:5038
hw acceleration                    OK  WHPX(10.0.22631) ok
AVDs defined                       OK  4
devices booted                     OK  1
```

The AVDs already exist on this machine. If you are standing one up somewhere
new, `avd.sh create heroes-1 36` — and it must be **API 36, not 35**. The app
*targets* 35, but the reference device is a Galaxy S26 running Android 16, so 36
is what reproduces what the player sees. The AVDs are shaped to match it:
1080x2340 @ 420dpi, 2GB, 2 cores, frameless.

Use the `google_apis` image, not `google_apis_playstore`. A playstore image
refuses `adb root`, which means no access to app storage, which costs you half
of the Debugging section below. The only reason to want one is Play services.

The first cold boot of a fresh AVD takes minutes. `avd.sh start` waits on
`sys.boot_completed` rather than on the device appearing in `adb devices`, since
adbd comes up long before the framework does.

## The daily loop

```bash
npm run verify                                  # validate data + headless self-test
./build_android.sh --apk-only --no-publish      # APK only, skips the AAB and the publish
npm run emu:install
~/.claude/skills/android-device/scripts/ux.sh app start com.kevinhorecka.heroesjourney
npm run emu:shot
```

`npm run verify` first, always — it plays six full journeys through the real
systems and catches everything that does not need eyes. The emulator is for the
things that do.

`install.sh heroes` picks the newest APK from `dist/android/` or `releases/`,
whichever is more recent, and installs with `-r -d` so it keeps app data and
allows a downgrade. It does not build. If you forget, you will silently
reinstall the build you were already looking at — check the version it prints.

For a UI change with no Android surface to it, the web preview (`npm run build`)
is seconds instead of minutes. Reach for the emulator when the answer depends on
being a real Android app: touch targets, safe areas, the launcher icon, the
updater, notifications, install and upgrade behaviour.

## Wiping: which one

Two different sizes of clean, and reaching for the big one out of habit costs
you five minutes every time.

| | What it clears | Cost |
|---|---|---|
| `npm run emu:wipe` (`pm clear`) | this app's data dir and caches — save, run, history, debug settings | seconds, device stays up |
| `npm run emu:fresh` (`-wipe-data`) | the whole data partition: every app, accounts, system settings | a cold boot, minutes |

**`emu:wipe` is what a first-run test wants.** The game keeps everything under
`user://`, which is inside the app's data dir, so clearing the app is
indistinguishable from a fresh install as far as the game can tell. Wiping the
AVD to test onboarding is slow and buys nothing.

`emu:fresh` is for the state that lives *outside* the app: a corrupt system
image, a permission you can no longer un-grant from Settings, an install that
will not upgrade. Note that `avd.sh reset` relaunches without pinning the
console port, so if anything else is booted the device may come back as
`emulator-5556` rather than `emulator-5554`; check `adb devices`.

## Visual and UX work

`emu:shot` writes a PNG and prints the path. Open it and look at it. The AVDs
are created with `showDeviceFrame=no`, so the screenshot is the screen and
nothing else — no bezel, no chrome, no shadow — which is what makes before/after
comparison mean anything.

**The screenshot is exactly 1080x2340, which is the tap coordinate space.** A
pixel you measure in the PNG is the argument you pass to `ux.sh tap`, one to
one, with no scaling in between. That is the whole input loop for this app:

```bash
npm run emu:shot                       # look at it, read off the coordinates
$S/ux.sh tap 540 1893
$S/ux.sh swipe 540 1800 540 700 300
$S/ux.sh key BACK
```

> **`emu:ui` does not do for this app what it does for MacroPad.** Godot renders
> the entire game into one `SurfaceView`; there is no Android view hierarchy
> behind it. A `uiautomator` dump against a running Heroes build returns three
> rows — the content frame, the Godot fragment container, and a hidden EditText
> for the soft keyboard — and no game control appears at all. The skill's
> "why isn't this tappable" workflow, with per-element ids and tap points, is
> real for Compose apps and empty here. Read coordinates off a screenshot
> instead, or use the in-game debug bubble, which knows what the game thinks the
> layout is. `emu:ui` is still worth running when the question is about a system
> surface — a permission dialog, the installer, the share sheet — because those
> *are* real Android views.

For anything time-dependent — a janky transition, a flash of the wrong colour, a
fade that lands late — record instead of firing screenshots:

```bash
$S/ux.sh rec 10 transition      # mp4 in ~/android/out/, step through it
```

## Debugging

### Logs

Godot's `print()` reaches logcat under the tag `godot`. Two useful filters:

```bash
$S/ux.sh log com.kevinhorecka.heroesjourney     # everything from the app's pid
adb logcat -s godot:V                           # just the game's own output
adb logcat -d -v brief --pid=$(adb shell pidof com.kevinhorecka.heroesjourney)
```

The `avc: denied … /dev/pmsg0` warnings at startup are noise from the emulator
image and do not mean anything. `Failed to load cached shader, recompiling` on
first launch after an install is also expected.

### Reaching app storage

`adb root` is required, and works because the AVDs use `google_apis`:

```bash
adb root        # "restarting adbd as root"
adb shell id    # uid=0(root) — the restart takes a second or two
```

`run-as` is **not** an alternative here. The APK this repo builds is
release-signed and therefore not debuggable, so `run-as` fails with
`package not debuggable: com.kevinhorecka.heroesjourney` no matter what. `adb
root` is the only way in.

### Where the game's state lives

`user://` on Android is the app's internal files directory:

```
/data/data/com.kevinhorecka.heroesjourney/files
```

`/data/user/0/com.kevinhorecka.heroesjourney/files` is the same directory —
`/data/data` is the compatibility symlink, and `readlink -f` resolves to the
`/data/user/0` form. Either path works in every command below. Nothing is on
external storage; the export does not set `use_external_data_dir`.

| File | Written by | What |
|---|---|---|
| `heroes_save.json` | `scripts/autoload/Meta.gd` | the meta save: codex, inventory, levels, streak, notify prefs |
| `heroes_run.json` | `scripts/game/RunStore.gd` | the in-flight run, so it survives being killed while backgrounded |
| `history.ndjson` | `scripts/autoload/History.gd` | every run ever walked, one JSON object per line, append-only |
| `heroes_buffs.json` | `scripts/autoload/Buffs.gd` | active buffs |
| `objectives.json` | `scripts/autoload/Objectives.gd` | objective state |
| `dialogue.json` | `scripts/autoload/Dialogue.gd` | dialogue state |
| `steps.cfg` | `scripts/autoload/Steps.gd` | the step baseline — see Limits; always meaningless on an emulator |
| `debug.json` | `scripts/autoload/Debug.gd` | debug bubble knobs. Deliberately *not* in the save, so wiping a save keeps your brightness |
| `updater.cfg`, `update.apk` | `scripts/autoload/Updater.gd` | updater settings, and a download in flight |
| `reports/` | `scripts/autoload/Debug.gd` | state reports and frame grabs the debug bubble writes |

A file only exists once something has written it — a device that has never
finished a run has no `history.ndjson`.

### Pulling, editing and pushing state back

This is the useful part: you can put the game into any state you like without
playing to it.

```bash
D=/data/data/com.kevinhorecka.heroesjourney/files
adb root
adb pull $D/heroes_save.json ./save.json
# edit save.json
adb push ./save.json $D/heroes_save.json
adb shell chown u0_a216:u0_a216 $D/heroes_save.json      # see below
adb shell am force-stop com.kevinhorecka.heroesjourney   # it saves on exit —
$S/ux.sh app start com.kevinhorecka.heroesjourney        # stop it before pushing
```

Verified end to end: `loops` edited from 0 to 99, pushed, app restarted, and the
game came up with 99 and wrote it back.

Two things that bite:

**Ownership.** Overwriting an existing file keeps that file's owner, so a plain
push over `heroes_save.json` is fine. Pushing a file that does **not** exist yet
creates it owned by `u0_a0` — root's push identity, not the app's — and the app
then cannot write it. `chown` it to the app's uid. Find the uid with
`adb shell stat -c %U $D` or from `ls -l` on a file already there; it is per
install, not fixed, so do not hardcode the `u0_a216` above. The SELinux label is
inherited from the directory and comes out right on its own.

**Force-stop first.** The game writes its save on nearly every meaningful action
and on backgrounding. Push under a running app and the next write throws your
edit away.

To wipe just the game's state and keep the install, `pm clear` is the whole
answer — no need to delete files individually:

```bash
adb -s emulator-5554 shell pm clear com.kevinhorecka.heroesjourney
```

## What the emulator cannot tell you

Stated plainly, because both of these fail quietly rather than loudly.

**There is no step counter.** The emulator exposes twelve Goldfish sensors —
accelerometer, gyroscope, magnetometer, orientation, temperature, proximity,
light, pressure, humidity — and not one of them is
`android.sensor.step_counter`. Anything routed through the `HeroesSteps` plugin
therefore reports zero, forever, and reports it as a successful reading. Nothing
errors, nothing logs, the number is simply always 0. `adb emu sensor set` cannot
help: it can only drive sensors the image has.

So the emulator is honest about screens, layout, navigation, persistence, the
updater, notification scheduling and permission flows, and dishonest about
anything downstream of a step: the walk, ring progress, the honesty gate as the
player experiences it, streaks that depend on real movement. Those go on real
hardware, or behind a test hook that injects step counts.

**Performance means nothing here.** Godot's GL Compatibility renderer on the
emulator runs through the host GPU — this machine reports
`Android Emulator OpenGL ES Translator (NVIDIA GeForce GTX 1080 Ti)` — so you
are measuring a desktop GPU with a translation layer in front of it, on a
machine with far more RAM and thermal headroom than a phone. It is neither an
upper nor a lower bound on the real thing. Frame-rate and battery questions go
to a real device.

The other native plugins, `HeroesNotify` and `HeroesUpdater`, do work on the
emulator; notification scheduling and the download-and-install path are both
honest there.

## Two devices

`heroes-1` and `heroes-2`, on pinned console ports. Pin them: the console port
*is* the adb serial (`emulator-5554`), so pinning makes a two-player run
reproducible and keeps every `-s` flag stable across restarts.

```bash
$S/avd.sh start heroes-1 5554
$S/avd.sh start heroes-2 5556
$S/net.sh reverse 8070          # applies to every booted device
$S/install.sh --all heroes
$S/ux.sh -s emulator-5556 shot
```

Each emulator sits behind its own NAT and **cannot reach its siblings
directly**. They meet at a server. `adb reverse` maps a device port to the adb
server host — which here is Windows — and WSL2's localhost forwarding carries it
the rest of the way:

```
emulator localhost:8070 → Windows localhost:8070 → WSL server:8070
```

**The server must bind `0.0.0.0`, not `127.0.0.1`.** WSL2 only forwards a WSL
listener to Windows localhost when it binds the wildcard address. A server on
`127.0.0.1` works perfectly from inside WSL and times out from the emulator,
which is a maddening way to lose an hour. This is why the docs and scripts here
say `http://0.0.0.0:8070` rather than localhost. `net.sh check 8070` proves the
hop before you start suspecting game code.

`10.0.2.2` inside an emulator is the Windows host loopback, if you would rather
not set up a reverse mapping at all.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `adb devices` empty, emulator window right there | `ADB_SERVER_SOCKET` unset, so adb spawned its own server in WSL, which sees nothing | `env -u ADB_SERVER_SOCKET adb kill-server && source ~/.claude/skills/android-device/scripts/env.sh` |
| Worked yesterday, nothing today | The WSL gateway IP moved on restart; a stale `ADB_SERVER_SOCKET` in an old shell | `npm run emu:up`, then re-source `env.sh`. It is computed, never hardcoded — do not paste an IP anywhere |
| adb fails with no useful message, cannot restart the server | Version drift: the Linux client and Windows server are different adb revisions. Over TCP a mismatched client cannot restart the remote server, and the error never mentions versions | Put the same revision on both sides. Both are pinned at **37.0.1**; `doctor.sh` catches the mismatch. Android Studio updating platform-tools underneath you is how this happens |
| `could not connect to TCP port 5554: Connection refused` from `adb emu …` | Console commands bypass the adb server entirely — the client opens the emulator's console port on Windows loopback and authenticates with a token in the **Windows** home directory. A WSL client can reach neither | Run `emu` subcommands through Windows: `winadb -s emulator-5554 emu kill`, or `avd.sh stop` which does it for you. Everything that is not `emu` stays on the Linux client |
| `adb root` says the device cannot be rooted | It is a `google_apis_playstore` image | Use a `google_apis` AVD (`heroes-1`, `heroes-2`, `macropad`). `macropad-ps35` exists only for Play services |
| `run-as: package not debuggable` | The installed APK is release-signed | `adb root`. There is no debug-signed build in this repo's normal loop |
| `npm run emu:launch` → `line 104: $2: unbound variable` | The script passes no subcommand to `ux.sh app`, which needs `start\|stop\|clear\|info <pkg>` | `$S/ux.sh app start com.kevinhorecka.heroesjourney` |
| `npm run emu:wipe` → `sh: 1: adb: not found` | npm runs scripts in a non-interactive `sh`. Ubuntu's `.bashrc` returns early for those, so the PATH and `ADB_SERVER_SOCKET` it sets never happen. The other `emu:*` scripts are unaffected because each one sources `env.sh` itself | Run it from an interactive shell that has sourced `env.sh`: `adb -s emulator-5554 shell pm clear com.kevinhorecka.heroesjourney`, or `$S/ux.sh app clear com.kevinhorecka.heroesjourney` |
| `INSTALL_FAILED_UPDATE_INCOMPATIBLE` | A build signed with a different key is already installed | `adb uninstall com.kevinhorecka.heroesjourney` first. This erases its data — see the signing notes in [`DEPLOY.md`](DEPLOY.md#signing) |
| `install.sh heroes` installs the wrong build | It picks the newest APK in `dist/android/` or `releases/` and never builds | Build first, and read the version it prints |
| Emulator in `adb devices` but the screen is black / unresponsive | adbd comes up long before the framework does | Wait for `adb shell getprop sys.boot_completed` to return 1. A first cold boot runs to minutes |
| `uiautomator dump failed (is the screen on?)` | Screen off, or nothing focusable | `$S/ux.sh key WAKEUP`. Expect a near-empty dump for this app regardless — see Visual work |
| Emulator cannot reach a server that works from WSL | The server bound `127.0.0.1`; WSL2 only forwards a wildcard listener | Bind `0.0.0.0`. `net.sh check <port>` proves the hop |
| Step count is always 0 | There is no step sensor on the emulator | Not a bug. See What the emulator cannot tell you |
| `android-36 was unexpected at this time` | A package id like `system-images;android-36;google_apis;x86_64` went through `cmd.exe /c "…"`, which treats `;` as an argument separator | Use `sdk_run` from `env.sh`, which writes a one-shot batch file |

`npm run emu:doctor` first, whenever anything is off. It checks every link in
the chain and names the fix for each failure, which is faster than working down
this table.

## See also

- [`DEPLOY.md`](DEPLOY.md) — building the APK, signing, versioning, and the
  over-the-air update path the emulator is a poor test of (the phone downloads
  from a keyed URL on the home proxy)
- `~/.claude/skills/android-device/SKILL.md` — the bridge itself, and the same
  toolkit pointed at MacroPad
