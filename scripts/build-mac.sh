#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p .build/module-cache dist
build_dir=$(mktemp -d "${TMPDIR:-/tmp}/splat-build.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT
mkdir -p "$build_dir/Splat Attack.app/Contents/MacOS"
xcrun swiftc -swift-version 5 -parse-as-library -O -module-cache-path "$PWD/.build/module-cache" \
  macos/SplatAttack.swift -o "$build_dir/Splat Attack.app/Contents/MacOS/SplatAttack" \
  -framework SwiftUI -framework AppKit
python3 - "$build_dir" <<'PY'
import plistlib, sys
from pathlib import Path
root = Path.cwd()
with (Path(sys.argv[1]) / 'Splat Attack.app/Contents/Info.plist').open('wb') as file:
    plistlib.dump(dict(CFBundleExecutable='SplatAttack', CFBundleIdentifier='com.splatattack.local',
                      CFBundleName='Splat Attack', CFBundlePackageType='APPL', CFBundleVersion='1',
                      CFBundleShortVersionString='0.1.0', LSMinimumSystemVersion='14.0',
                      NSHighResolutionCapable=True, SplatRepository=str(root)), file)
PY
codesign --force --deep --sign - "$build_dir/Splat Attack.app"
# Signing outside synced folders avoids FinderInfo/FileProvider races.
ditto --norsrc "$build_dir/Splat Attack.app" "dist/Splat Attack.app"
xattr -cr "dist/Splat Attack.app"
echo 'Built dist/Splat Attack.app'
