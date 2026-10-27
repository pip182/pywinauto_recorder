#!/usr/bin/env python3
"""
Previews the control panel with a fake recorder, so its UI can be checked on Linux or macOS
(the real recorder needs Windows). Nothing is recorded or replayed.

Usage: pip install PyQt6 pyperclip && python3 preview_panel.py
"""

import sys
import types
import time
import tempfile
from pathlib import Path

# Skips pywinauto_recorder/__init__.py, which imports the Windows-only recorder and player
pkg = types.ModuleType('pywinauto_recorder')
pkg.__path__ = [str(Path(__file__).parent / 'pywinauto_recorder')]
pkg.__version__ = 'preview'
sys.modules['pywinauto_recorder'] = pkg

from pywinauto_recorder.control_panel import run_control_panel  # noqa: E402


class FakeRecorder(object):
	"""Mimics the Recorder attributes and methods used by the control panel."""
	mode = 'Info'
	smart_mode = False
	relative_coordinate_mode = False
	process_menu_click_mode = False
	last_recorded_file = None
	last_copy_time = None

	def is_alive(self):
		return self.mode != 'Quit'

	def start_recording(self):
		time.sleep(0.6)
		self.mode = 'Record'

	def stop_recording(self):
		with tempfile.NamedTemporaryFile('w', suffix='.py', prefix='recorded ', delete=False) as f:
			f.write('# fake recording\n')
		self.last_recorded_file = f.name
		self.mode = 'Stop'
		return f.name

	def playback(self, str_code='', filename=''):
		self.mode = 'Play'
		time.sleep(1.5)
		self.mode = 'Stop'

	def quit(self):
		self.mode = 'Quit'


if __name__ == '__main__':
	sys.exit(run_control_panel(FakeRecorder()))
