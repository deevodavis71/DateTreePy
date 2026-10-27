"""Capture the DateTree window in its main states, for checking UI changes.

    python3 tools/screenshots.py OUT_DIR [aqua|darkaqua]
    python3 tools/screenshots.py --readme

The first form writes 1-empty, 2-ready, 3-done and 4-running PNGs to OUT_DIR,
using synthetic NEFs and a throwaway settings file, so it never touches real
photos or the user's saved folders. The optional argument forces light or dark
appearance.

--readme regenerates docs/screenshot-light.png and docs/screenshot-dark.png:
a staged finished run with realistic paths and totals, captured as a window
(with its shadow) rather than a screen region.

Needs Screen Recording permission for the terminal running it.
"""

import ctypes
import ctypes.util
import os
import subprocess
import sys
import tempfile
import time
import tkinter as tk
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetree import gui  # noqa: E402
from tests.nef_fixture import build_nef  # noqa: E402

TITLE_BAR = 28
PROJECT = Path(__file__).resolve().parent.parent


def own_window_id() -> int:
    """CGWindowID of this process's main window, for `screencapture -l`.

    Tk doesn't expose it, so ask the window server via CoreGraphics.
    """
    cg = ctypes.CDLL(ctypes.util.find_library("CoreGraphics"))
    cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
    cg.CGWindowListCopyWindowInfo.restype = ctypes.c_void_p
    cg.CGWindowListCopyWindowInfo.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
    cf.CFArrayGetCount.restype = ctypes.c_long
    cf.CFArrayGetCount.argtypes = [ctypes.c_void_p]
    cf.CFArrayGetValueAtIndex.restype = ctypes.c_void_p
    cf.CFArrayGetValueAtIndex.argtypes = [ctypes.c_void_p, ctypes.c_long]
    cf.CFDictionaryGetValue.restype = ctypes.c_void_p
    cf.CFDictionaryGetValue.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    cf.CFStringCreateWithCString.restype = ctypes.c_void_p
    cf.CFStringCreateWithCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
    cf.CFNumberGetValue.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]

    def key(name: str):
        return cf.CFStringCreateWithCString(None, name.encode(), 0x08000100)  # UTF-8

    def number(info, name: str) -> int:
        value = ctypes.c_int64()
        cf.CFNumberGetValue(cf.CFDictionaryGetValue(info, key(name)), 4,  # SInt64
                            ctypes.byref(value))
        return value.value

    windows = cg.CGWindowListCopyWindowInfo(1, 0)  # on-screen only
    for i in range(cf.CFArrayGetCount(windows)):
        info = cf.CFArrayGetValueAtIndex(windows, i)
        if number(info, "kCGWindowOwnerPID") == os.getpid() and \
                number(info, "kCGWindowLayer") == 0:
            return number(info, "kCGWindowNumber")
    raise RuntimeError("could not find this process's window")


def readme_screenshots() -> None:
    """Stage a finished run and capture it in light and dark appearance."""
    docs = PROJECT / "docs"
    docs.mkdir(exist_ok=True)
    tmp = Path(tempfile.mkdtemp())
    for appearance, name in (("aqua", "light"), ("darkaqua", "dark")):
        source = tmp / name / "volumes" / "NIKON Z 6"
        dest = tmp / name / "home" / "Pictures"
        source.mkdir(parents=True)
        dest.mkdir(parents=True)
        # Show where these would really live, not the temp folders behind them.
        shown = {source.parent: "/Volumes", dest.parent: "~"}
        root = tk.Tk()
        root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", root, appearance)
        root.update()
        with mock.patch.object(gui, "display_path", lambda p: shown.get(p, str(p))):
            app = gui.DateTreeApp(root, settings_path=tmp / f"{name}.json")
            root.geometry("+200+200")
            gui.activate_window(root)
            app.source_panel.set_path(source)
            app.dest_panel.set_path(dest)
        app.eject_reminder.set(True)
        app.progress.set_fraction(1.0)
        app.status.configure(text="Copied 212 (5.3 GB), skipped 38 already present.")
        for _ in range(40):
            root.update()
            time.sleep(0.02)
        subprocess.run(["screencapture", "-x", "-l", str(own_window_id()),
                        str(docs / f"screenshot-{name}.png")], check=True)
        root.destroy()
    print(f"wrote {docs}/screenshot-light.png and screenshot-dark.png")


def main() -> None:
    if sys.argv[1:] == ["--readme"]:
        readme_screenshots()
        return
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    appearance = sys.argv[2] if len(sys.argv) > 2 else None

    tmp = Path(tempfile.mkdtemp())
    source, dest = tmp / "NIKON Z 6", tmp / "Pictures"
    source.mkdir()
    dest.mkdir()
    for i in range(40):
        build_nef(source / f"DSC_{i:04d}.NEF", original=f"2026:07:{20 + i % 5:02d} 10:00:00")

    root = tk.Tk()
    if appearance:
        root.tk.call("::tk::unsupported::MacWindowStyle", "appearance", root, appearance)
        root.update()
    app = gui.DateTreeApp(root, settings_path=tmp / "settings.json")
    root.geometry("+200+200")
    gui.activate_window(root)

    def grab(name: str) -> None:
        for _ in range(30):
            root.update()
            time.sleep(0.02)
        x, y = root.winfo_rootx(), root.winfo_rooty() - TITLE_BAR
        w, h = root.winfo_width(), root.winfo_height() + TITLE_BAR
        subprocess.run(["screencapture", "-x", "-o", f"-R{x},{y},{w},{h}",
                        str(out / f"{name}.png")], check=True)

    grab("1-empty")
    app.source_panel.set_path(source)
    app.dest_panel.set_path(dest)
    grab("2-ready")
    with mock.patch.object(gui.messagebox, "showinfo"):
        app._on_organize()
        while app._running or "Copied" not in app.status.cget("text"):
            root.update()
            time.sleep(0.02)
    grab("3-done")

    # A real run over 40 tiny files is too quick to catch, so pose one.
    app.progress.set_fraction(0.42)
    app.flow_arrow.set_active(True)
    app.organize_button.set_text("Cancel")
    app.source_panel.set_enabled(False)
    app.dest_panel.set_enabled(False)
    app.status.configure(text="[17/40] DSC_0016.NEF")
    grab("4-running")
    root.destroy()
    print(f"wrote screenshots to {out}")


if __name__ == "__main__":
    main()
