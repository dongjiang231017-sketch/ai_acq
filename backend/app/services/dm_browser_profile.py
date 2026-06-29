from datetime import datetime, timedelta
from pathlib import Path
from re import sub

from app.core.config import settings
from app.models.task import DirectMessageAccount


def normalize_profile_key(value: str) -> str:
    cleaned = sub(r"[^a-zA-Z0-9_-]+", "-", value.strip()).strip("-").lower()
    return cleaned or "dm-account"


def profile_key_for_account(account: DirectMessageAccount) -> str:
    raw = account.browser_profile_key or f"{account.platform}-{account.account_name}-{account.id[:8]}"
    return normalize_profile_key(raw)


def profile_path_for_account(account: DirectMessageAccount) -> str:
    if account.browser_profile_path:
        return account.browser_profile_path
    return str(Path(settings.dm_browser_profile_root) / profile_key_for_account(account))


def resolved_profile_path_for_account(account: DirectMessageAccount) -> Path:
    profile_path = Path(profile_path_for_account(account)).expanduser()
    if profile_path.is_absolute():
        return profile_path
    return (Path.cwd() / profile_path).resolve()


def attach_profile_defaults(account: DirectMessageAccount) -> None:
    account.browser_profile_key = profile_key_for_account(account)
    account.browser_profile_path = profile_path_for_account(account)


def normalize_account_state(account: DirectMessageAccount) -> None:
    attach_profile_defaults(account)
    account.session_status = account.session_status or ("模拟可用" if account.status == "可用" else "未登录")
    account.risk_status = account.risk_status or "正常"
    account.min_send_interval_seconds = account.min_send_interval_seconds or 0


def profile_has_session_artifacts(account: DirectMessageAccount, since: datetime | None = None) -> bool:
    """Best-effort local check that a user interacted with the isolated browser profile."""
    profile_path = resolved_profile_path_for_account(account)
    if not profile_path.exists():
        return False

    cutoff = (since - timedelta(seconds=5)).timestamp() if since else None
    artifact_paths = [
        profile_path / "Default" / "Network" / "Cookies",
        profile_path / "Default" / "Cookies",
        profile_path / "Default" / "Local Storage" / "leveldb",
        profile_path / "Default" / "Session Storage",
        profile_path / "Default" / "IndexedDB",
    ]
    for artifact_path in artifact_paths:
        if not artifact_path.exists():
            continue
        candidates = [artifact_path] if artifact_path.is_file() else list(artifact_path.rglob("*"))[:40]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            stat = candidate.stat()
            if stat.st_size <= 0:
                continue
            if cutoff is None or stat.st_mtime >= cutoff:
                return True
    return False
