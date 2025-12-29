"""Qt application window for OpenKeyFlow."""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict

import logging

from PyQt5 import QtCore, QtGui, QtWidgets

from backend import autostart
from backend import storage
from backend.logging_utils import configure_logging, get_logger
from backend.trigger_engine import TriggerEngine

APP_NAME = "OpenKeyFlow"
ASSETS_DIR = Path(__file__).resolve().parents[1] / "assets"
SETTINGS_ICON_PATH = ASSETS_DIR / "settings_icon.ico"

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

def make_status_icon(enabled: bool) -> QtGui.QIcon:
    icon_size = 64
    pixmap = QtGui.QPixmap(icon_size, icon_size)
    pixmap.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    color = QtGui.QColor("#2ecc71" if enabled else "#e74c3c")
    painter.setBrush(color)
    painter.setPen(QtCore.Qt.NoPen)
    margin = 8
    diameter = icon_size - (margin * 2)
    painter.drawEllipse(margin, margin, diameter, diameter)
    painter.end()
    return QtGui.QIcon(pixmap)

def load_settings_icon() -> QtGui.QIcon:
    if SETTINGS_ICON_PATH.exists():
        return QtGui.QIcon(str(SETTINGS_ICON_PATH))
    settings_icon = QtGui.QIcon.fromTheme("settings")
    if not settings_icon.isNull():
        return settings_icon
    return QtGui.QIcon()

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

    palette = QtGui.QPalette()
    if dark:
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
            QHeaderView::section {
                background-color: #1f1f24;
                color: #ff7b7b;
                border: 1px solid #ff8080;
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

class SettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent: "MainWindow") -> None:  # type: ignore[name-defined]
        super().__init__(parent)
        self.window = parent
        self.setWindowTitle("Settings")
        self.setWindowIcon(make_status_icon(self.window.enabled))
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)

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
        layout.addWidget(general_group)

        data_group = QtWidgets.QGroupBox("Data & Import/Export")
        data_layout = QtWidgets.QHBoxLayout(data_group)
        import_btn = QtWidgets.QPushButton("Import CSV")
        export_btn = QtWidgets.QPushButton("Export CSV")
        import_btn.clicked.connect(self.window.import_csv)
        export_btn.clicked.connect(self.window.export_csv)
        data_layout.addWidget(import_btn)
        data_layout.addWidget(export_btn)
        layout.addWidget(data_group)

        logging_group = QtWidgets.QGroupBox("Diagnostics")
        logging_layout = QtWidgets.QGridLayout(logging_group)
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
        layout.addWidget(logging_group)

        links_group = QtWidgets.QGroupBox("Links")
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
        links_layout.addWidget(donate_btn)
        links_layout.addWidget(github_btn)
        links_layout.addWidget(help_btn)
        layout.addWidget(links_group)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        close_button = buttons.button(QtWidgets.QDialogButtonBox.Close)
        if close_button:
            close_button.setText("Close")
        layout.addWidget(buttons)

        self._update_logging_controls()

    def _update_logging_controls(self) -> None:
        enabled = self.logging_checkbox.isChecked()
        self.log_path_edit.setEnabled(enabled)
        self.browse_btn.setEnabled(enabled)

    def _on_autostart_toggled(self, checked: bool) -> None:
        success = self.window.update_autostart(checked)
        if not success:
            self.autostart_checkbox.blockSignals(True)
            self.autostart_checkbox.setChecked(not checked)
            self.autostart_checkbox.blockSignals(False)

    def _on_dark_mode_toggled(self, checked: bool) -> None:
        self.window.set_dark_mode(checked)

    def _on_logging_toggled(self, checked: bool) -> None:
        self.window.set_logging_enabled(checked, Path(self.log_path_edit.text()))
        self._update_logging_controls()

    def _on_choose_log_path(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Select log file", self.log_path_edit.text(), "Log files (*.log)")
        if not path:
            return
        self.log_path_edit.setText(path)
        self.window.set_logging_path(Path(path))
        self._update_logging_controls()


class MainWindow(QtWidgets.QMainWindow):
    updateCounters = QtCore.pyqtSignal()

    def __init__(self, engine: TriggerEngine, logger: Logger | None = None) -> None:
        super().__init__()
        self.engine = engine
        self.hotkeys: Dict[str, str] = storage.load_hotkeys()
        self.config = storage.load_config()
        self.dark_mode = bool(self.config.get("dark_mode", False))
        self.enabled = True
        self.hotkey_lock = threading.RLock()
        self.logger: Logger = logger or get_logger()

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
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(True)
        layout.addWidget(self.table, 1)

        self._apply_table_header_theme()

        bottom_row = QtWidgets.QHBoxLayout()
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

        self.settings_btn = QtWidgets.QToolButton()
        settings_icon = load_settings_icon()
        if settings_icon.isNull():
            settings_icon = make_gear_icon(self.palette())
        self.settings_btn.setIcon(settings_icon)
        self.settings_btn.setToolTip("Open settings")
        self.settings_btn.setAutoRaise(True)
        self.settings_btn.clicked.connect(self.open_settings)
        bottom_row.addWidget(self.settings_btn)

        layout.addLayout(bottom_row)

        self.search_edit.textChanged.connect(self.proxy.setQuery)
        self.tray: QtWidgets.QSystemTrayIcon | None = None
        self.refresh_status_ui()

        self.counter_timer = QtCore.QTimer(self)
        self.counter_timer.setInterval(300)
        self.counter_timer.timeout.connect(self.refresh_counters_only)
        self.counter_timer.start()
        self.tray = QtWidgets.QSystemTrayIcon(self)
        self.tray.setIcon(make_status_icon(self.enabled))
        tray_menu = QtWidgets.QMenu()
        tray_menu.addAction("Toggle Enabled", self.toggle_enabled)
        tray_menu.addAction("Settings", self.open_settings)
        tray_menu.addSeparator()
        tray_menu.addAction("Show/Hide", self.toggle_window_visibility)
        tray_menu.addAction("Quit", self.quit_app)
        self.tray.setContextMenu(tray_menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

        if self.engine.hooks_available():
            self.engine.add_hotkey("ctrl+f12", self.toggle_enabled)     

        self._was_hidden_to_tray = False
        self.settings_dialog: SettingsDialog | None = None
        self._tray_message_shown = False

        set_app_palette(self.dark_mode)
        self._apply_table_header_theme()
        QtCore.QTimer.singleShot(200, self._maybe_show_use_policy_prompt)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def populate_model(self) -> None:
        self.model.setRowCount(0)
        for trigger, output in self.hotkeys.items():
            items = [QtGui.QStandardItem(trigger), QtGui.QStandardItem(output)]
            self.model.appendRow(items)

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
        if self.tray is not None:
            self.tray.setIcon(status_icon)

    def _apply_table_header_theme(self) -> None:
        header = self.table.horizontalHeader()
        if self.dark_mode:
            header.setStyleSheet(
                "QHeaderView::section { background-color: #1f1f24; color: #ff7b7b; border: 1px solid #ff8080; }"
            )
        else:
            header.setStyleSheet("")

    def set_dark_mode(self, enabled: bool) -> None:
        self.dark_mode = enabled
        set_app_palette(self.dark_mode)
        self._apply_table_header_theme()
        settings_icon = QtGui.QIcon.fromTheme("settings")
        if settings_icon.isNull():
            settings_icon = make_gear_icon(self.palette())
        self.settings_btn.setIcon(settings_icon)
        self.config["dark_mode"] = self.dark_mode
        storage.save_config(self.config)

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

    def update_autostart(self, enabled: bool) -> bool:
        return set_autostart_enabled(self, enabled)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        dialog.exec_()

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
            self.engine.remove_hotkey("ctrl+f12")
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

        storage.save_hotkeys(self.hotkeys)
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
        with self.hotkey_lock:
            for trigger in to_delete:
                self.hotkeys.pop(trigger, None)
        storage.save_hotkeys(self.hotkeys)
        self.engine.update_hotkeys(self.hotkeys)
        self.populate_model()
        self.refresh_status_ui()

    def import_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        added = 0
        with self.hotkey_lock:
            for trigger, output in storage.import_hotkeys_from_csv(Path(path)):
                self.hotkeys[trigger] = output
                added += 1
        storage.save_hotkeys(self.hotkeys)
        self.engine.update_hotkeys(self.hotkeys)
        self.populate_model()
        self.refresh_status_ui()
        QtWidgets.QMessageBox.information(self, "Import", f"Imported {added} hotkeys.")

    def export_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        storage.export_hotkeys_to_csv(Path(path), self.hotkeys)
        QtWidgets.QMessageBox.information(self, "Export", f"Exported {len(self.hotkeys)} hotkeys.")

    def toggle_enabled(self) -> None:
        self.enabled = self.engine.toggle_enabled()
        self.refresh_status_ui()

    def toggle_theme(self) -> None:
        
        self.set_dark_mode(not self.dark_mode)