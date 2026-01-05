"""Data storage helpers for OpenKeyFlow."""
from __future__ import annotations

import base64
import csv
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Dict, Iterable, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
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
CSV_HEADERS = ("Trigger", "Output")
CSV_SAMPLE_ROWS = (
    ("SAMPLE_HOTKEY", "SAMPLE_OUTPUT"),
    ("SAMPLE_HOTKEY_2", "SAMPLE_OUTPUT_2"),
)
DEFAULT_LOG_FILE = DATA_DIR / "openkeyflow.log"

DEFAULT_CONFIG = {
    "dark_mode": False,
    "cooldown": 0.3,
    "paste_delay": 0.05,
    "accepted_use_policy": False,
    "quick_add_hotkey": "ctrl+f10",
    "hotkey_modifier": "ctrl",
    "quick_add_key": "f10",
    "profile_switch_key": "f11",
    "toggle_hotkey_key": "f12",
    "logging_enabled": False,
    "log_file": str(DEFAULT_LOG_FILE),
    "profile_colors": {},
    "profiles_encrypted": False,
    "profile_recovery_code": None,
}

DEFAULT_PROFILE_NAME = "main"
ENCRYPTION_VERSION = 1
PBKDF2_ITERATIONS = 200_000
SALT_BYTES = 16
NONCE_BYTES = 12

class ProfilesEncryptionError(RuntimeError):
    """Raised when encrypted profile data cannot be decrypted."""

def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding=encoding,
        dir=path.parent,
        delete=False,
    ) as tmp:
        tmp.write(text)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, path)

def _atomic_write_json(
    path: Path,
    payload: Dict[str, object],
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as tmp:
        json.dump(payload, tmp, indent=indent, ensure_ascii=ensure_ascii)
        tmp.flush()
        os.fsync(tmp.fileno())
    os.replace(tmp.name, path)

def _default_profiles() -> Dict[str, object]:
    return {
        "current_profile": DEFAULT_PROFILE_NAME,
        "profiles": {
            DEFAULT_PROFILE_NAME: {},
        },
    }

def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(passphrase.encode("utf-8"))

def _encode_bytes(value: bytes) -> str:
    return base64.b64encode(value).decode("utf-8")

def _decode_bytes(value: str) -> bytes:
    return base64.b64decode(value.encode("utf-8"))

def _encrypt_payload(payload: Dict[str, object], passphrase: str) -> Dict[str, str | int | bool]:
    salt = os.urandom(SALT_BYTES)
    nonce = os.urandom(NONCE_BYTES)
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    plaintext = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return {
        "encrypted": True,
        "version": ENCRYPTION_VERSION,
        "salt": _encode_bytes(salt),
        "nonce": _encode_bytes(nonce),
        "data": _encode_bytes(ciphertext),
    }

def _decrypt_payload(payload: Dict[str, object], passphrase: str) -> Dict[str, object]:
    if payload.get("version") != ENCRYPTION_VERSION:
        raise ProfilesEncryptionError("Unsupported encrypted profiles version.")
    try:
        salt = _decode_bytes(str(payload["salt"]))
        nonce = _decode_bytes(str(payload["nonce"]))
        data = _decode_bytes(str(payload["data"]))
    except KeyError as exc:
        raise ProfilesEncryptionError("Encrypted profiles are missing required fields.") from exc
    except (ValueError, TypeError) as exc:
        raise ProfilesEncryptionError("Encrypted profiles contain invalid data.") from exc
    key = _derive_key(passphrase, salt)
    aesgcm = AESGCM(key)
    try:
        plaintext = aesgcm.decrypt(nonce, data, None)
    except InvalidTag as exc:
        raise ProfilesEncryptionError("Invalid passphrase or corrupted profiles data.") from exc
    try:
        return json.loads(plaintext.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfilesEncryptionError("Decrypted profiles are invalid JSON.") from exc

def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_data()
    if not HOTKEYS_FILE.exists():
        _atomic_write_text(HOTKEYS_FILE, "{}", encoding="utf-8")
    if not PROFILES_FILE.exists():
        profiles = _default_profiles()
        try:
            hotkeys = _load_hotkeys_file()
        except Exception:
            hotkeys = {}
        if hotkeys:
            profiles["profiles"][DEFAULT_PROFILE_NAME] = hotkeys
        _atomic_write_json(PROFILES_FILE, profiles)
    if not CONFIG_FILE.exists():
        _atomic_write_json(CONFIG_FILE, DEFAULT_CONFIG, ensure_ascii=True)
    if not CSV_TEMPLATE.exists():
        export_sample_csv(CSV_TEMPLATE)

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

def load_hotkeys(*, passphrase: str | None = None) -> Dict[str, str]:
    current_profile, profiles = load_profiles(passphrase=passphrase)
    return dict(profiles.get(current_profile, {}))

def save_hotkeys(hotkeys: Dict[str, str], *, passphrase: str | None = None) -> None:
    current_profile, profiles = load_profiles(passphrase=passphrase)
    profiles[current_profile] = dict(hotkeys)
    save_profiles(current_profile, profiles, passphrase=passphrase)

def _load_hotkeys_file() -> Dict[str, str]:
    with HOTKEYS_FILE.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    if not data:
        _atomic_write_text(HOTKEYS_FILE, "{}", encoding="utf-8")
    return {str(k): str(v) for k, v in data.items()}

def profiles_are_encrypted() -> bool:
    if not PROFILES_FILE.exists():
        return False
    try:
        raw = json.loads(PROFILES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(isinstance(raw, dict) and raw.get("encrypted") is True)

def load_profiles(*, passphrase: str | None = None) -> Tuple[str, Dict[str, Dict[str, str]]]:
    ensure_data_dir()
    if not PROFILES_FILE.exists():
        default_profiles = _default_profiles()
        _atomic_write_json(PROFILES_FILE, default_profiles)
    with PROFILES_FILE.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            data = {}
    encrypted = bool(isinstance(data, dict) and data.get("encrypted") is True)
    if encrypted:
        if not passphrase:
            raise ProfilesEncryptionError("Profiles are encrypted and require a passphrase.")
        data = _decrypt_payload(data, passphrase)
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
    save_profiles(current_profile, profiles, passphrase=passphrase if encrypted else None)
    return current_profile, profiles

def save_profiles(
    current_profile: str,
    profiles: Dict[str, Dict[str, str]],
    *,
    passphrase: str | None = None,
) -> None:
    ensure_data_dir()
    payload = {
        "current_profile": current_profile,
        "profiles": profiles,
    }
    if passphrase:
        payload_to_write: Dict[str, object] = _encrypt_payload(payload, passphrase)
    else:
        payload_to_write = payload
    _atomic_write_json(PROFILES_FILE, payload_to_write, ensure_ascii=False)        

def load_config() -> Dict[str, object]:
    ensure_data_dir()
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("r", encoding="utf-8") as f:
            data = json.load(f)
        merged = DEFAULT_CONFIG.copy()
        merged.update({k: data.get(k, v) for k, v in DEFAULT_CONFIG.items()})
        merged.setdefault("log_file", str(DEFAULT_LOG_FILE))
        return merged
    return DEFAULT_CONFIG.copy()

def save_config(config: Dict[str, object]) -> None:
    ensure_data_dir()
    merged = DEFAULT_CONFIG.copy()
    merged.update(config)
    _atomic_write_json(CONFIG_FILE, merged, ensure_ascii=True)
    
def export_hotkeys_to_csv(path: Path, hotkeys: Dict[str, str]) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(list(CSV_HEADERS))
        for trigger, output in hotkeys.items():
            writer.writerow([trigger, output])

def export_sample_csv(path: Path) -> None:
    path = Path(path)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, quoting=csv.QUOTE_ALL)
        writer.writerow(list(CSV_HEADERS))
        for trigger, output in CSV_SAMPLE_ROWS:
            writer.writerow([trigger, output])
        writer.writerow(["", ""])

def import_hotkeys_from_csv(path: Path) -> Iterable[Tuple[str, str]]:
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return []
    header = rows[0] if rows else []
    header_normalized = [value.strip().lower() for value in header]
    use_dict_reader = False
    if "trigger" in header_normalized and "output" in header_normalized:
        use_dict_reader = True
    elif "hotkey" in header_normalized and "output" in header_normalized:
        use_dict_reader = True
    if use_dict_reader:
        with path.open("r", encoding="utf-8") as f:
            dict_reader = csv.DictReader(f, skipinitialspace=True)
            for row in dict_reader:
                trigger = (row.get("Trigger") or row.get("trigger") or row.get("Hotkey") or "").strip()
                output = (row.get("Output") or row.get("output") or row.get("Text") or "").strip()
                if _is_sample_csv_row(trigger, output):
                    continue
                if trigger and output:
                    yield trigger, output
        return []
    for row in rows[1:]:
        if len(row) < 2:
            continue
        trigger = row[0].strip()
        output = row[1].strip()
        if _is_sample_csv_row(trigger, output):
            continue
        if trigger and output:
            yield trigger, output

def _is_sample_csv_row(trigger: str, output: str) -> bool:
    if not trigger or not output:
        return False
    trigger_upper = trigger.strip().upper()
    output_upper = output.strip().upper()
    if trigger_upper.startswith("SAMPLE_"):
        return True
    if output_upper.startswith("SAMPLE_"):
        return True
    return False


def default_log_path() -> Path:
    return DEFAULT_LOG_FILE