from pywinauto_recorder.core import path_separator, get_wrapper_path, get_entry, get_entry_list
from pywinauto import Desktop
from win32api import GetCursorPos
from time import sleep
from multiprocessing import Process, Event, Queue
from queue import Empty, Full
from pywinauto_recorder.recorder import _find_common_path

wrapper_old_info_tip = None
common_path_info_tip = ''
MAX_VALUE_LENGTH = 300


def _post(info_queue, info):
	"""Posts the information of the element under the cursor (None to hide it), dropping the oldest if nobody reads."""
	while True:
		try:
			info_queue.put_nowait(info)
			return
		except Full:
			try:
				info_queue.get_nowait()
			except Empty:
				pass


def _split_path(path):
	""":return: The [name, type] of each entry of an element path"""
	if path.startswith(path_separator):
		path = path[len(path_separator):]
	if not path:
		return []
	return [list(get_entry(entry)[:2]) for entry in get_entry_list(path)]


def _short(value):
	value = str(value)
	return value if len(value) <= MAX_VALUE_LENGTH else value[:MAX_VALUE_LENGTH] + '…'


def _element_properties(wrapper, str_name, str_type):
	""":return: The [label, value] of the properties worth knowing to write code using the element"""
	properties = [
		['process id', str(wrapper.element_info.process_id)],
		['native window handle', str(wrapper.element_info.handle)]]
	value = None
	try:
		if callable(getattr(wrapper, 'get_value', None)):
			value = wrapper.get_value()
			properties.append(['wrapper.get_value()', _short(value)])
	except Exception:
		value = None
	try:
		if callable(getattr(wrapper, 'legacy_properties', None)):
			legacy_value = wrapper.legacy_properties()['Value']
			if legacy_value and legacy_value != value:
				properties.append(["wrapper.legacy_properties()['Value']", _short(legacy_value)])
	except Exception:
		pass
	try:
		if str_type in ('Button', 'CheckBox', 'RadioButton', 'GroupBox'):
			properties.append(["wrapper.legacy_properties()['State']", str(wrapper.legacy_properties()['State'])])
			from pywinauto.controls.win32_controls import ButtonWrapper
			properties.append(['ButtonWrapper(wrapper).is_checked()', str(ButtonWrapper(wrapper).is_checked())])
		elif str_type == 'ComboBox':
			from pywinauto.controls.win32_controls import ComboBoxWrapper
			properties.append(['ComboBoxWrapper(wrapper).selected_text()', _short(ComboBoxWrapper(wrapper).selected_text())])
		elif str_type == 'Edit':
			text_block = str(wrapper.text_block())
			if text_block != str_name:
				properties.append(['wrapper.text_block()', _short(text_block)])
	except Exception:
		pass
	return properties


def _rectangle(wrapper):
	r = wrapper.rectangle()
	return [r.left, r.top, r.width(), r.height()]


def _display_info_tiptool(desktop, info_queue):
	"""
	Posts the information of the element under the cursor to the info box of the control panel, with its rectangle and
	the one of the parent it has in common with the previous element, which the control panel outlines.
	"""
	global wrapper_old_info_tip
	global common_path_info_tip

	x, y = GetCursorPos()
	wrapper = desktop.from_point(x, y)

	if wrapper is None:
		return

	common_path_info_tip = ''
	parent_wrapper = None
	if wrapper != wrapper_old_info_tip:
		if wrapper_old_info_tip:
			common_path_info_tip = _find_common_path(get_wrapper_path(wrapper), get_wrapper_path(wrapper_old_info_tip))
			if common_path_info_tip:
				parent_wrapper = wrapper.parent()
				while parent_wrapper and get_wrapper_path(parent_wrapper) != common_path_info_tip:
					parent_wrapper = parent_wrapper.parent()
		wrapper_old_info_tip = wrapper
	else:
		return

	end_path = get_wrapper_path(wrapper)[len(common_path_info_tip)::]
	element = _split_path(end_path)
	str_name, str_type = element[-1] if element else ('', None)
	_post(info_queue, {
		'context': _split_path(common_path_info_tip),
		'element': element,
		'properties': _element_properties(wrapper, str_name, str_type),
		'rectangle': _rectangle(wrapper),
		'parent_rectangle': _rectangle(parent_wrapper) if parent_wrapper else None})


def task(info_mode_event, info_mode_quit_event, info_queue):
	global wrapper_old_info_tip
	global common_path_info_tip
	info_queue.cancel_join_thread()  # exits even if the info posted last was never read
	desktop = Desktop(backend='uia', allow_magic_lookup=False)
	shown = False
	while not info_mode_quit_event.is_set():
		try:
			if info_mode_event.is_set():
				if not shown:
					# Posted again when shown, even if the cursor is still on the same element
					wrapper_old_info_tip = None
					shown = True
				_display_info_tiptool(desktop, info_queue)
			else:
				if shown:
					_post(info_queue, None)
					shown = False
			sleep(0.1)
		except Exception:
			wrapper_old_info_tip = None
			common_path_info_tip = ''
			if shown:
				_post(info_queue, None)
				shown = False
			sleep(2.0)
	_post(info_queue, None)


class ElementInfoTooltip:
	"""
	Finds the element under the cursor in a separate process, and posts its information to `queue` for the control
	panel: a dict with the 'context' path it shares with the previous element, its own 'element' path (both lists of
	[name, type]), its 'properties' (a list of [label, value]), and the 'rectangle' of the element and the
	'parent_rectangle' of that common parent (None if there is none), as [x, y, width, height] in screen pixels.
	None is posted when hidden.
	"""
	def __init__(self):
		self.info_mode_quit = Event()
		self.info_mode_quit.clear()
		self.info_mode = Event()
		self.info_mode.clear()
		self.queue = Queue(maxsize=16)
		self.process = Process(target=task, args=(self.info_mode, self.info_mode_quit, self.queue))
		self.process.start()

	def show(self):
		if not self.info_mode.is_set():
			self.info_mode.set()
			print("def show(self):")

	def hide(self):
		if self.info_mode.is_set():
			self.info_mode.clear()
			print("def hide(self):")

	def __del__(self):
		self.info_mode_quit.set()
		self.process.join()


if __name__ == '__main__':
	element_info_tooltip = ElementInfoTooltip()

	element_info_tooltip.show()
	print('\nMain process blocking', flush=True)
	sleep(88)

	element_info_tooltip.hide()
	print("\n2 seconds without displaying info tip")
	sleep(2)

	del element_info_tooltip
