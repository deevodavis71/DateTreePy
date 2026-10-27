# DateTree — working notes for Claude

macOS GUI app that copies Nikon `.NEF` files from a card/folder into
`<destination>/YYYY-MM-DD/<file>`, dated by EXIF capture time. Python 3 +
tkinter, **standard library only — no third-party packages**. Keep it that way
unless the user asks otherwise.

Built from scratch in July 2026. `README.md` is the user-facing documentation;
this file is the context that isn't obvious from the code.

**Provenance — matters, don't blur it.** This is a clean-room reimplementation
of *DateTree* by Colin Henein (https://www.orange-carb.org/DateTree/, v1.3,
©2020), which Steve has used for years and which is expected to stop working on
future macOS releases. The name, layout and button wording come from that app;
**everything here was written from screenshots only**. Never copy, decompile or
inspect the original's code or assets, and don't present this as affiliated with
or endorsed by its author. The credit section at the top of `README.md` says all
this publicly — keep it there. The UI was restyled in October 2026 at Steve's
request (cards, system font, pill button). It keeps the original's two-panel
left-to-right flow and its wording, so the credit still stands.

## Commands

```sh
./start.sh                          # run the app (terminal)
open DateTree.app                   # run the app (LaunchServices — see gotchas)
./start.sh path/to/FILE.NEF         # print the date it would file a file under
python3 -m unittest discover -s tests -t .    # 68 tests, all passing
./tools/make_app.sh                 # rebuild DateTree.app
./tools/build_release.sh            # standalone app + zip in dist/ (PyInstaller)
python3 tools/make_icon.py          # regenerate the icon only
```

## Layout

| Path | Purpose |
| --- | --- |
| `datetree/exif.py` | NEF (TIFF) capture-date reader, hand-rolled with `struct` |
| `datetree/organizer.py` | File discovery + copy engine, GUI-agnostic |
| `datetree/gui.py` | Tkinter UI |
| `datetree/settings.py` | Remembers last-used folders and the eject-reminder option |
| `datetree/__main__.py` | Entry point; also the date-inspection CLI |
| `tools/` | `make_app.sh`, `launcher.sh.in`, `make_icon.py`, `build_release.sh`, `screenshots.py` |
| `.github/workflows/release.yml` | Pushing a `v*` tag builds and publishes a release |
| `assets/DateTree.icns` | Tracked icon asset; the bundle gets a copy |
| `tests/nef_fixture.py` | Builds synthetic NEFs so tests need no real raw files |

`DateTree.app` is generated and **git-ignored** — never hand-edit it; edit
`tools/launcher.sh.in` and re-run `./tools/make_app.sh`.

The engine takes callbacks (`on_scanned`, `on_progress`, `is_cancelled`) and
knows nothing about Tk; the GUI runs it on a worker thread and marshals events
back through a `queue.Queue` polled by `root.after`. Preserve that split.

## Decisions the user made (don't silently revisit)

- **Date source:** EXIF `DateTimeOriginal` → `DateTimeDigitized` → TIFF
  `DateTime` → filesystem mtime. The status line reports how many files needed
  the mtime fallback.
- **Duplicates:** if the destination name exists, skip it. Not overwrite, not
  rename-with-suffix. Re-running over a card is meant to be cheap and safe.
- **Toolkit:** tkinter via `brew install python-tk`. PySide6 was offered and
  declined — do not add GUI dependencies.
- **Releases:** a self-contained universal2 `.app` frozen with PyInstaller,
  ad-hoc signed (no Developer ID, so users click *Open Anyway* once),
  published by pushing a `v*` tag that matches `__version__`. PyInstaller is
  the one sanctioned non-stdlib package, and only as a **build tool**, pinned
  in `tools/release-requirements.txt`. The app's runtime stays stdlib-only.
- **File types:** `.NEF` only. Sidecars (`.XMP`) and RAW+JPEG partners were
  offered and declined.

Deliberate behaviours worth preserving: atomic copy via temp file + verified
size + `os.replace`; `shutil.copystat` to keep mtimes; `._*` AppleDouble stubs
skipped; a destination nested inside the source is pruned from the scan;
source == destination rejected; nothing is ever moved or deleted.

## Environment

- `python3` is Homebrew **3.14** at `/opt/homebrew/bin/python3`, with
  `python-tk@3.14` installed. This is the interpreter to use.
- `python@3.13` is also installed **without Tk** — handy for testing Tk-less
  code paths, and a trap if something picks it up accidentally.
- `/usr/bin/python3` is 3.9 with Tk 8.5; works but looks dated.
- Git repo on `main`, remote `origin` = github.com/deevodavis71/DateTreePy.
  History starts at the initial commit; the app was built before the repo
  existed, so early stages aren't in history — that initial commit message
  records the sequence. Commit as work progresses now.

## Gotchas discovered the hard way

Each of these cost real debugging time. They are all verified, not theory.

1. **Automator "Run Shell Script" produces a blank window.** That action runs
   inside an XPC service (`XPC_SERVICE_NAME=com.apple.automator.xpc.runner`,
   `SECURITYSESSIONID` unset), so the process is never activated, and an
   unactivated Aqua process never gets its first draw pass — correct geometry,
   nothing painted. Diagnosed by diffing Tk state between an iTerm2 run and a
   real Automator run: the *only* meaningful difference was `tk_focus` (`.` vs
   empty). Mitigated by `activate_window()` in `gui.py`; properly fixed by
   launching via LaunchServices (`open -a .../DateTree.app`).
2. **macOS attributes a process to whichever bundle its executable sits in.**
   Homebrew's `python3` lives inside `Python.app`, so the app showed up in the
   Dock as "Python" with Python's icon, ignoring our `Info.plist`. Fix:
   `make_app.sh` symlinks the GUI Python binary to
   `DateTree.app/Contents/MacOS/python-gui` and the launcher execs it *through
   that symlink*. Framework Python still resolves its prefix correctly.
   The symlink is version-pinned; see README Troubleshooting.
3. **Creating and destroying several `tk.Tk()` roots in one process crashes Tk
   on macOS** (SIGTRAP, exit -5). `tests/test_gui.py` therefore shares one
   class-level root and gives each test a `Toplevel`. Don't "simplify" that.
4. **ttk widgets have no `-background` option.** `widget.cget("background")` on
   a `ttk.Frame` raises `TclError`; canvas backgrounds come from
   `window_background()`, which reads the theme via `ttk.Style().lookup`.
5. **macOS native buttons can't be recoloured**, hence the cards, the pill
   Organize button and the progress bar are all custom `tk.Canvas` widgets.
   Draw rounded shapes with `rounded_rect()`, which uses ovals and is
   anti-aliased. Smoothed polygons give visibly faceted corners, which is what
   the first UI had.
6. **`make_app.sh` must verify `import tkinter` before linking an
   interpreter.** Linking a Tk-less Python built an app that reported success
   but couldn't start, and the launcher's `start.sh` fallback did *not* rescue
   it because the symlink existed. There's now an up-front guard.

7. **Tk objects must not be garbage-collected on the worker thread.** Old
   `DateTreeApp`s from earlier GUI tests sit in reference cycles; if the cyclic
   GC reclaims them on the copy worker, a Tk variable's `__del__` calls Tcl off
   the main thread and the run stalls. The suite then failed every time.
   `GuiTests.setUp` runs `gc.collect()` on the main thread first. The real app
   has one long-lived `DateTreeApp`, so it isn't affected.

## Verification status

- 68 tests pass (`unittest`, no pytest). Several of them drive real Tk widgets and
  copy real files through the worker thread.
- The EXIF reader is confirmed working against genuine Nikon NEF files: Steve
  tested it on real photographs on 2026-07-26. Automated coverage still uses
  the synthetic TIFFs in `tests/nef_fixture.py`, since real raws are far too
  large to commit. To re-check after changing `exif.py`, run
  `./start.sh /path/to/real.NEF` — `(exif)` means the capture date was read,
  `(mtime)` means it fell back and the reader needs a look.
- Release build: `tools/build_release.sh` verified locally on 2026-10-27
  (arm64, Homebrew 3.14). The app launched via `open` and loaded only its
  bundled Python/Tcl/Tk, with no Homebrew paths. The universal2 CI path
  (python.org pkg) had not run yet at that point.
- **Screen capture works** as of 2026-10-27; it was blocked by macOS TCC
  before then. `python3 tools/screenshots.py OUT_DIR [aqua|darkaqua]` captures
  the window in four states, then you read the PNGs with the Read tool. The
  current card UI was checked that way in light and dark mode, including hover
  and the eject popup. A native `messagebox` runs a modal loop in which Tk
  `after` callbacks don't fire, so capture a dialog from a `threading.Timer`.

## Conventions

Comments explain *why*, sparingly. Tests are `unittest`, one behaviour per
test, named as a sentence. Errors surface to the user in the status line, with
a dialog only for hard failures. Anything that touches the user's photo library
gets a test before it ships.
