from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from elio_api.authz.service import actor_has_permission
from elio_api.evidence.models import Evidence
from elio_api.identity.auth import AuthContext
from elio_api.work.models import Assignment, WorkItem
from elio_api.work.service import load_work_item_tenant


class EvidenceError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass(slots=True)
class LocalEvidenceStore:
    """Content-addressed local object store. S3-compatible backend can replace this later
    without changing the evidence domain model (storage_reference stays the key)."""

    root: Path

    def ensure_tenant_root(self, tenant_id: str) -> Path:
        path = self.root / tenant_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def path_for(self, tenant_id: str, checksum: str) -> Path:
        return self.ensure_tenant_root(tenant_id) / checksum

    def object_key(self, tenant_id: str, checksum: str) -> str:
        return f"{tenant_id}/{checksum}"

    def write(self, tenant_id: str, checksum: str, data: bytes) -> Path:
        target = self.path_for(tenant_id, checksum)
        tmp = target.with_suffix(".partial")
        tmp.write_bytes(data)
        tmp.replace(target)
        return target

    def read(self, storage_reference: str) -> bytes:
        target = self.root / storage_reference
        resolved = target.resolve()
        if not str(resolved).startswith(str(self.root.resolve())):
            raise EvidenceError("STORAGE_PATH_INVALID", "Invalid storage reference")
        if not resolved.is_file():
            raise EvidenceError("STORAGE_NOT_FOUND", "Evidence object missing")
        return resolved.read_bytes()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


async def register_evidence(
    session: AsyncSession,
    auth: AuthContext,
    *,
    work_item_id: str,
    evidence_type: str,
    metadata: dict[str, object],
    captured_at_client: datetime | None,
    device_session_id: str | None,
    work_task_id: str | None = None,
) -> Evidence:
    item: WorkItem = await load_work_item_tenant(
        session, work_item_id=work_item_id, tenant_id=auth.tenant.id
    )
    if item.status in {"COMPLETED", "CANCELLED", "EXPIRED"}:
        raise EvidenceError(
            "WORK_ITEM_TERMINAL",
            f"Cannot attach evidence to terminal work item ({item.status})",
        )

    if work_task_id is not None:
        from elio_api.work.models import WorkTask

        task = await session.get(WorkTask, work_task_id)
        if task is None or task.tenant_id != auth.tenant.id or task.work_item_id != item.id:
            raise EvidenceError("TASK_NOT_FOUND", "Work task not found for this work item")

    evidence = Evidence(
        tenant_id=auth.tenant.id,
        work_item_id=item.id,
        work_task_id=work_task_id,
        captured_by=auth.actor.id,
        device_session_id=device_session_id,
        evidence_type=evidence_type,
        verification_status="CAPTURED",
        metadata_json=json.dumps(metadata, sort_keys=True),
        captured_at_client=captured_at_client,
    )
    session.add(evidence)
    await session.flush()
    await session.commit()
    return evidence


async def upload_evidence_content(
    session: AsyncSession,
    auth: AuthContext,
    store: LocalEvidenceStore,
    *,
    evidence_id: str,
    data: bytes,
    content_type: str,
) -> Evidence:
    from elio_api.sync.service import append_change

    evidence = await session.get(Evidence, evidence_id)
    if evidence is None or evidence.tenant_id != auth.tenant.id:
        raise EvidenceError("EVIDENCE_NOT_FOUND", "Evidence not found")

    if evidence.captured_by != auth.actor.id:
        raise EvidenceError(
            "NOT_CAPTURE_OWNER", "Only the capturing actor may upload this evidence"
        )
    if evidence.verification_status not in {"CAPTURED", "UPLOADED"}:
        raise EvidenceError(
            "EVIDENCE_IMMUTABLE",
            f"Evidence content locked at status {evidence.verification_status}",
        )

    checksum = sha256_hex(data)
    settings_min = __import__("elio_api.config", fromlist=["get_settings"]).get_settings()
    if evidence.evidence_type in {"photo", "image"} and len(data) < settings_min.min_evidence_bytes:
        raise EvidenceError(
            "EVIDENCE_TOO_SMALL",
            "Photo is too small to be useful — capture a proper image",
        )

    from elio_api.work.anti_abuse import EvidenceReuseError, assert_evidence_not_reused

    try:
        await assert_evidence_not_reused(
            session,
            tenant_id=auth.tenant.id,
            actor_id=auth.actor.id,
            work_item_id=evidence.work_item_id,
            checksum=checksum,
        )
    except EvidenceReuseError as exc:
        raise EvidenceError(exc.code, exc.message) from exc

    storage_reference = store.object_key(auth.tenant.id, checksum)
    store.write(auth.tenant.id, checksum, data)

    evidence.content_type = content_type
    evidence.size_bytes = len(data)
    evidence.checksum = checksum
    evidence.storage_reference = storage_reference
    evidence.verification_status = "UPLOADED"
    evidence.uploaded_at = datetime.now(UTC)

    await append_change(
        session,
        tenant_id=auth.tenant.id,
        actor_id=auth.actor.id,
        entity_type="evidence",
        entity_id=evidence.id,
        event_type="EvidenceUploaded",
        payload={
            "evidence_id": evidence.id,
            "work_item_id": evidence.work_item_id,
            "checksum": checksum,
            "status": evidence.verification_status,
        },
        work_item_id=evidence.work_item_id,
    )
    await session.commit()
    return evidence


async def list_evidence_for_work(
    session: AsyncSession,
    auth: AuthContext,
    *,
    work_item_id: str,
) -> list[Evidence]:
    item = await load_work_item_tenant(
        session, work_item_id=work_item_id, tenant_id=auth.tenant.id
    )
    result = await session.execute(
        select(Evidence)
        .where(Evidence.work_item_id == item.id, Evidence.tenant_id == auth.tenant.id)
        .order_by(Evidence.received_at_server.desc())
    )
    return list(result.scalars().all())


async def read_evidence_bytes(
    session: AsyncSession,
    auth: AuthContext,
    store: LocalEvidenceStore,
    *,
    evidence_id: str,
) -> tuple[Evidence, bytes]:
    evidence = await session.get(Evidence, evidence_id)
    if evidence is None or evidence.tenant_id != auth.tenant.id:
        raise EvidenceError("EVIDENCE_NOT_FOUND", "Evidence not found")

    assignment = (
        await session.execute(
            select(Assignment).where(
                Assignment.work_item_id == evidence.work_item_id,
                Assignment.assignee_actor_id == auth.actor.id,
            )
        )
    ).scalars().first()
    can_review = await actor_has_permission(
        session,
        actor_id=auth.actor.id,
        tenant_id=auth.tenant.id,
        permission="work_item.review",
    )
    if assignment is None and evidence.captured_by != auth.actor.id and not can_review:
        raise EvidenceError("EVIDENCE_ACCESS_DENIED", "Not permitted to read this evidence")

    if evidence.storage_reference is None:
        raise EvidenceError("EVIDENCE_NOT_UPLOADED", "Content not uploaded")
    data = store.read(evidence.storage_reference)
    if evidence.checksum and sha256_hex(data) != evidence.checksum:
        raise EvidenceError("CHECKSUM_MISMATCH", "Stored object failed integrity check")
    return evidence, data
