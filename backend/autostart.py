"""Platform-specific autostart helpers."""
from __future__ import annotations

import os
import platform
import plistlib
import sys
from pathlib import Path
from typing import Tuple

APP_NAME = "OpenKeyFlow"
LINUX_AUTOSTART_NAME = "openkeyflow.desktop"
MAC_PLIST_NAME = "com.exoteriklabs.openkeyflow.plist"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _exec_command() -> list[str]:
    return [sys.executable, "-m", "app"]


def status() -> Tuple[bool, str | None]:
    system = platform.system()
    if system == "Windows":
        shortcut = _windows_startup_shortcut()
        return shortcut.exists(), None
    if system == "Linux":
        desktop = _linux_autostart_file()
        return desktop.exists(), None
    if system == "Darwin":
        plist = _mac_plist_path()
        return plist.exists(), None
    return False, "Autostart is not supported on this platform."


def enable() -> Tuple[bool, str | None]:
    system = platform.system()
    if system == "Windows":
        return _enable_windows()
    if system == "Linux":
        return _enable_linux()
    if system == "Darwin":
        return _enable_macos()
    return False, "Autostart is not supported on this platform."


def disable() -> Tuple[bool, str | None]:
    system = platform.system()
    if system == "Windows":
        return _disable_windows()
    if system == "Linux":
        return _disable_linux()
    if system == "Darwin":
        return _disable_macos()
    return False, "Autostart is not supported on this platform."


def _windows_startup_shortcut() -> Path:
    appdata = Path(os.environ.get("APPDATA", ""))
    startup_dir = appdata / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return startup_dir / f"{APP_NAME}.lnk"


def _enable_windows() -> Tuple[bool, str | None]:
    try:
        from win32com.client import Dispatch  # type: ignore
    except Exception as exc:
        return False, f"pywin32 is not available: {exc}"
    shortcut = _windows_startup_shortcut()
    try:
        shortcut.parent.mkdir(parents=True, exist_ok=True)
        shell = Dispatch("WScript.Shell")
        link = shell.CreateShortcut(str(shortcut))
        link.TargetPath = str(Path(sys.executable))
        link.Arguments = "-m app"
        link.WorkingDirectory = str(_project_root())
        link.IconLocation = link.TargetPath
        link.save()
        return True, None
    except Exception as exc:  # pragma: no cover - Windows only
        return False, str(exc)


def _disable_windows() -> Tuple[bool, str | None]:
    shortcut = _windows_startup_shortcut()
    if not shortcut.exists():
        return True, None
    try:
        shortcut.unlink()
        return True, None
    except Exception as exc:  # pragma: no cover - Windows only
        return False, str(exc)


def _linux_autostart_file() -> Path:
    return Path.home() / ".config" / "autostart" / LINUX_AUTOSTART_NAME


def _enable_linux() -> Tuple[bool, str | None]:
    desktop_file = _linux_autostart_file()
    try:
        desktop_file.parent.mkdir(parents=True, exist_ok=True)
        exec_cmd = " ".join(_exec_command())
        content = (
            "[Desktop Entry]\n"
            "Type=Application\n"
            f"Name={APP_NAME}\n"
            f"Exec={exec_cmd}\n"
            f"Path={_project_root()}\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
        desktop_file.write_text(content, encoding="utf-8")
        return True, None
    except Exception as exc:
        return False, str(exc)


def _disable_linux() -> Tuple[bool, str | None]:
    desktop_file = _linux_autostart_file()
    if not desktop_file.exists():
        return True, None
    try:
        desktop_file.unlink()
        return True, None
    except Exception as exc:
        return False, str(exc)


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / MAC_PLIST_NAME


def _enable_macos() -> Tuple[bool, str | None]:
    plist_path = _mac_plist_path()
    try:
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "Label": "com.exoteriklabs.openkeyflow",
            "ProgramArguments": _exec_command(),
            "WorkingDirectory": str(_project_root()),
            "RunAtLoad": True,
            "KeepAlive": False,
        }
        with plist_path.open("wb") as handle:
            plistlib.dump(data, handle)
        return True, None
    except Exception as exc:
        return False, str(exc)


def _disable_macos() -> Tuple[bool, str | None]:
    plist_path = _mac_plist_path()
    if not plist_path.exists():
        return True, None
    try:
        plist_path.unlink()
        return True, None
    except Exception as exc:
        return False, str(exc)
