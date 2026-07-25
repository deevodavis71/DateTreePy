"""Tkinter GUI for DateTree."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import settings as settings_store
from .exif import DATE_SOURCE_MTIME
from .organizer import (
    DEFAULT_EXTENSIONS,
    STATUS_FAILED,
    OrganizeError,
    Summary,
    organize,
)

APP_NAME = "DateTree"
POLL_MS = 80


@dataclass(frozen=True)
class Palette:
    text: str
    muted: str
    tile: str
    tile_border: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_disabled: str
    accent_text: str
    drive_body: str
    drive_edge: str
    drive_glyph: str
    folder_front: str
    folder_back: str
    folder_edge: str


LIGHT = Palette(
    text="#1d1d1f",
    muted="#8e8e93",
    tile="#ededed",
    tile_border="#dcdcdc",
    accent="#007aff",
    accent_hover="#0a84ff",
    accent_pressed="#0062cc",
    accent_disabled="#b9b9bd",
    accent_text="#ffffff",
    drive_body="#e9cd97",
    drive_edge="#c9a86a",
    drive_glyph="#b4914f",
    folder_front="#7cb8ee",
    folder_back="#5aa2e5",
    folder_edge="#4a90d9",
)

DARK = Palette(
    text="#f2f2f7",
    muted="#8e8e93",
    tile="#2c2c2e",
    tile_border="#3a3a3c",
    accent="#0a84ff",
    accent_hover="#3d9bff",
    accent_pressed="#0062cc",
    accent_disabled="#48484a",
    accent_text="#ffffff",
    drive_body="#d9bc86",
    drive_edge="#a98d55",
    drive_glyph="#8d7440",
    folder_front="#5aa2e5",
    folder_back="#4a8fd0",
    folder_edge="#3f7cb8",
)


def window_background(widget: tk.Misc) -> str:
    """Background colour to paint canvases with so they blend into the window.

    ttk widgets have no -background option, so it has to come from the theme.
    """
    try:
        colour = ttk.Style(widget).lookup("TFrame", "background")
    except tk.TclError:
        colour = ""
    return colour or "systemWindowBackgroundColor"


def detect_palette(widget: tk.Misc) -> Palette:
    """Pick a light or dark palette from the system window background."""
    for colour in ("systemWindowBackgroundColor", window_background(widget)):
        try:
            r, g, b = widget.winfo_rgb(colour)
        except tk.TclError:
            continue
        luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 65535
        return DARK if luminance < 0.5 else LIGHT
    return LIGHT


def human_bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _round_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, **kwargs) -> int:
    """Draw a rounded rectangle (Tk has no primitive for one)."""
    points = [
        x1 + radius, y1, x2 - radius, y1, x2, y1,
        x2, y1 + radius, x2, y2 - radius, x2, y2,
        x2 - radius, y2, x1 + radius, y2, x1, y2,
        x1, y2 - radius, x1, y1 + radius, x1, y1,
    ]
    return canvas.create_polygon(points, smooth=True, splinesteps=24, **kwargs)


class Tooltip:
    """Plain hover tooltip, used to show the full path behind a folder name."""

    def __init__(self, widget: tk.Misc):
        self._widget = widget
        self._window: tk.Toplevel | None = None
        self._text = ""
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def set_text(self, text: str) -> None:
        self._text = text
        if self._window is not None:
            self._hide()

    def _show(self, _event=None) -> None:
        if not self._text or self._window is not None:
            return
        self._window = tk.Toplevel(self._widget)
        self._window.wm_overrideredirect(True)
        self._window.wm_geometry(
            f"+{self._widget.winfo_rootx() + 12}+{self._widget.winfo_rooty() + 30}"
        )
        tk.Label(
            self._window,
            text=self._text,
            justify="left",
            background="#ffffe0",
            foreground="#1d1d1f",
            relief="solid",
            borderwidth=1,
            padx=6,
            pady=3,
        ).pack()

    def _hide(self, _event=None) -> None:
        if self._window is not None:
            self._window.destroy()
            self._window = None


class AccentButton(tk.Canvas):
    """A filled accent button; Tk's native button can't be recoloured on macOS."""

    def __init__(self, parent, text: str, command, palette: Palette,
                 width: int = 152, height: int = 36):
        super().__init__(
            parent, width=width, height=height, highlightthickness=0,
            borderwidth=0, background=window_background(parent),
        )
        self._palette = palette
        self._command = command
        self._enabled = True
        self._hovering = False
        self._pressed = False
        self._shape = _round_rect(
            self, 1, 1, width - 1, height - 1, 9, fill=palette.accent, outline=""
        )
        self._label = self.create_text(
            width / 2, height / 2 + 1, text=text,
            fill=palette.accent_text, font=("Helvetica", 14),
        )
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)

    def set_text(self, text: str) -> None:
        self.itemconfigure(self._label, text=text)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        self._pressed = False
        self._repaint()

    def _repaint(self) -> None:
        if not self._enabled:
            fill = self._palette.accent_disabled
        elif self._pressed:
            fill = self._palette.accent_pressed
        elif self._hovering:
            fill = self._palette.accent_hover
        else:
            fill = self._palette.accent
        self.itemconfigure(self._shape, fill=fill)
        self.configure(cursor="" if not self._enabled else "pointinghand")

    def _on_enter(self, _event):
        self._hovering = True
        self._repaint()

    def _on_leave(self, _event):
        self._hovering = False
        self._repaint()

    def _on_press(self, _event):
        if self._enabled:
            self._pressed = True
            self._repaint()

    def _on_release(self, event):
        was_pressed = self._pressed
        self._pressed = False
        self._repaint()
        if not (self._enabled and was_pressed):
            return
        if 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self._command()


def draw_drive_icon(canvas: tk.Canvas, palette: Palette,
                    cx: float, cy: float) -> None:
    """External-drive glyph for the source panel."""
    w, h = 74, 100
    x1, y1 = cx - w / 2, cy - h / 2
    x2, y2 = cx + w / 2, cy + h / 2
    _round_rect(canvas, x1, y1, x2, y2, 7,
                fill=palette.drive_body, outline=palette.drive_edge, width=1)
    # USB plug glyph.
    canvas.create_rectangle(cx - 6, y1 + 22, cx + 6, y1 + 56,
                            fill=palette.drive_glyph, outline="")
    canvas.create_rectangle(cx - 2, y1 + 14, cx + 2, y1 + 22,
                            fill=palette.drive_glyph, outline="")
    # Base plate.
    _round_rect(canvas, x1 + 6, y2 - 18, x2 - 6, y2 - 7, 4,
                fill="#f7f2e6", outline=palette.drive_edge, width=1)


def draw_folder_icon(canvas: tk.Canvas, palette: Palette,
                     cx: float, cy: float) -> None:
    """Folder glyph for the destination panel."""
    w, h = 96, 74
    x1, y1 = cx - w / 2, cy - h / 2
    x2, y2 = cx + w / 2, cy + h / 2
    # Back sheet with the tab.
    canvas.create_polygon(
        [x1, y1 + 12, x1 + 6, y1, x1 + 40, y1, x1 + 48, y1 + 12, x2, y1 + 12, x2, y2, x1, y2],
        fill=palette.folder_back, outline=palette.folder_edge, width=1,
    )
    # Front flap.
    _round_rect(canvas, x1, y1 + 20, x2, y2, 6,
                fill=palette.folder_front, outline=palette.folder_edge, width=1)


class FolderPanel(ttk.Frame):
    """Heading, icon tile, selected-folder field and Select... button."""

    TILE = 152

    def __init__(self, parent, heading: str, placeholder: str, icon: str,
                 palette: Palette, dialog_title: str):
        super().__init__(parent)
        self._palette = palette
        self._placeholder = placeholder
        self._dialog_title = dialog_title
        self.path: Path | None = None
        self._on_change = None

        ttk.Label(self, text=heading, style="Heading.TLabel").pack(pady=(0, 12))

        tile = tk.Canvas(
            self, width=self.TILE, height=self.TILE, highlightthickness=0,
            borderwidth=0, background=window_background(self), cursor="pointinghand",
        )
        tile.pack()
        _round_rect(tile, 2, 2, self.TILE - 2, self.TILE - 2, 12,
                    fill=palette.tile, outline=palette.tile_border, width=1)
        centre = self.TILE / 2
        if icon == "drive":
            draw_drive_icon(tile, palette, centre, centre)
        else:
            draw_folder_icon(tile, palette, centre, centre)
        tile.bind("<Button-1>", lambda _e: self.choose())
        self._tile = tile

        self._var = tk.StringVar(value=placeholder)
        self._entry = ttk.Entry(
            self, textvariable=self._var, justify="center",
            state="readonly", style="Placeholder.TEntry", width=22,
        )
        self._entry.pack(pady=(14, 8), fill="x")
        self._tooltip = Tooltip(self._entry)

        self._button = ttk.Button(self, text="Select...", command=self.choose)
        self._button.pack()

    def on_change(self, callback) -> None:
        self._on_change = callback

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._button.configure(state=state)
        self._tile.configure(cursor="pointinghand" if enabled else "")
        if enabled:
            self._tile.bind("<Button-1>", lambda _e: self.choose())
        else:
            self._tile.unbind("<Button-1>")

    def choose(self) -> None:
        initial = str(self.path) if self.path else None
        selected = filedialog.askdirectory(
            title=self._dialog_title, initialdir=initial, mustexist=True
        )
        if not selected:
            return
        self.set_path(Path(selected))

    def set_path(self, path: Path) -> None:
        self.path = path
        self._var.set(path.name or str(path))
        self._entry.configure(style="Path.TEntry")
        self._tooltip.set_text(str(path))
        if self._on_change is not None:
            self._on_change()


class DateTreeApp:
    def __init__(self, root: tk.Tk, settings_path: Path | None = None):
        self.root = root
        self.palette = detect_palette(root)
        self._queue: queue.Queue[dict] = queue.Queue()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._settings_path = settings_path or settings_store.default_settings_path()
        self._restoring = False

        root.title(APP_NAME)
        root.minsize(568, 508)
        root.geometry("600x532")

        self._configure_styles()
        self._build_layout()
        self._restore_folders()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Heading.TLabel", font=("Helvetica", 16),
                        foreground=self.palette.text)
        style.configure("Status.TLabel", font=("Helvetica", 11),
                        foreground=self.palette.muted)
        for name, colour in (("Path.TEntry", self.palette.text),
                             ("Placeholder.TEntry", self.palette.muted)):
            style.configure(name, foreground=colour)
            style.map(name, foreground=[("readonly", colour),
                                        ("disabled", self.palette.muted)])

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=(26, 22, 26, 18))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(2, weight=1)
        outer.rowconfigure(0, weight=1)

        self.source_panel = FolderPanel(
            outer, "Copy From:", "NIKON Z 6", "drive", self.palette,
            "Choose the folder to copy NEF files from",
        )
        self.source_panel.grid(row=0, column=0, sticky="n", padx=(0, 18))

        ttk.Separator(outer, orient="vertical").grid(
            row=0, column=1, sticky="ns", pady=4
        )

        self.dest_panel = FolderPanel(
            outer, "Organize Into:", "Pictures", "folder", self.palette,
            "Choose the folder to organize NEF files into",
        )
        self.dest_panel.grid(row=0, column=2, sticky="n", padx=(18, 0))

        bottom = ttk.Frame(outer)
        bottom.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(26, 0))
        bottom.columnconfigure(0, weight=1)

        self.progress = ttk.Progressbar(bottom, orient="horizontal", mode="determinate")
        self.progress.grid(row=0, column=0, sticky="ew", padx=(0, 18))

        self.organize_button = AccentButton(
            bottom, "Organize", self._on_organize, self.palette
        )
        self.organize_button.grid(row=0, column=1)
        self.organize_button.set_enabled(False)

        self.status = ttk.Label(
            outer, text="Choose a source and a destination folder to begin.",
            style="Status.TLabel", anchor="w",
        )
        self.status.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(14, 0))

        self.source_panel.on_change(self._on_folder_chosen)
        self.dest_panel.on_change(self._on_folder_chosen)

    @property
    def _running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def _restore_folders(self) -> None:
        """Re-select the folders used last time, if they are still there."""
        saved = settings_store.load(self._settings_path)
        self._restoring = True
        unavailable = []
        for panel, path, label in (
            (self.source_panel, saved.source, "source"),
            (self.dest_panel, saved.destination, "destination"),
        ):
            if path is None:
                continue
            if path.is_dir():
                panel.set_path(path)
            else:
                # An ejected card or a renamed folder: keep the placeholder.
                unavailable.append(label)
        self._restoring = False
        self._refresh_ready_state()
        if unavailable:
            self.status.configure(
                text=f"Last used {' and '.join(unavailable)} folder"
                     f"{'s are' if len(unavailable) > 1 else ' is'} unavailable."
            )

    def _on_folder_chosen(self) -> None:
        if not self._restoring:
            settings_store.save(
                settings_store.Settings(
                    source=self.source_panel.path,
                    destination=self.dest_panel.path,
                ),
                self._settings_path,
            )
        self._refresh_ready_state()

    def _refresh_ready_state(self) -> None:
        if self._running:
            return
        ready = self.source_panel.path is not None and self.dest_panel.path is not None
        self.organize_button.set_enabled(ready)
        if ready:
            self.status.configure(text="Ready.")

    def _on_organize(self) -> None:
        if self._running:
            self._cancel.set()
            self.organize_button.set_enabled(False)
            self.status.configure(text="Cancelling...")
            return

        source = self.source_panel.path
        dest = self.dest_panel.path
        if source is None or dest is None:
            return

        self._cancel.clear()
        self.progress.configure(mode="indeterminate", maximum=100, value=0)
        self.progress.start(12)
        self.status.configure(text="Scanning for NEF files...")
        self.organize_button.set_text("Cancel")
        self.source_panel.set_enabled(False)
        self.dest_panel.set_enabled(False)

        self._worker = threading.Thread(
            target=self._run_organize, args=(source, dest), daemon=True
        )
        self._worker.start()
        self.root.after(POLL_MS, self._drain_queue)

    def _run_organize(self, source: Path, dest: Path) -> None:
        try:
            summary = organize(
                source,
                dest,
                extensions=DEFAULT_EXTENSIONS,
                on_scanned=lambda total: self._queue.put(
                    {"kind": "scanned", "total": total}
                ),
                on_progress=lambda done, total, path: self._queue.put(
                    {"kind": "progress", "done": done, "total": total,
                     "name": path.name}
                ),
                is_cancelled=self._cancel.is_set,
            )
        except OrganizeError as exc:
            self._queue.put({"kind": "error", "message": str(exc)})
        except Exception as exc:  # unexpected: surface it rather than dying silently
            self._queue.put({"kind": "error", "message": f"{type(exc).__name__}: {exc}"})
        else:
            self._queue.put({"kind": "done", "summary": summary})

    def _drain_queue(self) -> None:
        finished = False
        while True:
            try:
                event = self._queue.get_nowait()
            except queue.Empty:
                break
            kind = event["kind"]
            if kind == "scanned":
                self.progress.stop()
                total = event["total"]
                self.progress.configure(mode="determinate", maximum=max(total, 1), value=0)
                self.status.configure(
                    text=f"Found {total} NEF file{'s' if total != 1 else ''}."
                )
            elif kind == "progress":
                self.progress.configure(value=event["done"] - 1)
                self.status.configure(
                    text=f"[{event['done']}/{event['total']}] {event['name']}"
                )
            elif kind == "error":
                self._finish()
                self.status.configure(text="Failed.")
                messagebox.showerror(APP_NAME, event["message"], parent=self.root)
                finished = True
            elif kind == "done":
                self._finish()
                self._report(event["summary"])
                finished = True
        if not finished:
            # Keep polling until a "done"/"error" event arrives, which is also
            # how a worker that exits unexpectedly still gets noticed.
            self.root.after(POLL_MS, self._drain_queue)

    def _finish(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.organize_button.set_text("Organize")
        self.source_panel.set_enabled(True)
        self.dest_panel.set_enabled(True)
        self._worker = None
        self._refresh_ready_state()

    def _report(self, summary: Summary) -> None:
        self.progress.configure(value=self.progress.cget("maximum"))
        parts = [f"Copied {summary.copied} ({human_bytes(summary.bytes_copied)})"]
        if summary.skipped:
            parts.append(f"skipped {summary.skipped} already present")
        if summary.failed:
            parts.append(f"{summary.failed} failed")
        fallbacks = sum(
            1 for r in summary.results if r.date_source == DATE_SOURCE_MTIME
        )
        if fallbacks:
            parts.append(f"{fallbacks} used the file date (no EXIF)")
        if summary.cancelled:
            parts.append("cancelled")
        self.status.configure(text=", ".join(parts) + ".")

        failures = [r for r in summary.results if r.status == STATUS_FAILED]
        if failures:
            detail = "\n".join(f"{r.source.name}: {r.error}" for r in failures[:12])
            if len(failures) > 12:
                detail += f"\n...and {len(failures) - 12} more."
            messagebox.showwarning(
                APP_NAME, f"{len(failures)} file(s) could not be copied:\n\n{detail}",
                parent=self.root,
            )

    def _on_close(self) -> None:
        if self._running:
            if not messagebox.askokcancel(
                APP_NAME, "A copy is in progress. Stop it and quit?", parent=self.root
            ):
                return
            self._cancel.set()
        self.root.destroy()


def activate_window(root: tk.Tk) -> None:
    """Bring the window to the front and force a first paint.

    Launched from a terminal the process gets activated for free. Launched from
    a context that isn't a foreground GUI app -- an Automator "Run Shell Script"
    action, launchd, cron -- nothing activates it, and an unactivated Aqua
    process never gets its draw pass, so the window appears blank at the right
    size. Asking for focus explicitly is what triggers that first paint.
    """
    root.update_idletasks()
    root.lift()
    try:
        root.attributes("-topmost", True)
        root.after(200, lambda: root.attributes("-topmost", False))
    except tk.TclError:
        pass  # not fatal: worst case the window opens behind another one
    root.focus_force()
    root.update()


def main() -> None:
    root = tk.Tk()
    DateTreeApp(root)
    activate_window(root)
    root.mainloop()
