#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'This installer targets Apple Silicon Macs, macOS 14 or newer.'; exit 1
fi
if ! command -v brew >/dev/null; then
  echo 'Install Homebrew from https://brew.sh, then run this script again.'; exit 1
fi
for package in python@3.11 ffmpeg; do
  brew list "$package" >/dev/null 2>&1 || brew install "$package"
done
if [[ ! -x .venv/bin/python ]]; then
  "$(brew --prefix python@3.11)/bin/python3.11" -m venv .venv
fi
.venv/bin/pip install -r requirements.txt
mkdir -p .tools/brush
if [[ ! -x .tools/brush/brush_app ]]; then
  archive=$(mktemp -t splat-brush)
  trap 'rm -f "$archive"' EXIT
  curl -fL 'https://github.com/ArthurBrussee/brush/releases/download/v0.3.0/brush-app-aarch64-apple-darwin.tar.xz' -o "$archive"
  expected=65b2631398c839be3c1d4d7160fe2326389dec87830aac0710985e6690a1048c
  actual=$(shasum -a 256 "$archive" | cut -d ' ' -f 1)
  [[ "$actual" == "$expected" ]] || { echo 'Brush download checksum mismatch'; exit 1; }
  tar -xf "$archive" -C .tools/brush --strip-components=1
fi
.venv/bin/python -m splat_attack.pipeline doctor
bash scripts/build-mac.sh
echo 'Setup complete. Open dist/Splat Attack.app.'
