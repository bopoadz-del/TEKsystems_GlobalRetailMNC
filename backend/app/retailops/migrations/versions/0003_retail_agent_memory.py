"""Alembic revision: retail agent memory table."""

from __future__ import annotations

from alembic import op

from app.retailops.models import RetailAgentMemory

revision = "0003_retail_agent_memory"
down_revision = "0002_retail_learning"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    RetailAgentMemory.__table__.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    RetailAgentMemory.__table__.drop(bind=bind, checkfirst=True)
