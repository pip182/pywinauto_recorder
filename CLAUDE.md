# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Pywinauto recorder records Windows UI actions with UI Automation (pywinauto, `uia` backend) and replays them. This fork
saves each recording as a JSON file (actions + element properties + a replay script) meant to be read by an AI agent
that writes the automation script. Windows only (except `preview_panel.py`).

## Commands

Use the project venv: `.venv\Scripts\python.exe` (Python 3.10, PyQt6 6.12, pywinauto 0.6.9; versions pinned in
`requirements.txt`).

- Run the recorder (control panel): `.venv\Scripts\python.exe pywinauto_recorder.py`
- Replay a recording or script: `.venv\Scripts\python.exe pywinauto_recorder.py "<file.json|file.py>"`
- Unit tests (no GUI): `.venv\Scripts\python.exe -m pytest -q tests\tests.py`
- Single test: `.venv\Scripts\python.exe -m pytest -q tests\tests.py::test_get_entry_list`
- Lint as CI does: `flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics`
- Build the self-contained `dist\pywinauto_recorder.exe` (PyInstaller, one file, no console): `build_exe.bat`, or
  `.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean pywinauto_recorder.spec`. The exe has no stdout: its
  output goes to `~/Pywinauto recorder/pywinauto_recorder.log`. Test it by replaying a script through it with
  `QT_QPA_PLATFORM=offscreen` (a replay runs any `.py` inside the exe).
- Preview the panel on Linux/macOS with a fake recorder: `python3 preview_panel.py`

`tests_Notepad.py`, `tests_Paint.py` and `tests_Calculator.py` start real applications and move the real mouse and
type on the keyboard. Never run them (or `pytest tests` as a whole) while the user is using the machine; ask first.
Likewise, don't drive the real mouse/keyboard to test the recorder. Test the pipeline with synthetic events and the Qt
windows off-screen (`QT_QPA_PLATFORM=offscreen`, or `WA_DontShowOnScreen` + `grab()` to get rendered fonts).

Recordings and `config.ini` (window filtering) live in `~/Pywinauto recorder/`. They are the user's data: copy a
recording to a scratch folder before editing it in a test.

## Architecture

Entry point `pywinauto_recorder.py` creates a `Recorder` and runs the PyQt6 `ControlPanel`, or replays a file.

**UIPath**: elements are addressed by `Name||ControlType` entries joined by `->` from the top-level window
(`core.path_separator`, `core.type_separator`). A last entry may end with `#[row,col]` (position among elements with
the same path) or `#[reference path,col]` (the row of a unique element; only the player handles it), and `%(dx,dy)` for a
click offset. `core.find_elements` resolves a path; it walks the path level by level (`find_children_along_path`) and
enumerates windows with `EnumWindows` because full UIA descendant searches are very slow on some apps. pywinauto's
`title=` matches `rich_text` (an edit's content), not the UIA Name, so names are filtered with `core.filter_by_name`.

**Recorder** (`recorder.py`, a `Thread`) — several concurrent parts:
- The run loop identifies the element under the cursor every ~100 ms, tries the strategies unique path → array_2D,
  fills `Highlights` and, while recording, appends `ElementEvent`s to `event_list`. Smart mode (array_1D) was removed:
  for an array_2D element, the details thread writes `row_label` (`_find_row_label`) to the JSON instead.
- Global hooks from the `keyboard` and `mouse` libraries append raw events to `event_list` and handle the shortcuts
  (CTRL+ALT+R record, CTRL+ALT+N note, CTRL+SHIFT+D info, CTRL+SHIFT+F copy find code). Clicks on the
  recorder's own windows are ignored (`_is_own_window_under_cursor`).
- Worker threads: `_click_queue` identifies the element at a click position when the loop hasn't yet (replaces a
  placeholder `ElementEvent`), `_details_queue` reads the slow element properties written to the JSON.
- `stop_recording` turns the raw events into actions: `_clean_events` → `_process_events` (keys → `SendKeysEvent`,
  wheel, click / drag and drop by the Windows drag threshold, menu clicks → `MenuEvent`) → `_write_in_file`.

**Recording JSON**: `_get_action` converts processed events to action dicts; `_get_event` is the reverse. The replay
script is always generated from the action dicts (`get_script`, `update_recording`), so a recording edited in the step
editor and a fresh one produce the same script. Notes (`NoteEvent`, `note` actions, a `note` on an action, top-level
`notes`) become `#` comments. `_JSON_ABOUT` documents the format inside every file; keep it in sync with the format.
`player.playback` runs the `pywinauto_recorder_script` of a JSON file, or a `.py` file.

**Player** (`player.py`): the replay API used by the scripts (`UIPath` context manager, `click`, `send_keys`,
`menu_click`, `find`, ...). `send_keys` uses pywinauto syntax; the recorder escapes `^ % ~ { }` and the player escapes
`( ) +`. Don't set the global `core` native window handle from the recorder (it restricts what replays can find);
pass `window_handle` explicitly.

**UI** (PyQt6): `control_panel.py` has the floating panel (polls the recorder state every 200 ms; the Replay button
is the Note button while recording), click-through outline overlays and the element info box. The info box is fed by
`element_observer.py`, which inspects elements in a separate `multiprocessing` process. `step_editor.py` has the step
editor (reorder / edit / delete steps, add notes, save) and the note dialog.

## Conventions

- Indent with 4 spaces (no tabs, except inside strings that are data, e.g. the tutorial texts); files use LF line
  endings. Docstrings use `:param x:` / `:return:`.
- Prefer the Edit tool for changes: rewriting files through shell heredocs has mangled `\` line continuations and
  `\n` escapes and converted files to CRLF.
- UIA calls into some apps (e.g. BricsCAD, which owns hundreds of hidden windows) are slow or hang; keep UIA work out
  of hooks and the Qt thread.
