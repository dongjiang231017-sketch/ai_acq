import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from re import sub

from app.core.config import settings
from app.models.task import DirectMessageAccount


PLATFORM_SESSION_DOMAINS = {
    "美团": ("meituan.com",),
    "饿了么": ("ele.me", "eleme.cn", "eleme.io"),
    "抖音": ("douyin.com", "bytedance.com", "snssdk.com"),
}

SESSION_MARKERS = (
    "auth",
    "login",
    "passport",
    "session",
    "sid",
    "sso",
    "ticket",
    "token",
    "uid",
    "user",
)


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
    account.session_status = account.session_status or "未登录"
    account.risk_status = account.risk_status or "正常"
    account.min_send_interval_seconds = account.min_send_interval_seconds or 0


def _domain_matches(host: str, domains: tuple[str, ...]) -> bool:
    normalized_host = host.lower().lstrip(".")
    return any(normalized_host == domain or normalized_host.endswith(f".{domain}") for domain in domains)


def _looks_like_session_key(value: str) -> bool:
    normalized_value = value.lower()
    return any(marker in normalized_value for marker in SESSION_MARKERS)


def _cookie_db_has_login_marker(cookie_db_path: Path, domains: tuple[str, ...]) -> bool:
    if not cookie_db_path.exists() or cookie_db_path.stat().st_size <= 0:
        return False
    try:
        connection = sqlite3.connect(f"file:{cookie_db_path}?mode=ro", uri=True, timeout=1)
    except sqlite3.Error:
        return False

    try:
        cursor = connection.execute("select host_key, name, value, length(encrypted_value) from cookies")
        for host_key, name, value, encrypted_value_size in cursor.fetchall():
            if not _domain_matches(str(host_key), domains):
                continue
            if not _looks_like_session_key(str(name)):
                continue
            if value or encrypted_value_size:
                return True
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return False


def _storage_path_has_login_marker(storage_path: Path, domains: tuple[str, ...]) -> bool:
    if not storage_path.exists():
        return False
    domain_tokens = tuple(domain.encode("utf-8") for domain in domains)
    marker_tokens = tuple(marker.encode("utf-8") for marker in SESSION_MARKERS)
    candidates = [storage_path] if storage_path.is_file() else list(storage_path.rglob("*"))[:80]
    for candidate in candidates:
        if not candidate.is_file() or candidate.stat().st_size <= 0:
            continue
        try:
            data = candidate.read_bytes()[:262144].lower()
        except OSError:
            continue
        if any(domain in data for domain in domain_tokens) and any(marker in data for marker in marker_tokens):
            return True
    return False


def profile_has_session_artifacts(
    account: DirectMessageAccount,
    since: datetime | None = None,
    *,
    include_existing: bool = False,
) -> bool:
    """Best-effort local check for real login markers in the isolated browser profile."""
    profile_path = resolved_profile_path_for_account(account)
    if not profile_path.exists():
        return False

    cutoff = (since - timedelta(seconds=5)).timestamp() if since else None
    domains = PLATFORM_SESSION_DOMAINS.get(account.platform, ())
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
        if domains and artifact_path.name == "Cookies" and _cookie_db_has_login_marker(artifact_path, domains):
            return True
        if domains and artifact_path.name != "Cookies" and _storage_path_has_login_marker(artifact_path, domains):
            return True
        candidates = [artifact_path] if artifact_path.is_file() else list(artifact_path.rglob("*"))[:40]
        for candidate in candidates:
            if not candidate.is_file():
                continue
            stat = candidate.stat()
            if stat.st_size <= 0:
                continue
            if not domains and (cutoff is None or stat.st_mtime >= cutoff):
                return True
    return False
