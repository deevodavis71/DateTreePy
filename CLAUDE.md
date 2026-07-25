# DateTree — working notes for Claude

macOS GUI app that copies Nikon `.NEF` files from a card/folder into
`<destination>/YYYY-MM-DD/<file>`, dated by EXIF capture time. Python 3 +
tkinter, **standard library only — no third-party packages**. Keep it that way
unless the user asks otherwise.

Built from scratch in July 2026 as a Python rewrite of an existing macOS app,
specified from a screenshot of that app's window. `README.md` is the
user-facing documentation; this file is the context that isn't obvious from the
code.

## Commands

```sh
./start.sh                          # run the app (terminal)
open DateTree.app                   # run the app (LaunchServices — see gotchas)
./start.sh path/to/FILE.NEF         # print the date it would file a file under
python3 -m unittest discover -s tests -t .    # 55 tests, all passing
./tools/make_app.sh                 # rebuild DateTree.app
python3 tools/make_icon.py          # regenerate the icon only
```

## Layout

| Path | Purpose |
| --- | --- |
| `datetree/exif.py` | NEF (TIFF) capture-date reader, hand-rolled with `struct` |
| `datetree/organizer.py` | File discovery + copy engine, GUI-agnostic |
| `datetree/gui.py` | Tkinter UI |
| `datetree/settings.py` | Remembers last-used folders |
| `datetree/__main__.py` | Entry point; also the date-inspection CLI |
| `tools/` | `make_app.sh`, `launcher.sh.in`, `make_icon.py` |
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
- Git repo on `main`, no remote. History starts at the initial commit; the app
  was built before the repo existed, so early stages aren't in history — that
  initial commit message records the sequence. Commit as work progresses now.

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
5. **macOS native buttons can't be recoloured**, hence the accent Organize
   button is a custom `tk.Canvas` widget with its own hover/press/disabled
   states.
6. **`make_app.sh` must verify `import tkinter` before linking an
   interpreter.** Linking a Tk-less Python built an app that reported success
   but couldn't start, and the launcher's `start.sh` fallback did *not* rescue
   it because the symlink existed. There's now an up-front guard.

## Verification status

- 55 tests pass (`unittest`, no pytest). 7 of them drive real Tk widgets and
  copy real files through the worker thread.
- **The EXIF reader has never been run against a genuine Nikon NEF** — there
  are none on this machine. It is verified only against the synthetic TIFFs in
  `tests/nef_fixture.py`. Ask the user to run
  `./start.sh /path/to/real.NEF`: `(exif)` means it worked, `(mtime)` means it
  fell back and the reader needs a look.
- **Screen capture is blocked** in this environment (macOS TCC — `screencapture`
  fails with "could not create image from display"), so no GUI change has ever
  been visually confirmed by Claude. Verify layout/painting by reasoning about
  widget state, or ask the user to look. Reading generated PNGs with the Read
  tool *does* work, which is how the app icon was checked.

## Conventions

Comments explain *why*, sparingly. Tests are `unittest`, one behaviour per
test, named as a sentence. Errors surface to the user in the status line, with
a dialog only for hard failures. Anything that touches the user's photo library
gets a test before it ships.
