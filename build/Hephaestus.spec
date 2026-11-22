# -*- mode: python ; coding: utf-8 -*-
"""Hephaestus V1.2.1 Windows 桌面端 PyInstaller 配置。

用法：
    python -m PyInstaller --noconfirm --clean build/Hephaestus.spec          # onedir
    ￥env:HEPHAESTUS_ONEFILE=1; python -m PyInstaller --noconfirm --clean build/Hephaestus.spec   # onefile

产物：
    onedir  -> dist/Hephaestus/Hephaestus.exe
    onefile -> dist/Hephaestus.exe
"""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent          # noqa: F821 - PyInstaller 注入
ICON = ROOT / "desktop" / "assets" / "Hephaestus.ico"
ONE_FILE = os.environ.get("HEPHAESTUS_ONEFILE") == "1"

hiddenimports = [
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "webview.platforms.edgechromium",
    "webview.platforms.winforms",
    "clr_loader",
]

a = Analysis(
    [str(ROOT / "desktop_launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "static"), "static")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "PIL"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries if ONE_FILE else [],
    a.datas if ONE_FILE else [],
    [],
    name="Hephaestus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON) if ICON.is_file() else None,
    version=str(ROOT / "build" / "version_info.txt"),
)

if not ONE_FILE:
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="Hephaestus",
    )
