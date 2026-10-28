from fastapi import APIRouter

from app.api.routes import auth, health, leads, sources, stats, users

api_router = APIRouter()
api_router.include_router(health.router, tags=["system"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(leads.router, prefix="/leads", tags=["leads"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(stats.router, prefix="/stats", tags=["statistics"])
