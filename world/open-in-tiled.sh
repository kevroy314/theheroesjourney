#!/usr/bin/env bash
# Open the world map in Tiled.
#
# Tiled is not a build dependency — nothing in run.sh, test.sh or the Godot
# export touches it — so it is not installed by the project. This finds whatever
# copy is on the machine and says how to get one if there is none.
#
#   world/open-in-tiled.sh            # the map
#   world/open-in-tiled.sh --project  # the whole project pane
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

target="$here/overworld.tmj"
[[ "${1:-}" == "--project" ]] && target="$here/heroes.tiled-project"
if [[ ! -f "$target" ]]; then
  echo "no $target yet — run: npm run world:export" >&2
  exit 1
fi

pick() {
  command -v tiled >/dev/null 2>&1 && { echo tiled; return; }
  for app in "$HOME/Applications"/Tiled-*.AppImage /opt/Tiled-*.AppImage; do
    [[ -x "$app" ]] && { echo "$app"; return; }
  done
  command -v flatpak >/dev/null 2>&1 \
    && flatpak info org.mapeditor.Tiled >/dev/null 2>&1 \
    && { echo "flatpak run org.mapeditor.Tiled"; return; }
}

bin="$(pick || true)"
if [[ -z "$bin" ]]; then
  cat >&2 <<'MSG'
Tiled is not installed. Any of these will do:
  curl -L -o ~/Applications/Tiled.AppImage \
    https://github.com/mapeditor/tiled/releases/latest/download/Tiled-1.12.2_Linux_x86_64.AppImage
  chmod +x ~/Applications/Tiled.AppImage
  flatpak install flathub org.mapeditor.Tiled
  sudo apt install tiled          # 1.8 on jammy: old, but it opens this map
MSG
  exit 1
fi

# Tiled's AppImage ships a Wayland plugin it cannot always load under WSLg, and
# the failure is a hard exit rather than a fallback. Pin xcb; XWayland is there.
export QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-xcb}"
exec $bin "$target"
