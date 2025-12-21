"""Platform-aware keyboard hook backends."""
from __future__ import annotations

import os
import platform
import threading
from dataclasses import dataclass
from typing import Callable, Optional


class HookBackendUnavailable(RuntimeError):
    """Raised when a keyboard hook backend cannot be initialized."""


@dataclass(frozen=True)
class HookEvent:
    event_type: str
    name: str


class BaseHookBackend:
    def start(self, handler: Callable[[HookEvent], None]) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def wait(self) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def send(self, hotkey: str) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def write(self, text: str) -> None:  # pragma: no cover - interface only
        raise NotImplementedError

    def is_toggled(self, key: str) -> bool:  # pragma: no cover - interface only
        return False

    def add_hotkey(self, hotkey: str, callback: Callable[[], None]) -> None:  # pragma: no cover
        raise NotImplementedError

    def remove_hotkey(self, hotkey: str) -> None:  # pragma: no cover
        raise NotImplementedError


class KeyboardBackend(BaseHookBackend):
    def __init__(self) -> None:
        try:
            import keyboard  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency resolution
            raise HookBackendUnavailable("Missing dependency: keyboard") from exc
        self._keyboard = keyboard

    def start(self, handler: Callable[[HookEvent], None]) -> None:
        def _wrapped(event) -> None:
            handler(HookEvent(event.event_type, event.name or ""))

        self._keyboard.hook(_wrapped)

    def wait(self) -> None:
        self._keyboard.wait()

    def send(self, hotkey: str) -> None:
        self._keyboard.send(hotkey)

    def write(self, text: str) -> None:
        self._keyboard.write(text, delay=0)

    def is_toggled(self, key: str) -> bool:
        if hasattr(self._keyboard, "is_toggled"):
            return bool(self._keyboard.is_toggled(key))
        return False

    def add_hotkey(self, hotkey: str, callback: Callable[[], None]) -> None:
        self._keyboard.add_hotkey(hotkey, callback)

    def remove_hotkey(self, hotkey: str) -> None:
        self._keyboard.remove_hotkey(hotkey)


class PynputBackend(BaseHookBackend):
    def __init__(self) -> None:
        try:
            from pynput import keyboard as pynput_keyboard  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency resolution
            raise HookBackendUnavailable("Missing dependency: pynput") from exc
        self._keyboard = pynput_keyboard
        self._controller = pynput_keyboard.Controller()
        self._listener: Optional[pynput_keyboard.Listener] = None
        self._hotkeys: Optional[pynput_keyboard.GlobalHotKeys] = None
        self._listener_lock = threading.Lock()

    def start(self, handler: Callable[[HookEvent], None]) -> None:
        def on_press(key) -> None:
            name = self._key_to_name(key)
            if name:
                handler(HookEvent("down", name))

        def on_release(key) -> None:
            name = self._key_to_name(key)
            if name:
                handler(HookEvent("up", name))

        with self._listener_lock:
            if self._listener and self._listener.running:
                return
            self._listener = self._keyboard.Listener(on_press=on_press, on_release=on_release)
            self._listener.start()

    def wait(self) -> None:
        if self._listener:
            self._listener.join()

    def send(self, hotkey: str) -> None:
        keys = [part.strip().lower() for part in hotkey.split("+")]
        modifiers = [key for key in keys[:-1]]
        final = keys[-1]
        pressed = []
        try:
            for mod in modifiers:
                key_obj = self._to_key(mod)
                if key_obj is not None:
                    self._controller.press(key_obj)
                    pressed.append(key_obj)
            key_obj = self._to_key(final)
            if key_obj is not None:
                self._controller.press(key_obj)
                self._controller.release(key_obj)
        finally:
            for key_obj in reversed(pressed):
                self._controller.release(key_obj)

    def write(self, text: str) -> None:
        self._controller.type(text)

    def add_hotkey(self, hotkey: str, callback: Callable[[], None]) -> None:
        normalized = self._normalize_hotkey(hotkey)
        if self._hotkeys:
            self._hotkeys.stop()
        self._hotkeys = self._keyboard.GlobalHotKeys({normalized: callback})
        self._hotkeys.start()

    def remove_hotkey(self, hotkey: str) -> None:
        if self._hotkeys:
            self._hotkeys.stop()
            self._hotkeys = None

    @staticmethod
    def _normalize_hotkey(hotkey: str) -> str:
        parts = [part.strip().lower() for part in hotkey.split("+")]
        return "+".join(f"<{part}>" for part in parts)

    def _key_to_name(self, key) -> str | None:
        if isinstance(key, self._keyboard.KeyCode):
            if key.char:
                return key.char.lower()
            return None
        if key == self._keyboard.Key.space:
            return "space"
        if key == self._keyboard.Key.enter:
            return "enter"
        if key == self._keyboard.Key.tab:
            return "tab"
        if key == self._keyboard.Key.backspace:
            return "backspace"
        if key == self._keyboard.Key.shift:
            return "shift"
        if key == self._keyboard.Key.shift_l:
            return "left shift"
        if key == self._keyboard.Key.shift_r:
            return "right shift"
        if key == self._keyboard.Key.caps_lock:
            return "caps lock"
        return None

    def _to_key(self, name: str):
        mapping = {
            "backspace": self._keyboard.Key.backspace,
            "space": self._keyboard.Key.space,
            "enter": self._keyboard.Key.enter,
            "tab": self._keyboard.Key.tab,
            "shift": self._keyboard.Key.shift,
            "ctrl": self._keyboard.Key.ctrl,
            "alt": self._keyboard.Key.alt,
        }
        if name in mapping:
            return mapping[name]
        if len(name) == 1:
            return name
        if name.startswith("f") and name[1:].isdigit():
            return getattr(self._keyboard.Key, name)
        return None


def _default_backend_name() -> str:
    if platform.system() == "Windows":
        return "keyboard"
    return "pynput"


def selected_backend_name() -> str:
    override = os.getenv("OPENKEYFLOW_HOOK_BACKEND")
    if override:
        return override.strip().lower()
    return _default_backend_name()


def required_packages() -> list[str]:
    name = selected_backend_name()
    if name == "keyboard":
        return ["keyboard"]
    if name == "pynput":
        return ["pynput"]
    return []


def get_backend() -> BaseHookBackend:
    name = selected_backend_name()
    if name == "keyboard":
        return KeyboardBackend()
    if name == "pynput":
        return PynputBackend()
    raise HookBackendUnavailable(f"Unknown hook backend: {name}")