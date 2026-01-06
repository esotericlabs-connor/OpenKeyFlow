#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="$ROOT_DIR/dist"
OUT_FILE="$ROOT_DIR/tools/checksums-latest.txt"

# Files to ignore
IGNORE_EXTENSIONS="txt md sig"

is_ignored() {
  local file="$1"
  for ext in $IGNORE_EXTENSIONS; do
    [[ "$file" == *.$ext ]] && return 0
  done
  return 1
}

hash_file() {
  local file="$1"
  local name
  name="$(basename "$file")"

  sha256=$(sha256sum "$file" | awk '{print $1}')
  sha512=$(sha512sum "$file" | awk '{print $1}')

  echo "SHA256 ($name) = $sha256"
  echo "SHA512 ($name) = $sha512"
  echo
}

# Start fresh
{
  echo "# OpenKeyFlow – Latest Release Checksums"
  echo "# Generated on $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
  echo
} > "$OUT_FILE"

for OS in windows linux macos; do
  OS_DIR="$DIST_DIR/$OS"

  echo "---${OS^^}---" >> "$OUT_FILE"

  if [[ ! -d "$OS_DIR" ]]; then
    echo "PENDING" >> "$OUT_FILE"
    echo >> "$OUT_FILE"
    continue
  fi

  FOUND=false

  while IFS= read -r -d '' file; do
    is_ignored "$file" && continue
    FOUND=true
    hash_file "$file" >> "$OUT_FILE"
  done < <(find "$OS_DIR" -type f -print0)

  if [[ "$FOUND" == false ]]; then
    echo "PENDING" >> "$OUT_FILE"
    echo >> "$OUT_FILE"
  fi
done

echo "✔ checksums-latest.txt updated"
