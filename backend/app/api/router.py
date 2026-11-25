"""Central API router mounting all versioned endpoints."""
from fastapi import APIRouter
from backend.app.api.v1 import auth, health, intake, shipments

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(intake.router, tags=["intake"])
api_router.include_router(shipments.router, tags=["shipments"])

