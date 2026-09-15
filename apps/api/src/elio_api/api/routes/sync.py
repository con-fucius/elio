from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query, Request

from elio_api.identity.auth import AuthContext
from elio_api.identity.deps import AuthDep, SessionDep
from elio_api.sync.schemas import (
    SyncCommandEnvelope,
    SyncCommandResult,
    SyncDownloadResponse,
    SyncUploadBody,
    SyncUploadResponse,
)
from elio_api.sync.service import read_changes
from elio_api.work.service import (
    WorkError,
    create_work_item,
    execute_work_command,
)
from elio_api.work.state_machine import WorkCommandType

router = APIRouter(prefix="/sync", tags=["sync"])

_COMMAND_MAP: dict[str, WorkCommandType] = {
    "ReleaseWork": WorkCommandType.RELEASE,
    "AssignWork": WorkCommandType.ASSIGN,
    "ReassignWork": WorkCommandType.REASSIGN,
    "AcceptAssignment": WorkCommandType.ACCEPT,
    "StartWork": WorkCommandType.START,
    "RaiseException": WorkCommandType.RAISE_EXCEPTION,
    "ResolveException": WorkCommandType.RESOLVE_EXCEPTION,
    "SubmitWork": WorkCommandType.SUBMIT,
    "WithdrawSubmission": WorkCommandType.WITHDRAW,
    "BeginReview": WorkCommandType.BEGIN_REVIEW,
    "AcceptReview": WorkCommandType.ACCEPT_REVIEW,
    "RejectSubmission": WorkCommandType.REJECT_REVIEW,
    "ReturnToWorker": WorkCommandType.RETURN_TO_WORKER,
    "ResumeWork": WorkCommandType.RESUME,
    "CancelWork": WorkCommandType.CANCEL,
}


def _correlation(request: Request) -> str:
    return getattr(request.state, "correlation_id", "") or ""


def _map_work_error(exc: WorkError) -> SyncCommandResult:
    status_map = {
        "WORK_ITEM_NOT_FOUND": "rejected",
        "NOT_ASSIGNEE": "rejected",
        "NO_ACTIVE_ASSIGNMENT": "conflict",
        "ILLEGAL_TRANSITION": "conflict",
        "WORK_ITEM_TERMINAL": "conflict",
        "WORK_VERSION_CONFLICT": "conflict",
        "IDEMPOTENCY_CONFLICT": "rejected",
        "ALREADY_ASSIGNED": "conflict",
        "REVIEW_REQUIRED": "rejected",
        "ASSIGNEE_REQUIRED": "rejected",
        "TEMPLATE_INCOMPLETE": "rejected",
        "TASKS_NOT_EDITABLE": "conflict",
        "TASK_NOT_FOUND": "rejected",
        "SKIP_NOT_ALLOWED": "rejected",
    }
    return SyncCommandResult(
        command_id="",
        status=status_map.get(exc.code, "rejected"),
        reason_code=exc.code,
        message=exc.message,
        retryable=exc.retryable,
    )


async def _apply_one(
    session: SessionDep,
    auth: AuthContext,
    cmd: SyncCommandEnvelope,
    request: Request,
) -> SyncCommandResult:
    payload = dict(cmd.payload)
    try:
        if cmd.command_type == "CreateWorkItem":
            result = await create_work_item(
                session,
                auth,
                work_type=str(payload.get("work_type", "")),
                title=str(payload.get("title", "")),
                organisation_id=payload.get("organisation_id"),
                context_ref=payload.get("context_ref"),
                priority=int(payload.get("priority", 100)),
                idempotency_key=cmd.idempotency_key,
                command_id=cmd.command_id,
                correlation_id=_correlation(request),
                client_time=cmd.client_created_at,
            )
            return SyncCommandResult(
                command_id=cmd.command_id,
                status="accepted",
                work_item_id=result.work_item_id,
                work_item_status=result.status,
                version=result.version,
                idempotent_replay=result.idempotent_replay,
            )

        if cmd.command_type in {"CompleteTask", "SkipTask"}:
            from elio_api.work.template_service import complete_task as complete_task_svc

            task_id = str(payload.get("task_id") or "")
            if not task_id or not cmd.aggregate_id:
                return SyncCommandResult(
                    command_id=cmd.command_id,
                    status="rejected",
                    reason_code="TASK_ID_REQUIRED",
                    message="task_id and aggregate_id (work item) are required",
                )
            result = await complete_task_svc(
                session,
                auth,
                work_item_id=cmd.aggregate_id,
                task_id=task_id,
                action=cmd.command_type,
                notes=str(payload.get("notes", "")),
                idempotency_key=cmd.idempotency_key,
                command_id=cmd.command_id,
                correlation_id=_correlation(request),
                expected_version=payload.get("expected_version"),
                client_time=cmd.client_created_at,
            )
            # complete_task returns task status; re-read work item for authoritative status
            from elio_api.work.service import load_work_item_tenant

            work = await load_work_item_tenant(
                session, work_item_id=result.work_item_id, tenant_id=auth.tenant.id
            )
            return SyncCommandResult(
                command_id=cmd.command_id,
                status="accepted",
                work_item_id=result.work_item_id,
                work_item_status=work.status,
                version=work.version,
                idempotent_replay=result.idempotent_replay,
            )

        command = _COMMAND_MAP.get(cmd.command_type)
        if command is None or not cmd.aggregate_id:
            return SyncCommandResult(
                command_id=cmd.command_id,
                status="rejected",
                reason_code="UNKNOWN_COMMAND",
                message=f"Unsupported command_type: {cmd.command_type}",
            )

        result = await execute_work_command(
            session,
            auth,
            work_item_id=cmd.aggregate_id,
            command=command,
            idempotency_key=cmd.idempotency_key,
            command_id=cmd.command_id,
            correlation_id=_correlation(request),
            expected_version=payload.get("expected_version"),
            reason=str(payload.get("reason", "")),
            assignee_actor_id=payload.get("assignee_actor_id"),
            client_time=cmd.client_created_at,
        )
        return SyncCommandResult(
            command_id=cmd.command_id,
            status="accepted",
            work_item_id=result.work_item_id,
            work_item_status=result.status,
            version=result.version,
            idempotent_replay=result.idempotent_replay,
        )
    except WorkError as exc:
        await session.rollback()
        mapped = _map_work_error(exc)
        mapped.command_id = cmd.command_id
        return mapped
    except Exception:
        await session.rollback()
        raise


@router.post("/commands", response_model=SyncUploadResponse)
async def upload_commands(
    body: SyncUploadBody,
    request: Request,
    auth: AuthDep,
    session: SessionDep,
) -> SyncUploadResponse:
    """Bounded batch upload. Per-command results — never all-or-nothing (ADR-005)."""
    results: list[SyncCommandResult] = []
    # Process sequentially inside one request; each command manages its own commit.
    # Isolation: commands are independent aggregates; failures do not roll back prior accepts.
    for cmd in body.commands:
        # Use a nested session approach: same session commits per command in service.
        result = await _apply_one(session, auth, cmd, request)
        results.append(result)
    return SyncUploadResponse(results=results)


@router.get("/changes", response_model=SyncDownloadResponse)
async def download_changes(
    auth: AuthDep,
    session: SessionDep,
    cursor: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
) -> SyncDownloadResponse:
    page = await read_changes(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        cursor=cursor,
        limit=limit,
    )
    return SyncDownloadResponse(
        changes=page.changes,
        next_cursor=page.next_cursor,
        has_more=page.has_more,
    )
