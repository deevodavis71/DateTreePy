"""Scan a source tree for raw files and copy them into date folders."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Sequence

from .exif import capture_date, date_folder

DEFAULT_EXTENSIONS = (".nef",)

STATUS_COPIED = "copied"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"


@dataclass
class FileResult:
    source: Path
    status: str
    dest: Path | None = None
    date_source: str | None = None
    error: str | None = None


@dataclass
class Summary:
    copied: int = 0
    skipped: int = 0
    failed: int = 0
    bytes_copied: int = 0
    cancelled: bool = False
    results: list[FileResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.copied + self.skipped + self.failed

    def record(self, result: FileResult) -> None:
        self.results.append(result)
        if result.status == STATUS_COPIED:
            self.copied += 1
        elif result.status == STATUS_SKIPPED:
            self.skipped += 1
        else:
            self.failed += 1


class OrganizeError(Exception):
    """Raised for problems that stop the whole run before it starts."""


def find_raw_files(
    source: Path,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
    exclude: Path | None = None,
) -> Iterator[Path]:
    """Yield matching files under source, recursively and in stable order.

    exclude prunes a directory from the walk, which keeps a destination
    nested inside the source from feeding freshly copied files back in.
    """
    wanted = {ext.lower() for ext in extensions}
    exclude_resolved = None
    if exclude is not None:
        try:
            exclude_resolved = exclude.resolve()
        except OSError:
            exclude_resolved = None

    for dirpath, dirnames, filenames in os.walk(source, onerror=lambda _e: None):
        if exclude_resolved is not None:
            kept = []
            for name in dirnames:
                try:
                    if Path(dirpath, name).resolve() == exclude_resolved:
                        continue
                except OSError:
                    pass
                kept.append(name)
            dirnames[:] = kept
        dirnames.sort()
        for name in sorted(filenames):
            # "._NAME.NEF" files are macOS AppleDouble metadata stubs, not photos.
            if name.startswith("._"):
                continue
            if Path(name).suffix.lower() in wanted:
                yield Path(dirpath, name)


def destination_for(source_file: Path, dest_root: Path) -> tuple[Path, str]:
    """Return (destination path, date source) for one file."""
    day, date_source = capture_date(source_file)
    return dest_root / date_folder(day) / source_file.name, date_source


def _copy_file(source_file: Path, dest_file: Path) -> int:
    """Copy via a temp file in the destination folder, then rename into place.

    A crash mid-copy would otherwise leave a truncated file that later runs
    would treat as already copied and skip forever.
    """
    dest_file.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        dir=dest_file.parent, prefix=f".{dest_file.name}.", suffix=".part"
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with open(source_file, "rb") as src, open(temp_path, "wb") as dst:
            shutil.copyfileobj(src, dst, length=4 * 1024 * 1024)
        expected = source_file.stat().st_size
        written = temp_path.stat().st_size
        if written != expected:
            raise OSError(f"size mismatch after copy ({written} != {expected})")
        shutil.copystat(source_file, temp_path)
        os.replace(temp_path, dest_file)
        return written
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise


def organize(
    source: Path,
    dest_root: Path,
    extensions: Sequence[str] = DEFAULT_EXTENSIONS,
    on_scanned: Callable[[int], None] | None = None,
    on_progress: Callable[[int, int, Path], None] | None = None,
    is_cancelled: Callable[[], bool] | None = None,
) -> Summary:
    """Copy every matching file from source into dest_root/YYYY-MM-DD/.

    Files whose destination name already exists are skipped. Callbacks let a
    GUI report progress; is_cancelled is polled between files.
    """
    source = Path(source)
    dest_root = Path(dest_root)

    if not source.is_dir():
        raise OrganizeError(f"Source folder does not exist: {source}")
    if not dest_root.is_dir():
        raise OrganizeError(f"Destination folder does not exist: {dest_root}")
    if source.resolve() == dest_root.resolve():
        raise OrganizeError("Source and destination are the same folder.")

    files = list(find_raw_files(source, extensions, exclude=dest_root))
    if on_scanned is not None:
        on_scanned(len(files))

    summary = Summary()
    for index, source_file in enumerate(files, start=1):
        if is_cancelled is not None and is_cancelled():
            summary.cancelled = True
            break
        if on_progress is not None:
            on_progress(index, len(files), source_file)
        try:
            dest_file, date_source = destination_for(source_file, dest_root)
            if dest_file.exists():
                summary.record(
                    FileResult(
                        source_file, STATUS_SKIPPED, dest_file, date_source
                    )
                )
                continue
            written = _copy_file(source_file, dest_file)
            summary.bytes_copied += written
            summary.record(
                FileResult(source_file, STATUS_COPIED, dest_file, date_source)
            )
        except OSError as exc:
            summary.record(FileResult(source_file, STATUS_FAILED, error=str(exc)))
    return summary
