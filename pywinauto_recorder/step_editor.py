"""
The window editing the steps of a recording (a JSON file of the recorder): reorder, delete and change them, and add
notes, for the reader of the file (e.g. an AI agent writing an automation script from it) and as comments in the
script. The dialog asking for a note while recording is here too.
"""

import ctypes
import html
import json
from pathlib import Path
import pyperclip
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QKeySequence, QShortcut
from PyQt6.QtWidgets import QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, \
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QSpinBox, QSplitter, \
    QVBoxLayout, QWidget
from .control_panel import icon
from .core import get_entry, get_entry_list
from .recorder import update_recording

__all__ = ['NoteDialog', 'StepEditor', 'describe_action']

EDITOR_STYLE_SHEET = """
QWidget { background: #2b2b2b; color: #e8e8e8; font: 9pt "Segoe UI"; }
QLabel#title { font: 11pt "Segoe UI Semibold"; color: #ffffff; }
QLabel#hint, QLabel#saved { color: #8a8a8a; font: 8pt "Segoe UI"; }
QLabel#element { color: #b8cfe0; }
QListWidget { background: #1e1e1e; border: 1px solid #505050; border-radius: 4px; outline: none; }
QListWidget::item { padding: 5px 6px; border-bottom: 1px solid #333333; }
QListWidget::item:selected { background: #34495a; color: #ffffff; }
QLineEdit, QPlainTextEdit, QSpinBox, QComboBox { background: #1e1e1e; border: 1px solid #505050; border-radius: 4px;
                                                  padding: 4px; selection-background-color: #4aa3f0; }
QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: #4aa3f0; }
QLineEdit#code { font: 9pt "Consolas"; }
QComboBox QAbstractItemView { background: #1e1e1e; border: 1px solid #505050; }
QPushButton { color: #f0f0f0; background: #3c3c3c; border: 1px solid #505050; border-radius: 4px;
              padding: 5px 14px; min-width: 60px; }
QPushButton#icon_only { padding: 5px 8px; min-width: 0; }
QPushButton:hover { background: #474747; }
QPushButton:disabled { color: #707070; }
QPushButton:default { border-color: #4aa3f0; }
QSplitter::handle { background: transparent; }
QToolTip { background: #1e2a33; color: #e0ecf5; border: 1px solid #34495a; padding: 4px; }
"""

ACTION_NAMES = {
    'click': 'Click', 'send_keys': 'Type', 'mouse_wheel': 'Scroll', 'drag_and_drop': 'Drag and drop',
    'find': 'Find', 'menu_click': 'Menu', 'note': 'Note'}
NOTE_HINT = ('For the reader of the recording (e.g. an AI agent): what to wait for, what changes from one run to '
             'another, why this is done...')
KEYS_HINT = ('pywinauto send_keys syntax: {ENTER}, {TAB}, {VK_LCONTROL down}c{VK_LCONTROL up}...; '
             'type ^ % ~ { } as {^} {%} {~} {{} {}}')


def _element_name(uipath, element=None):
    """:return: The name of the element at the end of a path, or what tells it apart, and its control type"""
    try:
        name, control_type, _, _ = get_entry(get_entry_list(uipath)[-1])
    except Exception:
        return uipath or '', ''
    element = element or {}
    if not name:
        automation_id = element.get('automation_id') or ''
        name = automation_id if automation_id and not automation_id.isdigit() else ''
    return name.strip(), control_type or element.get('control_type') or ''


def _window_name(uipath):
    try:
        name, control_type, _, _ = get_entry(get_entry_list(uipath)[0])
        return name.strip() or control_type
    except Exception:
        return ''


def describe_action(action):
    """:return: A one-line description of an action of the JSON file"""
    kind = action.get('action')
    if kind == 'click':
        name, control_type = _element_name(action.get('uipath'), action.get('element'))
        click = ['', 'Click', 'Double click', 'Triple click'][min(action.get('click_count', 1), 3)]
        if action.get('button', 'left') != 'left':
            click = action['button'].capitalize() + ' ' + click.lower()
        text = f'{click} {name} {control_type}'.replace('  ', ' ')
        window = _window_name(action.get('uipath'))
        return text + (f'  ·  {window}' if window and window != name else '')
    if kind == 'send_keys':
        return 'Type  ' + action.get('keys', '')
    if kind == 'mouse_wheel':
        return f"Scroll {action.get('delta')}"
    if kind == 'drag_and_drop':
        start, end = action.get('from') or {}, action.get('to') or {}
        return 'Drag {} to {}'.format(
            ' '.join(_element_name(start.get('uipath'), start.get('element'))),
            ' '.join(_element_name(end.get('uipath'), end.get('element'))))
    if kind == 'find':
        return 'Find ' + ' '.join(_element_name(action.get('uipath'), action.get('element')))
    if kind == 'menu_click':
        return f"Menu {action.get('menu_path', '').replace('->', ' › ')}  ·  {_window_name(action.get('window'))}"
    if kind == 'note':
        return '✎ ' + ((action.get('note') or '').strip().splitlines() or [''])[0]
    return kind or '?'


def _element_summary(element):
    """:return: The HTML of the main properties of the element of an action"""
    if not element:
        return ''
    keys = ('name', 'control_type', 'automation_id', 'class_name', 'process_name', 'value')
    return '<br>'.join(
        f'<span style="color:#8a8a8a">{key.replace("_", " ")}</span>&nbsp; {html.escape(str(element[key]))}'
        for key in keys if element.get(key) not in (None, ''))


def _force_foreground(widget):
    """
    Windows only lets the foreground application activate a window: the recorder asks for a note while the user is
    in another application, so its input is attached to the one of the foreground window for a moment.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = int(widget.winId())
        foreground_thread = user32.GetWindowThreadProcessId(user32.GetForegroundWindow(), None)
        own_thread = ctypes.windll.kernel32.GetCurrentThreadId()
        attached = foreground_thread != own_thread and user32.AttachThreadInput(own_thread, foreground_thread, True)
        try:
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(own_thread, foreground_thread, False)
    except Exception:
        pass
    widget.activateWindow()
    widget.raise_()


class _NoteEdit(QPlainTextEdit):
    """A note: Enter validates it, as in a single-line field, and Shift+Enter starts a new line."""
    def __init__(self, on_enter):
        super().__init__()
        self.on_enter = on_enter

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and \
                not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self.on_enter()
        else:
            super().keyPressEvent(event)


class NoteDialog(QDialog):
    """Asks for a note while recording. The recorder doesn't record the keys typed in it."""
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Dialog)
        self.setWindowTitle('Add a note to the recording')
        self.setStyleSheet(EDITOR_STYLE_SHEET)
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Note', objectName='title'))
        hint = QLabel(NOTE_HINT + '\nEnter adds it, Shift+Enter starts a new line.', objectName='hint', wordWrap=True)
        layout.addWidget(hint)
        self.edit = _NoteEdit(self.accept)
        self.edit.setFixedHeight(90)
        layout.addWidget(self.edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Add note')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, lambda: (_force_foreground(self), self.edit.setFocus()))

    def text(self):
        return self.edit.toPlainText().strip()


class StepEditor(QWidget):
    """
    Edits the steps of a recording: the list on the left (drag a step to move it), the selected step on the right.
    Saving writes the code of the actions and the script again, and copies the JSON to the clipboard like a recording.
    """
    def __init__(self, file_name):
        super().__init__(None, Qt.WindowType.Window)
        self.file_name = Path(file_name)
        self.recording = json.loads(self.file_name.read_text(encoding='utf-8'))
        self.actions = {}  # by key, the key being the data of the items of the list
        self._next_key = 0
        self._dirty = False
        self._loading = False
        self.setWindowTitle('Steps · ' + self.file_name.name)
        self.setStyleSheet(EDITOR_STYLE_SHEET)
        self.resize(980, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        layout.addWidget(QLabel(html.escape(self.file_name.name), objectName='title'))
        layout.addWidget(QLabel('Notes about the whole recording, e.g. what it does and what its inputs are',
                                objectName='hint'))
        self.notes = QPlainTextEdit(placeholderText='e.g. Opens Production Coach, logs in and imports a work order. '
                                                    'The work order name is an input.')
        self.notes.setFixedHeight(64)
        self.notes.setPlainText(self.recording.get('notes', ''))
        self.notes.textChanged.connect(self._set_dirty)
        layout.addWidget(self.notes)

        splitter = QSplitter()
        layout.addWidget(splitter, 1)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(self._show_step)
        self.list.model().rowsMoved.connect(self._on_moved)
        left_layout.addWidget(self.list, 1)
        buttons = QHBoxLayout()
        self.btn_up = self._button(buttons, '', self.move_up, 'Move the step up (Alt+Up)', 'ph.arrow-up')
        self.btn_down = self._button(buttons, '', self.move_down, 'Move the step down (Alt+Down)', 'ph.arrow-down')
        self._button(buttons, 'Add note', self.add_note, 'Add a note after the selected step (Ctrl+N)', 'ph.note-pencil')
        self.btn_delete = self._button(buttons, 'Delete', self.delete_step, 'Delete the selected step (Delete)',
                                       'ph.trash')
        for button in (self.btn_up, self.btn_down):
            button.setObjectName('icon_only')
        buttons.addStretch()
        left_layout.addLayout(buttons)
        splitter.addWidget(left)

        self.detail = QWidget()
        detail_layout = QVBoxLayout(self.detail)
        detail_layout.setContentsMargins(8, 0, 0, 0)
        self.form = QFormLayout()
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        detail_layout.addLayout(self.form)
        detail_layout.addStretch()
        splitter.addWidget(self.detail)
        splitter.setSizes([520, 460])

        bottom = QHBoxLayout()
        self.saved = QLabel(objectName='saved')
        bottom.addWidget(self.saved, 1)
        self._button(bottom, 'Save', self.save, 'Save the file and copy it to the clipboard (Ctrl+S)',
                     'ph.floppy-disk').setDefault(True)
        self._button(bottom, 'Close', self.close, 'Close the editor', 'ph.x')
        layout.addLayout(bottom)

        for keys, slot in (('Ctrl+S', self.save), ('Ctrl+N', self.add_note), ('Alt+Up', self.move_up),
                           ('Alt+Down', self.move_down)):
            QShortcut(QKeySequence(keys), self, slot)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self.list, self.delete_step,
                  context=Qt.ShortcutContext.WidgetShortcut)

        for action in self.recording.get('actions', []):
            self._add_item(action)
        if self.list.count():
            self.list.setCurrentRow(0)
        self._show_step(self.list.currentItem())

    @staticmethod
    def _button(layout, text, slot, tooltip, icon_name=None):
        button = QPushButton(text, toolTip=tooltip, autoDefault=False)
        if icon_name:
            button.setIcon(icon(icon_name, beside_text=bool(text)))
        button.clicked.connect(slot)
        layout.addWidget(button)
        return button

    # The list of steps

    def _add_item(self, action, row=None):
        key = self._next_key
        self._next_key += 1
        self.actions[key] = action
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, key)
        if row is None:
            self.list.addItem(item)
        else:
            self.list.insertItem(row, item)
        self._renumber()
        return item

    def _action(self, item):
        return self.actions[item.data(Qt.ItemDataRole.UserRole)] if item is not None else None

    def _ordered_actions(self):
        return [self._action(self.list.item(row)) for row in range(self.list.count())]

    def _renumber(self):
        for row in range(self.list.count()):
            item = self.list.item(row)
            action = self._action(item)
            text = f'{row + 1}.  {describe_action(action)}'
            note = (action.get('note') or '').strip() if action.get('action') != 'note' else ''
            if note:
                text += '\n      ✎ ' + note.splitlines()[0]
            item.setText(text)
            item.setForeground(QColor('#f0c040' if action.get('action') == 'note' else '#e8e8e8'))
            item.setToolTip(action.get('pywinauto_recorder_code') or '')
        row = self.list.currentRow()
        self.btn_up.setEnabled(row > 0)
        self.btn_down.setEnabled(0 <= row < self.list.count() - 1)
        self.btn_delete.setEnabled(row >= 0)

    def _on_moved(self, *_):
        self._set_dirty()
        self._renumber()

    def move_up(self):
        self._move(-1)

    def move_down(self):
        self._move(1)

    def _move(self, offset):
        row = self.list.currentRow()
        if row < 0 or not 0 <= row + offset < self.list.count():
            return
        item = self.list.takeItem(row)
        self.list.insertItem(row + offset, item)
        self.list.setCurrentItem(item)
        self._on_moved()

    def delete_step(self):
        row = self.list.currentRow()
        if row < 0:
            return
        item = self.list.takeItem(row)
        del self.actions[item.data(Qt.ItemDataRole.UserRole)]
        self._set_dirty()
        self._renumber()
        self._show_step(self.list.currentItem())

    def add_note(self):
        row = self.list.currentRow()
        item = self._add_item({'action': 'note', 'note': ''}, row + 1 if row >= 0 else self.list.count())
        self.list.setCurrentItem(item)
        self._set_dirty()
        if self.note_edit:
            self.note_edit.setFocus()

    # The selected step

    def _show_step(self, item, *_):
        self._loading = True
        while self.form.rowCount():
            self.form.removeRow(0)
        self.note_edit = None
        action = self._action(item)
        if action is None:
            self.form.addRow(QLabel('No step', objectName='hint'))
            self._loading = False
            self._renumber()
            return
        kind = action.get('action')
        header = ACTION_NAMES.get(kind, kind)
        if action.get('time') is not None:
            header += f'  <span style="color:#8a8a8a; font-size:8pt">at {action["time"]:.1f} s</span>'
        self.form.addRow(QLabel(header, objectName='title', textFormat=Qt.TextFormat.RichText))

        self.note_edit = QPlainTextEdit(placeholderText=NOTE_HINT)
        self.note_edit.setPlainText(action.get('note', ''))
        self.note_edit.setFixedHeight(110 if kind == 'note' else 70)
        self.note_edit.textChanged.connect(lambda: self._set(action, 'note', self.note_edit.toPlainText()))
        self.form.addRow('Note', self.note_edit)

        if kind == 'click':
            self._add_line_edit('UI path', action, 'uipath')
            button = QComboBox()
            button.addItems(['left', 'right', 'middle'])
            button.setCurrentText(action.get('button', 'left'))
            button.currentTextChanged.connect(lambda text: self._set(action, 'button', text))
            self.form.addRow('Button', button)
            self._add_spin_box('Clicks', action, 'click_count', 1, 3)
        elif kind == 'send_keys':
            self._add_line_edit('Keys', action, 'keys', KEYS_HINT)
            self.form.addRow('', QLabel(KEYS_HINT, objectName='hint', wordWrap=True))
        elif kind == 'mouse_wheel':
            self._add_spin_box('Delta', action, 'delta', -100, 100)
        elif kind == 'drag_and_drop':
            self._add_line_edit('From', action.setdefault('from', {}), 'uipath')
            self._add_line_edit('To', action.setdefault('to', {}), 'uipath')
        elif kind == 'find':
            self._add_line_edit('UI path', action, 'uipath')
        elif kind == 'menu_click':
            self._add_line_edit('Window', action, 'window')
            self._add_line_edit('Menu path', action, 'menu_path', "Menu items joined by '->', e.g. File->Save")

        element = action.get('element') or (action.get('from') or {}).get('element')
        if kind == 'menu_click' and action.get('elements'):
            element = action['elements'][-1]
        summary = _element_summary(element)
        if summary:
            self.form.addRow('Element', QLabel(summary, objectName='element', wordWrap=True,
                                               textFormat=Qt.TextFormat.RichText))
        self.code = QLabel(objectName='hint', wordWrap=True, textFormat=Qt.TextFormat.RichText,
                           textInteractionFlags=Qt.TextInteractionFlag.TextSelectableByMouse)
        self.form.addRow('Code', self.code)
        self._show_code(action)
        self._loading = False
        self._renumber()

    def _add_line_edit(self, label, target, key, tooltip=''):
        edit = QLineEdit(str(target.get(key, '')), objectName='code', toolTip=tooltip)
        edit.textChanged.connect(lambda text: self._set(target, key, text))
        self.form.addRow(label, edit)

    def _add_spin_box(self, label, action, key, minimum, maximum):
        spin_box = QSpinBox(minimum=minimum, maximum=maximum, value=int(action.get(key, minimum)))
        spin_box.valueChanged.connect(lambda value: self._set(action, key, value))
        self.form.addRow(label, spin_box)

    def _show_code(self, action):
        update_recording({'options': self.recording.get('options'), 'actions': [action]})
        self.code.setText(html.escape(action.get('pywinauto_recorder_code', '')).replace('\n', '<br>') or
                          '<i>a comment in the script</i>')

    def _set(self, target, key, value):
        if self._loading:
            return
        target[key] = value
        if key == 'note' and not value.strip() and target.get('action') != 'note':
            del target[key]  # an empty note isn't written
        self._set_dirty()
        self._renumber()
        action = self._action(self.list.currentItem())
        if action is not None:
            self._show_code(action)

    # Saving

    def _set_dirty(self, *_):
        if self._loading:
            return
        self._dirty = True
        self.saved.setText('Not saved')

    def save(self):
        for row in reversed(range(self.list.count())):  # the empty notes aren't saved
            action = self._action(self.list.item(row))
            if action.get('action') == 'note' and not (action.get('note') or '').strip() and \
                    row != self.list.currentRow():
                del self.actions[self.list.takeItem(row).data(Qt.ItemDataRole.UserRole)]
        self._renumber()
        recording = {}
        notes = self.notes.toPlainText().strip()
        for key, value in self.recording.items():
            if key == 'notes':
                continue
            recording[key] = value
            if key == 'recorded_at' and notes:
                recording['notes'] = notes  # near the top, where the reader sees it first
        if notes and 'notes' not in recording:
            recording['notes'] = notes
        recording['actions'] = [
            action for action in self._ordered_actions()
            if action.get('action') != 'note' or (action.get('note') or '').strip()]
        update_recording(recording)
        text = json.dumps(recording, indent='\t', ensure_ascii=False, default=str)
        try:
            self.file_name.write_text(text, encoding='utf-8')
        except OSError as error:
            QMessageBox.critical(self, 'Save failed', str(error))
            return False
        pyperclip.copy(text)
        self.recording = recording
        self._dirty = False
        self.saved.setText('Saved and copied to the clipboard')
        return True

    def closeEvent(self, event):
        if self._dirty:
            answer = QMessageBox.question(
                self, 'Unsaved changes', 'Save the changes to the steps?',
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard |
                QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel or \
                    (answer == QMessageBox.StandardButton.Save and not self.save()):
                event.ignore()
                return
        event.accept()
