import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetree import settings  # noqa: E402


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.path = self.tmp / "settings.json"

    def test_round_trip(self):
        settings.save(
            settings.Settings(source=Path("/Volumes/CARD"), destination=Path("/Photos")),
            self.path,
        )
        loaded = settings.load(self.path)
        self.assertEqual(loaded.source, Path("/Volumes/CARD"))
        self.assertEqual(loaded.destination, Path("/Photos"))

    def test_creates_parent_directory(self):
        nested = self.tmp / "a" / "b" / "settings.json"
        self.assertTrue(settings.save(settings.Settings(source=Path("/x")), nested))
        self.assertTrue(nested.is_file())

    def test_missing_file_gives_empty_settings(self):
        loaded = settings.load(self.tmp / "absent.json")
        self.assertIsNone(loaded.source)
        self.assertIsNone(loaded.destination)

    def test_corrupt_file_gives_empty_settings(self):
        self.path.write_text("{not json at all", encoding="utf-8")
        self.assertIsNone(settings.load(self.path).source)

    def test_non_object_json_gives_empty_settings(self):
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(settings.load(self.path).source)

    def test_ignores_wrong_types_and_blanks(self):
        self.path.write_text(
            json.dumps({"source": 42, "destination": "   "}), encoding="utf-8"
        )
        loaded = settings.load(self.path)
        self.assertIsNone(loaded.source)
        self.assertIsNone(loaded.destination)

    def test_saving_only_one_side_keeps_other_null(self):
        settings.save(settings.Settings(source=Path("/only")), self.path)
        loaded = settings.load(self.path)
        self.assertEqual(loaded.source, Path("/only"))
        self.assertIsNone(loaded.destination)

    def test_save_overwrites_previous_values(self):
        settings.save(settings.Settings(source=Path("/first")), self.path)
        settings.save(settings.Settings(source=Path("/second")), self.path)
        self.assertEqual(settings.load(self.path).source, Path("/second"))

    def test_save_leaves_no_temp_files_behind(self):
        settings.save(settings.Settings(source=Path("/x")), self.path)
        self.assertEqual([p.name for p in self.tmp.iterdir()], ["settings.json"])

    def test_unwritable_location_reports_failure(self):
        # A path whose parent is a regular file can never be created.
        blocker = self.tmp / "blocker"
        blocker.write_text("", encoding="utf-8")
        self.assertFalse(
            settings.save(settings.Settings(source=Path("/x")), blocker / "s.json")
        )

    def test_default_path_is_under_application_support_on_macos(self):
        path = settings.default_settings_path()
        self.assertEqual(path.name, "settings.json")
        if sys.platform == "darwin":
            self.assertIn("Application Support", str(path))
            self.assertEqual(path.parent.name, "DateTree")


if __name__ == "__main__":
    unittest.main()
