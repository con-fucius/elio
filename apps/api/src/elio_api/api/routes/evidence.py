from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from elio_api.authz.permissions import PermissionCode
from elio_api.config import get_settings
from elio_api.evidence.service import (
    EvidenceError,
    LocalEvidenceStore,
    read_evidence_bytes,
    register_evidence,
    upload_evidence_content,
)
from elio_api.identity.auth import AuthContext
from elio_api.identity.deps import SessionDep, require_permission

router = APIRouter(tags=["evidence"])


def _store() -> LocalEvidenceStore:
    return LocalEvidenceStore(root=Path(get_settings().evidence_root))


class RegisterEvidenceBody(BaseModel):
    work_item_id: str
    evidence_type: str = Field(min_length=1, max_length=64)
    captured_at_client: datetime | None = None
    device_session_id: str | None = None
    work_task_id: str | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class EvidenceRead(BaseModel):
    id: str
    work_item_id: str
    work_task_id: str | None = None
    evidence_type: str
    verification_status: str
    content_type: str
    size_bytes: int | None
    checksum: str | None
    captured_at_client: datetime | None
    received_at_server: datetime


@router.get(
    "/work-items/{work_item_id}/evidence",
    response_model=list[EvidenceRead],
)
async def list_evidence(
    work_item_id: str,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_READ))],
) -> list[EvidenceRead]:
    from elio_api.evidence.service import list_evidence_for_work
    from elio_api.work.service import WorkError

    try:
        rows = await list_evidence_for_work(session, auth, work_item_id=work_item_id)
    except WorkError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": exc.code, "message": exc.message, "retryable": False},
        ) from exc
    return [
        EvidenceRead(
            id=e.id,
            work_item_id=e.work_item_id,
            work_task_id=e.work_task_id,
            evidence_type=e.evidence_type,
            verification_status=e.verification_status,
            content_type=e.content_type,
            size_bytes=e.size_bytes,
            checksum=e.checksum,
            captured_at_client=e.captured_at_client,
            received_at_server=e.received_at_server,
        )
        for e in rows
    ]


def _evidence_error(exc: EvidenceError) -> HTTPException:
    status_code = status.HTTP_409_CONFLICT
    if exc.code in {"EVIDENCE_NOT_FOUND"}:
        status_code = status.HTTP_404_NOT_FOUND
    elif exc.code in {"NOT_CAPTURE_OWNER", "EVIDENCE_ACCESS_DENIED"}:
        status_code = status.HTTP_403_FORBIDDEN
    elif exc.code in {"EVIDENCE_TOO_SMALL", "EVIDENCE_REUSED"}:
        status_code = getattr(status, "HTTP_422_UNPROCESSABLE_CONTENT", 422)
    return HTTPException(
        status_code=status_code,
        detail={"code": exc.code, "message": exc.message, "retryable": False},
    )


@router.post(
    "/work-items/{work_item_id}/evidence",
    response_model=EvidenceRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_evidence(
    work_item_id: str,
    body: RegisterEvidenceBody,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> EvidenceRead:
    if body.work_item_id != work_item_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PATH_BODY_MISMATCH",
                "message": "work_item_id in path and body must match",
                "retryable": False,
            },
        )
    try:
        evidence = await register_evidence(
            session,
            auth,
            work_item_id=work_item_id,
            evidence_type=body.evidence_type,
            metadata=body.metadata,
            captured_at_client=body.captured_at_client,
            device_session_id=body.device_session_id,
            work_task_id=body.work_task_id,
        )
    except EvidenceError as exc:
        raise _evidence_error(exc) from exc
    except Exception as exc:
        # WorkError from load_work_item_tenant
        from elio_api.work.service import WorkError

        if isinstance(exc, WorkError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": exc.code, "message": exc.message, "retryable": False},
            ) from exc
        raise
    return EvidenceRead(
        id=evidence.id,
        work_item_id=evidence.work_item_id,
        evidence_type=evidence.evidence_type,
        verification_status=evidence.verification_status,
        content_type=evidence.content_type,
        size_bytes=evidence.size_bytes,
        checksum=evidence.checksum,
        captured_at_client=evidence.captured_at_client,
        received_at_server=evidence.received_at_server,
    )


@router.put("/evidence/{evidence_id}/content", response_model=EvidenceRead)
async def put_evidence_content(
    evidence_id: str,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> EvidenceRead:
    data = await request.body()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "EMPTY_BODY",
                "message": "Evidence content body is empty",
                "retryable": False,
            },
        )
    content_type = request.headers.get("content-type", "application/octet-stream")
    try:
        evidence = await upload_evidence_content(
            session,
            auth,
            _store(),
            evidence_id=evidence_id,
            data=data,
            content_type=content_type,
        )
    except EvidenceError as exc:
        raise _evidence_error(exc) from exc
    return EvidenceRead(
        id=evidence.id,
        work_item_id=evidence.work_item_id,
        evidence_type=evidence.evidence_type,
        verification_status=evidence.verification_status,
        content_type=evidence.content_type,
        size_bytes=evidence.size_bytes,
        checksum=evidence.checksum,
        captured_at_client=evidence.captured_at_client,
        received_at_server=evidence.received_at_server,
    )


@router.get("/evidence/{evidence_id}/content")
async def get_evidence_content(
    evidence_id: str,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_READ))],
) -> Response:
    try:
        evidence, data = await read_evidence_bytes(
            session, auth, _store(), evidence_id=evidence_id
        )
    except EvidenceError as exc:
        raise _evidence_error(exc) from exc
    return Response(
        content=data,
        media_type=evidence.content_type,
        headers={
            "X-Evidence-Checksum": evidence.checksum or "",
            "X-Evidence-Status": evidence.verification_status,
        },
    )
