#!/usr/bin/env python3

from ctypes import wintypes, windll, Structure, POINTER, pointer, WinError
import argparse
from multiprocessing import freeze_support
from os.path import isfile as os_path_isfile
from pathlib import Path
import sys
from sys import exit as sys_exit
from pywinauto_recorder.recorder import Recorder
from pywinauto_recorder.player import _show_console_window


def get_AC_line_satus():
    class SYSTEM_POWER_STATUS(Structure):
        _fields_ = [
            ('ACLineStatus', wintypes.BYTE),
            ('BatteryFlag', wintypes.BYTE),
            ('BatteryLifePercent', wintypes.BYTE),
            ('Reserved1', wintypes.BYTE),
            ('BatteryLifeTime', wintypes.DWORD),
            ('BatteryFullLifeTime', wintypes.DWORD),
        ]
    SYSTEM_POWER_STATUS_P = POINTER(SYSTEM_POWER_STATUS)
    GetSystemPowerStatus = windll.kernel32.GetSystemPowerStatus
    GetSystemPowerStatus.argtypes = [SYSTEM_POWER_STATUS_P]
    GetSystemPowerStatus.restype = wintypes.BOOL
    status = SYSTEM_POWER_STATUS()
    if not GetSystemPowerStatus(pointer(status)):
        raise WinError()

    return status.ACLineStatus == 1


if __name__ == '__main__':
    # In the compiled exe, the element observer process starts the exe again: run only the process task
    freeze_support()
    if sys.stdout is None or sys.stderr is None:
        # The compiled exe has no console: what the recorder prints goes to a log file (the player flushes stdout)
        log_dir = Path.home() / 'Pywinauto recorder'
        log_dir.mkdir(exist_ok=True)
        log_file = open(log_dir / 'pywinauto_recorder.log', 'w', encoding='utf-8', buffering=1)
        sys.stdout = sys.stdout or log_file
        sys.stderr = sys.stderr or log_file
    _show_console_window(6)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "filename", metavar='path', help="replay a python script", type=str, action='store', nargs='?', default='')
    args = parser.parse_args()
    if args.filename:
        # Qt is only loaded to report an error, so that replaying doesn't wait for it
        def show_error(error):
            from pywinauto_recorder.control_panel import get_application, show_playback_error
            get_application()
            show_playback_error(None, error, blocking=True)

        recorder = Recorder()
        if os_path_isfile(args.filename):
            print("Replaying: " + args.filename)
            recorder.playback(filename=args.filename, on_error=show_error)
        else:
            print("Error: file '" + args.filename + "' not found.")
            from PyQt6.QtWidgets import QMessageBox
            from pywinauto_recorder.control_panel import get_application
            get_application()
            QMessageBox.warning(None, "Pywinauto recorder", "File not found:\n" + args.filename)
        print("Exit")
    else:
        from PyQt6.QtWidgets import QMessageBox
        from pywinauto_recorder.control_panel import get_application, run_control_panel
        get_application()
        if not get_AC_line_satus():
            QMessageBox.warning(
                None, "AC line status is off!",
                "Not plugging your laptop in the AC Power can dramatically slow down Pywinauto Recorder.")
        recorder = Recorder()
        run_control_panel(recorder)
        print("Exit")

    sys_exit(0)
