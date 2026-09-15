"""initial empty schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-01
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Intentionally empty: Phase 1 skeleton has no domain tables yet.
    # Domain tables (WorkItem, Assignment, ...) arrive with the work engine,
    # not as a placeholder schema.
    pass


def downgrade() -> None:
    pass
