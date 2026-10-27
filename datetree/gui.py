"""Tkinter GUI for DateTree."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

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
WINDOW_WIDTH = 640


@dataclass(frozen=True)
class Palette:
    text: str
    muted: str
    card: str
    card_border: str
    accent: str
    accent_hover: str
    accent_pressed: str
    accent_disabled: str
    accent_text: str
    accent_tint: str
    track: str
    sd_body: str
    sd_label: str
    sd_pins: str
    folder_front: str
    folder_back: str


LIGHT = Palette(
    text="#1d1d1f",
    muted="#6e6e73",
    card="#ffffff",
    card_border="#dcdce1",
    accent="#007aff",
    accent_hover="#1a88ff",
    accent_pressed="#0062cc",
    accent_disabled="#c7c7cc",
    accent_text="#ffffff",
    accent_tint="#e3eeff",
    track="#dcdce1",
    sd_body="#3a3a3c",
    sd_label="#f5c400",
    sd_pins="#d9b54a",
    folder_front="#4aa8f5",
    folder_back="#1a8cf0",
)

DARK = Palette(
    text="#f5f5f7",
    muted="#98989d",
    card="#2c2c2e",
    card_border="#3a3a3c",
    accent="#0a84ff",
    accent_hover="#409cff",
    accent_pressed="#0062cc",
    accent_disabled="#48484a",
    accent_text="#ffffff",
    accent_tint="#1d3550",
    track="#3a3a3c",
    sd_body="#58585c",
    sd_label="#f5c400",
    sd_pins="#c9a227",
    folder_front="#3b9cf0",
    folder_back="#0a74da",
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


def system_font_family(widget: tk.Misc) -> str:
    """The platform UI font (San Francisco on macOS) rather than Helvetica."""
    try:
        return tkfont.nametofont("TkDefaultFont", root=widget).actual("family")
    except (tk.TclError, RuntimeError):
        return "Helvetica"


def human_bytes(count: int) -> str:
    size = float(count)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def volume_name(path: Path) -> str | None:
    """Name of the mounted volume under /Volumes that holds `path`, if any.

    The boot disk also appears in /Volumes, but as a symlink to `/`, so
    resolving the path first keeps internal folders from counting as a card.
    """
    parts = path.resolve().parts
    if len(parts) >= 3 and parts[:2] == ("/", "Volumes"):
        return parts[2]
    return None


def display_path(path: Path) -> str:
    """A folder's location for display, with the home folder shown as ~."""
    home = str(Path.home())
    text = str(path)
    if text == home or text.startswith(home + "/"):
        return "~" + text[len(home):]
    return text


def fit_text(widget: tk.Misc, font, text: str, width: int) -> str:
    """Shorten `text` with a middle ellipsis until it fits in `width` pixels."""
    def measure(s: str) -> int:
        return int(widget.tk.call("font", "measure", font, s))

    if width <= 0 or measure(text) <= width:
        return text
    keep = len(text)
    while keep > 1:
        keep -= 1
        head = (keep + 1) // 2
        candidate = text[:head] + "…" + text[len(text) - (keep - head):]
        if measure(candidate) <= width:
            return candidate
    return "…"


def rounded_rect(canvas: tk.Canvas, x1, y1, x2, y2, radius, fill, tags=()) -> None:
    """Filled rounded rectangle built from ovals and rectangles.

    Tk has no rounded-rectangle primitive, and a smoothed polygon gives visibly
    faceted corners, whereas ovals are drawn anti-aliased.
    """
    r = max(0, min(radius, (x2 - x1) / 2, (y2 - y1) / 2))
    common = {"fill": fill, "outline": "", "tags": tags}
    if r:
        for cx, cy in ((x1, y1), (x2 - 2 * r, y1), (x1, y2 - 2 * r), (x2 - 2 * r, y2 - 2 * r)):
            canvas.create_oval(cx, cy, cx + 2 * r, cy + 2 * r, **common)
    canvas.create_rectangle(x1 + r, y1, x2 - r, y2, **common)
    canvas.create_rectangle(x1, y1 + r, x2, y2 - r, **common)


def bordered_rect(canvas, x1, y1, x2, y2, radius, fill, border, tags=()) -> None:
    """Rounded rectangle with a 1px border: a border-coloured shape, inset fill."""
    rounded_rect(canvas, x1, y1, x2, y2, radius, border, tags)
    rounded_rect(canvas, x1 + 1, y1 + 1, x2 - 1, y2 - 1, radius - 1, fill, tags)


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
            f"+{self._widget.winfo_rootx() + 12}"
            f"+{self._widget.winfo_rooty() + self._widget.winfo_height() + 4}"
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
    """A pill-shaped accent button; Tk's native button can't be recoloured on macOS."""

    def __init__(self, parent, text: str, command, palette: Palette, family: str,
                 width: int = 148, height: int = 38):
        super().__init__(
            parent, width=width, height=height, highlightthickness=0,
            borderwidth=0, background=window_background(parent),
        )
        self._palette = palette
        self._command = command
        self._text = text
        self._font = (family, 14, "bold")
        self._size = (width, height)
        self._enabled = True
        self._hovering = False
        self._pressed = False
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<ButtonPress-1>", self._on_press)
        self.bind("<ButtonRelease-1>", self._on_release)
        self._repaint()

    def set_text(self, text: str) -> None:
        self._text = text
        self._repaint()

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
        width, height = self._size
        self.delete("all")
        rounded_rect(self, 0, 0, width, height, height / 2, fill)
        self.create_text(width / 2, height / 2, text=self._text,
                         fill=self._palette.accent_text, font=self._font)
        self.configure(cursor="pointinghand" if self._enabled else "")

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


class SlimProgress(tk.Canvas):
    """A thin rounded progress track, with a sliding segment while scanning."""

    HEIGHT = 6
    FRAME_MS = 16

    def __init__(self, parent, palette: Palette):
        super().__init__(
            parent, height=self.HEIGHT, highlightthickness=0, borderwidth=0,
            background=window_background(parent),
        )
        self._palette = palette
        self.fraction = 0.0
        self._phase: float | None = None  # set while indeterminate
        self._job: str | None = None
        self.bind("<Configure>", lambda _e: self._repaint())
        self.bind("<Destroy>", lambda _e: self.stop())

    def set_fraction(self, fraction: float) -> None:
        self.stop()
        self.fraction = min(max(fraction, 0.0), 1.0)
        self._repaint()

    def start(self) -> None:
        """Animate an indeterminate segment until stopped."""
        self.stop()
        self._phase = 0.0
        self._tick()

    def stop(self) -> None:
        self._phase = None
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None
        self._repaint()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.012) % 1.0
        self._repaint()
        self._job = self.after(self.FRAME_MS, self._tick)

    def _repaint(self) -> None:
        try:
            self.delete("all")
        except tk.TclError:
            return  # being destroyed
        width, h = self.winfo_width(), self.HEIGHT
        if width <= 1:
            return
        rounded_rect(self, 0, 0, width, h, h / 2, self._palette.track)
        if self._phase is not None:
            segment = width * 0.28
            start = (width + segment) * self._phase - segment
            x1, x2 = max(start, 0), min(start + segment, width)
            if x2 - x1 >= h:
                rounded_rect(self, x1, 0, x2, h, h / 2, self._palette.accent)
        elif self.fraction > 0:
            rounded_rect(self, 0, 0, max(width * self.fraction, h), h, h / 2,
                         self._palette.accent)


class FlowArrow(tk.Canvas):
    """Round badge with an arrow between the cards: files flow left to right."""

    SIZE = 36

    def __init__(self, parent, palette: Palette):
        super().__init__(
            parent, width=self.SIZE, height=self.SIZE, highlightthickness=0,
            borderwidth=0, background=window_background(parent),
        )
        self._palette = palette
        self.set_active(False)

    def set_active(self, active: bool) -> None:
        p, s = self._palette, self.SIZE
        self.delete("all")
        if active:
            self.create_oval(0, 0, s, s, fill=p.accent, outline="")
        else:
            self.create_oval(0, 0, s, s, fill=p.card_border, outline="")
            self.create_oval(1, 1, s - 1, s - 1, fill=p.card, outline="")
        colour = p.accent_text if active else p.muted
        mid = s / 2
        self.create_line(mid - 7, mid, mid + 7, mid, fill=colour, width=2,
                         capstyle="round")
        self.create_line(mid + 1, mid - 6, mid + 7, mid, mid + 1, mid + 6,
                         fill=colour, width=2, capstyle="round", joinstyle="round")


def draw_card_icon(canvas: tk.Canvas, palette: Palette, cx: float, cy: float) -> None:
    """Memory-card glyph for the source card: clipped corner, pins, label."""
    w, h, clip = 58, 74, 16
    x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    r = 6
    canvas.create_polygon(
        x1 + clip, y1, x2 - r, y1, x2, y1 + r, x2, y2 - r, x2 - r, y2,
        x1 + r, y2, x1, y2 - r, x1, y1 + clip,
        fill=palette.sd_body, outline="", joinstyle="round",
    )
    for corner in ((x2 - 2 * r, y1), (x2 - 2 * r, y2 - 2 * r), (x1, y2 - 2 * r)):
        canvas.create_oval(corner[0], corner[1], corner[0] + 2 * r, corner[1] + 2 * r,
                           fill=palette.sd_body, outline="")
    for i in range(5):
        px = x1 + clip + 2 + i * 7.5
        rounded_rect(canvas, px, y1 + 6, px + 4.5, y1 + 20, 2, palette.sd_pins)
    rounded_rect(canvas, x1 + 8, y1 + 34, x2 - 8, y2 - 10, 4, palette.sd_label)


def draw_folder_icon(canvas: tk.Canvas, palette: Palette, cx: float, cy: float) -> None:
    """Folder glyph for the destination card."""
    w, h = 84, 64
    x1, y1, x2, y2 = cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2
    rounded_rect(canvas, x1, y1, x1 + 34, y1 + 20, 6, palette.folder_back)
    rounded_rect(canvas, x1, y1 + 8, x2, y2, 8, palette.folder_back)
    rounded_rect(canvas, x1, y1 + 17, x2, y2, 8, palette.folder_front)


class FolderCard(tk.Canvas):
    """A clickable card: caption, icon, folder name, location and Select... pill."""

    HEIGHT = 262
    RADIUS = 14

    def __init__(self, parent, caption: str, placeholder: str, icon: str,
                 palette: Palette, family: str, dialog_title: str):
        super().__init__(
            parent, height=self.HEIGHT, width=240, highlightthickness=0,
            borderwidth=0, background=window_background(parent),
            cursor="pointinghand",
        )
        self._palette = palette
        self._caption = caption
        self._placeholder = placeholder
        self._icon = icon
        self._dialog_title = dialog_title
        self._fonts = {
            "caption": (family, 11, "bold"),
            "title": (family, 15, "bold"),
            "detail": (family, 11),
            "button": (family, 12),
        }
        self.path: Path | None = None
        self.enabled = True
        self._hovering = False
        self._on_change = None
        self._tooltip = Tooltip(self)

        self.bind("<Configure>", lambda _e: self._repaint())
        self.bind("<Enter>", lambda _e: self._set_hover(True), add="+")
        self.bind("<Leave>", lambda _e: self._set_hover(False), add="+")
        self.bind("<Button-1>", lambda _e: self.choose())

    @property
    def title(self) -> str:
        """The name shown on the card: the folder's name, or the placeholder."""
        if self.path is None:
            return self._placeholder
        return self.path.name or str(self.path)

    def on_change(self, callback) -> None:
        self._on_change = callback

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        self.configure(cursor="pointinghand" if enabled else "")
        self._repaint()

    def choose(self) -> None:
        if not self.enabled:
            return
        initial = str(self.path) if self.path else None
        selected = filedialog.askdirectory(
            title=self._dialog_title, initialdir=initial, mustexist=True
        )
        if not selected:
            return
        self.set_path(Path(selected))

    def set_path(self, path: Path) -> None:
        self.path = path
        self._tooltip.set_text(str(path))
        self._repaint()
        if self._on_change is not None:
            self._on_change()

    def _set_hover(self, hovering: bool) -> None:
        self._hovering = hovering
        self._repaint()

    def _repaint(self) -> None:
        p = self._palette
        width, height = self.winfo_width(), self.HEIGHT
        if width <= 1:
            width = int(self.cget("width"))
        self.delete("all")
        highlight = self._hovering and self.enabled
        bordered_rect(self, 0, 0, width, height, self.RADIUS, p.card,
                      p.accent if highlight else p.card_border)

        cx = width / 2
        self.create_text(cx, 26, text=self._caption.upper(), fill=p.muted,
                         font=self._fonts["caption"])
        if self._icon == "card":
            draw_card_icon(self, p, cx, 96)
        else:
            draw_folder_icon(self, p, cx, 96)

        room = width - 32
        placeholder = self.path is None
        self.create_text(
            cx, 162, fill=p.muted if placeholder else p.text,
            text=fit_text(self, self._fonts["title"], self.title, room),
            font=self._fonts["title"],
        )
        detail = ("Click to choose a folder" if placeholder
                  else display_path(self.path.parent))
        self.create_text(cx, 184, fill=p.muted, font=self._fonts["detail"],
                         text=fit_text(self, self._fonts["detail"], detail, room))

        pill_w, pill_h, pill_y = 96, 28, 214
        fill = p.accent_tint if self.enabled else p.track
        rounded_rect(self, cx - pill_w / 2, pill_y, cx + pill_w / 2, pill_y + pill_h,
                     pill_h / 2, fill)
        self.create_text(cx, pill_y + pill_h / 2, text="Select…",
                         fill=p.accent if self.enabled else p.muted,
                         font=self._fonts["button"])


class DateTreeApp:
    def __init__(self, root: tk.Tk, settings_path: Path | None = None):
        self.root = root
        self.palette = detect_palette(root)
        self.family = system_font_family(root)
        self._queue: queue.Queue[dict] = queue.Queue()
        self._cancel = threading.Event()
        self._worker: threading.Thread | None = None
        self._settings_path = settings_path or settings_store.default_settings_path()
        self._restoring = False
        self._run_source: Path | None = None

        root.title(APP_NAME)
        self._configure_styles()
        self._build_layout()
        # Fit the height to the content, which depends on the system font.
        root.update_idletasks()
        height = root.winfo_reqheight()
        root.minsize(WINDOW_WIDTH - 40, height)
        root.geometry(f"{WINDOW_WIDTH}x{height}")
        self._restore_folders()
        root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.configure("Status.TLabel", font=(self.family, 12),
                        foreground=self.palette.muted)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self.root, padding=(24, 22, 24, 20))
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.columnconfigure(2, weight=1)

        self.source_panel = FolderCard(
            outer, "Copy From", "No card chosen", "card", self.palette,
            self.family, "Choose the folder to copy NEF files from",
        )
        self.source_panel.grid(row=0, column=0, sticky="new")

        self.flow_arrow = FlowArrow(outer, self.palette)
        self.flow_arrow.grid(row=0, column=1, sticky="n", padx=14,
                             pady=(FolderCard.HEIGHT - FlowArrow.SIZE) // 2)

        self.dest_panel = FolderCard(
            outer, "Organize Into", "No folder chosen", "folder", self.palette,
            self.family, "Choose the folder to organize NEF files into",
        )
        self.dest_panel.grid(row=0, column=2, sticky="new")

        self.progress = SlimProgress(outer, self.palette)
        self.progress.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(22, 0))

        self.status = ttk.Label(
            outer, text="Choose a source and a destination folder to begin.",
            style="Status.TLabel", anchor="w",
        )
        self.status.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        footer = ttk.Frame(outer)
        footer.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        footer.columnconfigure(0, weight=1)

        self.eject_reminder = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            footer, text="Remind me to eject the card after copying",
            variable=self.eject_reminder, command=self._save_settings,
        ).grid(row=0, column=0, sticky="w")

        self.organize_button = AccentButton(
            footer, "Organize", self._on_organize, self.palette, self.family
        )
        self.organize_button.grid(row=0, column=1, sticky="e")
        self.organize_button.set_enabled(False)

        self.source_panel.on_change(self._on_folder_chosen)
        self.dest_panel.on_change(self._on_folder_chosen)

    @property
    def _running(self) -> bool:
        return self._worker is not None and self._worker.is_alive()

    def _restore_folders(self) -> None:
        """Re-select the folders used last time, if they are still there."""
        saved = settings_store.load(self._settings_path)
        self.eject_reminder.set(saved.eject_reminder)
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
            self._save_settings()
        self._refresh_ready_state()

    def _save_settings(self) -> None:
        settings_store.save(
            settings_store.Settings(
                source=self.source_panel.path,
                destination=self.dest_panel.path,
                eject_reminder=self.eject_reminder.get(),
            ),
            self._settings_path,
        )

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
        self._run_source = source
        self.progress.start()
        self.flow_arrow.set_active(True)
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
                total = event["total"]
                self.progress.set_fraction(0)
                self.status.configure(
                    text=f"Found {total} NEF file{'s' if total != 1 else ''}."
                )
            elif kind == "progress":
                self.progress.set_fraction((event["done"] - 1) / max(event["total"], 1))
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
        self.flow_arrow.set_active(False)
        self.organize_button.set_text("Organize")
        self.source_panel.set_enabled(True)
        self.dest_panel.set_enabled(True)
        self._worker = None
        self._refresh_ready_state()

    def _report(self, summary: Summary) -> None:
        self.progress.set_fraction(1.0 if summary.results else 0.0)
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
        elif not summary.cancelled:
            self._remind_to_eject()

    def _remind_to_eject(self) -> None:
        """Nudge the user to eject the card, if they asked to be reminded.

        Only a source on a mounted volume has anything to eject; a run from a
        folder on the internal disk stays quiet. Cancelled or partly failed runs
        are skipped too, since the user will likely want to run them again.
        """
        if not self.eject_reminder.get() or self._run_source is None:
            return
        name = volume_name(self._run_source)
        if name is None:
            return
        messagebox.showinfo(
            APP_NAME,
            f"Copying is finished. Please eject \u201c{name}\u201d now.",
            detail="Eject it in Finder (or drag it to the Trash), then remove "
                   "the card.",
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
