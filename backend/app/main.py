import asyncio
import json
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.admin import setup_admin
from app.api.router import api_router
from app.api.system_settings import _seed_settings
from app.core.config import settings
from app.core.correlation import EXPOSED_CORRELATION_HEADERS, install_correlation_middleware
from app.core.errors import setup_exception_handlers
from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User
from app.services.platform_browser import ensure_platform_browser_sessions
from app.services.telephony_runtime_config import telephony_config_source_report

logger = logging.getLogger(__name__)


def _seed_initial_client_user() -> None:
    username = settings.initial_client_username.strip()
    password = settings.initial_client_password
    if not username or not password:
        return

    with SessionLocal() as db:
        existing = db.scalar(select(User).where(User.username == username))
        if existing is not None:
            return
        user = User(
            username=username,
            display_name=settings.initial_client_display_name.strip() or username,
            email=settings.initial_client_email.strip() or None,
            phone=settings.initial_client_phone.strip() or None,
            password_hash=hash_password(password),
            status="启用",
            is_superuser=False,
        )
        db.add(user)
        db.commit()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=EXPOSED_CORRELATION_HEADERS,
    )
    install_correlation_middleware(app)

    app.include_router(api_router, prefix=settings.api_prefix)
    setup_exception_handlers(app)
    setup_admin(app)

    @app.on_event("startup")
    def seed_runtime_settings() -> None:
        _seed_initial_client_user()
        with SessionLocal() as db:
            _seed_settings(db)
            ensure_platform_browser_sessions(db)
            db.commit()

    @app.on_event("startup")
    def log_telephony_config_sources() -> None:
        # 【审计B9】启动时打一条日志列出关键电话参数的最终取值来源（进程环境变量 / sidecar env / .env默认），
        # 便于排查"改了不生效"的配置漂移问题。
        try:
            report = telephony_config_source_report(
                [
                    "TELEPHONY_GATEWAY_MODE",
                    "ASTERISK_DEPLOYMENT_MODE",
                    "ASTERISK_HOST",
                    "ASTERISK_AMI_PORT",
                    "ASTERISK_AMI_USERNAME",
                    "ASTERISK_AMI_PASSWORD",
                    "VOICE_GATEWAY_TRUNK_NAME",
                    "ASTERISK_TRUNK_NAME",
                    "ASTERISK_LIVE_CALL_ENABLED",
                    "ASTERISK_BULK_CALL_ENABLED",
                    "ASTERISK_AUDIO_SOCKET_HOST",
                    "ASTERISK_AUDIO_SOCKET_PORT",
                ]
            )
            logger.info("telephony_config_sources %s", json.dumps(report, ensure_ascii=False))
        except Exception:  # noqa: BLE001 启动日志失败不影响服务
            logger.exception("telephony_config_sources_log_failed")

    @app.on_event("startup")
    async def start_telephony_registration_watchdog() -> None:
        # 【审计B1】掉注册自愈：常驻看门狗每30秒轮询 pjsip contacts，contact 消失/恢复写日志事件，
        # 连续丢失写 /tmp/ai_acq_telephony_alert.json。启动失败只打日志，不影响 API 启动。
        if not settings.telephony_registration_watchdog_enabled:
            logger.info("telephony_registration_watchdog_disabled")
            return
        try:
            from app.services.telephony_registration_watchdog import run_registration_watchdog

            app.state.telephony_watchdog_task = asyncio.create_task(run_registration_watchdog())
        except Exception:  # noqa: BLE001
            logger.exception("telephony_registration_watchdog_start_failed")

    return app


app = create_app()
