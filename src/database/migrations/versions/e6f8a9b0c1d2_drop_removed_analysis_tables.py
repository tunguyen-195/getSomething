"""Drop removed legacy analysis/transcription tables.

Revision ID: e6f8a9b0c1d2
Revises: d5e6f7a8b9c1
Create Date: 2026-05-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "e6f8a9b0c1d2"
down_revision = "d5e6f7a8b9c1"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in set(sa.inspect(bind).get_table_names())


def upgrade():
    if _has_table("analysisdetails"):
        op.drop_table("analysisdetails")
    if _has_table("transcriptions"):
        op.drop_table("transcriptions")
    if _has_table("analysis_results"):
        op.drop_table("analysis_results")


def downgrade():
    if not _has_table("analysis_results"):
        op.create_table(
            "analysis_results",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("keywords", sa.JSON(), nullable=True),
            sa.Column("entities", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("audio_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("sentiment_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("confidence_score", sa.Integer(), nullable=True),
            sa.Column("processing_time", sa.Integer(), nullable=True),
            sa.Column("extra_metadata", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["audio_id"], ["audio_files.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["sentiment_id"], ["sentiments.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("audio_id", "version", name="uq_analysis_audio_version"),
        )
        op.create_index("idx_analysis_audio", "analysis_results", ["audio_id"], unique=False)
        op.create_index("idx_analysis_created_by", "analysis_results", ["created_by"], unique=False)
        op.create_index("idx_analysis_sentiment", "analysis_results", ["sentiment_id"], unique=False)
        op.create_index(op.f("ix_analysis_results_id"), "analysis_results", ["id"], unique=False)

    if not _has_table("transcriptions"):
        op.create_table(
            "transcriptions",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("text", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("duration", sa.Float(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.Column("task_id", sa.String(), nullable=True),
            sa.Column("audio_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("language_id", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("confidence_score", sa.Integer(), nullable=True),
            sa.Column("processing_time", sa.Integer(), nullable=True),
            sa.Column("extra_metadata", sa.JSON(), nullable=True),
            sa.ForeignKeyConstraint(["audio_id"], ["audio_files.id"]),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["language_id"], ["languages.id"]),
            sa.ForeignKeyConstraint(["task_id"], ["tasks.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("audio_id", "version", name="uq_transcription_audio_version"),
        )
        op.create_index("idx_transcription_audio", "transcriptions", ["audio_id"], unique=False)
        op.create_index("idx_transcription_created_by", "transcriptions", ["created_by"], unique=False)
        op.create_index("idx_transcription_language", "transcriptions", ["language_id"], unique=False)
        op.create_index(op.f("ix_transcriptions_id"), "transcriptions", ["id"], unique=False)

    if not _has_table("analysisdetails"):
        op.create_table(
            "analysisdetails",
            sa.Column("analysis_id", sa.Integer(), nullable=False),
            sa.Column("detail_type", sa.String(length=50), nullable=False),
            sa.Column("content", sa.JSON(), nullable=False),
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["analysis_id"], ["analysis_results.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("idx_detail_analysis", "analysisdetails", ["analysis_id"], unique=False)
        op.create_index("idx_detail_type", "analysisdetails", ["detail_type"], unique=False)
        op.create_index(op.f("ix_analysisdetails_id"), "analysisdetails", ["id"], unique=False)
