import os
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetree import exif  # noqa: E402
from tests.nef_fixture import build_nef  # noqa: E402


class ReadCaptureDateTimeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_reads_datetime_original_little_endian(self):
        nef = build_nef(self.tmp / "a.NEF", original="2026:07:25 14:32:10")
        self.assertEqual(
            exif.read_capture_datetime(nef), datetime(2026, 7, 25, 14, 32, 10)
        )

    def test_reads_datetime_original_big_endian(self):
        nef = build_nef(
            self.tmp / "b.NEF", original="2019:01:02 03:04:05", byte_order=">"
        )
        self.assertEqual(
            exif.read_capture_datetime(nef), datetime(2019, 1, 2, 3, 4, 5)
        )

    def test_falls_back_to_digitized_then_ifd0(self):
        nef = build_nef(
            self.tmp / "c.NEF", original=None, digitized="2020:05:06 07:08:09"
        )
        self.assertEqual(
            exif.read_capture_datetime(nef), datetime(2020, 5, 6, 7, 8, 9)
        )
        nef = build_nef(
            self.tmp / "d.NEF", original=None, ifd0_datetime="2021:11:12 13:14:15"
        )
        self.assertEqual(
            exif.read_capture_datetime(nef), datetime(2021, 11, 12, 13, 14, 15)
        )

    def test_prefers_original_over_other_tags(self):
        nef = build_nef(
            self.tmp / "e.NEF",
            original="2026:07:25 14:32:10",
            digitized="2000:01:01 00:00:00",
            ifd0_datetime="1999:01:01 00:00:00",
        )
        self.assertEqual(
            exif.read_capture_datetime(nef), datetime(2026, 7, 25, 14, 32, 10)
        )

    def test_returns_none_when_no_date_tags(self):
        nef = build_nef(self.tmp / "f.NEF", original=None)
        self.assertIsNone(exif.read_capture_datetime(nef))

    def test_zeroed_date_is_treated_as_absent(self):
        nef = build_nef(self.tmp / "g.NEF", original="0000:00:00 00:00:00")
        self.assertIsNone(exif.read_capture_datetime(nef))

    def test_rejects_non_tiff(self):
        junk = self.tmp / "h.NEF"
        junk.write_bytes(b"not a raw file at all")
        with self.assertRaises(exif.ExifError):
            exif.read_capture_datetime(junk)

    def test_rejects_truncated_file(self):
        nef = build_nef(self.tmp / "i.NEF")
        data = nef.read_bytes()
        nef.write_bytes(data[:12])
        with self.assertRaises(exif.ExifError):
            exif.read_capture_datetime(nef)


class ParseTests(unittest.TestCase):
    def test_accepts_dashed_form(self):
        self.assertEqual(
            exif.parse_exif_datetime("2026-07-25 14:32:10"),
            datetime(2026, 7, 25, 14, 32, 10),
        )

    def test_accepts_date_only(self):
        self.assertEqual(
            exif.parse_exif_datetime("2026:07:25"), datetime(2026, 7, 25)
        )

    def test_rejects_empty_and_garbage(self):
        self.assertIsNone(exif.parse_exif_datetime("   "))
        self.assertIsNone(exif.parse_exif_datetime("whenever"))


class CaptureDateTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_uses_exif_when_present(self):
        nef = build_nef(self.tmp / "a.NEF", original="2026:07:25 14:32:10")
        os.utime(nef, (0, 0))  # mtime deliberately wrong
        day, source = exif.capture_date(nef)
        self.assertEqual(day, date(2026, 7, 25))
        self.assertEqual(source, exif.DATE_SOURCE_EXIF)

    def test_falls_back_to_mtime(self):
        nef = build_nef(self.tmp / "b.NEF", original=None)
        stamp = datetime(2022, 3, 4, 12, 0, 0).timestamp()
        os.utime(nef, (stamp, stamp))
        day, source = exif.capture_date(nef)
        self.assertEqual(day, date(2022, 3, 4))
        self.assertEqual(source, exif.DATE_SOURCE_MTIME)

    def test_falls_back_to_mtime_for_unparseable_file(self):
        junk = self.tmp / "c.NEF"
        junk.write_bytes(b"garbage")
        stamp = datetime(2023, 8, 9, 6, 0, 0).timestamp()
        os.utime(junk, (stamp, stamp))
        day, source = exif.capture_date(junk)
        self.assertEqual(day, date(2023, 8, 9))
        self.assertEqual(source, exif.DATE_SOURCE_MTIME)

    def test_date_folder_format(self):
        self.assertEqual(exif.date_folder(date(2026, 7, 5)), "2026-07-05")


if __name__ == "__main__":
    unittest.main()
