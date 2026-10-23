# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:\\luya\\script_tools\\adb_tool\\adb_screenshot_tool.py'],
    pathex=[],
    binaries=[('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\adb.exe', 'platform-tools'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\AdbWinApi.dll', 'platform-tools'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\AdbWinUsbApi.dll', 'platform-tools'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\avcodec-61.dll', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\avformat-61.dll', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\avutil-59.dll', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\libusb-1.0.dll', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\scrcpy.exe', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\SDL2.dll', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\swresample-5.dll', 'scrcpy')],
    datas=[('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\icon.png', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\open_a_terminal_here.bat', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\scrcpy-console.bat', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\scrcpy-noconsole.vbs', 'scrcpy'), ('D:\\luya\\script_tools\\adb_tool\\vendor\\scrcpy\\scrcpy-win64-v3.3.3\\scrcpy-server', 'scrcpy')],
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
    name='adb_screenshot_tool_embedded',
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
