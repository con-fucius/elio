from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from elio_api.authz.permissions import PermissionCode
from elio_api.identity.auth import AuthContext
from elio_api.identity.deps import SessionDep, require_permission
from elio_api.work.models import WorkItem, WorkTask, WorkTemplate
from elio_api.work.service import (
    WorkError,
    create_work_item,
    execute_work_command,
    load_work_item_tenant,
)
from elio_api.work.state_machine import WorkCommandType

router = APIRouter(prefix="/work-items", tags=["work-items"])


class CreateWorkItemBody(BaseModel):
    work_type: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    organisation_id: str | None = None
    context_ref: str | None = Field(default=None, max_length=255)
    priority: int = Field(default=100, ge=0, le=1000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    command_id: str | None = None
    client_time: datetime | None = None


class CommandBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    command_id: str | None = None
    expected_version: int | None = Field(default=None, ge=1)
    reason: str = Field(default="", max_length=2000)
    assignee_actor_id: str | None = None
    outcome_type: str | None = Field(default=None, max_length=64)
    client_time: datetime | None = None


class CommandResponse(BaseModel):
    work_item_id: str
    status: str
    version: int
    idempotent_replay: bool = False


class WorkItemRead(BaseModel):
    id: str
    tenant_id: str
    work_type: str
    domain: str
    status: str
    priority: int
    version: int
    title: str
    context_ref: str | None
    active_assignment_id: str | None
    template_id: str | None = None
    template_version: int | None = None
    outcome_type: str | None = None
    exception_count: int = 0
    created_at: datetime


class WorkTaskRead(BaseModel):
    id: str
    work_item_id: str
    sequence: int
    key: str
    title: str
    description: str
    required: bool
    required_evidence_types: list[str]
    fields: list[dict[str, object]] = Field(default_factory=list)
    field_values: dict[str, object] = Field(default_factory=dict)
    status: str
    notes: str


class TaskCommandBody(BaseModel):
    idempotency_key: str = Field(min_length=8, max_length=128)
    command_id: str | None = None
    notes: str = Field(default="", max_length=4000)
    field_values: dict[str, object] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)
    client_time: datetime | None = None


class TaskDraftBody(BaseModel):
    notes: str = Field(default="", max_length=4000)
    field_values: dict[str, object] = Field(default_factory=dict)
    expected_version: int | None = Field(default=None, ge=1)


class WorkEditBody(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    expected_version: int | None = Field(default=None, ge=1)


class TemplateTaskCreate(BaseModel):
    key: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    required: bool = True
    required_evidence_types: list[str] = Field(default_factory=list)
    fields: list[dict[str, object]] = Field(default_factory=list)


class TemplateCreateBody(BaseModel):
    work_type: str = Field(min_length=1, max_length=64)
    domain: str = Field(default="hospital", max_length=32)
    title: str = Field(min_length=1, max_length=255)
    description: str = ""
    outcome_types: list[str] = Field(default_factory=lambda: ["COMPLETED", "FAILED"])
    default_outcome_type: str = "COMPLETED"
    review_required: bool = True
    tasks: list[TemplateTaskCreate] = Field(min_length=1)


class TemplateRead(BaseModel):
    id: str
    work_type: str
    domain: str
    title: str
    description: str
    outcome_types: list[str]
    default_outcome_type: str
    review_required: bool
    version: int
    status: str
    tasks: list[WorkTaskRead]


def _correlation(request: Request) -> str:
    return getattr(request.state, "correlation_id", "") or ""


def _headers(
    idempotency_key: str,
    x_command_id: str | None,
) -> tuple[str, str]:
    command_id = x_command_id or str(uuid.uuid4())
    return idempotency_key, command_id


def _work_error(exc: WorkError) -> HTTPException:
    code = status.HTTP_409_CONFLICT
    if exc.code in {"WORK_ITEM_NOT_FOUND"}:
        code = status.HTTP_404_NOT_FOUND
    elif exc.code in {"NOT_ASSIGNEE", "PERMISSION_DENIED"}:
        code = status.HTTP_403_FORBIDDEN
    elif exc.code in {
        "ILLEGAL_TRANSITION",
        "IDEMPOTENCY_CONFLICT",
        "WORK_VERSION_CONFLICT",
        "ALREADY_ASSIGNED",
        "WORK_ITEM_TERMINAL",
        "REVIEW_REQUIRED",
        "ASSIGNEE_REQUIRED",
        "NO_ACTIVE_ASSIGNMENT",
        "TEMPLATE_INCOMPLETE",
        "TASKS_NOT_EDITABLE",
        "TASK_NOT_FOUND",
        "SKIP_NOT_ALLOWED",
        "FIELDS_REQUIRED",
        "WORK_IMMUTABLE",
        "EXCEPTION_REQUIRED",
        "EXECUTION_TOO_FAST",
    }:
        code = status.HTTP_409_CONFLICT
    return HTTPException(
        status_code=code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "correlation_id": None,
            "retryable": exc.retryable,
        },
    )


async def _result_from_body(
    session: SessionDep,
    auth: AuthContext,
    *,
    body: CommandBody,
    command: WorkCommandType,
    work_item_id: str,
    request: Request,
    assignee_actor_id: str | None = None,
) -> CommandResponse:
    command_id = body.command_id or str(uuid.uuid4())
    payload: dict[str, object] = {}
    if body.outcome_type:
        payload["outcome_type"] = body.outcome_type
    try:
        result = await execute_work_command(
            session,
            auth,
            work_item_id=work_item_id,
            command=command,
            idempotency_key=body.idempotency_key,
            command_id=command_id,
            correlation_id=_correlation(request),
            expected_version=body.expected_version,
            reason=body.reason,
            assignee_actor_id=assignee_actor_id,
            client_time=body.client_time,
            payload=payload,
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    return CommandResponse(
        work_item_id=result.work_item_id,
        status=result.status,
        version=result.version,
        idempotent_replay=result.idempotent_replay,
    )


@router.post("", response_model=CommandResponse, status_code=status.HTTP_201_CREATED)
async def create_work(
    body: CreateWorkItemBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_CREATE))],
) -> CommandResponse:
    command_id = body.command_id or str(uuid.uuid4())
    try:
        result = await create_work_item(
            session,
            auth,
            work_type=body.work_type,
            title=body.title,
            organisation_id=body.organisation_id,
            context_ref=body.context_ref,
            priority=body.priority,
            idempotency_key=body.idempotency_key,
            command_id=command_id,
            correlation_id=_correlation(request),
            client_time=body.client_time,
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    return CommandResponse(
        work_item_id=result.work_item_id,
        status=result.status,
        version=result.version,
        idempotent_replay=result.idempotent_replay,
    )


@router.get("/{work_item_id}", response_model=WorkItemRead)
async def get_work_item(
    work_item_id: str,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_READ))],
) -> WorkItemRead:
    try:
        item = await load_work_item_tenant(
            session, work_item_id=work_item_id, tenant_id=auth.tenant.id
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    return WorkItemRead(
        id=item.id,
        tenant_id=item.tenant_id,
        work_type=item.work_type,
        domain=item.domain,
        status=item.status,
        priority=item.priority,
        version=item.version,
        title=item.title,
        context_ref=item.context_ref,
        active_assignment_id=item.active_assignment_id,
        template_id=item.template_id,
        template_version=item.template_version,
        outcome_type=item.outcome_type,
        exception_count=item.exception_count or 0,
        created_at=item.created_at,
    )


@router.get("", response_model=list[WorkItemRead])
async def list_work_items(
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_READ))],
    status_filter: Literal["active", "all"] = "active",
    assigned_to: Literal["me", "any"] = "any",
) -> list[WorkItemRead]:
    """Tenant-scoped list. assigned_to=me filters by active or historical assignment."""
    query = select(WorkItem).where(WorkItem.tenant_id == auth.tenant.id)
    if status_filter == "active":
        query = query.where(
            WorkItem.status.notin_(
                ["COMPLETED", "CANCELLED", "EXPIRED"],
            )
        )
    if assigned_to == "me":
        from elio_api.work.models import Assignment

        query = (
            query.join(Assignment, Assignment.work_item_id == WorkItem.id)
            .where(
                Assignment.tenant_id == auth.tenant.id,
                Assignment.assignee_actor_id == auth.actor.id,
            )
            .distinct()
        )
    query = query.order_by(WorkItem.created_at.desc()).limit(200)
    rows = (await session.execute(query)).scalars().all()
    return [
        WorkItemRead(
            id=item.id,
            tenant_id=item.tenant_id,
            work_type=item.work_type,
            domain=item.domain,
            status=item.status,
            priority=item.priority,
            version=item.version,
            title=item.title,
            context_ref=item.context_ref,
            active_assignment_id=item.active_assignment_id,
            template_id=item.template_id,
            template_version=item.template_version,
            outcome_type=item.outcome_type,
            exception_count=item.exception_count or 0,
            created_at=item.created_at,
        )
        for item in rows
    ]


@router.post("/{work_item_id}/release", response_model=CommandResponse)
async def release_work(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_CREATE))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.RELEASE,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/assign", response_model=CommandResponse)
async def assign_work(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_ASSIGN))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.ASSIGN,
        work_item_id=work_item_id,
        request=request,
        assignee_actor_id=body.assignee_actor_id,
    )


@router.post("/{work_item_id}/accept", response_model=CommandResponse)
async def accept_work(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_ACCEPT))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.ACCEPT,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/start", response_model=CommandResponse)
async def start_work(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.START,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/exception", response_model=CommandResponse)
async def raise_exception(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXCEPTION))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.RAISE_EXCEPTION,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/unblock", response_model=CommandResponse)
async def resolve_exception(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXCEPTION))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.RESOLVE_EXCEPTION,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/submit", response_model=CommandResponse)
async def submit_work(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_SUBMIT))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.SUBMIT,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/withdraw", response_model=CommandResponse)
async def withdraw_submission(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_WITHDRAW))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.WITHDRAW,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/review/begin", response_model=CommandResponse)
async def begin_review(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_REVIEW))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.BEGIN_REVIEW,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/review/accept", response_model=CommandResponse)
async def accept_review(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_REVIEW))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.ACCEPT_REVIEW,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/review/reject", response_model=CommandResponse)
async def reject_review(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_REVIEW))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.REJECT_REVIEW,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/resume", response_model=CommandResponse)
async def resume_work(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.RESUME,
        work_item_id=work_item_id,
        request=request,
    )


@router.post("/{work_item_id}/cancel", response_model=CommandResponse)
async def cancel_work(
    work_item_id: str,
    body: CommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_CANCEL))],
) -> CommandResponse:
    return await _result_from_body(
        session,
        auth,
        body=body,
        command=WorkCommandType.CANCEL,
        work_item_id=work_item_id,
        request=request,
    )


def _task_read(t: WorkTask) -> WorkTaskRead:
    import json as _j

    from elio_api.work.template_service import _parse_json_dict, _parse_json_list

    try:
        fields_raw = _j.loads(t.fields_json or "[]")
        fields: list[dict[str, object]] = (
            fields_raw if isinstance(fields_raw, list) else []
        )
    except _j.JSONDecodeError:
        fields = []
    field_values = _parse_json_dict(t.field_values_json)
    return WorkTaskRead(
        id=t.id,
        work_item_id=t.work_item_id,
        sequence=t.sequence,
        key=t.key,
        title=t.title,
        description=t.description,
        required=t.required,
        required_evidence_types=_parse_json_list(t.required_evidence_types_json),
        fields=fields,
        field_values=field_values,
        status=t.status,
        notes=t.notes,
    )


@router.get("/{work_item_id}/tasks", response_model=list[WorkTaskRead])
async def list_work_tasks(
    work_item_id: str,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_READ))],
) -> list[WorkTaskRead]:
    from elio_api.work.template_service import list_work_tasks as _list

    try:
        item = await load_work_item_tenant(
            session, work_item_id=work_item_id, tenant_id=auth.tenant.id
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    tasks = await _list(session, work_item_id=item.id, tenant_id=auth.tenant.id)
    return [_task_read(t) for t in tasks]


@router.post("/{work_item_id}/tasks/{task_id}/complete", response_model=CommandResponse)
async def complete_task(
    work_item_id: str,
    task_id: str,
    body: TaskCommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> CommandResponse:
    from elio_api.work.template_service import complete_task as _complete

    command_id = body.command_id or str(uuid.uuid4())
    try:
        result = await _complete(
            session,
            auth,
            work_item_id=work_item_id,
            task_id=task_id,
            action="CompleteTask",
            notes=body.notes,
            idempotency_key=body.idempotency_key,
            command_id=command_id,
            correlation_id=_correlation(request),
            expected_version=body.expected_version,
            client_time=body.client_time,
            field_values=body.field_values,
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    return CommandResponse(
        work_item_id=result.work_item_id,
        status=result.status,
        version=result.version,
    )


@router.patch("/{work_item_id}", response_model=CommandResponse)
async def edit_work_item(
    work_item_id: str,
    body: WorkEditBody,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> CommandResponse:
    from elio_api.work.template_service import update_work_item_draft

    try:
        result = await update_work_item_draft(
            session,
            auth,
            work_item_id=work_item_id,
            title=body.title,
            expected_version=body.expected_version,
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    return CommandResponse(
        work_item_id=result.work_item_id,
        status=result.status,
        version=result.version,
    )


@router.patch("/{work_item_id}/tasks/{task_id}", response_model=CommandResponse)
async def edit_task_draft(
    work_item_id: str,
    task_id: str,
    body: TaskDraftBody,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> CommandResponse:
    from elio_api.work.template_service import update_task_draft

    try:
        result = await update_task_draft(
            session,
            auth,
            work_item_id=work_item_id,
            task_id=task_id,
            notes=body.notes,
            field_values=body.field_values,
            expected_version=body.expected_version,
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    return CommandResponse(
        work_item_id=result.work_item_id,
        status=result.status,
        version=result.version,
    )


@router.post("/{work_item_id}/tasks/{task_id}/skip", response_model=CommandResponse)
async def skip_task(
    work_item_id: str,
    task_id: str,
    body: TaskCommandBody,
    request: Request,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.WORK_ITEM_EXECUTE))],
) -> CommandResponse:
    from elio_api.work.template_service import complete_task as _complete

    command_id = body.command_id or str(uuid.uuid4())
    try:
        result = await _complete(
            session,
            auth,
            work_item_id=work_item_id,
            task_id=task_id,
            action="SkipTask",
            notes=body.notes,
            idempotency_key=body.idempotency_key,
            command_id=command_id,
            correlation_id=_correlation(request),
            expected_version=body.expected_version,
            client_time=body.client_time,
        )
    except WorkError as exc:
        raise _work_error(exc) from exc
    # Return authoritative work-item status, not task status
    work = await load_work_item_tenant(
        session, work_item_id=result.work_item_id, tenant_id=auth.tenant.id
    )
    return CommandResponse(
        work_item_id=result.work_item_id,
        status=work.status,
        version=work.version,
    )


def _template_read(t: WorkTemplate) -> TemplateRead:
    import json as _json

    def _loads(raw: str) -> list[str]:
        try:
            v = _json.loads(raw or "[]")
            return [str(x) for x in v] if isinstance(v, list) else []
        except _json.JSONDecodeError:
            return []

    def _loads_any(raw: str) -> object:
        try:
            return _json.loads(raw or "[]")
        except _json.JSONDecodeError:
            return []

    tasks = []
    for task in t.tasks or []:
        fields_raw = _loads_any(task.fields_json)
        fields = fields_raw if isinstance(fields_raw, list) else []
        tasks.append(
            WorkTaskRead(
                id=task.id,
                work_item_id="",
                sequence=task.sequence,
                key=task.key,
                title=task.title,
                description=task.description,
                required=task.required,
                required_evidence_types=_loads(task.required_evidence_types_json),
                fields=fields,
                field_values={},
                status="PENDING",
                notes="",
            )
        )
    return TemplateRead(
        id=t.id,
        work_type=t.work_type,
        domain=t.domain,
        title=t.title,
        description=t.description,
        outcome_types=_loads(t.outcome_types_json),
        default_outcome_type=t.default_outcome_type,
        review_required=t.review_required,
        version=t.version,
        status=t.status,
        tasks=tasks,
    )


# Templates API (separate prefix via include in main)
templates_router = APIRouter(prefix="/templates", tags=["work-templates"])


@templates_router.get("", response_model=list[TemplateRead])
async def list_templates(
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.TEMPLATE_READ))],
    domain: str | None = None,
) -> list[TemplateRead]:
    from elio_api.work.template_service import list_templates as _list

    rows = await _list(session, tenant_id=auth.tenant.id, domain=domain)
    return [_template_read(t) for t in rows]


@templates_router.post("", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateCreateBody,
    session: SessionDep,
    auth: Annotated[AuthContext, Depends(require_permission(PermissionCode.TEMPLATE_MANAGE))],
) -> TemplateRead:
    from elio_api.work.template_service import TemplateDef
    from elio_api.work.template_service import create_template as _create

    definition = TemplateDef(
        work_type=body.work_type,
        domain=body.domain,
        title=body.title,
        description=body.description,
        outcome_types=body.outcome_types,
        default_outcome_type=body.default_outcome_type,
        review_required=body.review_required,
        tasks=[t.model_dump() for t in body.tasks],
    )
    template = await _create(session, auth, definition)
    from sqlalchemy.orm import selectinload

    reloaded = (
        await session.execute(
            select(WorkTemplate)
            .options(selectinload(WorkTemplate.tasks))
            .where(WorkTemplate.id == template.id)
        )
    ).scalar_one()
    return _template_read(reloaded)

