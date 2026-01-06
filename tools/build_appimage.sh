#!/usr/bin/env bash
set -euo pipefail

# ------------------------------------------------------------
# Paths / constants
# ------------------------------------------------------------
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="OpenKeyFlow"
PYTHON_BIN="${PYTHON_BIN:-python}"
BUILD_ROOT="${BUILD_ROOT:-"$ROOT_DIR/dist/appimage"}"
APPDIR="$BUILD_ROOT/${APP_NAME}.AppDir"

# ------------------------------------------------------------
# Read version (TOML-safe, Py3.11+)
# ------------------------------------------------------------
VERSION="$(
  "$PYTHON_BIN" - <<'PY'
import tomllib
from pathlib import Path

toml_path = Path("openkeyflow.toml")
if not toml_path.exists():
    raise SystemExit("openkeyflow.toml not found")

metadata = tomllib.loads(toml_path.read_text(encoding="utf-8"))
print(metadata["project"]["version"])
PY
)"

# ------------------------------------------------------------
# Preconditions
# ------------------------------------------------------------
if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "pyinstaller is required. Install with:" >&2
  echo "  $PYTHON_BIN -m pip install pyinstaller" >&2
  exit 1
fi

cd "$ROOT_DIR"

# ------------------------------------------------------------
# 1/4 – PyInstaller build
# ------------------------------------------------------------
echo "[1/4] Building PyInstaller bundle"
rm -rf build dist
pyinstaller OpenKeyFlow.spec

if [[ ! -d "dist/$APP_NAME" ]]; then
  echo "PyInstaller output not found at dist/$APP_NAME" >&2
  exit 1
fi

# ------------------------------------------------------------
# 2/4 – Assemble AppDir
# ------------------------------------------------------------
echo "[2/4] Assembling AppDir"
rm -rf "$APPDIR"
mkdir -p \
  "$APPDIR/usr/bin" \
  "$APPDIR/usr/share/applications" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -a "dist/$APP_NAME/." "$APPDIR/usr/bin/"

cat > "$APPDIR/usr/share/applications/openkeyflow.desktop" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=OpenKeyFlow
Exec=OpenKeyFlow
Icon=openkeyflow
Categories=Utility;
Terminal=false
DESKTOP

cp "assets/okf_logo_light.png" \
  "$APPDIR/usr/share/icons/hicolor/256x256/apps/openkeyflow.png"
cp "assets/okf_logo_light.png" "$APPDIR/openkeyflow.png"

# ------------------------------------------------------------
# AppRun (absolute, robust)
# ------------------------------------------------------------
cat > "$APPDIR/AppRun" <<'APPRUN'
#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec "$HERE/usr/bin/OpenKeyFlow" "$@"
APPRUN
chmod +x "$APPDIR/AppRun"

# ------------------------------------------------------------
# 3/4 – appimagetool
# ------------------------------------------------------------
APPIMAGETOOL="${APPIMAGETOOL:-"$BUILD_ROOT/appimagetool.AppImage"}"

if [[ ! -x "$APPIMAGETOOL" ]]; then
  echo "[3/4] Downloading appimagetool"
  mkdir -p "$BUILD_ROOT"
  curl -L -o "$APPIMAGETOOL" \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage"
  chmod +x "$APPIMAGETOOL"
fi

# ------------------------------------------------------------
# 4/4 – Build AppImage
# ------------------------------------------------------------
echo "[4/4] Building AppImage"
ARCH="$(uname -m)"
OUTPUT="${OUTPUT:-"$ROOT_DIR/dist/${APP_NAME}-${VERSION}-${ARCH}.AppImage"}"

"$APPIMAGETOOL" "$APPDIR" "$OUTPUT"

echo "✔ AppImage created at: $OUTPUT"
