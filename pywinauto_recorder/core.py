# -*- coding: utf-8 -*-

import re
from enum import Enum
import configparser
import ast
from pywinauto import Desktop as PywinautoDesktop
from pywinauto.controls.uiawrapper import UIAWrapper
from pywinauto.uia_element_info import UIAElementInfo
from pywinauto import findwindows
from pywinauto.uia_defines import IUIA
from comtypes import COMError
import win32gui


__all__ = ['path_separator', 'type_separator', 'Strategy', 'is_int', 'is_absolute_path',
           'get_wrapper_path', 'get_wrapper_path_and_window', 'get_entry_list', 'get_entry', 'match_entry_list', 'get_sorted_region',
           'find_elements', 'read_config_file', 'get_native_window_handle', 'set_native_window_handle']

desktop = PywinautoDesktop(backend='uia', allow_magic_lookup=False)
native_window_handle = None


def get_native_window_handle():
    return native_window_handle


def set_native_window_handle(handle):
    global native_window_handle
    native_window_handle = handle




class CoreSettings:
    class window_filtering:
        mode = 'ignore_windows'
        admit_windows = []
        ignore_windows = []


path_separator = "->"
type_separator = "||"


# > The `Strategy` class is an enumeration of the different strategies that can be used to solve the problem
class Strategy(Enum):
    unique_path = 1  # the path alone
    array_2D = 3  # the path and the position among the elements having it: '#[row,column]'


_path_cache_request = None


def get_wrapper_path_and_window(wrapper):
    """
    It walks once from the element up to its top-level window (the ancestor whose parent is the desktop), like
    pywinauto's parent() and top_level_parent() do, but each step reads the parent with its name, control type and
    handle in a single cross-process call, instead of 4 to 6 calls.

    :param wrapper: The UIAWrapper of the element
    :return: The path of the element and the native handle of its top-level window (None if it has none), or
        ('', None) if the element doesn't exist anymore
    """
    global _path_cache_request
    iuia = IUIA()
    if _path_cache_request is None:
        request = iuia.iuia.CreateCacheRequest()
        for property_id in (iuia.UIA_dll.UIA_NamePropertyId, iuia.UIA_dll.UIA_ControlTypePropertyId,
                            iuia.UIA_dll.UIA_NativeWindowHandlePropertyId):
            request.AddProperty(property_id)
        _path_cache_request = request
    desktop_handle = win32gui.GetDesktopWindow()
    walker = iuia.iuia.ControlViewWalker

    def entry(element):
        name = element.CachedName or ''
        return name + type_separator + iuia.known_control_type_ids.get(element.CachedControlType, '')

    try:
        element = wrapper.element_info.element.BuildUpdatedCache(_path_cache_request)
        entries = []
        while True:
            parent = walker.GetParentElementBuildCache(element, _path_cache_request)
            if not parent or parent.CachedNativeWindowHandle == desktop_handle:
                break  # element is the top-level window
            entries.append(entry(element))
            element = parent
        path = entry(element) + ''.join(path_separator + e for e in reversed(entries))
        return path, element.CachedNativeWindowHandle or None
    except (COMError, ValueError):
        return '', None  # the element or one of its ancestors was closed


def get_wrapper_path(wrapper, wrapper_top_level_parent=None):
    """
    :param wrapper: The UIAWrapper of the element
    :param wrapper_top_level_parent: Unused, kept for compatibility
    :return: The path of the element from its top-level window, '' if the element doesn't exist anymore
    """
    return get_wrapper_path_and_window(wrapper)[0]


def get_entry_list(path):
    """
    It splits the path into a list of entries
    It only handles one #[y,x] at the end. It does not handle the #[y,x] in the middle.
    
    :param path: the path to the element
    :return: A list of the entries.
    """
    i = path.rfind("#[")
    if i != -1:
        i = path.rfind(path_separator, 0, i)
    else:
        i = path.rfind(path_separator)
    if i == -1:
        return [path]
    last_entry = path[i + len(path_separator)::]
    start_entry = path[:i]
    return start_entry.split(path_separator) + [last_entry]


def is_int(s):
    """
    "If the string can be converted to an integer, return True, otherwise return False."

    The try statement is used to catch exceptions. In this case, if the string can be converted to an integer, the int()
    function will return the integer. If the string cannot be converted to an integer, the int() function will raise a
    ValueError exception

    :param s: the string to check
    :return: True or False
    """
    try:
        int(s)
        return True
    except ValueError:
        return False


def is_absolute_path(entry):
    return entry[-16:] == '~Absolute_UIPath'


def get_entry(entry):
    """
    It takes a string of the form "name"#["y",x]%(dx,dy)~Absolute_UIPath and returns a tuple of the form (name, type, [y,x], (dx,dy))
    
    :param entry: the string that is the entry in the listbox
    :return: The name of the entry, the type of the entry, the size of the entry, and the dx and dy of the entry.
    """
    if is_absolute_path(entry):
        entry = entry[:-16]
    if entry[0:7] == "RegEx: ":
        entry = entry[7:]
    i = entry.find(type_separator)
    if i == -1:
        return entry, None, None, None
    while i < len(entry) and entry[i] == type_separator[0]:
        i = i + 1
    i = i - len(type_separator)
    str_name = entry[0:i]
    
    entry2 = entry[i + len(type_separator):]
    i = entry2.rfind("""%(""")
    
    if i != -1:
        str_dx_dy = entry2[i + 2:]
        entry3 = entry2[0:i]
    else:
        str_dx_dy = None
        entry3 = entry2
    
    i = entry3.rfind("""#[""")
    if i != -1:
        str_array = entry3[i + 2:-1]
        str_type = entry3[0:i]
    else:
        str_array = None
        str_type = entry3
    
    if str_type == '':
        str_type = None
    if str_array:
        words = str_array.split(',')
        y = words[0]
        if is_int(y):
            y = int(y)
        x = int(words[1])
        y_x = [y, x]
    else:
        y_x = None
    if str_dx_dy:
        words = str_dx_dy.split(',')
        dx_dy = (float(words[0]), float(words[1].split(')')[0]))
    else:
        dx_dy = None
    return str_name, str_type, y_x, dx_dy


def is_regex_entry(entry):
    """
    It returns True if the first seven characters of the string entry are "RegEx: " and False otherwise
    
    :param entry: The entry to check
    :return: A boolean value.
    """
    return entry[0:7] == "RegEx: "


def match_entry(entry, template):
    """
    It returns true if the entry matches the template, and false otherwise
    
    :param entry: the entry to be matched
    :param template: the template to match against
    :return: A boolean value.
    """
    # print("match_entry: entry: " + entry + " template: " + template)
    template_name, template_type, _, _ = get_entry(template)
    entry_name, entry_type, _, _ = get_entry(entry)
    if is_regex_entry(template):
        return re.match(template_name, entry_name) and (template_type == entry_type or not template_type)
    else:
        return template_name == entry_name and (template_type == entry_type or not template_type)


def match_entry_list(l1, l2):
    """
    It takes an entry list and a template list, and returns True if the entry list matches the template list

    :param l1: the entry list of an element
    :param l2: the template list (already completed with UIPath)
    :return: True if the entry list matches the template list.
    """
    if (l1 == []):
        return (l2 == [] or l2 == ['*'])
    if (l2 == [] or l2[0] == '*'):
        return match_entry_list(l2, l1)
    if (l1[0] == '*'):
        return (match_entry_list(l1, l2[1:]) or match_entry_list(l1[1:], l2))
    if is_regex_entry(l1[0]):
        if match_entry(l2[0], l1[0]):
            return match_entry_list(l1[1:], l2[1:])
    elif match_entry(l1[0], l2[0]):
        return match_entry_list(l1[1:], l2[1:])
    else:
        return False


def is_filter_criteria_ok(child, min_height=8, max_height=200, min_width=8, max_width=800):
    """
    "Return True if the child is visible and its height and width are within the specified ranges."
    
    The function is_filter_criteria_ok() takes four arguments:
    
    child: the child to check
    min_height: the minimum height of the child
    max_height: the maximum height of the child
    min_width: the minimum width of the child
    max_width: the maximum width of the child
    The function returns True if the child is visible and its height and width are within the specified ranges. Otherwise,
    it returns False
    
    :param child: the child element to check
    :param min_height: The minimum height of the element, defaults to 8 (optional)
    :param max_height: The maximum height of the element, defaults to 200 (optional)
    :param min_width: The minimum width of the element, defaults to 8 (optional)
    :param max_width: The maximum width of the element, defaults to 800 (optional)
    :return: A list of all the visible elements that meet the filter criteria.
    """
    if child.is_visible():
        r = child.rectangle()
        h = r.height()
        w = r.width()
        if (min_height <= h <= max_height) and (min_width <= w <= max_width):
            return True
    return False


def all_height_equal(iterator):
    """
    It returns True if all the elements in the iterator have the same height, and False otherwise
    
    :param iterator: an iterable object
    :return: A boolean value.
    """
    iterator = iter(iterator)
    try:
        first = next(iterator)
        first_height = first.rectangle().height()
    except StopIteration:
        return True
    for x in iterator:
        if first_height != x.rectangle().height():
            return False
    return True


def get_sorted_region(elements, min_height=8, max_height=9999, min_width=8, max_width=9999, line_tolerance=20):
    """
    It takes a list of elements, filters them based on the given criteria, sorts them by top and left, and then returns a
    list of lists of elements, where each list is a row of elements
    
    :param elements: the list of elements to be sorted
    :param min_height: The minimum height of the elements to be considered, defaults to 8 (optional)
    :param max_height: The maximum height of the elements in the region, defaults to 9999 (optional)
    :param min_width: The minimum width of the elements to be considered, defaults to 8 (optional)
    :param max_width: The maximum width of the elements in the region, defaults to 9999 (optional)
    :param line_tolerance: This is the maximum distance between two elements in the same row, defaults to 20 (optional)
    :return: The number of rows, the number of columns, and the sorted elements.
    """
    # rectangle() and is_visible() are cross-process calls: each one is done only once per element.
    filtered_elements = []
    for e in elements:
        if e.is_visible():
            r = e.rectangle()
            if (min_height <= r.height() <= max_height) and (min_width <= r.width() <= max_width):
                filtered_elements.append((e, r))
    if not filtered_elements:
        return 0, 0, []
    filtered_elements.sort(key=lambda e_r: (e_r[1].top, e_r[1].left))

    first_height = filtered_elements[0][1].height()
    if all(r.height() == first_height for _, r in filtered_elements):
        line_tolerance = first_height

    rows = [[]]
    w = -1
    y = filtered_elements[0][1].top
    for e_r in filtered_elements:
        if (e_r[1].top - y) >= line_tolerance:
            rows.append([])
            y = e_r[1].top
        rows[-1].append(e_r)
        w = max(w, len(rows[-1]))
    arrays = []
    for row in rows:
        row.sort(key=lambda e_r: (e_r[1].left, -e_r[1].width()))
        arrays.append([e for e, _ in row])
    return len(arrays), w, arrays


def filter_by_name(element_infos, name, regex=False):
    """
    It keeps the elements whose name is the given name, or matches it if regex is True.
    pywinauto's 'title' and 'title_re' criteria can't be used: they match the rich text, which is the content of the
    edits and of the documents instead of their name, whereas get_wrapper_path writes the names in the paths.

    :param element_infos: The UIAElementInfo list to filter
    :param name: The name, or the regular expression if regex is True, None to keep all the elements
    :param regex: True if name is a regular expression
    :return: The UIAElementInfo list of the matching elements
    """
    if name is None:
        return element_infos
    if regex:
        name_regex = re.compile(name)
        return [ei for ei in element_infos if name_regex.match(ei.name)]
    return [ei for ei in element_infos if ei.name == name]


def find_window_candidates(root_entry, handle=None):
    """
    It returns a list of windows that match the given root entry
    
    :return: A list of window candidates.
    """
    title, control_type, _, _ = get_entry(root_entry)
    if root_entry == "*":
        title = None
        control_type = None
    if handle is not None:
        element_infos = [w.element_info for w in desktop.windows(
            control_type=control_type, visible_only=False, enabled_only=False, active_only=False, handle=handle)]
    else:
        # Not desktop.windows(): UI Automation would query the hidden windows too, which can't be used, and an
        # application owning hundreds of them (e.g. bricscad_bsb.exe) makes it take seconds.
        handles = []
        win32gui.EnumWindows(lambda h, _: handles.append(h) if win32gui.IsWindowVisible(h) else None, None)

        def matching(window_handles):
            element_infos = []
            for h in window_handles:
                try:
                    element_info = UIAElementInfo(h)
                    if control_type is None or element_info.control_type == control_type:
                        element_infos.append(element_info)
                except Exception:
                    pass  # the window was closed
            return filter_by_name(element_infos, title, regex=is_regex_entry(root_entry))

        element_infos = []
        if title and not is_regex_entry(root_entry):
            # The title of a window, read without asking its application, is its UI Automation name almost always:
            # only the windows having it are asked first. All of them are asked if none matches.
            element_infos = matching([h for h in handles if win32gui.GetWindowText(h) == title])
        if not element_infos:
            element_infos = matching(handles)
        return [UIAWrapper(ei) for ei in element_infos]
    element_infos = filter_by_name(element_infos, title, regex=is_regex_entry(root_entry))
    return [UIAWrapper(ei) for ei in element_infos]


def filter_window_candidates(window_candidates):
    """
    It filters out windows that are not in the list of admitted windows, or that are in the list of ignored windows
    
    :param window_candidates: a list of Window objects
    :return: A list of window candidates that have been filtered.
    """
    if core_settings.window_filtering.mode == 'admit_windows':
        window_candidates = list(filter(
            lambda w: any(substr in w.element_info.name for substr in core_settings.window_filtering.admit_windows),
            window_candidates))
    else:
        window_candidates = list(filter(
            lambda w: not any(substr in w.element_info.name for substr in core_settings.window_filtering.ignore_windows),
            window_candidates))
    return window_candidates


def get_element_info_path(element_info, window, path_by_runtime_id):
    """
    It returns the path of the element from the window down to the element.
    The paths of the visited ancestors are memoized in path_by_runtime_id, so that each ancestor shared by several
    elements is read only once.

    :param element_info: The UIAElementInfo of the element
    :param window: The UIAElementInfo of the window containing the element
    :param path_by_runtime_id: The memoized paths, by UIA runtime id
    :return: The path of the element, or '' if the element is not in the window.
    """
    try:
        chain = []
        while True:
            if element_info is None:
                return ''
            runtime_id = element_info.runtime_id
            if runtime_id and runtime_id in path_by_runtime_id:
                path = path_by_runtime_id[runtime_id]
                break
            if not runtime_id and element_info == window:
                path = window.name + type_separator + window.control_type
                break
            chain.append((runtime_id, element_info))
            element_info = element_info.parent
        for runtime_id, ancestor in reversed(chain):
            path = path + path_separator + ancestor.name + type_separator + ancestor.control_type
            if runtime_id:
                path_by_runtime_id[runtime_id] = path
        return path
    except Exception:
        return ''


def filter_with_match_entry_list(window, descendants, entry_list):
    result = []
    ds = {}
    path_by_runtime_id = {}
    if window.runtime_id:
        path_by_runtime_id[window.runtime_id] = window.name + type_separator + window.control_type
    for d in descendants:
        wp = get_element_info_path(d, window, path_by_runtime_id)
        if wp not in ds:
            ds[wp] = []
        ds[wp].append(d)
    for k in ds.keys():
        if match_entry_list(get_entry_list(k), entry_list):
            result += ds[k]
    return result


def find_children_along_path(window, entry_list):
    """
    It walks down the path from the window, asking UI Automation only for the children matching each entry. It is much
    faster than searching all the descendants of the window, which can be thousands in a grid.

    :param window: The UIAElementInfo of the window
    :param entry_list: The entries of the path below the window, without '*'
    :return: The UIAElementInfo list of the elements found
    """
    parents = [window]
    for entry in entry_list:
        name, control_type, _, _ = get_entry(entry)
        regex = is_regex_entry(entry)
        children = []
        for parent in parents:
            # The name is a UI Automation condition unless it is empty or a regular expression, filtered below
            children +=parent.children(control_type=control_type, title=None if regex else name)
        parents = filter_by_name(children, name, regex=regex)
        if not parents:
            break
    return parents


def find_elements(full_element_path=None, window_handle=None):
    """
    It returns the elements (UIAWrapper list) that matche the full_element_path

    :param full_element_path: full path of the element(s) to find
    :param window_handle: The native handle of the window to search in, the one of the application in focus if None
    :return: The elements found
    """
    entry_list = get_entry_list(full_element_path)
    if window_handle is None:
        window_handle = native_window_handle
    window_candidates = find_window_candidates(entry_list[0], handle=window_handle)
    if window_candidates == []:
        return []
    window_candidates = filter_window_candidates(window_candidates)
    if len(entry_list) == 1 and len(window_candidates) == 1:
        if entry_list == ['*']:
            return [window_candidates[0]]
        title, control_type, _, _ = get_entry(entry_list[0])
        if window_candidates[0].element_info.name == title and window_candidates[0].element_info.control_type == control_type:
            return [window_candidates[0]]

    candidates = []
    title, control_type, _, _ = get_entry(entry_list[-1])
    for window in window_candidates:
        if entry_list[-1] == '*':
            eis = findwindows.find_elements(backend="uia", parent=window, top_level_only=False)
            candidates += filter_with_match_entry_list(window.element_info, eis, entry_list)
        elif len(entry_list) > 1 and '*' not in entry_list:
            candidates += find_children_along_path(window.element_info, entry_list[1:])
        else:
            eis = findwindows.find_elements(control_type=control_type, backend="uia",
                                            parent=None if len(entry_list)==1 else window, top_level_only=len(entry_list)==1)
            eis = filter_by_name(eis, title, regex=is_regex_entry(entry_list[-1]))
            candidates += filter_with_match_entry_list(window.element_info, eis, entry_list)
    candidates = [UIAWrapper(ei) for ei in candidates]
    
    if not candidates:
            return []
    else:
        return candidates


# The following code should be called in recoder.py because it's useful only when recording
def read_config_file():
    """
    It reads the configuration file and stores the settings in the global variable `core_settings`
    """
    global core_settings
    config_file_content = '''[window_filtering]
    mode = ignore_windows
    admit_windows = []
    ignore_windows = []
    '''
    from pathlib import Path
    config_file = Path.home() / 'Pywinauto recorder' / 'config.ini'
    if config_file.exists and config_file.is_file():
        print("Reading configuration file: " + str(config_file))
        config = configparser.RawConfigParser()
        config.read(config_file)
        
        # config.read_string(ini_config)
        
        class Dict2Obj:
            def __init__(self, in_dict: dict):
                assert isinstance(in_dict, dict)
                for key, val in in_dict.items():
                    if isinstance(val, (list, tuple)):
                        setattr(self, key, [Dict2Obj(x) if isinstance(x, dict) else x for x in val])
                    else:
                        setattr(self, key, Dict2Obj(val) if isinstance(val, dict) else val)
        
        core_settings = Dict2Obj({s: dict(config.items(s)) for s in config.sections()})
        print("Window filtering mode: " + core_settings.window_filtering.mode)
        if core_settings.window_filtering.mode == "admit_windows":
            print("Admitted windows: " + core_settings.window_filtering.admit_windows)
            core_settings.window_filtering.admit_windows = ast.literal_eval(core_settings.window_filtering.admit_windows)
        else:
            print("Ignored windows: " + core_settings.window_filtering.ignore_windows)
            core_settings.window_filtering.ignore_windows = ast.literal_eval(core_settings.window_filtering.ignore_windows)
    else:
        print("Warning: '" + str(config_file) + "' not found! This file is created with a default configuration!")
        home_dir = Path.home() / 'Pywinauto recorder'
        home_dir.mkdir(parents=True, exist_ok=True)
        with open(config_file, 'w') as out_file:
            out_file.write(config_file_content)


core_settings = CoreSettings()
