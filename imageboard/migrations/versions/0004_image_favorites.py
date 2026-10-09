"""Add per-user image favorites.

Revision ID: 0004_image_favorites
Revises: 0003_api_query_indexes
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_image_favorites"
down_revision = "0003_api_query_indexes"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "image_favorite",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["user_id"], ["user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["image_id"], ["image.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "image_id"),
    )
    op.create_index(
        "image_favorite_user_created_idx", "image_favorite", ["user_id", sa.text("created_at DESC")]
    )


def downgrade():
    op.drop_index("image_favorite_user_created_idx", table_name="image_favorite")
    op.drop_table("image_favorite")
