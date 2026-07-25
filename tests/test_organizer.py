import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetree import organizer  # noqa: E402
from datetree.exif import DATE_SOURCE_EXIF, DATE_SOURCE_MTIME  # noqa: E402
from tests.nef_fixture import build_nef  # noqa: E402


class OrganizeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.source = self.tmp / "card"
        self.dest = self.tmp / "library"
        self.source.mkdir()
        self.dest.mkdir()

    def test_copies_into_capture_date_folder(self):
        build_nef(self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10")
        summary = organizer.organize(self.source, self.dest)
        self.assertEqual(summary.copied, 1)
        self.assertTrue((self.dest / "2026-07-25" / "DSC_0001.NEF").is_file())
        self.assertEqual(summary.results[0].date_source, DATE_SOURCE_EXIF)

    def test_recurses_and_groups_by_day(self):
        build_nef(self.source / "100ND750" / "a.NEF", original="2026:07:25 09:00:00")
        build_nef(self.source / "100ND750" / "b.NEF", original="2026:07:25 23:59:59")
        build_nef(self.source / "101ND750" / "c.NEF", original="2026:07:26 00:00:01")
        summary = organizer.organize(self.source, self.dest)
        self.assertEqual(summary.copied, 3)
        self.assertEqual(
            sorted(p.name for p in (self.dest / "2026-07-25").iterdir()),
            ["a.NEF", "b.NEF"],
        )
        self.assertTrue((self.dest / "2026-07-26" / "c.NEF").is_file())

    def test_ignores_other_extensions(self):
        build_nef(self.source / "keep.NEF", original="2026:07:25 10:00:00")
        (self.source / "skip.jpg").write_bytes(b"jpeg")
        (self.source / "skip.xmp").write_bytes(b"xmp")
        summary = organizer.organize(self.source, self.dest)
        self.assertEqual(summary.total, 1)
        self.assertEqual(summary.copied, 1)

    def test_extension_match_is_case_insensitive(self):
        build_nef(self.source / "lower.nef", original="2026:07:25 10:00:00")
        build_nef(self.source / "upper.NEF", original="2026:07:25 10:00:00")
        summary = organizer.organize(self.source, self.dest)
        self.assertEqual(summary.copied, 2)

    def test_skips_appledouble_stubs(self):
        build_nef(self.source / "._DSC_0001.NEF", original="2026:07:25 10:00:00")
        summary = organizer.organize(self.source, self.dest)
        self.assertEqual(summary.total, 0)

    def test_skips_when_destination_name_exists(self):
        build_nef(self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10")
        existing = self.dest / "2026-07-25" / "DSC_0001.NEF"
        existing.parent.mkdir(parents=True)
        existing.write_bytes(b"already here")

        summary = organizer.organize(self.source, self.dest)
        self.assertEqual(summary.copied, 0)
        self.assertEqual(summary.skipped, 1)
        self.assertEqual(existing.read_bytes(), b"already here")

    def test_rerun_is_idempotent(self):
        build_nef(self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10")
        organizer.organize(self.source, self.dest)
        second = organizer.organize(self.source, self.dest)
        self.assertEqual((second.copied, second.skipped), (0, 1))

    def test_preserves_content_and_mtime(self):
        source_file = build_nef(
            self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10",
            payload=b"x" * 5000,
        )
        stamp = datetime(2026, 7, 25, 14, 32, 10).timestamp()
        os.utime(source_file, (stamp, stamp))
        organizer.organize(self.source, self.dest)
        copied = self.dest / "2026-07-25" / "DSC_0001.NEF"
        self.assertEqual(copied.read_bytes(), source_file.read_bytes())
        self.assertAlmostEqual(copied.stat().st_mtime, stamp, places=0)

    def test_uses_mtime_when_exif_missing(self):
        source_file = build_nef(self.source / "DSC_0001.NEF", original=None)
        stamp = datetime(2024, 2, 29, 8, 0, 0).timestamp()
        os.utime(source_file, (stamp, stamp))
        summary = organizer.organize(self.source, self.dest)
        self.assertTrue((self.dest / "2024-02-29" / "DSC_0001.NEF").is_file())
        self.assertEqual(summary.results[0].date_source, DATE_SOURCE_MTIME)

    def test_destination_inside_source_is_not_rescanned(self):
        nested_dest = self.source / "organised"
        nested_dest.mkdir()
        build_nef(self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10")
        summary = organizer.organize(self.source, nested_dest)
        self.assertEqual(summary.copied, 1)
        self.assertEqual(summary.total, 1)

    def test_rejects_same_source_and_destination(self):
        with self.assertRaises(organizer.OrganizeError):
            organizer.organize(self.source, self.source)

    def test_rejects_missing_folders(self):
        with self.assertRaises(organizer.OrganizeError):
            organizer.organize(self.tmp / "nope", self.dest)
        with self.assertRaises(organizer.OrganizeError):
            organizer.organize(self.source, self.tmp / "nope")

    def test_cancellation_stops_early(self):
        for index in range(5):
            build_nef(
                self.source / f"DSC_000{index}.NEF", original="2026:07:25 10:00:00"
            )
        seen = []

        def cancel_after_two():
            return len(seen) >= 2

        def note(done, total, path):
            seen.append(path)

        summary = organizer.organize(
            self.source, self.dest, on_progress=note, is_cancelled=cancel_after_two
        )
        self.assertTrue(summary.cancelled)
        self.assertEqual(summary.copied, 2)

    def test_failed_copy_is_reported_and_leaves_no_partial_file(self):
        build_nef(self.source / "DSC_0001.NEF", original="2026:07:25 14:32:10")
        with mock.patch.object(
            organizer.shutil, "copyfileobj", side_effect=OSError("disk on fire")
        ):
            summary = organizer.organize(self.source, self.dest)
        self.assertEqual(summary.failed, 1)
        self.assertIn("disk on fire", summary.results[0].error)
        day_folder = self.dest / "2026-07-25"
        self.assertEqual(list(day_folder.iterdir()), [])

    def test_progress_and_scan_callbacks_fire(self):
        build_nef(self.source / "a.NEF", original="2026:07:25 10:00:00")
        build_nef(self.source / "b.NEF", original="2026:07:25 11:00:00")
        totals, progress = [], []
        organizer.organize(
            self.source,
            self.dest,
            on_scanned=totals.append,
            on_progress=lambda done, total, path: progress.append((done, total)),
        )
        self.assertEqual(totals, [2])
        self.assertEqual(progress, [(1, 2), (2, 2)])

    def test_summary_counts_bytes(self):
        build_nef(self.source / "a.NEF", original="2026:07:25 10:00:00",
                  payload=b"y" * 1000)
        summary = organizer.organize(self.source, self.dest)
        expected = (self.source / "a.NEF").stat().st_size
        self.assertEqual(summary.bytes_copied, expected)


if __name__ == "__main__":
    unittest.main()
