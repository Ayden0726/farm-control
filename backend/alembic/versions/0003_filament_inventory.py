"""Filament inventory, FarmOS-generated barcodes, and purchasing.

Revision ID: 0003_filament_inventory
Revises: 0002_notifications
Create Date: 2026-09-11
"""

from alembic import op

from app.schema_upgrade import upgrade_schema

revision = "0003_filament_inventory"
down_revision = "0002_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    upgrade_schema(bind)


def downgrade() -> None:
    pass
