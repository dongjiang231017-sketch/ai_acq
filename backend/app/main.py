from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import setup_admin
from app.api.router import api_router
from app.core.config import settings
from app.core.errors import setup_exception_handlers
from app.db.session import SessionLocal
from app.services.platform_browser import ensure_platform_browser_sessions


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    setup_exception_handlers(app)
    setup_admin(app)
    with SessionLocal() as db:
        ensure_platform_browser_sessions(db)
        db.commit()
    return app


app = create_app()
