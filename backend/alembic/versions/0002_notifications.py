"""Phone notification tables and delivery history.

Revision ID: 0002_notifications
Revises: 0001_initial
Create Date: 2026-09-10
"""

from alembic import op

from app.schema_upgrade import upgrade_schema

revision = "0002_notifications"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    upgrade_schema(bind)


def downgrade() -> None:
    op.drop_table("notification_deliveries")
    op.drop_table("printer_notification_preferences")
    op.drop_table("notification_preferences")
    op.drop_table("notification_provider_settings")
