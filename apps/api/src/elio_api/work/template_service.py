"""WorkTemplate domain: definition, instantiation, checklist completion, submit guards."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from elio_api.identity.auth import AuthContext
from elio_api.sync.service import append_change
from elio_api.work.models import (
    AuditEntry,
    TemplateTask,
    WorkItem,
    WorkTask,
    WorkTemplate,
)
from elio_api.work.service import (
    CommandResult,
    WorkError,
    _assert_assignee,
    _load_idempotency,
    _store_idempotency,
    active_assignment,
    load_work_item_tenant,
    request_hash,
)


def _parse_json_list(raw: str) -> list[str]:
    try:
        value = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [str(v) for v in value]


def _parse_json_dict(raw: str) -> dict[str, object]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    if not isinstance(value, dict):
        return {}
    return value


def _missing_required_fields(task: WorkTask, field_values: dict[str, object]) -> list[str]:
    """Return labels of required form fields that are empty/missing."""
    try:
        defs = json.loads(task.fields_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(defs, list):
        return []
    missing: list[str] = []
    for f in defs:
        if not isinstance(f, dict) or not f.get("required"):
            continue
        key = str(f.get("key") or "")
        label = str(f.get("label") or key or "field")
        val = field_values.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.append(label)
    return missing


async def load_active_template(
    session: AsyncSession, *, tenant_id: str, work_type: str
) -> WorkTemplate | None:
    result = await session.execute(
        select(WorkTemplate)
        .where(
            WorkTemplate.tenant_id == tenant_id,
            WorkTemplate.work_type == work_type,
            WorkTemplate.status == "active",
        )
        .order_by(WorkTemplate.version.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_templates(
    session: AsyncSession, *, tenant_id: str, domain: str | None = None
) -> list[WorkTemplate]:
    query = select(WorkTemplate).where(
        WorkTemplate.tenant_id == tenant_id,
        WorkTemplate.status == "active",
    )
    if domain:
        query = query.where(WorkTemplate.domain == domain)
    query = query.options(selectinload(WorkTemplate.tasks)).order_by(
        WorkTemplate.work_type.asc(), WorkTemplate.version.desc()
    )
    return list((await session.execute(query)).scalars().all())


async def instantiate_tasks(
    session: AsyncSession,
    *,
    tenant_id: str,
    work_item: WorkItem,
    template: WorkTemplate,
) -> list[WorkTask]:
    tasks = (
        await session.execute(
            select(TemplateTask)
            .where(TemplateTask.template_id == template.id)
            .order_by(TemplateTask.sequence.asc())
        )
    ).scalars().all()
    rows: list[WorkTask] = []
    for t in tasks:
        rows.append(
            WorkTask(
                tenant_id=tenant_id,
                work_item_id=work_item.id,
                template_task_id=t.id,
                sequence=t.sequence,
                key=t.key,
                title=t.title,
                description=t.description,
                required=t.required,
                required_evidence_types_json=t.required_evidence_types_json,
                fields_json=t.fields_json or "[]",
                field_values_json="{}",
                status="PENDING",
            )
        )
    session.add_all(rows)
    work_item.template_id = template.id
    work_item.template_version = template.version
    await session.flush()
    return rows


async def list_work_tasks(
    session: AsyncSession, *, work_item_id: str, tenant_id: str
) -> list[WorkTask]:
    result = await session.execute(
        select(WorkTask)
        .where(WorkTask.work_item_id == work_item_id, WorkTask.tenant_id == tenant_id)
        .order_by(WorkTask.sequence.asc())
    )
    return list(result.scalars().all())


@dataclass(slots=True)
class SubmitGuardResult:
    ok: bool
    missing_tasks: list[str]
    missing_evidence: list[str]
    outcome_type: str | None


async def evaluate_submit_guard(
    session: AsyncSession,
    *,
    work_item: WorkItem,
    outcome_type: str | None,
    allow_exception_outcome: bool = False,
) -> SubmitGuardResult:
    """Server-side template rules at SubmitWork. Exception outcomes may bypass checklist."""
    exception_outcomes = {
        "UNABLE_TO_ACCESS",
        "FAILED",
        "PARTIALLY_COMPLETED",
        "BLOCKED",
        "REFERRED",
        "REQUIRES_FOLLOW_UP",
    }
    if allow_exception_outcome and outcome_type in exception_outcomes:
        return SubmitGuardResult(True, [], [], outcome_type)

    tasks = await list_work_tasks(
        session, work_item_id=work_item.id, tenant_id=work_item.tenant_id
    )
    if not tasks:
        return SubmitGuardResult(True, [], [], outcome_type)

    missing_tasks: list[str] = []
    for task in tasks:
        if not task.required:
            continue
        if task.status not in {"COMPLETED", "SKIPPED"}:
            missing_tasks.append(task.title)

    missing_evidence: list[str] = []
    from sqlalchemy import func as sa_func

    from elio_api.evidence.models import Evidence

    for task in tasks:
        if not task.required or task.status == "SKIPPED":
            continue
        required_types = _parse_json_list(task.required_evidence_types_json)
        for etype in required_types:
            count = (
                await session.execute(
                    select(sa_func.count())
                    .select_from(Evidence)
                    .where(
                        Evidence.work_item_id == work_item.id,
                        Evidence.work_task_id == task.id,
                        Evidence.evidence_type == etype,
                        Evidence.verification_status.in_(["UPLOADED", "VERIFIED"]),
                    )
                )
            ).scalar_one()
            if count < 1:
                missing_evidence.append(f"{task.title}: {etype}")

    ok = not missing_tasks and not missing_evidence
    final_outcome = outcome_type
    if ok and work_item.outcome_type is None:
        final_outcome = outcome_type
    return SubmitGuardResult(ok, missing_tasks, missing_evidence, final_outcome)


async def complete_task(
    session: AsyncSession,
    auth: AuthContext,
    *,
    work_item_id: str,
    task_id: str,
    action: str,
    notes: str,
    idempotency_key: str,
    command_id: str,
    correlation_id: str,
    expected_version: int | None = None,
    client_time: datetime | None = None,
    field_values: dict[str, object] | None = None,
) -> CommandResult:
    """action: CompleteTask | SkipTask. Does not change WorkItem state machine."""
    command_type = "CompleteTask" if action == "CompleteTask" else "SkipTask"
    field_values = field_values or {}
    payload = {
        "task_id": task_id,
        "notes": notes,
        "action": action,
        "field_values": field_values,
    }

    existing = await _load_idempotency(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        idempotency_key=idempotency_key,
    )
    if existing is not None:
        if existing.request_hash != request_hash(command_type, payload):
            raise WorkError("IDEMPOTENCY_CONFLICT", "Same key used with different payload")
        stored = json.loads(existing.result_payload or "{}")
        return CommandResult(
            work_item_id=stored.get("work_item_id", work_item_id),
            status=stored.get("status", ""),
            version=int(stored.get("version", 0)),
            idempotent_replay=True,
        )

    item = await load_work_item_tenant(
        session, work_item_id=work_item_id, tenant_id=auth.tenant.id
    )
    if expected_version is not None and item.version != expected_version:
        raise WorkError(
            "WORK_VERSION_CONFLICT",
            f"Version mismatch: expected {expected_version}, actual {item.version}",
        )

    from elio_api.work.state_machine import TERMINAL_STATUSES, WorkItemStatus

    if WorkItemStatus(item.status) in TERMINAL_STATUSES:
        raise WorkError("WORK_ITEM_TERMINAL", f"Work item is terminal: {item.status}")

    editable = {
        "IN_PROGRESS",
        "BLOCKED",
        "ACCEPTED",
        "SUBMITTED",
        "UNDER_REVIEW",
        "REJECTED",
    }
    if item.status not in editable:
        raise WorkError(
            "TASKS_NOT_EDITABLE",
            f"Tasks cannot change in status {item.status}",
        )

    await _assert_assignee(session, item, auth)

    task = await session.get(WorkTask, task_id)
    if task is None or task.tenant_id != auth.tenant.id or task.work_item_id != item.id:
        raise WorkError("TASK_NOT_FOUND", "Task not found")

    if action == "CompleteTask":
        missing_fields = _missing_required_fields(task, field_values)
        if missing_fields:
            raise WorkError(
                "FIELDS_REQUIRED",
                "Required answers missing: " + ", ".join(missing_fields),
            )

    new_status = "COMPLETED" if action == "CompleteTask" else "SKIPPED"
    if task.status == new_status:
        # idempotent no-op at task level still returns success
        pass
    elif action == "SkipTask" and not task.required:
        task.status = "SKIPPED"
    elif action == "SkipTask" and task.required:
        raise WorkError(
            "SKIP_NOT_ALLOWED",
            f"Required task '{task.title}' cannot be skipped",
        )
    else:
        task.status = "COMPLETED"

    task.notes = notes or task.notes
    if field_values:
        task.field_values_json = json.dumps(field_values, sort_keys=True)
    task.completed_by = auth.actor.id
    task.completed_at = datetime.now(UTC)
    task.updated_at = datetime.now(UTC)
    item.updated_at = datetime.now(UTC)

    session.add(
        AuditEntry(
            tenant_id=auth.tenant.id,
            actor_id=auth.actor.id,
            action=command_type,
            aggregate_type="work_task",
            aggregate_id=task.id,
            before_state=None,
            after_state=json.dumps({"status": task.status, "notes": task.notes}),
            policy_version="1",
            reason=notes,
            correlation_id=correlation_id,
            source="api",
        )
    )
    await append_change(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        entity_type="work_task",
        entity_id=task.id,
        event_type=command_type,
        payload={
            "work_item_id": item.id,
            "task_id": task.id,
            "status": task.status,
            "title": task.title,
            "sequence": task.sequence,
        },
        work_item_id=item.id,
    )

    result_payload = {
        "work_item_id": item.id,
        "status": task.status,
        "version": item.version,
        "task_id": task.id,
    }
    await _store_idempotency(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        idempotency_key=idempotency_key,
        command_type=command_type,
        payload=payload,
        status="accepted",
        result_ref=task.id,
        result_payload=result_payload,
    )
    await session.commit()
    return CommandResult(
        work_item_id=item.id,
        status=task.status,
        version=item.version,
    )


async def update_task_draft(
    session: AsyncSession,
    auth: AuthContext,
    *,
    work_item_id: str,
    task_id: str,
    notes: str,
    field_values: dict[str, object] | None,
    expected_version: int | None = None,
) -> CommandResult:
    """Save notes/field answers on a task without completing it. Pre-submit only."""
    item = await load_work_item_tenant(
        session, work_item_id=work_item_id, tenant_id=auth.tenant.id
    )
    if item.status in {"SUBMITTED", "UNDER_REVIEW", "COMPLETED", "CANCELLED", "EXPIRED"}:
        raise WorkError(
            "TASKS_NOT_EDITABLE",
            "This work is past the editing stage",
        )
    if expected_version is not None and item.version != expected_version:
        raise WorkError(
            "WORK_VERSION_CONFLICT",
            "Work was updated on another device. Refresh and try again.",
        )
    await _assert_assignee(session, item, auth)
    task = await session.get(WorkTask, task_id)
    if task is None or task.tenant_id != auth.tenant.id or task.work_item_id != item.id:
        raise WorkError("TASK_NOT_FOUND", "Task not found")
    task.notes = notes
    if field_values is not None:
        task.field_values_json = json.dumps(field_values, sort_keys=True)
    task.updated_at = datetime.now(UTC)
    item.updated_at = datetime.now(UTC)
    await append_change(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        entity_type="work_task",
        entity_id=task.id,
        event_type="TaskDraftSaved",
        payload={
            "work_item_id": item.id,
            "task_id": task.id,
            "status": task.status,
            "title": task.title,
            "sequence": task.sequence,
        },
        work_item_id=item.id,
    )
    await session.commit()
    return CommandResult(work_item_id=item.id, status=task.status, version=item.version)


async def update_work_item_draft(
    session: AsyncSession,
    auth: AuthContext,
    *,
    work_item_id: str,
    title: str,
    expected_version: int | None = None,
) -> CommandResult:
    """Edit work title before submit. Immutable after SUBMITTED."""
    item = await load_work_item_tenant(
        session, work_item_id=work_item_id, tenant_id=auth.tenant.id
    )
    if item.status in {"SUBMITTED", "UNDER_REVIEW", "COMPLETED", "CANCELLED", "EXPIRED"}:
        raise WorkError(
            "WORK_IMMUTABLE",
            "Submitted work can no longer be edited",
        )
    if expected_version is not None and item.version != expected_version:
        raise WorkError(
            "WORK_VERSION_CONFLICT",
            "Work was updated on another device. Refresh and try again.",
        )
    # Creators, assignees, and supervisors may edit pre-submit
    await active_assignment(session, work_item_id=item.id, tenant_id=auth.tenant.id)
    item.title = title.strip()[:255] or item.title
    item.version = item.version + 1
    item.updated_at = datetime.now(UTC)
    await append_change(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        entity_type="work_item",
        entity_id=item.id,
        event_type="WorkItemEdited",
        payload={
            "work_item_id": item.id,
            "title": item.title,
            "status": item.status,
            "version": item.version,
        },
        work_item_id=item.id,
    )
    await session.commit()
    return CommandResult(work_item_id=item.id, status=item.status, version=item.version)


# --- template CRUD (admin) ---

@dataclass(slots=True)
class TemplateDef:
    work_type: str
    domain: str
    title: str
    description: str
    outcome_types: list[str]
    default_outcome_type: str
    review_required: bool
    tasks: list[dict[str, Any]]


async def create_template(
    session: AsyncSession,
    auth: AuthContext,
    definition: TemplateDef,
) -> WorkTemplate:
    existing_active = await load_active_template(
        session, tenant_id=auth.tenant.id, work_type=definition.work_type
    )
    next_version = 1
    if existing_active is not None:
        if existing_active.work_type != definition.work_type:
            next_version = existing_active.version + 1
        else:
            # retire previous active version and bump
            existing_active.status = "retired"
            next_version = existing_active.version + 1

    template = WorkTemplate(
        tenant_id=auth.tenant.id,
        work_type=definition.work_type,
        domain=definition.domain,
        title=definition.title,
        description=definition.description,
        outcome_types_json=json.dumps(definition.outcome_types),
        default_outcome_type=definition.default_outcome_type,
        review_required=definition.review_required,
        version=next_version,
        status="active",
        created_by=auth.actor.id,
    )
    session.add(template)
    await session.flush()

    for i, task in enumerate(definition.tasks, start=1):
        session.add(
            TemplateTask(
                template_id=template.id,
                sequence=i,
                key=str(task["key"]),
                title=str(task["title"]),
                description=str(task.get("description", "")),
                required=bool(task.get("required", True)),
                required_evidence_types_json=json.dumps(
                    task.get("required_evidence_types", [])
                ),
                fields_json=json.dumps(task.get("fields", [])),
            )
        )
    await session.flush()
    await session.commit()
    return template


async def seed_default_tenant_templates(
    session: AsyncSession,
    *,
    tenant_id: str,
    created_by: str,
) -> list[WorkTemplate]:
    """Idempotent seed of baseline templates across hospital, marketing, collections."""
    specs: list[TemplateDef] = [
        TemplateDef(
            work_type="facility_inspection",
            domain="hospital",
            title="Facility inspection",
            description="Non-clinical facility inspection checklist",
            outcome_types=["COMPLETED", "PARTIALLY_COMPLETED", "UNABLE_TO_ACCESS", "FAILED"],
            default_outcome_type="COMPLETED",
            review_required=True,
            tasks=[
                {
                    "key": "arrive",
                    "title": "Confirm you are at the right site",
                    "description": "Check facility name and address before you start work",
                    "required": True,
                    "required_evidence_types": [],
                },
                {
                    "key": "visual_check",
                    "title": "Take a photo of the area",
                    "description": "One clear photo of the ward, room, or equipment area",
                    "required": True,
                    "required_evidence_types": ["photo"],
                },
                {
                    "key": "record_findings",
                    "title": "Record what you found",
                    "description": "Short factual notes only — no patient names or clinical detail",
                    "required": True,
                    "required_evidence_types": [],
                    "fields": [
                        {
                            "key": "summary",
                            "label": "What did you observe?",
                            "type": "text",
                            "required": True,
                        },
                        {
                            "key": "condition",
                            "label": "Overall condition",
                            "type": "choice",
                            "options": ["good", "fair", "poor"],
                            "required": True,
                        },
                        {
                            "key": "area",
                            "label": "Area checked",
                            "type": "text",
                            "required": False,
                        },
                    ],
                },
                {
                    "key": "follow_up",
                    "title": "Need follow-up?",
                    "description": "Only if something needs fixing or a return visit",
                    "required": False,
                    "required_evidence_types": [],
                },
            ],
        ),
        TemplateDef(
            work_type="equipment_service",
            domain="hospital",
            title="Equipment service intervention",
            description="Biomedical/equipment service work card",
            outcome_types=["COMPLETED", "PARTIALLY_COMPLETED", "UNABLE_TO_ACCESS", "FAILED"],
            default_outcome_type="COMPLETED",
            review_required=True,
            tasks=[
                {
                    "key": "verify_asset",
                    "title": "Photo the equipment nameplate",
                    "description": "Clear photo of serial or asset label for this machine",
                    "required": True,
                    "required_evidence_types": ["photo"],
                },
                {
                    "key": "perform_service",
                    "title": "Carry out the service work",
                    "description": "Do the steps listed on the assignment. Note what was done.",
                    "required": True,
                    "required_evidence_types": [],
                    "fields": [
                        {
                            "key": "work_done",
                            "label": "What work did you complete?",
                            "type": "text",
                            "required": True,
                        },
                        {
                            "key": "parts_used",
                            "label": "Parts used (if any)",
                            "type": "text",
                            "required": False,
                        },
                    ],
                },
                {
                    "key": "test_function",
                    "title": "Confirm the equipment works",
                    "description": "Test after service. Record the result in plain words.",
                    "required": True,
                    "required_evidence_types": ["observation"],
                    "fields": [
                        {
                            "key": "result",
                            "label": "Does it work now?",
                            "type": "choice",
                            "options": ["yes", "partially", "no"],
                            "required": True,
                        },
                        {
                            "key": "test_notes",
                            "label": "Test notes",
                            "type": "text",
                            "required": False,
                        },
                    ],
                },
            ],
        ),
        TemplateDef(
            work_type="outlet_visit",
            domain="marketing",
            title="Outlet visit",
            description="Commercial visit to a customer outlet",
            outcome_types=[
                "COMPLETED",
                "PARTIALLY_COMPLETED",
                "UNABLE_TO_ACCESS",
                "FAILED",
            ],
            default_outcome_type="COMPLETED",
            review_required=False,
            tasks=[
                {
                    "key": "check_in",
                    "title": "You are at the right outlet",
                    "description": "Confirm shop name or landmark before you begin",
                    "required": True,
                    "required_evidence_types": [],
                },
                {
                    "key": "activity",
                    "title": "Do the job you were sent for",
                    "description": "Merchandising, order, stock check, or promotion — as assigned",
                    "required": True,
                    "required_evidence_types": [],
                    "fields": [
                        {
                            "key": "activity_type",
                            "label": "What did you complete?",
                            "type": "choice",
                            "options": [
                                "merchandising",
                                "order_capture",
                                "stock_check",
                                "promotion",
                                "follow_up",
                            ],
                            "required": True,
                        },
                        {
                            "key": "outcome_notes",
                            "label": "What happened at the outlet?",
                            "type": "text",
                            "required": True,
                        },
                        {
                            "key": "decision_maker",
                            "label": "Who did you speak to? (role only)",
                            "type": "text",
                            "required": False,
                        },
                    ],
                },
                {
                    "key": "photo_proof",
                    "title": "Photo of shelf or shopfront",
                    "description": "Only if your assignment asks for proof — not every visit",
                    "required": False,
                    "required_evidence_types": ["photo"],
                },
            ],
        ),
        TemplateDef(
            work_type="collection_contact",
            domain="collections",
            title="Authorized collection contact",
            description="Contact attempt under authorised recovery rules only",
            outcome_types=[
                "COMPLETED",
                "PARTIALLY_COMPLETED",
                "UNABLE_TO_ACCESS",
                "FAILED",
            ],
            default_outcome_type="COMPLETED",
            review_required=True,
            tasks=[
                {
                    "key": "verify_context",
                    "title": "Check this is the right case",
                    "description": "Match case reference and allowed action before contact",
                    "required": True,
                    "required_evidence_types": [],
                    "fields": [
                        {
                            "key": "case_ref",
                            "label": "Case reference (as shown on assignment)",
                            "type": "text",
                            "required": True,
                        },
                        {
                            "key": "allowed_action",
                            "label": "Action you are allowed to take",
                            "type": "choice",
                            "options": ["visit", "phone", "letter", "arrangement_discussion"],
                            "required": True,
                        },
                    ],
                },
                {
                    "key": "contact_attempt",
                    "title": "Attempt authorised contact only",
                    "description": "Approved channel only. No third-party debt details.",
                    "required": True,
                    "required_evidence_types": [],
                    "fields": [
                        {
                            "key": "channel",
                            "label": "Channel used",
                            "type": "choice",
                            "options": ["visit", "phone", "letter"],
                            "required": True,
                        },
                        {
                            "key": "result",
                            "label": "Contact result",
                            "type": "choice",
                            "options": [
                                "spoke_with_customer",
                                "no_answer",
                                "wrong_details",
                                "promise_to_pay",
                                "dispute",
                            ],
                            "required": True,
                        },
                        {
                            "key": "spoke_to",
                            "label": "Who did you speak to? (relationship only)",
                            "type": "choice",
                            "options": [
                                "customer",
                                "authorized_representative",
                                "no_one",
                                "other",
                            ],
                            "required": True,
                        },
                    ],
                },
                {
                    "key": "record_followup",
                    "title": "Record the next step",
                    "description": "Promise, dispute, or close. No threats or extra contacts.",
                    "required": True,
                    "required_evidence_types": [],
                    "fields": [
                        {
                            "key": "next_step",
                            "label": "What happens next?",
                            "type": "choice",
                            "options": [
                                "promise_to_pay",
                                "dispute_escalation",
                                "close_no_action",
                                "legal_review",
                            ],
                            "required": True,
                        },
                        {
                            "key": "follow_up_date",
                            "label": "Follow-up date (YYYY-MM-DD) if any",
                            "type": "text",
                            "required": False,
                        },
                    ],
                },
            ],
        ),
    ]

    created: list[WorkTemplate] = []
    for spec in specs:
        existing = await load_active_template(
            session, tenant_id=tenant_id, work_type=spec.work_type
        )
        if existing is not None:
            continue
        template = WorkTemplate(
            tenant_id=tenant_id,
            work_type=spec.work_type,
            domain=spec.domain,
            title=spec.title,
            description=spec.description,
            outcome_types_json=json.dumps(spec.outcome_types),
            default_outcome_type=spec.default_outcome_type,
            review_required=spec.review_required,
            version=1,
            status="active",
            created_by=created_by,
        )
        session.add(template)
        await session.flush()
        for i, task in enumerate(spec.tasks, start=1):
            session.add(
                TemplateTask(
                    template_id=template.id,
                    sequence=i,
                    key=task["key"],
                    title=task["title"],
                    description=task.get("description", ""),
                    required=task["required"],
                    required_evidence_types_json=json.dumps(
                        task.get("required_evidence_types", [])
                    ),
                    fields_json=json.dumps(task.get("fields", [])),
                )
            )
        created.append(template)
    return created


# Back-compat alias
async def seed_default_hospital_templates(
    session: AsyncSession,
    *,
    tenant_id: str,
    created_by: str,
) -> list[WorkTemplate]:
    return await seed_default_tenant_templates(
        session, tenant_id=tenant_id, created_by=created_by
    )
