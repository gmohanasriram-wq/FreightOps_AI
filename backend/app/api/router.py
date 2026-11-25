"""Central API router mounting all versioned endpoints."""
from fastapi import APIRouter
from backend.app.api.v1 import (
    approvals,
    auth,
    carriers,
    health,
    intake,
    recommendations,
    shipments,
    workflows,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(carriers.router, tags=["carriers"])
api_router.include_router(intake.router, tags=["intake"])
api_router.include_router(shipments.router, tags=["shipments"])
api_router.include_router(recommendations.router, tags=["recommendations"])
api_router.include_router(approvals.router, tags=["approvals"])
api_router.include_router(workflows.router, tags=["workflows"])

