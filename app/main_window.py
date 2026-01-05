"""Qt application window for OpenKeyFlow."""
from __future__ import annotations

import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict

from logging import Logger

from PyQt5 import QtCore, QtGui, QtWidgets, QtPrintSupport

from backend import autostart
from backend import storage
from backend.logging_utils import configure_logging, get_logger
from backend.trigger_engine import TriggerEngine

APP_NAME = "OpenKeyFlow"
APP_VERSION = "1.0.0"
HOTKEY_CLIPBOARD_PREFIX = "OpenKeyFlowHotkeys:"
HOTKEY_MODIFIERS = ("ctrl", "shift", "alt")
DEFAULT_HOTKEY_MODIFIER = "ctrl"
DEFAULT_QUICK_ADD_KEY = "f10"
DEFAULT_PROFILE_SWITCH_KEY = "f11"
DEFAULT_TOGGLE_HOTKEY_KEY = "f12"
HOTKEY_CONFLICTS = {
    "windows": {
        "alt+f4",
        "alt+tab",
        "ctrl+alt+del",
        "ctrl+shift+esc",
    },
    "linux": {
        "alt+f2",
        "alt+f3",
        "alt+f4",
        "alt+f5",
        "alt+f6",
        "ctrl+alt+f1",
        "ctrl+alt+f2",
        "ctrl+alt+f3",
        "ctrl+alt+f4",
        "ctrl+alt+f5",
        "ctrl+alt+f6",
        "ctrl+alt+f7",
        "ctrl+alt+f8",
        "ctrl+alt+f9",
        "ctrl+alt+f10",
        "ctrl+alt+f11",
        "ctrl+alt+f12",
    },
}

def normalize_hotkey_modifier(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in HOTKEY_MODIFIERS:
        return normalized
    return DEFAULT_HOTKEY_MODIFIER


def normalize_hotkey_key(value: str | None) -> str:
    if value is None:
        return ""
    key = str(value).strip().lower().replace(" ", "")
    return key

def split_hotkey(hotkey: str) -> tuple[str, str]:
    parts = [part.strip().lower() for part in str(hotkey).split("+") if part.strip()]
    modifier = next((part for part in parts if part in HOTKEY_MODIFIERS), "ctrl")
    key = next((part for part in reversed(parts) if part not in HOTKEY_MODIFIERS), "")
    return modifier, key

class LineNumberArea(QtWidgets.QWidget):
    def __init__(self, editor: "CodeEditor") -> None:
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self) -> QtCore.QSize:  # noqa: N802 - Qt override
        return QtCore.QSize(self.editor.lineNumberAreaWidth(), 0)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt override
        self.editor.lineNumberAreaPaintEvent(event)

class CodeEditor(QtWidgets.QPlainTextEdit):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._line_number_area = LineNumberArea(self)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.blockCountChanged.connect(self.update_line_number_area_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.update_line_number_area_width(0)
        self.highlight_current_line()

    def lineNumberAreaWidth(self) -> int:  # noqa: N802 - Qt override
        digits = len(str(max(1, self.blockCount())))
        padding = 12 + self.fontMetrics().horizontalAdvance("9") * digits
        return padding

    def update_line_number_area_width(self, _: int) -> None:
        self.setViewportMargins(self.lineNumberAreaWidth(), 0, 0, 0)

    def update_line_number_area(self, rect: QtCore.QRect, dy: int) -> None:
        if dy:
            self._line_number_area.scroll(0, dy)
        else:
            self._line_number_area.update(0, rect.y(), self._line_number_area.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_area_width(0)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._line_number_area.setGeometry(
            QtCore.QRect(cr.left(), cr.top(), self.lineNumberAreaWidth(), cr.height())
        )

    def lineNumberAreaPaintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: N802 - Qt override
        painter = QtGui.QPainter(self._line_number_area)
        palette = self.palette()
        background = palette.color(QtGui.QPalette.AlternateBase)
        painter.fillRect(event.rect(), background)

        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())

        number_color = QtGui.QColor(palette.color(QtGui.QPalette.Text))
        number_color.setAlpha(160)
        painter.setPen(number_color)

        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                number = str(block_number + 1)
                painter.drawText(
                    0,
                    top,
                    self._line_number_area.width() - 4,
                    self.fontMetrics().height(),
                    QtCore.Qt.AlignRight,
                    number,
                )
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def highlight_current_line(self) -> None:
        selection = QtWidgets.QTextEdit.ExtraSelection()
        line_color = QtGui.QColor(self.palette().color(QtGui.QPalette.Highlight))
        line_color.setAlpha(40)
        selection.format.setBackground(line_color)
        selection.format.setProperty(QtGui.QTextFormat.FullWidthSelection, True)
        selection.cursor = self.textCursor()
        selection.cursor.clearSelection()
        self.setExtraSelections([selection])

class ProfileSwitchToast(QtWidgets.QWidget):
    def __init__(self, message: str, color: QtGui.QColor) -> None:
        super().__init__(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(QtCore.Qt.NoFocus)

        container = QtWidgets.QFrame(self)
        container.setObjectName("toastContainer")
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(8)

        label = QtWidgets.QLabel(message)
        label.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(label)

        text_color = readable_text_color(color)
        container.setStyleSheet(
            (
                "QFrame#toastContainer {"
                f"background-color: {color.name()};"
                f"color: {text_color.name()};"
                "border-radius: 8px;"
                "border: 1px solid rgba(0, 0, 0, 0.2);"
                "}"
            )
        )

        outer_layout = QtWidgets.QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.addWidget(container)

        self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._opacity_effect)
        self._animation = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._animation.setDuration(4500)
        self._animation.setStartValue(0.0)
        self._animation.setKeyValueAt(0.15, 1.0)
        self._animation.setKeyValueAt(0.85, 1.0)
        self._animation.setEndValue(0.0)
        self._animation.finished.connect(self.close)

    def show_toast(self) -> None:
        screen = QtWidgets.QApplication.primaryScreen()
        if not screen:
            return
        geometry = screen.availableGeometry()
        self.adjustSize()
        width = max(260, self.sizeHint().width())
        self.resize(width, self.sizeHint().height())
        x = geometry.x() + (geometry.width() - self.width()) // 2
        y = geometry.y() + 24
        self.move(x, y)
        self.show()
        self._animation.start()

class PassphraseDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget, title: str, prompt: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self._passphrase = ""
        self.recovery_code = secrets.token_hex(8).upper()

        layout = QtWidgets.QVBoxLayout(self)

        prompt_label = QtWidgets.QLabel(prompt)
        prompt_label.setWordWrap(True)
        layout.addWidget(prompt_label)

        self.passphrase_edit = QtWidgets.QLineEdit()
        self.passphrase_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.passphrase_edit.setPlaceholderText("Enter passphrase")
        layout.addWidget(self.passphrase_edit)

        self.confirm_edit = QtWidgets.QLineEdit()
        self.confirm_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        self.confirm_edit.setPlaceholderText("Confirm passphrase")
        layout.addWidget(self.confirm_edit)

        requirements = QtWidgets.QLabel(
            "Requirements: at least 12 characters, includes letters, numbers, and one symbol."
        )
        requirements.setWordWrap(True)
        layout.addWidget(requirements)

        recovery_group = QtWidgets.QGroupBox("Recovery Code")
        recovery_layout = QtWidgets.QVBoxLayout(recovery_group)
        recovery_hint = QtWidgets.QLabel(
            "Keep this recovery code in a safe place. You can copy, select, or print it."
        )
        recovery_hint.setWordWrap(True)
        recovery_layout.addWidget(recovery_hint)

        recovery_row = QtWidgets.QHBoxLayout()
        self.recovery_edit = QtWidgets.QLineEdit(self.recovery_code)
        self.recovery_edit.setReadOnly(True)
        self.recovery_edit.setCursorPosition(0)
        self.recovery_edit.setMinimumWidth(220)
        recovery_row.addWidget(self.recovery_edit, 1)

        copy_btn = QtWidgets.QPushButton("Copy")
        copy_btn.clicked.connect(self._copy_recovery_code)
        recovery_row.addWidget(copy_btn)

        print_btn = QtWidgets.QPushButton("Print")
        print_btn.clicked.connect(self._print_recovery_code)
        recovery_row.addWidget(print_btn)

        recovery_layout.addLayout(recovery_row)
        layout.addWidget(recovery_group)

        self.error_label = QtWidgets.QLabel()
        self.error_label.setStyleSheet("color: #ff6b6b;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _copy_recovery_code(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.recovery_code)
        self.recovery_edit.selectAll()

    def _print_recovery_code(self) -> None:
        printer = QtPrintSupport.QPrinter()
        dialog = QtPrintSupport.QPrintDialog(printer, self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        doc = QtGui.QTextDocument()
        doc.setPlainText(
            "OpenKeyFlow Recovery Code\n\n"
            f"{self.recovery_code}\n\n"
            "Store this recovery code securely."
        )
        doc.print_(printer)

    def _on_accept(self) -> None:
        passphrase = self.passphrase_edit.text().strip()
        confirm = self.confirm_edit.text().strip()
        error = validate_passphrase(passphrase)
        if error:
            self.error_label.setText(error)
            return
        if passphrase != confirm:
            self.error_label.setText("Passphrases do not match.")
            return
        self._passphrase = passphrase
        self.accept()

    def passphrase(self) -> str:
        return self._passphrase

class UpdateCheckWorker(QtCore.QObject):
    finished = QtCore.pyqtSignal(str, bool)
    failed = QtCore.pyqtSignal(str)

    def __init__(self, os_name: str) -> None:
        super().__init__()
        self.os_name = os_name

    def _friendly_error_message(self, exc: Exception) -> str:
        if isinstance(exc, urllib.error.HTTPError):
            return "Update check failed due to a server error. Please try again later."
        if isinstance(exc, urllib.error.URLError):
            reason = exc.reason
            if isinstance(reason, TimeoutError):
                return "Update check timed out. Please try again."
            return "Unable to reach the update server. Check your internet connection."
        if isinstance(exc, TimeoutError):
            return "Update check timed out. Please try again."
        return "Update check failed. Please try again later."

    def run(self) -> None:
        try:
            latest = fetch_latest_version(self.os_name)
        except Exception as exc:
            self.failed.emit(self._friendly_error_message(exc))
            return
        if not latest:
            self.failed.emit("No releases found.")
            return
        up_to_date = compare_versions(APP_VERSION, latest) >= 0
        message = f"You're up to date (v{APP_VERSION})." if up_to_date else f"Update available: v{latest}."
        self.finished.emit(message, up_to_date)
        
def autostart_supported() -> bool:
    _, error = autostart.status()
    return error is None

def is_autostart_enabled() -> bool:
    enabled, error = autostart.status()
    if error:
        return False
    return enabled

def set_autostart_enabled(parent: QtWidgets.QWidget, enabled: bool) -> bool:
    if enabled:
        success, message = autostart.enable()
    else:
        success, message = autostart.disable()
    if not success:
        QtWidgets.QMessageBox.warning(
            parent,
            "Autostart",
            message or "Autostart is not supported on this platform.",
        )
    return success

class HotkeyFilter(QtCore.QSortFilterProxyModel):
    def __init__(self) -> None:
        super().__init__()
        self.query = ""

    def setQuery(self, text: str) -> None:  # noqa: N802 (Qt naming)
        self.query = text.lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:  # noqa: N802
        if not self.query:
            return True
        model = self.sourceModel()
        key_idx = model.index(source_row, 0, source_parent)
        val_idx = model.index(source_row, 1, source_parent)
        trigger = (model.data(key_idx, QtCore.Qt.DisplayRole) or "").lower()
        output = (model.data(val_idx, QtCore.Qt.DisplayRole) or "").lower()
        return self.query in trigger or self.query in output

def make_status_icon(enabled: bool, *, override_color: QtGui.QColor | None = None) -> QtGui.QIcon:
    icon_size = 64
    pixmap = QtGui.QPixmap(icon_size, icon_size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    color = override_color or QtGui.QColor("#2ecc71" if enabled else "#e74c3c")
    painter.setBrush(color)
    painter.setPen(QtCore.Qt.NoPen)
    margin = 8
    diameter = icon_size - (margin * 2)
    painter.drawEllipse(margin, margin, diameter, diameter)
    painter.end()
    return QtGui.QIcon(pixmap)

def make_color_icon(color: QtGui.QColor, size: int = 12) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setBrush(color)
    painter.setPen(QtGui.QPen(QtGui.QColor(20, 20, 20, 120), 1))
    painter.drawRoundedRect(0, 0, size - 1, size - 1, 3, 3)
    painter.end()
    return QtGui.QIcon(pixmap)

def readable_text_color(color: QtGui.QColor) -> QtGui.QColor:
    luminance = (0.299 * color.red()) + (0.587 * color.green()) + (0.114 * color.blue())
    return QtGui.QColor("#1c1c1c" if luminance > 165 else "#ffffff")

def make_logo_pixmap(dark_mode: bool, target_width: int = 220) -> QtGui.QPixmap:
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    preferred_name = "okf_logo_dark.png" if dark_mode else "okf_logo_light.png"
    logo_path = assets_dir / preferred_name
    if not logo_path.exists():
        logo_path = assets_dir / "okf_logo.png"
    if not logo_path.exists():
        logo_path = assets_dir / "ofk_logo.png"
    pixmap = QtGui.QPixmap(str(logo_path))
    if pixmap.isNull():
        return pixmap
    if pixmap.width() == 0:
        return pixmap
    target_height = round((pixmap.height() / pixmap.width()) * target_width)
    return pixmap.scaled(
        target_width,
        target_height,
        QtCore.Qt.KeepAspectRatio,
        QtCore.Qt.SmoothTransformation,
    )

def validate_passphrase(passphrase: str) -> str | None:
    if len(passphrase) < 12:
        return "Passphrase must be at least 12 characters long."
    if not any(char.isalpha() for char in passphrase):
        return "Passphrase must include at least one letter."
    if not any(char.isdigit() for char in passphrase):
        return "Passphrase must include at least one number."
    if not any(not char.isalnum() for char in passphrase):
        return "Passphrase must include at least one symbol."
    return None

def compare_versions(current: str, latest: str) -> int:
    def parse(version: str) -> tuple[int, ...]:
        parts = [part for part in version.strip().lstrip("vV").split(".") if part]
        return tuple(int(part) for part in parts if part.isdigit() or part.isnumeric())

    current_parts = parse(current)
    latest_parts = parse(latest)
    if current_parts == latest_parts:
        return 0
    if current_parts > latest_parts:
        return 1
    return -1

def fetch_latest_version(os_name: str) -> str | None:
    url = f"https://api.github.com/repos/exoteriklabs/OpenKeyFlow/contents/dist/{os_name}"
    request = urllib.request.Request(url, headers={"User-Agent": "OpenKeyFlow"})
    with urllib.request.urlopen(request, timeout=8) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, list):
        return None
    versions = []
    for entry in payload:
        if entry.get("type") != "dir":
            continue
        name = entry.get("name")
        if isinstance(name, str) and name:
            versions.append(name)
    if not versions:
        return None
    def parse_version(value: str) -> tuple[int, ...]:
        return tuple(int(part) for part in value.strip().lstrip("vV").split(".") if part.isdigit())

    versions.sort(key=parse_version)
    return versions[-1]

def make_gear_icon(palette: QtGui.QPalette, size: int = 18) -> QtGui.QIcon:
    pixmap = QtGui.QPixmap(size, size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    font = QtGui.QFont()
    font.setPointSize(int(size * 0.8))
    painter.setFont(font)
    painter.setPen(palette.color(QtGui.QPalette.Text))
    painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, "⚙")
    painter.end()

    return QtGui.QIcon(pixmap)

def set_app_palette(dark: bool) -> None:
    app = QtWidgets.QApplication.instance()
    if not app:
        return

    if dark:
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(22, 24, 30))
        palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(30, 32, 40))
        palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(42, 44, 54))
        palette.setColor(QtGui.QPalette.ToolTipBase, QtCore.Qt.white)
        palette.setColor(QtGui.QPalette.ToolTipText, QtCore.Qt.white)
        palette.setColor(QtGui.QPalette.Text, QtCore.Qt.white)
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor(36, 38, 48))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(255, 115, 115))
        palette.setColor(QtGui.QPalette.PlaceholderText, QtGui.QColor(255, 170, 170))
        palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(255, 99, 132))
        palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
        app.setPalette(palette)
        app.setStyleSheet(
            """
            QPushButton, QToolButton {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #2c2f3b, stop:1 #ff4d4f);
                color: white;
                border: 1px solid #ff8080;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QPushButton:hover, QToolButton:hover {
                background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,
                    stop:0 #ff5f6d, stop:1 #ffc371);
                color: #1c1c1c;
            }
            QPushButton:disabled, QToolButton:disabled {
                background-color: #2d2d2d;
                color: rgba(255, 255, 255, 0.6);
                border: 1px solid #555;
            }
            QLineEdit, QPlainTextEdit, QTextEdit {
                background-color: #1f2128;
                color: #ffcccc;
                selection-background-color: #ff5f6d;
                selection-color: #1c1c1c;
                border: 1px solid #ff8080;
                border-radius: 4px;
                padding: 2px 4px;
            }
            QGroupBox::title {
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #1f1f24;
                color: #ff7b7b;
                border: 1px solid #ff8080;
            }
            QMessageBox {
                background-color: #1f2128;
            }
            QMessageBox QLabel {
                color: #ffffff;
            }
            QTabWidget::pane {
                border: 1px solid #ff8080;
            }
            QTabBar::tab {
                background: #1f2128;
                color: #ffcccc;
                border: 1px solid #ff8080;
                border-bottom: none;
                padding: 4px 10px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                background: #2c2f3b;
                color: #ffffff;
            }
            """
        )
    else:
        palette = QtWidgets.QApplication.style().standardPalette()
        highlight_color = QtGui.QColor(255, 95, 109)
        palette.setColor(QtGui.QPalette.Highlight, highlight_color)
        palette.setColor(QtGui.QPalette.HighlightedText, QtCore.Qt.white)
        app.setPalette(palette)
        app.setStyleSheet("")

def toggle_autostart(parent: QtWidgets.QWidget) -> None:
    enabled, error = autostart.status()
    if error:
        QtWidgets.QMessageBox.warning(parent, "Autostart", error)
        return
    if enabled:
        success, message = autostart.disable()
        if success:
            QtWidgets.QMessageBox.information(parent, "Autostart", "Autostart disabled.")
        else:
            QtWidgets.QMessageBox.warning(parent, "Autostart", f"Failed to disable autostart:\n{message}")
    else:
        success, message = autostart.enable()
        if success:
            QtWidgets.QMessageBox.information(parent, "Autostart", "Autostart enabled.")
        else:
            QtWidgets.QMessageBox.warning(parent, "Autostart", f"Failed to enable autostart:\n{message}")

class SpecialAddDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Special Add")
        if parent:
            self.setWindowIcon(make_status_icon(getattr(parent, "enabled", True)))
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        instructions = QtWidgets.QLabel(
            "Enter a trigger and multi-line output. The trigger cannot contain spaces."
        )
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

        form_layout = QtWidgets.QFormLayout()
        self.trigger_edit = QtWidgets.QLineEdit()
        self.trigger_edit.setPlaceholderText("Trigger (no spaces)")
        form_layout.addRow("Trigger:", self.trigger_edit)

        self.tab_widget = QtWidgets.QTabWidget()
        self.output_edit = QtWidgets.QPlainTextEdit()
        self.output_edit.setPlaceholderText("Expansion output (supports multiple lines)")
        self.output_edit.setMinimumHeight(160)

        self.code_edit = CodeEditor()
        self.code_edit.setPlaceholderText("Code block (will be wrapped for you)")
        self.code_edit.setMinimumHeight(160)
        fixed_font = QtGui.QFontDatabase.systemFont(QtGui.QFontDatabase.FixedFont)
        self.code_edit.setFont(fixed_font)

        self.tab_widget.addTab(self.output_edit, "Text")
        self.tab_widget.addTab(self.code_edit, "Code block")
        form_layout.addRow("Output:", self.tab_widget)
        layout.addLayout(form_layout)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self) -> tuple[str, str]:
        current_index = self.tab_widget.currentIndex()
        if current_index == 1:
            content = self.code_edit.toPlainText()
            if content.strip():
                wrapped = content
                if not content.strip().startswith("```"):
                    wrapped = f"```\n{content}\n```"
                return self.trigger_edit.text(), wrapped
        return self.trigger_edit.text(), self.output_edit.toPlainText()

    def accept(self) -> None:  # noqa: D401 - inherited docs
        trigger = self.trigger_edit.text().strip()
        output = self.code_edit.toPlainText() if self.tab_widget.currentIndex() == 1 else self.output_edit.toPlainText()
        if not trigger or not output.strip():
            QtWidgets.QMessageBox.warning(self, "Special Add", "Trigger and output are required.")
            return
        if " " in trigger:
            QtWidgets.QMessageBox.warning(self, "Special Add", "Triggers cannot contain spaces.")
            return
        self.trigger_edit.setText(trigger)
        super().accept()

class QuickAddDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Quick Add")
        if parent:
            self.setWindowIcon(make_status_icon(getattr(parent, "enabled", True)))
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool | QtCore.Qt.WindowStaysOnTopHint)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.card = QtWidgets.QFrame()
        self.card.setObjectName("quickAddCard")
        card_layout = QtWidgets.QVBoxLayout(self.card)
        card_layout.setContentsMargins(18, 18, 18, 18)
        card_layout.setSpacing(12)
        layout.addWidget(self.card)

        self.header_frame = QtWidgets.QFrame()
        self.header_frame.setObjectName("quickAddHeader")
        header_layout = QtWidgets.QVBoxLayout(self.header_frame)
        header_layout.setContentsMargins(14, 10, 14, 10)
        header_layout.setSpacing(4)
        self.header_title = QtWidgets.QLabel("Quick Add from Clipboard")
        title_font = self.header_title.font()
        title_font.setPointSize(title_font.pointSize() + 1)
        title_font.setBold(True)
        self.header_title.setFont(title_font)
        self.header_hint = QtWidgets.QLabel("Review the output, choose a trigger, then add.")
        self.header_hint.setWordWrap(True)
        header_layout.addWidget(self.header_title)
        header_layout.addWidget(self.header_hint)
        card_layout.addWidget(self.header_frame)

        form_layout = QtWidgets.QFormLayout()
        self.trigger_edit = QtWidgets.QLineEdit()
        self.trigger_edit.setPlaceholderText("Trigger (no spaces)")
        form_layout.addRow("Trigger:", self.trigger_edit)

        self.output_edit = QtWidgets.QPlainTextEdit()
        self.output_edit.setPlaceholderText("Expansion output")
        self.output_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.output_edit.setMinimumHeight(140)
        form_layout.addRow("Output:", self.output_edit)
        card_layout.addLayout(form_layout)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel | QtWidgets.QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        card_layout.addWidget(buttons)

        shadow = QtWidgets.QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 6)
        shadow.setColor(QtGui.QColor(0, 0, 0, 150))
        self.card.setGraphicsEffect(shadow)

        self.set_theme(False)

    def set_header_color(self, color: QtGui.QColor) -> None:
        text_color = readable_text_color(color)
        self.header_frame.setStyleSheet(
            (
                "QFrame#quickAddHeader {"
                f"background-color: {color.name()};"
                f"color: {text_color.name()};"
                "border-radius: 8px;"
                "border: 1px solid rgba(0, 0, 0, 0.2);"
                "}"
            )
        )

    def set_theme(self, dark_mode: bool) -> None:
        if dark_mode:
            background = "#1f1f24"
            field_bg = "#15151a"
            field_border = "#3a3a44"
            text_color = "#f5f5f5"
        else:
            background = "#f5f6f8"
            field_bg = "#ffffff"
            field_border = "#c9c9cf"
            text_color = "#1c1c1e"
        self.card.setStyleSheet(
            (
                "QFrame#quickAddCard {"
                f"background-color: {background};"
                f"color: {text_color};"
                "border-radius: 12px;"
                "border: 1px solid rgba(0, 0, 0, 0.12);"
                "}"
                "QLineEdit, QPlainTextEdit {"
                f"background-color: {field_bg};"
                f"color: {text_color};"
                f"border: 1px solid {field_border};"
                "border-radius: 6px;"
                "padding: 6px;"
                "}"
                "QDialogButtonBox QPushButton {"
                "padding: 6px 14px;"
                "border-radius: 6px;"
                "}"
            )
        )

    def set_clipboard_text(self, text: str) -> None:
        self.set_data("", text, focus_trigger=True)

    def set_data(self, trigger: str, output: str, *, focus_trigger: bool = False) -> None:
        self.output_edit.setPlainText(output)
        self.trigger_edit.setText(trigger)
        self._resize_for_output(output)
        if focus_trigger:
            QtCore.QTimer.singleShot(0, self.trigger_edit.setFocus)

    def _resize_for_output(self, text: str) -> None:
        length = len(text)
        lines = text.count("\n") + 1
        if length > 1500 or lines > 20:
            self.output_edit.setMinimumHeight(320)
            self.resize(760, 520)
        elif length > 500 or lines > 6:
            self.output_edit.setMinimumHeight(240)
            self.resize(640, 440)
        else:
            self.output_edit.setMinimumHeight(160)
            self.resize(520, 340)

    def get_data(self) -> tuple[str, str]:
        return self.trigger_edit.text(), self.output_edit.toPlainText()

    def accept(self) -> None:  # noqa: D401 - inherited docs
        trigger = self.trigger_edit.text().strip()
        output = self.output_edit.toPlainText()
        if not trigger or not output.strip():
            QtWidgets.QMessageBox.warning(self, "Quick Add", "Trigger and output are required.")
            return
        if " " in trigger:
            QtWidgets.QMessageBox.warning(self, "Quick Add", "Triggers cannot contain spaces.")
            return
        self.trigger_edit.setText(trigger)
        super().accept()

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent: "MainWindow") -> None:  # type: ignore[name-defined]
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Settings")
        self.setWindowIcon(make_status_icon(self.window.enabled))
        self.setModal(True)
        self._last_update_check_at = 0.0
        self._update_cooldown_seconds = 30.0

        layout = QtWidgets.QVBoxLayout(self)

        self._update_thread: QtCore.QThread | None = None
        self._update_worker: UpdateCheckWorker | None = None

        header_layout = QtWidgets.QHBoxLayout()
        self.logo_label = QtWidgets.QLabel()
        logo_pixmap = make_logo_pixmap(self.window.dark_mode)
        self.logo_label.setPixmap(logo_pixmap)
        self.logo_label.setScaledContents(False)
        self.logo_label.setFixedSize(logo_pixmap.size())
        self.logo_label.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
        self.logo_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)

        header_layout.addWidget(self.logo_label)
        header_layout.addStretch(1)

        updates_container = QtWidgets.QWidget()
        updates_container.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        updates_layout = QtWidgets.QVBoxLayout(updates_container)
        updates_layout.setContentsMargins(0, 0, 0, 0)
        updates_layout.setSpacing(4)
        self.update_btn = QtWidgets.QPushButton("Check for updates")
        self.update_btn.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.update_btn.setMinimumHeight(26)
        self.update_btn.clicked.connect(self._on_check_updates)
        updates_layout.addWidget(self.update_btn)
        self.update_status_label = QtWidgets.QLabel("Update status: not checked.")
        self.update_status_label.setWordWrap(True)
        self.update_status_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.update_status_label.setMinimumHeight(18)
        updates_layout.addWidget(self.update_status_label)
        header_layout.addWidget(updates_container, 1, QtCore.Qt.AlignRight)
        layout.addLayout(header_layout)

        general_group = QtWidgets.QGroupBox("General")
        general_layout = QtWidgets.QVBoxLayout(general_group)

        self.autostart_checkbox = QtWidgets.QCheckBox("Launch OpenKeyFlow on startup")
        self.autostart_checkbox.setChecked(is_autostart_enabled())
        self.autostart_checkbox.setEnabled(autostart_supported())
        self.autostart_checkbox.toggled.connect(self._on_autostart_toggled)

        self.dark_mode_checkbox = QtWidgets.QCheckBox("Enable dark mode")
        self.dark_mode_checkbox.setChecked(self.window.dark_mode)
        self.dark_mode_checkbox.toggled.connect(self._on_dark_mode_toggled)

        general_layout.addWidget(self.autostart_checkbox)
        if not autostart_supported():
            hint = QtWidgets.QLabel("Autostart shortcuts are available on Windows systems.")
            hint.setWordWrap(True)
            general_layout.addWidget(hint)
        general_layout.addWidget(self.dark_mode_checkbox)
        hotkeys_group = QtWidgets.QGroupBox("App Global Hotkeys")
        hotkeys_layout = QtWidgets.QVBoxLayout(hotkeys_group)
        modifier_row = QtWidgets.QHBoxLayout()
        modifier_label = QtWidgets.QLabel("Modifier key:")
        self.hotkey_modifier_combo = QtWidgets.QComboBox()
        self.hotkey_modifier_combo.addItems(["CTRL", "SHIFT", "ALT"])
        current_modifier = self.window.hotkey_modifier.upper()
        index = self.hotkey_modifier_combo.findText(current_modifier)
        if index >= 0:
            self.hotkey_modifier_combo.setCurrentIndex(index)
        self.hotkey_modifier_combo.currentTextChanged.connect(self._on_hotkey_modifier_changed)
        self._apply_modifier_combo_theme()
        modifier_row.addWidget(modifier_label)
        modifier_row.addWidget(self.hotkey_modifier_combo, 1)
        hotkeys_layout.addLayout(modifier_row)

        self.quick_add_hotkey_btn = self._build_hotkey_button(self.window.quick_add_key)
        quick_add_row = self._build_hotkey_row("Quick Add hotkey:", self.quick_add_hotkey_btn)
        self.quick_add_hotkey_btn.clicked.connect(lambda: self._begin_listening("quick_add"))
                
        hotkeys_layout.addLayout(quick_add_row)
        self.profile_switch_hotkey_btn = self._build_hotkey_button(self.window.profile_switch_key)
        profile_switch_row = self._build_hotkey_row("Profile Switch hotkey:", self.profile_switch_hotkey_btn)
        self.profile_switch_hotkey_btn.clicked.connect(lambda: self._begin_listening("profile_switch"))
        hotkeys_layout.addLayout(profile_switch_row)

        self.toggle_hotkey_btn = self._build_hotkey_button(self.window.toggle_hotkey_key)
        toggle_row = self._build_hotkey_row("Toggle OpenKeyFlow hotkey:", self.toggle_hotkey_btn)
        self.toggle_hotkey_btn.clicked.connect(lambda: self._begin_listening("toggle"))
        hotkeys_layout.addLayout(toggle_row)
        reset_hotkeys_row = QtWidgets.QHBoxLayout()
        reset_hotkeys_row.addStretch(1)
        self.reset_hotkeys_btn = QtWidgets.QPushButton("Reset global hotkeys")
        self.reset_hotkeys_btn.clicked.connect(self._on_reset_hotkeys)
        reset_hotkeys_row.addWidget(self.reset_hotkeys_btn)
        hotkeys_layout.addLayout(reset_hotkeys_row)
        general_layout.addWidget(hotkeys_group)
        content_layout = QtWidgets.QHBoxLayout()
        left_column = QtWidgets.QVBoxLayout()
        right_column = QtWidgets.QVBoxLayout()
        left_column.setSpacing(12)
        right_column.setSpacing(12)

        general_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        left_column.addWidget(general_group, 3)

        data_group = QtWidgets.QGroupBox("Data & Import/Export")
        data_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        data_layout = QtWidgets.QHBoxLayout(data_group)
        import_btn = QtWidgets.QPushButton("Import CSV")
        export_btn = QtWidgets.QPushButton("Export CSV")
        export_sample_btn = QtWidgets.QPushButton("Export Sample CSV")
        for button in (import_btn, export_btn, export_sample_btn):
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        import_btn.clicked.connect(self.window.import_csv)
        export_btn.clicked.connect(self.window.export_csv)
        export_sample_btn.clicked.connect(self.window.export_sample_csv)
        data_layout.addWidget(import_btn)
        data_layout.addWidget(export_btn)
        data_layout.addWidget(export_sample_btn)
        left_column.addWidget(data_group, 2)

        privacy_group = QtWidgets.QGroupBox("Privacy & Security")
        privacy_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        privacy_layout = QtWidgets.QVBoxLayout(privacy_group)

        self.encryption_checkbox = QtWidgets.QCheckBox("Encrypt profiles with a passphrase")
        self.encryption_checkbox.setChecked(bool(self.window.config.get("profiles_encrypted", False)))
        self.encryption_checkbox.toggled.connect(self._on_encryption_toggled)
        privacy_layout.addWidget(self.encryption_checkbox)

        encryption_hint = QtWidgets.QLabel(
            "You will be prompted for the passphrase on startup to access your profiles."
        )
        encryption_hint.setWordWrap(True)
        privacy_layout.addWidget(encryption_hint)

        self.change_passphrase_btn = QtWidgets.QPushButton("Change passphrase")
        self.change_passphrase_btn.clicked.connect(self._on_change_passphrase)
        privacy_layout.addWidget(self.change_passphrase_btn)

        self.clipboard_checkbox = None

        left_column.addWidget(privacy_group, 2)

        profiles_group = QtWidgets.QGroupBox("Profiles")
        profiles_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        profiles_layout = QtWidgets.QVBoxLayout(profiles_group)
        self.profile_list = QtWidgets.QListWidget()
        self.profile_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.profile_list.setMinimumHeight(120)
        self.profile_list.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        profiles_layout.addWidget(self.profile_list)

        profile_buttons_row = QtWidgets.QHBoxLayout()
        new_profile_btn = QtWidgets.QPushButton("New")
        rename_profile_btn = QtWidgets.QPushButton("Rename")
        delete_profile_btn = QtWidgets.QPushButton("Delete")
        set_active_btn = QtWidgets.QPushButton("Set Active")

        new_profile_btn.clicked.connect(self._on_new_profile)
        rename_profile_btn.clicked.connect(self._on_rename_profile)
        delete_profile_btn.clicked.connect(self._on_delete_profile)
        set_active_btn.clicked.connect(self._on_set_active_profile)

        for button in (new_profile_btn, rename_profile_btn, delete_profile_btn, set_active_btn):
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            profile_buttons_row.addWidget(button)
        profiles_layout.addLayout(profile_buttons_row)

        profile_color_row = QtWidgets.QHBoxLayout()
        self.profile_color_label = QtWidgets.QLabel("Profile color:")
        self.profile_color_preview = QtWidgets.QFrame()
        self.profile_color_preview.setFixedSize(18, 18)
        self.profile_color_preview.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.profile_color_preview.setFrameShadow(QtWidgets.QFrame.Plain)

        self.profile_color_btn = QtWidgets.QToolButton()
        self.profile_color_btn.setText("Choose color")
        self.profile_color_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.profile_color_btn.setMenu(self._build_profile_color_menu())

        profile_color_row.addWidget(self.profile_color_label)
        profile_color_row.addWidget(self.profile_color_preview)
        profile_color_row.addWidget(self.profile_color_btn)
        profile_color_row.addStretch(1)
        profiles_layout.addLayout(profile_color_row)

        right_column.addWidget(profiles_group, 3)

        logging_group = QtWidgets.QGroupBox("Diagnostics")
        logging_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        logging_layout = QtWidgets.QGridLayout(logging_group)
        right_column.addWidget(logging_group, 2)
        self.logging_checkbox = QtWidgets.QCheckBox("Enable debug logging")
        self.logging_checkbox.setChecked(bool(self.window.config.get("logging_enabled", False)))
        self.logging_checkbox.toggled.connect(self._on_logging_toggled)
        logging_layout.addWidget(self.logging_checkbox, 0, 0, 1, 2)

        self.log_path_edit = QtWidgets.QLineEdit(str(self.window.config.get("log_file", storage.default_log_path())))
        self.log_path_edit.setPlaceholderText("Log file path")
        self.browse_btn = QtWidgets.QPushButton("Choose…")
        self.browse_btn.clicked.connect(self._on_choose_log_path)
        logging_layout.addWidget(QtWidgets.QLabel("Log file:"), 1, 0)
        logging_layout.addWidget(self.log_path_edit, 1, 1)
        logging_layout.addWidget(self.browse_btn, 1, 2)
        right_column.addWidget(logging_group)

        links_group = QtWidgets.QGroupBox("Links")
        links_group.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        links_layout = QtWidgets.QHBoxLayout(links_group)
        donate_btn = QtWidgets.QPushButton("Donate")
        donate_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        donate_btn.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://buymeacoffee.com/exoteriklabs"))
        )
        github_btn = QtWidgets.QPushButton("GitHub")
        github_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        github_btn.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://github.com/exoteriklabs"))
        )
        help_btn = QtWidgets.QPushButton("Help")
        help_btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        help_btn.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(
                QtCore.QUrl("https://github.com/exoteriklabs/OpenKeyFlow/blob/main/README.md")
            )
        )
        for button in (donate_btn, github_btn, help_btn):
            button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            links_layout.addWidget(button)
        right_column.addWidget(links_group, 1)

        content_layout.addLayout(left_column, 1)
        content_layout.addLayout(right_column, 1)
        layout.addLayout(content_layout)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_button = buttons.button(QtWidgets.QDialogButtonBox.Close)
        if close_button:
            close_button.setText("Close")
        layout.addWidget(buttons)

        self._update_logging_controls()        
        self._update_encryption_controls()
        self.section_groups = [
            general_group,
            data_group,
            privacy_group,
            profiles_group,
            logging_group,
            links_group,
        ]
        self._listening_target: str | None = None
        self._listening_button: QtWidgets.QPushButton | None = None
        self._listening_previous_label: str | None = None
        self._apply_section_title_style()
        self.refresh_profiles()
        self.profile_list.currentItemChanged.connect(self._on_profile_selection_changed)
        self._refresh_profile_color_controls()

    def _update_logging_controls(self) -> None:
        enabled = self.logging_checkbox.isChecked()
        self.log_path_edit.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)

    def _update_encryption_controls(self) -> None:
        encrypted = self.encryption_checkbox.isChecked()
        self.change_passphrase_btn.setEnabled(encrypted)

    def _build_hotkey_button(self, key: str) -> QtWidgets.QPushButton:
        button = QtWidgets.QPushButton(self._display_hotkey_key(key))
        button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        button.setFixedWidth(140)
        return button

    def _build_hotkey_row(self, label_text: str, button: QtWidgets.QPushButton) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel(label_text)
        row.addWidget(label)
        row.addStretch(1)
        row.addWidget(button)
        return row

    def _display_hotkey_key(self, key: str) -> str:
        normalized = normalize_hotkey_key(key)
        if not normalized:
            return "Unassigned"
        return normalized.upper()

    def _begin_listening(self, target: str) -> None:
        if self._listening_button is not None:
            self._end_listening(apply_change=False)
        self._listening_target = target
        if target == "quick_add":
            self._listening_button = self.quick_add_hotkey_btn
        elif target == "profile_switch":
            self._listening_button = self.profile_switch_hotkey_btn
        elif target == "toggle":
            self._listening_button = self.toggle_hotkey_btn
        else:
            self._listening_button = None
        if self._listening_button is None:
            self._listening_target = None
            return
        self._listening_previous_label = self._listening_button.text()
        self._listening_button.setText("Waiting for input")
        self.grabKeyboard()

    def _end_listening(self, *, apply_change: bool, key_value: str | None = None) -> None:
        if self._listening_button is None:
            return
        self.releaseKeyboard()
        if apply_change and key_value is not None:
            self._listening_button.setText(self._display_hotkey_key(key_value))
        else:
            if self._listening_previous_label is not None:
                self._listening_button.setText(self._listening_previous_label)
        self._listening_target = None
        self._listening_button = None
        self._listening_previous_label = None

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: N802 - Qt override
        if self._listening_target is None:
            super().keyPressEvent(event)
            return
        key = event.key()
        if key in (QtCore.Qt.Key_Control, QtCore.Qt.Key_Shift, QtCore.Qt.Key_Alt, QtCore.Qt.Key_Meta):
            return
        if key == QtCore.Qt.Key_Escape:
            self._end_listening(apply_change=False)
            return
        key_name = QtGui.QKeySequence(key).toString()
        key_value = normalize_hotkey_key(key_name or event.text())
        if not key_value:
            return
        if self._listening_target == "quick_add":
            self.window.set_quick_add_key(key_value)
        elif self._listening_target == "profile_switch":
            self.window.set_profile_switch_key(key_value)
        elif self._listening_target == "toggle":
            self.window.set_toggle_hotkey_key(key_value)
        self._end_listening(apply_change=True, key_value=key_value)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802 - Qt override
        if self._listening_target is not None:
            self._end_listening(apply_change=False)
        super().closeEvent(event)

    def _apply_section_title_style(self) -> None:
        if self.window.dark_mode:
            section_title_style = (
                "QGroupBox { font-weight: 600; }"
                "QGroupBox::title { color: #ffffff; font-weight: 600; }"
            )
        else:
            section_title_style = "QGroupBox { font-weight: 600; }"
        for group in self.section_groups:
            group.setStyleSheet(section_title_style)

    def _apply_modifier_combo_theme(self) -> None:
        if self.window.dark_mode:
            combo_style = (
                "QComboBox {"
                "background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,"
                "stop:0 #2c2f3b, stop:1 #ff4d4f);"
                "color: white;"
                "border: 1px solid #ff8080;"
                "border-radius: 4px;"
                "padding: 2px 24px 2px 8px;"
                "}"
                "QComboBox::drop-down {"
                "subcontrol-origin: padding;"
                "subcontrol-position: top right;"
                "width: 20px;"
                "border-left: 1px solid #ff8080;"
                "}"
                "QComboBox QAbstractItemView {"
                "background-color: #1f2128;"
                "color: #ffffff;"
                "selection-background-color: #ff5f6d;"
                "selection-color: #1c1c1c;"
                "}"
            )
        else:
            combo_style = (
                "QComboBox {"
                "background-color: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:1,"
                "stop:0 #ff7b7b, stop:1 #ff4d4f);"
                "color: white;"
                "border: 1px solid #e45b5b;"
                "border-radius: 4px;"
                "padding: 2px 24px 2px 8px;"
                "}"
                "QComboBox::drop-down {"
                "subcontrol-origin: padding;"
                "subcontrol-position: top right;"
                "width: 20px;"
                "border-left: 1px solid #e45b5b;"
                "}"
                "QComboBox QAbstractItemView {"
                "background-color: #ffffff;"
                "color: #222222;"
                "selection-background-color: #ff7b7b;"
                "selection-color: #ffffff;"
                "}"
            )
        self.hotkey_modifier_combo.setStyleSheet(combo_style)
        self.hotkey_modifier_combo.setMinimumHeight(26)
        self.hotkey_modifier_combo.setFixedWidth(140)

    def _refresh_logo(self) -> None:
        logo_pixmap = make_logo_pixmap(self.window.dark_mode)
        if logo_pixmap.isNull():
            return
        self.logo_label.setPixmap(logo_pixmap)
        self.logo_label.setFixedSize(logo_pixmap.size())

    def _apply_theme_assets(self) -> None:
        self._apply_modifier_combo_theme()
        self._refresh_logo()

    def _on_autostart_toggled(self, checked: bool) -> None:
        success = self.window.update_autostart(checked)
        if not success:
            self.autostart_checkbox.blockSignals(True)
            self.autostart_checkbox.setChecked(not checked)
            self.autostart_checkbox.blockSignals(False)

    def _on_dark_mode_toggled(self, checked: bool) -> None:
        self.window.set_dark_mode(checked)

    def _on_hotkey_modifier_changed(self, value: str) -> None:
        self.window.set_hotkey_modifier(value.lower())

    def _on_reset_hotkeys(self) -> None:
        self.window.reset_global_hotkeys()
        self.hotkey_modifier_combo.blockSignals(True)
        index = self.hotkey_modifier_combo.findText(self.window.hotkey_modifier.upper())
        if index >= 0:
            self.hotkey_modifier_combo.setCurrentIndex(index)
        self.hotkey_modifier_combo.blockSignals(False)
        self.quick_add_hotkey_btn.setText(self._display_hotkey_key(self.window.quick_add_key))
        self.profile_switch_hotkey_btn.setText(self._display_hotkey_key(self.window.profile_switch_key))
        self.toggle_hotkey_btn.setText(self._display_hotkey_key(self.window.toggle_hotkey_key))

    def _on_logging_toggled(self, checked: bool) -> None:
        self.window.set_logging_enabled(checked, Path(self.log_path_edit.text()))
        self._update_logging_controls()

    def _on_encryption_toggled(self, checked: bool) -> None:
        success = self.window.set_profiles_encrypted(checked)
        if not success:
            self.encryption_checkbox.blockSignals(True)
            self.encryption_checkbox.setChecked(not checked)
            self.encryption_checkbox.blockSignals(False)
        self._update_encryption_controls()

    def _on_change_passphrase(self) -> None:
        self.window.change_profiles_passphrase()

    def _on_check_updates(self) -> None:
        now = time.monotonic()
        if now - self._last_update_check_at < self._update_cooldown_seconds:
            self.update_status_label.setText(
                "Update status: please wait a moment before checking again."
            )
            return
        self._last_update_check_at = now
        self.update_btn.setEnabled(False)
        self.update_status_label.setText("Update status: checking...")
        os_name = self.window.current_os_label()
        self._update_thread = QtCore.QThread(self)
        self._update_worker = UpdateCheckWorker(os_name)
        self._update_worker.moveToThread(self._update_thread)
        self._update_thread.started.connect(self._update_worker.run)
        self._update_worker.finished.connect(self._on_update_finished)
        self._update_worker.failed.connect(self._on_update_failed)
        self._update_worker.finished.connect(self._update_thread.quit)
        self._update_worker.failed.connect(self._update_thread.quit)
        self._update_thread.finished.connect(self._update_thread.deleteLater)
        self._update_thread.start()

    def _on_update_finished(self, message: str, _up_to_date: bool) -> None:
        self.update_status_label.setText(f"Update status: {message}")
        self.update_btn.setEnabled(True)

    def _on_update_failed(self, message: str) -> None:
        self.update_status_label.setText(f"Update status: {message}")
        self.update_btn.setEnabled(True)

    def _on_choose_log_path(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select log file", self.log_path_edit.text(), "Log files (*.log)")
        if not path:
            return
        self.log_path_edit.setText(path)
        self.window.set_logging_path(Path(path))
        self._update_logging_controls()

    def refresh_profiles(self) -> None:
        self.profile_list.clear()
        current = self.window.current_profile
        for name in self.window.profile_names():
            display = f"{name} (current)" if name == current else name
            item = QtWidgets.QListWidgetItem(display)
            item.setData(QtCore.Qt.UserRole, name)
            color = self.window.profile_color(name)
            if color:
                swatch_color = QtGui.QColor(color)
                item.setIcon(make_color_icon(swatch_color))
                item.setForeground(QtGui.QBrush(swatch_color))
            self.profile_list.addItem(item)
        self._refresh_profile_color_controls()

    def _selected_profile_name(self) -> str | None:
        item = self.profile_list.currentItem()
        if not item:
            return None
        return item.data(QtCore.Qt.UserRole)
    
    def _on_profile_selection_changed(
        self, current: QtWidgets.QListWidgetItem | None, _: QtWidgets.QListWidgetItem | None
    ) -> None:
        self._refresh_profile_color_controls()

    def _refresh_profile_color_controls(self) -> None:
        profile_name = self._selected_profile_name() or self.window.current_profile
        color = self.window.profile_color(profile_name)
        if color:
            self._set_color_preview(QtGui.QColor(color))
        else:
            self._set_color_preview(None)

    def _set_color_preview(self, color: QtGui.QColor | None) -> None:
        if color:
            self.profile_color_preview.setStyleSheet(
                f"QFrame {{ background-color: {color.name()}; border: 1px solid #555; }}"
            )
        else:
            self.profile_color_preview.setStyleSheet("QFrame { background-color: transparent; border: 1px dashed #555; }")

    def _build_profile_color_menu(self) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self)
        palette = [
            ("Ruby", "#e74c3c"),
            ("Coral", "#ff6b6b"),
            ("Amber", "#f39c12"),
            ("Lime", "#8bc34a"),
            ("Teal", "#1abc9c"),
            ("Sky", "#3498db"),
            ("Indigo", "#5c6bc0"),
            ("Violet", "#9b59b6"),
            ("Slate", "#7f8c8d"),
        ]
        for name, hex_color in palette:
            action = menu.addAction(name)
            action.setData(hex_color)
            action.setIcon(make_color_icon(QtGui.QColor(hex_color)))
        menu.addSeparator()
        clear_action = menu.addAction("Clear color")
        clear_action.setData(None)
        custom_action = menu.addAction("Custom…")
        custom_action.setData("custom")
        menu.triggered.connect(self._on_profile_color_selected)
        return menu

    def _on_profile_color_selected(self, action: QtWidgets.QAction) -> None:
        profile_name = self._selected_profile_name() or self.window.current_profile
        if not profile_name:
            return
        data = action.data()
        if data == "custom":
            current = self.window.profile_color(profile_name)
            base = QtGui.QColor(current) if current else QtGui.QColor("#ff6b6b")
            color = QtWidgets.QColorDialog.getColor(
                base,
                self,
                "Select profile color",
                QtWidgets.QColorDialog.ShowAlphaChannel,
            )
            if not color.isValid():
                return
            color_hex = color.name()
        else:
            color_hex = data
        self.window.set_profile_color(profile_name, color_hex)
        self.refresh_profiles()

    def _on_new_profile(self) -> None:
        if self.window.prompt_create_profile():
            self.refresh_profiles()

    def _on_rename_profile(self) -> None:
        profile_name = self._selected_profile_name()
        if not profile_name:
            return
        if self.window.prompt_rename_profile(profile_name):
            self.refresh_profiles()

    def _on_delete_profile(self) -> None:
        profile_name = self._selected_profile_name()
        if not profile_name:
            return
        if self.window.delete_profile(profile_name):
            self.refresh_profiles()

    def _on_set_active_profile(self) -> None:
        profile_name = self._selected_profile_name()
        if not profile_name:
            return
        if self.window.set_current_profile(profile_name):
            self.refresh_profiles()

class MainWindow(QtWidgets.QMainWindow):
    updateCounters = QtCore.pyqtSignal()


    def __init__(
        self,
        engine: TriggerEngine,
        logger: Logger | None = None,
        *,
        profile_passphrase: str | None = None,
        profiles_encrypted: bool = False,
    ) -> None:
        super().__init__()
        self.engine = engine
        self.current_profile, self.profiles = storage.load_profiles(passphrase=profile_passphrase)
        self.hotkeys: Dict[str, str] = dict(self.profiles.get(self.current_profile, {}))        
        self.config = storage.load_config()
        self.config["profiles_encrypted"] = profiles_encrypted
        self.profile_colors: Dict[str, str] = self._normalize_profile_colors(
            self.config.get("profile_colors", {})
        )
        self.dark_mode = bool(self.config.get("dark_mode", False))
        self.enabled = True
        self.hotkey_lock = threading.RLock()
        self.logger: Logger = logger or get_logger()
        self.profile_passphrase = profile_passphrase
        self.profiles_encrypted = profiles_encrypted
        self.hotkey_modifier = normalize_hotkey_modifier(self.config.get("hotkey_modifier"))
        self.quick_add_key = normalize_hotkey_key(self.config.get("quick_add_key"))
        self.profile_switch_key = normalize_hotkey_key(self.config.get("profile_switch_key"))
        self.toggle_hotkey_key = normalize_hotkey_key(self.config.get("toggle_hotkey_key"))
        legacy_hotkey = str(self.config.get("quick_add_hotkey", "")).strip().lower()
        if legacy_hotkey and not self.quick_add_key:
            legacy_modifier, legacy_key = split_hotkey(legacy_hotkey)
            self.hotkey_modifier = normalize_hotkey_modifier(legacy_modifier)
            self.quick_add_key = normalize_hotkey_key(legacy_key)
        if not self.quick_add_key:
            self.quick_add_key = DEFAULT_QUICK_ADD_KEY
        if not self.profile_switch_key:
            self.profile_switch_key = DEFAULT_PROFILE_SWITCH_KEY
        if not self.toggle_hotkey_key:
            self.toggle_hotkey_key = DEFAULT_TOGGLE_HOTKEY_KEY
        self.quick_add_hotkey = self._compose_hotkey(self.quick_add_key)
        self.profile_switch_hotkey = self._compose_hotkey(self.profile_switch_key)
        self.toggle_hotkey = self._compose_hotkey(self.toggle_hotkey_key)
        config_updated = False
        for key, value in (
            ("hotkey_modifier", self.hotkey_modifier),
            ("quick_add_key", self.quick_add_key),
            ("profile_switch_key", self.profile_switch_key),
            ("toggle_hotkey_key", self.toggle_hotkey_key),
            ("quick_add_hotkey", self.quick_add_hotkey),
        ):
            if self.config.get(key) != value:
                self.config[key] = value
                config_updated = True
        if config_updated:
            storage.save_config(self.config)

        self._allow_close = False

        self.engine.set_cooldown(float(self.config.get("cooldown", 0.3)))
        self.engine.set_paste_delay(float(self.config.get("paste_delay", 0.05)))
        self.engine.update_hotkeys(self.hotkeys)
        self.engine.set_logger(self.logger)

        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(760, 480)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        input_row = QtWidgets.QHBoxLayout()
        self.key_edit = QtWidgets.QLineEdit()
        self.key_edit.setPlaceholderText("Hotkey trigger")
        self.value_edit = QtWidgets.QLineEdit()
        self.value_edit.setPlaceholderText("Expansion output")
        add_btn = QtWidgets.QPushButton("Add")
        delete_btn = QtWidgets.QPushButton("Delete Selected")
        special_btn = QtWidgets.QPushButton("Special Add")

        add_btn.clicked.connect(self.add_hotkey)
        delete_btn.clicked.connect(self.delete_selected)
        special_btn.clicked.connect(self.open_special_add)
        self.key_edit.returnPressed.connect(self._handle_return_pressed)
        self.value_edit.returnPressed.connect(self._handle_return_pressed)

        input_row.addWidget(QtWidgets.QLabel("Hotkey:"))
        input_row.addWidget(self.key_edit, 1)
        input_row.addWidget(QtWidgets.QLabel("→"))
        input_row.addWidget(self.value_edit, 2)
        input_row.addWidget(add_btn)
        input_row.addWidget(delete_btn)
        input_row.addWidget(special_btn)
        layout.addLayout(input_row)

        search_row = QtWidgets.QHBoxLayout()
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search triggers or outputs…")
        search_row.addWidget(self.search_edit, 1)
        layout.addLayout(search_row)

        self.model = QtGui.QStandardItemModel(0, 2, self)
        self.model.setHorizontalHeaderLabels(["Hotkey", "Output"])
        self.populate_model()

        self.proxy = HotkeyFilter()
        self.proxy.setSourceModel(self.model)

        self.table = QtWidgets.QTableView()
        self.table.setModel(self.proxy)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        self.table.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_hotkey_context_menu)
        layout.addWidget(self.table, 1)
        self.copy_action = QtWidgets.QAction("Copy", self)
        self.copy_action.setShortcut(QtGui.QKeySequence.Copy)
        self.copy_action.triggered.connect(self.copy_selected_hotkeys)
        self.table.addAction(self.copy_action)

        self.paste_action = QtWidgets.QAction("Paste", self)
        self.paste_action.setShortcut(QtGui.QKeySequence.Paste)
        self.paste_action.triggered.connect(self.paste_hotkeys)
        self.table.addAction(self.paste_action)

        self.delete_action = QtWidgets.QAction("Delete", self)
        self.delete_action.setShortcut(QtGui.QKeySequence.Delete)
        self.delete_action.triggered.connect(self.delete_selected)
        self.table.addAction(self.delete_action)

        self._apply_table_header_theme()

        bottom_row = QtWidgets.QHBoxLayout()
        self.profile_menu = QtWidgets.QMenu(self)
        self.profile_menu.triggered.connect(self._on_profile_menu_triggered)
        self.profile_button = QtWidgets.QPushButton()
        self.profile_button.setMenu(self.profile_menu)
        bottom_row.addWidget(self.profile_button)

        self.profile_create_container = QtWidgets.QWidget()
        profile_create_layout = QtWidgets.QHBoxLayout(self.profile_create_container)
        profile_create_layout.setContentsMargins(0, 0, 0, 0)
        self.profile_create_label = QtWidgets.QLabel("Enter new name:")
        self.profile_create_edit = QtWidgets.QLineEdit()
        self.profile_create_ok = QtWidgets.QPushButton("OK")
        self.profile_create_cancel = QtWidgets.QPushButton("Cancel")
        profile_create_layout.addWidget(self.profile_create_label)
        profile_create_layout.addWidget(self.profile_create_edit)
        profile_create_layout.addWidget(self.profile_create_ok)
        profile_create_layout.addWidget(self.profile_create_cancel)
        self.profile_create_container.setVisible(False)
        self.profile_create_ok.clicked.connect(self._on_profile_create_confirmed)
        self.profile_create_cancel.clicked.connect(self._hide_profile_create_inline)
        self.profile_create_edit.returnPressed.connect(self._on_profile_create_confirmed)
        bottom_row.addWidget(self.profile_create_container)
        bottom_row.addStretch(1)

        self.hotkey_count_label = QtWidgets.QLabel()
        self.fired_count_label = QtWidgets.QLabel()
        bottom_row.addWidget(self.hotkey_count_label)
        bottom_row.addWidget(self.fired_count_label)

        self.toggle_btn = QtWidgets.QToolButton()
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.setIconSize(QtCore.QSize(24, 24))
        self.toggle_btn.setAutoRaise(True)
        self.toggle_btn.clicked.connect(self.toggle_enabled)
        self.toggle_btn.setStyleSheet("QToolButton { background: transparent; border: none; padding: 0; }")
        bottom_row.addWidget(self.toggle_btn)

        self.settings_btn = QtWidgets.QPushButton("Settings")
        self.settings_btn.setToolTip("Open settings")
        self.settings_btn.clicked.connect(self.open_settings)
        bottom_row.addWidget(self.settings_btn)

        layout.addLayout(bottom_row)

        self.search_edit.textChanged.connect(self.proxy.setQuery)
        self.tray: QtWidgets.QSystemTrayIcon | None = None
        self.refresh_status_ui()
        self._refresh_profile_menu()

        self.counter_timer = QtCore.QTimer(self)
        self.counter_timer.setInterval(300)
        self.counter_timer.timeout.connect(self.refresh_counters_only)
        self.counter_timer.start()
        self.tray = QtWidgets.QSystemTrayIcon(self)
        self.tray.setIcon(make_status_icon(self.enabled))

        self.tray_menu = QtWidgets.QMenu()
        self.tray_profile_menu = QtWidgets.QMenu("Profiles", self.tray_menu)
        self.tray_profile_menu.triggered.connect(self._on_tray_profile_triggered)
        self.tray_menu.addAction("Toggle Enabled", self.toggle_enabled)
        self.tray_menu.addAction("Settings", self.open_settings)
        self.tray_menu.addMenu(self.tray_profile_menu)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("Show/Hide", self.toggle_window_visibility)
        self.tray_menu.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(self.tray_menu)        
        self.tray.activated.connect(self._tray_activated)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()
        self._refresh_tray_profile_menu()
        self._tray_active_icon = make_status_icon(True, override_color=QtGui.QColor("#f1c40f"))
        self._active_fire_count = 0

        self.engine.set_fire_hooks(
            on_start=self._notify_fire_start,
            on_end=self._notify_fire_end,
        )

        if self.engine.hooks_available():
            self._register_global_hotkeys()

        self._was_hidden_to_tray = False
        self.settings_dialog: SettingsDialog | None = None
        self._tray_message_shown = False
        self._is_outputting = False
        self._profile_toast: ProfileSwitchToast | None = None
        self._quick_add_toast: ProfileSwitchToast | None = None
        self.quick_add_dialog: QuickAddDialog | None = None

        app = QtWidgets.QApplication.instance()
        if app:
            app.focusChanged.connect(self._on_focus_changed)
            self.engine.set_app_active(app.activeWindow() is not None)

        set_app_palette(self.dark_mode)
        self._apply_table_header_theme()
        QtCore.QTimer.singleShot(200, self._maybe_show_use_policy_prompt)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _compose_hotkey(self, key: str) -> str:
        normalized_key = normalize_hotkey_key(key)
        if not normalized_key:
            return ""
        return f"{self.hotkey_modifier}+{normalized_key}"
    
    def populate_model(self) -> None:
        self.model.setRowCount(0)
        for trigger, output in self.hotkeys.items():
            items = [QtGui.QStandardItem(trigger), QtGui.QStandardItem(output)]
            self.model.appendRow(items)

    def _run_on_ui_thread(self, action: Callable[[], None]) -> None:
        app = QtWidgets.QApplication.instance()
        if app is None:
            action()
            return
        if QtCore.QThread.currentThread() == app.thread():
            action()
        else:
            QtCore.QTimer.singleShot(0, action)

    def refresh_status_ui(self) -> None:
        self.refresh_counters_only()
        status_icon = make_status_icon(self.enabled)
        self.toggle_btn.setChecked(self.enabled)
        self.toggle_btn.setIcon(status_icon)
        self.toggle_btn.setToolTip("Click to disable hotkeys" if self.enabled else "Click to enable hotkeys")
        self.setWindowIcon(status_icon)
        app = QtWidgets.QApplication.instance()
        if app:
            app.setWindowIcon(status_icon)
        if self.tray is not None and not self._is_outputting:
            self.tray.setIcon(status_icon)

    def _apply_table_header_theme(self) -> None:
        header = self.table.horizontalHeader()
        if self.dark_mode:
            header.setStyleSheet(
                "QHeaderView::section { background-color: #1f1f24; color: #ff7b7b; border: 1px solid #ff8080; }"
            )
        else:
            header.setStyleSheet("")

    def _show_hotkey_context_menu(self, position: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        menu.addAction(self.copy_action)
        menu.addAction(self.paste_action)
        menu.addSeparator()
        menu.addAction(self.delete_action)
        menu.exec_(self.table.viewport().mapToGlobal(position))

    def _selected_hotkeys(self) -> list[tuple[str, str]]:
        selection = self.table.selectionModel().selectedRows()
        hotkeys: list[tuple[str, str]] = []
        for index in selection:
            source = self.proxy.mapToSource(index)
            trigger = self.model.item(source.row(), 0).text()
            output = self.model.item(source.row(), 1).text()
            hotkeys.append((trigger, output))
        return hotkeys

    def copy_selected_hotkeys(self) -> None:
        hotkeys = self._selected_hotkeys()
        if not hotkeys:
            return
        payload = [{"trigger": trigger, "output": output} for trigger, output in hotkeys]
        clipboard = QtWidgets.QApplication.clipboard()
        clipboard.setText(f"{HOTKEY_CLIPBOARD_PREFIX}{json.dumps(payload)}")

    def paste_hotkeys(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        text = clipboard.text()
        if not text.startswith(HOTKEY_CLIPBOARD_PREFIX):
            QtWidgets.QMessageBox.information(
                self,
                "Paste Hotkeys",
                "Clipboard does not contain OpenKeyFlow hotkeys.",
            )
            return
        raw = text[len(HOTKEY_CLIPBOARD_PREFIX) :]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            QtWidgets.QMessageBox.warning(self, "Paste Hotkeys", "Clipboard data is not valid.")
            return
        if not isinstance(payload, list):
            QtWidgets.QMessageBox.warning(self, "Paste Hotkeys", "Clipboard data is not valid.")
            return

        incoming: list[tuple[str, str]] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            trigger = item.get("trigger")
            output = item.get("output")
            if isinstance(trigger, str) and isinstance(output, str):
                trigger = trigger.strip()
                if trigger:
                    incoming.append((trigger, output))

        if not incoming:
            QtWidgets.QMessageBox.information(self, "Paste Hotkeys", "No hotkeys found to paste.")
            return

        with self.hotkey_lock:
            conflicts = [trigger for trigger, _ in incoming if trigger in self.hotkeys]

        overwrite = False
        if conflicts:
            response = QtWidgets.QMessageBox.question(
                self,
                "Paste Hotkeys",
                f"{len(conflicts)} hotkeys already exist. Replace them?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            overwrite = response == QtWidgets.QMessageBox.Yes

        added = 0
        replaced = 0
        with self.hotkey_lock:
            for trigger, output in incoming:
                if trigger in self.hotkeys and not overwrite:
                    continue
                if trigger in self.hotkeys:
                    replaced += 1
                else:
                    added += 1
                self.hotkeys[trigger] = output

        if added or replaced:
            self._save_current_profile()
            self.engine.update_hotkeys(self.hotkeys)
            self.populate_model()
            self.refresh_status_ui()
            message = f"Added {added} hotkeys."
            if replaced:
                message = f"Added {added} hotkeys and replaced {replaced}."
            QtWidgets.QMessageBox.information(self, "Paste Hotkeys", message)
        else:
            QtWidgets.QMessageBox.information(self, "Paste Hotkeys", "No new hotkeys were added.")

    def _notify_fire_start(self) -> None:
        QtCore.QTimer.singleShot(0, self._start_tray_flash)

    def _notify_fire_end(self) -> None:
        QtCore.QTimer.singleShot(0, self._stop_tray_flash)

    def _start_tray_flash(self) -> None:
        self._active_fire_count += 1
        if self._active_fire_count == 1:
            self._is_outputting = True
            if self.tray is not None:
                self.tray.setIcon(self._tray_active_icon)

    def _stop_tray_flash(self) -> None:
        if self._active_fire_count == 0:
            return
        self._active_fire_count -= 1
        if self._active_fire_count == 0:
            self._is_outputting = False
            if self.tray is not None:
                self.tray.setIcon(make_status_icon(self.enabled))

    def _on_focus_changed(self, _old: QtWidgets.QWidget | None, _new: QtWidgets.QWidget | None) -> None:
        app = QtWidgets.QApplication.instance()
        if not app:
            return
        self.engine.set_app_active(app.activeWindow() is not None)

    def set_dark_mode(self, enabled: bool) -> None:
        self.dark_mode = enabled
        set_app_palette(self.dark_mode)
        self._apply_table_header_theme()
        self._apply_profile_button_color()
        self.config["dark_mode"] = self.dark_mode
        storage.save_config(self.config)
        if self.settings_dialog:
            self.settings_dialog._apply_section_title_style()
            self.settings_dialog._apply_theme_assets()

    def set_hotkey_modifier(self, modifier: str) -> None:
        normalized = normalize_hotkey_modifier(modifier)
        if normalized == self.hotkey_modifier:
            return
        previous = {
            "quick_add": self.quick_add_hotkey,
            "profile_switch": self.profile_switch_hotkey,
            "toggle": self.toggle_hotkey,
        }
        self.hotkey_modifier = normalized
        self.quick_add_hotkey = self._compose_hotkey(self.quick_add_key)
        self.profile_switch_hotkey = self._compose_hotkey(self.profile_switch_key)
        self.toggle_hotkey = self._compose_hotkey(self.toggle_hotkey_key)
        self._persist_hotkey_settings()
        self._rebuild_global_hotkeys(previous)
        self._warn_if_hotkey_conflict(self.quick_add_hotkey, "Quick Add hotkey")
        self._warn_if_hotkey_conflict(self.profile_switch_hotkey, "Profile Switch hotkey")
        self._warn_if_hotkey_conflict(self.toggle_hotkey, "Toggle OpenKeyFlow hotkey")

    def set_quick_add_key(self, key: str) -> None:
        normalized = normalize_hotkey_key(key)
        if normalized == self.quick_add_key:
            return
        previous = {
            "quick_add": self.quick_add_hotkey,
            "profile_switch": self.profile_switch_hotkey,
            "toggle": self.toggle_hotkey,
        }
        self.quick_add_key = normalized
        self.quick_add_hotkey = self._compose_hotkey(self.quick_add_key)
        self._persist_hotkey_settings()
        self._rebuild_global_hotkeys(previous)
        self._warn_if_hotkey_conflict(self.quick_add_hotkey, "Quick Add hotkey")

    def set_profile_switch_key(self, key: str) -> None:
        normalized = normalize_hotkey_key(key)
        if normalized == self.profile_switch_key:
            return
        previous = {
            "quick_add": self.quick_add_hotkey,
            "profile_switch": self.profile_switch_hotkey,
            "toggle": self.toggle_hotkey,
        }
        self.profile_switch_key = normalized
        self.profile_switch_hotkey = self._compose_hotkey(self.profile_switch_key)
        self._persist_hotkey_settings()
        self._rebuild_global_hotkeys(previous)
        self._warn_if_hotkey_conflict(self.profile_switch_hotkey, "Profile Switch hotkey")

    def set_toggle_hotkey_key(self, key: str) -> None:
        normalized = normalize_hotkey_key(key)
        if normalized == self.toggle_hotkey_key:
            return
        previous = {
            "quick_add": self.quick_add_hotkey,
            "profile_switch": self.profile_switch_hotkey,
            "toggle": self.toggle_hotkey,
        }
        self.toggle_hotkey_key = normalized
        self.toggle_hotkey = self._compose_hotkey(self.toggle_hotkey_key)
        self._persist_hotkey_settings()
        self._rebuild_global_hotkeys(previous)
        self._warn_if_hotkey_conflict(self.toggle_hotkey, "Toggle OpenKeyFlow hotkey")

    def _persist_hotkey_settings(self) -> None:
        self.config["hotkey_modifier"] = self.hotkey_modifier
        self.config["quick_add_key"] = self.quick_add_key
        self.config["profile_switch_key"] = self.profile_switch_key
        self.config["toggle_hotkey_key"] = self.toggle_hotkey_key
        self.config["quick_add_hotkey"] = self.quick_add_hotkey
        storage.save_config(self.config)

    def _rebuild_global_hotkeys(self, previous_hotkeys: Dict[str, str]) -> None:
        if not self.engine.hooks_available():
            return
        for hotkey in previous_hotkeys.values():
            if hotkey:
                self.engine.remove_hotkey(hotkey)
        self._register_global_hotkeys()

    def reset_global_hotkeys(self) -> None:
        previous = {
            "quick_add": self.quick_add_hotkey,
            "profile_switch": self.profile_switch_hotkey,
            "toggle": self.toggle_hotkey,
        }
        self.hotkey_modifier = DEFAULT_HOTKEY_MODIFIER
        self.quick_add_key = DEFAULT_QUICK_ADD_KEY
        self.profile_switch_key = DEFAULT_PROFILE_SWITCH_KEY
        self.toggle_hotkey_key = DEFAULT_TOGGLE_HOTKEY_KEY
        self.quick_add_hotkey = self._compose_hotkey(self.quick_add_key)
        self.profile_switch_hotkey = self._compose_hotkey(self.profile_switch_key)
        self.toggle_hotkey = self._compose_hotkey(self.toggle_hotkey_key)
        self._persist_hotkey_settings()
        self._rebuild_global_hotkeys(previous)
        self._warn_if_hotkey_conflict(self.quick_add_hotkey, "Quick Add hotkey")
        self._warn_if_hotkey_conflict(self.profile_switch_hotkey, "Profile Switch hotkey")
        self._warn_if_hotkey_conflict(self.toggle_hotkey, "Toggle OpenKeyFlow hotkey")

    def _register_global_hotkeys(self) -> None:
        if not self.engine.hooks_available():
            return
        if self.toggle_hotkey:
            self.engine.add_hotkey(
                self.toggle_hotkey,
                lambda: self._run_on_ui_thread(self.toggle_enabled),
            )
        if self.profile_switch_hotkey:
            self.engine.add_hotkey(
                self.profile_switch_hotkey,
                lambda: self._run_on_ui_thread(self.cycle_profile_hotkey),
            )
        if self.quick_add_hotkey:
            self._register_quick_add_hotkey(self.quick_add_hotkey)

    def _warn_if_hotkey_conflict(self, hotkey: str, action_label: str) -> None:
        if not hotkey:
            return
        try:
            os_label = self.current_os_label()
            conflicts = HOTKEY_CONFLICTS.get(os_label, set())
            if hotkey in conflicts:
                QtWidgets.QMessageBox.information(
                    self,
                    "Potential Hotkey Conflict",
                    (
                        f"{action_label} is set to '{hotkey}', which can conflict with system shortcuts."
                        " OpenKeyFlow will still use the hotkey, but it may be intercepted by the OS."
                    ),
                )
        except Exception:
            return

    def set_logging_enabled(self, enabled: bool, path: Path | None = None) -> None:
        log_path = Path(path) if path else Path(self.config.get("log_file", storage.default_log_path()))
        self.config["logging_enabled"] = enabled
        self.config["log_file"] = str(log_path)
        storage.save_config(self.config)
        try:
            configure_logging(enabled, log_path)
            self.logger = get_logger()
            self.engine.set_logger(self.logger)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Logging",
                f"Failed to configure logging at {log_path}:\n{exc}",
            )
            self.config["logging_enabled"] = False
            storage.save_config(self.config)

    def set_logging_path(self, path: Path) -> None:
        self.config["log_file"] = str(path)
        storage.save_config(self.config)
        try:
            configure_logging(bool(self.config.get("logging_enabled", False)), path)
            self.logger = get_logger()
            self.engine.set_logger(self.logger)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Logging",
                f"Failed to set log path to {path}:\n{exc}",
            )

    def set_profiles_encrypted(self, enabled: bool) -> bool:
        if enabled:
            result = self._prompt_new_passphrase(
                "Encrypt Profiles",
                "Create a passphrase:",
            )
            if not result:
                return False
            passphrase, recovery_code = result
            try:
                storage.save_profiles(self.current_profile, self.profiles, passphrase=passphrase)
            except Exception as exc:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Encrypt Profiles",
                    f"Failed to encrypt profiles:\n{exc}",
                )
                return False
            self.profiles_encrypted = True
            self.profile_passphrase = passphrase
            self.config["profiles_encrypted"] = True
            self.config["profile_recovery_code"] = recovery_code
            storage.save_config(self.config)
            return True

        if not self.profiles_encrypted:
            return True

        passphrase = self.profile_passphrase or self._prompt_passphrase(
            "Decrypt Profiles",
            "Enter your current passphrase:",
        )
        if not passphrase:
            return False
        try:
            storage.load_profiles(passphrase=passphrase)
        except storage.ProfilesEncryptionError as exc:
            QtWidgets.QMessageBox.warning(self, "Decrypt Profiles", str(exc))
            return False
        try:
            storage.save_profiles(self.current_profile, self.profiles)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Decrypt Profiles",
                f"Failed to save decrypted profiles:\n{exc}",
            )
            return False
        self.profiles_encrypted = False
        self.profile_passphrase = None
        self.config["profiles_encrypted"] = False
        storage.save_config(self.config)
        return True

    def change_profiles_passphrase(self) -> None:
        if not self.profiles_encrypted:
            QtWidgets.QMessageBox.information(
                self,
                "Change Passphrase",
                "Profiles are not encrypted.",
            )
            return
        current_passphrase = self.profile_passphrase or self._prompt_passphrase(
            "Change Passphrase",
            "Enter your current passphrase:",
        )
        if not current_passphrase:
            return
        try:
            storage.load_profiles(passphrase=current_passphrase)
        except storage.ProfilesEncryptionError as exc:
            QtWidgets.QMessageBox.warning(self, "Change Passphrase", str(exc))
            return
        result = self._prompt_new_passphrase(
            "Change Passphrase",
            "Enter a new passphrase:",
        )
        if not result:
            return
        new_passphrase, recovery_code = result
        try:
            storage.save_profiles(self.current_profile, self.profiles, passphrase=new_passphrase)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(
                self,
                "Change Passphrase",
                f"Failed to update passphrase:\n{exc}",
            )
            return
        self.profile_passphrase = new_passphrase
        self.config["profiles_encrypted"] = True
        self.config["profile_recovery_code"] = recovery_code
        storage.save_config(self.config)

    def _prompt_passphrase(self, title: str, prompt: str, *, confirm: bool = False) -> str | None:
        passphrase, ok = QtWidgets.QInputDialog.getText(
            self,
            title,
            prompt,
            QtWidgets.QLineEdit.Password,
        )
        if not ok:
            return None
        passphrase = passphrase.strip()
        if not passphrase:
            return None
        if confirm:
            confirm_value, ok = QtWidgets.QInputDialog.getText(
                self,
                title,
                "Confirm passphrase:",
                QtWidgets.QLineEdit.Password,
            )
            if not ok:
                return None
            if confirm_value != passphrase:
                QtWidgets.QMessageBox.warning(
                    self,
                    title,
                    "Passphrases do not match.",
                )
                return None
        return passphrase

    def _prompt_new_passphrase(self, title: str, prompt: str) -> tuple[str, str] | None:
        dialog = PassphraseDialog(self, title, prompt)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None
        passphrase = dialog.passphrase()
        if not passphrase:
            return None
        return passphrase, dialog.recovery_code

    def update_autostart(self, enabled: bool) -> bool:
        return set_autostart_enabled(self, enabled)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        self.settings_dialog = dialog
        dialog.finished.connect(self._on_settings_closed)
        dialog.exec_()

    def _on_settings_closed(self) -> None:
        self.settings_dialog = None

    def _maybe_show_use_policy_prompt(self) -> None:
        if self.config.get("accepted_use_policy"):
            return

        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Information)
        msg.setWindowTitle("Acceptable Use Policy")
        msg.setText(
            "OpenKeyFlow is intended for accessibility and productivity automation only."
        )
        msg.setInformativeText(
            "By clicking OK, you confirm you will operate OpenKeyFlow ethically and lawfully."
        )
        msg.setStandardButtons(QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel)
        msg.setDefaultButton(QtWidgets.QMessageBox.Ok)
        result = msg.exec_()

        if result == QtWidgets.QMessageBox.Ok:
            self.config["accepted_use_policy"] = True
            storage.save_config(self.config)
        else:
            QtWidgets.QApplication.instance().quit()

    def refresh_counters_only(self) -> None:
        fired = self.engine.get_stats()["fired"]
        self.hotkey_count_label.setText(f"Hotkeys: {len(self.hotkeys)}")
        self.fired_count_label.setText(f"Fired: {fired}")

    def toggle_window_visibility(self) -> None:
        if self.isVisible():
            self.hide()
            self._was_hidden_to_tray = True
        else:
            self.showNormal()
            self.activateWindow()
            self.raise_()

    def _handle_return_pressed(self) -> None:
        trigger = self.key_edit.text()
        output = self.value_edit.text()
        if trigger and output:
            self.add_hotkey()
        elif not trigger and not output:
            self.open_special_add()
        elif not trigger:
            self.key_edit.setFocus()
        else:
            self.value_edit.setFocus()

    def _tray_activated(self, reason: QtWidgets.QSystemTrayIcon.ActivationReason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.toggle_window_visibility()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self._allow_close:
            event.accept()
            return
        self.hide()
        self._was_hidden_to_tray = True
        if self.tray and not self._tray_message_shown:
            self.tray.showMessage(APP_NAME, "OpenKeyFlow is still running in the system tray. Use Quit to exit.")
            self._tray_message_shown = True
        event.ignore()

    def quit_app(self) -> None:
        try:
            if self.toggle_hotkey:
                self.engine.remove_hotkey(self.toggle_hotkey)
            if self.profile_switch_hotkey:
                self.engine.remove_hotkey(self.profile_switch_hotkey)
            if self.quick_add_hotkey:
                self.engine.remove_hotkey(self.quick_add_hotkey)
        except Exception:
            pass
        self._allow_close = True
        QtWidgets.QApplication.instance().quit()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def add_hotkey(self) -> None:
        trigger = self.key_edit.text()
        output = self.value_edit.text()
        if not trigger and not output:
            self.open_special_add()
            return
        if not trigger or not output:
            QtWidgets.QMessageBox.warning(self, "Add Hotkey", "Both trigger and output are required.")
            return
        if self._add_hotkey(trigger, output):
            self.key_edit.clear()
            self.value_edit.clear()

    def open_special_add(self) -> None:
        dialog = SpecialAddDialog(self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            trigger, output = dialog.get_data()
            self._add_hotkey(trigger, output)

    def open_quick_add_from_clipboard(self) -> None:
        clipboard = QtWidgets.QApplication.clipboard()
        if clipboard is None:
            self._show_quick_add_toast("Clipboard has no text to add")
            return
        mime = clipboard.mimeData()
        if mime is None or not mime.hasText():
            self._show_quick_add_toast("Clipboard has no text to add")
            return
        text = mime.text()
        if not text.strip():
            self._show_quick_add_toast("Clipboard has no text to add")
            return

        active_modal = QtWidgets.QApplication.activeModalWidget()
        if active_modal is not None and not isinstance(active_modal, QuickAddDialog):
            active_modal.raise_()
            active_modal.activateWindow()
            return

        self.logger.info("[QUICK_ADD] opened, clipboard_len=%s", len(text))
        dialog = active_modal if isinstance(active_modal, QuickAddDialog) else self._get_quick_add_dialog()
        dialog.set_clipboard_text(text)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _add_hotkey(self, trigger: str, output: str) -> bool:
        normalized_trigger = trigger.strip()
        if not normalized_trigger:
            QtWidgets.QMessageBox.warning(self, "Add Hotkey", "Trigger is required.")
            return False
        if " " in normalized_trigger:
            QtWidgets.QMessageBox.warning(self, "Add Hotkey", "Triggers cannot contain spaces.")
            return False
        if not output:
            QtWidgets.QMessageBox.warning(self, "Add Hotkey", "Output is required.")
            return False

        with self.hotkey_lock:
            if normalized_trigger in self.hotkeys:
                QtWidgets.QMessageBox.warning(self, "Add Hotkey", "Trigger already exists.")
                return False
            overlaps = [
                existing
                for existing in self.hotkeys
                if existing != normalized_trigger
                and (existing.startswith(normalized_trigger) or normalized_trigger.startswith(existing))
            ]

        if overlaps:
            overlaps_text = "\n".join(f"• {name}" for name in overlaps)
            response = QtWidgets.QMessageBox.question(
                self,
                "Potential Conflict",
                (
                    "This trigger overlaps with existing ones and may cause unreliable expansions.\n\n"
                    f"Existing overlaps:\n{overlaps_text}\n\n"
                    "Do you want to add it anyway?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if response != QtWidgets.QMessageBox.Yes:
                return False

        with self.hotkey_lock:
            if normalized_trigger in self.hotkeys:
                QtWidgets.QMessageBox.warning(self, "Add Hotkey", "Trigger already exists.")
                return False
            self.hotkeys[normalized_trigger] = output

        self._save_current_profile()
        self.engine.update_hotkeys(self.hotkeys)
        self.populate_model()
        self.refresh_status_ui()
        return True

    def delete_selected(self) -> None:
        selection = self.table.selectionModel().selectedRows()
        if not selection:
            return
        to_delete = []
        for index in selection:
            source = self.proxy.mapToSource(index)
            trigger = self.model.item(source.row(), 0).text()
            to_delete.append(trigger)
        if not to_delete:
            return
        count = len(to_delete)
        prompt = "Delete this hotkey?" if count == 1 else f"Delete these {count} selected hotkeys?"
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete Hotkeys",
            prompt,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return
        with self.hotkey_lock:
            for trigger in to_delete:
                self.hotkeys.pop(trigger, None)
        self._save_current_profile()
        self.engine.update_hotkeys(self.hotkeys)
        self.populate_model()
        self.refresh_status_ui()

    def import_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV Files (*.csv)")
        if not path:
            return        
        incoming = list(storage.import_hotkeys_from_csv(Path(path)))
        if not incoming:
            QtWidgets.QMessageBox.information(self, "Import", "No hotkeys found to import.")
            return
        choice = self._prompt_import_destination(len(incoming))
        if not choice:
            return
        profile_name, switch_to = choice
        added = self._import_hotkeys_to_profile(profile_name, incoming, switch_to)
        QtWidgets.QMessageBox.information(
            self,
            "Import",
            f"Imported {added} hotkeys into '{profile_name}'.",
        )

    def export_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        storage.export_hotkeys_to_csv(Path(path), self.hotkeys)
        QtWidgets.QMessageBox.information(self, "Export", f"Exported {len(self.hotkeys)} hotkeys.")

    def export_sample_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export Sample CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        storage.export_sample_csv(Path(path))
        QtWidgets.QMessageBox.information(self, "Export Sample CSV", "Exported a sample CSV template.")

    def cycle_profile_hotkey(self) -> None:
        profile_names = self.profile_names()
        if len(profile_names) <= 1:
            return
        try:
            current_index = profile_names.index(self.current_profile)
        except ValueError:
            current_index = 0
        next_index = (current_index + 1) % len(profile_names)
        next_profile = profile_names[next_index]
        self.set_current_profile(next_profile, announce=True)

    def _prompt_import_destination(self, count: int) -> tuple[str, bool] | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Import Hotkeys")
        layout = QtWidgets.QVBoxLayout(dialog)

        prompt = QtWidgets.QLabel(
            f"Found {count} hotkeys to import. Choose a destination profile:"
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        combo = QtWidgets.QComboBox()
        for name in self.profile_names():
            combo.addItem(name, name)
        combo.addItem("Create new profile…", "__new__")
        layout.addWidget(combo)

        new_name_edit = QtWidgets.QLineEdit()
        new_name_edit.setPlaceholderText("New profile name")
        new_name_edit.setVisible(False)
        layout.addWidget(new_name_edit)

        switch_checkbox = QtWidgets.QCheckBox("Switch to selected profile after import")
        switch_checkbox.setChecked(True)
        layout.addWidget(switch_checkbox)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        layout.addWidget(buttons)

        def on_selection_changed(index: int) -> None:
            is_new = combo.itemData(index) == "__new__"
            new_name_edit.setVisible(is_new)
            if is_new:
                switch_checkbox.setChecked(True)

        def on_accept() -> None:
            if combo.currentData() == "__new__":
                name = self._normalize_profile_name(new_name_edit.text())
                if not name:
                    QtWidgets.QMessageBox.warning(dialog, "Import Hotkeys", "Profile name cannot be empty.")
                    return
                if name in self.profiles:
                    QtWidgets.QMessageBox.warning(dialog, "Import Hotkeys", "That profile already exists.")
                    return
            dialog.accept()

        combo.currentIndexChanged.connect(on_selection_changed)
        buttons.accepted.connect(on_accept)
        buttons.rejected.connect(dialog.reject)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None

        if combo.currentData() == "__new__":
            profile_name = self._normalize_profile_name(new_name_edit.text())
        else:
            profile_name = combo.currentData()

        if not profile_name:
            return None

        return profile_name, switch_checkbox.isChecked()

    def _import_hotkeys_to_profile(
        self,
        profile_name: str,
        incoming: list[tuple[str, str]],
        switch_to: bool,
    ) -> int:
        added = 0
        with self.hotkey_lock:
            self.profiles[self.current_profile] = dict(self.hotkeys)
            profile_hotkeys = dict(self.profiles.get(profile_name, {}))
            for trigger, output in incoming:
                profile_hotkeys[trigger] = output
                added += 1
            self.profiles[profile_name] = profile_hotkeys

        if switch_to:
            self.current_profile = profile_name
            self.hotkeys = dict(self.profiles[profile_name])
            self.engine.update_hotkeys(self.hotkeys)
            self.populate_model()
            self.refresh_status_ui()
        elif profile_name == self.current_profile:
            self.hotkeys = dict(self.profiles[profile_name])
            self.engine.update_hotkeys(self.hotkeys)
            self.populate_model()
            self.refresh_status_ui()

        passphrase = self.profile_passphrase if self.profiles_encrypted else None
        storage.save_profiles(self.current_profile, self.profiles, passphrase=passphrase)
        self._sync_profile_ui()
        return added

    def toggle_enabled(self) -> None:
        self.enabled = self.engine.toggle_enabled()
        self.refresh_status_ui()

    def toggle_theme(self) -> None:
        self.set_dark_mode(not self.dark_mode)

    # ------------------------------------------------------------------
    # Profiles
    # ------------------------------------------------------------------
    def profile_names(self) -> list[str]:
        return list(self.profiles.keys())

    def profile_color(self, name: str) -> str | None:
        color = self.profile_colors.get(name)
        if isinstance(color, str) and color:
            return color
        return None

    def set_profile_color(self, name: str, color: str | None) -> None:
        if not name:
            return
        if color:
            self.profile_colors[name] = color
        else:
            self.profile_colors.pop(name, None)
        self.config["profile_colors"] = dict(self.profile_colors)
        storage.save_config(self.config)
        self._apply_profile_button_color()
        self._sync_profile_ui()

    def _show_profile_switch_toast(self, profile_name: str) -> None:
        color_hex = self.profile_color(profile_name) or "#f1c40f"
        color = QtGui.QColor(color_hex)
        if self._profile_toast is not None:
            self._profile_toast.close()
        message = f"Switched to profile: {profile_name}"
        self._profile_toast = ProfileSwitchToast(message, color)
        self._profile_toast.show_toast()

    def _show_quick_add_toast(self, message: str) -> None:
        color = QtGui.QColor("#f1c40f")
        if self._quick_add_toast is not None:
            self._quick_add_toast.close()
        self._quick_add_toast = ProfileSwitchToast(message, color)
        self._quick_add_toast.show_toast()

    def _register_quick_add_hotkey(self, hotkey: str) -> None:
        if not hotkey:
            return
        self.engine.add_hotkey(
            hotkey,
            lambda: self._run_on_ui_thread(self.open_quick_add_from_clipboard),
        )

    def _get_quick_add_dialog(self) -> QuickAddDialog:
        if self.quick_add_dialog is None:
            dialog = QuickAddDialog(self)
            dialog.accepted.connect(self._on_quick_add_accepted)
            self.quick_add_dialog = dialog
        color_hex = self.profile_color(self.current_profile) or "#f1c40f"
        self.quick_add_dialog.set_header_color(QtGui.QColor(color_hex))
        self.quick_add_dialog.set_theme(self.dark_mode)
        return self.quick_add_dialog

    def _on_quick_add_accepted(self) -> None:
        if self.quick_add_dialog is None:
            return
        trigger, output = self.quick_add_dialog.get_data()
        if not self._add_hotkey(trigger, output):
            self.quick_add_dialog.set_data(trigger, output, focus_trigger=True)
            self.quick_add_dialog.show()
            self.quick_add_dialog.raise_()
            self.quick_add_dialog.activateWindow()

    def current_os_label(self) -> str:
        platform = sys.platform
        if platform.startswith("win"):
            return "windows"
        if platform.startswith("linux"):
            return "linux"
        if platform.startswith("darwin"):
            return "macos"
        return "windows"

    def _refresh_profile_combo(self) -> None:
        self._refresh_profile_menu()

    def _refresh_profile_menu(self) -> None:
        self.profile_menu.clear()
        for name in self.profile_names():
            action = self.profile_menu.addAction(name)
            action.setData(name)
            color = self.profile_color(name)
            if color:
                action.setIcon(make_color_icon(QtGui.QColor(color)))
        self.profile_menu.addSeparator()
        add_action = self.profile_menu.addAction("Add new profile…")
        add_action.setData(None)
        self.profile_button.setText(f"Profile: {self.current_profile}")
        self._apply_profile_button_color()
        self._refresh_tray_profile_menu()

    def _refresh_tray_profile_menu(self) -> None:
        if not hasattr(self, "tray_profile_menu") or self.tray_profile_menu is None:
            return
        self.tray_profile_menu.clear()
        action_group = QtWidgets.QActionGroup(self.tray_profile_menu)
        action_group.setExclusive(True)
        for name in self.profile_names():
            action = self.tray_profile_menu.addAction(name)
            action.setCheckable(True)
            action.setChecked(name == self.current_profile)
            action.setData(name)
            action_group.addAction(action)
            color = self.profile_color(name)
            if color:
                action.setIcon(make_color_icon(QtGui.QColor(color)))
        self.tray_profile_menu.addSeparator()
        create_action = self.tray_profile_menu.addAction("Create New Profile…")

    def _sync_profile_ui(self) -> None:
        self._refresh_profile_menu()
        if self.settings_dialog:
            self.settings_dialog.refresh_profiles()

    def _on_profile_menu_triggered(self, action: QtGui.QAction) -> None:
        data = action.data()
        if data is None:
            self._show_profile_create_inline()
            return
        if data != self.current_profile:
            self.set_current_profile(data)

    def _on_tray_profile_triggered(self, action: QtGui.QAction) -> None:
        data = action.data()
        if data == "__create__":
            self.show_profile_create_from_tray()
            return
        if isinstance(data, str) and data != self.current_profile:
            self.set_current_profile(data)

    def show_profile_create_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._show_profile_create_inline()

    def _show_profile_create_inline(self) -> None:
        self.profile_button.setEnabled(False)
        self.profile_create_edit.clear()
        self.profile_create_container.setVisible(True)
        self.profile_create_edit.setFocus()

    def _hide_profile_create_inline(self) -> None:
        self.profile_create_container.setVisible(False)
        self.profile_button.setEnabled(True)

    def _on_profile_create_confirmed(self) -> None:
        name = self.profile_create_edit.text()
        if self.create_profile(name):
            self._hide_profile_create_inline()
        else:
            self.profile_create_edit.setFocus()
            
    def _save_current_profile(self) -> None:
        self.profiles[self.current_profile] = dict(self.hotkeys)
        passphrase = self.profile_passphrase if self.profiles_encrypted else None
        storage.save_profiles(self.current_profile, self.profiles, passphrase=passphrase)
        
    def _normalize_profile_colors(self, colors: object) -> Dict[str, str]:
        if not isinstance(colors, dict):
            return {}
        normalized: Dict[str, str] = {}
        for name, value in colors.items():
            if isinstance(name, str) and isinstance(value, str) and value.strip():
                normalized[name] = value.strip()
        return normalized

    def _apply_profile_button_color(self) -> None:
        color_hex = self.profile_color(self.current_profile)
        if not color_hex:
            self.profile_button.setStyleSheet("")
            return
        color = QtGui.QColor(color_hex)
        text_color = readable_text_color(color)
        hover_color = color.lighter(115)
        pressed_color = color.darker(115)
        self.profile_button.setStyleSheet(
            (
                "QPushButton {"
                f"background-color: {color.name()};"
                f"color: {text_color.name()};"
                f"border: 1px solid {pressed_color.name()};"
                "border-radius: 4px;"
                "padding: 4px 8px;"
                "}"
                "QPushButton:hover {"
                f"background-color: {hover_color.name()};"
                f"color: {text_color.name()};"
                "}"
                "QPushButton:pressed {"
                f"background-color: {pressed_color.name()};"
                f"color: {text_color.name()};"
                "}"
            )
        )

    def _normalize_profile_name(self, name: str) -> str:
        return name.strip()

    def create_profile(self, name: str) -> bool:      
        name = self._normalize_profile_name(name)
        if not name:
            QtWidgets.QMessageBox.warning(self, "Create Profile", "Profile name cannot be empty.")
            return False
        if name in self.profiles:
            QtWidgets.QMessageBox.warning(self, "Create Profile", "That profile already exists.")
            return False
        self.profiles[name] = {}
        self.current_profile = name
        self.hotkeys = {}
        self.engine.update_hotkeys(self.hotkeys)
        self.profile_colors.pop(name, None)
        self._save_current_profile()
        self.populate_model()
        self.refresh_status_ui()
        self._sync_profile_ui()
        return True
    
    def prompt_create_profile(self) -> bool:
        name, ok = QtWidgets.QInputDialog.getText(self, "Create Profile", "Profile name:")
        if not ok:
            return False
        return self.create_profile(name)

    def prompt_rename_profile(self, current_name: str) -> bool:
        new_name, ok = QtWidgets.QInputDialog.getText(
            self,
            "Rename Profile",
            "New profile name:",
            text=current_name,
        )
        if not ok:
            return False
        new_name = self._normalize_profile_name(new_name)
        if not new_name:
            QtWidgets.QMessageBox.warning(self, "Rename Profile", "Profile name cannot be empty.")
            return False
        if new_name in self.profiles and new_name != current_name:
            QtWidgets.QMessageBox.warning(self, "Rename Profile", "That profile already exists.")
            return False
        if new_name == current_name:
            return False
        self.profiles[new_name] = self.profiles.pop(current_name)
        if self.current_profile == current_name:
            self.current_profile = new_name
        if current_name in self.profile_colors:
            self.profile_colors[new_name] = self.profile_colors.pop(current_name)
            self.config["profile_colors"] = dict(self.profile_colors)
            storage.save_config(self.config)
        self._save_current_profile()
        self._sync_profile_ui()
        return True

    def delete_profile(self, profile_name: str) -> bool:
        if profile_name not in self.profiles:
            return False
        if len(self.profiles) <= 1:
            QtWidgets.QMessageBox.warning(self, "Delete Profile", "You must keep at least one profile.")
            return False
        response = QtWidgets.QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile '{profile_name}'? This cannot be undone.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return False
        self.profiles.pop(profile_name, None)
        self.profile_colors.pop(profile_name, None)
        if self.current_profile == profile_name:
            self.current_profile = next(iter(self.profiles))
            self.hotkeys = dict(self.profiles[self.current_profile])
            self.engine.update_hotkeys(self.hotkeys)
            self.populate_model()
            self.refresh_status_ui()
        self.config["profile_colors"] = dict(self.profile_colors)
        storage.save_config(self.config)
        self._save_current_profile()
        self._sync_profile_ui()
        return True

    def set_current_profile(self, profile_name: str, *, announce: bool = False) -> bool:
        if profile_name not in self.profiles:
            return False
        if profile_name == self.current_profile:
            return True
        self._save_current_profile()
        self.current_profile = profile_name
        self.hotkeys = dict(self.profiles.get(profile_name, {}))
        self.engine.update_hotkeys(self.hotkeys)
        self.populate_model()
        self.refresh_status_ui()
        self._sync_profile_ui()
        if announce:
            self._show_profile_switch_toast(profile_name)
        return True