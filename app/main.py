"""Application entry point for OpenKeyFlow."""
from __future__ import annotations

import sys

from PyQt5 import QtCore, QtWidgets

from backend import storage
from backend.trigger_engine import TriggerEngine
from .main_window import APP_NAME, MainWindow


def main() -> None:
    storage.ensure_data_dir()
    config = storage.load_config()
    
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    profiles_encrypted = storage.profiles_are_encrypted()
    if profiles_encrypted and not config.get("profiles_encrypted"):
        config["profiles_encrypted"] = True
        storage.save_config(config)

    passphrase: str | None = None
    while True:
        try:
            current_profile, profiles = storage.load_profiles(passphrase=passphrase)
            break
        except storage.ProfilesEncryptionError as exc:
            prompt = "Enter your profiles passphrase:"
            if passphrase:
                prompt = "Passphrase incorrect. Try again:"
            passphrase_text, ok = QtWidgets.QInputDialog.getText(
                None,
                "Profiles Locked",
                prompt,
                QtWidgets.QLineEdit.Password,
            )
            if not ok:
                return
            passphrase = passphrase_text.strip()
            if not passphrase:
                QtWidgets.QMessageBox.warning(None, "Profiles Locked", str(exc))
                passphrase = None

    hotkeys = profiles.get(current_profile, {})

    engine = TriggerEngine(
        hotkeys=hotkeys,
        cooldown=float(config.get("cooldown", 0.3)),
        paste_delay=float(config.get("paste_delay", 0.05)),
        use_clipboard=bool(config.get("use_clipboard", True)),
    )

    window = MainWindow(
        engine,
        profile_passphrase=passphrase,
        profiles_encrypted=bool(config.get("profiles_encrypted", False)),
    )
    window.show()

    if engine.hooks_available():
        engine.start()
    else:
        reason = engine.hooks_error() or "Keyboard hooks are unavailable."
        QtWidgets.QMessageBox.warning(
            window,
            "Keyboard Hooks Unavailable",
            "OpenKeyFlow could not initialize the global keyboard hooks.\n\n"
            f"Reason: {reason}\n\n"
            "Install the platform-specific hook dependencies or set "
            "OPENKEYFLOW_HOOK_BACKEND to choose a different backend.",
        )

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()