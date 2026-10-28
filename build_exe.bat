@echo off
REM Builds the self-contained dist\pywinauto_recorder.exe with PyInstaller (see pywinauto_recorder.spec)
cd /d "%~dp0"
set PYTHON_EXE=.venv\Scripts\python.exe
if not exist %PYTHON_EXE% set PYTHON_EXE=python
%PYTHON_EXE% -m pip install -r requirements.txt -r requirements-build.txt || exit /b 1
%PYTHON_EXE% -m PyInstaller --noconfirm --clean pywinauto_recorder.spec || exit /b 1
echo.
echo Built dist\pywinauto_recorder.exe
