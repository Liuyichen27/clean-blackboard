# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：单文件窗口程序。

界面（ui/）和图标（assets/）作为数据文件塞进去，运行时从 _MEIPASS 读。
"""

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = [
    ("ui", "ui"),
    ("assets", "assets"),
]
datas += collect_data_files("webview")

hiddenimports = collect_submodules("webview")
hiddenimports += [
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
    "pythonnet",
]

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "pytest", "PIL"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="白板",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    icon="assets/app.ico",
    version=None,
)
