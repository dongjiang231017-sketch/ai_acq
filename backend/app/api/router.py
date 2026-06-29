from fastapi import APIRouter

from app.api import direct_messages, health, intent, leads, learning, modules, outbound, reports, system_settings, tasks, voice

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(modules.router, prefix="/modules", tags=["modules"])
api_router.include_router(leads.router, prefix="/leads", tags=["leads"])
api_router.include_router(tasks.router, prefix="/tasks", tags=["tasks"])
api_router.include_router(outbound.router, prefix="/outbound", tags=["outbound"])
api_router.include_router(direct_messages.router, prefix="/direct-messages", tags=["direct-messages"])
api_router.include_router(intent.router, prefix="/intent", tags=["intent"])
api_router.include_router(learning.router, prefix="/learning", tags=["learning"])
api_router.include_router(voice.router, prefix="/voice", tags=["voice"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(system_settings.router, prefix="/settings", tags=["settings"])
