# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\luya\\script_tools\\adb_tool\\adb_screenshot_tool.py'],
    pathex=[],
    binaries=[('C:\\platform-tools\\adb.exe', 'platform-tools'), ('C:\\platform-tools\\AdbWinApi.dll', 'platform-tools'), ('C:\\platform-tools\\AdbWinUsbApi.dll', 'platform-tools')],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='adb_screenshot_tool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
