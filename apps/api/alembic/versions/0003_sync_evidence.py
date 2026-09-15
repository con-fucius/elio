"""sync change feed and evidence tables

Revision ID: 0003_sync_evidence
Revises: 0002_identity_work
Create Date: 2026-05-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_sync_evidence"
down_revision: str | None = "0002_identity_work"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "change_log",
        sa.Column("sequence", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("server_event_time", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("sequence"),
    )
    op.create_index("ix_change_log_tenant_id", "change_log", ["tenant_id"])
    op.create_index("ix_change_log_work_item_id", "change_log", ["work_item_id"])
    op.create_index("ix_change_log_tenant_seq", "change_log", ["tenant_id", "sequence"])
    op.create_index("ix_change_log_work_item_seq", "change_log", ["work_item_id", "sequence"])

    op.create_table(
        "evidence",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), sa.ForeignKey("work_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("captured_by", sa.String(length=36), sa.ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("device_session_id", sa.String(length=36), nullable=True),
        sa.Column("evidence_type", sa.String(length=64), nullable=False),
        sa.Column("verification_status", sa.String(length=32), nullable=False),
        sa.Column("content_type", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("checksum", sa.String(length=64), nullable=True),
        sa.Column("storage_reference", sa.String(length=512), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=False),
        sa.Column("retention_class", sa.String(length=32), nullable=False),
        sa.Column("captured_at_client", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at_server", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "verification_status in ('CAPTURED','UPLOADED','VERIFIED','REJECTED','DISPUTED','EXPIRED')",
            name="ck_evidence_status",
        ),
    )
    op.create_index("ix_evidence_tenant_id", "evidence", ["tenant_id"])
    op.create_index("ix_evidence_work_item_id", "evidence", ["work_item_id"])
    op.create_index("ix_evidence_captured_by", "evidence", ["captured_by"])
    op.create_index("ix_evidence_work_status", "evidence", ["work_item_id", "verification_status"])


def downgrade() -> None:
    op.drop_table("evidence")
    op.drop_table("change_log")
