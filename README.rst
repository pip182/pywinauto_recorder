|Codacy Badge| |Docs badge| |License| |PyPI version|

.. image:: https://raw.githubusercontent.com/beuaaa/pywinauto_recorder/master/Images/logo.png?sanitize=true
    :align: center
    :width: 200

.. important::

   This is a heavily modified fork of `beuaaa/pywinauto_recorder`_ by David Pratmarty. It differs from the original
   in large ways. It still replays scripts written for the original, but it records differently:

   - Recordings are saved as **JSON files** (actions, element properties and the replay script) instead of Python
     scripts.
   - It has a new **PyQt6 control panel**, element outlines and information box, and a **step editor** to reorder,
     change and delete recorded steps and to add **notes**.
   - It finds elements and records clicks and keys in new ways. Clicks made before the outline appears are still
     recorded, and typed text, Tab and shortcuts are kept.

   The badges and the online documentation below are those of the original project, and don't describe this fork.
   Report problems with this fork at `pip182/pywinauto_recorder`_, not upstream.

.. _beuaaa/pywinauto_recorder: https://github.com/beuaaa/pywinauto_recorder

Description
===========
"Pywinauto recorder" records user interface actions and replays them. It is a unique inspect/record/replay tool in the
open source field because it identifies elements by their path in the user interface rather than by hard-coded
coordinates, thanks to Pywinauto_.

Pywinauto_ is a library that uses accessibility technologies allowing you to automate almost any type of GUI: MFC, VB6,
VCL, simple WinForms controls and most of the old legacy apps, WinForms, WPF, Store apps, Qt, browsers.

This fork (`pip182/pywinauto_recorder`_) saves each recording as a **JSON file** describing every action with the UI
Automation properties of its element, plus the script replaying it. The file is meant to be given to an AI agent
that writes a robust automation script from it.

.. _Pywinauto: https://github.com/pywinauto/pywinauto/
.. _pip182/pywinauto_recorder: https://github.com/pip182/pywinauto_recorder

Installation
============
Windows only. With Python 3.8 or later:

.. code-block:: bat

    python -m venv .venv
    .venv\Scripts\pip install -r requirements.txt

Usage
=====
Start the recorder:

.. code-block:: bat

    .venv\Scripts\python.exe pywinauto_recorder.py

A small floating control panel appears at the top of the screen:

- **● Record** starts / stops recording. The element under the cursor is outlined: green when it is identified
  uniquely, red when several elements have the same path. The status bar confirms each recorded click or key, and
  warns when a click is missed. An element among identical ones (e.g. a grid cell) is recorded by its row and column,
  and the JSON file also gives the label of its row (``row_label``), so that a script can find the row again even if
  rows were added or sorted.
- **▶ Replay** replays the last recording. While recording, it becomes **✎ Note**, to add a note to the recording.
- **ⓘ Info** shows the path and the properties of the element under the cursor.
- **⋯** replays the clipboard or a file, edits recordings, opens the output folder and sets the recording options.

Keyboard shortcuts:

=============  ====================================================
CTRL+ALT+R     Start / stop recording
CTRL+ALT+N     Add a note while recording
CTRL+SHIFT+D   Display / hide element information
CTRL+SHIFT+F   Copy the code finding the element under the cursor
=============  ====================================================

Recordings are saved in ``%USERPROFILE%\Pywinauto recorder`` as ``recorded <date>.json`` and copied to the
clipboard.

Editing a recording
-------------------
When a recording stops, the step editor opens (turn it off with **Edit steps after recording** in the ⋯ menu;
**Edit last recording...** opens it again). In it you can:

- write notes about the whole recording, e.g. what it does and what its inputs are,
- reorder steps (drag them, or Alt+Up / Alt+Down), delete them, and change their UI path or typed keys,
- add a note on a step or between two steps (Ctrl+N), e.g. *Wait until the import finishes*.

Saving (Ctrl+S) writes the code of the steps and the replay script again, with the notes as comments, and copies the
JSON to the clipboard.

Replaying
---------
Click **Replay**, use **Replay file...** in the ⋯ menu, drag and drop a file on ``pywinauto_recorder.exe``, or run:

.. code-block:: bat

    .venv\Scripts\python.exe pywinauto_recorder.py "recorded <date>.json"

A recording (``.json``) or a Python script using ``pywinauto_recorder.player`` can be replayed.

The recording file
==================
Each file starts with an ``about`` section documenting its format. The main keys are:

- ``notes``: the notes of the user about the whole recording,
- ``actions``: the actions in the order they were done (``click``, ``send_keys``, ``mouse_wheel``, ``drag_and_drop``,
  ``menu_click``, ``find`` and ``note``), each with its time, cursor position, ``uipath``, the properties of its
  ``element`` (name, control type, automation id, class name, process, supported UI Automation patterns, value,
  ancestors...), its optional ``note`` and its ``pywinauto_recorder_code``,
- ``pywinauto_recorder_script``: the whole recording as a script, for example:

.. code-block:: python

    from pywinauto_recorder.player import *

    with UIPath(u"Connections||Window"):
        with UIPath(u"||Pane->||Pane"):
            # Office is the production connection
            click(u" Office||Text")

A UI path is a list of ``Name||ControlType`` entries joined by ``->`` from the top-level window. The functions of the
player return Pywinauto_ wrappers, so a script can be enhanced with Pywinauto methods_. The values of password fields
are never written.

.. _methods: https://pywinauto.readthedocs.io/en/latest/controls_overview.html

Documentation
=============
See https://pywinauto-recorder.readthedocs.io for the documentation of the original project. Its player API still
applies, but its descriptions of recording, the panel and the output files don't apply to this fork.

.. |PyPI version| image:: https://img.shields.io/pypi/v/pywinauto-recorder.svg
   :target: https://pypi.org/project/pywinauto-recorder
.. |Docs badge| image:: https://img.shields.io/badge/docs-latest-brightgreen.svg
   :target: https://pywinauto-recorder.readthedocs.io/
.. |License| image:: https://img.shields.io/badge/License-MIT-yellow.svg
   :target: https://opensource.org/licenses/MIT
   :alt: Repository License
.. |Codacy Badge| image:: https://app.codacy.com/project/badge/Grade/499d4f647ceb480abb921e0fda2d06c4
   :target: https://www.codacy.com/gh/beuaaa/pywinauto_recorder/dashboard?utm_source=github.com&amp;utm_medium=referral&amp;utm_content=beuaaa/pywinauto_recorder&amp;utm_campaign=Badge_Grade
