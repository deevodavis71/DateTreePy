"""End-to-end checks that drive the real Tk widgets (window kept hidden)."""

import sys
import tempfile
import time
import tkinter as tk
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetree import gui  # noqa: E402
from tests.nef_fixture import build_nef  # noqa: E402

TIMEOUT_SECONDS = 20


class GuiTests(unittest.TestCase):
    """Each test gets a fresh hidden Toplevel.

    One shared Tk root is reused for the whole class: creating and destroying
    several Tk roots in a single process crashes Tk on macOS (SIGTRAP).
    """

    _root: tk.Tk | None = None

    @classmethod
    def setUpClass(cls):
        try:
            cls._root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"no Tk display available: {exc}") from exc
        cls._root.withdraw()

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.source = self.tmp / "card"
        self.dest = self.tmp / "library"
        self.source.mkdir()
        self.dest.mkdir()

        # Never let tests read or write the real user settings file.
        self.settings_path = self.tmp / "settings.json"
        self.app = self._make_app()

    def _make_app(self) -> gui.DateTreeApp:
        window = tk.Toplevel(self._root)
        window.withdraw()
        self.addCleanup(window.destroy)
        self.root = window
        return gui.DateTreeApp(window, settings_path=self.settings_path)

    def _pump_until(self, predicate):
        deadline = time.monotonic() + TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            self.root.update()
            if predicate():
                return
            time.sleep(0.02)
        self.fail(f"timed out; last status was {self.app.status.cget('text')!r}")

    def test_button_disabled_until_both_folders_chosen(self):
        self.assertFalse(self.app.organize_button._enabled)
        self.app.source_panel.set_path(self.source)
        self.assertFalse(self.app.organize_button._enabled)
        self.app.dest_panel.set_path(self.dest)
        self.assertTrue(self.app.organize_button._enabled)
        self.assertEqual(self.app.status.cget("text"), "Ready.")

    def test_select_dialog_updates_field_and_tooltip(self):
        panel = self.app.source_panel
        self.assertEqual(panel._var.get(), "NIKON Z 6")
        self.assertEqual(str(panel._entry.cget("style")), "Placeholder.TEntry")
        with mock.patch.object(
            gui.filedialog, "askdirectory", return_value=str(self.source)
        ):
            panel.choose()
        self.assertEqual(panel.path, self.source)
        self.assertEqual(panel._var.get(), "card")
        self.assertEqual(str(panel._entry.cget("style")), "Path.TEntry")
        self.assertEqual(panel._tooltip._text, str(self.source))

    def test_cancelled_dialog_leaves_state_untouched(self):
        with mock.patch.object(gui.filedialog, "askdirectory", return_value=""):
            self.app.source_panel.choose()
        self.assertIsNone(self.app.source_panel.path)
        self.assertFalse(self.app.organize_button._enabled)

    def test_organize_copies_files_and_reports(self):
        build_nef(self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10")
        build_nef(self.source / "sub" / "DSC_0002.NEF", original="2026:07:26 09:00:00")
        (self.source / "ignore.jpg").write_bytes(b"jpeg")

        self.app.source_panel.set_path(self.source)
        self.app.dest_panel.set_path(self.dest)
        self.app._on_organize()
        self._pump_until(lambda: "Copied" in self.app.status.cget("text"))

        self.assertTrue((self.dest / "2026-07-25" / "DSC_0001.NEF").is_file())
        self.assertTrue((self.dest / "2026-07-26" / "DSC_0002.NEF").is_file())
        self.assertIn("Copied 2", self.app.status.cget("text"))
        # Controls are handed back to the user once the run ends.
        self.assertTrue(self.app.organize_button._enabled)
        self.assertEqual(str(self.app.source_panel._button.cget("state")), "normal")

    def test_second_run_reports_skips(self):
        build_nef(self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10")
        self.app.source_panel.set_path(self.source)
        self.app.dest_panel.set_path(self.dest)

        self.app._on_organize()
        self._pump_until(lambda: "Copied" in self.app.status.cget("text"))
        self.app._on_organize()
        self._pump_until(lambda: "skipped" in self.app.status.cget("text"))
        self.assertIn("skipped 1 already present", self.app.status.cget("text"))

    def test_same_folder_shows_error_dialog(self):
        self.app.source_panel.set_path(self.source)
        self.app.dest_panel.set_path(self.source)
        with mock.patch.object(gui.messagebox, "showerror") as showerror:
            self.app._on_organize()
            self._pump_until(lambda: showerror.called)
        message = showerror.call_args[0][1]
        self.assertIn("same folder", message)
        self.assertEqual(self.app.status.cget("text"), "Failed.")

    def test_mtime_fallback_is_surfaced_in_status(self):
        build_nef(self.source / "DSC_0001.NEF", original=None)
        self.app.source_panel.set_path(self.source)
        self.app.dest_panel.set_path(self.dest)
        self.app._on_organize()
        self._pump_until(lambda: "Copied" in self.app.status.cget("text"))
        self.assertIn("used the file date (no EXIF)", self.app.status.cget("text"))


    def test_choices_are_saved_and_restored_next_launch(self):
        self.app.source_panel.set_path(self.source)
        self.app.dest_panel.set_path(self.dest)

        restarted = self._make_app()
        self.assertEqual(restarted.source_panel.path, self.source)
        self.assertEqual(restarted.dest_panel.path, self.dest)
        self.assertEqual(restarted.source_panel._var.get(), "card")
        self.assertEqual(str(restarted.dest_panel._entry.cget("style")), "Path.TEntry")
        self.assertTrue(restarted.organize_button._enabled)

    def test_saved_folder_that_no_longer_exists_is_not_restored(self):
        gone = self.tmp / "ejected"
        gone.mkdir()
        self.app.source_panel.set_path(gone)
        self.app.dest_panel.set_path(self.dest)
        gone.rmdir()

        restarted = self._make_app()
        self.assertIsNone(restarted.source_panel.path)
        self.assertEqual(restarted.source_panel._var.get(), "NIKON Z 6")
        self.assertEqual(restarted.dest_panel.path, self.dest)
        self.assertFalse(restarted.organize_button._enabled)
        self.assertIn("unavailable", restarted.status.cget("text"))

    def test_activate_window_focuses_without_disturbing_layout(self):
        self.root.deiconify()
        self.addCleanup(self.root.withdraw)
        gui.activate_window(self.root)
        self.assertTrue(self.root.winfo_viewable())
        self.assertEqual(self.root.winfo_width(), 600)
        # -topmost must be released again, or the window would sit above
        # everything else for the rest of the session.
        self._pump_until(lambda: not self.root.attributes("-topmost"))

    def test_first_launch_with_no_settings_file_starts_empty(self):
        self.assertFalse(self.settings_path.exists())
        self.assertIsNone(self.app.source_panel.path)
        self.assertIn("Choose a source", self.app.status.cget("text"))

    def test_restoring_does_not_rewrite_the_settings_file(self):
        self.app.source_panel.set_path(self.source)
        first = self.settings_path.read_text(encoding="utf-8")
        self._make_app()
        self.assertEqual(self.settings_path.read_text(encoding="utf-8"), first)


class HelperTests(unittest.TestCase):
    def test_human_bytes(self):
        self.assertEqual(gui.human_bytes(0), "0 B")
        self.assertEqual(gui.human_bytes(999), "999 B")
        self.assertEqual(gui.human_bytes(1536), "1.5 KB")
        self.assertEqual(gui.human_bytes(5 * 1024**3), "5.0 GB")


if __name__ == "__main__":
    unittest.main()
