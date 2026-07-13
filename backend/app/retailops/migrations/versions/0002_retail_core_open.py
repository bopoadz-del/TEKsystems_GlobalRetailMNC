"""retail_core_open_v1 structured tables

Revision ID: 0002_retail_core_open
Revises: 0001_initial
Create Date: 2026-07-13
"""

from __future__ import annotations

from alembic import op

from app.retailops.models import (
    RetailPackSource,
    RetailProduct,
    RetailPromotion,
    RetailSale,
    RetailStockStatus,
    RetailTransaction,
)

revision = "0002_retail_core_open"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_TABLES = (
    RetailPackSource.__table__,
    RetailProduct.__table__,
    RetailSale.__table__,
    RetailStockStatus.__table__,
    RetailPromotion.__table__,
    RetailTransaction.__table__,
)


def upgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_TABLES):
        table.drop(bind=bind, checkfirst=True)
