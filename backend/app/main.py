import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, select
from sqlalchemy.exc import SQLAlchemyError

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

logger = logging.getLogger(__name__)


def _get_existing_tables() -> set[str]:
    with SessionLocal() as db:
        bind = db.get_bind()
        if bind is None:
            return set()
        return set(inspect(bind).get_table_names())


def _seed_initial_client_user() -> None:
    username = settings.initial_client_username.strip()
    password = settings.initial_client_password
    if not username or not password:
        return
    if "users" not in _get_existing_tables():
        logger.warning("skip initial client seed because users table is not available yet")
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
            existing_tables = _get_existing_tables()
            try:
                if "system_settings" in existing_tables:
                    _seed_settings(db)
                else:
                    logger.warning("skip system settings seed because system_settings table is not available yet")
                if "platform_browser_sessions" in existing_tables:
                    ensure_platform_browser_sessions(db)
                else:
                    logger.warning(
                        "skip browser session seed because platform_browser_sessions table is not available yet"
                    )
                db.commit()
            except SQLAlchemyError:
                db.rollback()
                logger.exception("startup seed skipped because database schema is not ready")
    return app


app = create_app()
