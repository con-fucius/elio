from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.sync.models import ChangeLog


async def append_change(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str,
    entity_type: str,
    entity_id: str,
    event_type: str,
    payload: dict[str, Any],
    work_item_id: str | None = None,
) -> ChangeLog:
    row = ChangeLog(
        tenant_id=tenant_id,
        actor_id=actor_id,
        work_item_id=work_item_id,
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        payload=json.dumps(payload, sort_keys=True),
    )
    session.add(row)
    await session.flush()
    return row


@dataclass(slots=True)
class ChangePage:
    changes: list[dict[str, Any]]
    next_cursor: int
    has_more: bool


async def read_changes(
    session: AsyncSession,
    *,
    tenant_id: str,
    actor_id: str,
    cursor: int,
    limit: int = 200,
) -> ChangePage:
    """Return tenant-scoped changes after cursor.

    Visibility: a change is included if work_item_id is null (tenant-level)
    or the actor has an assignment (any status) on that work item,
    or the change was authored by this actor.
    """
    from elio_api.work.models import Assignment

    assigned_ids = (
        await session.execute(
            select(Assignment.work_item_id).where(
                Assignment.tenant_id == tenant_id,
                Assignment.assignee_actor_id == actor_id,
            )
        )
    ).scalars().all()
    assigned_set = set(assigned_ids)

    result = await session.execute(
        select(ChangeLog)
        .where(ChangeLog.tenant_id == tenant_id, ChangeLog.sequence > cursor)
        .order_by(ChangeLog.sequence.asc())
        .limit(limit + 1)
    )
    rows = list(result.scalars().all())
    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    visible: list[ChangeLog] = []
    for row in rows:
        if row.work_item_id is None or row.work_item_id in assigned_set or row.actor_id == actor_id:
            visible.append(row)

    # Advance cursor to last scanned sequence so pages with no visible rows still progress.
    scanned_cursor = rows[-1].sequence if rows else cursor

    changes = [
        {
            "sequence": row.sequence,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "event_type": row.event_type,
            "work_item_id": row.work_item_id,
            "payload": json.loads(row.payload),
            "server_event_time": row.server_event_time.isoformat(),
        }
        for row in visible
    ]
    return ChangePage(changes=changes, next_cursor=scanned_cursor, has_more=has_more)
