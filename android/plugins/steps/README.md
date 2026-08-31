# HeroesSteps — native Android step counter plugin

A Godot 4 Android plugin (v2 architecture) that exposes the device's **hardware
pedometer** to GDScript as the `HeroesSteps` singleton.

## Why native, and why this sensor

`Sensor.TYPE_STEP_COUNTER` is maintained by a low-power sensor hub, not by the app. It
keeps counting while the game is backgrounded, force-stopped, or the screen is off, which
is the entire reason for going native — steps accrue all day and the game reads the total
whenever it next runs. Health Connect would require a separate app and a data-sharing
grant; the accelerometer would require us to stay resident and burn battery.

The counter is **cumulative since the last device boot** and **resets to zero on reboot**.
The plugin deliberately does not try to hide that: GDScript stores a baseline and diffs
against it, and uses `elapsed_realtime_ms()` to notice a reboot.

## API

Singleton name: `HeroesSteps` (`Engine.get_singleton("HeroesSteps")`).

| Method | Returns | Notes |
| --- | --- | --- |
| `has_sensor()` | `bool` | Whether this device has a `TYPE_STEP_COUNTER` sensor at all. Many budget phones and most emulators do not. |
| `has_permission()` | `bool` | Whether `ACTIVITY_RECOGNITION` is granted. Always `true` below API 29, where it is not a runtime permission. |
| `request_permission()` | `void` | Asynchronous. Shows the system dialog; the answer arrives on `permission_result`. |
| `steps_since_boot()` | `int` | Last cumulative reading, or `-1` if the sensor is missing, `start()` has not been called, or no event has arrived yet. |
| `elapsed_realtime_ms()` | `int` | `SystemClock.elapsedRealtime()` — milliseconds since boot, including deep sleep. |
| `start()` | `void` | Registers the sensor listener. Idempotent; a no-op without the sensor or the permission. |
| `stop()` | `void` | Unregisters. Idempotent. The hardware keeps counting either way. |

Signals:

| Signal | Payload |
| --- | --- |
| `permission_result` | `granted: bool` |
| `steps_changed` | `since_boot: int` |

### Guarantees worth relying on

- `request_permission()` emits `permission_result` **exactly once** per call, on every
  path: already granted, pre-API-29, no activity attached, granted, denied, and dialog
  dismissed without an answer (Android reports that as empty result arrays; we report it
  as `false`).
- `steps_changed` only fires when the value actually changes, so it is safe to connect
  something expensive to it.
- On a device with no step counter: `has_sensor()` returns `false`, `start()`/`stop()` do
  nothing and log at info level, and `steps_since_boot()` stays `-1` forever. Nothing
  throws and nothing crashes.

### Reboot handling

`elapsed_realtime_ms()` shares its epoch with the step counter. If it is **lower** than the
value sampled last time, the device rebooted and the step total restarted from zero —
re-baseline instead of computing a negative delta.

## Rebuilding the AAR

```sh
export JAVA_HOME=/home/kevin/.sdkman/candidates/java/current   # JDK 17
export ANDROID_HOME=/home/kevin/android-sdk
cd android/plugins/steps
./gradlew assemble
```

`assemble` is finalized by a `copyPluginBinary` task that drops the release AAR at
`android/plugins/steps/HeroesSteps.aar` — the exact path `../HeroesSteps.gdap` points at.
**Commit that AAR**: the Godot export reads the prebuilt binary and will not run Gradle
for you, so a checkout without it cannot produce a working APK.

No NDK is needed; this is Kotlin only.

## How Godot finds this at export time

1. `android/plugins/HeroesSteps.gdap` — the Android exporter scans `res://android/plugins`
   (non-recursively, hence the `.gdap` sitting one level above this directory) and passes
   the `binary=` path to the Gradle build as `-Pplugins_local_binaries`.
2. `export_presets.cfg` must enable it under the Android preset's options:
   `plugins/HeroesSteps=true`. A plugin that is found but not enabled is silently skipped.
3. At runtime, Godot's `GodotPluginRegistry` scans the merged `AndroidManifest.xml` for
   `org.godotengine.plugin.v2.*` meta-data. Ours is declared in
   `src/main/AndroidManifest.xml` and is merged into the app by AGP, so there is nothing
   to add to the app manifest by hand.

The AAR manifest also declares `ACTIVITY_RECOGNITION` and an optional
`android.hardware.sensor.stepcounter` feature, so the plugin is self-contained even if the
export preset's permission list is ever regenerated.

## Version coupling

`build.gradle.kts` compiles against `org.godotengine:godot:4.7.0.stable` as a
`compileOnly` dependency — the engine library is already inside the exported app
(`android/build/libs/`), and bundling a second copy would collide at dex time. When
`android/.build_version` moves to a new Godot minor version, bump `godotVersion` to match
and rebuild.

`.gdignore` keeps the Godot editor from indexing the Gradle sources and outputs; without
it every `./gradlew` run would churn the editor's filesystem cache and the AAR could end
up inside the exported PCK.
