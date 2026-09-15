from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.identity.auth import AuthContext
from elio_api.identity.deps import SessionDep
from elio_api.sync.service import append_change
from elio_api.work.models import (
    Assignment,
    AuditEntry,
    IdempotencyRecord,
    WorkItem,
    WorkItemTransition,
)
from elio_api.work.state_machine import (
    TERMINAL_STATUSES,
    IllegalTransition,
    WorkCommandType,
    WorkItemStatus,
    apply_transition,
)


class WorkError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.message = message
        self.retryable = retryable
        super().__init__(message)


def request_hash(command_type: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps({"command_type": command_type, "payload": payload}, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


async def load_work_item_tenant(
    session: AsyncSession, *, work_item_id: str, tenant_id: str
) -> WorkItem:
    item = await session.get(WorkItem, work_item_id)
    if item is None:
        raise WorkError("WORK_ITEM_NOT_FOUND", "Work item not found")
    if item.tenant_id != tenant_id:
        # Do not reveal existence across tenants.
        raise WorkError("WORK_ITEM_NOT_FOUND", "Work item not found")
    return item


async def active_assignment(
    session: AsyncSession, *, work_item_id: str, tenant_id: str
) -> Assignment | None:
    from sqlalchemy import select

    result = await session.execute(
        select(Assignment).where(
            Assignment.work_item_id == work_item_id,
            Assignment.tenant_id == tenant_id,
            Assignment.status == "active",
        )
    )
    return result.scalar_one_or_none()


@dataclass(slots=True)
class CommandResult:
    work_item_id: str
    status: str
    version: int
    idempotent_replay: bool = False


async def _load_idempotency(
    session: AsyncSession, *, tenant_id: str, actor_id: str, idempotency_key: str
) -> IdempotencyRecord | None:
    from sqlalchemy import select

    result = await session.execute(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.actor_id == actor_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )
    return result.scalar_one_or_none()


async def _store_idempotency(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str,
    idempotency_key: str,
    command_type: str,
    payload: dict[str, Any],
    status: str,
    result_ref: str,
    result_payload: dict[str, Any],
) -> None:
    session.add(
        IdempotencyRecord(
            tenant_id=tenant_id,
            actor_id=actor_id,
            idempotency_key=idempotency_key,
            command_type=command_type,
            request_hash=request_hash(command_type, payload),
            status=status,
            result_ref=result_ref,
            result_payload=json.dumps(result_payload, sort_keys=True),
        )
    )


async def _write_audit(
    session: AsyncSession,
    *,
    auth: AuthContext,
    action: str,
    aggregate_id: str,
    before_state: dict[str, Any],
    after_state: dict[str, Any],
    reason: str,
    correlation_id: str,
) -> None:
    session.add(
        AuditEntry(
            tenant_id=auth.tenant.id,
            actor_id=auth.actor.id,
            action=action,
            aggregate_type="work_item",
            aggregate_id=aggregate_id,
            before_state=json.dumps(before_state, sort_keys=True),
            after_state=json.dumps(after_state, sort_keys=True),
            policy_version=after_state.get("policy_version", "1"),
            reason=reason,
            correlation_id=correlation_id,
            source="api",
        )
    )


async def create_work_item(
    session: SessionDep,
    auth: AuthContext,
    *,
    work_type: str,
    title: str,
    organisation_id: str | None = None,
    context_ref: str | None = None,
    priority: int = 100,
    idempotency_key: str,
    command_id: str,
    correlation_id: str,
    client_time: datetime | None = None,
) -> CommandResult:
    payload = {
        "work_type": work_type,
        "title": title,
        "organisation_id": organisation_id,
        "context_ref": context_ref,
        "priority": priority,
    }
    existing = await _load_idempotency(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        if existing.request_hash != request_hash("CreateWorkItem", payload):
            # Different payload same key → reject (ADR-005 / contract §6)
            raise WorkError("IDEMPOTENCY_CONFLICT", "Same key used with different payload")
        if existing.result_payload:
            stored = json.loads(existing.result_payload)
            return CommandResult(
                work_item_id=stored["work_item_id"],
                status=stored["status"],
                version=stored["version"],
                idempotent_replay=True,
            )
        raise WorkError("IDEMPOTENCY_CONFLICT", "Incomplete idempotency record", retryable=True)

    item = WorkItem(
        tenant_id=auth.tenant.id,
        organisation_id=organisation_id,
        work_type=work_type,
        domain="hospital",
        status=WorkItemStatus.DRAFT.value,
        priority=priority,
        version=1,
        policy_version="1",
        context_ref=context_ref,
        title=title,
        created_by=auth.actor.id,
    )
    session.add(item)
    await session.flush()

    # Instantiate checklist from active WorkTemplate when one exists for this work_type.
    from elio_api.work.template_service import instantiate_tasks, load_active_template

    template = await load_active_template(
        session, tenant_id=auth.tenant.id, work_type=work_type
    )
    task_count = 0
    if template is not None:
        if template.domain:
            item.domain = template.domain
        item.template_id = template.id
        item.template_version = template.version
        item.outcome_type = None
        tasks = await instantiate_tasks(
            session, tenant_id=auth.tenant.id, work_item=item, template=template
        )
        task_count = len(tasks)

    session.add(
        WorkItemTransition(
            tenant_id=auth.tenant.id,
            work_item_id=item.id,
            from_status="NONE",
            to_status=WorkItemStatus.DRAFT.value,
            command_type="CreateWorkItem",
            actor_id=auth.actor.id,
            reason="created",
            command_id=command_id,
            idempotency_key=idempotency_key,
            version_after=1,
            client_time=client_time,
        )
    )
    await _write_audit(
        session,
        auth=auth,
        action="WorkItemCreated",
        aggregate_id=item.id,
        before_state={},
        after_state={"status": item.status, "version": item.version, "title": title},
        reason="create",
        correlation_id=correlation_id,
    )
    await append_change(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        entity_type="work_item",
        entity_id=item.id,
        event_type="WorkItemCreated",
        payload={
            "work_item_id": item.id,
            "status": item.status,
            "version": item.version,
            "title": title,
            "work_type": work_type,
            "template_id": item.template_id,
            "template_task_count": task_count,
        },
        work_item_id=item.id,
    )

    result_payload = {"work_item_id": item.id, "status": item.status, "version": item.version}
    await _store_idempotency(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        idempotency_key=idempotency_key,
        command_type="CreateWorkItem",
        payload=payload,
        status="accepted",
        result_ref=item.id,
        result_payload=result_payload,
    )
    await session.commit()
    return CommandResult(
        work_item_id=item.id,
        status=item.status,
        version=item.version,
    )


async def _assert_version(item: WorkItem, expected_version: int | None) -> None:
    if expected_version is not None and item.version != expected_version:
        raise WorkError(
            "WORK_VERSION_CONFLICT",
            f"Version mismatch: expected {expected_version}, actual {item.version}",
        )


async def _assert_assignee(
    session: SessionDep, item: WorkItem, auth: AuthContext, *, require_match: bool = True
) -> Assignment:
    assignment = await active_assignment(
        session, work_item_id=item.id, tenant_id=auth.tenant.id
    )
    if assignment is None:
        raise WorkError("NO_ACTIVE_ASSIGNMENT", "Work item has no active assignment")
    if require_match and assignment.assignee_actor_id != auth.actor.id:
        raise WorkError("NOT_ASSIGNEE", "Actor is not the active assignee")
    return assignment


async def execute_work_command(
    session: SessionDep,
    auth: AuthContext,
    *,
    work_item_id: str,
    command: WorkCommandType,
    idempotency_key: str,
    command_id: str,
    correlation_id: str,
    expected_version: int | None = None,
    reason: str = "",
    payload: dict[str, Any] | None = None,
    assignee_actor_id: str | None = None,
    client_time: datetime | None = None,
    allow_direct_complete: bool = False,
) -> CommandResult:
    payload = payload or {}
    existing = await _load_idempotency(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        if existing.request_hash != request_hash(command.value, payload):
            raise WorkError("IDEMPOTENCY_CONFLICT", "Same key used with different payload")
        stored = json.loads(existing.result_payload or "{}")
        return CommandResult(
            work_item_id=stored["work_item_id"],
            status=stored["status"],
            version=stored["version"],
            idempotent_replay=True,
        )

    item = await load_work_item_tenant(
        session, work_item_id=work_item_id, tenant_id=auth.tenant.id
    )
    current = WorkItemStatus(item.status)
    if current in TERMINAL_STATUSES:
        raise WorkError("WORK_ITEM_TERMINAL", f"Work item is terminal: {current.value}")

    await _assert_version(item, expected_version)

    # Authorization edge cases beyond permission bit
    if command == WorkCommandType.ACCEPT or command in {
        WorkCommandType.START,
        WorkCommandType.SUBMIT,
        WorkCommandType.RAISE_EXCEPTION,
        WorkCommandType.WITHDRAW,
        WorkCommandType.RESUME,
    }:
        await _assert_assignee(session, item, auth)
    elif command == WorkCommandType.RESOLVE_EXCEPTION:
        # Assignee or anyone with review/cancel authority may clear a block.
        assignment = await active_assignment(
            session, work_item_id=item.id, tenant_id=auth.tenant.id
        )
        if assignment is not None and assignment.assignee_actor_id == auth.actor.id:
            pass
        else:
            from elio_api.authz.service import actor_has_permission

            can_clear = await actor_has_permission(
                session,
                actor_id=auth.actor.id,
                tenant_id=auth.tenant.id,
                permission="work_item.review",
            ) or await actor_has_permission(
                session,
                actor_id=auth.actor.id,
                tenant_id=auth.tenant.id,
                permission="work_item.cancel",
            )
            if not can_clear:
                raise WorkError(
                    "NOT_ASSIGNEE",
                    "Only the assignee or a supervisor can clear this block",
                )
    elif command == WorkCommandType.COMPLETE_DIRECT and not allow_direct_complete:
        raise WorkError(
            "REVIEW_REQUIRED",
            "Direct completion not allowed for this work type; use review workflow",
        )
    elif command == WorkCommandType.ASSIGN and not assignee_actor_id:
        raise WorkError("ASSIGNEE_REQUIRED", "assignee_actor_id is required")

    if command == WorkCommandType.START and item.started_at is None:
        item.started_at = datetime.now(UTC)

    if command == WorkCommandType.SUBMIT:
        from elio_api.work.anti_abuse import (
            EXCEPTION_OUTCOMES,
            assert_exception_path_allowed,
            assert_minimum_execution,
        )
        from elio_api.work.template_service import evaluate_submit_guard

        outcome_type = payload.get("outcome_type")
        exception_outcome = str(outcome_type or "") in EXCEPTION_OUTCOMES
        await assert_exception_path_allowed(
            session,
            work_item=item,
            outcome_type=outcome_type,
            is_exception_outcome=exception_outcome,
        )
        await assert_minimum_execution(
            item, outcome_type=outcome_type, is_exception_outcome=exception_outcome
        )
        guard = await evaluate_submit_guard(
            session,
            work_item=item,
            outcome_type=str(outcome_type) if outcome_type else None,
            allow_exception_outcome=exception_outcome,
        )
        if not guard.ok:
            detail_bits = []
            if guard.missing_tasks:
                detail_bits.append(
                    "incomplete required tasks: " + ", ".join(guard.missing_tasks)
                )
            if guard.missing_evidence:
                detail_bits.append(
                    "missing evidence: " + ", ".join(guard.missing_evidence)
                )
            raise WorkError(
                "TEMPLATE_INCOMPLETE",
                "; ".join(detail_bits) or "Template requirements not met",
            )
        if outcome_type:
            item.outcome_type = str(outcome_type)
        elif template_default := payload.get("default_outcome"):
            item.outcome_type = str(template_default)

    try:
        transition = apply_transition(current, command)
    except IllegalTransition as exc:
        raise WorkError(
            "ILLEGAL_TRANSITION",
            f"{exc}",
        ) from exc

    before_state = {"status": item.status, "version": item.version}

    if command == WorkCommandType.ASSIGN:
        prior = await active_assignment(
            session, work_item_id=item.id, tenant_id=auth.tenant.id
        )
        if prior is not None:
            raise WorkError("ALREADY_ASSIGNED", "Active assignment already exists")
        assignment = Assignment(
            tenant_id=auth.tenant.id,
            work_item_id=item.id,
            assignee_actor_id=assignee_actor_id or "",
            assigned_by=auth.actor.id,
            status="active",
        )
        session.add(assignment)
        await session.flush()
        item.active_assignment_id = assignment.id
    elif command == WorkCommandType.REASSIGN:
        prior = await active_assignment(
            session, work_item_id=item.id, tenant_id=auth.tenant.id
        )
        if prior is None:
            raise WorkError("NO_ACTIVE_ASSIGNMENT", "No active assignment to reassign")
        if not assignee_actor_id:
            raise WorkError("ASSIGNEE_REQUIRED", "assignee_actor_id is required")
        prior.status = "superseded"
        prior.closed_at = datetime.now(UTC)
        assignment = Assignment(
            tenant_id=auth.tenant.id,
            work_item_id=item.id,
            assignee_actor_id=assignee_actor_id,
            assigned_by=auth.actor.id,
            status="active",
        )
        session.add(assignment)
        await session.flush()
        item.active_assignment_id = assignment.id

    if command == WorkCommandType.RAISE_EXCEPTION:
        from elio_api.work.anti_abuse import record_exception

        await record_exception(
            session,
            tenant_id=auth.tenant.id,
            work_item_id=item.id,
            actor_id=auth.actor.id,
            reason=reason,
        )
    elif command == WorkCommandType.RESOLVE_EXCEPTION:
        from elio_api.work.anti_abuse import resolve_open_exceptions

        await resolve_open_exceptions(
            session,
            work_item_id=item.id,
            resolver_id=auth.actor.id,
            notes=reason or "resolved",
        )

    item.status = transition.to_status.value
    item.version = item.version + 1
    item.updated_at = datetime.now(UTC)

    session.add(
        WorkItemTransition(
            tenant_id=auth.tenant.id,
            work_item_id=item.id,
            from_status=transition.from_status.value,
            to_status=transition.to_status.value,
            command_type=command.value,
            actor_id=auth.actor.id,
            reason=reason,
            command_id=command_id,
            idempotency_key=idempotency_key,
            version_after=item.version,
            client_time=client_time,
        )
    )
    await _write_audit(
        session,
        auth=auth,
        action=command.value,
        aggregate_id=item.id,
        before_state=before_state,
        after_state={"status": item.status, "version": item.version, "policy_version": "1"},
        reason=reason,
        correlation_id=correlation_id,
    )
    await append_change(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        entity_type="work_item",
        entity_id=item.id,
        event_type=command.value,
        payload={
            "work_item_id": item.id,
            "status": item.status,
            "version": item.version,
            "from_status": transition.from_status.value,
            "to_status": transition.to_status.value,
        },
        work_item_id=item.id,
    )

    result_payload = {"work_item_id": item.id, "status": item.status, "version": item.version}
    try:
        await _store_idempotency(
            session,
            tenant_id=auth.tenant.id,
            actor_id=auth.actor.id,
            idempotency_key=idempotency_key,
            command_type=command.value,
            payload=payload,
            status="accepted",
            result_ref=item.id,
            result_payload=result_payload,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise WorkError(
            "IDEMPOTENCY_CONFLICT",
            "Concurrent duplicate command",
            retryable=False,
        ) from exc

    return CommandResult(
        work_item_id=item.id,
        status=item.status,
        version=item.version,
    )
