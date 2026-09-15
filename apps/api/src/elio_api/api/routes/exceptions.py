from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from elio_api.authz.permissions import PermissionCode
from elio_api.identity.auth import AuthContext
from elio_api.identity.deps import SessionDep, require_permission
from elio_api.work.models import WorkException
from elio_api.work.service import load_work_item_tenant

router = APIRouter(tags=["exceptions"])


class ExceptionRead(BaseModel):
    id: str
    work_item_id: str
    category: str
    detail: str
    status: str
    raised_by: str
    raised_at: datetime
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_notes: str


@router.get(
    "/work-items/{work_item_id}/exceptions",
    response_model=list[ExceptionRead],
)
async def list_work_exceptions(
    work_item_id: str,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_READ))],
    open_only: bool = False,
) -> list[ExceptionRead]:
    from elio_api.work.service import WorkError

    try:
        item = await load_work_item_tenant(
            session, work_item_id=work_item_id, tenant_id=auth.tenant.id
        )
    except WorkError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message, "retryable": False},
        ) from exc

    query = select(WorkException).where(
        WorkException.work_item_id == item.id,
        WorkException.tenant_id == auth.tenant.id,
    )
    if open_only:
        query = query.where(WorkException.status == "OPEN")
    query = query.order_by(WorkException.raised_at.desc())
    rows = (await session.execute(query)).scalars().all()
    return [
        ExceptionRead(
            id=r.id,
            work_item_id=r.work_item_id,
            category=r.category,
            detail=r.detail,
            status=r.status,
            raised_by=r.raised_by,
            raised_at=r.raised_at,
            resolved_by=r.resolved_by,
            resolved_at=r.resolved_at,
            resolution_notes=r.resolution_notes,
        )
        for r in rows
    ]
