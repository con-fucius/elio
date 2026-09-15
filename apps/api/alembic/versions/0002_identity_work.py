"""identity and work engine tables

Revision ID: 0002_identity_work
Revises: 0001_initial
Create Date: 2026-05-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_identity_work"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=64), nullable=False, unique=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('active', 'suspended', 'deleted')", name="ck_tenant_status"),
    )

    op.create_table(
        "permissions",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("description", sa.String(length=255), nullable=False),
    )

    op.create_table(
        "organisations",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_org_tenant_name"),
        sa.CheckConstraint("status in ('active', 'inactive')", name="ck_org_status"),
    )
    op.create_index("ix_organisations_tenant_id", "organisations", ["tenant_id"])

    op.create_table(
        "actors",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), sa.ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_subject", sa.String(length=255), nullable=False, unique=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "email", name="uq_actor_tenant_email"),
        sa.CheckConstraint("status in ('active', 'disabled')", name="ck_actor_status"),
    )
    op.create_index("ix_actors_tenant_id", "actors", ["tenant_id"])
    op.create_index("ix_actors_organisation_id", "actors", ["organisation_id"])

    op.create_table(
        "roles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "name", name="uq_role_tenant_name"),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])

    op.create_table(
        "role_permissions",
        sa.Column("role_id", sa.String(length=36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_code", sa.String(length=64), sa.ForeignKey("permissions.code", ondelete="RESTRICT"), primary_key=True),
    )

    op.create_table(
        "actor_roles",
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("actors.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", sa.String(length=36), sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("actors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("jti", sa.String(length=64), nullable=False, unique=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_sessions_tenant_id", "sessions", ["tenant_id"])
    op.create_index("ix_sessions_actor_id", "sessions", ["actor_id"])
    op.create_index("ix_sessions_jti", "sessions", ["jti"])

    op.create_table(
        "device_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("actors.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_id", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "actor_id", "device_id", name="uq_device_actor"),
    )
    op.create_index("ix_device_sessions_tenant_id", "device_sessions", ["tenant_id"])
    op.create_index("ix_device_sessions_actor_id", "device_sessions", ["actor_id"])

    op.create_table(
        "work_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("organisation_id", sa.String(length=36), sa.ForeignKey("organisations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("work_type", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("context_ref", sa.String(length=255), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("active_assignment_id", sa.String(length=36), nullable=True),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "status in ('DRAFT','READY','ASSIGNED','ACCEPTED','IN_PROGRESS','BLOCKED','SUBMITTED','UNDER_REVIEW','REJECTED','COMPLETED','CANCELLED','EXPIRED')",
            name="ck_work_item_status",
        ),
        sa.CheckConstraint("domain in ('hospital','marketing','collections')", name="ck_work_item_domain"),
        sa.CheckConstraint("version >= 1", name="ck_work_item_version"),
    )
    op.create_index("ix_work_items_tenant_id", "work_items", ["tenant_id"])
    op.create_index("ix_work_items_organisation_id", "work_items", ["organisation_id"])
    op.create_index("ix_work_items_tenant_status", "work_items", ["tenant_id", "status"])

    op.create_table(
        "assignments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), sa.ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assignee_actor_id", sa.String(length=36), sa.ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("assigned_by", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status in ('active','superseded','revoked','completed')", name="ck_assignment_status"),
    )
    op.create_index("ix_assignments_tenant_id", "assignments", ["tenant_id"])
    op.create_index("ix_assignments_work_item_id", "assignments", ["work_item_id"])
    op.create_index("ix_assignments_assignee_actor_id", "assignments", ["assignee_actor_id"])
    op.create_index(
        "uq_assignment_one_active",
        "assignments",
        ["work_item_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "work_item_transitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), sa.ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("command_type", sa.String(length=64), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("command_id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("version_after", sa.Integer(), nullable=False),
        sa.Column("client_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("server_event_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_work_item_transitions_tenant_id", "work_item_transitions", ["tenant_id"])
    op.create_index("ix_work_item_transitions_work_item_id", "work_item_transitions", ["work_item_id"])
    op.create_index("ix_work_transitions_item_time", "work_item_transitions", ["work_item_id", "server_event_time"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), sa.ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("command_type", sa.String(length=64), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("result_ref", sa.String(length=36), nullable=True),
        sa.Column("result_payload", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "actor_id", "idempotency_key", name="uq_idempotency_tenant_actor_key"),
        sa.CheckConstraint(
            "status in ('accepted','rejected','requires_review','conflict','retryable')",
            name="ck_idempotency_status",
        ),
    )

    op.create_table(
        "audit_entries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("aggregate_type", sa.String(length=64), nullable=False),
        sa.Column("aggregate_id", sa.String(length=36), nullable=False),
        sa.Column("before_state", sa.Text(), nullable=True),
        sa.Column("after_state", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("server_event_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index("ix_audit_entries_tenant_id", "audit_entries", ["tenant_id"])
    op.create_index("ix_audit_entries_actor_id", "audit_entries", ["actor_id"])
    op.create_index("ix_audit_entries_aggregate_id", "audit_entries", ["aggregate_id"])


def downgrade() -> None:
    op.drop_table("audit_entries")
    op.drop_table("idempotency_records")
    op.drop_table("work_item_transitions")
    op.drop_index("uq_assignment_one_active", table_name="assignments")
    op.drop_table("assignments")
    op.drop_table("work_items")
    op.drop_table("device_sessions")
    op.drop_table("sessions")
    op.drop_table("actor_roles")
    op.drop_table("role_permissions")
    op.drop_table("roles")
    op.drop_table("actors")
    op.drop_table("organisations")
    op.drop_table("permissions")
    op.drop_table("tenants")
