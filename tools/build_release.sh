#!/usr/bin/env bash
#
# Build a self-contained DateTree.app for distribution, zipped into dist/.
#
# Unlike tools/make_app.sh, the result bundles its own Python and Tk, so it
# runs on a Mac without Homebrew. PyInstaller is installed into a throwaway
# venv under build/; it is a build tool only, never a runtime dependency.
#
#   ./tools/build_release.sh              build for this Mac's architecture
#   ARCH=universal2 ./tools/build_release.sh   needs a universal2 Python
#
# Set DATETREE_PYTHON to choose the interpreter that gets bundled.

set -euo pipefail

PROJECT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT"

VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' datetree/__init__.py)"
PYTHON="${DATETREE_PYTHON:-python3}"
ARCH="${ARCH:-$(uname -m)}"
BUILD="$PROJECT/build/release"
DIST="$PROJECT/dist"
APP="$DIST/DateTree.app"
ZIP="$DIST/DateTree-$VERSION-macOS-$ARCH.zip"

if [ -z "$VERSION" ]; then
    echo "could not read __version__ from datetree/__init__.py" >&2
    exit 1
fi

# Same guard as make_app.sh: a Tk-less Python freezes into an app that can't start.
if ! "$PYTHON" -c 'import tkinter' >/dev/null 2>&1; then
    echo "$PYTHON has no Tk support; it cannot be bundled." >&2
    exit 1
fi

rm -rf "$BUILD" "$APP" "$ZIP"
"$PYTHON" -m venv "$BUILD/venv"
"$BUILD/venv/bin/python" -m pip install --quiet --upgrade pip
"$BUILD/venv/bin/python" -m pip install --quiet -r tools/release-requirements.txt

"$BUILD/venv/bin/pyinstaller" \
    --noconfirm --clean --log-level WARN \
    --windowed \
    --name DateTree \
    --icon "$PROJECT/assets/DateTree.icns" \
    --osx-bundle-identifier io.github.deevodavis71.datetreepy \
    --target-arch "$ARCH" \
    --paths "$PROJECT" \
    --distpath "$DIST" \
    --workpath "$BUILD/work" \
    --specpath "$BUILD" \
    tools/release_entry.py

# PyInstaller writes a minimal Info.plist; fill in what make_app.sh also sets.
PLIST="$APP/Contents/Info.plist"
plutil -replace CFBundleShortVersionString -string "$VERSION" "$PLIST"
plutil -replace CFBundleVersion -string "$VERSION" "$PLIST"
plutil -replace CFBundleDisplayName -string DateTree "$PLIST"
plutil -replace LSApplicationCategoryType -string public.app-category.photography "$PLIST"
plutil -replace LSMinimumSystemVersion -string 12.0 "$PLIST"
plutil -replace NSRequiresAquaSystemAppearance -bool false "$PLIST"

# Editing Info.plist invalidates PyInstaller's signature, so sign again.
# Ad-hoc only: there is no Developer ID, so Gatekeeper will still ask the user
# to approve the app once (see README).
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

# ditto keeps the bundle's symlinks and extended attributes, which zip does not.
ditto -c -k --keepParent "$APP" "$ZIP"
echo "built $ZIP"
