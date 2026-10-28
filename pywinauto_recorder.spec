# PyInstaller spec: builds the self-contained dist\pywinauto_recorder.exe (one file, no Python needed).
# Build with build_exe.bat, or: .venv\Scripts\python.exe -m PyInstaller --noconfirm --clean pywinauto_recorder.spec
import re
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import FixedFileInfo, StringFileInfo, StringStruct, StringTable, \
    VarFileInfo, VarStruct, VSVersionInfo

root = Path(SPECPATH)
version = re.search(r'__version__ = "(.+)"', (root / 'pywinauto_recorder' / '__init__.py').read_text()).group(1)
version_tuple = tuple(int(n) for n in (version.split('.') + ['0'] * 4)[:4])
icon_file = str(root / 'pywinauto_recorder' / 'Icons' / 'IconPyRec.ico')

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'Pywinauto Recorder'),
            StringStruct('FileDescription', 'Pywinauto Recorder'),
            StringStruct('FileVersion', version),
            StringStruct('InternalName', 'pywinauto_recorder'),
            StringStruct('OriginalFilename', 'pywinauto_recorder.exe'),
            StringStruct('ProductName', 'Pywinauto Recorder'),
            StringStruct('ProductVersion', version),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)

a = Analysis(
    [str(root / 'pywinauto_recorder.py')],
    pathex=[str(root)],
    # _application_icon looks for Icons\IconPyRec.ico next to the package modules
    datas=[(icon_file, 'pywinauto_recorder/Icons')],
    # Replayed scripts are exec'd by the exe and can use any part of the replay API and of pywinauto
    hiddenimports=collect_submodules('pywinauto_recorder') + collect_submodules('pywinauto'),
    excludes=['tkinter', 'pytest', 'setuptools'],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='pywinauto_recorder',
    icon=icon_file,
    version=version_info,
    # No console window: the output goes to ~\Pywinauto recorder\pywinauto_recorder.log (see pywinauto_recorder.py)
    console=False,
    upx=False,
    runtime_tmpdir=None,
)
