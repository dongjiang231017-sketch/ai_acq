from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.collection import PlatformBrowserSession

try:
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
except Exception:  # pragma: no cover - handled with a runtime error message
    Page = Any  # type: ignore[assignment]
    PlaywrightTimeoutError = Exception  # type: ignore[assignment]
    sync_playwright = None


class BrowserSessionError(ValueError):
    pass


BROWSER_PLATFORM_METADATA: dict[str, dict[str, str]] = {
    "meituan": {
        "name": "美团团购登录态",
        "login_url": "https://m.dianping.com/",
        "home_url": "https://m.dianping.com/",
        "engine": "dianping_shop_search",
        "note": "第一版通过大众点评手机版搜索入口采集团购商家，需先登录点评/美团账号。",
    },
    "shangou": {
        "name": "美团闪购登录态",
        "login_url": "https://i.meituan.com/mttouch/page/home",
        "home_url": "https://i.meituan.com/mttouch/page/home",
        "engine": "meituan_flash_sale",
        "note": "已接入本地浏览器登录态管理，后续在此基础上适配闪购页选择器。",
    },
}

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
ADDRESS_HINT_RE = re.compile(r"(路|街|道|广场|大厦|商场|中心|公寓|城|巷|里|号|店|楼|室)")
DISTRICT_HINT_RE = re.compile(r"(区|县|市)")


def browser_managed_providers() -> set[str]:
    return set(BROWSER_PLATFORM_METADATA)


def ensure_platform_browser_sessions(db: Session) -> list[PlatformBrowserSession]:
    sessions: list[PlatformBrowserSession] = []
    for provider, meta in BROWSER_PLATFORM_METADATA.items():
        session = db.scalar(select(PlatformBrowserSession).where(PlatformBrowserSession.provider == provider))
        if session is None:
            session = PlatformBrowserSession(
                provider=provider,
                name=meta["name"],
                login_url=meta["login_url"],
                home_url=meta["home_url"],
                profile_dir=str(_profile_dir(provider)),
                status="未初始化",
                note=meta["note"],
            )
            db.add(session)
            db.flush()
        else:
            session.name = meta["name"]
            session.login_url = meta["login_url"]
            session.home_url = meta["home_url"]
            session.profile_dir = str(_profile_dir(provider))
            if not session.note:
                session.note = meta["note"]
        sessions.append(session)
    return sessions


def open_platform_login_window(db: Session, provider: str) -> PlatformBrowserSession:
    session = _get_session(db, provider)
    _ensure_playwright_available()

    if session.login_process_id and _process_is_running(session.login_process_id):
        raise BrowserSessionError(f"{session.name} 的登录窗口已经打开，请直接去登录后关闭窗口。")

    _profile_dir(provider).mkdir(parents=True, exist_ok=True)
    process = subprocess.Popen(
        [sys.executable, "-m", "app.services.platform_browser_login", provider],
        cwd=str(_backend_dir()),
        start_new_session=True,
    )
    session.status = "登录中"
    session.login_process_id = process.pid
    session.last_login_started_at = datetime.utcnow()
    session.last_error = None
    db.commit()
    db.refresh(session)
    return session


def validate_platform_browser_session(db: Session, provider: str) -> PlatformBrowserSession:
    session = _get_session(db, provider)
    _ensure_playwright_available()

    profile_dir = _profile_dir(provider)
    if not _profile_ready(profile_dir):
        session.status = "未初始化"
        session.login_process_id = None
        session.last_validated_at = datetime.utcnow()
        session.last_error = "未发现可用的本地浏览器登录态，请先点击“打开登录窗口”。"
        db.commit()
        db.refresh(session)
        return session

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=True,
                user_agent=MOBILE_USER_AGENT,
                viewport={"width": 390, "height": 844},
                is_mobile=True,
                has_touch=True,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            page = context.new_page()
            page.goto(session.home_url, wait_until="networkidle", timeout=settings.browser_default_timeout_seconds * 1000)
            _ensure_page_authenticated(page, session.provider)
            session.status = "可用"
            session.last_error = None
            context.close()
    except BrowserSessionError as exc:
        session.status = "失效"
        session.last_error = str(exc)
    except Exception as exc:
        session.status = "失效"
        session.last_error = f"校验浏览器登录态失败：{exc}"

    session.login_process_id = None
    session.last_login_finished_at = session.last_login_finished_at or datetime.utcnow()
    session.last_validated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    return session


def clear_platform_browser_session(db: Session, provider: str) -> PlatformBrowserSession:
    session = _get_session(db, provider)
    profile_dir = _profile_dir(provider)
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    session.status = "未初始化"
    session.login_process_id = None
    session.last_error = None
    session.last_validated_at = None
    session.last_login_started_at = None
    session.last_login_finished_at = None
    db.commit()
    db.refresh(session)
    return session


def mark_platform_login_finished(provider: str, status: str, error_message: str | None = None) -> None:
    with _session_scope() as db:
        session = _get_session(db, provider)
        session.status = status
        session.login_process_id = None
        session.last_login_finished_at = datetime.utcnow()
        session.last_error = error_message
        db.commit()


def collect_browser_platform_pois(
    db: Session,
    provider: str,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    session = validate_platform_browser_session(db, provider)
    if session.status != "可用":
        raise BrowserSessionError(session.last_error or f"{session.name} 登录态不可用，请先在后台重新登录。")

    if provider == "meituan":
        return _collect_meituan_shop_pois(city, category, keyword, target_count)
    if provider == "shangou":
        raise BrowserSessionError("美团闪购已接入登录态管理，下一步需要在登录后校验页面结构再补抓取规则。")
    raise BrowserSessionError(f"暂不支持的数据源：{provider}")


def _collect_meituan_shop_pois(city: str, category: str, keyword: str, target_count: int) -> list[dict[str, Any]]:
    query = " ".join(_clean_items([city, category, keyword]))
    if not query:
        raise BrowserSessionError("美团团购采集关键词不能为空")

    search_url = f"https://m.dianping.com/shoplist/1/search?from=m_search&keyword={quote(query)}"
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(_profile_dir("meituan")),
            headless=True,
            user_agent=MOBILE_USER_AGENT,
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
        )
        page = context.new_page()
        page.goto(search_url, wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
        page.wait_for_timeout(3000)
        _ensure_page_authenticated(page, "meituan")
        _scroll_page(page, rounds=3)
        records = _extract_dianping_shop_cards(page, city, category, keyword, target_count)
        context.close()
    return records


def _extract_dianping_shop_cards(
    page: Page,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    anchors = page.locator("a[href*='/shop/']")
    seen_names: set[str] = set()
    records: list[dict[str, Any]] = []
    for index in range(min(anchors.count(), max(target_count * 8, 20))):
        anchor = anchors.nth(index)
        href = anchor.get_attribute("href")
        if not href:
            continue
        detail_url = urljoin("https://m.dianping.com", href)
        text = anchor.inner_text(timeout=1000).strip()
        lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
        name = _pick_shop_name(lines)
        if not name or name in seen_names:
            continue
        seen_names.add(name)

        address = _pick_address(lines, city)
        district = _pick_district(lines, city)
        records.append(
            {
                "id": _extract_shop_id(href, detail_url),
                "name": name,
                "cityname": city,
                "adname": district,
                "pname": None,
                "address": address,
                "tel": None,
                "location": None,
                "type": category or keyword or "美团团购",
                "detail_url": detail_url,
                "_raw_provider": "meituan",
                "_raw_payload": {
                    "provider": "meituan",
                    "query_city": city,
                    "query_category": category,
                    "query_keyword": keyword,
                    "source_url": detail_url,
                    "list_text": lines,
                },
            },
        )
        if len(records) >= target_count:
            break
    return records


def _ensure_playwright_available() -> None:
    if sync_playwright is None:
        raise BrowserSessionError(
            "未安装 Playwright，请先执行 `pip install playwright` 和 `python -m playwright install chromium`。"
        )


def _get_session(db: Session, provider: str) -> PlatformBrowserSession:
    ensure_platform_browser_sessions(db)
    session = db.scalar(select(PlatformBrowserSession).where(PlatformBrowserSession.provider == provider))
    if session is None:
        raise BrowserSessionError(f"未找到平台浏览器登录态配置：{provider}")
    return session


def _ensure_page_authenticated(page: Page, provider: str) -> None:
    title = page.title()
    url = page.url
    body_text = page.locator("body").inner_text(timeout=5000)[:2000]

    invalid_markers = (
        "手机号快捷登录",
        "发送验证码",
        "身份核实",
        "用最短线连接验证",
    )
    if any(marker in title or marker in body_text for marker in invalid_markers):
        raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 已退出登录或触发校验，请重新登录。")
    if "verify.meituan.com" in url or "/mlogin/" in url:
        raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 已退出登录或触发校验，请重新登录。")


def _scroll_page(page: Page, rounds: int) -> None:
    for _ in range(rounds):
        page.mouse.wheel(0, 2400)
        page.wait_for_timeout(1200)


def _pick_shop_name(lines: list[str]) -> str | None:
    ignored_prefixes = ("去APP查看", "打开", "取消", "更多", "上海", "南昌")
    for line in lines:
        if any(line.startswith(prefix) for prefix in ignored_prefixes):
            continue
        if len(line) < 2:
            continue
        if any(token in line for token in ("评价", "人均", "销量", "推荐", "优惠", "App内打开")):
            continue
        if re.fullmatch(r"[\d.]+", line):
            continue
        return line
    return None


def _pick_address(lines: list[str], city: str) -> str | None:
    for line in lines:
        if city and city in line and ADDRESS_HINT_RE.search(line):
            return line
    for line in lines:
        if ADDRESS_HINT_RE.search(line):
            return line
    return None


def _pick_district(lines: list[str], city: str) -> str | None:
    for line in lines:
        if city and city in line and DISTRICT_HINT_RE.search(line):
            parts = [part.strip() for part in re.split(r"[/·\s]+", line) if part.strip()]
            for part in parts:
                if DISTRICT_HINT_RE.search(part) and city not in part:
                    return part
    return None


def _extract_shop_id(href: str, detail_url: str) -> str:
    match = re.search(r"/shop/(\d+)", href) or re.search(r"/shop/(\d+)", detail_url)
    if match:
        return match.group(1)
    return str(abs(hash(detail_url)))


def _normalize_line(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _clean_items(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


def _session_scope() -> Session:
    from app.db.session import SessionLocal

    return SessionLocal()


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[2]


def _profile_root() -> Path:
    configured = Path(settings.browser_profile_root)
    if not configured.is_absolute():
        configured = _backend_dir() / configured
    configured.mkdir(parents=True, exist_ok=True)
    return configured


def _profile_dir(provider: str) -> Path:
    return _profile_root() / provider


def _profile_ready(profile_dir: Path) -> bool:
    return profile_dir.exists() and any(profile_dir.iterdir())


def _process_is_running(pid: int) -> bool:
    try:
        Path(f"/proc/{pid}")
    except Exception:
        pass
    try:
        import os

        os.kill(pid, 0)
        return True
    except OSError:
        return False
