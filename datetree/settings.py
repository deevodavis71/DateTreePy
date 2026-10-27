"""Remember the folders and options chosen in the previous session."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

APP_DIR_NAME = "DateTree"
KEY_SOURCE = "source"
KEY_DESTINATION = "destination"
KEY_EJECT_REMINDER = "eject_reminder"


def default_settings_path() -> Path:
    """Where to keep settings, following platform convention."""
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / APP_DIR_NAME
    else:
        config_home = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
        base = Path(config_home) / "datetree"
    return base / "settings.json"


@dataclass
class Settings:
    source: Path | None = None
    destination: Path | None = None
    eject_reminder: bool = False


def _as_path(value: object) -> Path | None:
    if isinstance(value, str) and value.strip():
        return Path(value)
    return None


def load(path: Path | None = None) -> Settings:
    """Read saved settings. A missing or unreadable file yields empty settings."""
    path = path or default_settings_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    if not isinstance(raw, dict):
        return Settings()
    return Settings(
        source=_as_path(raw.get(KEY_SOURCE)),
        destination=_as_path(raw.get(KEY_DESTINATION)),
        eject_reminder=raw.get(KEY_EJECT_REMINDER) is True,
    )


def save(settings: Settings, path: Path | None = None) -> bool:
    """Write settings, replacing any existing file. False if it couldn't be saved.

    Failing to save is never worth interrupting a copy over, so the caller is
    free to ignore the result.
    """
    path = path or default_settings_path()
    payload = {
        KEY_SOURCE: str(settings.source) if settings.source else None,
        KEY_DESTINATION: str(settings.destination) if settings.destination else None,
        KEY_EJECT_REMINDER: settings.eject_reminder,
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(dir=path.parent, prefix=".settings.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise
    except OSError:
        return False
    return True
