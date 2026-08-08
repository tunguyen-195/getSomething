"""Normalize case and audio creation metadata to timezone-aware instants.

Revision ID: e6f7a8b9c2
Revises: d5e6f7a8b9c1
Create Date: 2026-08-09 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c2"
down_revision = "d5e6f7a8b9c1"
branch_labels = None
depends_on = None


LEGACY_LOCAL_TIMEZONE = "Asia/Bangkok"


def _column(bind, table_name, column_name):
    columns = {
        column["name"]: column
        for column in sa.inspect(bind).get_columns(table_name)
    }
    if column_name not in columns:
        raise RuntimeError(f"Missing required column {table_name}.{column_name}")
    return columns[column_name]


def _convert_created_at(bind, operations, table_name):
    column = _column(bind, table_name, "created_at")
    null_count = bind.execute(
        sa.text(f"SELECT COUNT(*) FROM {table_name} WHERE created_at IS NULL")
    ).scalar_one()
    if null_count:
        raise RuntimeError(
            f"Refusing to invent creation metadata: {table_name}.created_at "
            f"contains {null_count} NULL row(s)"
        )
    if not getattr(column["type"], "timezone", False):
        operations.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=False),
            type_=sa.DateTime(timezone=True),
            postgresql_using=(
                f'"created_at" AT TIME ZONE \'{LEGACY_LOCAL_TIMEZONE}\''
            ),
        )
    operations.alter_column(
        table_name,
        "created_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


def _ensure_index(bind, operations, table_name, index_name, columns):
    existing_names = {
        index["name"] for index in sa.inspect(bind).get_indexes(table_name)
    }
    if index_name not in existing_names:
        operations.create_index(index_name, table_name, columns, unique=False)


def _upgrade(bind, operations):
    required_tables = {"cases", "audio_files"}
    missing_tables = required_tables - set(sa.inspect(bind).get_table_names())
    if missing_tables:
        raise RuntimeError(
            f"Cannot normalize creation timestamps; missing tables: {sorted(missing_tables)}"
        )

    for table_name in ("cases", "audio_files"):
        _convert_created_at(bind, operations, table_name)

    # Scale-read indexes match deterministic UI pagination/sort query shapes.
    _ensure_index(
        bind,
        operations,
        "cases",
        "idx_case_archived_created_at",
        ["is_archived", "created_at", "id"],
    )
    _ensure_index(
        bind,
        operations,
        "audio_files",
        "idx_audio_case_archived_created_at",
        ["case_id", "is_archived", "created_at", "id"],
    )


def upgrade():
    _upgrade(op.get_bind(), op)


def downgrade():
    bind = op.get_bind()
    for table_name, index_name in (
        ("cases", "idx_case_archived_created_at"),
        ("audio_files", "idx_audio_case_archived_created_at"),
    ):
        existing_names = {
            index["name"] for index in sa.inspect(bind).get_indexes(table_name)
        }
        if index_name in existing_names:
            op.drop_index(index_name, table_name=table_name)

    for table_name in ("cases", "audio_files"):
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=True,
            server_default=sa.text("now()"),
        )
        op.alter_column(
            table_name,
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(timezone=False),
            postgresql_using=(
                f'"created_at" AT TIME ZONE \'{LEGACY_LOCAL_TIMEZONE}\''
            ),
        )
