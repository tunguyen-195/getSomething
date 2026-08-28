"""Add durable parent/item persistence for multi-audio workflows.

Revision ID: f7a8b9c0d3
Revises: e6f7a8b9c2
Create Date: 2026-08-27 00:00:00.000000

"""

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d3"
down_revision = "e6f7a8b9c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audio_batches",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("completed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("cancelled_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("total_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("upload_options", sa.JSON(), nullable=False),
        sa.Column(
            "transcription_task_ids",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint_sha256", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('created', 'queued', 'processing', "
            "'partially_succeeded', 'succeeded', 'failed', "
            "'cancel_requested', 'cancelled')",
            name="check_audio_batch_status",
        ),
        sa.CheckConstraint(
            "requested_count BETWEEN 1 AND 20",
            name="check_audio_batch_requested_count",
        ),
        sa.CheckConstraint(
            "completed_count >= 0", name="check_audio_batch_completed_count"
        ),
        sa.CheckConstraint("failed_count >= 0", name="check_audio_batch_failed_count"),
        sa.CheckConstraint(
            "cancelled_count >= 0", name="check_audio_batch_cancelled_count"
        ),
        sa.CheckConstraint(
            "completed_count + failed_count + cancelled_count <= requested_count",
            name="check_audio_batch_terminal_counts",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (completed_count = requested_count AND "
            "failed_count = 0 AND cancelled_count = 0)",
            name="check_audio_batch_succeeded_counts",
        ),
        sa.CheckConstraint(
            "status <> 'cancelled' OR cancelled_count = requested_count",
            name="check_audio_batch_cancelled_counts",
        ),
        sa.CheckConstraint(
            "total_size_bytes BETWEEN 1 AND 1000000000",
            name="check_audio_batch_total_size",
        ),
        sa.CheckConstraint(
            "char_length(idempotency_key) BETWEEN 1 AND 128",
            name="check_audio_batch_idempotency_length",
        ),
        sa.CheckConstraint(
            "request_fingerprint_sha256 ~ '^[0-9a-f]{64}$'",
            name="check_audio_batch_fingerprint",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z0-9_]{1,80}$'",
            name="check_audio_batch_error_code",
        ),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "case_id",
            "idempotency_key",
            name="uq_audio_batch_owner_case_idempotency",
        ),
    )
    op.create_index(
        "idx_audio_batch_owner_created",
        "audio_batches",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "idx_audio_batch_case_created",
        "audio_batches",
        ["case_id", "created_at", "id"],
    )
    op.create_index("idx_audio_batch_status", "audio_batches", ["status"])

    op.create_table(
        "audio_batch_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(), nullable=False),
        sa.Column("audio_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("verified_audio_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("position >= 0", name="check_audio_batch_item_position"),
        sa.CheckConstraint(
            "status IN ('uploaded', 'queued', 'transcribing', 'transcribed', "
            "'failed', 'cancel_requested', 'cancelled')",
            name="check_audio_batch_item_status",
        ),
        sa.CheckConstraint(
            "verified_audio_sha256 ~ '^[0-9a-f]{64}$'",
            name="check_audio_batch_item_sha256",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z0-9_]{1,80}$'",
            name="check_audio_batch_item_error_code",
        ),
        sa.ForeignKeyConstraint(["audio_id"], ["audio_files.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["batch_id"], ["audio_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_id", "audio_id", name="uq_audio_batch_item_audio"),
        sa.UniqueConstraint(
            "batch_id", "position", name="uq_audio_batch_item_position"
        ),
        sa.UniqueConstraint("batch_id", "task_id", name="uq_audio_batch_item_task"),
    )
    op.create_index(
        "idx_audio_batch_item_batch_status",
        "audio_batch_items",
        ["batch_id", "status", "position"],
    )
    op.create_index("idx_audio_batch_item_task", "audio_batch_items", ["task_id"])
    op.create_index("idx_audio_batch_item_audio", "audio_batch_items", ["audio_id"])
    op.create_index(op.f("ix_audio_batch_items_id"), "audio_batch_items", ["id"])

    op.create_table(
        "audio_batch_summary_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("source_manifest", sa.JSON(), nullable=False),
        sa.Column("source_manifest_sha256", sa.String(length=64), nullable=False),
        sa.Column("summary_options", sa.JSON(), nullable=False),
        sa.Column(
            "user_prompt_applied",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("summary_id", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'succeeded', 'failed', "
            "'cancel_requested', 'cancelled')",
            name="check_audio_batch_summary_job_status",
        ),
        sa.CheckConstraint(
            "selected_count BETWEEN 1 AND 20",
            name="check_audio_batch_summary_job_selected_count",
        ),
        sa.CheckConstraint(
            "source_manifest_sha256 ~ '^[0-9a-f]{64}$'",
            name="check_audio_batch_summary_job_manifest_sha256",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[A-Z0-9_]{1,80}$'",
            name="check_audio_batch_summary_job_error_code",
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["audio_batches.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["summary_id"], ["summaries.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_audio_batch_summary_job_batch_created",
        "audio_batch_summary_jobs",
        ["batch_id", "created_at", "id"],
    )
    op.create_index(
        "idx_audio_batch_summary_job_owner_created",
        "audio_batch_summary_jobs",
        ["user_id", "created_at", "id"],
    )
    op.create_index(
        "idx_audio_batch_summary_job_status",
        "audio_batch_summary_jobs",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index(
        "idx_audio_batch_summary_job_status",
        table_name="audio_batch_summary_jobs",
    )
    op.drop_index(
        "idx_audio_batch_summary_job_owner_created",
        table_name="audio_batch_summary_jobs",
    )
    op.drop_index(
        "idx_audio_batch_summary_job_batch_created",
        table_name="audio_batch_summary_jobs",
    )
    op.drop_table("audio_batch_summary_jobs")

    op.drop_index(op.f("ix_audio_batch_items_id"), table_name="audio_batch_items")
    op.drop_index("idx_audio_batch_item_audio", table_name="audio_batch_items")
    op.drop_index("idx_audio_batch_item_task", table_name="audio_batch_items")
    op.drop_index("idx_audio_batch_item_batch_status", table_name="audio_batch_items")
    op.drop_table("audio_batch_items")

    op.drop_index("idx_audio_batch_status", table_name="audio_batches")
    op.drop_index("idx_audio_batch_case_created", table_name="audio_batches")
    op.drop_index("idx_audio_batch_owner_created", table_name="audio_batches")
    op.drop_table("audio_batches")
