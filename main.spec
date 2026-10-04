# -*- mode: python ; coding: utf-8 -*-


a_main = Analysis(
    ['src\\win_binary\\main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz_main = PYZ(a_main.pure)
exe_main = EXE(
    pyz_main,
    a_main.scripts,
    [],
    exclude_binaries=True,
    name='main',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

a_console = Analysis(
    ['src\\win_binary\\console.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz_console = PYZ(a_console.pure)
exe_console = EXE(
    pyz_console,
    a_console.scripts,
    [],
    exclude_binaries=True,
    name='console',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe_main,
    a_main.binaries,
    a_main.datas,

    exe_console,
    a_console.binaries,
    a_console.datas,

    strip=False,
    upx=True,
    upx_exclude=[],
    name='main',
)
