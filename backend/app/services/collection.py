from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from hashlib import md5
from math import ceil
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.collection import LeadCollectionRun, LeadCollectionTask, LeadProviderConfig, RawLeadRecord
from app.models.lead import MerchantLead
from app.services.platform_browser import (
    BrowserSessionError,
    browser_managed_providers,
    collect_browser_platform_pois,
)


class CollectionError(ValueError):
    pass


class CollectionValidationError(CollectionError):
    pass


@dataclass(frozen=True)
class LeadImportResult:
    lead: MerchantLead | None
    import_status: str
    phone: str | None = None


@dataclass(frozen=True)
class EnrichmentSeed:
    lead_id: str
    city: str
    category: str
    keyword: str


BLACKLIST_STATUSES = {"已勿扰", "黑名单", "黑名单拦截", "无效号码"}
INVALID_PHONE_TEXT = {"", "-", "无", "暂无", "未提供", "空号", "无效", "未知", "null", "none"}
PHONE_SPLIT_RE = re.compile(r"[|;/,，、\s]+")
NON_DIGIT_RE = re.compile(r"\D+")
HTML_TAG_RE = re.compile(r"<[^>]+>")
TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
META_CONTENT_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?P<key>[^"\']+)["\'][^>]+content=["\'](?P<content>[^"\']+)["\']',
    re.IGNORECASE,
)
JSON_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(?P<body>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
PHONE_TEXT_RE = re.compile(r"(?:1[3-9]\d{9}|400[- ]?\d{3}[- ]?\d{4}|800[- ]?\d{3}[- ]?\d{4}|0\d{2,3}[- ]?\d{7,8})")

MAP_PROVIDERS = {"amap", "baidu", "tencent"}
PLATFORM_PROVIDERS = {"meituan", "shangou", "douyin"}
PUBLIC_PROVIDERS = {"public_web"}
PROVIDER_SOURCE_LABELS = {
    "amap": "地图点位采集",
    "baidu": "地图点位采集",
    "tencent": "地图点位采集",
    "meituan": "平台页面采集",
    "shangou": "平台页面采集",
    "douyin": "平台页面采集",
    "public_web": "公开网页采集",
}
PLATFORM_PROVIDER_METADATA = {
    "meituan": {
        "label": "美团团购",
        "search_terms": ("美团", "团购"),
        "allowed_hosts": ("dianping.com", "meituan.com"),
    },
    "shangou": {
        "label": "淘宝闪购",
        "search_terms": ("淘宝", "闪购"),
        "allowed_hosts": ("taobao.com", "tb.cn", "ele.me"),
    },
    "douyin": {
        "label": "抖音生活服务",
        "search_terms": ("抖音", "团购"),
        "allowed_hosts": ("douyin.com", "life.douyin.com"),
    },
}
BROWSER_PLATFORM_PROVIDERS = browser_managed_providers()
COLLECTION_MODE_DISCOVERY = "discovery"
COLLECTION_MODE_ENRICH = "enrich"
COLLECTION_ACTIVE_STATUSES = {"排队中", "运行中"}
COLLECTION_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-acq-collection")
PUBLIC_SEARCH_EXCLUDED_HOSTS = (
    "sogou.com",
    "bing.com",
    "microsoft.com",
    "baidu.com",
    "amap.com",
    "weibo.com",
    "zhihu.com",
    "douyin.com",
)
PUBLIC_SEARCH_BAD_URL_TOKENS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".svg",
    ".css",
    ".js",
    "javascript:",
    "mailto:",
)


def _clean_items(values: list[str]) -> list[str]:
    return [value.strip() for value in values if value and value.strip()]


def _normalize_text(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "").strip()).lower()


def _normalize_phone_item(value: str | None) -> str | None:
    if not value:
        return None

    candidate = str(value).strip()
    if candidate.lower() in INVALID_PHONE_TEXT:
        return None

    # 去掉分机号、括号、空格等展示字符，统一保存为可比对的号码。
    candidate = re.split(r"(转|分机|ext\.?|extension)", candidate, maxsplit=1, flags=re.IGNORECASE)[0]
    digits = NON_DIGIT_RE.sub("", candidate)
    if digits.startswith("86") and len(digits) > 11:
        digits = digits[2:]

    if re.fullmatch(r"1[3-9]\d{9}", digits):
        return digits
    if re.fullmatch(r"400\d{7}|800\d{7}", digits):
        return f"{digits[:3]}-{digits[3:]}"
    if re.fullmatch(r"0\d{9,11}", digits):
        three_digit_area_codes = {"010", "020", "021", "022", "023", "024", "025", "027", "028", "029"}
        area_code_length = 3 if digits[:3] in three_digit_area_codes else 4
        return f"{digits[:area_code_length]}-{digits[area_code_length:]}"
    if re.fullmatch(r"\d{7,8}", digits):
        return digits
    return None


def _first_valid_phone(value: str | None) -> str | None:
    if not value:
        return None
    single_phone = _normalize_phone_item(value)
    if single_phone:
        return single_phone
    for item in PHONE_SPLIT_RE.split(str(value)):
        phone = _normalize_phone_item(item)
        if phone:
            return phone
    return None


def _extract_homepage_url(poi: dict[str, Any]) -> str | None:
    for key in ("platform_homepage_url", "homepage", "detail_url", "source_url", "url", "website"):
        value = str(poi.get(key) or "").strip()
        if value.startswith(("http://", "https://")):
            return value

    for nested_key in ("detail_info", "biz_ext", "_raw_payload"):
        nested = poi.get(nested_key)
        if not isinstance(nested, dict):
            continue
        for key in ("platform_homepage_url", "homepage", "detail_url", "source_url", "url", "website"):
            value = str(nested.get(key) or "").strip()
            if value.startswith(("http://", "https://")):
                return value
    return None


def _normalize_homepage_url(
    value: str | None,
    *,
    fallback_poi_id: str | None = None,
    max_length: int = 500,
) -> str | None:
    url = str(value or "").strip()
    if not url.startswith(("http://", "https://")):
        return None

    parts = urlsplit(url)
    normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
    if len(normalized) <= max_length:
        return normalized

    if parts.query:
        normalized = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        if fallback_poi_id:
            poi_hint = f"poi_id={quote(fallback_poi_id)}"
            connector = "&" if "?" in normalized else "?"
            candidate = f"{normalized}{connector}{poi_hint}"
            if len(candidate) <= max_length:
                return candidate

    if len(normalized) > max_length:
        normalized = normalized[:max_length].rstrip("?&")
    return normalized or None


def _safe_error_text(exc: Exception, max_length: int = 240) -> str:
    message = str(getattr(exc, "orig", exc) or exc).strip() or "未知错误"
    if len(message) <= max_length:
        return message
    return f"{message[:max_length].rstrip()}..."


def _is_blacklisted_lead(lead: MerchantLead) -> bool:
    status_text = " ".join(
        str(value or "")
        for value in (
            lead.status,
            lead.follow_up_status,
            lead.remark,
        )
    )
    return any(label in status_text for label in BLACKLIST_STATUSES)


def _split_location(location: str | None) -> tuple[str | None, str | None]:
    if not location or "," not in location:
        return None, None
    longitude, latitude = location.split(",", 1)
    return longitude.strip() or None, latitude.strip() or None


def _build_location(longitude: Any, latitude: Any) -> str | None:
    if longitude in (None, "") or latitude in (None, ""):
        return None
    return f"{longitude},{latitude}"


def _score_lead(record: dict[str, Any], city: str, category: str, keyword: str) -> int:
    score = 45
    if _first_valid_phone(record.get("tel")):
        score += 22
    if record.get("address"):
        score += 10
    if record.get("location"):
        score += 8
    type_text = str(record.get("type") or "")
    name = str(record.get("name") or "")
    if category and (category in type_text or category in name):
        score += 10
    if keyword and keyword in name:
        score += 5
    if city and city in str(record.get("cityname") or ""):
        score += 5
    return max(0, min(score, 100))


def _provider_label(provider: str) -> str:
    if provider in PLATFORM_PROVIDER_METADATA:
        return str(PLATFORM_PROVIDER_METADATA[provider]["label"])
    labels = {
        "amap": "高德地图",
        "baidu": "百度地图",
        "tencent": "腾讯位置服务",
        "public_web": "公开网页",
    }
    return labels.get(provider, provider)


def default_collection_mode(provider: str) -> str:
    return COLLECTION_MODE_ENRICH if provider in PLATFORM_PROVIDERS else COLLECTION_MODE_DISCOVERY


def normalize_collection_mode(provider: str, mode: str | None) -> str:
    normalized = str(mode or "").strip().lower()
    if normalized not in {COLLECTION_MODE_DISCOVERY, COLLECTION_MODE_ENRICH}:
        normalized = default_collection_mode(provider)
    if normalized == COLLECTION_MODE_ENRICH and provider not in PLATFORM_PROVIDERS:
        return COLLECTION_MODE_DISCOVERY
    return normalized


def _collection_mode_label(mode: str) -> str:
    return "平台补充" if mode == COLLECTION_MODE_ENRICH else "拓源采集"


def _collection_source_label(provider: str, collection_mode: str) -> str:
    if collection_mode == COLLECTION_MODE_ENRICH and provider in PLATFORM_PROVIDERS:
        return f"{_provider_label(provider)}补充采集"
    return PROVIDER_SOURCE_LABELS.get(provider, "公开来源采集")


def _is_active_collection_status(status: str | None) -> bool:
    return str(status or "").strip() in COLLECTION_ACTIVE_STATUSES


def _request_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": settings.collection_http_user_agent})
    with urlopen(request, timeout=settings.collection_request_timeout_seconds) as response:
        return response.read().decode("utf-8", errors="ignore")


def _read_provider_service_url(db: Session, provider: str, fallback: str) -> str:
    config = _read_provider_config(db, provider)
    if config and not config.enabled:
        raise CollectionError(f"{config.name} 已停用，请先在后台「采集接口配置」启用。")
    return (config.service_url if config and config.service_url else fallback).strip()


def _strip_html_tags(value: str | None) -> str:
    text = HTML_TAG_RE.sub(" ", str(value or ""))
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _extract_meta_content(html: str, keys: tuple[str, ...]) -> str | None:
    normalized_keys = {key.lower() for key in keys}
    for match in META_CONTENT_RE.finditer(html):
        if match.group("key").lower() in normalized_keys:
            value = _strip_html_tags(match.group("content"))
            if value:
                return value
    return None


def _extract_title(html: str) -> str | None:
    match = TITLE_RE.search(html)
    if not match:
        return None
    return _strip_html_tags(match.group(1))


def _candidate_json_nodes(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict):
        nodes = [raw]
        for value in raw.values():
            nodes.extend(_candidate_json_nodes(value))
        return nodes
    if isinstance(raw, list):
        nodes: list[dict[str, Any]] = []
        for item in raw:
            nodes.extend(_candidate_json_nodes(item))
        return nodes
    return []


def _extract_json_ld_nodes(html: str) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    for match in JSON_SCRIPT_RE.finditer(html):
        try:
            payload = json.loads(match.group("body"))
        except json.JSONDecodeError:
            continue
        nodes.extend(_candidate_json_nodes(payload))
    return nodes


def _clean_candidate_name(value: str | None) -> str | None:
    text = _strip_html_tags(value)
    if not text:
        return None
    for token in (" - 抖音", " - 美团", "_美团网", "_抖音", "| 抖音", "| 美团"):
        if token in text:
            text = text.split(token, 1)[0].strip()
    return text or None


def _extract_platform_name(html: str) -> str | None:
    for key_group in (
        ("og:title", "twitter:title"),
        ("title",),
    ):
        value = _extract_meta_content(html, key_group)
        cleaned = _clean_candidate_name(value)
        if cleaned:
            return cleaned
    return _clean_candidate_name(_extract_title(html))


def _extract_platform_phone(html: str) -> str | None:
    for node in _extract_json_ld_nodes(html):
        phone = _first_valid_phone(node.get("telephone") or node.get("tel") or node.get("phone"))
        if phone:
            return phone
    match = PHONE_TEXT_RE.search(html)
    if not match:
        return None
    return _first_valid_phone(match.group(0))


def _extract_platform_address(html: str) -> str | None:
    for node in _extract_json_ld_nodes(html):
        address = node.get("address")
        if isinstance(address, dict):
            text = " ".join(
                _strip_html_tags(address.get(key))
                for key in ("streetAddress", "addressLocality", "addressRegion", "addressCountry")
            ).strip()
            if text:
                return text
        text = _strip_html_tags(address)
        if text:
            return text
    for pattern in (
        r'"address"\s*:\s*"([^"]+)"',
        r'"addressName"\s*:\s*"([^"]+)"',
        r'"poi_address"\s*:\s*"([^"]+)"',
    ):
        match = re.search(pattern, html)
        if match:
            text = _strip_html_tags(match.group(1))
            if text:
                return text
    return None


def _extract_platform_page_id(provider: str, url: str, html: str) -> str:
    path = urlsplit(url).path
    match = re.search(r"/(video|note|poi|shop|deal|goods)/([A-Za-z0-9_-]{6,})", path)
    if match:
        return match.group(2)
    numeric = re.search(r"(\d{8,})", url)
    if numeric:
        return numeric.group(1)
    embedded = re.search(r'"(?:shop|poi|store|detail)_?id"\s*:\s*"?(?P<id>[A-Za-z0-9_-]{6,})"?', html)
    if embedded:
        return embedded.group("id")
    return md5(f"{provider}:{url}".encode("utf-8")).hexdigest()


def _build_platform_search_queries(provider: str, city: str, category: str, keyword: str) -> list[str]:
    meta = PLATFORM_PROVIDER_METADATA[provider]
    parts = _clean_items([city, category, keyword, *meta["search_terms"]])
    queries = [" ".join(parts)]
    if keyword:
        queries.append(" ".join(_clean_items([city, keyword, *meta["search_terms"]])))
    if category:
        queries.append(" ".join(_clean_items([city, category, *meta["search_terms"]])))
    for host in meta["allowed_hosts"]:
        queries.append(" ".join(_clean_items([city, category, keyword, *meta["search_terms"], f"site:{host}"])))
    return [query for query in queries if query]


def _discover_platform_urls(provider: str, query: str, limit: int, search_base_url: str) -> list[str]:
    allowed_hosts = tuple(PLATFORM_PROVIDER_METADATA[provider]["allowed_hosts"])
    urls: list[str] = []
    search_urls = [
        f"https://cn.bing.com/search?{urlencode({'q': query})}",
        f"https://www.bing.com/search?{urlencode({'q': query})}",
    ]
    if search_base_url and "bing.com" not in search_base_url:
        search_param = "q" if "bing." in search_base_url else "query"
        search_urls.append(f"{search_base_url}?{urlencode({search_param: query})}")

    for search_url in search_urls:
        try:
            html = _request_text(search_url)
        except Exception:
            continue
        for candidate in _extract_href_candidates(html, search_url):
            host = urlsplit(candidate).netloc.lower()
            if not any(host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts):
                continue
            if any(token in candidate for token in ("jpg", "jpeg", "png", "gif", "webp", "mtptimg", "pic.sogou.com")):
                continue
            if candidate.endswith("..."):
                continue
            if candidate not in urls:
                urls.append(candidate)
            if len(urls) >= limit:
                return urls
    return urls


def _unwrap_search_url(raw_url: str, base_url: str) -> str | None:
    value = unescape(str(raw_url or "")).strip()
    if not value:
        return None
    if value.startswith("//"):
        value = f"https:{value}"
    if value.startswith("/"):
        value = urljoin(base_url, value)
    parsed = urlsplit(value)
    if parsed.netloc.endswith("sogou.com") or parsed.netloc.endswith("bing.com"):
        query = parse_qs(parsed.query)
        for key in ("url", "u", "target", "to"):
            target = query.get(key, [""])[0]
            if target.startswith(("http://", "https://")):
                return unquote(target)
    return value if value.startswith(("http://", "https://")) else None


def _is_public_web_candidate(url: str) -> bool:
    lowered = url.lower()
    if any(token in lowered for token in PUBLIC_SEARCH_BAD_URL_TOKENS):
        return False
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    if not host:
        return False
    if any(host == excluded or host.endswith(f".{excluded}") for excluded in PUBLIC_SEARCH_EXCLUDED_HOSTS):
        return False
    if "verify" in host or "captcha" in lowered or "login" in lowered:
        return False
    return True


def _extract_href_candidates(html: str, base_url: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r'href=["\'](?P<href>[^"\']+)["\']', html, flags=re.IGNORECASE):
        candidate = _unwrap_search_url(match.group("href"), base_url)
        if not candidate or not _is_public_web_candidate(candidate):
            continue
        if candidate not in urls:
            urls.append(candidate)
    return urls


def _discover_public_web_urls(query: str, limit: int) -> list[str]:
    urls: list[str] = []
    search_urls = [
        f"https://www.sogou.com/web?{urlencode({'query': query})}",
        f"https://cn.bing.com/search?{urlencode({'q': query})}",
    ]
    for search_url in search_urls:
        try:
            html = _request_text(search_url)
        except Exception:
            continue
        for candidate in _extract_href_candidates(html, search_url):
            if candidate not in urls:
                urls.append(candidate)
            if len(urls) >= limit:
                return urls
    return urls


def _visible_text(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = _strip_html_tags(text)
    return re.sub(r"\s+", " ", unescape(text)).strip()


def _extract_label_value(text: str, label: str, max_chars: int = 100) -> str | None:
    match = re.search(rf"{label}\s*[:：]\s*(?P<value>.{{2,{max_chars}}})", text)
    if not match:
        return None
    value = re.split(r"(电话|联系电话|手机|地址|【|团购内容|查看|更多|上一篇|下一篇)", match.group("value"), maxsplit=1)[0]
    value = value.strip(" ：:-_，,。;；|")
    return value or None


def _extract_public_business_phone(html: str) -> str | None:
    text = _visible_text(html)
    fixed_phone = re.search(r"(?<!\d)(?:0\d{2,3}[-\s]?\d{7,8}|400[-\s]?\d{3}[-\s]?\d{4}|800[-\s]?\d{3}[-\s]?\d{4})(?!\d)", text)
    if fixed_phone:
        return _normalize_phone_item(fixed_phone.group(0))

    for match in re.finditer(r"(?<!\d)1[3-9]\d{9}(?!\d)", text):
        context = text[max(0, match.start() - 80) : match.end() + 80]
        if re.search(r"(电话|联系电话|联系|手机|商家|门店|餐厅|饭店|店铺|订餐|咨询)", context):
            return _normalize_phone_item(match.group(0))
    return None


def _extract_public_web_name(html: str, url: str, city: str, category: str) -> str | None:
    text = _visible_text(html)
    title = _extract_title(html) or urlsplit(url).netloc
    title = re.split(r"[-_|—]", title, maxsplit=1)[0]
    for token in (city, category, "南昌", "本地宝", "电话邦", "电话查询", "58同城", "商家电话", "团购"):
        title = title.replace(token, "")
    title = title.strip(" ：:-_，,。;；|")
    generic_names = {"联系我们", "联系我", "关于我们", "电话邦", "mp.weixin.qq.com", urlsplit(url).netloc}
    if len(title) >= 2 and title not in generic_names:
        cleaned_title = _clean_candidate_name(title)
        if cleaned_title and cleaned_title not in generic_names:
            return cleaned_title

    for label in ("原标题", "商家名称", "店名", "名称"):
        value = _extract_label_value(text, label, 80)
        cleaned_value = _clean_candidate_name(value)
        if cleaned_value and cleaned_value not in generic_names:
            return cleaned_value
    return None


def _extract_public_web_address(html: str) -> str | None:
    text = _visible_text(html)
    value = _extract_label_value(text, "地址", 120)
    if value:
        return value
    return _extract_platform_address(html)


def _extract_public_web_record(url: str, html: str, city: str, category: str, keyword: str) -> dict[str, Any] | None:
    if any(marker in html for marker in ("请输入验证码", "访问过于频繁", "安全验证", "登录后查看")):
        return None
    text = _visible_text(html)
    relevance_terms = _clean_items([city, category, keyword, "美食", "餐厅", "饭店", "酒家", "火锅", "团购", "订餐"])
    if not any(term in text for term in relevance_terms):
        return None
    phone = _extract_public_business_phone(html)
    if not phone:
        return None
    name = _extract_public_web_name(html, url, city, category)
    if not name:
        return None
    return {
        "id": md5(f"public_web:{url}".encode("utf-8")).hexdigest(),
        "name": name,
        "cityname": city,
        "adname": None,
        "pname": None,
        "address": _extract_public_web_address(html),
        "tel": phone,
        "location": None,
        "type": category or keyword or "公开网页",
        "detail_url": url,
        "_raw_provider": "public_web",
        "_raw_payload": {
            "provider": "public_web",
            "query_city": city,
            "query_category": category,
            "query_keyword": keyword,
            "source_url": url,
            "title": _extract_title(html),
        },
    }


def _candidate_address_score(reference: str | None, candidate: str | None) -> int:
    if not reference or not candidate:
        return 0
    normalized_reference = _normalize_text(reference)
    normalized_candidate = _normalize_text(candidate)
    if not normalized_reference or not normalized_candidate:
        return 0
    if normalized_reference == normalized_candidate:
        return 12
    if normalized_reference in normalized_candidate or normalized_candidate in normalized_reference:
        return 8
    return 0


def _pick_best_map_poi(name: str, address: str | None, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_name = _normalize_text(name)
    best_score = -1
    best_poi: dict[str, Any] | None = None
    for candidate in candidates:
        score = 0
        candidate_name = _normalize_text(candidate.get("name"))
        if candidate_name == normalized_name:
            score += 20
        elif normalized_name and (normalized_name in candidate_name or candidate_name in normalized_name):
            score += 12
        score += _candidate_address_score(address, candidate.get("address"))
        if _first_valid_phone(str(candidate.get("tel") or "")):
            score += 4
        if score > best_score:
            best_score = score
            best_poi = candidate
    return best_poi if best_score >= 12 else None


def _supplement_platform_poi_with_map(
    db: Session,
    poi: dict[str, Any],
    city: str,
    category: str,
) -> dict[str, Any]:
    name = str(poi.get("name") or "").strip()
    if not name:
        return poi

    current = dict(poi)
    for provider in ("amap", "baidu"):
        try:
            candidates = _request_provider_pois(db, provider, city, category, name, 8)
        except CollectionError:
            continue
        except Exception:
            continue
        match = _pick_best_map_poi(name, str(current.get("address") or ""), candidates)
        if not match:
            continue
        if not _first_valid_phone(str(current.get("tel") or "")):
            current["tel"] = match.get("tel")
        if not current.get("address"):
            current["address"] = match.get("address")
        if not current.get("adname"):
            current["adname"] = match.get("adname")
        if not current.get("pname"):
            current["pname"] = match.get("pname")
        if not current.get("cityname"):
            current["cityname"] = match.get("cityname")
        if not current.get("location"):
            current["location"] = match.get("location")
        raw_payload = dict(current.get("_raw_payload") or {})
        raw_payload["_map_match_provider"] = provider
        raw_payload["_map_match_id"] = match.get("id")
        current["_raw_payload"] = raw_payload
        return current
    return current


def _read_provider_config(db: Session, provider: str) -> LeadProviderConfig | None:
    return db.scalar(select(LeadProviderConfig).where(LeadProviderConfig.provider == provider))


def _read_provider_api_key(db: Session, provider: str) -> str | None:
    config = _read_provider_config(db, provider)
    if config and not config.enabled:
        raise CollectionError(f"{config.name} 已停用，请先在后台「采集接口配置」启用。")
    if config and config.api_key:
        return config.api_key.strip()
    if provider == "amap" and settings.amap_web_key:
        return settings.amap_web_key
    if provider == "baidu" and settings.baidu_map_key:
        return settings.baidu_map_key
    if provider == "tencent" and settings.tencent_map_key:
        return settings.tencent_map_key
    return None


def _request_amap_pois(
    db: Session,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    api_key = _read_provider_api_key(db, "amap")
    if not api_key:
        raise CollectionError("未配置高德地图密钥，请先到后台「采集接口配置」填写高德地图服务密钥。")

    keywords = " ".join(_clean_items([category, keyword])) or category or keyword
    if not keywords:
        raise CollectionError("采集关键词不能为空")

    page_size = 20
    max_pages = min(ceil(target_count / page_size), 10)
    pois: list[dict[str, Any]] = []
    for page in range(1, max_pages + 1):
        params = {
            "key": api_key,
            "keywords": keywords,
            "city": city,
            "citylimit": "true",
            "children": "0",
            "offset": str(page_size),
            "page": str(page),
            "extensions": "all",
            "output": "JSON",
        }
        url = f"https://restapi.amap.com/v3/place/text?{urlencode(params)}"
        with urlopen(url, timeout=settings.collection_request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if payload.get("status") != "1":
            info = payload.get("info") or "高德接口返回异常"
            raise CollectionError(f"高德地图采集失败：{info}")

        page_pois = payload.get("pois") or []
        if not isinstance(page_pois, list) or not page_pois:
            break
        pois.extend([poi for poi in page_pois if isinstance(poi, dict)])
        if len(pois) >= target_count:
            break

    return pois[:target_count]


def _normalize_baidu_poi(record: dict[str, Any], city: str, category: str) -> dict[str, Any]:
    location = record.get("location") if isinstance(record.get("location"), dict) else {}
    detail_info = record.get("detail_info") if isinstance(record.get("detail_info"), dict) else {}
    tag = detail_info.get("tag") or record.get("tag") or category
    return {
        "id": str(record.get("uid") or record.get("id") or "").strip(),
        "name": record.get("name"),
        "cityname": record.get("city") or city,
        "adname": record.get("area"),
        "pname": record.get("province"),
        "address": record.get("address"),
        "tel": record.get("telephone"),
        "location": _build_location(location.get("lng"), location.get("lat")),
        "type": tag,
        "detail_info": detail_info,
        "_raw_provider": "baidu",
        "_raw_payload": record,
    }


def _request_baidu_pois(
    db: Session,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    api_key = _read_provider_api_key(db, "baidu")
    if not api_key:
        raise CollectionError("未配置百度地图密钥，请先到后台「采集接口配置」填写百度地图访问密钥。")

    query = " ".join(_clean_items([category, keyword])) or category or keyword
    if not query:
        raise CollectionError("采集关键词不能为空")

    config = _read_provider_config(db, "baidu")
    service_url = (config.service_url if config else None) or "https://api.map.baidu.com/place/v3/region"
    page_size = 20
    max_pages = min(ceil(target_count / page_size), 10)
    pois: list[dict[str, Any]] = []
    for page_num in range(max_pages):
        params = {
            "ak": api_key,
            "query": query,
            "region": city,
            "city_limit": "true",
            "scope": "2",
            "page_size": str(page_size),
            "page_num": str(page_num),
            "output": "json",
        }
        url = f"{service_url}?{urlencode(params)}"
        with urlopen(url, timeout=settings.collection_request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if payload.get("status") != 0:
            info = payload.get("message") or payload.get("msg") or "百度接口返回异常"
            raise CollectionError(f"百度地图采集失败：{info}")

        page_pois = payload.get("results") or []
        if not isinstance(page_pois, list) or not page_pois:
            break
        pois.extend([_normalize_baidu_poi(poi, city, category) for poi in page_pois if isinstance(poi, dict)])
        if len(pois) >= target_count:
            break

    return pois[:target_count]


def _normalize_tencent_poi(record: dict[str, Any], city: str, category: str) -> dict[str, Any]:
    location = record.get("location") if isinstance(record.get("location"), dict) else {}
    ad_info = record.get("ad_info") if isinstance(record.get("ad_info"), dict) else {}
    return {
        "id": str(record.get("id") or "").strip(),
        "name": record.get("title"),
        "cityname": ad_info.get("city") or city,
        "adname": ad_info.get("district"),
        "pname": ad_info.get("province"),
        "address": record.get("address"),
        "tel": record.get("tel") or record.get("phone"),
        "location": _build_location(location.get("lng"), location.get("lat")),
        "type": record.get("category") or category,
        "ad_info": ad_info,
        "_raw_provider": "tencent",
        "_raw_payload": record,
    }


def _build_tencent_url(service_url: str, params: dict[str, str], secret_key: str | None) -> str:
    query = urlencode(params)
    if not secret_key:
        return f"{service_url}?{query}"

    path = urlsplit(service_url).path
    raw = f"{path}?{query}{secret_key.strip()}"
    signature = md5(quote(raw, safe="").encode("utf-8")).hexdigest()
    return f"{service_url}?{query}&sn={signature}"


def _request_tencent_pois(
    db: Session,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    api_key = _read_provider_api_key(db, "tencent")
    if not api_key:
        raise CollectionError("未配置腾讯位置服务密钥，请先到后台「采集接口配置」填写腾讯位置服务访问密钥。")

    query = " ".join(_clean_items([category, keyword])) or category or keyword
    if not query:
        raise CollectionError("采集关键词不能为空")

    config = _read_provider_config(db, "tencent")
    service_url = (config.service_url if config else None) or "https://apis.map.qq.com/ws/place/v1/search"
    secret_key = config.secret_key if config else None
    page_size = 20
    max_pages = min(ceil(target_count / page_size), 10)
    pois: list[dict[str, Any]] = []
    for page_index in range(1, max_pages + 1):
        params = {
            "key": api_key,
            "keyword": query,
            "boundary": f"region({city},0)",
            "page_size": str(page_size),
            "page_index": str(page_index),
            "output": "json",
        }
        url = _build_tencent_url(service_url, params, secret_key)
        with urlopen(url, timeout=settings.collection_request_timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))

        if payload.get("status") != 0:
            info = payload.get("message") or "腾讯位置服务接口返回异常"
            raise CollectionError(f"腾讯位置服务采集失败：{info}")

        page_pois = payload.get("data") or []
        if not isinstance(page_pois, list) or not page_pois:
            break
        pois.extend([_normalize_tencent_poi(poi, city, category) for poi in page_pois if isinstance(poi, dict)])
        if len(pois) >= target_count:
            break

    return pois[:target_count]


def _request_platform_pois(
    db: Session,
    provider: str,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    if provider not in PLATFORM_PROVIDERS:
        raise CollectionError(f"暂不支持的数据源：{provider}")

    browser_error: str | None = None
    if provider in BROWSER_PLATFORM_PROVIDERS:
        try:
            browser_records = collect_browser_platform_pois(db, provider, city, category, keyword, target_count)
            if browser_records:
                return browser_records
        except BrowserSessionError as exc:
            browser_error = str(exc)

    search_base_url = _read_provider_service_url(db, provider, "https://www.sogou.com/web")
    urls: list[str] = []
    for query in _build_platform_search_queries(provider, city, category, keyword):
        urls.extend(_discover_platform_urls(provider, query, target_count, search_base_url))
        if len(urls) >= target_count:
            break

    unique_urls: list[str] = []
    for url in urls:
        if url not in unique_urls:
            unique_urls.append(url)
        if len(unique_urls) >= target_count:
            break

    records: list[dict[str, Any]] = []
    for url in unique_urls:
        try:
            html = _request_text(url)
        except Exception:
            continue

        name = _extract_platform_name(html)
        if not name:
            continue

        record = {
            "id": _extract_platform_page_id(provider, url, html),
            "name": name,
            "cityname": city,
            "adname": None,
            "pname": None,
            "address": _extract_platform_address(html),
            "tel": _extract_platform_phone(html),
            "location": None,
            "type": category or keyword or _provider_label(provider),
            "detail_url": url,
            "_raw_provider": provider,
            "_raw_payload": {
                "provider": provider,
                "query_city": city,
                "query_category": category,
                "query_keyword": keyword,
                "source_url": url,
                "title": _extract_title(html),
            },
        }
        records.append(record)

    if records:
        return records[:target_count]
    if browser_error:
        raise CollectionValidationError(browser_error)
    return []


def _request_public_web_pois(
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    queries = [
        " ".join(_clean_items([city, category, keyword, "电话"])),
        " ".join(_clean_items([city, category, "商家", "电话"])),
        " ".join(_clean_items([city, keyword, "商家", "电话"])),
    ]
    urls: list[str] = []
    for query in [item for item in queries if item]:
        for candidate in _discover_public_web_urls(query, max(target_count * 8, 24)):
            if candidate not in urls:
                urls.append(candidate)
            if len(urls) >= max(target_count * 10, 30):
                break
        if len(urls) >= max(target_count * 10, 30):
            break

    records: list[dict[str, Any]] = []
    for url in urls:
        try:
            html = _request_text(url)
        except Exception:
            continue
        record = _extract_public_web_record(url, html, city, category, keyword)
        if not record:
            continue
        if any(existing["id"] == record["id"] or _normalize_text(existing["name"]) == _normalize_text(record["name"]) for existing in records):
            continue
        records.append(record)
        if len(records) >= target_count:
            break
    return records


def _request_provider_pois(
    db: Session,
    provider: str,
    city: str,
    category: str,
    keyword: str,
    target_count: int,
) -> list[dict[str, Any]]:
    if provider == "amap":
        return _request_amap_pois(db, city, category, keyword, target_count)
    if provider == "baidu":
        return _request_baidu_pois(db, city, category, keyword, target_count)
    if provider == "tencent":
        return _request_tencent_pois(db, city, category, keyword, target_count)
    if provider in PLATFORM_PROVIDERS:
        return _request_platform_pois(db, provider, city, category, keyword, target_count)
    if provider in PUBLIC_PROVIDERS:
        return _request_public_web_pois(city, category, keyword, target_count)
    raise CollectionError("当前只支持地图点位和平台公开页面采集数据源")


def _existing_lead_statement(
    owner_user_id: str | None,
    provider: str,
    poi_id: str,
    name: str,
    address: str | None,
    phone: str | None,
    homepage_url: str | None,
):
    conditions = [and_(MerchantLead.platform == provider, MerchantLead.source_poi_id == poi_id)]
    if phone:
        conditions.append(MerchantLead.phone == phone)
    if name and address:
        conditions.append(and_(MerchantLead.name == name, MerchantLead.address == address))
    if homepage_url:
        conditions.append(MerchantLead.platform_homepage_url == homepage_url)
    return select(MerchantLead).where(MerchantLead.owner_user_id == owner_user_id, or_(*conditions))


def _find_existing_lead(
    db: Session,
    owner_user_id: str | None,
    provider: str,
    poi_id: str,
    name: str,
    address: str | None,
    phone: str | None,
    homepage_url: str | None,
) -> MerchantLead | None:
    existing = db.scalar(_existing_lead_statement(owner_user_id, provider, poi_id, name, address, phone, homepage_url))
    if existing or not phone:
        return existing

    # 兼容历史数据里带括号、空格或短横线的号码，避免同号码换格式后重复入库。
    for candidate in db.scalars(
        select(MerchantLead).where(MerchantLead.owner_user_id == owner_user_id, MerchantLead.phone.is_not(None)),
    ).all():
        if _normalize_phone_item(candidate.phone) == phone:
            return candidate
    return None


class _DiscoveryIngestCache:
    """采集去重缓存（2026-07-09）。

    数据库迁到云端后，逐条 SELECT + SAVEPOINT + flush 被公网 RTT 放大
    （28ms/往返 × ~10 往返/条 ≈ 300ms/条，200 条要 1 分钟；库在本地时无感）。
    运行开头用两条查询把已有 raw poi_id 与线索匹配键拉进内存，循环内零查询、
    零 flush，结尾一次性 flush（executemany 批量写入）。
    匹配语义与 _find_existing_lead 一致：poi_id → 电话精确 → 名称+地址 →
    主页链接 → 归一化电话。
    """

    def __init__(self, db: Session, owner_user_id: str | None, provider: str) -> None:
        self.raw_poi_ids: set[str] = {
            v
            for v in db.scalars(
                select(RawLeadRecord.source_poi_id).where(
                    RawLeadRecord.owner_user_id == owner_user_id,
                    RawLeadRecord.provider == provider,
                ),
            ).all()
            if v
        }
        self.by_poi: dict[tuple[str, str], MerchantLead] = {}
        self.by_phone: dict[str, MerchantLead] = {}
        self.by_norm_phone: dict[str, MerchantLead] = {}
        self.by_name_addr: dict[tuple[str, str], MerchantLead] = {}
        self.by_homepage: dict[str, MerchantLead] = {}
        for lead in db.scalars(select(MerchantLead).where(MerchantLead.owner_user_id == owner_user_id)).all():
            self.register_lead(lead)

    def register_lead(self, lead: MerchantLead) -> None:
        if lead.platform and lead.source_poi_id:
            self.by_poi.setdefault((lead.platform, lead.source_poi_id), lead)
        if lead.phone:
            self.by_phone.setdefault(lead.phone, lead)
            normalized = _normalize_phone_item(lead.phone)
            if normalized:
                self.by_norm_phone.setdefault(normalized, lead)
        if lead.name and lead.address:
            self.by_name_addr.setdefault((lead.name, lead.address), lead)
        if lead.platform_homepage_url:
            self.by_homepage.setdefault(lead.platform_homepage_url, lead)

    def find_existing_lead(
        self,
        provider: str,
        poi_id: str,
        name: str,
        address: str | None,
        phone: str | None,
        homepage_url: str | None,
    ) -> MerchantLead | None:
        lead = self.by_poi.get((provider, poi_id))
        if lead is None and phone:
            lead = self.by_phone.get(phone)
        if lead is None and name and address:
            lead = self.by_name_addr.get((name, address))
        if lead is None and homepage_url:
            lead = self.by_homepage.get(homepage_url)
        if lead is None and phone:
            lead = self.by_norm_phone.get(_normalize_phone_item(phone) or "")
        return lead


def _lead_matches_keyword(lead: MerchantLead, keyword: str) -> bool:
    normalized_keyword = _normalize_text(keyword)
    if not normalized_keyword:
        return True
    haystack = _normalize_text(
        " ".join(
            str(value or "")
            for value in (
                lead.name,
                lead.city,
                lead.category,
                lead.address,
                lead.district,
                lead.remark,
            )
        ),
    )
    return normalized_keyword in haystack


def _select_enrichment_seeds(db: Session, task: LeadCollectionTask) -> list[EnrichmentSeed]:
    cities = _clean_items(task.cities or [])
    categories = _clean_items(task.categories or [])
    keywords = _clean_items(task.keywords or []) or [""]
    owner_user_id = task.owner_user_id
    if not owner_user_id:
        return []

    leads = list(
        db.scalars(
            select(MerchantLead)
            .where(MerchantLead.owner_user_id == owner_user_id)
            .order_by(MerchantLead.updated_at.desc(), MerchantLead.created_at.desc()),
        ).all(),
    )
    specs: list[EnrichmentSeed] = []
    seen: set[tuple[str, str, str, str]] = set()
    for city in cities:
        normalized_city = _normalize_text(city)
        for category in categories:
            normalized_category = _normalize_text(category)
            for keyword in keywords:
                added = 0
                for lead in leads:
                    if _is_blacklisted_lead(lead):
                        continue
                    if normalized_city and normalized_city not in _normalize_text(lead.city):
                        continue
                    if normalized_category and normalized_category not in _normalize_text(lead.category):
                        continue
                    if keyword and not _lead_matches_keyword(lead, keyword):
                        continue
                    spec_key = (lead.id, city, category, keyword)
                    if spec_key in seen:
                        continue
                    specs.append(EnrichmentSeed(lead_id=lead.id, city=city, category=category, keyword=keyword))
                    seen.add(spec_key)
                    added += 1
                    if added >= task.target_per_keyword:
                        break
    return specs


def _pick_best_platform_poi(seed: MerchantLead, candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    best = _pick_best_map_poi(seed.name, seed.address, candidates)
    if best:
        return best
    normalized_name = _normalize_text(seed.name)
    for candidate in candidates:
        if _normalize_text(candidate.get("name")) == normalized_name:
            return candidate
    return candidates[0]


def _append_remark(existing_remark: str | None, addition: str) -> str:
    cleaned_addition = addition.strip()
    if not cleaned_addition:
        return existing_remark or ""
    current = str(existing_remark or "").strip()
    if cleaned_addition in current:
        return current
    return cleaned_addition if not current else f"{current}\n{cleaned_addition}"


def _merge_platform_poi_into_lead(
    lead: MerchantLead,
    provider: str,
    poi: dict[str, Any],
    city: str,
    category: str,
    keyword: str,
) -> tuple[bool, str | None]:
    changed = False
    poi_id = str(poi.get("id") or "").strip() or None
    phone = _first_valid_phone(str(poi.get("tel") or ""))
    homepage_url = _normalize_homepage_url(_extract_homepage_url(poi), fallback_poi_id=poi_id)
    city_name = str(poi.get("cityname") or city or "").strip() or None
    district = str(poi.get("adname") or "").strip() or None
    address = str(poi.get("address") or "").strip() or None
    category_text = str(poi.get("type") or category or "").strip() or category
    longitude, latitude = _split_location(str(poi.get("location") or ""))

    if provider in PLATFORM_PROVIDERS and lead.platform != provider:
        lead.platform = provider
        changed = True
    if phone and _first_valid_phone(lead.phone) != phone and not _first_valid_phone(lead.phone):
        lead.phone = phone
        changed = True
    if homepage_url and lead.platform_homepage_url != homepage_url:
        lead.platform_homepage_url = homepage_url
        changed = True
    if homepage_url and lead.platform_url != homepage_url:
        lead.platform_url = homepage_url
        changed = True
    if not lead.source_poi_id and poi_id:
        lead.source_poi_id = poi_id
        changed = True
    if city_name and lead.city != city_name:
        lead.city = city_name
        changed = True
    if not lead.district and district:
        lead.district = district
        changed = True
    if not lead.address and address:
        lead.address = address
        changed = True
    if not lead.longitude and longitude:
        lead.longitude = longitude
        changed = True
    if not lead.latitude and latitude:
        lead.latitude = latitude
        changed = True
    if category_text and category_text != lead.category and _normalize_text(category_text) not in _normalize_text(lead.category):
        lead.category = category_text
        changed = True

    enrichment_note = f"平台补充：{_provider_label(provider)}，检索词：{keyword or lead.name}"
    next_remark = _append_remark(lead.remark, enrichment_note)
    if next_remark != (lead.remark or ""):
        lead.remark = next_remark
        changed = True
    return changed, phone or _first_valid_phone(lead.phone)


def _create_raw_record(
    *,
    task: LeadCollectionTask,
    run: LeadCollectionRun,
    provider: str,
    owner_user_id: str | None,
    poi: dict[str, Any],
    city: str,
    category: str,
    lead: MerchantLead | None,
    import_status: str,
    phone: str | None,
) -> RawLeadRecord:
    poi_id = str(poi.get("id") or "").strip()
    longitude, latitude = _split_location(str(poi.get("location") or ""))
    return RawLeadRecord(
        task_id=task.id,
        run_id=run.id,
        lead_id=lead.id if lead else None,
        owner_user_id=owner_user_id,
        provider=provider,
        source_poi_id=poi_id[:120],
        # 源头截断，与线索侧一致，避免批量 flush 触发 VARCHAR 约束错误
        name=str(poi.get("name") or "")[:160],
        city=(str(poi.get("cityname") or city or "")[:40] or None),
        district=(str(poi.get("adname") or "")[:80] or None),
        category=(str(poi.get("type") or category or "")[:120] or None),
        phone=phone or _first_valid_phone(str(poi.get("tel") or "")),
        address=(str(poi.get("address") or "")[:255] or None),
        source_url=_normalize_homepage_url(
            _extract_homepage_url(poi),
            fallback_poi_id=poi_id,
        ),
        longitude=longitude,
        latitude=latitude,
        import_status=import_status,
        raw_payload=poi,
    )


def _create_lead_from_poi(
    db: Session,
    owner_user_id: str | None,
    provider: str,
    poi: dict[str, Any],
    city: str,
    category: str,
    keyword: str,
    source_label: str,
    seed_lead: MerchantLead | None = None,
    cache: "_DiscoveryIngestCache | None" = None,
) -> LeadImportResult:
    poi_id = str(poi.get("id") or "").strip()
    name = str(poi.get("name") or "").strip()
    if not poi_id or not name:
        return LeadImportResult(lead=None, import_status="无效数据")

    city_name = str(poi.get("cityname") or city or "").strip() or None
    district = str(poi.get("adname") or "").strip() or None
    address = str(poi.get("address") or "").strip() or None
    raw_phone = str(poi.get("tel") or "")
    phone = _first_valid_phone(raw_phone)
    homepage_url = _normalize_homepage_url(_extract_homepage_url(poi), fallback_poi_id=poi_id)

    if seed_lead is not None:
        if _is_blacklisted_lead(seed_lead):
            return LeadImportResult(lead=None, import_status="黑名单拦截", phone=phone or _first_valid_phone(seed_lead.phone))
        changed, merged_phone = _merge_platform_poi_into_lead(seed_lead, provider, poi, city, category, keyword)
        db.add(seed_lead)
        db.flush()
        return LeadImportResult(
            lead=seed_lead,
            import_status="已补充" if changed else "重复线索",
            phone=merged_phone,
        )

    if not phone:
        if provider in PLATFORM_PROVIDERS:
            return LeadImportResult(lead=None, import_status="待补电话")
        return LeadImportResult(lead=None, import_status="无电话" if not raw_phone.strip() else "无效号码")

    longitude, latitude = _split_location(str(poi.get("location") or ""))
    category_text = str(poi.get("type") or category or "").strip() or category

    existing = (
        cache.find_existing_lead(provider, poi_id, name, address, phone, homepage_url)
        if cache is not None
        else _find_existing_lead(db, owner_user_id, provider, poi_id, name, address, phone, homepage_url)
    )
    if existing:
        if _is_blacklisted_lead(existing):
            return LeadImportResult(lead=None, import_status="黑名单拦截", phone=phone)
        return LeadImportResult(lead=existing, import_status="重复线索", phone=phone)

    lead = MerchantLead(
        # 显式生成主键：快路径延迟到运行结尾才 flush，若靠 default 的 uuid lambda，
        # lead.id 在 flush 前为 None，紧接着 _create_raw_record 读 lead.id 会写入 NULL
        # 外键（raw 记录与线索断链）。客户端生成 id 让 lead.id 立即可用。
        id=uuid4().hex,
        # 源头截断超长字段：高德 type 拼接后常超 VARCHAR(80)，否则批量 flush 触发约束错误
        name=name[:120],
        platform=provider,
        city=(city_name or city)[:40],
        category=category_text[:80],
        phone=phone,
        platform_homepage_url=homepage_url[:500] if homepage_url else None,
        source_poi_id=poi_id,
        province=(str(poi.get("pname") or "").strip()[:40] or None),
        district=district[:80] if district else None,
        address=address[:255] if address else None,
        longitude=longitude,
        latitude=latitude,
        source=source_label,
        intent_score=_score_lead(poi, city, category, keyword),
        status="待外呼",
        follow_up_status="未跟进",
        remark=f"采集关键词：{keyword or category}",
        owner_user_id=owner_user_id,
        created_by_user_id=owner_user_id,
    )
    db.add(lead)
    if cache is not None:
        cache.register_lead(lead)  # 批内去重靠缓存，flush 留到运行结尾一次性做
    else:
        db.flush()
    return LeadImportResult(lead=lead, import_status="已入库", phone=phone)


def _estimate_requested_count(task: LeadCollectionTask) -> int:
    cities = _clean_items(task.cities or [])
    categories = _clean_items(task.categories or [])
    keywords = _clean_items(task.keywords or []) or [""]
    return len(cities) * len(categories) * len(keywords) * max(int(task.target_per_keyword or 0), 1)


def _mark_task_and_run(task: LeadCollectionTask, run: LeadCollectionRun, status: str) -> None:
    run.status = status
    task.status = status
    task.last_run_status = status


def _record_import_result(
    db: Session,
    *,
    task: LeadCollectionTask,
    run: LeadCollectionRun,
    city: str,
    category: str,
    keyword: str,
    poi: dict[str, Any],
    seed_lead: MerchantLead | None = None,
    cache: "_DiscoveryIngestCache | None" = None,
) -> None:
    owner_user_id = task.owner_user_id
    poi_id = str(poi.get("id") or "").strip()
    if not poi_id:
        run.failed_count += 1
        return

    if cache is not None:
        if poi_id in cache.raw_poi_ids:
            run.duplicate_count += 1
            return
    else:
        existing_raw = db.scalar(
            select(RawLeadRecord).where(
                RawLeadRecord.owner_user_id == owner_user_id,
                RawLeadRecord.provider == task.provider,
                RawLeadRecord.source_poi_id == poi_id,
            ),
        )
        if existing_raw:
            run.duplicate_count += 1
            return

    try:
        if cache is not None:
            # 快路径：内存去重 + 延迟到运行结尾批量 flush，不用 SAVEPOINT
            import_result = _create_lead_from_poi(
                db,
                owner_user_id,
                task.provider,
                poi,
                city,
                category,
                keyword,
                _collection_source_label(task.provider, task.collection_mode),
                seed_lead=seed_lead,
                cache=cache,
            )
            raw_record = _create_raw_record(
                task=task,
                run=run,
                provider=task.provider,
                owner_user_id=owner_user_id,
                poi=poi,
                city=city,
                category=category,
                lead=import_result.lead,
                import_status=import_result.import_status,
                phone=import_result.phone,
            )
            db.add(raw_record)
            cache.raw_poi_ids.add(poi_id)
        else:
            with db.begin_nested():
                import_result = _create_lead_from_poi(
                    db,
                    owner_user_id,
                    task.provider,
                    poi,
                    city,
                    category,
                    keyword,
                    _collection_source_label(task.provider, task.collection_mode),
                    seed_lead=seed_lead,
                )
                raw_record = _create_raw_record(
                    task=task,
                    run=run,
                    provider=task.provider,
                    owner_user_id=owner_user_id,
                    poi=poi,
                    city=city,
                    category=category,
                    lead=import_result.lead,
                    import_status=import_result.import_status,
                    phone=import_result.phone,
                )
                db.add(raw_record)
                db.flush()
    except Exception as exc:
        run.failed_count += 1
        if not run.error_message:
            run.error_message = f"部分线索保存失败：{_safe_error_text(exc)}"
        return

    if import_result.import_status == "已入库":
        run.inserted_count += 1
    elif import_result.import_status == "已补充":
        run.updated_count += 1
    elif import_result.import_status == "重复线索":
        run.duplicate_count += 1
    else:
        run.failed_count += 1


def _run_discovery_collection(db: Session, task: LeadCollectionTask, run: LeadCollectionRun) -> None:
    cities = _clean_items(task.cities or [])
    categories = _clean_items(task.categories or [])
    keywords = _clean_items(task.keywords or []) or [""]
    run.requested_count = len(cities) * len(categories) * len(keywords) * task.target_per_keyword

    # 去重缓存：两条查询预热，循环内零数据库往返（云端库下 200 条从 ~60s 降到秒级）
    cache = _DiscoveryIngestCache(db, task.owner_user_id, task.provider)

    for city in cities:
        for category in categories:
            for keyword in keywords:
                pois = _request_provider_pois(db, task.provider, city, category, keyword, task.target_per_keyword)
                run.fetched_count += len(pois)
                for poi in pois:
                    _record_import_result(
                        db,
                        task=task,
                        run=run,
                        city=city,
                        category=category,
                        keyword=keyword,
                        poi=poi,
                        cache=cache,
                    )
    # 一次性批量写入本轮全部新线索/原始记录。
    # 快路径去掉了逐条 SAVEPOINT，若某条触发约束错误（字段已在源头截断，极少发生），
    # 批量 flush 会整批失败并让会话进入失效事务——必须 rollback，否则上游 finalize 的
    # commit 会在中毒会话上再抛，任务永久卡在「运行中」无法重跑（子代理审计 BUG 2）。
    try:
        db.flush()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        raise CollectionError(f"批量入库失败，本轮已回滚：{_safe_error_text(exc)}") from exc


def _run_platform_enrichment(db: Session, task: LeadCollectionTask, run: LeadCollectionRun) -> None:
    if task.provider not in PLATFORM_PROVIDERS:
        raise CollectionError("当前来源仅支持拓源采集，平台来源才支持补充模式。")

    seeds = _select_enrichment_seeds(db, task)
    run.requested_count = len(seeds)
    if not seeds:
        raise CollectionError("平台补充模式没有找到可补充的现有线索，请先执行一轮地图拓源采集。")

    for seed in seeds:
        lead = db.scalar(
            select(MerchantLead).where(
                MerchantLead.id == seed.lead_id,
                MerchantLead.owner_user_id == task.owner_user_id,
            ),
        )
        if lead is None or _is_blacklisted_lead(lead):
            run.failed_count += 1
            continue

        query_text = lead.name
        candidates = _request_platform_pois(db, task.provider, seed.city, seed.category, query_text, min(task.target_per_keyword, 5))
        match = _pick_best_platform_poi(lead, candidates)
        if not match:
            run.failed_count += 1
            continue

        run.fetched_count += 1
        _record_import_result(
            db,
            task=task,
            run=run,
            city=seed.city,
            category=seed.category,
            keyword=seed.keyword or query_text,
            poi=match,
            seed_lead=lead,
        )


def _finalize_collection_status(task: LeadCollectionTask, run: LeadCollectionRun, *, error: Exception | None = None) -> None:
    has_success = any((run.inserted_count, run.updated_count, run.duplicate_count))
    if isinstance(error, CollectionValidationError):
        run.error_message = str(error)
        _mark_task_and_run(task, run, "需验证")
        return
    if error is not None:
        run.error_message = str(error)
        _mark_task_and_run(task, run, "部分完成" if has_success else "失败")
        return
    if run.failed_count > 0:
        _mark_task_and_run(task, run, "部分完成" if has_success else "失败")
        return
    _mark_task_and_run(task, run, "已完成")


def _execute_collection_run(db: Session, task: LeadCollectionTask, run: LeadCollectionRun) -> None:
    cities = _clean_items(task.cities or [])
    categories = _clean_items(task.categories or [])
    if task.provider not in MAP_PROVIDERS | PLATFORM_PROVIDERS | PUBLIC_PROVIDERS:
        raise CollectionError("当前只支持地图点位、平台公开页面和公开网页采集数据源")
    if not cities or not categories:
        raise CollectionError("采集任务必须至少包含一个城市和一个品类")

    task.collection_mode = normalize_collection_mode(task.provider, task.collection_mode)
    run.collection_mode = task.collection_mode
    error: Exception | None = None
    try:
        if task.collection_mode == COLLECTION_MODE_ENRICH:
            _run_platform_enrichment(db, task, run)
        else:
            _run_discovery_collection(db, task, run)
    except (CollectionValidationError, CollectionError) as exc:
        error = exc
    except Exception as exc:
        error = CollectionError(_safe_error_text(exc))
    finally:
        _finalize_collection_status(task, run, error=error)
        run.finished_at = datetime.utcnow()
        db.add(task)
        db.add(run)
        db.commit()
        db.refresh(run)


def _run_collection_task_in_background(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.scalar(select(LeadCollectionRun).where(LeadCollectionRun.id == run_id))
        if run is None:
            return
        task = db.scalar(select(LeadCollectionTask).where(LeadCollectionTask.id == run.task_id))
        if task is None:
            run.status = "失败"
            run.error_message = "采集任务不存在，后台无法继续执行。"
            run.finished_at = datetime.utcnow()
            db.add(run)
            db.commit()
            return

        _mark_task_and_run(task, run, "运行中")
        db.add(task)
        db.add(run)
        db.commit()
        try:
            _execute_collection_run(db, task, run)
        except Exception as exc:
            run.status = "失败"
            run.error_message = _safe_error_text(exc)
            run.finished_at = datetime.utcnow()
            task.status = "失败"
            task.last_run_status = "失败"
            db.add(task)
            db.add(run)
            db.commit()


def enqueue_collection_task(db: Session, task: LeadCollectionTask) -> LeadCollectionRun:
    if _is_active_collection_status(task.status):
        raise CollectionError("该采集任务正在后台执行，请等待当前任务完成后再重试。")

    active_run = db.scalar(
        select(LeadCollectionRun)
        .where(
            LeadCollectionRun.task_id == task.id,
            LeadCollectionRun.status.in_(tuple(COLLECTION_ACTIVE_STATUSES)),
        )
        .order_by(LeadCollectionRun.started_at.desc()),
    )
    if active_run is not None:
        raise CollectionError("该采集任务已在队列中，请稍后刷新任务状态。")

    task.collection_mode = normalize_collection_mode(task.provider, task.collection_mode)
    run = LeadCollectionRun(
        task_id=task.id,
        provider=task.provider,
        collection_mode=task.collection_mode,
        status="排队中",
        requested_count=_estimate_requested_count(task),
    )
    _mark_task_and_run(task, run, "排队中")
    db.add(run)
    db.add(task)
    db.commit()
    db.refresh(run)

    try:
        COLLECTION_EXECUTOR.submit(_run_collection_task_in_background, run.id)
    except Exception as exc:
        run.status = "失败"
        run.error_message = f"后台排队失败：{_safe_error_text(exc)}"
        run.finished_at = datetime.utcnow()
        task.status = "失败"
        task.last_run_status = "失败"
        db.add(task)
        db.add(run)
        db.commit()
        db.refresh(run)
        raise CollectionError("采集任务加入后台队列失败，请稍后再试。") from exc
    return run
