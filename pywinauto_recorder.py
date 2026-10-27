#!/usr/bin/env python3

from ctypes import wintypes, windll, Structure, POINTER, pointer, WinError
import argparse
from os.path import isfile as os_path_isfile
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
	_show_console_window(6)
	parser = argparse.ArgumentParser()
	parser.add_argument(
		"filename", metavar='path', help="replay a python script", type=str, action='store', nargs='?', default='')
	args = parser.parse_args()
	if args.filename:
		recorder = Recorder()
		if os_path_isfile(args.filename):
			print("Replaying: " + args.filename)
			recorder.playback(filename=args.filename)
		else:
			print("Error: file '" + args.filename + "' not found.")
			input("Press Enter to continue...")
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
