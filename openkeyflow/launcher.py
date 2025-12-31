"""OpenKeyFlow startup helpers."""
from __future__ import annotations

import importlib.util
import os
import platform
import sys
from typing import Iterable, Sequence
from backend import hooks

BASE_REQUIRED_IMPORTS: Sequence[str] = (
    "PyQt5",
    "pyperclip",
    "PIL",
    "cryptography",
    "platformdirs",
)

LINUX_GLOBAL_HOTKEY_REQUIREMENTS: Sequence[str] = (
    "build-essential",
    "python3-dev",
    "libevdev-dev",
    "libudev-dev",
    "linux headers",
)

MACOS_GLOBAL_HOTKEY_REQUIREMENTS: Sequence[str] = (
    "Input Monitoring permission",
    "Accessibility permission",
)

def _is_linux() -> bool:
    return sys.platform.startswith("linux")

def _is_macos() -> bool:
    return sys.platform == "darwin"

def _in_virtualenv() -> bool:
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)

def _format_list(items: Iterable[str]) -> str:
    return "\n".join(f" - {item}" for item in items)

def _warn(message: str) -> None:
    sys.stderr.write(f"{message}\n")

def _requirements_file() -> str:
    backend_name = hooks.selected_backend_name()
    if backend_name == "keyboard":
        return "requirements-windows.txt"
    if backend_name == "pynput":
        if platform.system() == "Darwin":
            return "requirements-macos.txt"
        return "requirements-linux.txt"
    return "requirements.txt"

def _check_dependencies() -> None:
    required = list(BASE_REQUIRED_IMPORTS) + hooks.required_packages()
    missing = [name for name in required if importlib.util.find_spec(name) is None]
    if missing:
        joined = ", ".join(sorted(set(missing)))
        _warn("Required packages missing:")
        _warn(f"  {joined}")
        _warn("Install them for this interpreter with:")
        _warn(f"  {sys.executable} -m pip install -r {_requirements_file()}")
        raise SystemExit(1)

def _check_root_warning() -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        _warn("Warning: running as root is not recommended for desktop apps.")

def _check_linux_preflight() -> None:
    if not _is_linux():
        return

    _warn("Linux detected.")
    _warn("Global keyboard hooks require:")
    _warn(_format_list(LINUX_GLOBAL_HOTKEY_REQUIREMENTS))
    _warn("See README -> Linux setup")

    _check_root_warning()

    if not _in_virtualenv():
        _warn("Tip: use a virtual environment to isolate dependencies.")

    if importlib.util.find_spec("grp") is None:
        return

    import grp

    try:
        input_group = grp.getgrnam("input")
    except KeyError:
        _warn("Warning: input group not found; global hotkeys may not work.")
        return

    user = os.environ.get("SUDO_USER") or os.environ.get("USER")
    if not user:
        return

    groups = {g.gr_name for g in grp.getgrall() if user in g.gr_mem}
    if input_group.gr_name not in groups:
        _warn("Warning: add your user to the input group for global hotkeys:")
        _warn(f"  sudo usermod -aG input {user}")
        _warn("  (log out/in required)")

def _check_macos_preflight() -> None:
    if not _is_macos():
        return

    _warn("macOS detected.")
    _warn("Global keyboard hooks require:")
    _warn(_format_list(MACOS_GLOBAL_HOTKEY_REQUIREMENTS))
    _warn("See README -> macOS setup")

    _check_root_warning()

    if not _in_virtualenv():
        _warn(
            "Note: We recommend using an venv to isolate dependencies if running OKF from source."
        )
def main() -> None:
    _check_linux_preflight()
    _check_macos_preflight()
    _check_dependencies()

    from app.main import main as app_main

    _warn(f"Launching OpenKeyFlow on {platform.system()}...")
    app_main()
__all__ = ["main"]