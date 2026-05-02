"""
Revision ID: c4f1a2b3c9d0
Revises: b1cbd9b60b5b
Create Date: 2026-05-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "c4f1a2b3c9d0"
down_revision = "b1cbd9b60b5b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "auth_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("jti", sa.String(length=128), nullable=False),
        sa.Column("csrf_token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("jti"),
    )
    op.create_index("idx_auth_session_user", "auth_sessions", ["user_id"], unique=False)
    op.create_index("idx_auth_session_expires", "auth_sessions", ["expires_at"], unique=False)
    op.create_index("idx_auth_session_revoked", "auth_sessions", ["revoked_at"], unique=False)
    op.create_index(op.f("ix_auth_sessions_id"), "auth_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_auth_sessions_jti"), "auth_sessions", ["jti"], unique=False)

    op.create_table(
        "security_audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("attempted_identifier_hash", sa.String(length=128), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("detail", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_security_audit_event", "security_audit_logs", ["event_type"], unique=False)
    op.create_index("idx_security_audit_user", "security_audit_logs", ["user_id"], unique=False)
    op.create_index("idx_security_audit_created", "security_audit_logs", ["created_at"], unique=False)
    op.create_index("idx_security_audit_identifier", "security_audit_logs", ["attempted_identifier_hash"], unique=False)
    op.create_index(op.f("ix_security_audit_logs_id"), "security_audit_logs", ["id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_security_audit_logs_id"), table_name="security_audit_logs")
    op.drop_index("idx_security_audit_identifier", table_name="security_audit_logs")
    op.drop_index("idx_security_audit_created", table_name="security_audit_logs")
    op.drop_index("idx_security_audit_user", table_name="security_audit_logs")
    op.drop_index("idx_security_audit_event", table_name="security_audit_logs")
    op.drop_table("security_audit_logs")

    op.drop_index(op.f("ix_auth_sessions_jti"), table_name="auth_sessions")
    op.drop_index(op.f("ix_auth_sessions_id"), table_name="auth_sessions")
    op.drop_index("idx_auth_session_revoked", table_name="auth_sessions")
    op.drop_index("idx_auth_session_expires", table_name="auth_sessions")
    op.drop_index("idx_auth_session_user", table_name="auth_sessions")
    op.drop_table("auth_sessions")
