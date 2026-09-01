# HeroesUpdater — native Android APK-install plugin

A Godot 4 Android plugin (v2 architecture) that hands a downloaded APK to the system
package installer, exposed to GDScript as the `HeroesUpdater` singleton. The GDScript
half lives in `scripts/autoload/Updater.gd`, which does the whole download itself and
only crosses into native code for this last step.

## Why native at all

Android will not install from a `file://` URI — `FileUriExposedException`, API 24+ — so
the installer has to be handed a `content://` URI backed by a `FileProvider`, with the
MIME type `application/vnd.android.package-archive` set on the intent. `OS.shell_open()`
can produce neither. Everything before that (release index, download, SHA-256 check) is
ordinary GDScript and stays there.

The flow is a transcription of MacroPad's shipped `AppUpdater.kt`: gate on
`canRequestPackageInstalls()`, `ACTION_VIEW` + APK MIME type +
`FLAG_GRANT_READ_URI_PERMISSION`, and a route to
`Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES` when the gate is shut.

## API

Singleton name: `HeroesUpdater` (`Engine.get_singleton("HeroesUpdater")`).

| Method | Returns | Notes |
| --- | --- | --- |
| `can_install()` | `bool` | `PackageManager.canRequestPackageInstalls()`. Always `true` below API 26, where the grant is a single global setting. |
| `install_apk(path)` | `void` | `path` is an absolute filesystem path — GDScript passes `ProjectSettings.globalize_path("user://update.apk")`. Launches the system installer. |
| `open_install_settings()` | `void` | Deep-links to this app's row on the "Install unknown apps" screen. Falls back to the app details page on ROMs that do not export it. |

### Signals

| Signal | Payload | When |
|---|---|---|
| `install_failed` | `String` | The install did not happen, with a reason fit to show a player. |

**There is deliberately no success signal.** A successful install replaces this process
to do it, so a signal announcing success could never be observed — an API that promises
one would be lying. Failure is the case worth reporting, because it hands the player
back to a game that otherwise still thinks the update is pending.

This is why the plugin uses `PackageInstaller` rather than `ACTION_VIEW`: the latter is
fire-and-forget, so a signature mismatch, a downgrade, a full disk or a Play Protect
block all returned the player to an "Install" button that would fail again identically,
with nothing on screen saying why.

### What it does on the failure paths

`install_apk` never throws — an exception crossing the JNI boundary from a plugin method
takes the whole game down, and a player who cannot install an update should be left
holding a working game. Every refusal is logged under the `HeroesUpdater` tag and the
call returns silently:

- no file at `path`, or a zero-byte one (checked before `FileProvider`, which reports a
  missing file and an out-of-root file with the same useless exception);
- `can_install()` is false — GDScript is expected to have checked, but re-checking is
  cheaper than letting the installer bounce the player with its own dead end;
- `FileProvider` refuses the path (means `res/xml/heroes_updater_paths.xml` is wrong);
- nothing on the device handles the intent.

## The FileProvider

**Authority: `<applicationId>.updater.fileprovider`** — i.e.
`com.kevinhorecka.heroesjourney.updater.fileprovider`.

The obvious `<applicationId>.fileprovider` is **taken**: `godot-lib.aar` already declares
a provider under exactly that authority (it is how `OS.shell_open` shares files). Two
providers claiming one authority is `INSTALL_FAILED_CONFLICTING_PROVIDER` — the app
refuses to install at all, with no hint as to why.

**Root: `<files-path name="godot_user" path="." />`**

Godot's `user://` on Android is `Context.getFilesDir()` and nothing else.
`GodotIO.getDataDir()` is literally `getContext().getFilesDir().getAbsolutePath()`, and
`OS_Android` passes that through as the user data dir (running `realpath` over it, which
collapses the `/data/user/0` → `/data/data` symlink). So `user://update.apk` is
`/data/data/com.kevinhorecka.heroesjourney/files/update.apk`, and `files-path` — not
`cache-path`, not `external-files-path`, not `external-path` — is the root that contains
it. A wrong choice here builds cleanly and fails on the phone the moment the player taps
Install, with `IllegalArgumentException: Failed to find configured root that contains …`.

The symlink form does not matter: `FileProvider` canonicalises both the configured root
and the file passed to `getUriForFile`, so either spelling of the path resolves to the
same string.

## `REQUEST_INSTALL_PACKAGES`

Declared in **this plugin's** `src/main/AndroidManifest.xml`, and merged into the app by
AGP. It belongs here rather than only in `export_presets.cfg` because it is meaningless
without the plugin, and because the preset is hand-edited often enough that a
self-contained AAR is the safer home — same reasoning as `HeroesSteps` and
`ACTIVITY_RECOGNITION`.

It is not a runtime permission: it toggles an AppOp the player flips in Settings, so
there is no dialog to request. If it is missing from the merged manifest,
`canRequestPackageInstalls()` returns `false` forever with no error and no way for the
player to fix it.

Mirroring it in the export preset's `permissions/custom_permissions` is optional and
harmless; the preset must in any case carry `plugins/HeroesUpdater=true`, or the plugin
is found and silently skipped.

## Rebuilding the AAR

```sh
export JAVA_HOME=/home/kevin/.sdkman/candidates/java/current   # JDK 17
export ANDROID_HOME=/home/kevin/android-sdk
cd android/plugins/updater
./gradlew assemble
```

`assemble` is finalized by a `copyPluginBinary` task that drops the release AAR at
`android/plugins/updater/HeroesUpdater.aar` — the exact path `../HeroesUpdater.gdap`
points at. **Commit that AAR**: the Godot export reads the prebuilt binary and will not
run Gradle for you.

No NDK is needed; this is Kotlin only.

## How Godot finds this at export time

1. `android/plugins/HeroesUpdater.gdap` — the Android exporter scans `res://android/plugins`
   (non-recursively, hence the `.gdap` sitting one level above this directory) and passes
   the `binary=` path to the Gradle build as `-Pplugins_local_binaries`.
2. `export_presets.cfg` must enable it: `plugins/HeroesUpdater=true`.
3. At runtime, Godot's `GodotPluginRegistry` scans the merged `AndroidManifest.xml` for
   `org.godotengine.plugin.v2.*` meta-data and instantiates the named class.

## Dependencies

Both `compileOnly`, for different reasons:

- `org.godotengine:godot:4.7.0.stable` — the engine library is already inside the
  exported app (`android/build/libs/`); a second copy collides at dex time.
- `androidx.core:core` — a *local* plugin binary is added to the export as
  `implementation files(...)`, which carries no POM, so an AAR's own dependencies are
  never resolved and shipping it would achieve nothing. It does not need to: the Godot
  app template pulls `androidx.fragment` (→ `androidx.core`), and `godot-lib`'s own
  manifest declares an `androidx.core.content.FileProvider`, so the class is guaranteed
  present.

When `android/.build_version` moves to a new Godot minor version, bump `godotVersion` in
`build.gradle.kts` and rebuild.

`.gdignore` keeps the Godot editor from indexing the Gradle sources and outputs; without
it the AAR could end up inside the exported PCK.
