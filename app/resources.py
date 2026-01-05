"""Resource helpers for application paths."""
from __future__ import annotations

import sys
from pathlib import Path

def resource_path(relative_path: str | Path) -> Path:
    base = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
    return base / relative_path