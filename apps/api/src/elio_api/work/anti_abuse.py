"""Anti-abuse helpers for field work (KE operational reality)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.config import get_settings
from elio_api.evidence.models import Evidence
from elio_api.work.models import WorkException, WorkItem
from elio_api.work.service import WorkError

EXCEPTION_OUTCOMES = frozenset(
    {
        "UNABLE_TO_ACCESS",
        "FAILED",
        "PARTIALLY_COMPLETED",
        "BLOCKED",
        "REFERRED",
        "REQUIRES_FOLLOW_UP",
    }
)


def parse_exception_reason(reason: str) -> tuple[str, str]:
    """UI sends 'category| detail'. Plain text becomes category=other."""
    if "|" in reason:
        category, _, detail = reason.partition("|")
        category = category.strip() or "other"
        detail = detail.strip()
        return category[:64], detail[:2000]
    return "other", (reason or "").strip()[:2000]


async def record_exception(
    session: AsyncSession,
    *,
    tenant_id: str,
    work_item_id: str,
    actor_id: str,
    reason: str,
) -> WorkException:
    category, detail = parse_exception_reason(reason)
    row = WorkException(
        tenant_id=tenant_id,
        work_item_id=work_item_id,
        raised_by=actor_id,
        category=category,
        detail=detail,
        status="OPEN",
    )
    session.add(row)
    item = await session.get(WorkItem, work_item_id)
    if item is not None:
        item.exception_count = (item.exception_count or 0) + 1
    await session.flush()
    return row


async def resolve_open_exceptions(
    session: AsyncSession,
    *,
    work_item_id: str,
    resolver_id: str,
    notes: str,
) -> int:
    rows = (
        await session.execute(
            select(WorkException).where(
                WorkException.work_item_id == work_item_id,
                WorkException.status == "OPEN",
            )
        )
    ).scalars().all()
    now = datetime.now(UTC)
    for r in rows:
        r.status = "RESOLVED"
        r.resolved_by = resolver_id
        r.resolved_at = now
        r.resolution_notes = notes[:2000]
    await session.flush()
    return len(rows)


async def assert_exception_path_allowed(
    session: AsyncSession,
    *,
    work_item: WorkItem,
    outcome_type: str | None,
    is_exception_outcome: bool,
) -> None:
    """Exception-style submit requires a prior open (or just-raised) exception.

    Blocks the common loophole: start → immediately SubmitWork(UNABLE_TO_ACCESS)
    without ever reporting a block through RaiseException.
    """
    if not is_exception_outcome:
        return
    open_count = (
        await session.execute(
            select(WorkException.id)
            .where(
                WorkException.work_item_id == work_item.id,
                WorkException.status == "OPEN",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if open_count is None and (work_item.exception_count or 0) < 1:
        raise WorkError(
            "EXCEPTION_REQUIRED",
            "Report blocked first, then submit this outcome",
        )


async def assert_minimum_execution(
    work_item: WorkItem,
    *,
    outcome_type: str | None,
    is_exception_outcome: bool,
) -> None:
    settings = get_settings()
    if settings.min_execution_seconds <= 0:
        return
    if is_exception_outcome:
        return
    if outcome_type not in {None, "", "COMPLETED"}:
        return
    if work_item.started_at is None:
        return
    started = work_item.started_at
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    elapsed = (datetime.now(UTC) - started).total_seconds()
    if elapsed < settings.min_execution_seconds:
        raise WorkError(
            "EXECUTION_TOO_FAST",
            "Work finished too quickly to be credible — complete the checklist properly",
        )


async def assert_evidence_not_reused(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str,
    work_item_id: str,
    checksum: str,
) -> None:
    settings = get_settings()
    if settings.evidence_reuse_window_hours <= 0:
        return
    cutoff = datetime.now(UTC) - timedelta(hours=settings.evidence_reuse_window_hours)
    prior = (
        await session.execute(
            select(Evidence.id)
            .where(
                Evidence.tenant_id == tenant_id,
                Evidence.captured_by == actor_id,
                Evidence.checksum == checksum,
                Evidence.work_item_id != work_item_id,
                Evidence.received_at_server >= cutoff,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if prior is not None:
        raise EvidenceReuseError(
            "EVIDENCE_REUSED",
            "This file was already used on another assignment — capture a new photo",
        )


class EvidenceReuseError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)
