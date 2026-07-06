from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from app.core.config import settings
from app.services.platform_browser import (
    BROWSER_PLATFORM_METADATA,
    SHANGOU_REMOTE_DEBUGGING_PORT,
    _launch_persistent_context,
    _profile_dir,
    mark_platform_login_finished,
    sync_playwright,
)


def _chrome_binary() -> str | None:
    candidates = (
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/360Chrome.app/Contents/MacOS/360Chrome",
        shutil.which("google-chrome"),
        shutil.which("chrome"),
        shutil.which("chromium"),
    )
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _open_shangou_login_with_system_chrome(profile_dir: Path, url: str) -> int:
    chrome_binary = _chrome_binary()
    if not chrome_binary:
        raise RuntimeError("未找到可用的 Chrome 浏览器，请先安装 Google Chrome。")

    process = subprocess.Popen(
        [
            chrome_binary,
            f"--user-data-dir={profile_dir}",
            "--profile-directory=Default",
            "--new-window",
            "--no-first-run",
            "--no-default-browser-check",
            f"--remote-debugging-port={SHANGOU_REMOTE_DEBUGGING_PORT}",
            url,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print("已使用本机 Chrome 打开淘宝闪购登录窗口。请在这个专用窗口完成登录和验证，采集时尽量保持窗口开启。")
    return process.wait()


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
        if provider == "shangou":
            _open_shangou_login_with_system_chrome(profile_dir, meta["login_url"])
            mark_platform_login_finished(provider, "待验证", None)
            return 0

        with sync_playwright() as playwright:
            context = _launch_persistent_context(playwright, provider, profile_dir, headless=False)
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(meta["login_url"], wait_until="domcontentloaded", timeout=settings.browser_default_timeout_seconds * 1000)
            print(f"已打开 {meta['name']} 登录窗口。请手动完成登录，登录后直接关闭浏览器窗口即可。")
            context.wait_for_event("close", timeout=0)
    except Exception as exc:
        mark_platform_login_finished(provider, "失效", f"登录窗口异常关闭：{exc}")
        raise

    mark_platform_login_finished(provider, "待验证", None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
