"""This module contains functions and classes allowing to record a sequence of user actions.
All these functions and classes are private except the Recorder class.
"""

import sys
import os
import subprocess
import traceback
import time
import win32api
import win32con
from threading import Lock, Thread
from queue import Queue
import pywinauto
import keyboard
import mouse
from collections import namedtuple
import pyperclip
import codecs
import json
import ast
from datetime import datetime
import win32process
import win32gui
from pywinauto.uia_defines import get_elem_interface
from . import __version__
from .core import path_separator, type_separator, Strategy, is_int, \
                    get_wrapper_path_and_window, get_entry_list, get_entry, get_sorted_region, \
                    read_config_file
from .core import find_elements as not_ttl_cached_find_elements
#from .core import find_elements
from .player import playback
from cachetools import func


@func.ttl_cache(ttl=10)
def find_elements(full_element_path=None, window_handle=None):
    return not_ttl_cached_find_elements(full_element_path=full_element_path, window_handle=window_handle)


__all__ = ['Recorder']

# 'details' (an element dict of _get_element_details) and the positions and times are written in the JSON file only
ElementEvent = namedtuple('ElementEvent', ['strategy', 'rectangle', 'path', 'details'], defaults=(None,))
SendKeysEvent = namedtuple('SendKeysEvent', ['line', 'time'], defaults=(None,))
MouseWheelEvent = namedtuple('MouseWheelEvent', ['delta', 'time'], defaults=(None,))
DragAndDropEvent = namedtuple(
    'DragAndDropEvent', ['path', 'dx1', 'dy1', 'path2', 'dx2', 'dy2', 'time', 'x1', 'y1', 'x2', 'y2', 'details', 'details2'],
    defaults=(None,) * 7)
ClickEvent = namedtuple(
    'ClickEvent', ['button', 'click_count', 'path', 'dx', 'dy', 'time', 'x', 'y', 'details'], defaults=(None,) * 3)
FindEvent = namedtuple('FindEvent', ['path', 'dx', 'dy', 'time', 'details'], defaults=(None,))
MenuEvent = namedtuple('MenuEvent', ['path', 'menu_path', 'time', 'details'], defaults=(None, None))
NoteEvent = namedtuple('NoteEvent', ['text', 'time'], defaults=(None,))  # a note of the user, a comment in the script


def _escape_special_char(string):
    """
        Is called on all paths to remove all special characters but it's not good.
        Should be moved in core
        Should be called only in get_wrapper_path and unescape_special_char in get_entry
        and in script += 'menu_click... in menu_click as it's already done
        should replace -> by _>
    """
    for r in (("\\", "\\\\"), ("\t", "\\t"), ("\n", "\\n"), ("\r", "\\r"), ("\v", "\\v"), ("\f", "\\f"), ('"', '\\"')):
        string = string.replace(*r)
    return string


def _is_own_window_under_cursor():
    """
    :return: True if the window under the cursor is one of the recorder (its control panel, menu or dialogs). Fast
    enough for the mouse hook. The outlines and the information box let the mouse through, so Windows ignores them.
    """
    try:
        hwnd = win32gui.WindowFromPoint(win32api.GetCursorPos())
        return bool(hwnd) and win32process.GetWindowThreadProcessId(hwnd)[1] == os.getpid()
    except Exception:
        return False


def _describe_window_under_cursor():
    """:return: The process and the class of the window under the cursor, to tell where an error happens"""
    try:
        hwnd = win32gui.GetAncestor(win32gui.WindowFromPoint(win32api.GetCursorPos()), win32con.GA_ROOT)
        process_id = win32process.GetWindowThreadProcessId(hwnd)[1]
        return '{} ({}, "{}")'.format(_get_process_name(process_id) or 'process ' + str(process_id),
                                      win32gui.GetClassName(hwnd), win32gui.GetWindowText(hwnd))
    except Exception:
        return 'an unknown window'


_logged_errors = {}


def _log_loop_error(error):
    """
    Prints an error of the loop once (with its traceback) per kind of error and window, as the loop runs 10 times a
    second and the same error repeats as long as the cursor stays on the same window.
    """
    where = _describe_window_under_cursor()
    key = (type(error).__name__, str(getattr(error, 'hresult', None) or error)[:200], where)
    _logged_errors[key] = _logged_errors.get(key, 0) + 1
    if _logged_errors[key] > 1:
        return
    if getattr(error, 'hresult', None) == -2147024891:  # E_ACCESSDENIED
        message = ('Cannot inspect ' + where + ': access denied. Windows prevents a program from inspecting the '
                   'windows of a program run as administrator: run Pywinauto recorder as administrator to record it.')
    else:
        message = 'Error while identifying the element under the cursor, on ' + where + ':\n' + \
            ''.join(traceback.format_exception(type(error), error, error.__traceback__))
    try:
        print(message)
    except UnicodeEncodeError:  # a window title the console can't print
        print(message.encode('ascii', 'replace').decode('ascii'))


def _compute_dx_dy(x, y, rectangle):
    cx, cy = rectangle.mid_point()
    dx, dy = float(x - cx) / (rectangle.width() / 2 - 1), float(y - cy) / (rectangle.height() / 2 - 1)
    return (dx, dy)


# The UI Automation patterns written in the JSON file for each element, telling what can be done with it
_PATTERNS = ('Invoke', 'Value', 'Toggle', 'ExpandCollapse', 'SelectionItem', 'Selection', 'Grid', 'GridItem', 'Table',
             'Text', 'RangeValue', 'Scroll', 'Window')
_TOGGLE_STATES = {0: 'off', 1: 'on', 2: 'indeterminate'}
_EXPAND_COLLAPSE_STATES = {0: 'collapsed', 1: 'expanded', 2: 'partially_expanded', 3: 'leaf'}
_process_names = {}

# Written at the beginning of the JSON file, for the reader (e.g. an AI agent writing an automation script from it)
_JSON_ABOUT = {
    'description': 'User interface actions recorded by Pywinauto recorder with UI Automation, in the order the user did '
                   'them, with the properties of the elements they were done on.',
    'time': 'Seconds since the start of the recording.',
    'uipath': "Path of the element from its top-level window, used by pywinauto_recorder.player: 'Name||ControlType' "
              "entries joined by '->'. A last entry ending with '#[row,column]' picks the element among the elements "
              "having the same path by its position in their grid (see 'row_label' in 'element'). The player also "
              "accepts '#[reference path,column]': the element in the column of the row of the reference element.",
    'position': 'Screen pixels of the cursor.',
    'position_in_element_percent': 'Offset of the cursor from the center of the element, in % of its half width and '
                                   'half height.',
    'keys': 'Keys typed, in pywinauto send_keys syntax: {ENTER}, {TAB}, {VK_LCONTROL down}...; the typed characters '
            '^ % ~ { } are written {^} {%} {~} {{} {}}. Keys typed in an element with is_password true are a password.',
    'notes': 'Notes of the user about the whole recording, e.g. what it does and what changes from one run to another.',
    'note': "Note of the user: on an action, about that action; an action 'note' is a note between two actions, e.g. "
            "what to wait for before the next action. Notes are comments in the script.",
    'element': "UI Automation properties of the element when it was identified under the cursor; 'ancestors' are its "
               "parents from the top-level window, 'patterns' the UI Automation patterns it supports. For an element "
               "identified by its position ('#[row,column]'), 'row_label' is the unique element on its left on the same "
               "row (e.g. the label of a field, the first cell of a row): unlike the position, it stays the same when "
               "rows are added, removed or sorted; the player finds the element in that row with "
               "'#[row_label uipath,column]'.",
    'pywinauto_recorder_code': 'The action in pywinauto_recorder.player code.',
    'pywinauto_recorder_script': 'The whole recording as a pywinauto_recorder.player script, replayed by the Replay '
                                 'button of Pywinauto recorder.',
}


def _get_process_name(process_id):
    if process_id not in _process_names:
        try:
            handle = win32api.OpenProcess(0x1000, False, process_id)  # PROCESS_QUERY_LIMITED_INFORMATION
            try:
                _process_names[process_id] = os.path.basename(win32process.GetModuleFileNameEx(handle, 0))
            finally:
                win32api.CloseHandle(handle)
        except Exception:
            _process_names[process_id] = None
    return _process_names[process_id]


def _get_element_identity(element_info):
    """:return: The properties identifying an element (UIAElementInfo)"""
    return {
        'name': element_info.name, 'control_type': element_info.control_type,
        'automation_id': element_info.automation_id, 'class_name': element_info.class_name}


def _get_element_details(wrapper, strategy, path):
    """
    It reads the properties of an element written in the JSON file. It is slow (many cross-process calls), so it is
    called once per element.

    :param wrapper: The UIAWrapper of the element
    :param strategy: The Strategy used to identify the element
    :param path: The path identifying the element
    :return: A dict of the properties of the element, which can be converted to JSON
    """
    element_info = wrapper.element_info
    element = element_info.element
    details = {'uipath': path, 'identified_by': strategy.name}

    def add(key, read):
        try:
            value = read()
            if value is not None:
                details[key] = value
        except Exception:
            pass

    add('identity', lambda: _get_element_identity(element_info))
    details.update(details.pop('identity', {}))
    add('localized_control_type', lambda: element.CurrentLocalizedControlType)
    add('framework_id', lambda: element_info.framework_id)
    add('help_text', lambda: element.CurrentHelpText or None)
    add('access_key', lambda: element.CurrentAccessKey or None)
    add('is_enabled', lambda: bool(element.CurrentIsEnabled))
    add('is_keyboard_focusable', lambda: bool(element.CurrentIsKeyboardFocusable))
    add('is_password', lambda: bool(element.CurrentIsPassword))
    r = element_info.rectangle
    details['rectangle'] = {'left': r.left, 'top': r.top, 'right': r.right, 'bottom': r.bottom}
    add('process_id', lambda: element_info.process_id)
    add('process_name', lambda: _get_process_name(element_info.process_id))
    add('native_window_handle', lambda: element_info.handle)
    patterns = {}
    for name in _PATTERNS:
        try:
            patterns[name] = get_elem_interface(element, name)
        except Exception:
            pass
    details['patterns'] = list(patterns)
    if 'Value' in patterns and not details.get('is_password'):
        add('value', lambda: patterns['Value'].CurrentValue)
    if 'Toggle' in patterns:
        add('toggle_state', lambda: _TOGGLE_STATES.get(patterns['Toggle'].CurrentToggleState))
    if 'ExpandCollapse' in patterns:
        add('expand_collapse_state',
            lambda: _EXPAND_COLLAPSE_STATES.get(patterns['ExpandCollapse'].CurrentExpandCollapseState))
    if 'SelectionItem' in patterns:
        add('is_selected', lambda: bool(patterns['SelectionItem'].CurrentIsSelected))
    if 'GridItem' in patterns:
        add('grid_item', lambda: {'row': patterns['GridItem'].CurrentRow, 'column': patterns['GridItem'].CurrentColumn})
    if 'RangeValue' in patterns:
        add('range_value', lambda: patterns['RangeValue'].CurrentValue)

    def legacy_properties():
        properties = wrapper.legacy_properties()
        keys = ['Name', 'Description', 'Role', 'State', 'DefaultAction', 'KeyboardShortcut', 'Help']
        if not details.get('is_password'):
            keys.append('Value')
        return {key: properties[key] for key in keys if properties.get(key) not in (None, '')}

    add('legacy_properties', legacy_properties)

    def ancestors():
        chain = []
        parent = element_info.parent
        while parent is not None and parent.parent is not None:  # the desktop isn't written
            chain.append(_get_element_identity(parent))
            parent = parent.parent
        return list(reversed(chain))

    add('ancestors', ancestors)
    if strategy == Strategy.array_2D:
        add('row_label', lambda: _find_row_label(wrapper, path, get_wrapper_path_and_window(wrapper)[1]))
    return details


_ROW_LABEL_STEP = 9  # pixels between two points searched on the left of the element
_ROW_LABEL_MAX_STEPS = 150
_desktop = pywinauto.Desktop(backend='uia', allow_magic_lookup=False)
_row_labels = {}  # by (window handle, path without position, top, bottom): the elements of a row share their label


def _find_row_label(wrapper, path, window_handle):
    """
    It finds the unique element on the left of an element, on the same row: e.g. the label of an unnamed field, or the
    first cell of a row of a grid. Written in the JSON file for the elements identified by their position among the
    elements having the same path ('#[row,column]'): their position changes when rows are added, removed or sorted,
    their label doesn't.

    :param wrapper: The UIAWrapper of the element
    :param path: The path identifying the element, ending with '#[row,column]'
    :param window_handle: The native handle of its top-level window
    :return: The 'uipath', 'name' and 'control_type' of the label, or None if there is none
    """
    r = wrapper.element_info.rectangle
    i = path.rfind('#[')
    base_path = path[:i] if i > path.rfind(path_separator) else path
    key = (window_handle, base_path, r.top, r.bottom)
    if key in _row_labels:
        return _row_labels[key]
    try:
        window_left = win32gui.GetWindowRect(window_handle)[0] if window_handle else None
    except win32gui.error:
        window_left = None
    window_entry = get_entry_list(base_path)[0]
    x, y = r.left, (r.top + r.bottom) // 2
    label = None
    previous_path = None
    for _ in range(_ROW_LABEL_MAX_STEPS):
        x -= _ROW_LABEL_STEP
        if window_left is not None and x <= window_left:
            break
        element = _desktop.from_point(x, y)
        if element is None or element.rectangle().height() > r.height() * 2:
            continue  # nothing, or a container of the row rather than an element of it
        element_path, _ = get_wrapper_path_and_window(element)
        if not element_path or element_path in (previous_path, base_path):
            continue  # the same element as the previous point, or one of the elements having the same path
        previous_path = element_path
        if get_entry_list(element_path)[0] != window_entry:
            break  # out of the window
        if len(find_elements(element_path, window_handle)) == 1:
            info = element.element_info
            label = {'uipath': element_path, 'name': info.name, 'control_type': info.control_type}
            break
    if len(_row_labels) > 256:
        _row_labels.clear()
    _row_labels[key] = label
    return label


def _get_action_code(e_i, common_path='', relative_coordinate_mode=False):
    """
    :param e_i: The event of the action
    :param common_path: The path of the 'with UIPath' the code is in, '' for an absolute path
    :return: The pywinauto_recorder.player code of the action, without indentation
    """
    if isinstance(e_i, SendKeysEvent):
        return 'send_keys(' + e_i.line + ')\n'
    if isinstance(e_i, MouseWheelEvent):
        return 'mouse_wheel(' + str(e_i.delta) + ')\n'
    if isinstance(e_i, DragAndDropEvent):
        p1, p2 = e_i.path, e_i.path2
        dx1, dy1 = "{:.2f}".format(round(e_i.dx1 * 100, 2)), "{:.2f}".format(round(e_i.dy1 * 100, 2))
        dx2, dy2 = "{:.2f}".format(round(e_i.dx2 * 100, 2)), "{:.2f}".format(round(e_i.dy2 * 100, 2))
        if common_path:
            p1 = _get_relative_path(common_path, p1)
            p2 = _get_relative_path(common_path, p2)
        code = 'drag_and_drop(u"' + _escape_special_char(p1)
        if relative_coordinate_mode and eval(dx1) != 0 and eval(dy1) != 0:
            code += '%(' + dx1 + ',' + dy1 + ')'
        code += '", u"' + _escape_special_char(p2)
        if relative_coordinate_mode and eval(dx2) != 0 and eval(dy2) != 0:
            code += '%(' + dx2 + ',' + dy2 + ')'
        return code + '")\n'
    if isinstance(e_i, ClickEvent):
        p = e_i.path
        dx, dy = "{:.2f}".format(round(e_i.dx * 100, 2)), "{:.2f}".format(round(e_i.dy * 100, 2))
        if common_path:
            p = _get_relative_path(common_path, p)
        str_c = ['', '', 'double_', 'triple_']
        if e_i.button == 'left':
            code = str_c[e_i.click_count] + 'click(u"' + _escape_special_char(p)
        else:
            code = str_c[e_i.click_count] + e_i.button + '_click(u"' + _escape_special_char(p)
        if relative_coordinate_mode and eval(dx) != 0 and eval(dy) != 0:
            code += '%(' + dx + ',' + dy + ')'
        return code + '")\n'
    if isinstance(e_i, FindEvent):
        p = e_i.path
        dx, dy = "{:.2f}".format(round(e_i.dx * 100, 2)), "{:.2f}".format(round(e_i.dy * 100, 2))
        if common_path:
            p = _get_relative_path(common_path, p)
        code = 'wrapper = find(u"' + _escape_special_char(p)
        if relative_coordinate_mode and eval(dx) != 0 and eval(dy) != 0:
            code += '%(' + dx + ',' + dy + ')'
        return code + '")\n'
    if isinstance(e_i, MenuEvent):
        return 'menu_click(u"' + _escape_special_char(e_i.menu_path) + '")\n'
    if isinstance(e_i, NoteEvent):
        return ''.join('# ' + line + '\n' for line in (e_i.text or '').strip().splitlines())
    return ''


def _get_script(events, relative_coordinate_mode=False, notes=None):
    """
    :param notes: The notes on events, by index of event, written as comments above their code
    :return: The pywinauto_recorder.player script replaying the processed events
    """
    script = "# encoding: {}\n\n".format(sys.getdefaultencoding())
    script += "from pywinauto_recorder.player import *\n\n"
    common_path = ''
    common_window = ''
    common_region = ''
    i = 0
    while i < len(events):
        e_i = events[i]
        if type(e_i) in (DragAndDropEvent, ClickEvent, FindEvent, MenuEvent):
            if e_i.path != common_path:
                new_common_path = _find_new_common_path_in_next_user_events(events, i)
                if new_common_path != common_path:
                    common_path = new_common_path
                    entry_list = get_entry_list(common_path)
                    e_i_window = entry_list[0]
                    if e_i_window != common_window:
                        common_window = e_i_window
                        common_region = ''  # the region of the previous window, even if it has the same path
                        script +='\nwith UIPath(u"' + _escape_special_char(common_window) + '"):\n'
                    e_i_region = path_separator.join(entry_list[1:])
                    if e_i_region != common_region and e_i_region:
                        common_region = e_i_region
                        script += '\twith UIPath(u"' + _escape_special_char(common_region) + '"):\n'
                    else:
                        common_region = ''
        if type(e_i) in (SendKeysEvent, MouseWheelEvent, DragAndDropEvent, ClickEvent, FindEvent, MenuEvent, NoteEvent):
            indentation = '\t' * ((1 if common_window else 0) + (1 if common_window and common_region else 0))
            code = _get_action_code(e_i, common_path, relative_coordinate_mode)
            if notes and notes.get(i):
                code = _get_action_code(NoteEvent(notes[i]), common_path) + code
            for line in code.splitlines():
                script += indentation + line + '\n'
        i += 1
    return script


def _get_position(x, y, dx, dy):
    if x is None:
        return {}
    return {
        'position': {'x': x, 'y': y},
        'position_in_element_percent': {'dx': round(dx * 100, 2), 'dy': round(dy * 100, 2)}}


def _get_action(e_i, start_time, relative_coordinate_mode=False):
    """:return: The dict describing the action of a processed event in the JSON file, or None if it isn't an action"""
    if isinstance(e_i, ClickEvent):
        action = {'action': 'click', 'button': e_i.button, 'click_count': e_i.click_count}
        action.update(_get_position(e_i.x, e_i.y, e_i.dx, e_i.dy))
        action.update({'uipath': e_i.path, 'element': e_i.details})
    elif isinstance(e_i, SendKeysEvent):
        action = {'action': 'send_keys', 'keys': ast.literal_eval(e_i.line)}
    elif isinstance(e_i, MouseWheelEvent):
        action = {'action': 'mouse_wheel', 'delta': e_i.delta}
    elif isinstance(e_i, DragAndDropEvent):
        start = _get_position(e_i.x1, e_i.y1, e_i.dx1, e_i.dy1)
        start.update({'uipath': e_i.path, 'element': e_i.details})
        end = _get_position(e_i.x2, e_i.y2, e_i.dx2, e_i.dy2)
        end.update({'uipath': e_i.path2, 'element': e_i.details2})
        action = {'action': 'drag_and_drop', 'from': start, 'to': end}
    elif isinstance(e_i, FindEvent):
        action = {'action': 'find', 'uipath': e_i.path, 'element': e_i.details}
    elif isinstance(e_i, MenuEvent):
        action = {'action': 'menu_click', 'menu_path': e_i.menu_path, 'window': e_i.path, 'elements': e_i.details}
    elif isinstance(e_i, NoteEvent):
        action = {'action': 'note', 'note': e_i.text}
    else:
        return None
    if getattr(e_i, 'time', None) is not None:
        action = dict(time=round(e_i.time - start_time, 3), **action)
    code = _get_action_code(e_i, '', relative_coordinate_mode)
    if isinstance(e_i, MenuEvent):
        code = 'with UIPath(u"' + _escape_special_char(e_i.path) + '"):\n\t' + code
    action['pywinauto_recorder_code'] = code.rstrip('\n')
    return action


def _get_event(action):
    """:return: The processed event of an action of the JSON file (the reverse of _get_action), or None"""
    def offset(position):
        percent = position.get('position_in_element_percent') or {}
        return percent.get('dx', 0) / 100, percent.get('dy', 0) / 100

    kind = action.get('action')
    if kind == 'click':
        dx, dy = offset(action)
        return ClickEvent(action.get('button', 'left'), action.get('click_count', 1), action['uipath'], dx, dy, None)
    if kind == 'send_keys':
        return SendKeysEvent('"' + _escape_special_char(action['keys']) + '"', None)
    if kind == 'mouse_wheel':
        return MouseWheelEvent(action['delta'], None)
    if kind == 'drag_and_drop':
        start, end = action['from'], action['to']
        return DragAndDropEvent(start['uipath'], *offset(start), end['uipath'], *offset(end), None)
    if kind == 'find':
        return FindEvent(action['uipath'], 0, 0, None)
    if kind == 'menu_click':
        return MenuEvent(action['window'], action['menu_path'], None)
    if kind == 'note':
        return NoteEvent(action.get('note', ''))
    return None


def get_action_code(action, relative_coordinate_mode=False):
    """:return: The pywinauto_recorder.player code of an action of the JSON file, with its absolute path"""
    event = _get_event(action)
    if event is None:
        return ''
    code = _get_action_code(event, '', relative_coordinate_mode)
    if isinstance(event, MenuEvent):
        code = 'with UIPath(u"' + _escape_special_char(event.path) + '"):\n\t' + code
    return code.rstrip('\n')


def get_script(actions, relative_coordinate_mode=False):
    """
    :param actions: The actions of the JSON file, possibly edited
    :return: The pywinauto_recorder.player script replaying them, with their notes as comments
    """
    events = []
    notes = {}
    for action in actions:
        event = _get_event(action)
        if event is not None:
            if not isinstance(event, NoteEvent) and (action.get('note') or '').strip():
                notes[len(events)] = action['note']
            events.append(event)
    return _get_script(events, relative_coordinate_mode, notes)


def update_recording(recording):
    """
    It writes again the code of the actions and the script of a recording whose actions were edited.

    :param recording: The dict of a JSON file of the recorder
    """
    relative_coordinate_mode = (recording.get('options') or {}).get('relative_coordinate_mode', False)
    for action in recording.get('actions', []):
        action['pywinauto_recorder_code'] = get_action_code(action, relative_coordinate_mode)
    recording['pywinauto_recorder_script'] = get_script(recording.get('actions', []), relative_coordinate_mode)


def _write_in_file(events, relative_coordinate_mode=False, start_time=None):
    """
    It writes the recording in a JSON file, with the properties of the elements and the pywinauto_recorder script
    replaying it, and copies the JSON to the clipboard.

    :return: The path of the JSON file
    """
    from pathlib import Path
    home_dir = Path.home() / 'Pywinauto recorder'
    home_dir.mkdir(parents=True, exist_ok=True)
    record_file_name = home_dir / Path('recorded ' + time.asctime().replace(':', '_') + '.json')
    print('Recording in file: ' + str(record_file_name.absolute()))
    if start_time is None:
        start_time = time.time()
    actions = [a for a in (_get_action(e, start_time, relative_coordinate_mode) for e in events) if a is not None]
    recording = {
        'about': _JSON_ABOUT,
        'recorder_version': __version__,
        'recorded_at': datetime.fromtimestamp(start_time).astimezone().isoformat(timespec='seconds'),
        'screen': {'width': win32api.GetSystemMetrics(0), 'height': win32api.GetSystemMetrics(1)},
        'options': {'relative_coordinate_mode': relative_coordinate_mode},
        'actions': actions,
        # From the actions, like the script of an edited recording
        'pywinauto_recorder_script': get_script(actions, relative_coordinate_mode),
    }
    text = json.dumps(recording, indent='\t', ensure_ascii=False, default=str)
    with codecs.open(record_file_name, "w", encoding='utf-8') as f:
        f.write(text)
    pyperclip.copy(text)
    return record_file_name


def _clean_events(events, remove_first_up=False):
    """"
    removes duplicate or useless events
    removes all the last down events due or not to (CRTL+ALT+r) when ending record mode
    :param remove_first_up: when True, removes the 2 first up events due to (CRTL+ALT+r) when starting record mode
    :param events: the copy of recorded event list
    """
    if remove_first_up:
        i = 0
        i_up = 0
        while i < len(events):
            if isinstance(events[i], keyboard.KeyboardEvent) and events[i].event_type == 'up':
                i_up = i_up + 1
                events.pop(i)
                if i_up == 2:
                    break
            else:
                i = i + 1
    i = 0
    previous_event_type = None
    while i < len(events):
        if type(events[i]) is previous_event_type:
            if type(events[i]) in (ElementEvent, mouse.MoveEvent):
                del events[i - 1]
            else:
                previous_event_type = type(events[i])
                i = i + 1
        else:
            previous_event_type = type(events[i])
            i = i + 1
    i = len(events) - 1
    while i > 0:
        if isinstance(events[i], keyboard.KeyboardEvent) and events[i].event_type == 'down':
            events.pop(i)
        elif isinstance(events[i], keyboard.KeyboardEvent) and events[i].event_type == 'up':
            break
        i = i - 1


def _process_events(events, process_menu_click=True):
    i = 0
    while i < len(events):
        if isinstance(events[i], keyboard.KeyboardEvent):
            _process_keyboard_events(events, i)
        elif isinstance(events[i], mouse.WheelEvent):
            _process_wheel_events(events, i)
        i = i + 1
    i = len(events) - 1
    while i >= 0:
        if isinstance(events[i], mouse.ButtonEvent) and events[i].event_type == 'up':
            i = _process_drag_and_drop_or_click_events(events, i)
        i = i - 1
    if process_menu_click:
        i = len(events) - 1
        while i >= 0:
            if isinstance(events[i], ClickEvent):
                i = _process_menu_select_events(events, i)
            i = i - 1


def _process_keyboard_events(events, i):
    keyboard_events = [events[i]]
    i0 = i + 1
    i_processed_events = []
    while i0 < len(events):
        if isinstance(events[i0], keyboard.KeyboardEvent):
            keyboard_events.append(events[i0])
            i_processed_events.append(i0)
            i0 = i0 + 1
        elif isinstance(events[i0], ElementEvent):
            i0 = i0 + 1
        else:
            break
    line = _get_send_keys_strings(keyboard_events)
    for i_p_e in sorted(i_processed_events, reverse=True):
        del events[i_p_e]
    if line:
        events[i] = SendKeysEvent(line=line, time=keyboard_events[0].time)


def _process_wheel_events(events, i):
    delta = events[i].delta
    i_processed_events = []
    i0 = i + 1
    while i0 < len(events):
        if isinstance(events[i0], mouse.WheelEvent):
            delta = delta + events[i0].delta
            i_processed_events.append(i0)
            i0 = i0 + 1
        elif type(events[i0]) in (ElementEvent, mouse.MoveEvent):
            i0 = i0 + 1
        else:
            break
    for i_p_e in sorted(i_processed_events, reverse=True):
        del events[i_p_e]
    events[i] = MouseWheelEvent(delta=delta, time=events[i].time)


def _process_drag_and_drop_or_click_events(events, i):
    # A click whose element or press wasn't recorded (e.g. no element identified yet, an ElementEvent without path) is
    # left unprocessed; _write_in_file ignores raw mouse events.
    element_event_before_button_up = None
    move_event_end = None
    i0 = i - 1
    while i0 >= 0:
        if isinstance(events[i0], ElementEvent):
            element_event_before_button_up = events[i0]
            break
        i0 = i0 - 1
    while i0 >= 0:
        if isinstance(events[i0], mouse.MoveEvent):
            move_event_end = events[i0]
            break
        i0 = i0 - 1
    if element_event_before_button_up is None or element_event_before_button_up.path is None or move_event_end is None:
        return i
    i0 = i - 1
    click_count = 0
    i1 = None
    while i0 >= 0:
        if isinstance(events[i0], mouse.ButtonEvent) and events[i0].event_type in ('down', 'double'):
            click_count = click_count + 1
            if events[i0].event_type == 'down' or click_count == 3:
                i1 = i0
                break
        i0 = i0 - 1
    if i1 is None:
        return i
    # Where the cursor was when the button went down and up: like Windows, it is a drag and drop only if the mouse moved
    # further than the drag threshold in between
    down_move = next((e for e in reversed(events[:i1]) if isinstance(e, mouse.MoveEvent)), move_event_end)
    up_move = next((e for e in reversed(events[i1:i]) if isinstance(e, mouse.MoveEvent)), down_move)
    drag_dx, drag_dy = win32api.GetSystemMetrics(68), win32api.GetSystemMetrics(69)  # SM_CXDRAG, SM_CYDRAG
    drag_and_drop = abs(up_move.x - down_move.x) > drag_dx or abs(up_move.y - down_move.y) > drag_dy
    element_event_before_button_down = None
    while i0 >= 0:
        if isinstance(events[i0], ElementEvent):
            element_event_before_button_down = events[i0]
            break
        i0 = i0 - 1
    if element_event_before_button_down is None or element_event_before_button_down.path is None:
        return i
    if drag_and_drop:
        dx1, dy1 = _compute_dx_dy(down_move.x, down_move.y, element_event_before_button_down.rectangle)
        dx2, dy2 = _compute_dx_dy(up_move.x, up_move.y, element_event_before_button_up.rectangle)
        events[i] = DragAndDropEvent(
            path=element_event_before_button_down.path, dx1=dx1, dy1=dy1,
            path2=element_event_before_button_up.path, dx2=dx2, dy2=dy2, time=events[i1].time,
            x1=down_move.x, y1=down_move.y, x2=up_move.x, y2=up_move.y,
            details=element_event_before_button_down.details, details2=element_event_before_button_up.details)
    else:
        up_event = events[i]
        dx, dy = _compute_dx_dy(down_move.x, down_move.y, element_event_before_button_down.rectangle)
        events[i] = ClickEvent(
            button=up_event.button, click_count=click_count,
            path=element_event_before_button_down.path, dx=dx, dy=dy, time=up_event.time,
            x=down_move.x, y=down_move.y, details=element_event_before_button_down.details)
    i_processed_events = []
    i0 = i - 1
    while i0 >= i1:
        if type(events[i0]) in (mouse.ButtonEvent, mouse.MoveEvent, ElementEvent):
            i_processed_events.append(i0)
        i0 = i0 - 1
    for i_p_e in sorted(i_processed_events, reverse=True):
        del events[i_p_e]
        i = i - 1
    return i


def _get_relative_path(common_path, path):
    if not path:
        return ''
    # TODO: check if common_path is the beginning of path
    path = path[len(common_path) + len(path_separator):]
    entry_list = get_entry_list(path)
    str_name, str_type, y_x, dx_dy = get_entry(entry_list[-1])
    if (y_x is not None) and not is_int(y_x[0]):
        y_x[0] = y_x[0][len(common_path) + 2:]
        path = path_separator.join(entry_list[:-1]) + path_separator + str_name
        if path == path_separator:
            path = ''
        path = path + type_separator + str_type + "#[" + y_x[0] + "," + str(y_x[1]) + "]"
        if dx_dy is not None and dx_dy[0] != 0 and dx_dy[1] != 0:
            path = path + "%(" + str(dx_dy[0]) + "," + str(dx_dy[1]) + ")"
    return path


def _find_common_path(current_path, next_path):
    current_entry_list = get_entry_list(current_path)
    if len(current_entry_list) > 1:
        _, _, y_x, _ = get_entry(current_entry_list[-1])
        if (y_x is not None) and not is_int(y_x[0]):
            current_entry_list = get_entry_list(y_x[0])[:-1]
        else:
            current_entry_list = current_entry_list[:-1]
    next_entry_list = get_entry_list(next_path)
    if len(next_entry_list)>1:
        next_entry_list = next_entry_list[:-1]
    n = 0
    try:
        while current_entry_list[n] == next_entry_list[n]:
            n = n + 1
    except IndexError:
        common_path = path_separator.join(current_entry_list[0:n])
        return common_path
    common_path = path_separator.join(current_entry_list[0:n])
    return common_path


def _find_new_common_path_in_next_user_events(events, i):
    path_i = events[i].path
    i0 = i + 1
    new_common_path = ''
    while i0 < len(events):
        e = events[i0]
        if type(e) in (DragAndDropEvent, ClickEvent, FindEvent, MenuEvent):
            new_common_path = _find_common_path(path_i, e.path)
            break
        elif type(e) in (ElementEvent, mouse.MoveEvent, NoteEvent):
            i0 = i0 + 1
        else:
            break
    if new_common_path == '':
        new_common_path = _find_common_path(path_i, path_i)
    return new_common_path


def _process_menu_select_events(events, i):
    i0 = i
    i_processed_events = []
    menu_path = []
    menu_details = []
    while i0 >= 0:
        if isinstance(events[i0], ClickEvent):
            entry_list = get_entry_list(events[i0].path)
            matching = [s for s in entry_list if "||MenuItem" in s]
            if matching:
                str_name, _, _, _ = get_entry(matching[0])
                menu_path.append(str_name)
                menu_details.append(events[i0].details)
                i_processed_events.append(i0)
                if [s for s in entry_list if "||MenuBar" in s]:
                    break
            else:
                break
        i0 -= 1
    if menu_path:
        menu_path = path_separator.join(reversed(menu_path))
        i_menu_bar = i_processed_events.pop()
        menu_bar_path = get_entry_list(events[i_menu_bar].path)[0]
        events[i_menu_bar] = MenuEvent(
            path=menu_bar_path, menu_path=menu_path, time=events[i_menu_bar].time, details=list(reversed(menu_details)))
        for i_p_e in sorted(i_processed_events, reverse=True):
            del events[i_p_e]
            i -= 1
    return i


# The names of the keys given by the keyboard module, and their pywinauto send_keys codes
_SEND_KEYS_CODES = {
    'enter': 'ENTER', 'tab': 'TAB', 'esc': 'ESC', 'backspace': 'BACKSPACE', 'delete': 'DELETE', 'insert': 'INSERT',
    'home': 'HOME', 'end': 'END', 'page up': 'PGUP', 'page down': 'PGDN',
    'up': 'UP', 'down': 'DOWN', 'left': 'LEFT', 'right': 'RIGHT',
    'print screen': 'PRTSC', 'num lock': 'NUMLOCK', 'scroll lock': 'SCROLLLOCK', 'menu': 'VK_APPS'}
_SEND_KEYS_CODES.update(('f' + str(n), 'F' + str(n)) for n in range(1, 25))

# The modifiers which make a shortcut with the next key, by name of the key, and their pywinauto send_keys codes
_SHORTCUT_MODIFIER_CODES = {
    'ctrl': 'VK_LCONTROL', 'left ctrl': 'VK_LCONTROL', 'right ctrl': 'VK_RCONTROL',
    'alt': 'VK_LMENU', 'left alt': 'VK_LMENU', 'right alt': 'VK_RMENU',
    'windows': 'VK_LWIN', 'left windows': 'VK_LWIN', 'right windows': 'VK_RWIN'}

# The modifiers which are typed when they are pressed and released alone, such as the Windows key opening the start menu
_ALONE_MODIFIER_CODES = {
    'alt': 'VK_LMENU', 'left alt': 'VK_LMENU',
    'windows': 'LWIN', 'left windows': 'LWIN', 'right windows': 'RWIN'}


def _escape_send_keys_char(char):
    """
    Escapes the characters having a meaning in pywinauto send_keys. '+', '(' and ')' are left as they are because
    player.send_keys escapes them.
    """
    return '{' + char + '}' if char in '^%~{}' else char


def _get_send_keys_strings(keyboard_events):
    """
    It converts the keyboard events into the string literal given to send_keys in the recorded script.
    The keyboard module names the printable keys after the character they type, with shift and caps lock applied, so
    only the shortcuts made with ctrl, alt or windows need the modifiers to be pressed when replaying.

    :param keyboard_events: The keyboard.KeyboardEvent list
    :return: The string literal, or '' if no key is typed.
    """
    keys = []  # A key or a typed character per item, so that backspace can remove the last typed character
    pressed_modifiers = []
    modifier_used = False
    for event in keyboard_events:
        name = event.name.replace('windows gauche', 'left windows').replace('windows droite', 'right windows')
        if name in _SHORTCUT_MODIFIER_CODES or 'shift' in name or name == 'alt gr':
            if event.event_type == 'down':
                if name not in pressed_modifiers:
                    pressed_modifiers.append(name)
                    modifier_used = False
            elif name in pressed_modifiers:
                pressed_modifiers.remove(name)
                if not modifier_used and name in _ALONE_MODIFIER_CODES:
                    keys.append('{' + _ALONE_MODIFIER_CODES[name] + '}')
                modifier_used = True
            continue
        if event.event_type != 'down':
            continue
        modifier_used = True
        if name == 'space':
            key = ' '
        elif len(name) == 1:
            key = name
        elif name in _SEND_KEYS_CODES:
            key = '{' + _SEND_KEYS_CODES[name] + '}'
        else:
            print("Warning: the key '" + name + "' is not recorded.")
            continue
        shortcut_modifiers = [_SHORTCUT_MODIFIER_CODES[m] for m in pressed_modifiers if m in _SHORTCUT_MODIFIER_CODES]
        if 'alt gr' in pressed_modifiers and len(key) == 1:
            shortcut_modifiers = []  # alt gr types a character, that the name of the key already is
        if shortcut_modifiers:
            if any('shift' in m for m in pressed_modifiers):
                shortcut_modifiers.append('VK_SHIFT')
            if len(key) == 1:
                key = _escape_send_keys_char(key.lower())
            keys.append(
                ''.join('{' + m + ' down}' for m in shortcut_modifiers) + key +
                ''.join('{' + m + ' up}' for m in reversed(shortcut_modifiers)))
        elif key == '{BACKSPACE}' and keys and len(keys[-1]) == 1:
            keys.pop()
        else:
            keys.append(_escape_send_keys_char(key) if len(key) == 1 else key)
    if not keys:
        return ''
    return '"' + _escape_special_char(''.join(keys)) + '"'


class Highlights(object):
    """
    The rectangles outlining the elements under the cursor, drawn by the control panel. The recorder fills them
    between clear_all() and refresh(); get() returns the ones of the last refresh(), as (kind, x, y, width, height)
    in screen pixels, where kind is 'unique', 'ambiguous' or 'selected'.
    """
    def __init__(self):
        self._lock = Lock()
        self._pending = []
        self._shown = ()

    def clear_all(self):
        with self._lock:
            self._pending = []

    def add(self, kind, rectangle):
        r = rectangle
        with self._lock:
            self._pending.append((kind, r.left, r.top, r.width(), r.height()))

    def refresh(self):
        with self._lock:
            self._shown = tuple(self._pending)

    def get(self):
        with self._lock:
            return self._shown

    def quit(self):
        self.clear_all()
        self.refresh()


class Recorder(Thread):
    """
    Recorder is a class thread used to record UI events in clipboard or in a file.

    .. code-block:: python
        :caption: Example of code using 'Recorder'::
        
        from pywinauto_recorder.recorder import Recorder
        from pywinauto_recorder.player import UIPath, click, move, playback

        recorder = Recorder()
        recorder.start_recording()
        with UIPath("Untitled - Notepad||Window"):
            doc = move("Text editor||Document")
            time.sleep(0.5)
            click(doc)
            utf8 = move("||Pane-> UTF-8||Text")
            time.sleep(0.5)
            click(utf8)
        recorded_python_script = recorder.stop_recording()
        recorder.quit()
        playback(filename=recorded_python_script)

    The above code clicks on the text field and then on 'utf8'.
    All these events are recorded in a file. Then the file is replayed.
    """
    def __init__(self):
        from .element_observer import ElementInfoTooltip
        Thread.__init__(self)
        from win32api import GetSystemMetrics
        self._loop_t0 = None
        self._window_handle = None
        self.screen_width = GetSystemMetrics(0)
        self.screen_height = GetSystemMetrics(1)
        self.highlights = Highlights()
        self.desktop = pywinauto.Desktop(backend='uia', allow_magic_lookup=False)
        self.daemon = True
        self.event_list = []
        self._events_lock = Lock()  # held to change event_list, which several threads change
        self.last_copy_time = None
        self.last_recorded_file = None
        self._cursor_on_own_window = False
        self._mode = "Initializing"
        self._process_menu_click_mode = False
        self._relative_coordinate_mode = False
        self.wrapper_old_info_tip = None
        self.common_path_info_tip = ""
        self.last_element_event = None
        self.started_recording_with_keyboard = False
        self.recorded_action_count = 0
        self.last_recorded_action = None  # (time, recorded, description) of the last click or key, for the status
        self._clicked_element_event = None
        self._details_key = None
        self._details = {}
        self._details_requested = False
        # The properties of the elements are read in another thread, as reading them in the loop would delay the
        # identification of the next element under the cursor
        self._details_queue = Queue()
        Thread(target=self.__read_element_details, daemon=True).start()
        self._click_queue = Queue()
        Thread(target=self.__identify_clicked_elements, daemon=True).start()
        self._recording_start_time = None
        self._overlay_warned = False
        # While the control panel asks for a note (CTRL+ALT+N), the keys typed in it aren't recorded
        self.note_pending = False
        self._note_time = None
        self._ignored_key_ups = set()  # the keys of the shortcut, released after it
        self.element_info_tooltip = ElementInfoTooltip()
        self.start()
    
    def __warn_if_overlay(self, wrapper):
        """
        The outlines and the information box let the mouse through: if Windows finds them under the cursor instead of
        the element below them, nothing can be inspected nor recorded where they are.

        :param wrapper: The element of the recorder found under the cursor
        """
        if self._overlay_warned:
            return
        try:
            title = win32gui.GetWindowText(get_wrapper_path_and_window(wrapper)[1] or 0)
        except Exception:
            return
        if title.startswith('Pywinauto recorder ') and title != 'Pywinauto recorder':
            self._overlay_warned = True
            print('Warning: UI Automation finds the window "' + title + '" under the cursor instead of the element '
                  'below it. Please report it: elements can\'t be inspected nor recorded under this window.')

    def __highlight(self, wrapper_rectangle, kind):
        self.highlights.add(kind, wrapper_rectangle)
        
    def __find_unique_element_array_2d(self, wrapper_rectangle, elements):
        nb_y, nb_x, candidates = get_sorted_region(elements)
        unique_array_2d = ''
        for r_y in range(nb_y):
            for r_x in range(nb_x):
                try:
                    r = candidates[r_y][r_x].rectangle()
                except IndexError:
                    continue
                if r == wrapper_rectangle:
                    self.__highlight(r, 'selected')
                    unique_array_2d = '#[' + str(r_y) + ',' + str(r_x) + ']'
                else:
                    self.__highlight(r, 'ambiguous')
        return unique_array_2d

    def __mouse_on(self, mouse_event):
        if self.mode == "Record":
            if isinstance(mouse_event, (mouse.ButtonEvent, mouse.WheelEvent)) and _is_own_window_under_cursor():
                return  # a click on the control panel of the recorder is not a user action to record
            if isinstance(mouse_event, mouse.ButtonEvent) and mouse_event.event_type in ('down', 'double'):
                self._clicked_element_event = self.__element_event_under_cursor()
                if self._clicked_element_event is None:
                    # The loop hasn't identified the element under the cursor yet: it is identified at the position of
                    # the click in another thread, and replaces this placeholder
                    placeholder = ElementEvent(strategy=None, rectangle=None, path=None, details={})
                    self.__add_event(placeholder)
                    self._click_queue.put((placeholder, win32api.GetCursorPos(), mouse_event.button))
            with self._events_lock:
                # Replaced in place: copying the list on each move slows the hook down as the recording grows.
                if isinstance(mouse_event, mouse.MoveEvent) and self.event_list and \
                        isinstance(self.event_list[-1], mouse.MoveEvent):
                    self.event_list[-1] = mouse_event
                else:
                    self.event_list.append(mouse_event)
            if isinstance(mouse_event, mouse.ButtonEvent) and mouse_event.event_type == 'up' and \
                    self._clicked_element_event is not None:
                self.__report_click(mouse_event.button, self._clicked_element_event)

    def __add_event(self, event):
        """Appends an event to event_list, which the hooks, the loop and the click thread change concurrently."""
        with self._events_lock:
            self.event_list.append(event)

    def __element_event_under_cursor(self):
        """
        :return: The last element identified, if it is still under the cursor, else None. Called by the mouse hook, so
        it must be fast.
        """
        x, y = win32api.GetCursorPos()
        for event in reversed(self.event_list):
            if isinstance(event, ElementEvent):
                r = event.rectangle
                if r is not None and r.left <= x <= r.right and r.top <= y <= r.bottom:
                    return event
                return None
        return None

    def __report_click(self, button, element_event):
        """Tells the control panel that a click is recorded, or missed if element_event is None."""
        if element_event is None:
            self.last_recorded_action = (time.time(), False, 'Click missed: no element found under the cursor')
            return
        name, str_type, _, _ = get_entry(get_entry_list(element_event.path)[-1])
        self.recorded_action_count += 1
        click = 'Click' if button == 'left' else button.capitalize() + ' click'
        self.last_recorded_action = (time.time(), True, click + ' on ' + (name or str_type))

    def __identify_element_at(self, x, y):
        """
        It identifies the element at a position like the loop does, with its path, and with its position among the
        elements having the same path if it isn't unique.

        :return: The ElementEvent of the element, or None if there is no element to record there.
        """
        wrapper = self.desktop.from_point(x, y)
        if wrapper is None or wrapper.process_id() == os.getpid():
            return None
        # Read before searching, as the click may change the user interface
        path, window_handle = get_wrapper_path_and_window(wrapper)
        rectangle = wrapper.rectangle()
        if not path:
            return None
        strategy = Strategy.unique_path
        elements = find_elements(path, window_handle)
        if len(elements) > 1:
            _, _, candidates = get_sorted_region(elements)
            for r_y, row in enumerate(candidates):
                for r_x, candidate in enumerate(row):
                    if candidate.rectangle() == rectangle:
                        path, strategy = path + '#[' + str(r_y) + ',' + str(r_x) + ']', Strategy.array_2D
        details = {}
        self._details_queue.put((wrapper, strategy, path, details))
        return ElementEvent(strategy, rectangle, path, details)

    def __identify_clicked_elements(self):
        """
        Identifies the elements clicked before the loop identified them, put in the queue by the mouse hook with the
        placeholder event they replace, until None is put.
        """
        while True:
            item = self._click_queue.get()
            try:
                if item is None:
                    return
                placeholder, (x, y), button = item
                try:
                    element_event = self.__identify_element_at(x, y)
                except Exception:
                    traceback.print_exc()
                    element_event = None
                if element_event is not None:
                    with self._events_lock:
                        for i in range(len(self.event_list) - 1, -1, -1):
                            if self.event_list[i] is placeholder:
                                self.event_list[i] = element_event
                                break
                self.__report_click(button, element_event)
            finally:
                self._click_queue.task_done()

    def __wait_for_queue(self, queue, timeout=10):
        """Waits for the items put in a queue to be processed."""
        deadline = time.time() + timeout
        while queue.unfinished_tasks and time.time() < deadline:
            time.sleep(0.05)

    def __read_element_details(self):
        """Fills the details of the elements put in the queue by the loop, until None is put."""
        while True:
            item = self._details_queue.get()
            try:
                if item is None:
                    return
                wrapper, strategy, path, details = item
                details.update(_get_element_details(wrapper, strategy, path))
            except Exception:
                traceback.print_exc()
            finally:
                self._details_queue.task_done()

    def __start_stop_recording_by_key(self):
        if self.mode != "Record":
            self.started_recording_with_keyboard = True
            self.start_recording()
        else:
            self.stop_recording()
    
    def __start_stop_displaying_info_by_key(self):
        if self.mode == "Info":
            self.mode = "Stop"
        else:
            self.mode = "Info"
            
    def __display_found_elemenet_by_key(self):
        if self.last_element_event:
            x, y = win32api.GetCursorPos()
            l_e_e = self.last_element_event
            dx, dy = _compute_dx_dy(x, y, l_e_e.rectangle)
            str_dx, str_dy = "{:.2f}".format(round(dx * 100, 2)), "{:.2f}".format(round(dy * 100, 2))
            i = l_e_e.path.find(path_separator)
            window_title = l_e_e.path[0:i]
            # element_path = l_e_e.path[i+len(path_separator):]
            p = _get_relative_path(window_title, l_e_e.path)
            code = 'with UIPath(u"' + _escape_special_char(window_title) + '"):\n'
            code += '\twrapper = find(u"' + _escape_special_char(p)
            if self.relative_coordinate_mode and eval(str_dx) != 0 and eval(str_dy) != 0:
                code += '%(' + str_dx + ',' + str_dy + ')'
            code += '")\n'
            code += '\twrapper.draw_outline()\n'
            pyperclip.copy(code)
            self.last_copy_time = time.time()
            if self.event_list and self.mode == "Record":
                self.__add_event(FindEvent(path=l_e_e.path, dx=dx, dy=dy, time=time.time(), details=l_e_e.details))
                
    def __remove_shortcut_keys(self, e):
        """Removes the keys pressed for a shortcut (e: the release of its last key) from the recorded events."""
        pressed = set(keyboard._pressed_events) | {e.scan_code}
        with self._events_lock:
            for i in range(len(self.event_list) - 1, -1, -1):
                event = self.event_list[i]
                if isinstance(event, keyboard.KeyboardEvent):
                    if event.event_type != 'down' or event.scan_code not in pressed:
                        break
                    del self.event_list[i]
        self._ignored_key_ups = pressed - {e.scan_code}

    def request_note(self):
        """Asks the control panel for a note, added at this point of the recording by add_note()."""
        if self.mode == "Record" and not self.note_pending:
            self._note_time = time.time()
            self.note_pending = True

    def add_note(self, text):
        """
        It records a note of the user, written in the JSON file and as a comment in the script.

        :param text: The note, or None if the user canceled it
        """
        if self.note_pending and self.mode == "Record" and text and text.strip():
            self.__add_event(NoteEvent(text.strip(), self._note_time))
            self.last_recorded_action = (time.time(), True, 'Note added')
        self.note_pending = False

    def __key_on(self, e):
        key_to_scan_codes = keyboard.key_to_scan_codes
        if (
                (e.name, e.event_type) == ('r', 'up') and
                set([key_to_scan_codes("alt")[0], key_to_scan_codes("ctrl")[0]]).issubset(keyboard._pressed_events)):
            self.__start_stop_recording_by_key()
        elif (
                (e.name, e.event_type) == ('n', 'up') and self.mode == "Record" and
                set([key_to_scan_codes("alt")[0], key_to_scan_codes("ctrl")[0]]).issubset(keyboard._pressed_events)):
            self.__remove_shortcut_keys(e)
            self.request_note()
        elif (
                (e.name, e.event_type) == ('F', 'up') and
                set([key_to_scan_codes("shift")[0], key_to_scan_codes("ctrl")[0]]).issubset(keyboard._pressed_events)):
            self.__display_found_elemenet_by_key()
        elif (
                (e.name, e.event_type) == ('D', 'up') and
                set([key_to_scan_codes("shift")[0], key_to_scan_codes("ctrl")[0]]).issubset(keyboard._pressed_events)):
            self.__start_stop_displaying_info_by_key()
        elif self.mode == "Record":
            if e.event_type == 'up' and e.scan_code in self._ignored_key_ups:
                self._ignored_key_ups.discard(e.scan_code)
                return
            if self.note_pending:
                return
            self.__add_event(e)
            if e.event_type == 'up' and e.name not in keyboard.all_modifiers:
                self.recorded_action_count += 1
                self.last_recorded_action = (time.time(), True, "Key '" + e.name + "'")


    # Ne fonctionne pas dans tous les cas car un rectangle pere n'englobe pas forcement un rectangle fils
    # (par exemple un TreeItem) Mais peut être utilisé en ultime recour
    '''
    def my_from_point(self, x, y, wrapper=None):
        def get_children_of_children_whith_empty_rectangle(wrapper_children):
            children_of_children_whith_empty_rectangle = []
            for child in wrapper_children:
                child_rectangle = child.rectangle()
                if child_rectangle.width() ==0 or child_rectangle.width()==0:
                    children_of_children_whith_empty_rectangle += child.children()
            return children_of_children_whith_empty_rectangle
        def get_children_of_children_not_in_parent_rectangle(wrapper_children):
            children_of_children_whith_empty_rectangle = []
            for child in wrapper_children:
                child_rectangle = child.rectangle()
                grandchildren = child.children()
                if grandchildren:
                    x = grandchildren[0].rectangle().left
                    y = grandchildren[0].rectangle().top
                    if not ((child_rectangle.left < x < child_rectangle.right) and (child_rectangle.top < y < child_rectangle.bottom)):
                        return grandchildren
            return []
        if not wrapper:
            wrapper = self.desktop.top_from_point(x, y)
        wrapper_children = wrapper.children()
        for child in wrapper_children:
            child_rectangle = child.rectangle()
            if (child_rectangle.left < x < child_rectangle.right) and (child_rectangle.top < y < child_rectangle.bottom):
                return self.my_from_point(x, y, wrapper=child)
        for grandchild in get_children_of_children_whith_empty_rectangle(wrapper_children):
            child_rectangle = grandchild.rectangle()
            if (child_rectangle.left < x < child_rectangle.right) and (child_rectangle.top < y < child_rectangle.bottom):
                return self.my_from_point(x, y, wrapper=grandchild)
            
        for grandchild in get_children_of_children_not_in_parent_rectangle(wrapper_children):
            child_rectangle = grandchild.rectangle()
            if (child_rectangle.left < x < child_rectangle.right) and (child_rectangle.top < y < child_rectangle.bottom):
                return self.my_from_point(x, y, wrapper=grandchild)

        return wrapper
    '''
    
    def run(self):
        """
        The function is called in a loop, and it tries to find the unique element under the mouse cursor.
        """
        import comtypes.client
        print("")
        print("COMPTYPES CACHE FOLDER:", comtypes.client._code_cache._find_gen_dir())
        
        dir_path = os.path.dirname(os.path.realpath(__file__))
        print("PYWINAUTO RECORDER FOLDER:", dir_path)
        
        keyboard.hook(self.__key_on)
        mouse.hook(self.__mouse_on)
        keyboard.start_recording()
        win32api.keybd_event(160, 0, win32con.KEYEVENTF_EXTENDEDKEY | win32con.KEYEVENTF_KEYUP, 0)
        ev_list = keyboard.stop_recording()
        # The one-file exe runs from a temporary folder: sys.executable is the exe itself
        exe_path = sys.executable if getattr(sys, 'frozen', False) else dir_path + r"\pywinauto_recorder.exe"
        if not ev_list and os.path.isfile(exe_path):
            print("Couldn't set keyboard hooks. Trying once again...\n")
            time.sleep(0.5)
            subprocess.call([exe_path])
            sys.exit(1)
        elements = []
        previous_wrapper_path = None
        unique_wrapper_path = None
        strategies = [Strategy.unique_path, Strategy.array_2D]
        i_strategy = 0
        self.mode = "Info"
        #strategy_unique_path_again_done = False
        while self.mode != "Quit":
            try:
                self._loop_t0 = time.time()
                self.highlights.clear_all()
                cursor_pos = win32api.GetCursorPos()
                if _is_own_window_under_cursor():
                    # Nothing to inspect on the recorder's windows, and UI Automation calls into them time out while
                    # the Qt thread runs a modal dialog (e.g. the file dialog of Edit a recording...)
                    self._cursor_on_own_window = True
                    self.element_info_tooltip.hide()
                    self.highlights.refresh()
                    time.sleep(0.05)
                    continue
                wrapper = self.desktop.from_point(*cursor_pos)
                if wrapper is None:
                    time.sleep(0.01)
                    continue
                self._cursor_on_own_window = wrapper.process_id() == os.getpid()
                if self._cursor_on_own_window:
                    # Nothing to inspect or record on the control panel of the recorder itself
                    self.__warn_if_overlay(wrapper)
                    self.element_info_tooltip.hide()
                    self.highlights.refresh()
                    time.sleep(0.05)
                    continue
                wrapper_path, window_handle = get_wrapper_path_and_window(wrapper)
                if not wrapper_path:
                    time.sleep(0.01)
                    continue
                # Passed to find_elements instead of set_native_window_handle, which would restrict what replays find
                self._window_handle = window_handle
                if wrapper_path == previous_wrapper_path:
                    if (unique_wrapper_path is None) or (strategies[i_strategy] == Strategy.array_2D):
                        i_strategy = i_strategy + 1
                        if i_strategy >= len(strategies):
                            i_strategy = len(strategies) - 1
                else:
                    # strategy_unique_path_again_done = False
                    i_strategy = 0
                    previous_wrapper_path = wrapper_path
                    elements = find_elements(wrapper_path, self._window_handle)
                #if wrapper_path == previous_wrapper_path and unique_wrapper_path:
                #   strategy = Strategy.unique_path_again
                # else:
                #   strategy = strategies[i_strategy]
                strategy = strategies[i_strategy]
                unique_wrapper_path = None
                # *** ----> this block of code must start a new while iteration if mouse cursor is outside wrapper rectangle
                # => add tests to leave if mouse cursor is outside wrapper rectangle
                wrapper_rectangle = wrapper.rectangle()
                
                #if strategy in [Strategy.unique_path, Strategy.unique_path_again]:
                if strategy is Strategy.unique_path:
                    x_new, y_new = win32api.GetCursorPos()
                    if not ((wrapper_rectangle.left < x_new < wrapper_rectangle.right) and (
                            wrapper_rectangle.top < y_new < wrapper_rectangle.bottom)):
                        i_strategy = 0
                        continue
                    if len(elements)==1:
                        unique_wrapper_path = wrapper_path
                        self.__highlight(wrapper_rectangle, 'unique')
                    else:
                        for e in elements:
                            self.__highlight(e.rectangle(), 'ambiguous')

                if strategy == Strategy.array_2D and elements:
                    x_new, y_new = win32api.GetCursorPos()
                    if not ((wrapper_rectangle.left < x_new < wrapper_rectangle.right) and (
                            wrapper_rectangle.top < y_new < wrapper_rectangle.bottom)):
                        i_strategy = 0
                        continue
                    unique_array_2d = self.__find_unique_element_array_2d(wrapper.rectangle(), elements)
                    if unique_array_2d is not None:
                        unique_wrapper_path = wrapper_path + unique_array_2d
                # <----- ***
                if unique_wrapper_path is not None:
                    recording = self.event_list and self.mode == "Record"
                    r = wrapper_rectangle
                    details_key = (unique_wrapper_path, r.left, r.top, r.right, r.bottom)
                    if details_key != self._details_key:
                        # Shared by the element events of the same element, and read once, as it is slow
                        self._details_key, self._details, self._details_requested = details_key, {}, False
                    self.last_element_event = ElementEvent(strategy, wrapper_rectangle, unique_wrapper_path, self._details)
                    if recording:
                        self.__add_event(self.last_element_event)
                        if not self._details_requested:
                            self._details_requested = True
                            self._details_queue.put((wrapper, strategy, unique_wrapper_path, self._details))
                if self.mode in ("Stop", "Play"):
                    self.element_info_tooltip.hide()
                    self.highlights.clear_all()
                    self.highlights.refresh()
                    while self.mode in ("Stop", "Play"):
                        time.sleep(0.1)
                if self.mode == "Info":
                    self.element_info_tooltip.show()
                
                self.highlights.refresh()
                
                loop_duration = time.time() - self._loop_t0
                while loop_duration < 0.1:
                    time.sleep(0.01)
                    loop_duration = time.time() - self._loop_t0
                time.sleep(0.01)  # highlights.clear_all() doit attendre la fin de highlights.refresh()
            except Exception as error:
                _log_loop_error(error)
                self.common_path_info_tip = ""
                self.wrapper_old_info_tip = None
                self.element_info_tooltip.hide()
                self.highlights.refresh()  # cleared at the start of the iteration
                time.sleep(0.1)  # the cursor is probably still where the error happened
        if self.event_list:
            self.stop_recording()
        mouse.unhook_all()
        keyboard.unhook_all()
        self._details_queue.put(None)
        self._click_queue.put(None)
        self.highlights.quit()
        print("Run end")

    @property
    def process_menu_click_mode(self):
        """
        If True, the process menu events are recorded else they are ignored.
    
        :return: The state of the process menu click mode.
        """
        return self._process_menu_click_mode
    
    @process_menu_click_mode.setter
    def process_menu_click_mode(self, value):
        """
        It sets the state of the process menu click mode.
        
        :param value: If the value is True, the process menu events are recorded else they are ignored.
        """
        self._process_menu_click_mode = value

    @property
    def relative_coordinate_mode(self):
        """
        If True, the relative coordinates are recorded else they are ignored.

        :return: The state of the relative coordinates mode.
        """
        return self._relative_coordinate_mode
    
    @relative_coordinate_mode.setter
    def relative_coordinate_mode(self, value):
        """
        It sets the state of the relative coordinates mode.

        :param value: If the value is True, the relative coordinates are recorded else they are ignored.
        """
        self._relative_coordinate_mode = value

    @property
    def mode(self):
        """
    It returns the mode of the recorder: "Record", "Play", "Info", "Stop", "Quit"
            
        :return: The mode of the recorder.
        """
        return self._mode
    
    @mode.setter
    def mode(self, value):
        """
        It sets the mode of the recorder: "Record", "Play", "Info", "Stop", "Quit"
        
        :param value: The mode of the recorder.
        """
        self._mode = value

    def start_recording(self):
        """
        It adds a mouse move event to the event list, clears the highlights and hides the element information, and then sets the mode to "Record".
        """
        time.sleep(0.6)  # wait the recorder to be fully ready
        x, y = win32api.GetCursorPos()
        self._recording_start_time = time.time()
        self.event_list = [mouse.MoveEvent(x, y, self._recording_start_time)]
        self.recorded_action_count = 0
        self.last_recorded_action = None
        self.note_pending = False
        self._ignored_key_ups = set()
        self.element_info_tooltip.hide()
        self.highlights.clear_all()
        self.highlights.refresh()
        self.mode = "Record"

    def stop_recording(self):
        """
        It cleans the event list, clears the highlights, writes the Python script, and then sets the mode to "Stop".
        :return: The name of the file that was created.
        """
        if self.mode == "Record" and len(self.event_list) > 2:
            self.__wait_for_queue(self._click_queue)  # the clicked elements replace their placeholders in event_list
            self.note_pending = False
            with self._events_lock:
                events, self.event_list = self.event_list, []
            self.mode = "Stop"
            time.sleep(0.6)  # wait the recorder to be fully ready
            if self.started_recording_with_keyboard:
                _clean_events(events, remove_first_up=True)
            else:
                _clean_events(events)
            self.started_recording_with_keyboard = False
            _process_events(events, process_menu_click=self.process_menu_click_mode)
            self.__wait_for_queue(self._details_queue)
            _clean_events(events)
            self.last_recorded_file = _write_in_file(
                events, relative_coordinate_mode=self.relative_coordinate_mode, start_time=self._recording_start_time)
            return self.last_recorded_file
        self.highlights.clear_all()
        self.highlights.refresh()
        self.mode = "Stop"
        return None

    def get_last_element_event(self):
        """
        It returns the last element of the event.
        :return: The last element event.
        """
        return self.last_element_event
    
    def playback(self, str_code='', filename='', on_error=None):
        """
        This function plays back a string of code or a Python file.
        
        :param str_code: The code to be played back
        :param filename: The name of the file coresponding to the code to be played back
        :param on_error: Called with the traceback if the code raises an exception, instead of printing it in the console
        """
        self.mode = "Play"
        self.highlights.refresh()
        playback(str_code, filename, on_error)
        self.mode = "Stop"
    
    def quit(self):
        """
        It saves the recording in progress, stops the loop and the process of the element information. It never waits
        for long: the loop and that process may be blocked in a UI Automation call to an application that hangs.
        """
        if self.mode == 'Record':
            self.stop_recording()  # the loop only writes the file in the Record mode
        self.highlights.clear_all()
        self.highlights.refresh()
        self.mode = 'Quit'
        self.join(timeout=5)  # a daemon thread: it doesn't keep the application alive if it doesn't stop
        self.element_info_tooltip.close()
        print("Quit")

read_config_file()