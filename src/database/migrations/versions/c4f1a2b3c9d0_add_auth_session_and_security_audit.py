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


def _existing_index_names(inspector, table_name):
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _has_unique_jti(inspector):
    if any(
        constraint.get("column_names") == ["jti"]
        for constraint in inspector.get_unique_constraints("auth_sessions")
    ):
        return True
    return any(
        index.get("column_names") == ["jti"] and index.get("unique")
        for index in inspector.get_indexes("auth_sessions")
    )


def _validate_existing_table(inspector, table_name, expected_columns):
    actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
    if actual_columns != set(expected_columns):
        raise RuntimeError(
            f"Cannot reconcile {table_name}: expected columns {sorted(expected_columns)}, "
            f"found {sorted(actual_columns)}"
        )
    foreign_keys = inspector.get_foreign_keys(table_name)
    if not any(
        fk.get("constrained_columns") == ["user_id"]
        and fk.get("referred_table") == "users"
        and fk.get("referred_columns") == ["id"]
        for fk in foreign_keys
    ):
        raise RuntimeError(f"Cannot reconcile {table_name}: missing users foreign key")


def _ensure_index(inspector, table_name, index_name, columns, unique=False):
    if index_name not in _existing_index_names(inspector, table_name):
        op.create_index(index_name, table_name, columns, unique=unique)


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("auth_sessions"):
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
    else:
        _validate_existing_table(
            inspector,
            "auth_sessions",
            {
                "id", "user_id", "jti", "csrf_token_hash", "expires_at",
                "revoked_at", "ip_address", "user_agent", "created_at", "updated_at",
            },
        )
        if not _has_unique_jti(inspector):
            op.create_unique_constraint("uq_auth_sessions_jti", "auth_sessions", ["jti"])

    inspector = sa.inspect(bind)
    _ensure_index(inspector, "auth_sessions", "idx_auth_session_user", ["user_id"])
    inspector = sa.inspect(bind)
    _ensure_index(inspector, "auth_sessions", "idx_auth_session_expires", ["expires_at"])
    inspector = sa.inspect(bind)
    _ensure_index(inspector, "auth_sessions", "idx_auth_session_revoked", ["revoked_at"])
    inspector = sa.inspect(bind)
    _ensure_index(inspector, "auth_sessions", op.f("ix_auth_sessions_id"), ["id"])
    inspector = sa.inspect(bind)
    _ensure_index(inspector, "auth_sessions", op.f("ix_auth_sessions_jti"), ["jti"])

    inspector = sa.inspect(bind)
    if not inspector.has_table("security_audit_logs"):
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
    else:
        _validate_existing_table(
            inspector,
            "security_audit_logs",
            {
                "id", "event_type", "status", "user_id", "attempted_identifier_hash",
                "ip_address", "user_agent", "detail", "created_at", "updated_at",
            },
        )

    for index_name, columns in [
        ("idx_security_audit_event", ["event_type"]),
        ("idx_security_audit_user", ["user_id"]),
        ("idx_security_audit_created", ["created_at"]),
        ("idx_security_audit_identifier", ["attempted_identifier_hash"]),
        (op.f("ix_security_audit_logs_id"), ["id"]),
    ]:
        inspector = sa.inspect(bind)
        _ensure_index(inspector, "security_audit_logs", index_name, columns)


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
