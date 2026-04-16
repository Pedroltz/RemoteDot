# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['agent.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # pynput Windows backend
        'pynput.keyboard._win32',
        'pynput.mouse._win32',
        # python-socketio / engine.io
        'engineio.async_drivers',
        'engineio.async_aiohttp',
        'socketio.async_client',
        'socketio.async_manager',
        # Pillow
        'PIL._imaging',
        'PIL.Image',
        'PIL.ImageGrab',
        # pywin32
        'win32api',
        'win32con',
        'win32gui',
        'win32process',
        # misc
        'pkg_resources.py2_warn',
        'configparser',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'pandas', 'scipy'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # sem janela de console
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
