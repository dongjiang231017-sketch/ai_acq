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


_SENSITIVE_ENV_KEYS = {"ASTERISK_AMI_PASSWORD"}


def telephony_config_source_report(names: list[str]) -> dict[str, dict[str, str]]:
    """【审计B9】返回每个电话参数的最终取值与来源，供启动日志排查配置漂移。

    来源优先级与 _first_env_value 保持一致：进程环境变量 > sidecar env 文件 > settings（.env/代码默认值）。
    敏感项只输出是否配置，不输出明文。
    """
    runtime_values = _runtime_env_values()
    runtime_path = runtime_values.get("__path__", "")
    report: dict[str, dict[str, str]] = {}
    for name in names:
        value = os.getenv(name)
        if value not in (None, ""):
            source = "process_env"
        else:
            value = runtime_values.get(name)
            if value not in (None, ""):
                source = f"sidecar_env:{runtime_path}"
            else:
                value = ""
                source = "settings(.env或代码默认值)"
        if name in _SENSITIVE_ENV_KEYS:
            display = "<configured>" if value else ""
        else:
            display = value or ""
        report[name] = {"value": display, "source": source}
    return report


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

    # 【审计B9】服务器托管模式下跳过 sidecar env 文件自动发现：
    # 残留的桌面客户端 backend-asterisk.env 会静默覆盖服务器 .env，造成"改了不生效"。
    # 显式指定的 *_ASTERISK_ENV_PATH 仍然生效。
    if os.getenv("ASTERISK_DEPLOYMENT_MODE", "").strip().lower() == "server":
        return _dedupe_paths(candidates)

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
