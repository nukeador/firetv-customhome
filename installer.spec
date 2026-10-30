# PyInstaller spec: omit installation records and SBOMs containing build-machine paths.
import sys
a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('assets/tvhome.apk', 'assets'), ('assets/smarttube-marker.apk', 'assets'),
           ('assets/sha256.json', 'assets'), ('assets/kara-home-only.bsdiff', 'assets'),
           ('assets/sheldonp-5746-home-only.bsdiff', 'assets')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
a.datas = [entry for entry in a.datas
           if not entry[0].replace('\\', '/').endswith('.dist-info/RECORD')
           and '.dist-info/sboms/' not in entry[0].replace('\\', '/')]
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [], name='firetv-customhome',
    debug=False, bootloader_ignore_signals=False, strip=sys.platform != 'win32', upx=True,
    upx_exclude=[], runtime_tmpdir=None, console=True,
    disable_windowed_traceback=False, argv_emulation=False,
    target_arch=None, codesign_identity=None, entitlements_file=None,
)
