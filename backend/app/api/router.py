from fastapi import APIRouter

from app.api import auth, health, leads, modules, tasks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(modules.router, prefix="/modules", tags=["modules"])
api_router.include_router(leads.router, prefix="/leads", tags=["leads"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
