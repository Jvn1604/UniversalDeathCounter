#!/usr/bin/env bash
# Turns the PyInstaller folder (dist/UniversalDeathCounter) into one
# AppImage file that runs on most Linux desktops without installing.
#
#   packaging/make_appimage.sh 2.10.0
#
# Needs appimagetool on PATH (the CI workflow downloads it).
set -euo pipefail

version="${1:?usage: make_appimage.sh <version>}"
root="$(cd "$(dirname "$0")/.." && pwd)"
appdir="$root/dist/AppDir"

rm -rf "$appdir"
mkdir -p "$appdir/usr/lib"
cp -a "$root/dist/UniversalDeathCounter" "$appdir/usr/lib/"
cp "$root/assets/icons/app_icon_256.png" "$appdir/universaldeathcounter.png"

cat > "$appdir/universaldeathcounter.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=DePhantom Universal Death Counter
Comment=Death counter and OBS overlay for hard games
Exec=UniversalDeathCounter
Icon=universaldeathcounter
Categories=Game;Utility;
EOF

cat > "$appdir/AppRun" <<'EOF'
#!/bin/sh
here="$(dirname "$(readlink -f "$0")")"
exec "$here/usr/lib/UniversalDeathCounter/UniversalDeathCounter" "$@"
EOF
chmod +x "$appdir/AppRun"

ARCH=x86_64 appimagetool "$appdir" "$root/dist/UniversalDeathCounter-$version-x86_64.AppImage"
