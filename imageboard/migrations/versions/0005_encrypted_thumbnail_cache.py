"""Store generated thumbnails as encrypted database blobs.

Revision ID: 0005_encrypted_thumbnail_cache
Revises: 0004_image_favorites
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_encrypted_thumbnail_cache"
down_revision = "0004_image_favorites"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "thumbnail_cache",
        sa.Column("cache_key", sa.LargeBinary(32), nullable=False),
        sa.Column("variant", sa.SmallInteger(), nullable=False),
        sa.Column("source_size", sa.BigInteger(), nullable=False),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("nonce", sa.LargeBinary(12), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("variant IN (160, 320)", name="thumbnail_cache_variant"),
        sa.PrimaryKeyConstraint("cache_key", "variant"),
    )


def downgrade():
    op.drop_table("thumbnail_cache")
