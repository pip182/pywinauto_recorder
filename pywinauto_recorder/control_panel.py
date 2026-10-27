"""A small always-on-top floating panel (PyQt6) to drive a Recorder: record, stop, replay and the other core actions."""

import os
import sys
import threading
import time
from pathlib import Path
import pyperclip
from PyQt6.QtCore import Qt, QTimer, QUrl
from PyQt6.QtGui import QAction, QDesktopServices, QIcon
from PyQt6.QtWidgets import QApplication, QFileDialog, QHBoxLayout, QLabel, QMenu, QMessageBox, QToolButton, \
	QSizePolicy, QVBoxLayout, QWidget
from . import __version__

__all__ = ['ControlPanel', 'get_application', 'run_control_panel']

OUTPUT_FOLDER = Path.home() / 'Pywinauto recorder'
WEB_SITE = 'https://pywinauto-recorder.readthedocs.io'
COPY_FEEDBACK_DURATION = 2.0
IDLE_OPACITY = 0.35

HELP_TEXT = """<h3>Pywinauto recorder {version}</h3>
<table cellspacing="4">
<tr><td><b>CTRL+ALT+R</b></td><td>Start / stop recording</td></tr>
<tr><td><b>CTRL+SHIFT+D</b></td><td>Display / hide element information</td></tr>
<tr><td><b>CTRL+ALT+S</b></td><td>Smart mode on / off</td></tr>
<tr><td><b>CTRL+SHIFT+F</b></td><td>Copy the code finding the element under the cursor</td></tr>
</table>
<p>Recorded scripts are saved in <i>{folder}</i> and copied to the clipboard.</p>
<p>To replay a script: click <b>Replay</b>, use <b>Replay file...</b> in the ⋯ menu,
drag and drop it on pywinauto_recorder.exe or run <i>python.exe recorded_file.py</i>.</p>
<p><a href="{web_site}">{web_site}</a></p>"""

STYLE_SHEET = """
#panel { background: #2b2b2b; border: 1px solid #505050; border-bottom: none;
         border-top-left-radius: 6px; border-top-right-radius: 6px; }
QLabel { color: #a0a0a0; font: 8pt "Segoe UI"; }
#status_bar { background: #1e2a33; border: 1px solid #34495a; border-left: 3px solid #4aa3f0;
              border-bottom-left-radius: 6px; border-bottom-right-radius: 6px; }
#status_bar QLabel { color: #b8cfe0; font: 8pt "Segoe UI Semibold"; letter-spacing: 0.3px; }
#status_bar QLabel#status_dot { color: #4aa3f0; font: 7pt "Segoe UI"; }
#status_bar[state="record"] { background: #33201f; border-color: #5a3432; border-left-color: #e04848; }
#status_bar[state="record"] QLabel { color: #f0c4c0; }
#status_bar[state="record"] QLabel#status_dot { color: #e04848; }
#status_bar[state="busy"] { background: #332b1c; border-color: #5a4a2e; border-left-color: #f0c040; }
#status_bar[state="busy"] QLabel { color: #f0e0b8; }
#status_bar[state="busy"] QLabel#status_dot { color: #f0c040; }
#status_bar[state="copied"] { background: #1d3324; border-color: #2f5a3c; border-left-color: #50c878; }
#status_bar[state="copied"] QLabel { color: #c0f0cc; }
#status_bar[state="copied"] QLabel#status_dot { color: #50c878; }
QLabel#grip { font: 12pt "Segoe UI"; padding: 0 2px; }
QToolButton { color: #f0f0f0; background: transparent; border: none; border-radius: 4px;
              padding: 4px 8px; font: 10pt "Segoe UI"; }
QToolButton:hover { background: #3c3c3c; }
QToolButton:checked { background: #505050; }
QToolButton:disabled { color: #707070; }
QToolButton::menu-indicator { image: none; }
QToolButton#record { color: #e04848; }
QToolButton#info { color: #4aa3f0; }
QToolButton#smart { color: #f0c040; }
QToolButton:disabled#record, QToolButton:disabled#info { color: #707070; }
QMenu { background: #2b2b2b; color: #f0f0f0; border: 1px solid #505050; padding: 4px; font: 9pt "Segoe UI"; }
QMenu::item { padding: 5px 24px 5px 20px; border-radius: 4px; }
QMenu::item:selected { background: #3c3c3c; }
QMenu::item:disabled { color: #707070; }
QMenu::separator { height: 1px; background: #505050; margin: 4px 6px; }
"""


class ControlPanel(QWidget):
	"""
	A frameless floating panel (drag it with the mouse) with buttons to start/stop recording, replay the last
	recorded script, toggle element information and Smart mode, plus a menu for the other actions.

	The recorder calls that block (start/stop recording, replay, help) run in a worker thread so the panel stays
	responsive; a timer polls the recorder to reflect the changes made with the keyboard shortcuts.
	"""
	POLL_MS = 200

	def __init__(self, recorder):
		super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
		                 Qt.WindowType.Tool)
		self.recorder = recorder
		self._busy = False
		self._hidden_for_replay = False
		self._drag_offset = None

		self.setWindowTitle('Pywinauto recorder')
		self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
		self.setStyleSheet(STYLE_SHEET)
		panel = QWidget(self)
		panel.setObjectName('panel')
		# The status bar is a separate element docked under the button bar
		self.status_bar = status_bar = QWidget(self)
		status_bar.setObjectName('status_bar')
		status_bar.setProperty('state', 'idle')
		outer = QVBoxLayout(self)
		outer.setContentsMargins(0, 0, 0, 0)
		outer.setSpacing(0)
		outer.addWidget(panel)
		outer.addWidget(status_bar)
		bar = QHBoxLayout(panel)
		bar.setContentsMargins(4, 3, 4, 3)
		bar.setSpacing(2)

		grip = QLabel('⠇', objectName='grip', toolTip='Drag to move')
		grip.setCursor(Qt.CursorShape.SizeAllCursor)
		grip.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
		bar.addWidget(grip)
		self.btn_record = self._add_button(bar, 'record', self.toggle_recording, 'Start / stop recording (CTRL+ALT+R)')
		self.btn_replay = self._add_button(bar, 'replay', self.replay, 'Replay the last recorded script')
		self.btn_info = self._add_button(
			bar, 'info', self.toggle_info, 'Display element information (CTRL+SHIFT+D)', checkable=True)
		self.btn_smart = self._add_button(
			bar, 'smart', self.toggle_smart_mode, 'Smart mode (CTRL+ALT+S)', checkable=True)
		self.btn_info.setText('ⓘ Info')
		self.btn_smart.setText('★ Smart')
		self.btn_replay.setText('▶ Replay')
		self.btn_menu = self._add_button(bar, 'menu', None, 'More actions')
		self.btn_menu.setText('⋯')
		self.btn_menu.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
		self.btn_menu.setMenu(self._create_menu())
		self.btn_quit = self._add_button(bar, 'quit', self.quit, 'Quit Pywinauto recorder')
		self.btn_quit.setText('✕')

		# Ignored horizontally so that the width of the panel doesn't follow the length of the status text
		self.status = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
		self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
		status_layout = QHBoxLayout(status_bar)
		status_layout.setContentsMargins(6, 3, 8, 3)
		status_layout.setSpacing(5)
		status_dot = QLabel('\u25cf', objectName='status_dot')
		status_dot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
		status_layout.addWidget(status_dot)
		status_layout.addWidget(self.status, 1)
		# Balances the dot so that the text is centered in the status bar
		status_layout.addSpacing(status_dot.sizeHint().width() + status_layout.spacing() - 2)

		self.timer = QTimer(self, interval=self.POLL_MS, timeout=self._refresh)
		self.timer.start()
		self._refresh()
		self._update_opacity()
		self.adjustSize()
		screen = QApplication.primaryScreen().availableGeometry()
		self.move(screen.center().x() - self.width() // 2, screen.top() + 10)

	def _add_button(self, layout, name, slot, tooltip, checkable=False):
		button = QToolButton(objectName=name, toolTip=tooltip, checkable=checkable)
		button.setCursor(Qt.CursorShape.PointingHandCursor)
		if slot:
			button.clicked.connect(slot)
		layout.addWidget(button)
		return button

	def _create_menu(self):
		menu = QMenu(self)
		menu.addAction('Replay clipboard', self.replay_clipboard)
		menu.addAction('Replay file...', self.replay_file)
		self.action_copy_last_script = menu.addAction('Copy last script to clipboard', self.copy_last_script)
		menu.addAction('Open output folder', self.open_output_folder)
		menu.addSeparator()
		self.action_relative_coordinates = QAction('% relative coordinates', menu, checkable=True)
		self.action_relative_coordinates.toggled.connect(
			lambda checked: setattr(self.recorder, 'relative_coordinate_mode', checked))
		menu.addAction(self.action_relative_coordinates)
		self.action_process_menu_click = QAction('Record menu_click', menu, checkable=True)
		self.action_process_menu_click.toggled.connect(
			lambda checked: setattr(self.recorder, 'process_menu_click_mode', checked))
		menu.addAction(self.action_process_menu_click)
		menu.addSeparator()
		menu.addAction('Help', self.display_help)
		menu.addAction('Web site', lambda: QDesktopServices.openUrl(QUrl(WEB_SITE)))
		menu.aboutToShow.connect(self._sync_menu)
		menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self._update_opacity))
		return menu

	def _sync_menu(self):
		self.action_relative_coordinates.setChecked(self.recorder.relative_coordinate_mode)
		self.action_process_menu_click.setChecked(self.recorder.process_menu_click_mode)
		self.action_copy_last_script.setEnabled(self.last_recorded_file is not None)

	def mousePressEvent(self, event):
		if event.button() == Qt.MouseButton.LeftButton:
			self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

	def mouseMoveEvent(self, event):
		if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
			self.move(event.globalPosition().toPoint() - self._drag_offset)

	def mouseReleaseEvent(self, event):
		self._drag_offset = None

	def enterEvent(self, event):
		self._update_opacity()

	def leaveEvent(self, event):
		self._update_opacity()

	def _update_opacity(self):
		"""The panel is faded so that it doesn't hide what is below it, until the mouse cursor is over it."""
		hovered = self.underMouse() or self._drag_offset is not None or self.btn_menu.menu().isVisible()
		self.setWindowOpacity(1.0 if hovered else IDLE_OPACITY)

	def _run_in_background(self, target, *args):
		def work():
			try:
				target(*args)
			finally:
				self._busy = False

		self._busy = True
		self._refresh()
		threading.Thread(target=work, daemon=True).start()

	@property
	def last_recorded_file(self):
		file_name = getattr(self.recorder, 'last_recorded_file', None)
		if file_name and os.path.isfile(str(file_name)):
			return Path(str(file_name))
		return None

	def toggle_recording(self):
		if self.recorder.mode == 'Record':
			self._run_in_background(self.recorder.stop_recording)
		elif self.recorder.mode != 'Play':
			self._run_in_background(self.recorder.start_recording)

	def _replay(self, str_code='', filename=''):
		if self._busy or self.recorder.mode in ('Record', 'Play'):
			return
		# Hidden while replaying so that it doesn't cover the elements the script clicks on.
		self._hidden_for_replay = True
		self.hide()
		self._run_in_background(self.recorder.playback, str_code, filename)

	def replay(self):
		if self.last_recorded_file:
			self._replay(filename=str(self.last_recorded_file))
		else:
			self.replay_clipboard()

	def replay_clipboard(self):
		self._replay(str_code=pyperclip.paste())

	def replay_file(self):
		initial_dir = OUTPUT_FOLDER if OUTPUT_FOLDER.is_dir() else Path.home()
		file_name, _ = QFileDialog.getOpenFileName(
			self, 'Replay a Python script', str(initial_dir), 'Python scripts (*.py);;All files (*.*)')
		if file_name:
			self._replay(filename=file_name)

	def copy_last_script(self):
		if self.last_recorded_file:
			pyperclip.copy(self.last_recorded_file.read_text(encoding='utf-8'))

	def toggle_info(self):
		if self.recorder.mode == 'Info':
			self.recorder.mode = 'Stop'
		elif self.recorder.mode == 'Stop':
			self.recorder.mode = 'Info'
		self._refresh()

	def toggle_smart_mode(self):
		self.recorder.smart_mode = not self.recorder.smart_mode
		self._refresh()

	def open_output_folder(self):
		OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
		QDesktopServices.openUrl(QUrl.fromLocalFile(str(OUTPUT_FOLDER)))

	def display_help(self):
		text = HELP_TEXT.format(version=__version__, folder=OUTPUT_FOLDER, web_site=WEB_SITE)
		QMessageBox.about(self, 'Pywinauto recorder', text)

	def quit(self):
		self.timer.stop()
		self.recorder.quit()
		QApplication.quit()

	def _status(self, mode):
		""":return: The state of the status bar (for its style) and its text"""
		if self._busy and mode != 'Record':
			return 'busy', 'Please wait...'
		last_copy_time = getattr(self.recorder, 'last_copy_time', None)
		if last_copy_time and time.time() - last_copy_time < COPY_FEEDBACK_DURATION:
			return 'copied', 'Code copied to clipboard'
		if mode == 'Record':
			return 'record', 'Recording...   CTRL+ALT+R to stop'
		if mode == 'Initializing':
			return 'busy', 'Starting...'
		if self.last_recorded_file:
			return 'idle', 'Last: ' + self.last_recorded_file.name
		return 'idle', 'Ready'

	def _refresh(self):
		"""Reflects the recorder state, also changed by keyboard shortcuts, in the panel."""
		if self.recorder.mode == 'Quit' and not self.recorder.is_alive():
			self.timer.stop()
			QApplication.quit()
			return
		mode = self.recorder.mode
		ready = not self._busy and mode not in ('Initializing', 'Play')
		if mode == 'Record':
			self.btn_record.setText('■ Stop')
			self.btn_record.setEnabled(not self._busy)
		else:
			self.btn_record.setText('● Record')
			self.btn_record.setEnabled(ready)
		self.btn_replay.setEnabled(ready and mode != 'Record')
		self.btn_info.setEnabled(ready and mode in ('Info', 'Stop'))
		self.btn_info.setChecked(mode == 'Info')
		self.btn_smart.setChecked(self.recorder.smart_mode)
		self.btn_menu.setEnabled(ready and mode != 'Record')
		self.btn_quit.setEnabled(not self._busy)
		state, text = self._status(mode)
		if self.status_bar.property('state') != state:
			self.status_bar.setProperty('state', state)
			self.setStyleSheet(STYLE_SHEET)  # re-applied so that the [state=...] selectors are evaluated again
		self.status.setText(self.status.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, self.status.width()))
		self.status.setToolTip(text)
		if self._hidden_for_replay and not self._busy and mode != 'Play':
			self._hidden_for_replay = False
			self.show()


def _application_icon():
	here = Path(__file__).parent
	for folder in (here, here.parent):  # the compiled version has the Icons folder next to the executable
		icon_file = folder / 'Icons' / 'IconPyRec.ico'
		if icon_file.is_file():
			return QIcon(str(icon_file))
	return QIcon()


def get_application():
	"""
	:return: The Qt application of the recorder, created if needed
	"""
	app = QApplication.instance()
	if app is None:
		app = QApplication(sys.argv)
		app.setApplicationName('Pywinauto recorder')
		app.setStyle('Fusion')
		app.setWindowIcon(_application_icon())
		app.setQuitOnLastWindowClosed(False)
	return app


def run_control_panel(recorder):
	"""
	Shows the control panel of the recorder and blocks until the user quits.

	:param recorder: The Recorder driven by the panel
	:return: The exit code of the Qt application
	"""
	app = get_application()
	panel = ControlPanel(recorder)
	panel.show()
	return app.exec()
