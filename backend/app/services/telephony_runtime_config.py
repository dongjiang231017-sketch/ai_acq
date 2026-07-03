from __future__ import annotations

import os
from pathlib import Path


def telephony_str(*names: str, fallback: str = "") -> str:
    value = _first_env_value(names)
    if value is not None:
        return value
    return fallback


def telephony_int(*names: str, fallback: int = 0) -> int:
    value = _first_env_value(names)
    if value is None:
        return fallback
    try:
        return int(value)
    except ValueError:
        return fallback


def telephony_bool(*names: str, fallback: bool = False) -> bool:
    value = _first_env_value(names)
    if value is None:
        return fallback
    return value.strip().lower() in {"1", "true", "yes", "on"}


def telephony_runtime_env_path() -> str:
    values = _runtime_env_values()
    return values.get("__path__", "")


def _first_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value is not None and value != "":
            return value
    runtime_values = _runtime_env_values()
    for name in names:
        value = runtime_values.get(name)
        if value is not None and value != "":
            return value
    return None


def _runtime_env_values() -> dict[str, str]:
    for path in _runtime_env_candidates():
        if not path.is_file():
            continue
        values = _parse_env_file(path)
        values["__path__"] = str(path)
        return values
    return {}


def _runtime_env_candidates() -> list[Path]:
    candidates: list[Path] = []
    for name in ["AI_ACQ_BACKEND_ASTERISK_ENV_PATH", "BACKEND_ASTERISK_ENV_PATH"]:
        explicit = os.getenv(name)
        if explicit:
            candidates.append(Path(explicit).expanduser())

    desktop_user_data = os.getenv("AI_ACQ_DESKTOP_USER_DATA_DIR")
    if desktop_user_data:
        candidates.append(Path(desktop_user_data).expanduser() / "asterisk-sidecar" / "state" / "backend-asterisk.env")

    home = Path.home()
    support = home / "Library" / "Application Support"
    for app_dir in ["ai-acq-qian-frontend", "商家AI获客客户端", "AI ACQ", "Electron"]:
        candidates.append(support / app_dir / "asterisk-sidecar" / "state" / "backend-asterisk.env")
    candidates.append(home / ".ai-acq-client" / "asterisk-sidecar" / "state" / "backend-asterisk.env")
    return _dedupe_paths(candidates)


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    deduped: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip().strip('"').strip("'")
    return values
