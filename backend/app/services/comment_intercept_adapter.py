from dataclasses import dataclass
from datetime import datetime

from app.core.config import settings
from app.models.task import CommentInterceptSource


@dataclass(frozen=True)
class PlatformComment:
    external_comment_id: str
    author_name: str
    author_profile_url: str
    content: str
    video_url: str
    city: str
    category: str
    like_count: int
    reply_count: int
    commented_at: datetime | None
    raw_payload: str


class CommentInterceptAdapterUnavailable(RuntimeError):
    pass


def _sync_action(source: CommentInterceptSource) -> str:
    if source.source_type == "关键词":
        return "搜索视频并同步评论"
    if source.source_type == "账号主页":
        return "读取账号主页视频并同步评论"
    return "同步视频评论"


def _disabled_message(source: CommentInterceptSource) -> str:
    return (
        f"{source.platform}评论截流未接通真实平台适配器：{source.source_type}来源需要真实登录态、"
        f"授权 API 或浏览器评论采集能力来{_sync_action(source)}。当前 "
        "COMMENT_INTERCEPT_LIVE_SYNC_ENABLED=false，系统已停止同步，不会生成模拟评论。"
    )


def sync_platform_comments(source: CommentInterceptSource) -> list[PlatformComment]:
    if not settings.comment_intercept_live_sync_enabled:
        raise CommentInterceptAdapterUnavailable(_disabled_message(source))

    adapter_mode = settings.comment_intercept_adapter_mode.strip().lower()
    if adapter_mode in {"", "disabled", "none"}:
        raise CommentInterceptAdapterUnavailable(
            f"{source.platform}评论截流真实同步开关已开启，但 COMMENT_INTERCEPT_ADAPTER_MODE 未配置为可用适配器。"
            "请先接入合规的授权 API 或浏览器评论采集适配器。"
        )

    raise CommentInterceptAdapterUnavailable(
        f"COMMENT_INTERCEPT_ADAPTER_MODE={settings.comment_intercept_adapter_mode} 还没有对应实现，"
        "评论截流未执行真实平台搜索或评论同步。"
    )
