#!/usr/bin/env python3
"""
Previews the control panel on Linux or macOS (the real recorder needs Windows) with a fake recorder, which inspects
the widgets of a sample app instead of the desktop: hover them in Info mode to see their outlines and information,
and click them while recording to get a script. Nothing is really replayed.

Under Wayland, the preview runs through XWayland, as Wayland doesn't let windows know or choose where they are.

Usage: pip install PyQt6 pyperclip && python3 preview_panel.py
"""

import os
import queue
import sys
import time
import types
from pathlib import Path

if os.environ.get('XDG_SESSION_TYPE') == 'wayland':
	os.environ.setdefault('QT_QPA_PLATFORM', 'xcb')

# Skips pywinauto_recorder/__init__.py, which imports the Windows-only recorder and player
pkg = types.ModuleType('pywinauto_recorder')
pkg.__path__ = [str(Path(__file__).parent / 'pywinauto_recorder')]
pkg.__version__ = 'preview'
sys.modules['pywinauto_recorder'] = pkg

import pyperclip  # noqa: E402
from PyQt6.QtCore import QEvent, QObject, QRect, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt6.QtGui import QAction, QCursor, QGuiApplication, QKeySequence, QShortcut  # noqa: E402
from PyQt6.QtWidgets import QApplication, QCheckBox, QComboBox, QGridLayout, QGroupBox, QHBoxLayout, QLabel, \
	QLineEdit, QListWidget, QPushButton, QVBoxLayout, QWidget, QWidgetAction  # noqa: E402
from pywinauto_recorder.control_panel import OUTPUT_FOLDER, get_application, run_control_panel  # noqa: E402

PATH_SEPARATOR, TYPE_SEPARATOR = '->', '||'
TYPE_NAMES = ((QPushButton, 'Button'), (QCheckBox, 'CheckBox'), (QLineEdit, 'Edit'), (QComboBox, 'ComboBox'),
              (QListWidget, 'List'), (QGroupBox, 'Group'), (QLabel, 'Text'))


class SampleApp(QWidget):
	"""An application to inspect, with elements found by their path alone and elements sharing the same path."""
	visibility_changed = pyqtSignal(bool)

	def __init__(self):
		super().__init__()
		self.setWindowTitle('Sample app')
		layout = QVBoxLayout(self)
		toolbar = QGroupBox('Toolbar')
		row = QHBoxLayout(toolbar)
		for _ in range(4):
			row.addWidget(QPushButton('Item'))  # the same path: found by their position
		layout.addWidget(toolbar)
		form = QGroupBox('Form')
		grid = QGridLayout(form)
		for i, label in enumerate(('Name:', 'Email:')):
			grid.addWidget(QLabel(label), i, 0)
			grid.addWidget(QLineEdit(), i, 1)  # unnamed: found by their position, or by their label in Smart mode
		grid.addWidget(QLabel('Country:'), 2, 0)
		country = QComboBox()
		country.addItems(['France', 'Canada', 'Japan'])
		grid.addWidget(country, 2, 1)
		grid.addWidget(QCheckBox('Remember me'), 3, 1)
		layout.addWidget(form)
		fruits = QGroupBox('Fruits')
		QVBoxLayout(fruits).addWidget(QListWidget())
		fruits.findChild(QListWidget).addItems(['Apple', 'Banana', 'Cherry', 'Banana'])
		layout.addWidget(fruits)
		buttons = QHBoxLayout()
		buttons.addStretch()
		for text in ('OK', 'Cancel'):
			buttons.addWidget(QPushButton(text))
		layout.addLayout(buttons)
		self.resize(460, 480)

	def showEvent(self, event):
		self.visibility_changed.emit(True)
		super().showEvent(event)

	def hideEvent(self, event):  # also when closed with its title bar
		self.visibility_changed.emit(False)
		super().hideEvent(event)


class Element(object):
	"""A widget or a list item of the sample app, with its path and rectangle in screen pixels."""
	def __init__(self, entries, rectangle, widget):
		self.entries = entries  # [name, type] of the element and of its ancestors, from the window
		self.rectangle = rectangle
		self.widget = widget

	@property
	def path(self):
		return PATH_SEPARATOR.join(name + TYPE_SEPARATOR + type_ for name, type_ in self.entries)


def _entry(widget):
	if widget.isWindow():
		return [widget.windowTitle(), 'Window']
	for widget_class, type_ in TYPE_NAMES:
		if isinstance(widget, widget_class):
			if isinstance(widget, (QLineEdit, QComboBox, QListWidget)):
				name = ''
			elif isinstance(widget, QGroupBox):
				name = widget.title()
			else:
				name = widget.text()
			return [name.replace('&', ''), type_]
	return None  # a layout widget, skipped in paths


def _screen_rectangle(widget, rectangle):
	""":return: A rectangle of a widget in screen pixels, as the recorder gets them from Windows"""
	top_left = widget.mapToGlobal(rectangle.topLeft())
	screen = widget.screen()
	origin, ratio = screen.geometry().topLeft(), screen.devicePixelRatio()
	return QRect(round(origin.x() + (top_left.x() - origin.x()) * ratio),
	             round(origin.y() + (top_left.y() - origin.y()) * ratio),
	             round(rectangle.width() * ratio), round(rectangle.height() * ratio))


def _element(widget, list_item=None):
	entries = []
	w = widget
	while w is not None:
		entry = _entry(w)
		if entry:
			entries.insert(0, entry)
		w = None if w.isWindow() else w.parentWidget()
	if list_item is not None:
		entries.append([list_item.text(), 'ListItem'])
		rectangle = widget.visualItemRect(list_item)
		return Element(entries, _screen_rectangle(widget.viewport(), rectangle), widget)
	return Element(entries, _screen_rectangle(widget, widget.rect()), widget)


def _all_elements(app_window):
	elements = [_element(app_window)]
	for widget in app_window.findChildren(QWidget):
		if widget.isVisible() and _entry(widget):
			elements.append(_element(widget))
			if isinstance(widget, QListWidget):
				elements.extend(_element(widget, widget.item(i)) for i in range(widget.count()))
	return elements


def _element_at(app_window, position):
	# QApplication.widgetAt() would find the outlines and the info box, which let the mouse through
	for window in QApplication.topLevelWidgets():
		if window is not app_window and window.isVisible() and window.frameGeometry().contains(position) and \
				not window.windowFlags() & Qt.WindowType.WindowTransparentForInput:
			return None  # the control panel, its menu or a message box
	if not app_window.isVisible() or not app_window.frameGeometry().contains(position):
		return None
	widget = app_window.childAt(app_window.mapFromGlobal(position)) or app_window
	list_widget = widget.parentWidget()
	if isinstance(list_widget, QListWidget) and widget is list_widget.viewport():
		item = list_widget.itemAt(widget.mapFromGlobal(position))
		if item:
			return _element(list_widget, item)
	while widget is not app_window and not _entry(widget):
		widget = widget.parentWidget()
	return _element(widget)


def _grid_position(element, matches):
	""":return: The [row, column] of an element among the ones having the same path, like the recorder"""
	rows = []
	for match in sorted(matches, key=lambda m: (m.rectangle.top(), m.rectangle.left())):
		if rows and abs(rows[-1][0].rectangle.top() - match.rectangle.top()) < match.rectangle.height() / 2:
			rows[-1].append(match)
		else:
			rows.append([match])
	for y, row in enumerate(rows):
		for x, match in enumerate(sorted(row, key=lambda m: m.rectangle.left())):
			if match.rectangle == element.rectangle:
				return y, x
	return 0, 0


def _reference(element, elements):
	""":return: The nearest element found by its path alone on the left of the element (Smart mode), or None"""
	paths = [e.path for e in elements]
	candidates = [
		e for e in elements if paths.count(e.path) == 1 and e.rectangle.right() <= element.rectangle.left() and
		abs(e.rectangle.center().y() - element.rectangle.center().y()) < element.rectangle.height() / 2]
	return max(candidates, key=lambda e: e.rectangle.right(), default=None)


class FakeHighlights(object):
	"""Mimics the Highlights of the Recorder: the outlines of the elements under the cursor."""
	rectangles = ()

	def get(self):
		return self.rectangles


class FakeElementInfoTooltip(object):
	"""Mimics the ElementInfoTooltip of the Recorder: its queue of information for the info box."""
	def __init__(self):
		self.queue = queue.Queue()


class FakeRecorder(QObject):
	"""
	Mimics the Recorder attributes and methods used by the control panel, inspecting the sample app like the
	recorder inspects the desktop, with the same strategies to find the element under the cursor.
	"""
	LOOP_MS = 100

	def __init__(self, app_window):
		super().__init__(app_window)  # deleted with it
		self.app_window = app_window
		self.window_title = app_window.windowTitle()  # read here, as the scripts are written by a worker thread
		self.mode = 'Info'
		self.smart_mode = False
		self.relative_coordinate_mode = False
		self.process_menu_click_mode = False
		self.last_recorded_file = None
		self.last_copy_time = None
		self.highlights = FakeHighlights()
		self.element_info_tooltip = FakeElementInfoTooltip()
		self._previous_path = None
		self._dwell = 0  # loops on the same element, which make the recorder try the next strategies
		self._info_element = None
		self._unique_path = None
		self._clicks = []
		QApplication.instance().installEventFilter(self)
		QShortcut(QKeySequence('Ctrl+Shift+F'), app_window, self.copy_find_code,
		          context=Qt.ShortcutContext.ApplicationShortcut)
		self.timer = QTimer(self, interval=self.LOOP_MS, timeout=self._loop)
		self.timer.start()

	def _loop(self):
		element = _element_at(self.app_window, QCursor.pos()) if self.mode in ('Info', 'Record') else None
		if element is None:
			self.highlights.rectangles = ()
			self._unique_path = None
			self._post_info(None)
			return
		self._dwell = self._dwell + 1 if element.path == self._previous_path else 0
		self._previous_path = element.path
		elements = _all_elements(self.app_window)
		matches = [e for e in elements if e.path == element.path]
		rectangles = []
		if len(matches) == 1:
			rectangles.append(('unique', element.rectangle))
			self._unique_path = element.path
		elif self._dwell == 0:  # the path alone: every element having it is ambiguous
			rectangles.extend(('ambiguous', m.rectangle) for m in matches)
			self._unique_path = None
		else:
			reference = _reference(element, elements) if self.smart_mode else None
			if reference:
				rectangles += [('reference', reference.rectangle), ('selected', element.rectangle)]
				x = _grid_position(element, matches)[1]
				self._unique_path = f'{element.path}#[{reference.path},{x}]'
			else:
				rectangles.extend(('ambiguous', m.rectangle) for m in matches if m.rectangle != element.rectangle)
				rectangles.append(('selected', element.rectangle))
				self._unique_path = '{}#[{},{}]'.format(element.path, *_grid_position(element, matches))
		self.highlights.rectangles = tuple(
			(kind, r.x(), r.y(), r.width(), r.height()) for kind, r in rectangles)
		self._post_info(element if self.mode == 'Info' else None)

	def _post_info(self, element):
		previous, self._info_element = self._info_element, element
		if element is None:
			if previous is not None:
				self.element_info_tooltip.queue.put(None)
			return
		if previous is not None and previous.rectangle == element.rectangle:
			return
		# The path shared with the previous element, without the last entry of either, like _find_common_path()
		common = []
		if previous is not None:
			for a, b in zip(element.entries[:-1], previous.entries[:-1]):
				if a != b:
					break
				common.append(a)
		parent = None
		if common:
			parent = next((e for e in _all_elements(self.app_window) if e.entries == common), None)
		widget = element.widget
		properties = [['process id', str(os.getpid())], ['native window handle', str(int(widget.winId()))]]
		if isinstance(widget, QLineEdit):
			properties.append(['wrapper.get_value()', widget.text()])
		elif isinstance(widget, QComboBox):
			properties.append(['ComboBoxWrapper(wrapper).selected_text()', widget.currentText()])
		elif isinstance(widget, QCheckBox):
			properties.append(['ButtonWrapper(wrapper).is_checked()', str(widget.isChecked())])
		r = element.rectangle
		self.element_info_tooltip.queue.put({
			'context': common,
			'element': element.entries[len(common):],
			'properties': properties,
			'rectangle': [r.x(), r.y(), r.width(), r.height()],
			'parent_rectangle': [parent.rectangle.x(), parent.rectangle.y(), parent.rectangle.width(),
			                     parent.rectangle.height()] if parent else None})

	def eventFilter(self, watched, event):
		if self.mode == 'Record' and event.type() == QEvent.Type.MouseButtonRelease and self._unique_path and \
				isinstance(watched, QWidget) and watched.window() is self.app_window:
			if not self._clicks or self._clicks[-1] != self._unique_path:
				self._clicks.append(self._unique_path)
		return False

	@staticmethod
	def _relative(path):
		return path.split(PATH_SEPARATOR, 1)[1] if PATH_SEPARATOR in path else ''

	def copy_find_code(self):
		if self._unique_path:
			pyperclip.copy(f'with UIPath(u"{self.window_title}||Window"):\n'
			               f'\twrapper = find(u"{self._relative(self._unique_path)}")\n\twrapper.draw_outline()\n')
			self.last_copy_time = time.time()

	def is_alive(self):
		return self.mode != 'Quit'

	def start_recording(self):
		time.sleep(0.6)
		self._clicks = []
		self.mode = 'Record'

	def stop_recording(self):
		script = '# encoding: utf-8\n\nfrom pywinauto_recorder.player import *\n\n'
		script += f'with UIPath(u"{self.window_title}||Window"):\n'
		script += ''.join(f'\tclick(u"{self._relative(path)}")\n' for path in self._clicks) or '\tpass\n'
		OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
		file_name = OUTPUT_FOLDER / ('recorded preview ' + time.strftime('%Y-%m-%d %H_%M_%S') + '.py')
		file_name.write_text(script, encoding='utf-8')
		pyperclip.copy(script)
		self.last_recorded_file = str(file_name)
		self.mode = 'Stop'
		return self.last_recorded_file

	def playback(self, str_code='', filename='', on_error=None):
		self.mode = 'Play'
		time.sleep(1.5)
		self.mode = 'Stop'
		if on_error and 'raise' in str_code:  # replay clipboard code containing "raise" to see the error box
			on_error('Traceback (most recent call last):\n  File "<clipboard>", line 1, in <module>\n'
			         'RuntimeError: simulated replay error\n')

	def quit(self):
		self.mode = 'Quit'


def add_sample_app_toggle(panel, sample_app):
	"""Adds a Preview section to the menu of the panel, to show or hide the sample app."""
	menu = panel.btn_menu.menu()
	menu.addSeparator()
	header = QWidgetAction(menu)
	header.setDefaultWidget(QLabel('PREVIEW', objectName='menu_header'))
	menu.addAction(header)
	action = QAction('Sample app', menu, checkable=True,
	                 toolTip='Show the sample app, whose elements the preview inspects and records')
	action.setChecked(sample_app.isVisible())
	action.toggled.connect(sample_app.setVisible)
	sample_app.visibility_changed.connect(action.setChecked)
	menu.addAction(action)


if __name__ == '__main__':
	get_application()
	sample_app = SampleApp()
	area = QGuiApplication.primaryScreen().availableGeometry()
	sample_app.move(area.center().x() - sample_app.width() // 2, area.top() + 220)
	sample_app.show()
	sys.exit(run_control_panel(FakeRecorder(sample_app), lambda panel: add_sample_app_toggle(panel, sample_app)))
