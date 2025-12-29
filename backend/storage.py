"""Data storage helpers for OpenKeyFlow."""
from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path
from typing import Dict, Iterable, Tuple

from platformdirs import user_config_dir, user_data_dir

APP_AUTHOR = "OpenKeyFlow"
APP_NAME = "OpenKeyFlow"

def _legacy_data_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "okf_data"

BASE_DATA_DIR = Path(user_data_dir(APP_NAME, APP_AUTHOR))
CONFIG_DIR = Path(user_config_dir(APP_NAME, APP_AUTHOR))
DATA_DIR = BASE_DATA_DIR
HOTKEYS_FILE = DATA_DIR / "hotkeys.json"
PROFILES_FILE = DATA_DIR / "profiles.json"
CONFIG_FILE = CONFIG_DIR / "config.json"
CSV_TEMPLATE = DATA_DIR / "export_sample.csv"
DEFAULT_LOG_FILE = DATA_DIR / "openkeyflow.log"

DEFAULT_CONFIG = {
    "dark_mode": False,
    "cooldown": 0.3,
    "paste_delay": 0.05,
    "accepted_use_policy": False,
    "logging_enabled": False,
    "log_file": str(DEFAULT_LOG_FILE),
}

DEFAULT_PROFILE_NAME = "main"

def _default_profiles() -> Dict[str, object]:
    return {
        "current_profile": DEFAULT_PROFILE_NAME,
        "profiles": {
            DEFAULT_PROFILE_NAME: {},
        },
    }

def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data()
    if not HOTKEYS_FILE.exists():
        HOTKEYS_FILE.write_text("{}", encoding="utf-8")
    if not PROFILES_FILE.exists():
        profiles = _default_profiles()
        try:
            hotkeys = _load_hotkeys_file()
        except Exception:
            hotkeys = {}
        if hotkeys:
            profiles["profiles"][DEFAULT_PROFILE_NAME] = hotkeys
        PROFILES_FILE.write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    if not CONFIG_FILE.exists():
        CONFIG_FILE.write_text(json.dumps(DEFAULT_CONFIG, indent=2), encoding="utf-8")
    if not CSV_TEMPLATE.exists():
        with CSV_TEMPLATE.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, quoting=csv.QUOTE_ALL)
            writer.writerow(["Trigger", "Output"])

def _migrate_legacy_data() -> None:
    legacy_dir = _legacy_data_dir()
    if not legacy_dir.exists():
        return
    legacy_hotkeys = legacy_dir / "hotkeys.json"
    legacy_config = legacy_dir / "config.json"
    migrated = False

    if legacy_hotkeys.exists() and not HOTKEYS_FILE.exists():
        HOTKEYS_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_hotkeys, HOTKEYS_FILE)
        migrated = True
    if legacy_config.exists() and not CONFIG_FILE.exists():
        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(legacy_config, CONFIG_FILE)
        migrated = True
    if migrated:
        for leftover in (legacy_hotkeys, legacy_config):
            try:
                leftover.unlink()
            except Exception:
                pass
        try:
            legacy_dir.rmdir()
        except Exception:
            pass

def load_hotkeys() -> Dict[str, str]:
    current_profile, profiles = load_profiles()
    return dict(profiles.get(current_profile, {}))

def save_hotkeys(hotkeys: Dict[str, str]) -> None:
    current_profile, profiles = load_profiles()
    profiles[current_profile] = dict(hotkeys)
    save_profiles(current_profile, profiles)

def _load_hotkeys_file() -> Dict[str, str]:
    with HOTKEYS_FILE.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    if not data:
        HOTKEYS_FILE.write_text("{}", encoding="utf-8")
    return {str(k): str(v) for k, v in data.items()}

def load_profiles() -> Tuple[str, Dict[str, Dict[str, str]]]:
    ensure_data_dir()
    if not PROFILES_FILE.exists():
        default_profiles = _default_profiles()
        PROFILES_FILE.write_text(json.dumps(default_profiles, indent=2), encoding="utf-8")
    with PROFILES_FILE.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    profiles_raw = data.get("profiles") if isinstance(data, dict) else {}
    if not isinstance(profiles_raw, dict):
        profiles_raw = {}
    profiles: Dict[str, Dict[str, str]] = {}
    for name, value in profiles_raw.items():
        if isinstance(name, str) and isinstance(value, dict):
            profiles[name] = {str(k): str(v) for k, v in value.items()}
    if DEFAULT_PROFILE_NAME not in profiles:
        profiles[DEFAULT_PROFILE_NAME] = {}
    current_profile = data.get("current_profile") if isinstance(data, dict) else None
    if not isinstance(current_profile, str) or current_profile not in profiles:
        current_profile = DEFAULT_PROFILE_NAME
    save_profiles(current_profile, profiles)
    return current_profile, profiles

def save_profiles(current_profile: str, profiles: Dict[str, Dict[str, str]]) -> None:
    ensure_data_dir()
    payload = {
        "current_profile": current_profile,
        "profiles": profiles,
    }
    with PROFILES_FILE.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

def save_hotkeys(hotkeys: Dict[str, str]) -> None:
    ensure_data_dir()
    with HOTKEYS_FILE.open("w", encoding="utf-8") as f:
        json.dump(hotkeys, f, indent=4, ensure_ascii=False)

def load_config() -> Dict[str, float]:
    ensure_data_dir()
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update({k: data.get(k, v) for k, v in DEFAULT_CONFIG.items()})
        merged.setdefault("log_file", str(DEFAULT_LOG_FILE))
        return merged
    return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, float]) -> None:
    ensure_data_dir()
    merged = DEFAULT_CONFIG.copy()
    merged.update(config)
    with CONFIG_FILE.open("w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2)

def export_hotkeys_to_csv(path: Path, hotkeys: Dict[str, str]) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(["Trigger", "Output"])
        for trigger, output in hotkeys.items():
            writer.writerow([trigger, output])


def import_hotkeys_from_csv(path: Path) -> Iterable[Tuple[str, str]]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f, skipinitialspace=True)
        for row in reader:
            trigger = (row.get("Trigger") or row.get("trigger") or row.get("Hotkey") or "").strip()
            output = (row.get("Output") or row.get("output") or row.get("Text") or "").strip()
            if trigger and output:
                yield trigger, output

def default_log_path() -> Path:
    return DEFAULT_LOG_FILE