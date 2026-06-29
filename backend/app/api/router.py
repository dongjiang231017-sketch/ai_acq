from fastapi import APIRouter

from app.api import direct_messages, health, leads, modules, outbound, tasks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(modules.router, prefix="/modules", tags=["modules"])
api_router.include_router(leads.router, prefix="/leads", tags=["leads"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(outbound.router, prefix="/outbound", tags=["outbound"])
api_router.include_router(direct_messages.router, prefix="/direct-messages", tags=["direct-messages"])
