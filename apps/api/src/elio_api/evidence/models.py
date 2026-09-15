from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from elio_api.db.base import Base, new_id


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Optional checklist task binding (template evidence requirements).
    work_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    captured_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    device_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # CAPTURED → UPLOADED → VERIFIED | REJECTED | DISPUTED | EXPIRED
    verification_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="CAPTURED"
    )
    content_type: Mapped[str] = mapped_column(
        String(128), nullable=False, default="application/octet-stream"
    )
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # sha256 hex of content; required once uploaded
    checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # tenant-scoped object key under evidence root, not a public URL
    storage_reference: Mapped[str | None] = mapped_column(String(512), nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    retention_class: Mapped[str] = mapped_column(
        String(32), nullable=False, default="operational"
    )
    captured_at_client: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at_server: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "verification_status in ('CAPTURED','UPLOADED','VERIFIED',"
            "'REJECTED','DISPUTED','EXPIRED')",
            name="ck_evidence_status",
        ),
        Index("ix_evidence_work_status", "work_item_id", "verification_status"),
    )
