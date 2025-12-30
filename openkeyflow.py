"""Convenience launcher for OpenKeyFlow."""
from __future__ import annotations

import importlib.util
import platform
import sys
from backend import hooks

def _ensure_dependencies() -> None:

    required = ["PyQt5", "pyperclip", *hooks.required_packages()]
    missing = [name for name in required if importlib.util.find_spec(name) is None]

    if missing:
        joined = ", ".join(sorted(set(missing)))
        backend_name = hooks.selected_backend_name()
        requirements_file = "requirements.txt"
        if backend_name == "keyboard":
            requirements_file = "requirements-windows.txt"
        elif backend_name == "pynput":
            if platform.system() == "Darwin":
                requirements_file = "requirements-macos.txt"
            else:
                requirements_file = "requirements-linux.txt"
        command = f"{sys.executable} -m pip install -r {requirements_file}"
        sys.stderr.write(
            "Required packages missing: "
            f"{joined}.\n"
            "Install them for this interpreter with:\n"
            f"  {command}\n"
        )
        sys.exit(1)

def main() -> None:
    _ensure_dependencies()
    from app.main import main as app_main

    app_main()

if __name__ == "__main__":
    main()
