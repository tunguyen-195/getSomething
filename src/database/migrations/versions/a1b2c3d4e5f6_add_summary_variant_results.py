"""Persist independent merged-summary variants without overwriting results.

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d3
Create Date: 2026-09-04 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "f7a8b9c0d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint(
        "check_audio_batch_summary_job_status",
        "audio_batch_summary_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "check_audio_batch_summary_job_status",
        "audio_batch_summary_jobs",
        "status IN ('queued', 'processing', 'succeeded', 'partially_succeeded', "
        "'failed', 'cancel_requested', 'cancelled')",
    )
    op.add_column(
        "audio_batch_summary_jobs",
        sa.Column(
            "summary_results",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "check_audio_batch_summary_job_results_array",
        "audio_batch_summary_jobs",
        "summary_results IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "check_audio_batch_summary_job_results_array",
        "audio_batch_summary_jobs",
        type_="check",
    )
    op.drop_column("audio_batch_summary_jobs", "summary_results")
    op.drop_constraint(
        "check_audio_batch_summary_job_status",
        "audio_batch_summary_jobs",
        type_="check",
    )
    op.create_check_constraint(
        "check_audio_batch_summary_job_status",
        "audio_batch_summary_jobs",
        "status IN ('queued', 'processing', 'succeeded', 'failed', "
        "'cancel_requested', 'cancelled')",
    )
