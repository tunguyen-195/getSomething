"""Add analysis domain template registry.

Revision ID: f7a0b1c2d3e4
Revises: e6f8a9b0c1d2
Create Date: 2026-05-03 14:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "f7a0b1c2d3e4"
down_revision = "e6f8a9b0c1d2"
branch_labels = None
depends_on = None


def _has_table(table_name: str) -> bool:
    bind = op.get_bind()
    return table_name in set(sa.inspect(bind).get_table_names())


def upgrade():
    if _has_table("analysis_domain_templates"):
        return
    op.create_table(
        "analysis_domain_templates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("template_key", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("schema_hash", sa.String(length=64), nullable=False),
        sa.Column("parent_template_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("scope", sa.String(length=30), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("case_id", sa.Integer(), nullable=True),
        sa.Column("schema_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("examples_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("scope IN ('global', 'user', 'case')", name="check_analysis_template_scope"),
        sa.CheckConstraint("status IN ('draft', 'published', 'archived')", name="check_analysis_template_status"),
        sa.CheckConstraint("version > 0", name="check_analysis_template_version_positive"),
        sa.ForeignKeyConstraint(["case_id"], ["cases.id"]),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_template_id"], ["analysis_domain_templates.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_key", "version", name="uq_analysis_template_key_version"),
    )
    op.create_index("idx_analysis_template_case", "analysis_domain_templates", ["case_id"], unique=False)
    op.create_index("idx_analysis_template_key", "analysis_domain_templates", ["template_key"], unique=False)
    op.create_index("idx_analysis_template_owner", "analysis_domain_templates", ["owner_user_id"], unique=False)
    op.create_index("idx_analysis_template_scope", "analysis_domain_templates", ["scope"], unique=False)
    op.create_index("idx_analysis_template_status", "analysis_domain_templates", ["status"], unique=False)
    op.create_index(op.f("ix_analysis_domain_templates_id"), "analysis_domain_templates", ["id"], unique=False)


def downgrade():
    if not _has_table("analysis_domain_templates"):
        return
    op.drop_index(op.f("ix_analysis_domain_templates_id"), table_name="analysis_domain_templates")
    op.drop_index("idx_analysis_template_status", table_name="analysis_domain_templates")
    op.drop_index("idx_analysis_template_scope", table_name="analysis_domain_templates")
    op.drop_index("idx_analysis_template_owner", table_name="analysis_domain_templates")
    op.drop_index("idx_analysis_template_key", table_name="analysis_domain_templates")
    op.drop_index("idx_analysis_template_case", table_name="analysis_domain_templates")
    op.drop_table("analysis_domain_templates")
