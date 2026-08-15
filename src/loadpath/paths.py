from __future__ import annotations

import sys
from pathlib import Path


def package_dir() -> Path:
    """Directory that holds Loadpath package data (static UI, report templates)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass) / "loadpath"
    return Path(__file__).resolve().parent
