"""
A small always-on-top floating panel (PyQt6) to drive a Recorder: record, stop, replay and the other core actions,
the outlines of the elements under the cursor, and the box showing the information of the element in Info mode.
"""

import html
import os
import sys
import threading
import time
import traceback
from pathlib import Path
from queue import Empty
import pyperclip
from PyQt6.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QRect, QRectF, QSettings, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QCursor, QDesktopServices, QGuiApplication, QIcon, QPainter, QPen, \
	QRegion
from PyQt6.QtWidgets import QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QMenu, \
	QMessageBox, QToolButton, \
	QSizePolicy, QVBoxLayout, QWidget, QWidgetAction
from . import __version__

__all__ = ['ControlPanel', 'ElementInfoBox', 'HighlightOverlay', 'get_application', 'run_control_panel',
           'show_playback_error']

OUTPUT_FOLDER = Path.home() / 'Pywinauto recorder'
WEB_SITE = 'https://pywinauto-recorder.readthedocs.io'
COPY_FEEDBACK_DURATION = 2.0
IDLE_OPACITY = 0.35
FADE_MS = 200

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
#status_bar QLabel { color: #b8cfe0; font: 9pt "Segoe UI Semibold"; letter-spacing: 0.3px; }
#status_bar QLabel#status_dot { color: #4aa3f0; font: 8pt "Segoe UI"; }
#status_bar[state="record"] { background: #33201f; border-color: #5a3432; border-left-color: #e04848; }
#status_bar[state="record"] QLabel { color: #f0c4c0; }
#status_bar[state="record"] QLabel#status_dot { color: #e04848; }
#status_bar[state="busy"] { background: #332b1c; border-color: #5a4a2e; border-left-color: #f0c040; }
#status_bar[state="busy"] QLabel { color: #f0e0b8; }
#status_bar[state="busy"] QLabel#status_dot { color: #f0c040; }
#status_bar[state="copied"] { background: #1d3324; border-color: #2f5a3c; border-left-color: #50c878; }
#status_bar[state="copied"] QLabel { color: #c0f0cc; }
#status_bar[state="copied"] QLabel#status_dot { color: #50c878; }
QLabel#grip { font: 16pt "Segoe UI"; padding: 0 4px; }
QToolButton { color: #f0f0f0; background: transparent; border: none; border-radius: 6px;
              padding: 8px 14px; font: 13pt "Segoe UI"; }
QToolButton:hover { background: #3c3c3c; }
QToolButton:checked { background: #505050; }
QToolButton:disabled { color: #707070; }
QToolButton::menu-indicator { image: none; }
QToolButton#record { color: #e04848; }
QToolButton#info { color: #4aa3f0; }
QToolButton#smart { color: #f0c040; }
QToolButton:disabled#record, QToolButton:disabled#info { color: #707070; }
QFrame#divider { background: #4a4a4a; }
QMenu { background: #2b2b2b; color: #f0f0f0; border: 1px solid #505050; padding: 4px; font: 9pt "Segoe UI"; }
QMenu::item { padding: 6px 24px 6px 30px; border-radius: 4px; }
QMenu::indicator { width: 12px; height: 12px; left: 10px; border-radius: 3px; }
QMenu::indicator:non-exclusive:unchecked { border: 1px solid #808080; background: transparent; }
QMenu::indicator:non-exclusive:checked { border: 1px solid #4aa3f0; background: #4aa3f0; }
QLabel#menu_header { color: #808080; font: 7pt "Segoe UI Semibold"; letter-spacing: 0.6px; padding: 6px 10px 2px 10px; }
QMenu::item:selected { background: #3c3c3c; }
QMenu::item:disabled { color: #707070; }
QMenu::separator { height: 1px; background: #444444; margin: 4px 6px; }
QToolTip { background: #1e2a33; color: #e0ecf5; border: 1px solid #34495a; border-radius: 4px;
           padding: 6px 8px; font: 9pt "Segoe UI"; }
"""

# The message boxes of the recorder (help, replay errors)
DIALOG_STYLE_SHEET = """
QMessageBox { background: #2b2b2b; }
QMessageBox QLabel { color: #e8e8e8; font: 9pt "Segoe UI"; }
QMessageBox QLabel a { color: #4aa3f0; }
QPushButton { color: #f0f0f0; background: #3c3c3c; border: 1px solid #505050; border-radius: 4px;
              padding: 5px 16px; font: 9pt "Segoe UI"; min-width: 60px; }
QPushButton:hover { background: #474747; }
QPushButton:default { border-color: #4aa3f0; }
QTextEdit { color: #e8e8e8; background: #1e1e1e; border: 1px solid #505050; font: 9pt "Consolas"; }
"""

# Kind of outlined element: (color, pen width, fill opacity, dashed, outset)
HIGHLIGHT_STYLES = {
	'unique': ('#50c878', 2, 0.12, False, 0),  # found by its path alone
	'ambiguous': ('#e04848', 2, 0.10, False, 0),  # several elements have the same path
	'selected': ('#f0c040', 2, 0.16, False, 0),  # the one under the cursor, found by its position among them
	'reference': ('#4aa3f0', 2, 0.10, False, 0),  # the element its position is relative to
	'inspected': ('#4aa3f0', 2, 0, False, 3),  # Info mode: the element under the cursor
	'common_parent': ('#c77dff', 1, 0, True, 0),  # Info mode: the parent shared with the previous element
}


WINDOWS = sys.platform == 'win32'
# The recorder warns if Windows reports one of these windows under the cursor instead of the element below it
OVERLAY_TITLE = 'Pywinauto recorder highlights'
INFO_BOX_TITLE = 'Pywinauto recorder element information'
_user32 = None


def _win32():
	""":return: A user32 of our own, so that its argument types don't change the ones used by pywinauto"""
	global _user32
	if _user32 is None:
		import ctypes
		from ctypes import wintypes
		_user32 = ctypes.WinDLL('user32', use_last_error=True)
		_user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
		_user32.GetWindowLongW.restype = ctypes.c_long
		_user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
		_user32.SetWindowLongW.restype = ctypes.c_long
		_user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
		# hWndInsertAfter as a signed integer, for HWND_TOPMOST (-1)
		_user32.SetWindowPos.argtypes = [wintypes.HWND, ctypes.c_ssize_t, ctypes.c_int, ctypes.c_int, ctypes.c_int,
		                                 ctypes.c_int, ctypes.c_uint]
	return _user32


def _make_click_through(widget):
	"""
	Makes sure that Windows lets the mouse through a window, never activates it, and leaves it out of the hit tests of
	UI Automation, so that the recorder finds the element below it. Qt sets WS_EX_LAYERED and WS_EX_TRANSPARENT for
	WindowTransparentForInput already: WS_EX_LAYERED isn't added here, as a layered window that Qt doesn't paint as
	one would be invisible.
	"""
	if not WINDOWS:
		return
	GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x00080000, 0x00000020
	WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000080, 0x08000000
	user32 = _win32()
	hwnd = int(widget.winId())
	style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
	if not style & WS_EX_LAYERED:
		print('Warning: "' + widget.windowTitle() + '" is not a layered window, the mouse may not go through it')
	wanted = style | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
	if wanted != style:
		user32.SetWindowLongW(hwnd, GWL_EXSTYLE, wanted)


def _raise_without_activating(widget):
	"""Brings a window to the top of the always-on-top windows, without taking the focus of the recorded application."""
	if WINDOWS:
		HWND_TOPMOST, SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = -1, 0x0001, 0x0002, 0x0010
		_win32().SetWindowPos(int(widget.winId()), HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)
	else:
		widget.raise_()


class HighlightOverlay(QWidget):
	"""
	A transparent window over a whole screen, which lets the mouse through, outlining the elements given by the
	`rectangles` function as (kind, x, y, width, height) in screen pixels, with a kind of HIGHLIGHT_STYLES.
	"""
	POLL_MS = 30
	RADIUS = 4

	def __init__(self, screen, rectangles, keep_above=()):
		"""
		:param screen: The QScreen to cover
		:param rectangles: A function returning the outlines to draw
		:param keep_above: The windows kept above the outlines when the overlay is brought to the top
		"""
		super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
		                 Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
		                 Qt.WindowType.WindowDoesNotAcceptFocus)
		self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
		self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
		self.setWindowTitle(OVERLAY_TITLE)
		self.screen_ = screen
		self.rectangles = rectangles
		self.keep_above = keep_above
		self._shown = ()
		self.setScreen(screen)
		self.fit_screen()
		screen.geometryChanged.connect(self.fit_screen)
		screen.logicalDotsPerInchChanged.connect(self.fit_screen)
		self.timer = QTimer(self, interval=self.POLL_MS, timeout=self._poll)
		self.timer.start()

	def fit_screen(self):
		# One pixel short of the screen, so that Windows doesn't take it for a full screen window
		self.setGeometry(self.screen_.geometry().adjusted(0, 0, 0, -1))
		self._shown = ()
		self.update()

	def showEvent(self, event):
		_make_click_through(self)
		super().showEvent(event)

	def _local_rectangle(self, x, y, width, height):
		"""
		:return: The rectangle in the window of a rectangle in screen pixels, or None if it is not on this screen.
		"""
		if WINDOWS:
			# Windows maps the screen pixels to the window itself, whatever the scale of each screen
			from ctypes import byref
			from ctypes.wintypes import POINT
			top_left = POINT(x, y)
			_win32().ScreenToClient(int(self.winId()), byref(top_left))
			ratio = self.devicePixelRatioF()
			rectangle = QRectF(top_left.x / ratio, top_left.y / ratio, width / ratio, height / ratio)
			return rectangle if rectangle.intersects(QRectF(self.rect())) else None
		# Elsewhere, Qt keeps the position of a screen in pixels and divides the coordinates in it by its ratio
		origin = self.screen_.geometry().topLeft()
		ratio = self.screen_.devicePixelRatio()
		size = self.screen_.size() * ratio
		if not QRect(origin.x(), origin.y(), round(size.width()), round(size.height())).intersects(
				QRect(x, y, width, height)):
			return None
		# From where the window really is, as a window manager may move it away from docks or top bars
		top_left = self.mapFromGlobal(QPointF(origin.x() + (x - origin.x()) / ratio, origin.y() + (y - origin.y()) / ratio))
		return QRectF(top_left.x(), top_left.y(), width / ratio, height / ratio)

	def _shapes(self, rectangles):
		for kind, *screen_rectangle in rectangles:
			rectangle = self._local_rectangle(*screen_rectangle)
			if rectangle is not None:
				color, width, fill, dashed, outset = HIGHLIGHT_STYLES.get(kind, HIGHLIGHT_STYLES['ambiguous'])
				# Drawn inside the element, so that the outlines of contiguous elements don't overlap
				inset = width / 2 - outset
				yield rectangle.adjusted(inset, inset, -inset, -inset), color, width, fill, dashed

	def _region(self, rectangles):
		region = QRegion()
		for rectangle, *_ in self._shapes(rectangles):
			region += rectangle.toAlignedRect().adjusted(-4, -4, 4, 4)
		return region

	def _poll(self):
		rectangles = self.rectangles()
		if rectangles != self._shown:
			if rectangles and not self._shown:
				# Back on top when outlines appear, as another always-on-top window may have covered the overlay
				_raise_without_activating(self)
				for window in self.keep_above:
					if window is not None and window.isVisible():
						_raise_without_activating(window)
			# Only the outlines that changed are repainted, as repainting the whole screen is slow
			dirty = self._region(self._shown) + self._region(rectangles)
			self._shown = rectangles
			if not dirty.isEmpty():
				self.update(dirty)

	def paintEvent(self, event):
		painter = QPainter(self)
		painter.setRenderHint(QPainter.RenderHint.Antialiasing)
		for rectangle, color, width, fill, dashed in self._shapes(self._shown):
			pen = QPen(QColor(color), width)
			if dashed:
				pen.setStyle(Qt.PenStyle.DashLine)
			painter.setPen(pen)
			fill_color = QColor(color)
			fill_color.setAlphaF(fill)
			painter.setBrush(fill_color if fill else Qt.BrushStyle.NoBrush)
			painter.drawRoundedRect(rectangle, self.RADIUS, self.RADIUS)
		painter.end()


def show_playback_error(parent, error, blocking=False):
	"""
	Shows the traceback of a script that failed to replay.

	:param parent: The parent window of the message box, or None
	:param error: The traceback
	:param blocking: True to wait for the message box to be closed
	"""
	lines = [line for line in error.strip().splitlines() if line.strip()]
	box = QMessageBox(QMessageBox.Icon.Critical, 'Replay failed', '', QMessageBox.StandardButton.Ok, parent)
	box.setStyleSheet(DIALOG_STYLE_SHEET)
	box.setTextFormat(Qt.TextFormat.RichText)
	box.setText('<b>The script stopped with an error</b><br>' + html.escape(lines[-1] if lines else error))
	box.setDetailedText(error)
	if blocking:
		box.exec()
	else:
		box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
		box.open()

INFO_BOX_WIDTH = 520
INFO_BOX_TOP = 150
INFO_STYLE_SHEET = """
#info_box { background: #2b2b2b; border: 1px solid #505050; border-radius: 8px; }
QLabel { color: #e8e8e8; font: 9pt "Segoe UI"; background: transparent; }
QLabel#context { color: #8a8a8a; font: 8pt "Segoe UI"; }
QLabel#element { color: #b8cfe0; font: 9pt "Segoe UI"; }
QLabel#hint { color: #707070; font: 8pt "Segoe UI"; }
QFrame#separator { background: #444444; }
"""


def _entry_html(name, type_, name_style=''):
	name_html = html.escape(name) if name else '<i style="color:#8a8a8a">no name</i>'
	if name_style:
		name_html = f'<span style="{name_style}">{name_html}</span>'
	if not type_:
		return name_html
	return f'{name_html} <span style="color:#7a8a96">{html.escape(type_)}</span>'


class ElementInfoBox(QWidget):
	"""
	The information of the element under the cursor in Info mode, read from the queue of the ElementInfoTooltip of
	the recorder: a dict with the 'context' path the element shares with the previous one, its own 'element' path
	(both lists of [name, type]) and its 'properties' (a list of [label, value]), or None to hide the box.

	It lets the mouse through and is displayed on the half of the screen away from the cursor.
	"""
	POLL_MS = 50

	def __init__(self, info_queue, panel=None):
		super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
		                 Qt.WindowType.Tool | Qt.WindowType.WindowTransparentForInput |
		                 Qt.WindowType.WindowDoesNotAcceptFocus)
		self.queue = info_queue
		self.panel = panel  # not covered by the box
		self.enabled = True  # False to only outline the element, without showing the box
		self.rectangles = ()  # the outlines of the element and of its common parent, for the HighlightOverlay
		self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
		self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
		self.setStyleSheet(INFO_STYLE_SHEET)
		self.setWindowTitle(INFO_BOX_TITLE)
		self.setFixedWidth(INFO_BOX_WIDTH)
		self.box = box = QWidget(self, objectName='info_box')
		outer = QVBoxLayout(self)
		outer.setContentsMargins(0, 0, 0, 0)
		outer.addWidget(box)
		layout = QVBoxLayout(box)
		layout.setContentsMargins(12, 12, 12, 12)
		layout.setSpacing(8)
		self.context = self._add_label(layout, 'context')
		self.element = self._add_label(layout, 'element')
		self.separator = QFrame(objectName='separator')
		self.separator.setFixedHeight(1)
		layout.addWidget(self.separator)
		self.properties = self._add_label(layout, 'properties')
		self._add_label(layout, 'hint').setText('CTRL+SHIFT+F copies the code finding this element')
		self.timer = QTimer(self, interval=self.POLL_MS, timeout=self._poll)
		self.timer.start()

	def showEvent(self, event):
		_make_click_through(self)
		super().showEvent(event)

	@staticmethod
	def _add_label(layout, name):
		label = QLabel(objectName=name, wordWrap=True, textFormat=Qt.TextFormat.RichText)
		layout.addWidget(label)
		return label

	def _poll(self):
		info = missing = object()
		while True:  # only the last posted information matters
			try:
				info = self.queue.get_nowait()
			except (Empty, OSError, ValueError):
				break
		if info is None:
			self.rectangles = ()
			self.hide()
		elif info is not missing:
			self.set_info(info)
			if self.enabled:
				self._place()  # before showing it, so that it doesn't appear somewhere else first
				self.show()
		elif self.isVisible():
			self._place()

	def set_enabled(self, enabled):
		self.enabled = enabled
		if not enabled:
			self.hide()
		elif self.rectangles:  # an element is being inspected
			self._place()
			self.show()

	def set_info(self, info):
		rectangles = []
		if info.get('rectangle'):
			rectangles.append(('inspected', *info['rectangle']))
		if info.get('parent_rectangle'):
			rectangles.append(('common_parent', *info['parent_rectangle']))
		self.rectangles = tuple(rectangles)
		context = info.get('context') or []
		self.context.setText(' › '.join(_entry_html(name, type_) for name, type_ in context))
		self.context.setVisible(bool(context))
		*parents, last = info.get('element') or [['', None]]
		parts = [_entry_html(name, type_) for name, type_ in parents]
		name, type_ = last
		element = _entry_html(name, None, 'color:#ffffff; font-size:11pt; font-weight:600')
		if type_:
			element += (f' &nbsp;<span style="background-color:#1e2a33; color:#4aa3f0; font-size:8pt">'
			            f'&nbsp;{html.escape(type_)}&nbsp;</span>')
		self.element.setText(' › '.join(parts + [element]))
		rows = ''.join(
			f'<tr><td style="color:#8a8a8a; font-family:Consolas; padding-right:12px">{html.escape(label)}</td>'
			f'<td>{html.escape(value).replace(chr(10), "<br>")}</td></tr>'
			for label, value in info.get('properties') or [])
		self.properties.setText(f'<table cellspacing="0" cellpadding="1">{rows}</table>')
		self.properties.setVisible(bool(rows))
		self.separator.setVisible(bool(rows))
		# Fits the height to the wrapped text (adjustSize() keeps the previous height when the box is visible)
		for layout in (self.box.layout(), self.layout()):
			layout.invalidate()
			layout.activate()
		self.resize(INFO_BOX_WIDTH, self.heightForWidth(INFO_BOX_WIDTH))

	def _place(self):
		"""On the half of the screen away from the cursor, below the control panel if it would cover it."""
		cursor = QCursor.pos()
		screen = QGuiApplication.screenAt(cursor) or QGuiApplication.primaryScreen()
		area = screen.availableGeometry()
		left, right = area.left() + 10, area.right() - self.width() - 10
		panel = self.panel.frameGeometry() if self.panel and self.panel.isVisible() else QRect()
		for x in (left, right) if cursor.x() > area.center().x() else (right, left):
			box = QRect(x, area.top() + INFO_BOX_TOP, self.width(), self.height())
			if box.intersects(panel.adjusted(-8, -8, 8, 8)):
				box.moveTop(panel.bottom() + 8)
			if not box.adjusted(-20, -20, 20, 20).contains(cursor):
				break
		if self.pos() != box.topLeft():
			self.move(box.topLeft())


class ControlPanel(QWidget):
	"""
	A frameless floating panel (drag it with the mouse) with buttons to start/stop recording, replay the last
	recorded script, toggle element information and Smart mode, plus a menu for the other actions.

	The recorder calls that block (start/stop recording, replay, help) run in a worker thread so the panel stays
	responsive; a timer polls the recorder to reflect the changes made with the keyboard shortcuts.
	"""
	POLL_MS = 200
	playback_failed = pyqtSignal(str)  # emitted by the replay thread, so that the error is shown by the Qt thread

	def __init__(self, recorder):
		super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint |
		                 Qt.WindowType.Tool)
		self.recorder = recorder
		self.settings = QSettings('Pywinauto recorder', 'Pywinauto recorder')
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
		# Only the status bar is faded, with an effect rather than the window opacity, which Wayland doesn't support
		self.opacity_effect = QGraphicsOpacityEffect(status_bar)
		status_bar.setGraphicsEffect(self.opacity_effect)
		self.fade = QPropertyAnimation(self.opacity_effect, b'opacity', self, duration=FADE_MS,
		                               easingCurve=QEasingCurve(QEasingCurve.Type.InOutQuad))
		outer = QVBoxLayout(self)
		outer.setContentsMargins(0, 0, 0, 0)
		outer.setSpacing(0)
		outer.addWidget(panel)
		outer.addWidget(status_bar)
		bar = QHBoxLayout(panel)
		bar.setContentsMargins(6, 6, 6, 6)
		bar.setSpacing(6)

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
		# The same width for the labelled buttons, so that they are evenly spaced and don't move when Record
		# becomes Stop, and square icon buttons
		labelled = (self.btn_record, self.btn_replay, self.btn_info, self.btn_smart)
		width = max(button.sizeHint().width() for button in labelled)
		side = max(button.sizeHint().height() for button in labelled)  # some symbols make a button taller
		for button in labelled:
			button.setFixedSize(width, side)
		for button in (self.btn_menu, self.btn_quit):
			button.setFixedSize(side, side)
		# Dividers between the actions (record, replay), the modes (info, smart) and the window buttons
		for button in (self.btn_info, self.btn_menu):
			divider = QFrame(objectName='divider')
			divider.setFixedSize(1, side // 2)
			bar.insertWidget(bar.indexOf(button), divider)

		# Ignored horizontally so that the width of the panel doesn't follow the length of the status text
		self.status = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
		self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
		status_layout = QHBoxLayout(status_bar)
		status_layout.setContentsMargins(8, 5, 8, 5)
		status_layout.setSpacing(6)
		status_dot = QLabel('\u25cf', objectName='status_dot')
		status_dot.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
		status_layout.addWidget(status_dot)
		status_layout.addWidget(self.status, 1)
		# Balances the dot so that the text is centered in the status bar
		status_layout.addSpacing(status_dot.sizeHint().width() + status_layout.spacing() - 2)

		self.timer = QTimer(self, interval=self.POLL_MS, timeout=self._refresh)
		self.timer.start()
		tooltip = getattr(recorder, 'element_info_tooltip', None)
		self.info_box = ElementInfoBox(tooltip.queue, self) if tooltip else None
		if self.info_box:
			self.info_box.set_enabled(self.action_info_box.isChecked())
		self.highlights = getattr(recorder, 'highlights', None)
		self.highlight_overlays = []
		self._create_overlays()
		QGuiApplication.instance().screenAdded.connect(self._create_overlays)
		QGuiApplication.instance().screenRemoved.connect(self._create_overlays)
		self.playback_failed.connect(lambda error: show_playback_error(self, error))
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
		menu.setToolTipsVisible(True)

		def add_action(text, help_text, slot=None, checkable=False):
			action = QAction(text, menu, checkable=checkable, toolTip=help_text)
			if slot:
				(action.toggled if checkable else action.triggered).connect(slot)
			menu.addAction(action)
			return action

		def add_header(text):
			if menu.actions():
				menu.addSeparator()
			header = QWidgetAction(menu)
			header.setDefaultWidget(QLabel(text.upper(), objectName='menu_header'))
			menu.addAction(header)

		add_header('Replay')
		add_action('Replay clipboard', 'Replay the Python code currently in the clipboard', self.replay_clipboard)
		add_action('Replay file...', 'Choose a Python script and replay it', self.replay_file)
		add_header('Recorded scripts')
		self.action_copy_last_script = add_action(
			'Copy last script to clipboard', 'Copy the code of the last recorded script to the clipboard',
			self.copy_last_script)
		add_action('Open output folder', f'Open {OUTPUT_FOLDER}, where the recorded scripts are saved',
		           self.open_output_folder)
		add_header('Recording options')
		self.action_relative_coordinates = add_action(
			'% relative coordinates',
			'Record where each click lands inside the element, as an offset from its center\n'
			'in % of its size, instead of always clicking its center', lambda checked: setattr(self.recorder, 'relative_coordinate_mode', checked),
			checkable=True)
		self.action_process_menu_click = add_action(
			'Record menu_click',
			'Record a series of clicks through a menu as a single menu_click("File->Save") line',
			lambda checked: setattr(self.recorder, 'process_menu_click_mode', checked), checkable=True)
		add_header('Display')
		self.action_info_box = add_action(
			'Element information box',
			'In Info mode, show the path and the properties of the element under the cursor in a box',
			self._set_info_box_enabled, checkable=True)
		self.action_info_box.setChecked(self.settings.value('show_info_box', True, type=bool))
		menu.addSeparator()
		add_action('Help', 'Keyboard shortcuts and how to replay a script', self.display_help)
		add_action('Web site', f'Open the documentation: {WEB_SITE}', lambda: QDesktopServices.openUrl(QUrl(WEB_SITE)))
		menu.aboutToShow.connect(self._sync_menu)
		menu.aboutToHide.connect(lambda: QTimer.singleShot(0, self._update_opacity))
		return menu

	def _set_info_box_enabled(self, enabled):
		self.settings.setValue('show_info_box', enabled)
		self.settings.sync()  # written now, in case the recorder doesn't quit normally
		if getattr(self, 'info_box', None):
			self.info_box.set_enabled(enabled)

	def _sync_menu(self):
		self.action_relative_coordinates.setChecked(self.recorder.relative_coordinate_mode)
		self.action_process_menu_click.setChecked(self.recorder.process_menu_click_mode)
		self.action_copy_last_script.setEnabled(self.last_recorded_file is not None)

	def mousePressEvent(self, event):
		if event.button() == Qt.MouseButton.LeftButton:
			# The window manager moves the window (required on Wayland, where a window can't move itself)
			if not self.windowHandle().startSystemMove():
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
		"""The status bar is faded so that it doesn't hide what is below it, until the mouse cursor is over the panel."""
		hovered = self.underMouse() or self._drag_offset is not None or self.btn_menu.menu().isVisible()
		target = 1.0 if hovered else IDLE_OPACITY
		if self.fade.endValue() == target and self.fade.state() == QPropertyAnimation.State.Running:
			return
		self.fade.stop()
		if self.opacity_effect.opacity() != target:
			# Starts from the current opacity, so that a fade reversed halfway doesn't jump
			self.fade.setStartValue(self.opacity_effect.opacity())
			self.fade.setEndValue(target)
			self.fade.start()

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
		self._run_in_background(self.recorder.playback, str_code, filename, self.playback_failed.emit)

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

	def _create_overlays(self, *_):
		"""One overlay per screen, created again when a screen is plugged in or out."""
		for overlay in self.highlight_overlays:
			overlay.timer.stop()
			overlay.hide()  # right away, as a removed screen is deleted before deleteLater() deletes its overlay
			overlay.deleteLater()
		self.highlight_overlays = [
			HighlightOverlay(screen, self._highlight_rectangles, keep_above=(self.info_box, self))
			for screen in QGuiApplication.screens()]
		for overlay in self.highlight_overlays:
			overlay.show()

	def _highlight_rectangles(self):
		recorder_rectangles = self.highlights.get() if self.highlights else ()
		return recorder_rectangles + (self.info_box.rectangles if self.info_box else ())

	def display_help(self):
		text = HELP_TEXT.format(version=__version__, folder=OUTPUT_FOLDER, web_site=WEB_SITE)
		box = QMessageBox(QMessageBox.Icon.NoIcon, 'Pywinauto recorder', text, QMessageBox.StandardButton.Ok, self)
		box.setStyleSheet(DIALOG_STYLE_SHEET)
		box.setIconPixmap(self.windowIcon().pixmap(48, 48))
		box.setTextFormat(Qt.TextFormat.RichText)
		box.exec()

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
			return 'record', 'Recording  ·  CTRL+ALT+R to stop'
		if mode == 'Initializing':
			return 'busy', 'Starting...'
		if mode == 'Info':
			return 'idle', 'Inspecting  ·  hover an element, CTRL+SHIFT+F copies its code'
		if self.last_recorded_file:
			return 'idle', 'Saved  ·  ' + self.last_recorded_file.name
		return 'idle', 'Ready  ·  press Record to start'

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


_application = None


def get_application():
	"""
	:return: The Qt application of the recorder, created if needed
	"""
	if sys.excepthook is sys.__excepthook__:
		# PyQt aborts the process on an exception raised in a slot, unless an exception hook is installed
		sys.excepthook = lambda *exc_info: traceback.print_exception(*exc_info)
	global _application
	app = QApplication.instance()
	if app is None:
		app = QApplication(sys.argv)
		app.setApplicationName('Pywinauto recorder')
		app.setStyle('Fusion')
		app.setWindowIcon(_application_icon())
		app.setQuitOnLastWindowClosed(False)
		# Kept here, as Python would delete it with the last reference, which callers may not keep
		_application = app
	return app


def _delete_windows(app):
	"""
	Deletes the windows while the Qt application still exists: Python would otherwise delete the ones it still
	refers to after it, when exiting, which crashes.
	"""
	from PyQt6 import sip
	for window in app.topLevelWidgets():
		if not sip.isdeleted(window):  # deleted with its parent window, for a menu
			sip.delete(window)


def run_control_panel(recorder, prepare=None):
	"""
	Shows the control panel of the recorder and blocks until the user quits.

	:param recorder: The Recorder driven by the panel
	:param prepare: Called with the panel before it is shown, to customize it
	:return: The exit code of the Qt application
	"""
	app = get_application()
	panel = ControlPanel(recorder)
	if prepare:
		prepare(panel)
	panel.show()
	exit_code = app.exec()
	_delete_windows(app)
	return exit_code
