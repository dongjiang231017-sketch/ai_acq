from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import os
import time
from datetime import datetime
from hashlib import md5
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode, urljoin
from urllib.request import urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.collection import LeadProviderConfig, PlatformBrowserSession

try:
    from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, sync_playwright
except Exception:  # pragma: no cover - handled with a runtime error message
    Page = Any  # type: ignore[assignment]
    PlaywrightTimeoutError = Exception  # type: ignore[assignment]
    sync_playwright = None

try:
    import websocket
except Exception:  # pragma: no cover - handled with a runtime error message
    websocket = None


class BrowserSessionError(ValueError):
    pass


BROWSER_PLATFORM_METADATA: dict[str, dict[str, str]] = {
    "meituan": {
        "name": "美团团购登录态",
        "login_url": "https://m.dianping.com/",
        "home_url": "https://m.dianping.com/",
        "engine": "dianping_shop_search",
        "viewport_mode": "mobile",
        "note": "第一版通过大众点评手机版搜索入口采集团购商家，需先登录点评/美团账号。",
    },
    "shangou": {
        "name": "淘宝闪购登录态",
        "login_url": "https://h5.ele.me/login/?redirect=https%3A%2F%2Fh5.ele.me%2F",
        "home_url": "https://h5.ele.me/",
        "engine": "taobao_flash_sale",
        "viewport_mode": "mobile",
        "note": "请登录淘宝闪购 H5 消费者页，登录后会回到首页。后端会使用登录态采集平台公开的商家电话，仅保留手机号码。",
    },
    "douyin": {
        "name": "抖音生活服务登录态",
        "login_url": "https://www.douyin.com/",
        "home_url": "https://www.douyin.com/",
        "engine": "douyin_life_service",
        "viewport_mode": "desktop",
        "note": "第一版通过抖音搜索页采集生活服务/团购商家，再回填地图电话。",
    },
}

MOBILE_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
)
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
)
SHANGOU_REMOTE_DEBUGGING_PORT = 9334
SHANGOU_REMOTE_DEBUGGING_ENDPOINT = f"http://127.0.0.1:{SHANGOU_REMOTE_DEBUGGING_PORT}"
ADDRESS_HINT_RE = re.compile(r"(路|街|道|广场|大厦|商场|中心|公寓|城|巷|里|号|店|楼|室)")
DISTRICT_HINT_RE = re.compile(r"(区|县|市)")
DIANPING_TITLE_NAME_RE = re.compile(r"【(?P<name>[^】]+)】")
DOUYIN_HASHTAG_RE = re.compile(r"#([^#\s]+)")
DOUYIN_DURATION_RE = re.compile(r"^\d{1,2}:\d{2}$")
DOUYIN_COUNT_RE = re.compile(r"^[\d.]+(?:万)?$")
DOUYIN_DATE_RE = re.compile(r"^(?:\d{4}年\d{1,2}月\d{1,2}日|\d{1,2}天前|\d{1,2}月\d{1,2}日)$")
DOUYIN_GENERIC_TAGS = {
    "南昌美食",
    "南昌火锅",
    "南昌探店",
    "南昌旅游攻略",
    "南昌打卡",
    "火锅",
    "重庆火锅",
    "火锅店",
    "火锅推荐",
    "火锅约起来",
    "火锅爱好者",
    "热辣江西",
    "真实生活分享计划",
    "青年创作者成长计划",
    "美食图文流量大赛",
    "美食探店推荐官",
    "交出你的宝藏烟火小店",
    "寻味烟火气",
    "用烟火小店打开中国美食地图",
    "晚餐吃什么",
    "天冷了吃点啥",
    "食欲感美食",
}
DOUYIN_GENERIC_CANDIDATE_TOKENS = (
    "合集",
    "攻略",
    "推荐",
    "分享",
    "打卡",
    "终于",
    "本地人",
    "好吃",
    "吃火锅",
    "带走",
    "附近",
    "人均",
    "限定",
    "收藏",
)
DOUYIN_LOCATION_WORDS = {
    "朝阳",
    "红谷滩",
    "高新",
    "东湖",
    "西湖",
    "青山湖",
    "青云谱",
    "九龙湖",
    "新建",
}
DOUYIN_MERCHANT_HINTS = (
    "火锅",
    "烤肉",
    "餐厅",
    "饭店",
    "酒楼",
    "酒家",
    "牛肉",
    "牛杂",
    "粥底",
    "串串",
    "烧烤",
    "料理",
    "小院",
    "食府",
    "小馆",
    "鲜切",
    "自助",
)
SHANGOU_DISTRICT_RE = re.compile(r"[\u4e00-\u9fff]{1,20}(?:高新区|经开区|开发区|新区|区|县|旗|镇|街道)")
SHANGOU_GENERIC_QUERY_TOKENS = {"商家", "商户", "商家信息", "店铺", "门店", "全部", "信息"}
PROFILE_SNAPSHOT_IGNORE = shutil.ignore_patterns(
    "SingletonLock",
    "SingletonSocket",
    "SingletonCookie",
    "DevToolsActivePort",
    "Crashpad",
    "Crash Reports",
    "Code Cache",
    "GPUCache",
    "GrShaderCache",
    "DawnGraphiteCache",
    "GraphiteDawnCache",
    "RunningChromeVersion",
)


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
        if provider == "shangou":
            _ensure_shangou_cdp_available()
            _validate_shangou_browser_session(session)
            session.status = "可用"
            session.last_error = None
        else:
            _ensure_playwright_available()
            with sync_playwright() as playwright:
                context = _launch_persistent_context(playwright, provider, profile_dir, headless=True, snapshot=True)
                page = context.new_page()
                try:
                    try:
                        page.goto(
                            session.home_url,
                            wait_until="domcontentloaded",
                            timeout=settings.browser_default_timeout_seconds * 1000,
                        )
                    except PlaywrightTimeoutError:
                        # 抖音等站点长连接较多，导航超时并不等同于登录失效，后续继续基于当前页面校验。
                        pass
                    page.wait_for_timeout(3000)
                    _ensure_page_authenticated(page, session.provider)
                    session.status = "可用"
                    session.last_error = None
                finally:
                    _close_browser_context(context)
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
        return _collect_shangou_shop_pois(db, city, category, keyword, target_count)
    if provider == "douyin":
        return _collect_douyin_shop_pois(city, category, keyword, target_count)
    raise BrowserSessionError(f"暂不支持的数据源：{provider}")


def _collect_meituan_shop_pois(city: str, category: str, keyword: str, target_count: int) -> list[dict[str, Any]]:
    query = " ".join(_clean_items([city, category, keyword]))
    if not query:
        raise BrowserSessionError("美团团购采集关键词不能为空")

    search_url = f"https://m.dianping.com/shoplist/1/search?from=m_search&keyword={quote(query)}"
    with sync_playwright() as playwright:
        context = _launch_persistent_context(playwright, "meituan", _profile_dir("meituan"), headless=False, snapshot=True)
        page = context.new_page()
        page.goto(search_url, wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
        page.wait_for_timeout(3000)
        _wait_for_platform_results(page, "meituan")
        _scroll_page(page, rounds=3)
        records = _extract_dianping_shop_cards(page, city, category, keyword, target_count)
        _close_browser_context(context)
    return records


def _collect_shangou_shop_pois(
    db: Session,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    city_name, district_name = _split_shangou_city_and_district(city, category, keyword)
    region = _resolve_shangou_region(db, city_name, district_name)
    query = _build_shangou_search_keyword(city_name, district_name, category, keyword)
    _ensure_shangou_cdp_available()
    return _collect_shangou_shop_pois_via_cdp(city_name, region, category, keyword, query, target_count)


def _split_shangou_city_and_district(city: str, category: str, keyword: str) -> tuple[str, str | None]:
    normalized_city = _normalize_line(city)
    district_name: str | None = None
    for candidate in (normalized_city, _normalize_line(category), _normalize_line(keyword)):
        match = SHANGOU_DISTRICT_RE.search(candidate)
        if match:
            district_name = match.group(0)
            break

    city_name = normalized_city
    if district_name and district_name in city_name:
        city_name = city_name.split(district_name, 1)[0].strip()
    city_name = city_name.rstrip("市").strip() or normalized_city
    return city_name, district_name


def _build_shangou_search_keyword(
    city_name: str,
    district_name: str | None,
    category: str,
    keyword: str,
) -> str:
    parts: list[str] = []
    if city_name:
        parts.append(city_name)
    if district_name:
        parts.append(district_name)
    for raw in (category, keyword):
        candidate = _normalize_line(raw)
        if district_name:
            candidate = candidate.replace(district_name, "").strip()
        if city_name:
            candidate = candidate.replace(city_name, "").strip()
        if candidate and candidate not in SHANGOU_GENERIC_QUERY_TOKENS:
            parts.append(candidate)
    return " ".join(_clean_items(parts)) or "附近商家"


def _read_browser_provider_api_key(db: Session, provider: str) -> str | None:
    config = db.scalar(select(LeadProviderConfig).where(LeadProviderConfig.provider == provider))
    if config and not config.enabled:
        return None
    if config and config.api_key:
        return config.api_key.strip()
    if provider == "amap" and settings.amap_web_key:
        return settings.amap_web_key.strip()
    if provider == "baidu" and settings.baidu_map_key:
        return settings.baidu_map_key.strip()
    return None


def _resolve_shangou_region(db: Session, city_name: str, district_name: str | None) -> dict[str, str]:
    region_query = f"{city_name}{district_name or ''}".strip()
    amap_key = _read_browser_provider_api_key(db, "amap")
    if amap_key:
        params = {
            "key": amap_key,
            "address": region_query,
            "output": "JSON",
        }
        url = f"https://restapi.amap.com/v3/geocode/geo?{urlencode(params)}"
        with urlopen(url, timeout=settings.collection_request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") == "1":
            geocodes = payload.get("geocodes") or []
            if isinstance(geocodes, list) and geocodes:
                geocode = geocodes[0]
                location = str(geocode.get("location") or "")
                if "," in location:
                    longitude, latitude = location.split(",", 1)
                    district = str(geocode.get("district") or district_name or "").strip() or district_name or ""
                    adcode = str(geocode.get("adcode") or "").strip()
                    return {
                        "city_name": city_name,
                        "district_name": district,
                        "district_adcode": adcode,
                        "longitude": longitude.strip(),
                        "latitude": latitude.strip(),
                    }

    baidu_key = _read_browser_provider_api_key(db, "baidu")
    if baidu_key:
        params = {
            "ak": baidu_key,
            "address": region_query,
            "output": "json",
        }
        url = f"https://api.map.baidu.com/geocoding/v3/?{urlencode(params)}"
        with urlopen(url, timeout=settings.collection_request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") == 0:
            result = payload.get("result") or {}
            location = result.get("location") or {}
            if location.get("lng") is not None and location.get("lat") is not None:
                components = result.get("addressComponent") or {}
                district = str(components.get("district") or district_name or "").strip() or district_name or ""
                adcode = str(components.get("adcode") or "").strip()
                return {
                    "city_name": city_name,
                    "district_name": district,
                    "district_adcode": adcode,
                    "longitude": str(location.get("lng")),
                    "latitude": str(location.get("lat")),
                }

    raise BrowserSessionError("未能解析淘宝闪购采集区域，请先在后台配置高德或百度地图密钥。")


def _open_shangou_search_results(page: Page, region: dict[str, str], query: str) -> None:
    search_url = (
        "https://h5.ele.me/minisearch"
        f"?from=mobile.default&__locLat={quote(str(region['latitude']))}&__locLng={quote(str(region['longitude']))}"
    )
    page.goto(search_url, wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
    page.wait_for_timeout(2500)
    _dismiss_shangou_overlay(page)

    input_locator = page.locator("input").first
    if input_locator.count() == 0:
        raise BrowserSessionError("淘宝闪购搜索页未正常打开，请在专用 Chrome 窗口确认登录后重试。")

    input_locator.click(timeout=3000)
    input_locator.fill(query, timeout=5000)
    page.wait_for_timeout(500)
    input_locator.press("Enter", timeout=3000)
    page.wait_for_timeout(3500)
    _dismiss_shangou_overlay(page)


def _ensure_shangou_search_cards(page: Page, timeout_ms: int = 15000) -> None:
    started = datetime.utcnow()
    while (datetime.utcnow() - started).total_seconds() * 1000 < timeout_ms:
        _ensure_page_authenticated(page, "shangou")
        _dismiss_shangou_overlay(page)
        cards = page.locator(".mat_shopmode-shop-item")
        if cards.count() > 0:
            return
        if _shangou_has_risk_prompt(page):
            raise BrowserSessionError("淘宝闪购已触发平台验证，请在专用 Chrome 窗口完成验证后，再回到系统里重试采集。")
        page.wait_for_timeout(1000)
    if _shangou_has_risk_prompt(page):
        raise BrowserSessionError("淘宝闪购已触发平台验证，请在专用 Chrome 窗口完成验证后，再回到系统里重试采集。")
    raise BrowserSessionError("淘宝闪购搜索结果暂时未加载出来，请稍后重试。")


def _dismiss_shangou_overlay(page: Page) -> None:
    close_button = page.locator(".baxia-dialog-close")
    try:
        if close_button.count() > 0 and close_button.first.is_visible():
            close_button.first.click(timeout=1000)
            page.wait_for_timeout(300)
    except Exception:
        pass


def _shangou_has_risk_prompt(page: Page) -> bool:
    try:
        body_text = page.locator("body").inner_text(timeout=1500)
    except Exception:
        body_text = ""
    if "哎呀出错了" in body_text or "小宝正在检修中" in body_text or "重新加载" in body_text:
        return True
    try:
        return page.locator(".baxia-dialog-mask").count() > 0 and page.locator(".mat_shopmode-shop-item").count() == 0
    except Exception:
        return False


def _extract_shangou_card_name(card: Any) -> str | None:
    try:
        rich_text = card.locator(".mat_shopmode-shop-item-r-title-text").first
        if rich_text.count() > 0:
            name = _extract_tiga_nodes_text(rich_text.get_attribute("nodes"))
            if name:
                return name
    except Exception:
        pass
    return _pick_shop_name([line for line in _safe_inner_text(card).splitlines() if _normalize_line(line)])


def _extract_tiga_nodes_text(raw_nodes: str | None) -> str | None:
    if not raw_nodes:
        return None
    try:
        nodes = json.loads(raw_nodes)
    except json.JSONDecodeError:
        return None

    queue = list(nodes) if isinstance(nodes, list) else [nodes]
    while queue:
        item = queue.pop(0)
        if not isinstance(item, dict):
            continue
        if item.get("type") == "text":
            text = _normalize_line(str(item.get("text") or ""))
            if text:
                return text
        children = item.get("children")
        if isinstance(children, list):
            queue[0:0] = children
    return None


def _safe_inner_text(locator: Any, timeout: int = 1000) -> str:
    try:
        return locator.inner_text(timeout=timeout).strip()
    except Exception:
        return ""


def _open_shangou_detail_from_card(page: Page, card: Any, index: int) -> dict[str, str] | None:
    card_name = _extract_shangou_card_name(card)
    card.scroll_into_view_if_needed(timeout=5000)
    page.wait_for_timeout(300)
    card.click(timeout=5000)
    page.wait_for_timeout(4000)
    if _shangou_has_risk_prompt(page):
        raise BrowserSessionError("淘宝闪购已触发平台验证，请在专用 Chrome 窗口完成验证后，再回到系统里重试采集。")
    match = re.search(r"[?&]shopId=([^&]+)", page.url)
    if not match:
        return None
    return {
        "shop_id": match.group(1),
        "name": card_name or "",
        "detail_url": page.url,
        "index": str(index),
    }


def _fetch_shangou_business_info(page: Page) -> dict[str, Any]:
    payload_text: str | None = None
    try:
        with page.expect_response(lambda response: "business.tab.page" in response.url, timeout=15000) as info:
            page.get_by_text("商家", exact=True).click(timeout=5000)
        payload_text = info.value.text()
    except Exception:
        try:
            page.get_by_text("商家", exact=True).click(timeout=5000)
            page.wait_for_timeout(1200)
        except Exception:
            pass

    if payload_text:
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {}
        info = payload.get("data", {}).get("resultMap", {}).get("businessTabBasicInfo", {}).get("storeInfo", {})
        if isinstance(info, dict):
            return {
                "name": _normalize_line(str(info.get("storeName") or "")) or None,
                "address": _normalize_line(str(info.get("storeAddress") or "")) or None,
                "longitude": info.get("longitude"),
                "latitude": info.get("latitude"),
                "raw": info,
            }

    body_text = page.locator("body").inner_text(timeout=3000)
    lines = [_normalize_line(line) for line in body_text.splitlines() if _normalize_line(line)]
    address = _pick_dianping_detail_address(lines)
    return {
        "name": _pick_shop_name(lines),
        "address": address,
        "longitude": None,
        "latitude": None,
        "raw": {"lines": lines[:80]},
    }


def _return_from_shangou_detail(page: Page) -> None:
    page.go_back(wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
    page.wait_for_timeout(2500)
    _dismiss_shangou_overlay(page)


def _fetch_shangou_search_page(
    page: Page,
    region: dict[str, str],
    query: str,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    params = {
        "latitude": region["latitude"],
        "longitude": region["longitude"],
        "keyword": query,
        "offset": str(offset),
        "limit": str(limit),
    }
    result = _page_fetch_text(
        page,
        f"/restapi/bgs/poi/search_poi_nearby?{urlencode(params)}",
        headers=_shangou_request_headers(longitude=region["longitude"], latitude=region["latitude"]),
    )
    if result["status"] != 200:
        raise BrowserSessionError(f"淘宝闪购搜索接口返回异常：HTTP {result['status']}")
    try:
        payload = json.loads(result["text"] or "[]")
    except json.JSONDecodeError as exc:
        raise BrowserSessionError("淘宝闪购搜索接口返回了无法解析的数据。") from exc
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _fetch_shangou_shop_phone(
    page: Page,
    shop_id: str,
    longitude: Any = None,
    latitude: Any = None,
) -> str | None:
    result = _page_fetch_text(
        page,
        f"/restapi/giraffe/restaurant/phone?shopId={quote(str(shop_id))}",
        headers=_shangou_request_headers(shop_id=shop_id, longitude=longitude, latitude=latitude),
    )
    if result["status"] != 200 or not result["text"].strip():
        return None

    raw_phone = result["text"].strip()
    try:
        decoded = json.loads(raw_phone)
    except json.JSONDecodeError:
        decoded = raw_phone

    if isinstance(decoded, dict):
        return _extract_mobile_phone(
            str(decoded.get("phone") or decoded.get("mobile") or decoded.get("data") or decoded.get("numbers") or "")
        )
    if isinstance(decoded, list):
        for item in decoded:
            if isinstance(item, dict):
                for candidate in item.get("numbers") or []:
                    phone = _extract_mobile_phone(str(candidate))
                    if phone:
                        return phone
                for key in ("phone", "mobile", "tel", "number"):
                    phone = _extract_mobile_phone(str(item.get(key) or ""))
                    if phone:
                        return phone
            else:
                phone = _extract_mobile_phone(str(item))
                if phone:
                    return phone
        return None
    return _extract_mobile_phone(str(decoded))


def _matches_shangou_region(item: dict[str, Any], region: dict[str, str]) -> bool:
    district_adcode = region.get("district_adcode")
    if district_adcode and str(item.get("district_adcode") or "").strip() == district_adcode:
        return True
    district_name = region.get("district_name") or ""
    address = str(item.get("address") or "")
    return bool(district_name and district_name in address)


def _extract_mobile_phone(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D+", "", str(value))
    if digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]
    return digits if re.fullmatch(r"1[3-9]\d{9}", digits) else None


def _build_shangou_location(longitude: Any, latitude: Any) -> str | None:
    if longitude in (None, "") or latitude in (None, ""):
        return None
    return f"{longitude},{latitude}"


def _shangou_request_headers(
    shop_id: str | None = None,
    longitude: Any = None,
    latitude: Any = None,
) -> dict[str, str]:
    parts: list[str] = []
    if shop_id:
        parts.append(f"shopid={shop_id}")
    if longitude not in (None, "") and latitude not in (None, ""):
        parts.append(f"loc={longitude},{latitude}")
    headers = {
        "Accept": "application/json, text/plain, */*",
    }
    if parts:
        headers["X-Shard"] = ";".join(parts)
    return headers


def _page_fetch_text(page: Page, path: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    return page.evaluate(
        """
        async ({ path, headers }) => {
          const response = await fetch(path, {
            credentials: "include",
            headers: headers || {},
          });
          const text = await response.text();
          return {
            status: response.status,
            url: response.url,
            text,
          };
        }
        """,
        {"path": path, "headers": headers or {}},
    )


class _ShangouCdpPage:
    def __init__(self, target: dict[str, Any]):
        self.target = target
        self._connection: Any | None = None
        self._next_id = 0

    def __enter__(self) -> "_ShangouCdpPage":
        if websocket is None:
            raise BrowserSessionError("未安装 websocket-client，无法连接淘宝闪购专用 Chrome。")
        try:
            self._connection = websocket.create_connection(
                self.target["webSocketDebuggerUrl"],
                enable_multithread=True,
                suppress_origin=True,
                http_proxy_host=None,
                http_proxy_port=None,
                timeout=settings.collection_request_timeout_seconds,
            )
            self._connection.settimeout(max(settings.collection_request_timeout_seconds, 5))
            self.call("Runtime.enable")
            self.call("Page.enable")
        except Exception as exc:
            self.close()
            raise BrowserSessionError("无法连接淘宝闪购专用 Chrome 页面，请确认专用窗口已打开并停留在闪购页面。") from exc
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._connection is None:
            return
        try:
            self._connection.close()
        except Exception:
            pass
        self._connection = None

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._connection is None:
            raise BrowserSessionError("淘宝闪购专用 Chrome 连接已关闭。")
        self._next_id += 1
        message_id = self._next_id
        self._connection.send(json.dumps({"id": message_id, "method": method, "params": params or {}}))
        while True:
            raw_message = self._connection.recv()
            payload = json.loads(raw_message)
            if payload.get("id") != message_id:
                continue
            if payload.get("error"):
                raise BrowserSessionError(f"淘宝闪购专用 Chrome 调用失败：{payload['error']}")
            return payload.get("result") or {}

    def evaluate(self, expression: str, await_promise: bool = False, return_by_value: bool = True) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": return_by_value,
            },
        )
        if result.get("exceptionDetails"):
            raise BrowserSessionError("淘宝闪购页面脚本执行失败，请刷新专用窗口后重试。")
        value = result.get("result") or {}
        return value.get("value")

    def current_url(self) -> str:
        return str(self.evaluate("location.href") or self.target.get("url") or "")

    def body_text(self, limit: int = 12000) -> str:
        return str(self.evaluate(f"document.body ? document.body.innerText.slice(0, {limit}) : ''") or "")

    def navigate(self, url: str, wait_seconds: float = 0.0) -> None:
        self.call("Page.navigate", {"url": url})
        if wait_seconds > 0:
            time.sleep(wait_seconds)

    def wait_for(
        self,
        resolver: Any,
        timeout_seconds: float,
        interval_seconds: float,
        failure_message: str,
    ) -> Any:
        deadline = time.monotonic() + timeout_seconds
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                value = resolver()
                if value:
                    return value
            except Exception as exc:  # pragma: no cover - best effort runtime polling
                last_error = exc
            time.sleep(interval_seconds)
        if last_error is not None:
            raise BrowserSessionError(f"{failure_message}：{last_error}")
        raise BrowserSessionError(failure_message)

    def dismiss_overlay(self) -> None:
        try:
            self.evaluate(
                """
                (() => {
                  const button = document.querySelector(".baxia-dialog-close");
                  if (button instanceof HTMLElement) {
                    button.click();
                    return true;
                  }
                  return false;
                })()
                """
            )
        except Exception:
            pass

    def scroll_by(self, delta_y: int) -> None:
        self.evaluate(f"window.scrollBy(0, {int(delta_y)});")

    def list_search_cards(self) -> list[dict[str, Any]]:
        data = self.evaluate(
            """
            (() => {
              const readMeta = (element) => {
                const fiberKey = Object.getOwnPropertyNames(element).find((key) => key.startsWith("__reactFiber$"));
                let cursor = fiberKey ? element[fiberKey] : null;
                for (let depth = 0; depth < 8 && cursor; depth += 1) {
                  const props = cursor?.stateNode?.props || cursor?.stateNode?.componentConfig?.props;
                  const content = props?.["data-content"];
                  if (content && typeof content === "object") {
                    const targetUrl = String(content.targetUrl || "");
                    const fromUrl = (pattern) => {
                      const match = targetUrl.match(pattern);
                      return match ? match[1] : "";
                    };
                    return {
                      detailUrl: targetUrl || "",
                      shopId: String(content.id || props["data-track-restaurant_id"] || fromUrl(/[?&]ele_id=([^&]+)/) || ""),
                      storeId: fromUrl(/[?&]store_id=([^&]+)/),
                      targetName: String(content.name || ""),
                      distance: String(content.distance || ""),
                    };
                  }
                  cursor = cursor.return;
                }
                return {
                  detailUrl: "",
                  shopId: "",
                  storeId: "",
                  targetName: "",
                  distance: "",
                };
              };
              const extractName = (root) => {
                const title = root.querySelector(".mat_shopmode-shop-item-r-title-text");
                const rawNodes = title?.getAttribute("nodes");
                if (rawNodes) {
                  try {
                    const queue = JSON.parse(rawNodes);
                    const list = Array.isArray(queue) ? [...queue] : [queue];
                    while (list.length) {
                      const item = list.shift();
                      if (!item || typeof item !== "object") continue;
                      if (item.type === "text" && item.text) return String(item.text).trim();
                      if (Array.isArray(item.children)) list.unshift(...item.children);
                    }
                  } catch (error) {
                    // ignore
                  }
                }
                return title?.textContent?.trim() || "";
              };
              return Array.from(document.querySelectorAll(".mat_shopmode-shop-item")).map((element, index) => {
                const rect = element.getBoundingClientRect();
                const meta = readMeta(element);
                return {
                  index,
                  name: extractName(element),
                  text: (element.innerText || "").trim(),
                  left: rect.left,
                  top: rect.top,
                  width: rect.width,
                  height: rect.height,
                  detail_url: meta.detailUrl,
                  shop_id: meta.shopId,
                  store_id: meta.storeId,
                  meta_name: meta.targetName,
                  distance: meta.distance,
                };
              });
            })()
            """
        )
        return data if isinstance(data, list) else []

    def click_point(self, x: float, y: float) -> None:
        for event_type, button, click_count in (
            ("mouseMoved", "none", 0),
            ("mousePressed", "left", 1),
            ("mouseReleased", "left", 1),
        ):
            payload: dict[str, Any] = {
                "type": event_type,
                "x": float(x),
                "y": float(y),
                "button": button,
                "buttons": 1 if event_type != "mouseMoved" else 0,
                "clickCount": click_count,
            }
            self.call("Input.dispatchMouseEvent", payload)

    def click_search_card(self, index: int) -> dict[str, Any] | None:
        self.evaluate(
            f"""
            (() => {{
              const element = document.querySelectorAll(".mat_shopmode-shop-item")[{index}];
              if (!(element instanceof HTMLElement)) return false;
              element.scrollIntoView({{ block: "center", inline: "nearest" }});
              return true;
            }})()
            """
        )
        time.sleep(0.4)
        cards = self.list_search_cards()
        if index >= len(cards):
            return None
        card = cards[index]
        self.click_point(card["left"] + (card["width"] / 2), card["top"] + min(card["height"] / 2, 60))
        return card

    def fetch_text(self, path: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
        payload = json.dumps({"path": path, "headers": headers or {}}, ensure_ascii=False)
        result = self.evaluate(
            f"""
            (async () => {{
              const {{ path, headers }} = {payload};
              const response = await fetch(path, {{
                credentials: "include",
                headers: headers || {{}},
              }});
              const text = await response.text();
              return {{
                status: response.status,
                url: response.url,
                text,
              }};
            }})()
            """,
            await_promise=True,
        )
        return result if isinstance(result, dict) else {"status": 0, "url": "", "text": ""}


def _ensure_shangou_cdp_available() -> None:
    if websocket is None:
        raise BrowserSessionError("未安装 websocket-client，无法连接淘宝闪购专用 Chrome。")
    try:
        with urlopen(f"{SHANGOU_REMOTE_DEBUGGING_ENDPOINT}/json/version", timeout=3) as response:
            response.read()
    except Exception as exc:
        raise BrowserSessionError("未检测到淘宝闪购专用 Chrome 窗口，请先点击“打开登录窗口”，并在该窗口完成登录。") from exc


def _load_shangou_cdp_targets() -> list[dict[str, Any]]:
    try:
        with urlopen(f"{SHANGOU_REMOTE_DEBUGGING_ENDPOINT}/json/list", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise BrowserSessionError("读取淘宝闪购专用 Chrome 页面失败，请确认窗口仍然打开。") from exc
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _pick_shangou_cdp_target(preferred_url_markers: tuple[str, ...] = ()) -> dict[str, Any]:
    targets = [item for item in _load_shangou_cdp_targets() if item.get("type") == "page"]
    shangou_targets = [
        item
        for item in targets
        if "h5.ele.me/" in str(item.get("url") or "")
    ]
    if not shangou_targets:
        raise BrowserSessionError("专用 Chrome 已打开，但当前没有淘宝闪购页面，请先在该窗口打开首页、搜索结果页或店铺详情页。")

    for marker in preferred_url_markers:
        for item in shangou_targets:
            if marker in str(item.get("url") or ""):
                return item
    for item in shangou_targets:
        if "h5.ele.me/login" not in str(item.get("url") or ""):
            return item
    return shangou_targets[0]


def _validate_shangou_browser_session(session: PlatformBrowserSession) -> None:
    target = _pick_shangou_cdp_target(("minisearch/result", "newretail/p/ushop/", "minisite", "h5.ele.me/"))
    with _ShangouCdpPage(target) as page:
        current_url = page.current_url()
        if "h5.ele.me/login" in current_url:
            raise BrowserSessionError(f"{session.name} 尚未完成 H5 登录，请重新登录。")
        if not _shangou_has_logged_in_user_cdp(page):
            raise BrowserSessionError(f"{session.name} 当前未检测到已登录账号，请重新登录。")


def _collect_shangou_shop_pois_via_cdp(
    city_name: str,
    region: dict[str, str],
    category: str,
    keyword: str,
    query: str,
    target_count: int,
) -> list[dict[str, Any]]:
    result_url = _build_shangou_result_url(region, query)
    target = _pick_shangou_cdp_target(("minisearch/result", "newretail/p/ushop/", "minisite", "h5.ele.me/"))
    with _ShangouCdpPage(target) as page:
        if not _shangou_has_logged_in_user_cdp(page):
            raise BrowserSessionError("淘宝闪购当前未检测到已登录账号，请先在专用 Chrome 窗口完成登录。")

        _prepare_shangou_result_page_cdp(page, city_name, region, query, result_url)
        _ensure_shangou_search_cards_cdp(page, result_url=result_url)
        search_candidates = _fetch_shangou_search_candidates_cdp(page, region, query, target_count)
        candidate_buckets = _group_shangou_candidates_by_name(search_candidates)

        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        result_index = 0
        scan_limit = max(target_count * 6, 30)

        while len(records) < target_count and result_index < scan_limit:
            cards = page.list_search_cards()
            while result_index >= len(cards):
                previous_count = len(cards)
                page.scroll_by(2200)
                time.sleep(1.2)
                page.dismiss_overlay()
                cards = page.list_search_cards()
                if len(cards) <= previous_count:
                    break
            if result_index >= len(cards):
                break

            card = cards[result_index]
            result_index += 1
            clicked_card = card
            detail = _resolve_shangou_card_detail(card)
            if detail is None:
                clicked_card = page.click_search_card(result_index - 1)
                if clicked_card is None:
                    continue
                detail = _wait_for_shangou_detail_cdp(page, result_url, clicked_card, result_index - 1)
                if detail is None:
                    continue

            shop_id = detail["shop_id"]
            if shop_id in seen_ids:
                if detail.get("opened_detail"):
                    _return_from_shangou_detail_cdp(page, result_url)
                continue

            phone = _fetch_shangou_shop_phone_cdp(page, shop_id)
            if not phone:
                if detail.get("opened_detail"):
                    _return_from_shangou_detail_cdp(page, result_url)
                continue

            business_info = (
                _fetch_shangou_business_info_cdp(page, city_name, clicked_card.get("name") or detail["name"])
                if detail.get("opened_detail")
                else {
                    "name": clicked_card.get("name") or clicked_card.get("meta_name") or detail["name"],
                    "address": None,
                    "longitude": None,
                    "latitude": None,
                    "raw": {"source": "search_card"},
                }
            )
            matched_candidate = _match_shangou_candidate(candidate_buckets, business_info.get("name"), detail["name"], clicked_card.get("name"))
            address = _sanitize_shangou_address(
                business_info.get("name") or clicked_card.get("name") or detail["name"],
                (matched_candidate or {}).get("address") or business_info.get("address"),
                city_name,
                region["district_name"],
            )
            location = _build_shangou_location(
                (matched_candidate or {}).get("longitude") or business_info.get("longitude"),
                (matched_candidate or {}).get("latitude") or business_info.get("latitude"),
            )
            seen_ids.add(shop_id)
            records.append(
                {
                    "id": shop_id,
                    "name": business_info.get("name") or clicked_card.get("name") or detail["name"] or shop_id,
                    "cityname": city_name,
                    "adname": region["district_name"],
                    "pname": None,
                    "address": address,
                    "tel": phone,
                    "location": location,
                    "type": category or keyword or "淘宝闪购",
                    "detail_url": detail["detail_url"],
                    "_raw_provider": "shangou",
                    "_raw_payload": {
                        "provider": "shangou",
                        "query_city": city_name,
                        "query_category": category,
                        "query_keyword": keyword,
                        "search_query": query,
                        "region": region,
                        "source_url": detail["detail_url"],
                        "search_record": {
                            "index": result_index - 1,
                            "name": clicked_card.get("name"),
                            "text": clicked_card.get("text"),
                            "detail_url": clicked_card.get("detail_url"),
                            "shop_id": clicked_card.get("shop_id"),
                        },
                        "business_info": business_info,
                        "search_candidate": matched_candidate,
                    },
                },
            )
            if detail.get("opened_detail"):
                _return_from_shangou_detail_cdp(page, result_url)
        return records[:target_count]


def _resolve_shangou_card_detail(card: dict[str, Any] | None) -> dict[str, str | bool] | None:
    if not isinstance(card, dict):
        return None
    shop_id = str(card.get("shop_id") or "").strip()
    detail_url = str(card.get("detail_url") or "").strip()
    fallback_name = str(card.get("meta_name") or card.get("name") or "").strip()
    if not shop_id and detail_url:
        match = re.search(r"[?&]ele_id=([^&]+)", detail_url)
        if match:
            shop_id = match.group(1)
    if not shop_id:
        return None
    return {
        "shop_id": shop_id,
        "name": fallback_name or shop_id,
        "detail_url": detail_url,
        "index": str(card.get("index") or ""),
        "opened_detail": False,
    }


def _build_shangou_result_url(region: dict[str, str], query: str) -> str:
    params = {
        "from": "mobile.default",
        "geolat": str(region["latitude"]),
        "geolng": str(region["longitude"]),
        "__locLat": str(region["latitude"]),
        "__locLng": str(region["longitude"]),
        "keyword": query,
    }
    return f"https://h5.ele.me/minisearch/result?{urlencode(params)}"


def _build_shangou_address_url(region: dict[str, str], query: str, result_url: str) -> str:
    params = {
        "redirect": result_url,
        "longitude": str(region["longitude"]),
        "latitude": str(region["latitude"]),
        "keyword": query,
        "from": "mobile.default",
    }
    return f"https://h5.ele.me/minisite/pages-poi/address/index?{urlencode(params)}"


def _prepare_shangou_result_page_cdp(
    page: _ShangouCdpPage,
    city_name: str,
    region: dict[str, str],
    query: str,
    result_url: str,
) -> None:
    page.dismiss_overlay()
    page.navigate(_build_shangou_address_url(region, query, result_url), wait_seconds=1.8)
    current_url = page.current_url()
    if "pages-poi/address/index" in current_url:
        current_city = _read_shangou_address_page_city_cdp(page)
        if city_name and city_name not in current_city:
            _switch_shangou_city_from_address_page_cdp(page, city_name)
        _select_shangou_address_cdp(page, city_name, region)
    elif "pages-poi/city/index" in current_url:
        _select_shangou_city_cdp(page, city_name)
        _select_shangou_address_cdp(page, city_name, region)
    current_url = page.current_url()
    if "minisearch/result" in current_url and current_url == result_url and page.list_search_cards():
        return
    page.navigate(result_url, wait_seconds=1.2)


def _switch_shangou_city_from_address_page_cdp(page: _ShangouCdpPage, city_name: str) -> None:
    current_city = _read_shangou_address_page_city_cdp(page)
    if current_city and city_name in current_city:
        return
    page.evaluate(
        """
        (() => {
          const trigger = document.querySelector('.poi-address-bar__city');
          if (!(trigger instanceof HTMLElement)) return false;
          trigger.click();
          return true;
        })()
        """
    )
    page.wait_for(
        lambda: page.current_url() if "pages-poi/city/index" in page.current_url() else None,
        8.0,
        0.4,
        "打开淘宝闪购城市选择页失败",
    )
    _select_shangou_city_cdp(page, city_name)


def _read_shangou_address_page_city_cdp(page: _ShangouCdpPage) -> str:
    return _normalize_line(
        str(
            page.evaluate(
                """
                (() => {
                  const node = document.querySelector('.poi-address-bar__city');
                  return node instanceof HTMLElement ? (node.innerText || node.textContent || '') : '';
                })()
                """
            )
            or ""
        )
    )


def _select_shangou_city_cdp(page: _ShangouCdpPage, city_name: str) -> None:
    normalized_city = city_name.rstrip("市").strip()
    target_labels = tuple(dict.fromkeys([f"{normalized_city}市", normalized_city]))

    def _click_target_city() -> bool:
        clicked = page.evaluate(
            f"""
            (() => {{
              const labels = {json.dumps(target_labels, ensure_ascii=False)};
              const nodes = Array.from(document.querySelectorAll('div, span, a'));
              const target = nodes.find((node) => labels.includes((node.innerText || node.textContent || '').trim()));
              if (!(target instanceof HTMLElement)) return false;
              target.click();
              return true;
            }})()
            """
        )
        return bool(clicked)

    if not _click_target_city():
        _search_shangou_city_cdp(page, normalized_city)
        page.wait_for(
            _click_target_city,
            8.0,
            0.5,
            f"淘宝闪购城市列表里没有找到“{normalized_city}市”，请先在专用窗口确认地址页可用。",
        )

    page.wait_for(
        lambda: _read_shangou_address_page_city_cdp(page) if "pages-poi/address/index" in page.current_url() else None,
        8.0,
        0.4,
        "切换淘宝闪购城市失败",
    )
    current_city = _read_shangou_address_page_city_cdp(page)
    if normalized_city and normalized_city not in current_city:
        raise BrowserSessionError(f"淘宝闪购当前城市仍是“{current_city or '未知'}”，未切换到“{normalized_city}”。")


def _search_shangou_city_cdp(page: _ShangouCdpPage, city_name: str) -> None:
    page.evaluate(
        f"""
        (() => {{
          const input = document.querySelector('.poi-city-search-bar-search-input-tag')
            || document.querySelectorAll('input')[1]
            || document.querySelector('input');
          if (!(input instanceof HTMLInputElement)) return false;
          const value = {json.dumps(city_name, ensure_ascii=False)};
          input.focus();
          input.value = value;
          input.dispatchEvent(new Event('input', {{ bubbles: true }}));
          input.dispatchEvent(new Event('change', {{ bubbles: true }}));
          input.dispatchEvent(new KeyboardEvent('keyup', {{ bubbles: true, key: 'Enter' }}));
          return true;
        }})()
        """
    )
    time.sleep(0.8)


def _select_shangou_address_cdp(page: _ShangouCdpPage, city_name: str, region: dict[str, str]) -> None:
    current_url = page.current_url()
    if "pages-poi/address/index" not in current_url:
        return

    current_city = _read_shangou_address_page_city_cdp(page)
    if city_name and city_name not in current_city:
        raise BrowserSessionError(f"淘宝闪购当前地址页城市仍是“{current_city or '未知'}”，未切换到“{city_name}”。")

    district_name = str(region.get("district_name") or "").strip()
    search_terms = [term for term in [f"{city_name}市政府", f"{city_name}市人民政府", district_name, city_name] if term]
    last_error: BrowserSessionError | None = None
    for term in search_terms:
        try:
            _open_shangou_address_search_cdp(page, term)
            if _click_shangou_address_candidate_cdp(page, city_name, term, district_name):
                page.wait_for(
                    lambda: page.current_url() if "minisearch/result" in page.current_url() else None,
                    10.0,
                    0.5,
                    "切换淘宝闪购收货地址失败",
                )
                return
        except BrowserSessionError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise BrowserSessionError(f"淘宝闪购未找到“{city_name}”可用收货地址，请先在专用窗口确认地址搜索可用。")


def _open_shangou_address_search_cdp(page: _ShangouCdpPage, keyword: str) -> None:
    page.evaluate(
        f"""
        (() => {{
          const input = document.querySelector('.poi-address-bar__input') || document.querySelector('input');
          if (!(input instanceof HTMLInputElement)) return false;
          input.click();
          input.focus();
          input.value = {json.dumps(keyword, ensure_ascii=False)};
          input.dispatchEvent(new Event('input', {{ bubbles: true }}));
          input.dispatchEvent(new Event('change', {{ bubbles: true }}));
          return true;
        }})()
        """
    )
    time.sleep(1.0)


def _click_shangou_address_candidate_cdp(
    page: _ShangouCdpPage,
    city_name: str,
    keyword: str,
    district_name: str | None,
) -> bool:
    result = page.evaluate(
        f"""
        (() => {{
          const cityName = {json.dumps(city_name, ensure_ascii=False)};
          const keyword = {json.dumps(keyword, ensure_ascii=False)};
          const districtName = {json.dumps(district_name or '', ensure_ascii=False)};
          const ignore = new Set(['全部', cityName, `${{cityName}}市`, districtName, `${{districtName}}区`, '新增收货地址']);
          const nodes = Array.from(document.querySelectorAll('div, span, a'));
          const candidates = nodes
            .map((node) => {{
              const text = (node.textContent || '').trim();
              return {{ node, text }};
            }})
            .filter((item) => item.text && !ignore.has(item.text))
            .filter((item) => !/搜索到多个不同区域的地址|请输入收货地址|查看更多地址|编辑|删除|常用|公司/.test(item.text))
            .filter((item) => !/(区|县)$/.test(item.text))
            .filter((item) => item.text.includes(cityName) || (districtName && item.text.includes(districtName)));

          const exact = candidates.find((item) => item.text === keyword);
          const strong = candidates.find((item) => item.text.includes(keyword) && item.text.length > cityName.length + 1);
          const first = exact || strong || candidates[0];
          if (!(first?.node instanceof HTMLElement)) return false;
          first.node.click();
          return true;
        }})()
        """
    )
    return bool(result)


def _try_recover_shangou_result_page_cdp(page: _ShangouCdpPage, result_url: str | None = None) -> None:
    clicked_reload = False
    try:
        clicked_reload = bool(
            page.evaluate(
                """
                (() => {
                  const trigger = Array.from(document.querySelectorAll("button, a, div, span"))
                    .find((item) => (item.textContent || "").trim() === "重新加载");
                  if (trigger instanceof HTMLElement) {
                    trigger.click();
                    return true;
                  }
                  location.reload();
                  return false;
                })()
                """
            )
        )
    except Exception:
        if result_url:
            page.navigate(result_url, wait_seconds=1.2)
            return
    time.sleep(1.8 if clicked_reload else 2.2)


def _ensure_shangou_search_cards_cdp(
    page: _ShangouCdpPage,
    timeout_seconds: float = 15.0,
    result_url: str | None = None,
) -> None:
    transient_retried = False

    def _cards_ready() -> bool:
        nonlocal transient_retried
        page.dismiss_overlay()
        body_text = page.body_text(limit=3000)
        if _shangou_has_auth_prompt_text(body_text):
            raise BrowserSessionError("淘宝闪购已触发平台验证，请先在专用 Chrome 窗口完成验证后再重试。")
        if _shangou_has_transient_error_text(body_text):
            if not transient_retried:
                transient_retried = True
                _try_recover_shangou_result_page_cdp(page, result_url)
                return False
            raise BrowserSessionError("淘宝闪购结果页暂时异常，请先在专用 Chrome 窗口点击“重新加载”后再试。")
        return len(page.list_search_cards()) > 0

    page.wait_for(_cards_ready, timeout_seconds, 0.8, "淘宝闪购搜索结果暂时未加载出来，请稍后重试")


def _wait_for_shangou_detail_cdp(
    page: _ShangouCdpPage,
    result_url: str,
    card: dict[str, Any],
    index: int,
) -> dict[str, str] | None:
    previous_url = result_url

    def _detail_ready() -> str | None:
        current_url = page.current_url()
        if current_url != previous_url and "/newretail/p/ushop/" in current_url:
            return current_url
        return None

    try:
        detail_url = page.wait_for(_detail_ready, 12.0, 0.5, "打开淘宝闪购店铺详情失败，请重试")
    except BrowserSessionError:
        return None

    match = re.search(r"[?&](?:ele_id|shopId)=([^&]+)", detail_url)
    if not match:
        return None
    return {
        "shop_id": match.group(1),
        "name": str(card.get("name") or ""),
        "detail_url": detail_url,
        "index": str(index),
        "opened_detail": True,
    }


def _fetch_shangou_shop_phone_cdp(page: _ShangouCdpPage, shop_id: str) -> str | None:
    result = page.fetch_text(
        f"/restapi/giraffe/restaurant/phone?shopId={quote(str(shop_id))}",
        headers=_shangou_request_headers(shop_id=shop_id),
    )
    return _parse_shangou_phone_response(result)


def _parse_shangou_phone_response(result: dict[str, Any]) -> str | None:
    if int(result.get("status") or 0) != 200 or not str(result.get("text") or "").strip():
        return None
    raw_phone = str(result.get("text") or "").strip()
    try:
        decoded = json.loads(raw_phone)
    except json.JSONDecodeError:
        decoded = raw_phone
    if isinstance(decoded, dict):
        return _extract_mobile_phone(
            str(decoded.get("phone") or decoded.get("mobile") or decoded.get("data") or decoded.get("numbers") or "")
        )
    if isinstance(decoded, list):
        for item in decoded:
            if isinstance(item, dict):
                for candidate in item.get("numbers") or []:
                    phone = _extract_mobile_phone(str(candidate))
                    if phone:
                        return phone
                for key in ("phone", "mobile", "tel", "number"):
                    phone = _extract_mobile_phone(str(item.get(key) or ""))
                    if phone:
                        return phone
            else:
                phone = _extract_mobile_phone(str(item))
                if phone:
                    return phone
        return None
    return _extract_mobile_phone(str(decoded))


def _fetch_shangou_business_info_cdp(
    page: _ShangouCdpPage,
    city_name: str,
    fallback_name: str | None,
) -> dict[str, Any]:
    try:
        page.evaluate(
            """
            (() => {
              const node = Array.from(document.querySelectorAll("*")).find((item) => item.textContent?.trim() === "商家");
              if (node instanceof HTMLElement) {
                node.click();
                return true;
              }
              return false;
            })()
            """
        )
        time.sleep(1.0)
    except Exception:
        pass
    lines = [_normalize_line(line) for line in page.body_text(limit=16000).splitlines() if _normalize_line(line)]
    return {
        "name": fallback_name or _pick_shop_name(lines),
        "address": _pick_shangou_detail_address(lines, city_name),
        "longitude": None,
        "latitude": None,
        "raw": {"lines": lines[:120]},
    }


def _return_from_shangou_detail_cdp(page: _ShangouCdpPage, result_url: str) -> None:
    try:
        page.evaluate("history.back()")
        page.wait_for(
            lambda: page.current_url() if "minisearch/result" in page.current_url() else None,
            10.0,
            0.5,
            "返回淘宝闪购搜索结果页失败",
        )
        _ensure_shangou_search_cards_cdp(page, timeout_seconds=8.0, result_url=result_url)
    except BrowserSessionError:
        page.navigate(result_url, wait_seconds=1.2)
        _ensure_shangou_search_cards_cdp(page, result_url=result_url)


def _fetch_shangou_search_candidates_cdp(
    page: _ShangouCdpPage,
    region: dict[str, str],
    query: str,
    target_count: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    limit = 20
    max_pages = max(2, min(6, ((target_count * 4) // limit) + 1))
    for page_index in range(max_pages):
        result = page.fetch_text(
            f"/restapi/bgs/poi/search_poi_nearby?{urlencode({'latitude': region['latitude'], 'longitude': region['longitude'], 'keyword': query, 'offset': str(page_index * limit), 'limit': str(limit)})}",
            headers=_shangou_request_headers(longitude=region["longitude"], latitude=region["latitude"]),
        )
        if int(result.get("status") or 0) != 200:
            break
        try:
            payload = json.loads(str(result.get("text") or "[]"))
        except json.JSONDecodeError:
            break
        if not isinstance(payload, list) or not payload:
            break
        for item in payload:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "")
            if not item_id or item_id in seen_ids or not _matches_shangou_region(item, region):
                continue
            seen_ids.add(item_id)
            candidates.append(item)
        if len(payload) < limit:
            break
    return candidates


def _group_shangou_candidates_by_name(candidates: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        key = _normalize_shangou_name_key(str(item.get("name") or ""))
        if not key:
            continue
        buckets.setdefault(key, []).append(item)
    return buckets


def _match_shangou_candidate(
    buckets: dict[str, list[dict[str, Any]]],
    *names: str | None,
) -> dict[str, Any] | None:
    for name in names:
        key = _normalize_shangou_name_key(str(name or ""))
        if not key:
            continue
        candidates = buckets.get(key) or []
        if candidates:
            return candidates.pop(0)
    return None


def _shangou_has_logged_in_user_cdp(page: _ShangouCdpPage) -> bool:
    data = page.evaluate(
        """
        (async () => {
          const parseUser = (raw) => {
            if (!raw) return null;
            try {
              let parsed = JSON.parse(raw);
              if (typeof parsed === "string") parsed = JSON.parse(parsed);
              if (parsed && typeof parsed === "object" && parsed.data) return parsed.data;
              return parsed && typeof parsed === "object" ? parsed : null;
            } catch (error) {
              return null;
            }
          };
          const candidates = [
            parseUser(localStorage.getItem("TiGa-ELEME_USER_INFO")),
            parseUser(localStorage.getItem("TiGa-ELEME_UT_USER_INFO")),
          ].filter(Boolean);
          if (candidates.length === 0) {
            try {
              const response = await fetch("/restapi/eus/v2/current_user?info_raw={}", { credentials: "include" });
              const text = (await response.text()).trim();
              if (text) candidates.push({ user_id: text });
            } catch (error) {
              // ignore
            }
          }
          return candidates.map((item) => item.user_id || item.userId || null).filter(Boolean);
        })()
        """,
        await_promise=True,
    )
    if not isinstance(data, list):
        return False
    for item in data:
        digits = re.sub(r"\D+", "", str(item or ""))
        if digits and digits != "0":
            return True
    return False


def _shangou_has_risk_prompt_text(body_text: str) -> bool:
    return _shangou_has_transient_error_text(body_text) or _shangou_has_auth_prompt_text(body_text)


def _shangou_has_transient_error_text(body_text: str) -> bool:
    return any(marker in body_text for marker in ("哎呀出错了", "小宝正在检修中", "重新加载"))


def _shangou_has_auth_prompt_text(body_text: str) -> bool:
    return any(marker in body_text for marker in ("身份核实", "手机号快捷登录"))


def _normalize_shangou_name_key(value: str | None) -> str:
    text = _normalize_line(str(value or "")).replace("（", "(").replace("）", ")")
    return re.sub(r"\s+", "", text)


def _pick_shangou_detail_address(lines: list[str], city_name: str) -> str | None:
    strong_hint_re = re.compile(r"(路|街|道|大道|巷|里|号|楼|室|广场|大厦|商场|中心)")
    for line in lines:
        if not line or len(line) < 6:
            continue
        if any(token in line for token in ("月售", "配送费", "起送", "评分", "优惠", "活动", "营业")):
            continue
        if city_name and city_name not in line and not DISTRICT_HINT_RE.search(line):
            continue
        if strong_hint_re.search(line):
            return line
    return None


def _sanitize_shangou_address(
    name: str | None,
    address: str | None,
    city_name: str,
    district_name: str | None,
) -> str | None:
    candidate = _normalize_line(str(address or ""))
    if not candidate:
        return None
    if _normalize_shangou_name_key(candidate) == _normalize_shangou_name_key(name):
        return None
    strong_hint_re = re.compile(r"(路|街|道|大道|巷|里|号|楼|室|广场|大厦|商场|中心)")
    if strong_hint_re.search(candidate):
        return candidate
    if city_name and city_name in candidate:
        return candidate
    if district_name and district_name in candidate:
        return candidate
    return None


def _collect_douyin_shop_pois(city: str, category: str, keyword: str, target_count: int) -> list[dict[str, Any]]:
    query_parts = _clean_items([city, category, keyword])
    if not any(token in " ".join(query_parts) for token in ("团购", "代金券", "套餐", "优惠")):
        query_parts.append("团购")
    query = " ".join(query_parts)
    if not query:
        raise BrowserSessionError("抖音生活服务采集关键词不能为空")

    search_url = f"https://www.douyin.com/search/{quote(query)}?type=general"
    with sync_playwright() as playwright:
        context = _launch_persistent_context(playwright, "douyin", _profile_dir("douyin"), headless=False, snapshot=True)
        page = context.new_page()
        page.goto(search_url, wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
        page.wait_for_timeout(4000)
        _wait_for_platform_results(page, "douyin")
        _scroll_page(page, rounds=4)
        records = _extract_douyin_search_cards(page, city, category, keyword, target_count)
        _close_browser_context(context)
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
        address = _pick_address(lines, city)
        district = _pick_district(lines, city)

        if _looks_like_dianping_deal_name(name):
            detail_name, detail_address, detail_district = _extract_dianping_shop_detail(page, detail_url)
            name = detail_name or name
            address = detail_address or address
            district = detail_district or district

        if not name or name in seen_names:
            continue
        seen_names.add(name)

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


def _extract_dianping_shop_detail(page: Page, detail_url: str) -> tuple[str | None, str | None, str | None]:
    detail_page = page.context.new_page()
    try:
        detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
        detail_page.wait_for_timeout(2500)
        title = detail_page.title()
        body_text = detail_page.locator("body").inner_text(timeout=5000)
        lines = [_normalize_line(line) for line in body_text.splitlines() if _normalize_line(line)]

        detail_name = _extract_dianping_name_from_title(title)
        if not detail_name:
            detail_name = _pick_dianping_detail_name(lines)
        detail_address = _pick_dianping_detail_address(lines)
        detail_district = _pick_district(lines, "")
        return detail_name, detail_address, detail_district
    except Exception:
        return None, None, None
    finally:
        detail_page.close()


def _extract_douyin_search_cards(
    page: Page,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    cards = page.locator(".search-result-card")
    seen_names: set[str] = set()
    records: list[dict[str, Any]] = []
    max_scan = min(cards.count(), max(target_count * 8, 24))
    for index in range(max_scan):
        card = cards.nth(index)
        text = card.inner_text(timeout=1000).strip()
        lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
        if not lines or lines[0] == "相关搜索":
            continue

        name, candidates = _pick_douyin_merchant_name(lines, city, category, keyword)
        if not name or name in seen_names:
            continue
        seen_names.add(name)

        records.append(
            {
                "id": md5(f"douyin:{city}:{category}:{keyword}:{name}:{index}".encode("utf-8")).hexdigest(),
                "name": name,
                "cityname": city,
                "adname": None,
                "pname": None,
                "address": None,
                "tel": None,
                "location": None,
                "type": category or keyword or "抖音生活服务",
                "detail_url": page.url,
                "_raw_provider": "douyin",
                "_raw_payload": {
                    "provider": "douyin",
                    "query_city": city,
                    "query_category": category,
                    "query_keyword": keyword,
                    "source_url": page.url,
                    "list_text": lines,
                    "candidate_names": candidates,
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


def _launch_persistent_context(playwright: Any, provider: str, profile_dir: Path, headless: bool, snapshot: bool = False):
    meta = BROWSER_PLATFORM_METADATA[provider]
    viewport_mode = meta.get("viewport_mode", "mobile")
    is_mobile = viewport_mode == "mobile"
    launch_profile_dir, snapshot_dir = _prepare_launch_profile_dir(provider, profile_dir, snapshot=snapshot)
    launch_options: dict[str, Any] = {
        "headless": headless,
        "locale": "zh-CN",
        "timezone_id": "Asia/Shanghai",
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    if is_mobile:
        launch_options.update(
            {
                "user_agent": MOBILE_USER_AGENT,
                "viewport": {"width": 430, "height": 932},
                "is_mobile": True,
                "has_touch": True,
            }
        )
    else:
        launch_options.update(
            {
                "user_agent": DESKTOP_USER_AGENT,
                "viewport": {"width": 1440, "height": 960},
            }
        )

    context = playwright.chromium.launch_persistent_context(str(launch_profile_dir), **launch_options)
    context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = window.chrome || { runtime: {} };
        """
    )
    setattr(context, "_ai_acq_snapshot_dir", snapshot_dir)
    return context


def _prepare_launch_profile_dir(provider: str, profile_dir: Path, snapshot: bool) -> tuple[Path, Path | None]:
    if not snapshot:
        return profile_dir, None
    snapshot_root = Path(tempfile.mkdtemp(prefix=f"ai-acq-{provider}-", dir=str(_profile_root())))
    snapshot_dir = snapshot_root / "profile"
    _copy_profile_tree_best_effort(profile_dir, snapshot_dir)
    for lock_name in ("SingletonLock", "SingletonSocket", "SingletonCookie", "DevToolsActivePort"):
        lock_file = snapshot_dir / lock_name
        if lock_file.exists():
            lock_file.unlink()
    return snapshot_dir, snapshot_root


def _close_browser_context(context: Any) -> None:
    snapshot_dir = getattr(context, "_ai_acq_snapshot_dir", None)
    try:
        context.close()
    finally:
        if snapshot_dir:
            shutil.rmtree(snapshot_dir, ignore_errors=True)


def _connect_shangou_browser(playwright: Any) -> tuple[Any, Any, Page, bool]:
    try:
        browser = playwright.chromium.connect_over_cdp(SHANGOU_REMOTE_DEBUGGING_ENDPOINT)
    except Exception as exc:
        raise BrowserSessionError("未检测到淘宝闪购专用 Chrome 窗口，请先点击“打开登录窗口”，并在该窗口完成登录。") from exc

    if not browser.contexts:
        raise BrowserSessionError("淘宝闪购专用 Chrome 尚未准备好，请重新打开登录窗口后再试。")

    context = browser.contexts[0]
    if context.pages:
        return browser, context, context.pages[0], False
    return browser, context, context.new_page(), True


def _release_connected_page(page: Page, page_created: bool) -> None:
    if not page_created:
        return
    try:
        page.close()
    except Exception:
        pass


def _copy_profile_tree_best_effort(source_dir: Path, target_dir: Path) -> None:
    ignored_names = {
        "SingletonLock",
        "SingletonSocket",
        "SingletonCookie",
        "DevToolsActivePort",
        "RunningChromeVersion",
        "Crashpad",
        "Crash Reports",
        "Code Cache",
        "GPUCache",
        "GrShaderCache",
        "DawnGraphiteCache",
        "GraphiteDawnCache",
    }
    target_dir.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        relative_root = root_path.relative_to(source_dir)
        destination_root = target_dir / relative_root
        destination_root.mkdir(parents=True, exist_ok=True)
        dirs[:] = [directory for directory in dirs if directory not in ignored_names]
        for filename in files:
            if filename in ignored_names:
                continue
            source_file = root_path / filename
            destination_file = destination_root / filename
            try:
                if source_file.is_symlink():
                    continue
                shutil.copy2(source_file, destination_file)
            except FileNotFoundError:
                continue
            except PermissionError:
                continue


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

    invalid_markers = {
        "meituan": (
            "手机号快捷登录",
            "发送验证码",
            "身份核实",
            "用最短线连接验证",
            "APP扫码，享七天免登录",
        ),
        "shangou": (
            "手机号快捷登录",
            "发送验证码",
            "身份核实",
            "用最短线连接验证",
            "APP扫码，享七天免登录",
        ),
        "douyin": (
            "验证码中间页",
            "验证中心",
            "手机验证码登录",
            "请完成下列验证后继续",
        ),
    }.get(provider, ())
    if any(marker in title or marker in body_text for marker in invalid_markers):
        raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 已退出登录或触发校验，请重新登录。")
    page_html = page.content()
    if provider == "shangou":
        if "h5.ele.me/login" in url or title.strip() == "饿了么-登录":
            raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 尚未完成 H5 登录，请重新登录。")
        if not _shangou_has_logged_in_user(page):
            raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 当前未检测到已登录账号，请重新登录。")
    if "verify.meituan.com" in url or "/mlogin/" in url or "captcha" in url.lower():
        raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 已退出登录或触发校验，请重新登录。")
    if "verifycenter/captcha" in page_html or "captcha_container" in page_html:
        raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 已退出登录或触发校验，请重新登录。")


def _shangou_has_logged_in_user(page: Page) -> bool:
    data = page.evaluate(
        """
        async () => {
          const parseUser = (raw) => {
            if (!raw) return null;
            try {
              let parsed = JSON.parse(raw);
              if (typeof parsed === "string") {
                parsed = JSON.parse(parsed);
              }
              if (parsed && typeof parsed === "object" && parsed.data) {
                return parsed.data;
              }
              return parsed && typeof parsed === "object" ? parsed : null;
            } catch (error) {
              return null;
            }
          };
          const candidates = [
            parseUser(localStorage.getItem("TiGa-ELEME_USER_INFO")),
            parseUser(localStorage.getItem("TiGa-ELEME_UT_USER_INFO")),
          ].filter(Boolean);
          if (candidates.length === 0) {
            try {
              const response = await fetch("/restapi/eus/v2/current_user?info_raw={}", {
                credentials: "include",
              });
              const text = (await response.text()).trim();
              if (text) {
                candidates.push({ user_id: text });
              }
            } catch (error) {
              // ignore
            }
          }
          return candidates.map((item) => item.user_id || item.userId || null).filter(Boolean);
        }
        """
    )
    if not isinstance(data, list):
        return False
    for item in data:
        digits = re.sub(r"\D+", "", str(item or ""))
        if digits and digits != "0":
            return True
    return False


def _scroll_page(page: Page, rounds: int) -> None:
    for _ in range(rounds):
        page.mouse.wheel(0, 2400)
        page.wait_for_timeout(1200)


def _wait_for_platform_results(page: Page, provider: str, timeout_ms: int = 60000) -> None:
    started = datetime.utcnow()
    result_selectors = {
        "meituan": "a[href*='/shop/']",
        "douyin": ".search-result-card",
    }
    result_selector = result_selectors.get(provider)
    if not result_selector:
        _ensure_page_authenticated(page, provider)
        return

    last_error: str | None = None
    while (datetime.utcnow() - started).total_seconds() * 1000 < timeout_ms:
        try:
            _ensure_page_authenticated(page, provider)
        except BrowserSessionError as exc:
            last_error = str(exc)
            if _platform_captcha_active(page, provider):
                page.wait_for_timeout(2000)
                continue
            raise

        try:
            if page.locator(result_selector).count() > 0:
                return
        except Exception:
            pass

        page.wait_for_timeout(2000)

    if _platform_captcha_active(page, provider):
        raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 触发滑块验证，请在弹出的浏览器窗口完成验证后重试。")
    if last_error:
        raise BrowserSessionError(last_error)
    raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 当前未拿到搜索结果，请稍后重试。")


def _platform_captcha_active(page: Page, provider: str) -> bool:
    url = page.url.lower()
    html = page.content().lower()
    if provider == "meituan":
        return "verify.meituan.com" in url or "spiderindefence" in url
    if provider == "douyin":
        return "verifycenter/captcha" in html or "captcha_container" in html
    return "captcha" in url or "captcha" in html


def _search_in_page(page: Page, query: str, provider: str) -> None:
    input_selectors = [
        "input[type='search']",
        "input[placeholder*='搜索']",
        "input[placeholder*='商品']",
        "input[placeholder*='商家']",
        "textarea[placeholder*='搜索']",
    ]
    for selector in input_selectors:
        locator = page.locator(selector)
        try:
            if locator.count() == 0:
                continue
            target = locator.first
            target.click(timeout=2000)
            target.fill(query, timeout=3000)
            target.press("Enter", timeout=2000)
            page.wait_for_timeout(3000)
            return
        except Exception:
            continue
    if provider == "shangou":
        candidate_urls = [
            f"https://i.meituan.com/awp/hfe/h5/search/search.html?keyword={quote(query)}",
            f"https://i.meituan.com/awp/hfe/h5/search/global.html?keyword={quote(query)}",
        ]
        for url in candidate_urls:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
                page.wait_for_timeout(3000)
                return
            except Exception:
                continue
    raise BrowserSessionError(f"{BROWSER_PLATFORM_METADATA[provider]['name']} 当前页面未找到可用搜索框，请先手动确认登录后再试。")


def _looks_like_dianping_deal_name(name: str | None) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    return any(token in text for token in ("代金券", "双人餐", "人餐", "套餐", "可叠加", "工作餐", "抢购"))


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


def _extract_dianping_name_from_title(title: str | None) -> str | None:
    if not title:
        return None
    match = DIANPING_TITLE_NAME_RE.search(title)
    if not match:
        return None
    return _normalize_line(match.group("name"))


def _pick_dianping_detail_name(lines: list[str]) -> str | None:
    for line in lines:
        if not line or len(line) < 2:
            continue
        if any(token in line for token in ("打开App", "输入商户名", "代金券", "团购套餐", "推荐菜", "小伙伴们还喜欢")):
            continue
        if "★" in line or "¥" in line or "条" in line:
            continue
        if any(token in line for token in ("营业中", "到店", "买券", "抢购", "查看更多", "大众点评")):
            continue
        return line
    return None


def _pick_dianping_detail_address(lines: list[str]) -> str | None:
    for line in lines:
        if ADDRESS_HINT_RE.search(line) and not any(token in line for token in ("打开App", "大众点评", "电脑版")):
            return line
    return None


def _extract_generic_shop_cards(
    page: Page,
    provider: str,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
    href_patterns: tuple[str, ...],
    host_tokens: tuple[str, ...],
) -> list[dict[str, Any]]:
    anchors = page.locator("a[href]")
    seen_ids: set[str] = set()
    records: list[dict[str, Any]] = []
    max_scan = min(anchors.count(), max(target_count * 10, 60))
    for index in range(max_scan):
        anchor = anchors.nth(index)
        href = anchor.get_attribute("href")
        if not href:
            continue
        href = href.strip()
        normalized_href = href.lower()
        if not any(token in normalized_href for token in href_patterns):
            continue
        if not any(token in normalized_href for token in host_tokens):
            continue
        detail_url = href if href.startswith(("http://", "https://")) else urljoin(page.url, href)
        text = anchor.inner_text(timeout=1000).strip()
        lines = [_normalize_line(line) for line in text.splitlines() if _normalize_line(line)]
        name = _pick_shop_name(lines)
        if not name:
            continue
        shop_id = _extract_shop_id(detail_url, detail_url)
        if shop_id in seen_ids:
            continue
        seen_ids.add(shop_id)
        address = _pick_address(lines, city)
        district = _pick_district(lines, city)
        records.append(
            {
                "id": shop_id,
                "name": name,
                "cityname": city,
                "adname": district,
                "pname": None,
                "address": address,
                "tel": None,
                "location": None,
                "type": category or keyword or provider,
                "detail_url": detail_url,
                "_raw_provider": provider,
                "_raw_payload": {
                    "provider": provider,
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


def _pick_douyin_merchant_name(
    lines: list[str],
    city: str,
    category: str,
    keyword: str,
) -> tuple[str | None, list[str]]:
    content_lines = [
        line
        for line in lines
        if line
        and not line.startswith("@")
        and line not in {"图文", "相关搜索", "问问AI"}
        and not DOUYIN_DURATION_RE.fullmatch(line)
        and not DOUYIN_COUNT_RE.fullmatch(line)
        and line != "·"
        and not DOUYIN_DATE_RE.fullmatch(line)
    ]
    content = " ".join(content_lines)
    hashtags = [_normalize_douyin_candidate(tag) for tag in DOUYIN_HASHTAG_RE.findall(content)]
    hashtag_candidates = [tag for tag in hashtags if _is_valid_douyin_merchant_candidate(tag, city, category, keyword)]
    preferred = [tag for tag in hashtag_candidates if any(hint in tag for hint in DOUYIN_MERCHANT_HINTS)]
    if preferred:
        return preferred[0], hashtag_candidates

    phrase_candidates: list[str] = []
    for match in re.finditer(r"([A-Za-z0-9\u4e00-\u9fff·()（）]{2,30})", content):
        candidate = _normalize_douyin_candidate(match.group(1))
        if _is_valid_douyin_merchant_candidate(candidate, city, category, keyword):
            phrase_candidates.append(candidate)
    preferred_phrases = [item for item in phrase_candidates if any(hint in item for hint in DOUYIN_MERCHANT_HINTS)]
    if preferred_phrases:
        return preferred_phrases[0], phrase_candidates
    return None, []


def _normalize_douyin_candidate(value: str) -> str:
    return _normalize_line(value).strip("!！?？,，。.;；:：·")


def _is_valid_douyin_merchant_candidate(candidate: str, city: str, category: str, keyword: str) -> bool:
    if not candidate or len(candidate) < 2 or len(candidate) > 30:
        return False
    if candidate in DOUYIN_GENERIC_TAGS:
        return False
    if candidate.startswith(("南昌", "江西")) and candidate.endswith(("美食", "火锅", "探店")):
        return False
    lowered = candidate.lower()
    if lowered in {"vlog", "图文"}:
        return False
    if candidate in DOUYIN_LOCATION_WORDS:
        return False
    if any(token in candidate for token in ("吃喝玩乐", "年度爱吃", *DOUYIN_GENERIC_CANDIDATE_TOKENS)):
        return False
    if candidate in {city, category, keyword}:
        return False
    if candidate.endswith(("代金券", "套餐", "优惠", "团购")) and len(candidate) <= 8:
        return False
    return True


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
