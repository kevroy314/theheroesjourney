#!/usr/bin/env bash
# Build a signed release APK + AAB of The Heroes' Journey and publish the APK.
#
#   ./build_android.sh                     build, then publish to releases/
#   ./build_android.sh --no-publish        build only
#   ./build_android.sh --apk-only          skip the (slow) second AAB export
#   RELEASE_NOTES="Overworld walking" ./build_android.sh
#
# The APK is what the phone sideloads and what tools/publish_release.py serves
# over the air. The AAB is built at the same time and archived beside it purely
# so the Play door stays open: a bundle has to be signed by the *same* key as
# the sideloaded builds or the two can never converge on one installed app, and
# the cheapest way to guarantee that is to produce both from one run.
#
# Nothing about the version is authored here. tools/version.py derives it from
# package.json and writes it into export_presets.cfg and project.godot, so the
# number in the APK, the number in releases.json and the number the running game
# reports cannot disagree — see that file for why the code is derived, not typed.
#
# Signing credentials never appear in this repo. Godot reads
# GODOT_ANDROID_KEYSTORE_RELEASE_{PATH,USER,PASSWORD} directly when the preset's
# keystore fields are blank (which they are, and must stay), so the secrets live
# in one 0600 file outside the tree. See docs/DEPLOY.md.
set -euo pipefail
cd "$(dirname "$0")"

GODOT="${GODOT:-/home/kevin/godot-tools/Godot_v4.7-stable_linux.x86_64}"
export JAVA_HOME="${JAVA_HOME:-/home/kevin/.sdkman/candidates/java/current}"
export ANDROID_HOME="${ANDROID_HOME:-/home/kevin/android-sdk}"
export PATH="$JAVA_HOME/bin:$PATH"

# Outside the repo on purpose. `git clean -xfd` deletes gitignored files, and a
# release key that gets deleted cannot be regenerated — every phone with the app
# installed would be stranded on its last build forever.
KEYSTORE_ENV="${HEROES_KEYSTORE_ENV:-$HOME/.config/heroesjourney/android-keystore.env}"

# Deliberately NOT under build/. build/ is bind-mounted as the nginx html root
# (docker-compose.yml), so a 77 MB signed APK parked there is served straight
# off the LAN address with no login — quietly routing around the keyed
# /releases/ path that the OTA updater is supposed to use. Same reasoning that
# keeps releases/ out of build/, for the opposite direction.
OUT_DIR="dist/android"
PUBLISH=1
APK_ONLY=0
for arg in "$@"; do
  case "$arg" in
    --no-publish) PUBLISH=0 ;;
    --apk-only)   APK_ONLY=1 ;;
    -h|--help)    sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

die() { echo; echo "[android] ERROR: $*" >&2; exit 1; }

# ------------------------------------------------------------------ preflight
[[ -x "$GODOT" ]] || die "no Godot at $GODOT (override with \$GODOT)"
[[ -d "$JAVA_HOME" ]] || die "JAVA_HOME=$JAVA_HOME does not exist"
[[ -d "$ANDROID_HOME" ]] || die "ANDROID_HOME=$ANDROID_HOME does not exist"
[[ -d android/build ]] || die "android/build is missing — install the Android build
  template from the Godot editor (Project > Install Android Build Template)"

if [[ -f "$KEYSTORE_ENV" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$KEYSTORE_ENV"; set +a
fi
: "${GODOT_ANDROID_KEYSTORE_RELEASE_PATH:?no release keystore.
  Expected $KEYSTORE_ENV to define GODOT_ANDROID_KEYSTORE_RELEASE_PATH/_USER/_PASSWORD,
  or those three exported in the environment. See docs/DEPLOY.md > Signing.}"
: "${GODOT_ANDROID_KEYSTORE_RELEASE_USER:?keystore env file is missing _USER}"
: "${GODOT_ANDROID_KEYSTORE_RELEASE_PASSWORD:?keystore env file is missing _PASSWORD}"
[[ -f "$GODOT_ANDROID_KEYSTORE_RELEASE_PATH" ]] \
  || die "keystore not found at $GODOT_ANDROID_KEYSTORE_RELEASE_PATH — restore it from
  backup. It cannot be regenerated; a new key cannot update an installed app."

# A blank keystore/release in the preset is what makes the env vars win. If a
# path ever gets committed there, the build would silently sign with whatever
# that file is — which is exactly how a repo leaks a signing key.
if grep -q '^keystore/release="[^"]' export_presets.cfg; then
  die "export_presets.cfg has a keystore/release path in it. Blank it — the
  keystore belongs in $KEYSTORE_ENV, not in a committed file."
fi

# --------------------------------------------------------------------- version
# Single source of truth, and the only chance to stop before anything is built.
python3 tools/version.py --sync
VERSION_NAME=$(python3 tools/version.py --name)
VERSION_CODE=$(python3 tools/version.py --code)
[[ -n "$VERSION_NAME" && -n "$VERSION_CODE" ]] \
  || die "could not read the version from package.json"

echo
echo "[android] The Heroes' Journey $VERSION_NAME (version code $VERSION_CODE)"
echo "[android] signing with $GODOT_ANDROID_KEYSTORE_RELEASE_PATH (alias $GODOT_ANDROID_KEYSTORE_RELEASE_USER)"
echo

# ----------------------------------------------------------------------- icons
# Cheap, deterministic, and the difference between shipping the game's icon and
# shipping Godot's default robot. Regenerating every build means the launcher
# icon can never fall behind data/themes/firstlight.json.
if python3 -c "import PIL" 2>/dev/null; then
  python3 tools/make_icons.py >/dev/null
  echo "[android] launcher icons regenerated from the theme"
else
  echo "[android] WARNING: Pillow not installed; reusing the committed icons"
fi

APK="$OUT_DIR/HeroesJourney-$VERSION_NAME-$VERSION_CODE.apk"
AAB="$OUT_DIR/HeroesJourney-$VERSION_NAME-$VERSION_CODE.aab"
mkdir -p "$OUT_DIR"
# Same reason run.sh does it for build/: without a .gdignore Godot treats the
# exported APK as a project resource and packs the previous build into the pck.
touch dist/.gdignore
# android/build/ is the gradle project Godot *writes into* — it stages the pck at
# src/main/assets/ and the launcher icons at res/mipmap*/. Without this the next
# import pass picks all of that up as res:// resources, which (a) packs the
# previous export inside the next one, (b) collides UIDs with res://icon.png and
# (c) hard-fails the export once the staging dir is cleaned between builds. Only
# the build/ subdirectory: android/plugins/ is source and must stay visible.
touch android/build/.gdignore

# A fresh checkout — or a run that just wrote four new PNGs — needs an import
# pass before the export can resolve them.
"$GODOT" --headless --path . --import >/dev/null 2>&1 || true

# `gradle_build/export_format` is the only thing that decides APK vs AAB, and
# Godot refuses to write an .aab unless it is set to 1. There is no CLI override,
# so flip it around each export and always put it back — an interrupted build
# must not leave the committed preset saying "AAB".
restore_format() {
  sed -i 's#^gradle_build/export_format=.*#gradle_build/export_format=0#' export_presets.cfg
}
trap restore_format EXIT

set_format() {
  python3 - "$1" <<'PY'
import re, sys
want = sys.argv[1]
blob = open("export_presets.cfg", encoding="utf-8").read()
start = blob.index("[preset.2.options]")
nxt = blob.find("\n[", start)
end = len(blob) if nxt < 0 else nxt
body, n = re.subn(r"(?m)^gradle_build/export_format=.*$",
                  "gradle_build/export_format=" + want, blob[start:end])
assert n == 1, "expected one gradle_build/export_format in [preset.2.options], got %d" % n
open("export_presets.cfg", "w", encoding="utf-8").write(blob[:start] + body + blob[end:])
PY
}

# ---------------------------------------------------------------------- export
# Godot has historically exited 0 after a failed Android export and left a
# zero-byte file behind, so the exit code alone is not evidence of anything.
# Every export is checked three ways: status, the log, and the artefact itself.
export_one() {
  local label="$1" format="$2" path="$3" log
  log=$(mktemp)
  rm -f "$path"
  set_format "$format"

  echo "[android] exporting $label — this takes a few minutes"
  local status=0
  "$GODOT" --headless --path . --export-release "Android" "$path" >"$log" 2>&1 || status=$?

  if (( status != 0 )); then
    sed -n '1,80p' "$log" >&2
    rm -f "$log"
    die "Godot exited $status exporting the $label"
  fi
  # "ERROR:" is Godot's own prefix; the export plugin also fails with plain
  # sentences, so match the ones that actually mean a broken build.
  if grep -qE '^ERROR:|Unable to complete|Building of Android project failed|error: |FAILURE: Build failed' "$log"; then
    grep -nE '^ERROR:|Unable to complete|Building of Android project failed|error: |FAILURE: Build failed' "$log" >&2
    echo "--- full log ---" >&2; sed -n '1,120p' "$log" >&2
    rm -f "$log"
    die "the $label export reported an error"
  fi
  rm -f "$log"

  [[ -f "$path" ]] || die "no $label at $path after a supposedly successful export"
  local bytes
  bytes=$(stat -c%s "$path")
  (( bytes > 1000000 )) || die "$path is only $bytes bytes — the export produced a stub"
  # Both formats are zip containers. A file that is not one was never signed.
  [[ "$(head -c2 "$path")" == "PK" ]] || die "$path is not a zip archive"
}

export_one "APK" 0 "$APK"
if (( APK_ONLY == 0 )); then
  export_one "AAB" 1 "$AAB"
fi
restore_format
trap - EXIT

# ---------------------------------------------------------------------- verify
# apksigner is the only thing that can tell a *signed* APK from a zip that
# happens to contain a manifest, and signing with the wrong key is silent until
# a phone refuses the update.
APKSIGNER=$(ls -1 "$ANDROID_HOME"/build-tools/*/apksigner 2>/dev/null | sort -V | tail -1 || true)
if [[ -n "$APKSIGNER" ]]; then
  "$APKSIGNER" verify --print-certs "$APK" \
    | grep -E 'Signer #1 certificate (DN|SHA-256 digest)' \
    | sed 's/^/[android] /' \
    || die "$APK failed apksigner verification — it is not usably signed"
else
  echo "[android] WARNING: no apksigner under $ANDROID_HOME/build-tools; signature unverified"
fi

# Decimal MB, matching what publish_release.py and run.sh print — otherwise the
# same file is reported at two different sizes two lines apart.
human() { numfmt --to=si --suffix=B --format='%.1f' "$(stat -c%s "$1")"; }

echo
echo "[android] built The Heroes' Journey $VERSION_NAME ($VERSION_CODE)"
printf '[android]   %-52s %s\n' "$APK" "$(human "$APK")"
[[ -f "$AAB" ]] && printf '[android]   %-52s %s\n' "$AAB" "$(human "$AAB")"
echo

# --------------------------------------------------------------------- publish
# Written by another tool and deliberately the only writer of releases/; match
# its CLI rather than reimplementing the index here.
if (( PUBLISH == 1 )) && [[ -f tools/publish_release.py ]]; then
  publish=(python3 tools/publish_release.py
           --apk "$APK"
           --version-name "$VERSION_NAME"
           --version-code "$VERSION_CODE")
  [[ -f "$AAB" ]] && publish+=(--aab "$AAB")
  # publish_release.py falls back to $RELEASE_NOTES itself, and omitting the
  # flag entirely is what makes it keep the notes a republished version already
  # had — so pass it only when there is something to say.
  [[ -n "${RELEASE_NOTES:-}" ]] && publish+=(--notes "$RELEASE_NOTES")
  "${publish[@]}"
elif (( PUBLISH == 1 )); then
  echo "[android] tools/publish_release.py not found; skipping the release publish"
fi

echo
echo "Install on a phone that has never had this app:"
echo "  adb install -r $APK"
echo
echo "The first release-signed build cannot upgrade the debug-signed one that is"
echo "already installed — Android rejects a signature change. Uninstall it first"
echo "(adb uninstall com.kevinhorecka.heroesjourney), which erases its save data."
