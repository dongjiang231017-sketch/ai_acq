from __future__ import annotations

import json
import re
from dataclasses import dataclass
from html import unescape
from hashlib import md5
from datetime import datetime
from math import ceil
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.collection import LeadCollectionRun, LeadCollectionTask, LeadProviderConfig, RawLeadRecord
from app.models.lead import MerchantLead
from app.services.platform_browser import (
    BrowserSessionError,
    browser_managed_providers,
    collect_browser_platform_pois,
)


class CollectionError(ValueError):
    pass


@dataclass(frozen=True)
class LeadImportResult:
    lead: MerchantLead | None
    import_status: str
    phone: str | None = None


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
        "allowed_hosts": ("meituan.com",),
    },
    "shangou": {
        "label": "美团闪购",
        "search_terms": ("美团", "闪购"),
        "allowed_hosts": ("meituan.com",),
    },
    "douyin": {
        "label": "抖音生活服务",
        "search_terms": ("抖音", "团购"),
        "allowed_hosts": ("douyin.com",),
    },
}
BROWSER_PLATFORM_PROVIDERS = browser_managed_providers()
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
    return [query for query in queries if query]


def _discover_platform_urls(provider: str, query: str, limit: int, search_base_url: str) -> list[str]:
    allowed_hosts = tuple(PLATFORM_PROVIDER_METADATA[provider]["allowed_hosts"])
    search_url = f"{search_base_url}?{urlencode({'query': query})}"
    html = _request_text(search_url)
    pattern = re.compile(r"https?://[^\"'\s<>]+")
    urls: list[str] = []
    for match in pattern.finditer(html):
        candidate = unescape(match.group(0))
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
            break
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

    if provider in BROWSER_PLATFORM_PROVIDERS:
        try:
            return collect_browser_platform_pois(db, provider, city, category, keyword, target_count)
        except BrowserSessionError as exc:
            raise CollectionError(str(exc)) from exc

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
        records.append(_supplement_platform_poi_with_map(db, record, city, category))

    return records[:target_count]


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


def _create_lead_from_poi(
    db: Session,
    owner_user_id: str | None,
    provider: str,
    poi: dict[str, Any],
    city: str,
    category: str,
    keyword: str,
    source_label: str,
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
    if not phone:
        if provider in PLATFORM_PROVIDERS:
            return LeadImportResult(lead=None, import_status="待补电话")
        return LeadImportResult(lead=None, import_status="无电话" if not raw_phone.strip() else "无效号码")

    longitude, latitude = _split_location(str(poi.get("location") or ""))
    category_text = str(poi.get("type") or category or "").strip() or category
    homepage_url = _extract_homepage_url(poi)

    existing = _find_existing_lead(db, owner_user_id, provider, poi_id, name, address, phone, homepage_url)
    if existing:
        if _is_blacklisted_lead(existing):
            return LeadImportResult(lead=None, import_status="黑名单拦截", phone=phone)
        return LeadImportResult(lead=existing, import_status="重复线索", phone=phone)

    lead = MerchantLead(
        name=name,
        platform=provider,
        city=city_name or city,
        category=category_text,
        phone=phone,
        platform_homepage_url=homepage_url,
        source_poi_id=poi_id,
        province=str(poi.get("pname") or "").strip() or None,
        district=district,
        address=address,
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
    db.flush()
    return LeadImportResult(lead=lead, import_status="已入库", phone=phone)


def run_collection_task(db: Session, task: LeadCollectionTask) -> LeadCollectionRun:
    cities = _clean_items(task.cities or [])
    categories = _clean_items(task.categories or [])
    keywords = _clean_items(task.keywords or []) or [""]
    owner_user_id = task.owner_user_id
    if task.provider not in MAP_PROVIDERS | PLATFORM_PROVIDERS | PUBLIC_PROVIDERS:
        raise CollectionError("当前只支持地图点位、平台公开页面和公开网页采集数据源")
    if not cities or not categories:
        raise CollectionError("采集任务必须至少包含一个城市和一个品类")
    source_label = PROVIDER_SOURCE_LABELS.get(task.provider, "公开来源采集")

    run = LeadCollectionRun(
        task_id=task.id,
        provider=task.provider,
        status="运行中",
        requested_count=len(cities) * len(categories) * len(keywords) * task.target_per_keyword,
    )
    task.status = "采集中"
    task.last_run_status = "运行中"
    db.add(run)
    db.flush()

    try:
        for city in cities:
            for category in categories:
                for keyword in keywords:
                    pois = _request_provider_pois(db, task.provider, city, category, keyword, task.target_per_keyword)
                    run.fetched_count += len(pois)
                    for poi in pois:
                        poi_id = str(poi.get("id") or "").strip()
                        if not poi_id:
                            run.failed_count += 1
                            continue

                        existing_raw = db.scalar(
                            select(RawLeadRecord).where(
                                RawLeadRecord.owner_user_id == owner_user_id,
                                RawLeadRecord.provider == task.provider,
                                RawLeadRecord.source_poi_id == poi_id,
                            ),
                        )
                        if existing_raw:
                            run.duplicate_count += 1
                            continue

                        import_result = _create_lead_from_poi(
                            db,
                            owner_user_id,
                            task.provider,
                            poi,
                            city,
                            category,
                            keyword,
                            source_label,
                        )
                        lead = import_result.lead
                        import_status = import_result.import_status
                        if import_status == "已入库":
                            run.inserted_count += 1
                        elif import_status == "重复线索":
                            run.duplicate_count += 1
                        else:
                            run.failed_count += 1

                        longitude, latitude = _split_location(str(poi.get("location") or ""))
                        raw_record = RawLeadRecord(
                            task_id=task.id,
                            run_id=run.id,
                            lead_id=lead.id if lead else None,
                            owner_user_id=owner_user_id,
                            provider=task.provider,
                            source_poi_id=poi_id,
                            name=str(poi.get("name") or ""),
                            city=str(poi.get("cityname") or city or "") or None,
                            district=str(poi.get("adname") or "") or None,
                            category=str(poi.get("type") or category or "") or None,
                            phone=import_result.phone or _first_valid_phone(str(poi.get("tel") or "")),
                            address=str(poi.get("address") or "") or None,
                            source_url=_extract_homepage_url(poi),
                            longitude=longitude,
                            latitude=latitude,
                            import_status=import_status,
                            raw_payload=poi,
                        )
                        db.add(raw_record)
                        db.flush()
        run.status = "已完成"
        task.status = "已完成"
        task.last_run_status = "已完成"
    except Exception as exc:
        run.status = "失败"
        run.error_message = str(exc)
        task.status = "失败"
        task.last_run_status = "失败"
    finally:
        run.finished_at = datetime.utcnow()
        db.add(task)
        db.add(run)
        db.commit()
        db.refresh(run)
    return run
