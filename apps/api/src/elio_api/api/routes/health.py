from typing import Annotated

from fastapi import APIRouter, Depends, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api import __version__
from elio_api.db import get_session
from elio_api.schemas import HealthStatus

router = APIRouter(tags=["health"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/health/live", response_model=HealthStatus)
async def liveness(request: Request) -> HealthStatus:
    """Process is up. Does not touch dependencies."""
    return HealthStatus(
        status="ok",
        service="elio-api",
        version=__version__,
        details={"correlation_id": getattr(request.state, "correlation_id", None)},
    )


@router.get("/health/ready", response_model=HealthStatus)
async def readiness(request: Request, session: SessionDep) -> HealthStatus:
    """Dependencies required to serve traffic. Fails if DB is unreachable."""
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        return HealthStatus(
            status="unavailable",
            service="elio-api",
            version=__version__,
            details={
                "database": "unreachable",
                "correlation_id": getattr(request.state, "correlation_id", None),
            },
        )
    return HealthStatus(
        status="ok",
        service="elio-api",
        version=__version__,
        details={
            "database": "ok",
            "correlation_id": getattr(request.state, "correlation_id", None),
        },
    )
