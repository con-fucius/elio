"""work templates and tasks

Revision ID: 0004_work_templates
Revises: 0003_sync_evidence
Create Date: 2026-05-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_work_templates"
down_revision: str | None = "0003_sync_evidence"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "work_templates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_type", sa.String(length=64), nullable=False),
        sa.Column("domain", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("outcome_types_json", sa.Text(), nullable=False),
        sa.Column("default_outcome_type", sa.String(length=64), nullable=False),
        sa.Column("review_required", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "work_type", "version", name="uq_template_type_version"),
        sa.CheckConstraint("status in ('active','retired')", name="ck_template_status"),
        sa.CheckConstraint("domain in ('hospital','marketing','collections')", name="ck_template_domain"),
        sa.CheckConstraint("version >= 1", name="ck_template_version"),
    )
    op.create_index("ix_work_templates_tenant_id", "work_templates", ["tenant_id"])
    op.create_index("ix_work_templates_tenant_type_status", "work_templates", ["tenant_id", "work_type", "status"])

    op.create_table(
        "template_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("template_id", sa.String(length=36), sa.ForeignKey("work_templates.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("required_evidence_types_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("template_id", "key", name="uq_template_task_key"),
        sa.UniqueConstraint("template_id", "sequence", name="uq_template_task_sequence"),
    )
    op.create_index("ix_template_tasks_template_id", "template_tasks", ["template_id"])

    op.create_table(
        "work_tasks",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), sa.ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_item_id", sa.String(length=36), sa.ForeignKey("work_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("template_task_id", sa.String(length=36), sa.ForeignKey("template_tasks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("required_evidence_types_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("completed_by", sa.String(length=36), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("work_item_id", "key", name="uq_work_task_key"),
        sa.UniqueConstraint("work_item_id", "sequence", name="uq_work_task_sequence"),
        sa.CheckConstraint("status in ('PENDING','COMPLETED','SKIPPED')", name="ck_work_task_status"),
    )
    op.create_index("ix_work_tasks_tenant_id", "work_tasks", ["tenant_id"])
    op.create_index("ix_work_tasks_work_item_id", "work_tasks", ["work_item_id"])
    op.create_index("ix_work_tasks_item_status", "work_tasks", ["work_item_id", "status"])

    op.add_column("work_items", sa.Column("template_id", sa.String(length=36), nullable=True))
    op.add_column("work_items", sa.Column("template_version", sa.Integer(), nullable=True))
    op.add_column("work_items", sa.Column("outcome_type", sa.String(length=64), nullable=True))
    op.add_column("work_items", sa.Column("outcome_notes", sa.Text(), nullable=False, server_default=""))
    op.create_foreign_key("fk_work_items_template", "work_items", "work_templates", ["template_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_work_items_template_id", "work_items", ["template_id"])

    op.add_column("evidence", sa.Column("work_task_id", sa.String(length=36), nullable=True))
    op.create_foreign_key("fk_evidence_work_task", "evidence", "work_tasks", ["work_task_id"], ["id"], ondelete="SET NULL")
    op.create_index("ix_evidence_work_task_id", "evidence", ["work_task_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_work_task_id", table_name="evidence")
    op.drop_constraint("fk_evidence_work_task", "evidence", type_="foreignkey")
    op.drop_column("evidence", "work_task_id")
    op.drop_index("ix_work_items_template_id", table_name="work_items")
    op.drop_constraint("fk_work_items_template", "work_items", type_="foreignkey")
    op.drop_column("work_items", "outcome_notes")
    op.drop_column("work_items", "outcome_type")
    op.drop_column("work_items", "template_version")
    op.drop_column("work_items", "template_id")
    op.drop_table("work_tasks")
    op.drop_table("template_tasks")
    op.drop_table("work_templates")
