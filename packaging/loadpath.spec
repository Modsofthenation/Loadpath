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

REQUIRED_PACKAGES = (
    "loadpath",
    "mcp",
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_settings",
    "anyio",
    "httpx",
    "jinja2",
    "typer",
    "rich",
    "click",
    "yaml",
)
OPTIONAL_PACKAGES = (
    "pydantic_core",
    "httpcore",
    "multipart",
    "sse_starlette",
    "jsonschema",
    "httptools",
    "websockets",
    "watchfiles",
    "dotenv",
    "uvloop",
)


def _collect(pkg: str, required: bool) -> None:
    global datas, binaries, hiddenimports
    try:
        pkg_datas, pkg_binaries, pkg_hidden = collect_all(pkg)
    except Exception:
        if required:
            raise
        return
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hidden


for pkg in REQUIRED_PACKAGES:
    _collect(pkg, required=True)
for pkg in OPTIONAL_PACKAGES:
    _collect(pkg, required=False)

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
