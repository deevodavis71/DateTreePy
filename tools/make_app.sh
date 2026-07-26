#!/usr/bin/env bash
#
# (Re)build DateTree.app in the project root.
#
# The bundle is a build artifact and is not tracked in git: its launcher has the
# project path baked in and it links a machine-specific Python. Run this after
# cloning, after a Python change, or after editing the launcher or icon.

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP="$PROJECT/DateTree.app"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$PROJECT/datetree/__init__.py")"
VERSION="${VERSION:-1.0.0}"
PYTHON="${DATETREE_PYTHON:-python3}"

# Check Tk before building anything. The bundle pins the interpreter it links,
# so a Tk-less one would produce an app that cannot start -- and because the
# link exists, the launcher's start.sh fallback would not kick in either.
if ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    cat >&2 <<EOF
$PYTHON has no Tk support, so linking it would produce an app that cannot start.

    brew install python-tk

Then run this script again, or set DATETREE_PYTHON to a Python that has Tk.
EOF
    exit 1
fi

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleDevelopmentRegion</key>          <string>en</string>
    <key>CFBundleDisplayName</key>                <string>DateTree</string>
    <key>CFBundleExecutable</key>                 <string>DateTree</string>
    <key>CFBundleIconFile</key>                   <string>DateTree</string>
    <key>CFBundleIdentifier</key>                 <string>io.github.deevodavis71.datetreepy</string>
    <key>CFBundleInfoDictionaryVersion</key>      <string>6.0</string>
    <key>CFBundleName</key>                       <string>DateTree</string>
    <key>CFBundlePackageType</key>                <string>APPL</string>
    <key>CFBundleShortVersionString</key>         <string>${VERSION}</string>
    <key>CFBundleSignature</key>                  <string>????</string>
    <key>CFBundleVersion</key>                    <string>${VERSION}</string>
    <key>LSApplicationCategoryType</key>          <string>public.app-category.photography</string>
    <key>LSMinimumSystemVersion</key>             <string>12.0</string>
    <key>NSHighResolutionCapable</key>            <true/>
    <key>NSRequiresAquaSystemAppearance</key>     <false/>
</dict>
</plist>
PLIST

# Generate the launcher from its template, baking in the project location as a
# fallback for when the bundle is copied somewhere else, such as /Applications.
# Generating rather than editing in place keeps this correct if the project moves.
sed "s|__PROJECT_DIR__|$PROJECT|g" "$PROJECT/tools/launcher.sh.in" \
    > "$APP/Contents/MacOS/DateTree"
chmod +x "$APP/Contents/MacOS/DateTree"

# The icon is a tracked source asset; the bundle gets a copy of it.
ICON="$PROJECT/assets/DateTree.icns"
if [ ! -f "$ICON" ]; then
    python3 "$PROJECT/tools/make_icon.py" "$ICON"
fi
cp "$ICON" "$APP/Contents/Resources/DateTree.icns"

# Link the GUI-capable Python binary into the bundle. macOS attributes a process
# to the bundle its executable path sits in, so launching Python through this
# symlink is what gets DateTree's own name and icon in the Dock instead of
# Python's. Framework Python resolves its prefix through the symlink correctly.
GUI_BINARY="$("$PYTHON" - <<'PY'
import sys
from pathlib import Path
candidate = Path(sys.prefix) / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
print(candidate if candidate.exists() else "")
PY
)"
if [ -n "$GUI_BINARY" ]; then
    ln -sfn "$GUI_BINARY" "$APP/Contents/MacOS/python-gui"
    echo "linked python-gui -> $GUI_BINARY"
else
    rm -f "$APP/Contents/MacOS/python-gui"
    echo "note: no Python.app binary found for $PYTHON; the app will appear" >&2
    echo "      in the Dock as \"Python\" but will still work" >&2
fi

# Ad-hoc sign so macOS treats it as a stable, identified app rather than
# re-prompting for permissions (Photos, removable volumes) on every change.
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 ||
    echo "note: ad-hoc codesign failed; the app still runs" >&2

# Nudge LaunchServices so Finder picks up the icon and name straight away.
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
    -f "$APP" >/dev/null 2>&1 || true

echo "built $APP (version $VERSION)"
