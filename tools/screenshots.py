"""Capture the DateTree window in its main states, for checking UI changes.

    python3 tools/screenshots.py OUT_DIR [aqua|darkaqua]

Writes 1-empty, 2-ready, 3-done and 4-running PNGs to OUT_DIR, using synthetic
NEFs and a throwaway settings file, so it never touches real photos or the
user's saved folders. The optional argument forces light or dark appearance.
Needs Screen Recording permission for the terminal running it.
"""

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


def main() -> None:
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
