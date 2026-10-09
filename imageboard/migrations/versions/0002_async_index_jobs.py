"""Add durable asynchronous indexing jobs.

Revision ID: 0002_async_index_jobs
Revises: 0001_secure_baseline
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_async_index_jobs"
down_revision = "0001_secure_baseline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "index_job",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("root_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("max_depth", sa.Integer()),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_by", sa.Integer(), sa.ForeignKey("user.id", ondelete="SET NULL")),
        sa.Column("worker_id", sa.String(128)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("discovered", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("processed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("indexed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("deindexed", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("skipped", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("errors", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(64)),
        sa.CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed', 'cancelled')"),
        sa.CheckConstraint("max_depth IS NULL OR max_depth >= 0"),
    )
    op.create_index("index_job_claim_idx", "index_job", ["status", "lease_expires_at", "created_at"])
    op.create_index("index_job_requester_idx", "index_job", ["requested_by", "created_at"])
    op.execute(
        "CREATE UNIQUE INDEX index_job_active_unique ON index_job ((1)) "
        "WHERE status IN ('pending', 'running')"
    )
    op.add_column("image", sa.Column("last_index_job", sa.Uuid()))
    op.create_index("image_last_index_job_idx", "image", ["last_index_job"])


def downgrade():
    op.drop_index("image_last_index_job_idx", table_name="image")
    op.drop_column("image", "last_index_job")
    op.drop_index("index_job_requester_idx", table_name="index_job")
    op.drop_index("index_job_claim_idx", table_name="index_job")
    op.drop_index("index_job_active_unique", table_name="index_job")
    op.drop_table("index_job")
