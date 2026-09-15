from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from elio_api.db.base import Base, new_id


class WorkItem(Base):
    __tablename__ = "work_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    organisation_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    work_type: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, default="hospital")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    # Optimistic concurrency: every material mutation increments version.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    context_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    active_assignment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    template_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("work_templates.id", ondelete="SET NULL"), nullable=True, index=True
    )
    template_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    outcome_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Anti-abuse / provenance
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exception_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_work_items_tenant_status", "tenant_id", "status"),
        CheckConstraint(
            "status in ('DRAFT','READY','ASSIGNED','ACCEPTED','IN_PROGRESS',"
            "'BLOCKED','SUBMITTED','UNDER_REVIEW','REJECTED','COMPLETED',"
            "'CANCELLED','EXPIRED')",
            name="ck_work_item_status",
        ),
        CheckConstraint(
            "domain in ('hospital','marketing','collections')",
            name="ck_work_item_domain",
        ),
        CheckConstraint("version >= 1", name="ck_work_item_version"),
    )

    assignments: Mapped[list[Assignment]] = relationship(
        back_populates="work_item", foreign_keys="Assignment.work_item_id"
    )


class Assignment(Base):
    __tablename__ = "assignments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assignee_actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assigned_by: Mapped[str] = mapped_column(String(36), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('active','superseded','revoked','completed')", name="ck_assignment_status"
        ),
        # One active assignment per work item; superseded rows remain for audit.
        Index(
            "uq_assignment_one_active",
            "work_item_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
            sqlite_where=text("status = 'active'"),
        ),
    )

    work_item: Mapped[WorkItem] = relationship(
        back_populates="assignments", foreign_keys=[work_item_id]
    )


class WorkItemTransition(Base):
    """Append-only material state-change history (business audit for transitions)."""

    __tablename__ = "work_item_transitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    command_id: Mapped[str] = mapped_column(String(36), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    version_after: Mapped[int] = mapped_column(Integer, nullable=False)
    client_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    server_event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_work_transitions_item_time", "work_item_id", "server_event_time"),
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False
    )
    actor_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    command_type: Mapped[str] = mapped_column(String(64), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    result_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result_payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "actor_id", "idempotency_key", name="uq_idempotency_tenant_actor_key"
        ),
        CheckConstraint(
            "status in ('accepted','rejected','requires_review','conflict','retryable')",
            name="ck_idempotency_status",
        ),
    )


class AuditEntry(Base):
    """Business audit — separate from application logs. Append-only in normal path."""

    __tablename__ = "audit_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    actor_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(64), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    before_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_state: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(32), nullable=False, default="1")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="api")
    server_event_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkTemplate(Base):
    """Reusable definition of a class of work items for a tenant + work_type."""

    __tablename__ = "work_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_type: Mapped[str] = mapped_column(String(64), nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, default="hospital")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # JSON array of allowed outcome codes for SubmitWork payload.outcome_type
    outcome_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    default_outcome_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="COMPLETED"
    )
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Templates are versioned by bumping this row's version and deactivating old.
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "work_type", "version", name="uq_template_type_version"),
        CheckConstraint("status in ('active','retired')", name="ck_template_status"),
        CheckConstraint(
            "domain in ('hospital','marketing','collections')",
            name="ck_template_domain",
        ),
        CheckConstraint("version >= 1", name="ck_template_version"),
        Index("ix_work_templates_tenant_type_status", "tenant_id", "work_type", "status"),
    )

    tasks: Mapped[list[TemplateTask]] = relationship(
        back_populates="template",
        order_by="TemplateTask.sequence",
        cascade="all, delete-orphan",
    )


class TemplateTask(Base):
    """Ordered checklist step on a template."""

    __tablename__ = "template_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    template_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_templates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # JSON array of evidence types that must exist when this task is completed/required at submit
    required_evidence_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # JSON array of structured form fields for this checklist step
    fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("template_id", "key", name="uq_template_task_key"),
        UniqueConstraint("template_id", "sequence", name="uq_template_task_sequence"),
    )

    template: Mapped[WorkTemplate] = relationship(back_populates="tasks")


class WorkTask(Base):
    """Instantiated checklist item on a concrete WorkItem."""

    __tablename__ = "work_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    template_task_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("template_tasks.id", ondelete="SET NULL"), nullable=True
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    required_evidence_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Snapshot of template field definitions for this work item's copy of the task
    fields_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    # Collected form answers for this task
    field_values_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PENDING")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    completed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("work_item_id", "key", name="uq_work_task_key"),
        UniqueConstraint("work_item_id", "sequence", name="uq_work_task_sequence"),
        CheckConstraint(
            "status in ('PENDING','COMPLETED','SKIPPED')",
            name="ck_work_task_status",
        ),
        Index("ix_work_tasks_item_status", "work_item_id", "status"),
    )


class WorkException(Base):
    """Raised exception on a work item — first-class for ops and anti-abuse."""

    __tablename__ = "work_exceptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    tenant_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    work_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raised_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="OPEN")
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raised_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint("status in ('OPEN','RESOLVED','WITHDRAWN')", name="ck_exception_status"),
        Index("ix_work_exceptions_item_status", "work_item_id", "status"),
    )

