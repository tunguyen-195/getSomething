"""Add runtime job leases for Lite single-job runner.

Revision ID: a8c1d2e3f4b5
Revises: f7a0b1c2d3e4
Create Date: 2026-05-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a8c1d2e3f4b5"
down_revision = "f7a0b1c2d3e4"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in set(sa.inspect(bind).get_table_names())


def upgrade():
    if _has_table("runtime_job_leases"):
        return
    op.create_table(
        "runtime_job_leases",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_key", sa.String(length=120), nullable=False),
        sa.Column("active_task_id", sa.String(), nullable=True),
        sa.Column("active_operation", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("owner_id", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "active_operation IS NULL OR active_operation IN ('transcribe', 'summarize', 'visualize')",
            name="check_runtime_job_operation",
        ),
        sa.CheckConstraint(
            "status IN ('idle', 'active', 'expired', 'released')",
            name="check_runtime_job_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("lease_key", name="uq_runtime_job_lease_key"),
    )
    op.create_index("idx_runtime_job_expires", "runtime_job_leases", ["lease_expires_at"], unique=False)
    op.create_index("idx_runtime_job_status", "runtime_job_leases", ["status"], unique=False)
    op.create_index(op.f("ix_runtime_job_leases_id"), "runtime_job_leases", ["id"], unique=False)
    op.create_index(op.f("ix_runtime_job_leases_lease_key"), "runtime_job_leases", ["lease_key"], unique=False)


def downgrade():
    if not _has_table("runtime_job_leases"):
        return
    op.drop_index(op.f("ix_runtime_job_leases_lease_key"), table_name="runtime_job_leases")
    op.drop_index(op.f("ix_runtime_job_leases_id"), table_name="runtime_job_leases")
    op.drop_index("idx_runtime_job_status", table_name="runtime_job_leases")
    op.drop_index("idx_runtime_job_expires", table_name="runtime_job_leases")
    op.drop_table("runtime_job_leases")
