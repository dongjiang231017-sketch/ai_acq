from __future__ import annotations

import sys

from app.core.config import settings
from app.services.platform_browser import (
    BROWSER_PLATFORM_METADATA,
    MOBILE_USER_AGENT,
    _profile_dir,
    mark_platform_login_finished,
    sync_playwright,
)


def main() -> int:
    if sync_playwright is None:
        print("未安装 Playwright，无法打开平台登录窗口。", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print("缺少平台参数，例如：python -m app.services.platform_browser_login meituan", file=sys.stderr)
        return 1

    provider = sys.argv[1].strip().lower()
    meta = BROWSER_PLATFORM_METADATA.get(provider)
    if meta is None:
        print(f"不支持的平台：{provider}", file=sys.stderr)
        return 1

    profile_dir = _profile_dir(provider)
    profile_dir.mkdir(parents=True, exist_ok=True)

    try:
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile_dir),
                headless=False,
                user_agent=MOBILE_USER_AGENT,
                viewport={"width": 430, "height": 932},
                is_mobile=True,
                has_touch=True,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(meta["login_url"], wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
            print(f"已打开 {meta['name']} 登录窗口。请手动完成登录，登录后直接关闭浏览器窗口即可。")
            context.wait_for_event("close")
    except Exception as exc:
        mark_platform_login_finished(provider, "失效", f"登录窗口异常关闭：{exc}")
        raise

    mark_platform_login_finished(provider, "待验证", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
