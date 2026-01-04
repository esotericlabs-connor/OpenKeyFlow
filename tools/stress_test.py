#!/usr/bin/env python3
"""Comprehensive stress test runner for OpenKeyFlow."""
from __future__ import annotations

import argparse
import contextlib
import os
import random
import string
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Tuple

from backend import autostart, hooks, logging_utils, storage
import backend.trigger_engine as trigger_engine
from backend.trigger_engine import TriggerEngine


class FakePyperclip:
    """In-memory clipboard shim for deterministic testing."""

    def __init__(self) -> None:
        self._value = ""

    def copy(self, text: str) -> None:
        self._value = text

    def paste(self) -> str:
        return self._value


class FakeBackend(hooks.BaseHookBackend):
    """Minimal hook backend that records sent keys and text."""

    def __init__(self) -> None:
        self.sent: List[str] = []
        self.written: List[str] = []
        self.hotkeys: Dict[str, Callable[[], None]] = {}
        self.handler: Callable[[hooks.HookEvent], None] | None = None

    def start(self, handler: Callable[[hooks.HookEvent], None]) -> None:
        self.handler = handler

    def wait(self) -> None:
        return

    def send(self, hotkey: str) -> None:
        self.sent.append(hotkey)

    def write(self, text: str, *, interval: float = 0.0) -> None:
        self.written.append(text)

    def is_toggled(self, key: str) -> bool:
        return False

    def add_hotkey(self, hotkey: str, callback: Callable[[], None]) -> None:
        self.hotkeys[hotkey] = callback

    def remove_hotkey(self, hotkey: str) -> None:
        self.hotkeys.pop(hotkey, None)


@dataclass
class StressStats:
    profile_switches: int = 0
    profiles_created: int = 0
    profiles_deleted: int = 0
    hotkeys_created: int = 0
    hotkeys_deleted: int = 0
    trigger_fires: int = 0
    fire_events: int = 0
    config_updates: int = 0
    csv_exports: int = 0
    csv_imports: int = 0
    encryption_cycles: int = 0
    autostart_cycles: int = 0
    hotkey_updates: int = 0


def random_string(rng: random.Random, length: int) -> str:
    alphabet = string.ascii_lowercase + string.digits
    return "".join(rng.choice(alphabet) for _ in range(length))


def build_triggers(rng: random.Random, count: int) -> Dict[str, str]:
    triggers: Dict[str, str] = {}
    for idx in range(count):
        trigger = f"-t{idx}_{random_string(rng, 6)}"
        output = f"Output for {trigger} :: {random_string(rng, 12)}"
        triggers[trigger] = output
    return triggers


def configure_storage(base_dir: Path) -> None:
    storage.BASE_DATA_DIR = base_dir
    storage.DATA_DIR = base_dir
    storage.CONFIG_DIR = base_dir / "config"
    storage.HOTKEYS_FILE = storage.DATA_DIR / "hotkeys.json"
    storage.PROFILES_FILE = storage.DATA_DIR / "profiles.json"
    storage.CONFIG_FILE = storage.CONFIG_DIR / "config.json"
    storage.CSV_TEMPLATE = storage.DATA_DIR / "export_sample.csv"
    storage.DEFAULT_LOG_FILE = storage.DATA_DIR / "openkeyflow.log"
    storage.DEFAULT_CONFIG = {
        **storage.DEFAULT_CONFIG,
        "log_file": str(storage.DEFAULT_LOG_FILE),
    }


@contextlib.contextmanager
def temporary_home_dir(base_dir: Path) -> Iterable[None]:
    original_home = os.environ.get("HOME", "")
    original_appdata = os.environ.get("APPDATA", "")
    os.environ["HOME"] = str(base_dir)
    os.environ["APPDATA"] = str(base_dir / "appdata")
    try:
        yield
    finally:
        if original_home:
            os.environ["HOME"] = original_home
        else:
            os.environ.pop("HOME", None)
        if original_appdata:
            os.environ["APPDATA"] = original_appdata
        else:
            os.environ.pop("APPDATA", None)


def exercise_storage(
    rng: random.Random,
    profiles: Dict[str, Dict[str, str]],
    stats: StressStats,
    passphrase: str,
) -> None:
    current_profile = rng.choice(list(profiles.keys()))
    storage.save_profiles(current_profile, profiles)
    loaded_profile, loaded_profiles = storage.load_profiles()
    if loaded_profile != current_profile:
        raise RuntimeError("Profile load/save mismatch")
    stats.profile_switches += 1

    storage.save_profiles(current_profile, profiles, passphrase=passphrase)
    loaded_profile, loaded_profiles = storage.load_profiles(passphrase=passphrase)
    if loaded_profile != current_profile:
        raise RuntimeError("Encrypted profile load/save mismatch")
    stats.encryption_cycles += 1

    config = storage.load_config()
    config["cooldown"] = rng.uniform(0.0, 0.5)
    config["paste_delay"] = rng.uniform(0.0, 0.1)
    config["logging_enabled"] = True
    storage.save_config(config)
    stats.config_updates += 1


def exercise_csv(tmp_dir: Path, hotkeys: Dict[str, str], stats: StressStats) -> None:
    export_path = tmp_dir / "export.csv"
    storage.export_hotkeys_to_csv(export_path, hotkeys)
    stats.csv_exports += 1

    imported = dict(storage.import_hotkeys_from_csv(export_path))
    if not imported:
        raise RuntimeError("CSV import returned no rows")
    stats.csv_imports += 1


def exercise_autostart(tmp_dir: Path, stats: StressStats) -> None:
    with temporary_home_dir(tmp_dir):
        enabled, _ = autostart.enable()
        if not enabled:
            return
        stats.autostart_cycles += 1
        disabled, _ = autostart.disable()
        if not disabled:
            raise RuntimeError("Autostart disable failed")


def make_engine(hotkeys: Dict[str, str]) -> Tuple[TriggerEngine, FakeBackend]:
    fake_backend = FakeBackend()

    def fake_get_backend() -> FakeBackend:
        return fake_backend

    hooks.get_backend = fake_get_backend
    trigger_engine.pyperclip = FakePyperclip()
    engine = TriggerEngine(
        hotkeys=hotkeys,
        cooldown=0.0,
        paste_delay=0.0,
    )
    engine._backend = fake_backend
    return engine, fake_backend


def exercise_triggers(
    rng: random.Random,
    engine: TriggerEngine,
    triggers: List[str],
    stats: StressStats,
    iterations: int,
) -> None:
    for _ in range(iterations):
        trigger = rng.choice(triggers)
        for char in trigger:
            engine._handle_event(hooks.HookEvent("down", char))
        stats.fire_events += 1

        if rng.random() < 0.25:
            engine._handle_event(hooks.HookEvent("down", "backspace"))
        if rng.random() < 0.1:
            engine._handle_event(hooks.HookEvent("down", "space"))

    stats.trigger_fires = engine.get_stats()["fired"]


def build_profiles(rng: random.Random, count: int, triggers: Dict[str, str]) -> Dict[str, Dict[str, str]]:
    profiles: Dict[str, Dict[str, str]] = {}
    trigger_items = list(triggers.items())
    for idx in range(count):
        name = f"profile_{idx}_{random_string(rng, 4)}"
        sample = dict(rng.sample(trigger_items, k=min(10, len(trigger_items))))
        profiles[name] = sample
    if not profiles:
        profiles[storage.DEFAULT_PROFILE_NAME] = {}
    return profiles


def update_profiles(
    rng: random.Random,
    profiles: Dict[str, Dict[str, str]],
    triggers: Dict[str, str],
    stats: StressStats,
) -> None:
    action = rng.choice(["add", "remove", "update"])
    if action == "add":
        name = f"profile_{random_string(rng, 6)}"
        profiles[name] = dict(rng.sample(list(triggers.items()), k=min(8, len(triggers))))
        stats.profiles_created += 1
        return
    if action == "remove" and len(profiles) > 1:
        name = rng.choice([key for key in profiles if key != storage.DEFAULT_PROFILE_NAME])
        profiles.pop(name, None)
        stats.profiles_deleted += 1
        return
    name = rng.choice(list(profiles.keys()))
    profiles[name].update(dict(rng.sample(list(triggers.items()), k=min(5, len(triggers)))))
    stats.hotkey_updates += 1


def update_hotkeys(rng: random.Random, hotkeys: Dict[str, str], stats: StressStats) -> None:
    if not hotkeys or rng.random() < 0.6:
        trigger = f"-dyn_{random_string(rng, 5)}"
        hotkeys[trigger] = f"Dynamic {random_string(rng, 8)}"
        stats.hotkeys_created += 1
    elif hotkeys:
        trigger = rng.choice(list(hotkeys.keys()))
        hotkeys.pop(trigger, None)
        stats.hotkeys_deleted += 1


def run_stress_test(args: argparse.Namespace) -> StressStats:
    rng = random.Random(args.seed)
    base_dir = Path(args.data_dir) if args.data_dir else Path(tempfile.mkdtemp(prefix="okf-stress-"))
    configure_storage(base_dir)
    storage.ensure_data_dir()

    stats = StressStats()

    config = storage.load_config()
    log_path = Path(config.get("log_file", storage.DEFAULT_LOG_FILE))
    logging_utils.configure_logging(True, log_path)

    triggers = build_triggers(rng, args.triggers)
    profiles = build_profiles(rng, args.profiles, triggers)
    current_profile = rng.choice(list(profiles.keys()))
    storage.save_profiles(current_profile, profiles)

    engine, _ = make_engine(triggers)

    for _ in range(args.iterations):
        update_profiles(rng, profiles, triggers, stats)
        update_hotkeys(rng, triggers, stats)
        engine.update_hotkeys(triggers)

        exercise_storage(rng, profiles, stats, args.passphrase)
        exercise_csv(base_dir, triggers, stats)
        exercise_autostart(base_dir, stats)
        if triggers:
            exercise_triggers(rng, engine, list(triggers.keys()), stats, args.trigger_iterations)

    logging_utils.configure_logging(False, log_path)
    return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="OpenKeyFlow stress test harness")
    parser.add_argument("--iterations", type=int, default=25, help="Number of stress cycles")
    parser.add_argument("--trigger-iterations", type=int, default=200, help="Events per cycle")
    parser.add_argument("--profiles", type=int, default=8, help="Number of starting profiles")
    parser.add_argument("--triggers", type=int, default=120, help="Number of starting triggers")
    parser.add_argument("--seed", type=int, default=1337, help="Random seed")
    parser.add_argument("--passphrase", type=str, default="openkeyflow", help="Encryption passphrase")
    parser.add_argument("--data-dir", type=str, default="", help="Override data directory")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    start = time.perf_counter()
    stats = run_stress_test(args)
    elapsed = time.perf_counter() - start

    print("OpenKeyFlow Stress Test Complete")
    print(f"Duration: {elapsed:.2f}s")
    print(f"Profiles created: {stats.profiles_created}")
    print(f"Profiles deleted: {stats.profiles_deleted}")
    print(f"Profile switches: {stats.profile_switches}")
    print(f"Hotkeys created: {stats.hotkeys_created}")
    print(f"Hotkeys deleted: {stats.hotkeys_deleted}")
    print(f"Hotkey updates: {stats.hotkey_updates}")
    print(f"Trigger fires: {stats.trigger_fires}")
    print(f"Trigger sequences: {stats.fire_events}")
    print(f"Config updates: {stats.config_updates}")
    print(f"CSV exports: {stats.csv_exports}")
    print(f"CSV imports: {stats.csv_imports}")
    print(f"Encryption cycles: {stats.encryption_cycles}")
    print(f"Autostart cycles: {stats.autostart_cycles}")


if __name__ == "__main__":
    main()