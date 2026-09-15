"""task form fields

Revision ID: 0006_task_fields
Revises: 0005_actor_password
Create Date: 2026-05-01
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_task_fields"
down_revision: str | None = "0005_actor_password"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "template_tasks",
        sa.Column("fields_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "work_tasks",
        sa.Column("fields_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "work_tasks",
        sa.Column("field_values_json", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("work_tasks", "field_values_json")
    op.drop_column("work_tasks", "fields_json")
    op.drop_column("template_tasks", "fields_json")
