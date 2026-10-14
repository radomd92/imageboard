"""Index user comment history.

Revision ID: 0006_user_comment_history
Revises: 0005_encrypted_thumbnail_cache
"""

from alembic import op

revision = "0006_user_comment_history"
down_revision = "0005_encrypted_thumbnail_cache"
branch_labels = None
depends_on = None


def upgrade():
    op.create_index("message_user_date_id_idx", "message", ["from_user", "message_date", "id"])


def downgrade():
    op.drop_index("message_user_date_id_idx", table_name="message")
