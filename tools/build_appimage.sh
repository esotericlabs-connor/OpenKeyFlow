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
CLEANUP="${CLEANUP:-1}"


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

if [[ ! -e "dist/$APP_NAME" ]]; then
  echo "PyInstaller output not found at dist/$APP_NAME" >&2
  exit 1
fi

# ------------------------------------------------------------
# 2/4 – Prepare linuxdeploy inputs
# ------------------------------------------------------------
echo "[2/4] Preparing linuxdeploy inputs"
rm -rf "$APPDIR"
mkdir -p "$BUILD_ROOT"

if [[ -f "dist/$APP_NAME" ]]; then
  APP_EXECUTABLE="$ROOT_DIR/dist/$APP_NAME"
elif [[ -d "dist/$APP_NAME" ]]; then
  APP_EXECUTABLE="$ROOT_DIR/dist/$APP_NAME/$APP_NAME"
else
  echo "PyInstaller output at dist/$APP_NAME is not a file or directory" >&2
  exit 1
fi

if [[ ! -x "$APP_EXECUTABLE" ]]; then
  echo "Executable not found or not executable: $APP_EXECUTABLE" >&2
  exit 1
fi

DESKTOP_FILE="$BUILD_ROOT/openkeyflow.desktop"
cat > "$DESKTOP_FILE" <<'DESKTOP'
[Desktop Entry]
Type=Application
Name=OpenKeyFlow
Exec=OpenKeyFlow
Icon=openkeyflow
Categories=Utility;
Terminal=false
DESKTOP

ICON_FILE="$ROOT_DIR/assets/okf_logo_light.png"
if [[ ! -f "$ICON_FILE" ]]; then
  echo "Icon file not found at $ICON_FILE" >&2
  exit 1
fi

# ------------------------------------------------------------
# 3/4 – linuxdeploy
# ------------------------------------------------------------
LINUXDEPLOY="${LINUXDEPLOY:-"$BUILD_ROOT/linuxdeploy-x86_64.AppImage"}"
LINUXDEPLOY_URL="https://github.com/linuxdeploy/linuxdeploy/releases/download/continuous/linuxdeploy-x86_64.AppImage"

if [[ ! -x "$LINUXDEPLOY" ]]; then
  echo "[3/4] Downloading linuxdeploy"
  mkdir -p "$BUILD_ROOT"
  curl -L -o "$LINUXDEPLOY" "$LINUXDEPLOY_URL"
  chmod +x "$LINUXDEPLOY"
fi

# ------------------------------------------------------------
# 4/4 – Build AppImage
# ------------------------------------------------------------
echo "[4/4] Building AppImage"
ARCH="$(uname -m)"
OUTPUT="${OUTPUT:-"$ROOT_DIR/dist/${APP_NAME}-${VERSION}-${ARCH}.AppImage"}"

"$LINUXDEPLOY" \
  --appdir "$APPDIR" \
  --executable "$APP_EXECUTABLE" \
  --desktop-file "$DESKTOP_FILE" \
  --icon-file "$ICON_FILE" \
  --output appimage

if [[ -e "$ROOT_DIR"/*.AppImage ]]; then
  mv "$ROOT_DIR"/*.AppImage "$OUTPUT"
fi
chmod +x "$OUTPUT"

if command -v ldconfig >/dev/null 2>&1; then
  if ! ldconfig -p 2>/dev/null | grep -q 'libfuse\.so\.2'; then
    echo "⚠️  libfuse2 not detected. If the AppImage won't launch, install libfuse2 or run with:" >&2
    echo "    APPIMAGE_EXTRACT_AND_RUN=1 \"$OUTPUT\"" >&2
  fi
fi

echo "✔ AppImage created at: $OUTPUT"

if [[ "$CLEANUP" == "1" ]]; then
  rm -rf "$APPDIR" "$ROOT_DIR/build" "$ROOT_DIR/dist/$APP_NAME" "$DESKTOP_FILE"
fi