import json
import keyboard
import mouse
import pytest
from pywinauto.win32structures import RECT
from pywinauto_recorder.core import Strategy, get_entry_list, get_entry, match_entry_list
from pywinauto_recorder import recorder
from pywinauto_recorder.recorder import ClickEvent, DragAndDropEvent, ElementEvent, MouseWheelEvent, NoteEvent, \
    SendKeysEvent, _clean_events, _get_action, _get_event, _get_script, _process_events, get_script, \
    update_recording
from pywinauto_recorder.player import _element_in_grid


################################################################################################
#                                   Tests of low level functions                               #
################################################################################################

def test_get_entry_list():
    """Tests get_entry_list(element_path)."""
    element_path = "D:\\Name||Window->||Pane->Property||Group->"
    element_path = element_path + "Label:||Text#[Name||Window->||Pane->Property||Group->Label:||Text,0]%(0,0)"
    entry_list = get_entry_list(element_path)
    assert entry_list[0] == 'D:\\Name||Window'
    assert entry_list[1] == '||Pane'
    assert entry_list[2] == 'Property||Group'
    assert entry_list[3] == 'Label:||Text#[Name||Window->||Pane->Property||Group->Label:||Text,0]%(0,0)'


def test_get_entry_list_with_asterisk():
    """Tests get_entry_list(element_path) having element_path with some asterisks."""
    element_path = "Name||Window->*->||Group->Property||%(0,0)"
    entry_list2 = get_entry_list(element_path)
    assert entry_list2[1] == '*'
    assert entry_list2[2] == '||Group'
    assert entry_list2[3] == 'Property||%(0,0)'


def test_get_entry_elements():
    """Tests get_entry(entry)."""
    str_name_with_colon = 'Name:'
    str_name_without_colon = 'Name'
    str_y_x_with_colon = 'y_name:||y_type'
    str_y_x_without_colon = 'y_name||y_type'
    test_data = [
        ('Name:||Type#[0,0]%(2,-24)',      (str_name_with_colon, 'Type', [0,0], (2,-24))),
        ('||Type#[0,0]%(2,-24)',           ('', 'Type', [0,0], (2,-24))),
        ('Name:||#[0,0]%(2,-24)',          (str_name_with_colon, None, [0,0], (2,-24))),
        ('Name:||Type#[0,0]',              (str_name_with_colon, 'Type', [0,0], None)),
        ('||Type#[0,0]',                   ('', 'Type', [0,0], None)),
        ('Name:||#[0,0]',                  (str_name_with_colon, None, [0,0], None)),
        ('Name:||Type',                    (str_name_with_colon, 'Type', None, None)),
        ('||Type',                         ('', 'Type', None, None)),
        ('Name:||',                        (str_name_with_colon, None, None, None)),
        ('Name||Type',                     (str_name_without_colon, 'Type', None, None)),
        ('||Type',                         ('', 'Type', None, None)),
        ('Name||',                         (str_name_without_colon, None, None, None)),
        ('Name||Type#[y_name:||y_type,0]', (str_name_without_colon, 'Type', [str_y_x_with_colon, 0], None)),
        ('||Type#[y_name:||y_type,0]',     ('', 'Type', [str_y_x_with_colon, 0], None)),
        ('Name||#[y_name:||y_type,0]',     (str_name_without_colon, None, [str_y_x_with_colon, 0], None)),
        ('Name||Type#[y_name||y_type,0]',  (str_name_without_colon, 'Type', [str_y_x_without_colon, 0], None)),
        ('||Type#[y_name||y_type,0]',      ('', 'Type', [str_y_x_without_colon, 0], None)),
        ('Name||#[y_name||y_type,0]',      (str_name_without_colon, None, [str_y_x_without_colon, 0], None))
    ]
    for data in test_data:
        str_name, str_type, y_x, dx_dy = get_entry(data[0])
        assert str_name == data[1][0]
        assert str_type == data[1][1]
        assert y_x == data[1][2]
        assert dx_dy == data[1][3]


def test_match_entry_list():
    """Tests if the entry_list matches the template_list."""
    entry = "wName||Window->pName||Pane->||Pane->materialFileLineEdit||Pane"
    template = "wName||Window->pName||Pane->*->RegEx: .*||Pane"
    assert match_entry_list(get_entry_list(entry), get_entry_list(template))

    template_list = get_entry_list("wName||Window->*->Tab1||Tab->A||Group->B||Group->*->Login||Button")
    entry_path_set = [
        ("wName||Window->Tab1||Tab->A||Group->B||Group->Login||Button", True),
        ("wName||Window->Tab1||Tab->A||Group->Login||Button", False),
        ("wName||Window->bla||bla->Tab1||Tab->A||Group->B||Group->bla||bla->Login||Button", True),
        ("wName||Window->bla||bla->Tab1||Tab->bla||bla->A||Group->B||Group->bla||bla->Login||Button", False),
        ("wName||Window->bla||bla->bla||bla->Tab1||Tab->A||Group->B||Group->bla||bla->bla||bla->Login||Button", True),
    ]
    for entry_path in entry_path_set:
        assert match_entry_list(get_entry_list(entry_path[0]), template_list) == entry_path[1]


################################################################################################
#                Tests of the recording pipeline, with synthetic events (no GUI)               #
################################################################################################

WINDOW = 'Untitled - Notepad||Window'
OK_PATH = WINDOW + '->OK||Button'
EDIT_PATH = WINDOW + '->Text editor||Document'


def _element(path, left=100, top=100, right=200, bottom=120):
    return ElementEvent(Strategy.unique_path, RECT(left, top, right, bottom), path, {'name': path})


def _key(name, event_type):
    return keyboard.KeyboardEvent(event_type, 0, name=name, time=1.0)


def _type(text):
    events = []
    for name in text:
        events += [_key(name, 'down'), _key(name, 'up')]
    return events


def _process(events):
    _clean_events(events)
    _process_events(events)
    _clean_events(events)
    return [e for e in events if _get_action(e, 0) is not None]


def test_click_is_recorded_on_the_element_under_the_cursor():
    events = _process([
        mouse.MoveEvent(150, 110, 1.0), _element(OK_PATH),
        mouse.ButtonEvent('down', 'left', 2.0), mouse.ButtonEvent('up', 'left', 2.1)])
    assert len(events) == 1
    click = events[0]
    assert isinstance(click, ClickEvent)
    assert (click.path, click.button, click.click_count, click.x, click.y) == (OK_PATH, 'left', 1, 150, 110)


def test_double_click():
    events = _process([
        mouse.MoveEvent(150, 110, 1.0), _element(OK_PATH),
        mouse.ButtonEvent('down', 'left', 2.0), mouse.ButtonEvent('up', 'left', 2.1),
        mouse.ButtonEvent('double', 'left', 2.2), mouse.ButtonEvent('up', 'left', 2.3)])
    clicks = [e for e in events if isinstance(e, ClickEvent)]
    assert clicks[-1].click_count == 2


def test_move_beyond_the_drag_threshold_is_a_drag_and_drop():
    target = WINDOW + '->Target||Pane'
    events = _process([
        mouse.MoveEvent(150, 110, 1.0), _element(OK_PATH),
        mouse.ButtonEvent('down', 'left', 2.0),
        mouse.MoveEvent(450, 310, 2.5), _element(target, 400, 300, 500, 320),
        mouse.ButtonEvent('up', 'left', 3.0)])
    assert len(events) == 1
    drag = events[0]
    assert isinstance(drag, DragAndDropEvent)
    assert (drag.path, drag.path2) == (OK_PATH, target)
    assert (drag.x1, drag.y1, drag.x2, drag.y2) == (150, 110, 450, 310)


def test_keys_are_grouped_in_one_send_keys():
    events = _process(_type('ab') + [_key('enter', 'down'), _key('enter', 'up')])
    assert len(events) == 1
    assert isinstance(events[0], SendKeysEvent)
    assert events[0].line == '"ab{ENTER}"'


def test_backspace_removes_the_last_typed_character():
    events = _process(_type('abc') + [_key('backspace', 'down'), _key('backspace', 'up')])
    assert events[0].line == '"ab"'


def test_send_keys_special_characters_are_escaped():
    events = _process(_type('5%{'))
    assert events[0].line == '"5{%}{{}"'


def test_shortcut_with_ctrl():
    events = _process([_key('ctrl', 'down'), _key('c', 'down'), _key('c', 'up'), _key('ctrl', 'up')])
    assert events[0].line == '"{VK_LCONTROL down}c{VK_LCONTROL up}"'


def test_wheel_events_are_summed():
    events = _process([
        mouse.MoveEvent(150, 110, 1.0), _element(OK_PATH),
        mouse.WheelEvent(-1.0, 2.0), mouse.WheelEvent(-1.0, 2.1), mouse.WheelEvent(-1.0, 2.2)])
    assert len(events) == 1
    assert isinstance(events[0], MouseWheelEvent)
    assert events[0].delta == -3.0


def _sample_events():
    return _process([
        mouse.MoveEvent(150, 110, 1.0), _element(OK_PATH),
        mouse.ButtonEvent('down', 'left', 2.0), mouse.ButtonEvent('up', 'left', 2.1),
        mouse.MoveEvent(300, 400, 3.0), _element(EDIT_PATH, 0, 200, 600, 600),
        mouse.ButtonEvent('down', 'left', 4.0), mouse.ButtonEvent('up', 'left', 4.1)]
        + _type('hi{')) + [NoteEvent('Wait for the dialog', 5.0)]


def test_json_actions_give_back_the_events():
    """The script of a JSON file is made from its actions: they must describe the events completely."""
    events = _sample_events()
    actions = [_get_action(e, 0) for e in events]
    assert [a['action'] for a in actions] == ['click', 'click', 'send_keys', 'note']
    assert actions[2]['keys'] == 'hi{{}'
    assert get_script(actions) == _get_script(events)
    for action in actions:
        assert recorder.get_action_code(action) == action['pywinauto_recorder_code']
    assert _get_event({'action': 'unknown'}) is None


def test_script_groups_actions_by_window():
    script = _get_script(_sample_events())
    assert 'with UIPath(u"' + WINDOW + '"):\n' in script
    assert '\tclick(u"OK||Button")\n' in script
    assert '\tclick(u"Text editor||Document")\n' in script
    assert '\tsend_keys("hi{{}")\n' in script
    assert '\t# Wait for the dialog\n' in script
    compile(script, 'script', 'exec')


def test_edited_recording_gets_its_code_and_script_again():
    actions = [_get_action(e, 0) for e in _sample_events()]
    del actions[1]
    actions[0]['note'] = 'Close the welcome dialog'
    actions[0]['uipath'] = WINDOW + '->Cancel||Button'
    recording = {'options': {'relative_coordinate_mode': False}, 'actions': actions}
    update_recording(recording)
    assert actions[0]['pywinauto_recorder_code'] == 'click(u"' + WINDOW + '->Cancel||Button")'
    script = recording['pywinauto_recorder_script']
    assert '# Close the welcome dialog\n' in script and 'Text editor' not in script
    compile(script, 'script', 'exec')


class _FakeElement:
    def __init__(self, left, top, name=''):
        self.rect = RECT(left, top, left + 50, top + 20)
        self.name = name

    def is_visible(self):
        return True

    def rectangle(self):
        return self.rect


def test_element_in_grid_by_row_and_column():
    elements = [_FakeElement(x, y, f'{y},{x}') for y in (0, 30) for x in (0, 60, 120)]
    assert _element_in_grid(elements, [1, 2], 'path').name == '30,120'
    assert _element_in_grid(elements, [0, 0], 'path').name == '0,0'


def test_element_in_grid_missing_row_or_column_is_searched_again():
    """The grid may not be filled yet when the search starts: no IndexError, the search goes on."""
    elements = [_FakeElement(x, 0) for x in (0, 60)]
    assert _element_in_grid(elements, [3, 0], 'path') is None
    assert _element_in_grid(elements, [0, 5], 'path') is None


class _FakeUIElement:
    def __init__(self, path, left, top, right, bottom):
        self.path = path
        self.rect = RECT(left, top, right, bottom)
        name, control_type, _, _ = get_entry(get_entry_list(path)[-1])
        self.element_info = type('ElementInfo', (), {'name': name, 'control_type': control_type, 'rectangle': self.rect})

    def rectangle(self):
        return self.rect


def _fake_row(monkeypatch, row):
    """Replaces UI Automation with the elements of a row, from left to right."""
    def from_point(x, y):
        return next((e for e in row if e.rect.left <= x < e.rect.right and e.rect.top <= y < e.rect.bottom), None)

    monkeypatch.setattr(recorder._desktop, 'from_point', from_point, raising=False)
    monkeypatch.setattr(recorder, 'get_wrapper_path_and_window', lambda element: (element.path, 1))
    monkeypatch.setattr(recorder, 'find_elements', lambda path, handle=None: [e for e in row if e.path == path] * (
        2 if path.endswith('||Edit') else 1))  # the edits have the same path in every row
    monkeypatch.setattr(recorder.win32gui, 'GetWindowRect', lambda handle: (0, 0, 800, 600))
    recorder._row_labels.clear()


def test_row_label_is_the_unique_element_on_the_left(monkeypatch):
    label = _FakeUIElement(WINDOW + '->Form||Group->Email:||Text', 20, 50, 90, 70)
    container = _FakeUIElement(WINDOW + '->Form||Group', 90, 0, 120, 400)  # taller than the row: skipped
    other_edit = _FakeUIElement(WINDOW + '->Form||Group->||Edit', 120, 50, 250, 70)
    edit = _FakeUIElement(WINDOW + '->Form||Group->||Edit', 300, 50, 450, 70)
    _fake_row(monkeypatch, [label, container, other_edit, edit])
    found = recorder._find_row_label(edit, edit.path + '#[1,1]', 1)
    assert found == {'uipath': label.path, 'name': 'Email:', 'control_type': 'Text'}
    # The elements of the same row share their label: read once
    monkeypatch.setattr(recorder._desktop, 'from_point', lambda x, y: pytest.fail('searched again'), raising=False)
    assert recorder._find_row_label(edit, edit.path + '#[1,1]', 1) == found


def test_no_row_label_when_nothing_unique_is_on_the_left(monkeypatch):
    first_edit = _FakeUIElement(WINDOW + '->Form||Group->||Edit', 20, 50, 250, 70)
    edit = _FakeUIElement(WINDOW + '->Form||Group->||Edit', 300, 50, 450, 70)
    _fake_row(monkeypatch, [first_edit, edit])
    assert recorder._find_row_label(edit, edit.path + '#[1,1]', 1) is None


@pytest.fixture
def qt_app(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    from pywinauto_recorder.control_panel import get_application
    return get_application()


def test_step_editor_saves_edited_steps(qt_app, tmp_path, monkeypatch):
    from pywinauto_recorder import step_editor
    copied = []
    monkeypatch.setattr(step_editor.pyperclip, 'copy', copied.append)  # leaves the clipboard of the user alone
    actions = [_get_action(e, 0) for e in _sample_events()]
    recording = {'recorded_at': '2026-10-28T10:00:00', 'options': {}, 'actions': actions}
    update_recording(recording)
    file_name = tmp_path / 'recording.json'
    file_name.write_text(json.dumps(recording), encoding='utf-8')

    editor = step_editor.StepEditor(file_name)
    assert editor.list.count() == 4
    editor.list.setCurrentRow(1)
    editor.delete_step()
    editor.list.setCurrentRow(0)
    editor.add_note()
    editor.note_edit.setPlainText('Check the dialog is closed')
    editor.notes.setPlainText('Says hi in Notepad')
    assert editor.save()

    saved = json.loads(file_name.read_text(encoding='utf-8'))
    assert [a['action'] for a in saved['actions']] == ['click', 'note', 'send_keys', 'note']
    assert saved['notes'] == 'Says hi in Notepad'
    assert list(saved).index('notes') == list(saved).index('recorded_at') + 1
    assert '# Check the dialog is closed\n' in saved['pywinauto_recorder_script']
    assert copied and json.loads(copied[-1]) == saved
    editor.close()

