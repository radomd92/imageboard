"""Add indexes for catalog API queries.

Revision ID: 0003_api_query_indexes
Revises: 0002_async_index_jobs
"""

from alembic import op

revision = "0003_api_query_indexes"
down_revision = "0002_async_index_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX image_created_date_id_idx ON image (created_date DESC, id DESC)")
    op.execute("CREATE INDEX image_name_trgm_idx ON image USING gin (lower(name) gin_trgm_ops)")
    op.execute("CREATE INDEX image_path_trgm_idx ON image USING gin (lower(image_path) gin_trgm_ops)")
    op.execute("CREATE INDEX image_hits_hit_date_idx ON image_hits (hit_date)")


def downgrade():
    op.drop_index("image_hits_hit_date_idx", table_name="image_hits")
    op.drop_index("image_path_trgm_idx", table_name="image")
    op.drop_index("image_name_trgm_idx", table_name="image")
    op.drop_index("image_created_date_id_idx", table_name="image")
