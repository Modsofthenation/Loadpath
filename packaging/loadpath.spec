# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the Loadpath sidecar used by the Electron app."""

from __future__ import annotations

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = Path(SPECPATH).resolve().parent
SRC = ROOT / "src"

datas: list = []
binaries: list = []
hiddenimports: list = collect_submodules("loadpath")

PACKAGES = (
    "loadpath",
    "mcp",
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "pydantic_core",
    "anyio",
    "httpx",
    "httpcore",
    "jinja2",
    "typer",
    "rich",
    "click",
    "yaml",
    "multipart",
    "sse_starlette",
    "jsonschema",
    "httptools",
    "websockets",
    "watchfiles",
    "dotenv",
    "uvloop",
)

for pkg in PACKAGES:
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:
        continue
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "numpy", "pandas", "playwright", "pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="loadpath",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="loadpath",
)
