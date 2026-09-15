"""anti-abuse columns and work_exceptions

Revision ID: 0007_anti_abuse
Revises: 0006_task_fields
Create Date: 2026-05-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_anti_abuse"
down_revision: str | None = "0006_task_fields"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "work_items",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_items",
        sa.Column("exception_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "work_exceptions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raised_by", sa.String(length=36), sa.ForeignKey("actors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("category", sa.String(length=64), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolved_by", sa.String(length=36), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('OPEN','RESOLVED','WITHDRAWN')", name="ck_exception_status"),
    )
    op.create_index("ix_work_exceptions_tenant_id", "work_exceptions", ["tenant_id"])
    op.create_index("ix_work_exceptions_work_item_id", "work_exceptions", ["work_item_id"])
    op.create_index("ix_work_exceptions_raised_by", "work_exceptions", ["raised_by"])
    op.create_index(
        "ix_work_exceptions_item_status",
        "work_exceptions",
        ["work_item_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("work_exceptions")
    op.drop_column("work_items", "exception_count")
    op.drop_column("work_items", "started_at")
