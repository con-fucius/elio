from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from elio_api.db.base import Base


class ChangeLog(Base):
    """Append-only tenant change feed for sync download. Cursor is `sequence`."""

    __tablename__ = "change_log"

    sequence: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Work items visible to an actor: null = all tenant readers; else assignee-scoped.
    work_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    server_event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_change_log_tenant_seq", "tenant_id", "sequence"),
        Index("ix_change_log_work_item_seq", "work_item_id", "sequence"),
    )
