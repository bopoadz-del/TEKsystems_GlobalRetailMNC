"""retail learning tables

Revision ID: 0002_retail_learning
Revises: 0001_initial
Create Date: 2026-07-14
"""

from __future__ import annotations

from alembic import op

from app.retailops.models import RetailLearningEvent, RetailLearningProfile

revision = "0002_retail_learning"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_TABLES = (
    RetailLearningEvent.__table__,
    RetailLearningProfile.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_TABLES):
        table.drop(bind=bind, checkfirst=True)
