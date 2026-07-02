from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin import setup_admin
from app.api.router import api_router
from app.api.system_settings import _seed_settings
from app.core.config import settings
from app.db.session import SessionLocal


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(api_router, prefix=settings.api_prefix)
    setup_admin(app)

    @app.on_event("startup")
    def seed_runtime_settings() -> None:
        with SessionLocal() as db:
            _seed_settings(db)

    return app


app = create_app()
