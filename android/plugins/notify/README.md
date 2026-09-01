# HeroesNotify — native Android local-notification plugin

A Godot 4 Android plugin (v2 architecture) that schedules **on-device** deadline and
streak reminders, exposed to GDScript as the `HeroesNotify` singleton.

## Why this exists

Reminders are the pressure that makes the game work. On the web they are Web Push: a
service worker, a VAPID subscription, and a small express server that fires the queue
(`scripts/autoload/Notify.gd`, `web/push.js`). The sideloaded Android build has none of
that infrastructure and shipped with no reminders at all — a regression on the platform
that matters most.

This plugin is a **second backend behind the same GDScript**. `Notify.gd` already
computes the entire "say this at that time" list as absolute times and replaces it
wholesale whenever anything changes; that logic is untouched. All that changes is where
the list is handed to: the push server on web, `AlarmManager` here.

Nothing native decides what to say or when. Keeping the interesting logic in GDScript
keeps it testable without a phone.

## API

Singleton name: `HeroesNotify` (`Engine.get_singleton("HeroesNotify")`).

| Method | Returns | Notes |
| --- | --- | --- |
| `has_permission()` | `bool` | Whether a notification posted right now would actually appear. |
| `request_permission()` | `void` | Asynchronous. Shows the system dialog on API 33+; the answer arrives on `permission_result`. |
| `schedule(id, unix_seconds, title, body)` | `void` | Arms one reminder at an absolute wall-clock time. Replaces any reminder with the same id. |
| `cancel(id)` | `void` | Disarms a pending reminder. No-op for an unknown or already-fired id. |
| `cancel_all()` | `void` | Disarms everything pending. |

Signals:

| Signal | Payload |
| --- | --- |
| `permission_result` | `granted: bool` |

`id` is an `int`, `unix_seconds` an `int` (seconds since the epoch — `Notify.gd` works in
milliseconds for the web bridge, so divide), `title` and `body` are `String`.

### Guarantees worth relying on

- `request_permission()` emits `permission_result` **exactly once per call**, on every
  path: already granted, below API 33 (where the permission does not exist and there is
  no dialog), no activity attached, granted, denied, permanently denied, and dialog
  dismissed without an answer — Android reports that last one as *empty* `permissions`
  and `grantResults` arrays, and we report it as `false`. Calls that arrive while a
  dialog is already up share that dialog's single answer, one emission each.
- No plugin method throws. An exception crossing the JNI boundary out of a Godot plugin
  method takes the whole game down, and a missing reminder must never do that. Every
  refusal is logged under the `HeroesNotify` tag and returns silently.
- `schedule()` with a time in the past is **dropped**, not fired immediately.
- Scheduling the same `id` twice replaces the alarm rather than adding a second one, so
  `Notify.gd` can re-sync as often as it likes. Ids must therefore be derived
  deterministically from the reminder (kind + slot), never from a counter.
- `cancel` / `cancel_all` are about the future. A notification that has already been
  **delivered** is deliberately left in the shade: the player may not have read it, and
  re-syncing the schedule is not a reason to take information away from them.

### `has_permission()` is broader than the permission

It returns `NotificationManager.areNotificationsEnabled()`, and on API 33+ additionally
requires `POST_NOTIFICATIONS` to be granted.

Checking only the permission would be wrong below 33, where it does not exist but the
player can still have switched the app's notifications off in Settings — the Hearth
would claim reminders were on while the phone silently dropped every one.

## Which `AlarmManager` call, and why

`setAndAllowWhileIdle(RTC_WAKEUP, …)`.

- **Not `setExact*`.** Those require `SCHEDULE_EXACT_ALARM`, which since API 31 is a
  special app access the user grants on a Settings screen, and whose pre-granted twin
  `USE_EXACT_ALARM` Google restricts to alarm-clock and calendar apps. A game is not one.
  It would cost a permission screen, a policy argument, and on API 34+ a
  `SecurityException` the moment the user revokes it.
- **We do not need exactness.** The reminders are one, six and twenty-four hours out.
  Being a few minutes late is invisible.
- **But `set()` is not enough either.** In Doze — which is exactly where a phone sits at
  3am — a plain `set()` is deferred to the next maintenance window, and those get rarer
  the longer the device stays still. The reminder could arrive hours late or not until
  the player picks the phone up, which defeats the point.
- `setAndAllowWhileIdle` is the middle: inexact and free of any permission, but
  explicitly exempt from Doze deferral. The platform rate-limits it to roughly one firing
  per app per 9–10 minutes while idle, which cannot matter for reminders spaced hours
  apart.

`RTC_WAKEUP` rather than `ELAPSED_REALTIME_WAKEUP` because the trigger is a wall-clock
instant the player reads off the game's own countdown; `_WAKEUP` because a reminder that
waits for the next screen-on is not a reminder.

## Reboot

Alarms live in a table the system rebuilds from nothing at boot: after a restart every
alarm this app owned is gone, and nothing tells you the queue used to have anything in
it. The same is true after an in-place app update.

**`HeroesNotifyBootReceiver` re-arms them**, from a durable copy of the reminder list in
`SharedPreferences`.

The cheaper alternative — let the game re-`schedule()` everything on next launch — was
rejected on *when* it runs. The entire point of these notifications is to reach a player
who is **not** in the game. A phone that reboots at 2am for an OS update would silently
drop the 7am deadline warning, and the game would only notice when the player next opened
it, which is the one moment they no longer need reminding. A reminder system whose failure
mode is "stops reminding you, quietly, on exactly the nights you were not going to open
the app" is not worth shipping. The persisted list is needed for `cancel_all()` anyway
(see below), so the receiver costs a loop.

Launch-time rescheduling from GDScript still happens on top of this and is harmless:
`schedule()` on an existing id replaces rather than duplicates.

**What the player experiences if the phone reboots overnight:** reminders that were still
in the future are re-armed within seconds of the unlock after boot and fire on time.
Reminders whose moment passed *while the phone was off* are discarded, not replayed — a
stale "6 hours before the loop resets" landing at breakfast is worse than silence.

The receiver listens for `ACTION_BOOT_COMPLETED`, not `LOCKED_BOOT_COMPLETED`: the store
is credential-encrypted and unreadable before first unlock. Moving it to device-protected
storage would put reminder text that names the player's goals outside the lockscreen's
encryption to gain a few minutes.

## Why there is a `SharedPreferences` store at all

Two things `AlarmManager` refuses to do:

1. **There is no "cancel every alarm I own".** `cancel()` takes a `PendingIntent`, and
   rebuilding an equal one requires already knowing its request code. `cancel_all()` is
   only implementable if we remember the ids.
2. **Nothing survives a reboot**, as above, and re-arming needs the payload, not just the
   ids.

It is one JSON blob, written with `commit()` rather than `apply()` because the interesting
cases are exactly the ones where the process may not be alive a second later.

## The notification channel

Required from API 26 up; the game's `min_sdk` is 26, so always. Posting to a channel that
does not exist is silently dropped with only a logcat line.

Channel id `heroes_reminders`, importance `IMPORTANCE_HIGH` so a deadline reminder
heads-up the way the PWA's Web Push notification does. It is created from three places
(plugin setup, alarm receiver, boot receiver) because the receivers may be the first thing
to run in a freshly cold-started process; `createNotificationChannel` is idempotent.

**Importance is only honoured the first time.** Once the channel exists the user owns it;
changing the constant later does nothing on a phone that already installed the app. The
only way to move it is a new channel id, which resets the user's own customisation — so
don't, without a reason.

## Tapping the notification

`packageManager.getLaunchIntentForPackage(packageName)` plus `FLAG_ACTIVITY_NEW_TASK`.
That resolves to `com.godot.game.GodotAppLauncher`, the exported activity-alias in the
merged manifest, and since `GodotApp` is `launchMode="singleInstancePerTask"` it resumes
the running game rather than stacking a second copy — the same thing tapping the launcher
icon does. Hard-coding the class name would be one engine rename away from a notification
that opens nothing.

Each reminder gets its own `PendingIntent` request code. Sharing one would have
`FLAG_UPDATE_CURRENT` quietly rewrite the others.

## The small icon

`Notification.Builder.build()` throws `IllegalArgumentException` without a small icon, so
the AAR ships `res/drawable/heroes_notify_icon.xml` — a flat white vector glyph, because
Android draws the small icon as a silhouette (alpha kept, colour discarded and re-tinted).

It is resolved at runtime with `Resources.getIdentifier` rather than through `R`. The
Godot export adds a local plugin binary as a bare `implementation files(…)` dependency,
and this keeps the code free of any assumption about an `R` class being generated for
that AAR's package. The Godot app template enables neither code nor resource shrinking, so
an apparently-unreferenced drawable is not at risk of being stripped. There is a platform
drawable as a fallback, so "no icon, no notification" cannot happen.

## Manifest, and the collision lesson

Both receivers are declared with **names of their own** —
`HeroesNotifyReceiver` and `HeroesNotifyBootReceiver`, not `AlarmReceiver` or
`BootReceiver`. AGP's manifest merger matches components **by class name, not by
attribute**, and this app already merges components contributed by `godot-lib.aar` and
`androidx.profileinstaller`. That is the same trap the updater plugin hit with
`androidx.core.content.FileProvider`; see `android/plugins/updater/README.md`.

- `HeroesNotifyReceiver` is `exported="false"`: the only sender is our own
  `PendingIntent`, and an exported reminder receiver would let any app on the phone post
  a fake deadline.
- `HeroesNotifyBootReceiver` **must** be `exported="true"` — `BOOT_COMPLETED` comes from
  the system, i.e. from outside the app, and a non-exported receiver would never run. The
  action is platform-protected, so nothing else can forge it.

The AAR declares `POST_NOTIFICATIONS` and `RECEIVE_BOOT_COMPLETED` itself, so the plugin
stays self-contained if `export_presets.cfg` is ever regenerated — same reasoning as
`ACTIVITY_RECOGNITION` in HeroesSteps.

`SCHEDULE_EXACT_ALARM` / `USE_EXACT_ALARM` are deliberately **absent**.

## Rebuilding the AAR

```sh
export JAVA_HOME=/home/kevin/.sdkman/candidates/java/current   # JDK 17
export ANDROID_HOME=/home/kevin/android-sdk
cd android/plugins/notify
./gradlew assemble
```

`assemble` is finalized by a `copyPluginBinary` task that drops the release AAR at
`android/plugins/notify/HeroesNotify.aar` — the exact path `../HeroesNotify.gdap` points
at. **Commit that AAR**: the Godot export reads the prebuilt binary and will not run
Gradle for you, so a checkout without it cannot produce a working APK.

No NDK is needed; this is Kotlin only.

## How Godot finds this at export time

1. `android/plugins/HeroesNotify.gdap` — the Android exporter scans `res://android/plugins`
   **non-recursively and skips directories**, which is why the `.gdap` sits one level
   above this directory with a `binary=` path relative to itself.
2. `export_presets.cfg` must enable it under the Android preset's options:
   `plugins/HeroesNotify=true`. A plugin that is found but not enabled is silently
   skipped.
3. At runtime, Godot's `GodotPluginRegistry` scans the merged `AndroidManifest.xml` for
   `org.godotengine.plugin.v2.*` meta-data and instantiates the named class. Ours is in
   `src/main/AndroidManifest.xml` and is merged into the app by AGP, so there is nothing
   to add to the app manifest by hand.

## What runs where

The alarm receiver runs with **no Godot engine in the process**. When a reminder comes due
six hours after the player closed the game, Android cold-starts the app process purely to
deliver that broadcast: no plugin instance, no GDScript, no `Engine.get_singleton`. That
is why the notification-building code lives in `HeroesNotifyAlarms` / `HeroesNotifyStore`,
reachable from a bare `Context`, and not in the plugin class.

| File | Runs with Godot | Runs without |
| --- | --- | --- |
| `HeroesNotifyPlugin.kt` | yes | — |
| `HeroesNotifyAlarms.kt` | yes | yes |
| `HeroesNotifyStore.kt` | yes | yes |
| `HeroesNotifyReceiver.kt` | — | yes |
| `HeroesNotifyBootReceiver.kt` | — | yes |

## Version coupling

`build.gradle.kts` compiles against `org.godotengine:godot:4.7.0.stable` as a
`compileOnly` dependency — the engine library is already inside the exported app
(`android/build/libs/`), and bundling a second copy would collide at dex time. When
`android/.build_version` moves to a new Godot minor version, bump `godotVersion` and
rebuild.

There is deliberately **no androidx dependency**. A local plugin binary is added to the
export as `implementation files(…)`, which carries no POM, so an AAR's own dependencies
are never resolved (see the updater README). Everything used here — `AlarmManager`,
`NotificationChannel`, `Notification.Builder` — is framework API available at API 26, so
`NotificationCompat` would buy nothing.

`.gdignore` keeps the Godot editor from indexing the Gradle sources and outputs; without
it every `./gradlew` run would churn the editor's filesystem cache and the AAR could end
up inside the exported PCK.

## Known limits the contract does not cover

- **Per-channel blocking.** `has_permission()` reports app-level state. A player who
  long-presses a reminder and turns off the *Reminders* channel specifically still gets
  `true`, and every notification is dropped. Detecting it needs
  `getNotificationChannel(CHANNEL_ID).importance != IMPORTANCE_NONE`; not exposed because
  the contract has nowhere to put a third state.
- **Aggressive OEM battery managers** (Xiaomi, Huawei, Samsung's "deep sleep" app list)
  can drop `setAndAllowWhileIdle` alarms and suppress `BOOT_COMPLETED` for apps the user
  has not exempted. No API detects it; the only fix is the player allowlisting the game.
- **Force-stop.** If the player force-stops the game from Settings, Android puts the
  package in the stopped state: alarms are cancelled and `BOOT_COMPLETED` is not delivered
  until the app is launched again by hand.
- **Timezone and clock changes.** Times are absolute UTC instants. Fly across three
  timezones and a reminder built for "19:00 local" fires at the old local time until
  `Notify.gd` next re-syncs.
