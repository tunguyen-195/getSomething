"""Compare existing security tables with the Alembic c4 migration contract."""

from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv
from sqlalchemy import JSON, DateTime, Integer, String, create_engine, inspect, text
from sqlalchemy.engine import make_url


EXPECTED_COLUMNS = {
    "auth_sessions": {
        "id": (Integer, None, False),
        "user_id": (Integer, None, False),
        "jti": (String, 128, False),
        "csrf_token_hash": (String, 128, False),
        "expires_at": (DateTime, None, False),
        "revoked_at": (DateTime, None, True),
        "ip_address": (String, 45, True),
        "user_agent": (String, 500, True),
        "created_at": (DateTime, None, True),
        "updated_at": (DateTime, None, True),
    },
    "security_audit_logs": {
        "id": (Integer, None, False),
        "event_type": (String, 80, False),
        "status": (String, 30, False),
        "user_id": (Integer, None, True),
        "attempted_identifier_hash": (String, 128, True),
        "ip_address": (String, 45, True),
        "user_agent": (String, 500, True),
        "detail": (JSON, None, True),
        "created_at": (DateTime, None, True),
        "updated_at": (DateTime, None, True),
    },
}


EXPECTED_INDEXES = {
    "auth_sessions": {
        "idx_auth_session_user": ["user_id"],
        "idx_auth_session_expires": ["expires_at"],
        "idx_auth_session_revoked": ["revoked_at"],
        "ix_auth_sessions_id": ["id"],
        "ix_auth_sessions_jti": ["jti"],
    },
    "security_audit_logs": {
        "idx_security_audit_event": ["event_type"],
        "idx_security_audit_user": ["user_id"],
        "idx_security_audit_created": ["created_at"],
        "idx_security_audit_identifier": ["attempted_identifier_hash"],
        "ix_security_audit_logs_id": ["id"],
    },
}


def _column_mismatches(inspector, table_name: str) -> list[str]:
    expected = EXPECTED_COLUMNS[table_name]
    actual = {column["name"]: column for column in inspector.get_columns(table_name)}
    mismatches = []
    if set(actual) != set(expected):
        mismatches.append(
            f"{table_name}: columns expected={sorted(expected)} actual={sorted(actual)}"
        )
    for name, (type_class, length, nullable) in expected.items():
        column = actual.get(name)
        if not column:
            continue
        if not isinstance(column["type"], type_class):
            mismatches.append(
                f"{table_name}.{name}: type {column['type']} is not {type_class.__name__}"
            )
        if length is not None and getattr(column["type"], "length", None) != length:
            mismatches.append(
                f"{table_name}.{name}: length {getattr(column['type'], 'length', None)} != {length}"
            )
        if bool(column["nullable"]) != nullable:
            mismatches.append(
                f"{table_name}.{name}: nullable {column['nullable']} != {nullable}"
            )
        if isinstance(column["type"], DateTime) and not column["type"].timezone:
            mismatches.append(f"{table_name}.{name}: timestamp must include timezone")
    return mismatches


def _constraint_mismatches(inspector, table_name: str) -> list[str]:
    mismatches = []
    primary_key = inspector.get_pk_constraint(table_name).get("constrained_columns", [])
    if primary_key != ["id"]:
        mismatches.append(f"{table_name}: primary key {primary_key} != ['id']")

    foreign_keys = inspector.get_foreign_keys(table_name)
    has_user_fk = any(
        fk.get("constrained_columns") == ["user_id"]
        and fk.get("referred_table") == "users"
        and fk.get("referred_columns") == ["id"]
        for fk in foreign_keys
    )
    if not has_user_fk:
        mismatches.append(f"{table_name}: missing user_id -> users.id foreign key")

    indexes = {index["name"]: index for index in inspector.get_indexes(table_name)}
    for name, columns in EXPECTED_INDEXES[table_name].items():
        index = indexes.get(name)
        if not index:
            mismatches.append(f"{table_name}: missing index {name}")
        elif index.get("column_names") != columns:
            mismatches.append(
                f"{table_name}.{name}: columns {index.get('column_names')} != {columns}"
            )

    if table_name == "auth_sessions":
        unique_constraints = inspector.get_unique_constraints(table_name)
        unique_jti = any(
            constraint.get("column_names") == ["jti"]
            for constraint in unique_constraints
        ) or any(
            index.get("column_names") == ["jti"] and index.get("unique")
            for index in indexes.values()
        )
        if not unique_jti:
            mismatches.append("auth_sessions.jti must be unique")
    return mismatches


def build_report(database_url: str) -> tuple[dict, int]:
    url = make_url(database_url)
    engine = create_engine(url)
    try:
        inspector = inspect(engine)
        existing = {
            table_name: inspector.has_table(table_name)
            for table_name in EXPECTED_COLUMNS
        }
        if not any(existing.values()):
            status = "NOT_APPLICABLE"
            mismatches = []
            exit_code = 2
        elif not all(existing.values()):
            status = "MISMATCH_C4"
            mismatches = [f"table presence mismatch: {existing}"]
            exit_code = 1
        else:
            mismatches = []
            for table_name in EXPECTED_COLUMNS:
                mismatches.extend(_column_mismatches(inspector, table_name))
                mismatches.extend(_constraint_mismatches(inspector, table_name))
            status = "MATCH_C4" if not mismatches else "MISMATCH_C4"
            exit_code = 0 if not mismatches else 1

        with engine.connect() as connection:
            current_revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one_or_none()

        report = {
            "status": status,
            "database": {"host": url.host, "port": url.port, "name": url.database},
            "current_revision": current_revision,
            "tables": existing,
            "mismatches": mismatches,
        }
        return report, exit_code
    finally:
        engine.dispose()


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    args = parser.parse_args()
    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")

    report, exit_code = build_report(args.database_url)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
