"""Allow up to 8 KiB of UTF-8 comment text.

Revision ID: 0007_larger_comments
Revises: 0006_user_comment_history
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_larger_comments"
down_revision = "0006_user_comment_history"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("message", "text", existing_type=sa.String(500), type_=sa.Text(), existing_nullable=False)
    op.create_check_constraint("message_text_bytes_limit", "message", "octet_length(text) <= 8192")


def downgrade():
    # Never truncate comments to satisfy the previous column size.
    has_long_comments = op.get_bind().execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM message WHERE char_length(text) > 500)")
    ).scalar()
    if has_long_comments:
        raise RuntimeError("Cannot downgrade while comments exceed 500 characters.")
    op.drop_constraint("message_text_bytes_limit", "message", type_="check")
    op.alter_column("message", "text", existing_type=sa.Text(), type_=sa.String(500), existing_nullable=False)
