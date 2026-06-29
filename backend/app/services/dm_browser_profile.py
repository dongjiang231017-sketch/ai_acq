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


def attach_profile_defaults(account: DirectMessageAccount) -> None:
    account.browser_profile_key = profile_key_for_account(account)
    account.browser_profile_path = profile_path_for_account(account)


def normalize_account_state(account: DirectMessageAccount) -> None:
    attach_profile_defaults(account)
    account.session_status = account.session_status or ("模拟可用" if account.status == "可用" else "未登录")
    account.risk_status = account.risk_status or "正常"
    account.min_send_interval_seconds = account.min_send_interval_seconds or 0
