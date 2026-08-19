"""Read-only inventory of test-like records in a SpeechToInfomation database."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url


COUNT_QUERIES = {
    "users": """
        SELECT count(*) FROM users
        WHERE username LIKE 'user\\_%' ESCAPE '\\'
          AND email LIKE '%@example.test'
    """,
    "cases": """
        SELECT count(*) FROM cases
        WHERE title LIKE 'case\\_%' ESCAPE '\\'
    """,
    "tasks": """
        SELECT count(*) FROM tasks
        WHERE filename IN ('restricted.wav', 'orphan.wav')
    """,
    "audio_files": """
        SELECT count(*) FROM audio_files
        WHERE filename ~ '^[0-9a-f]{32}\\.wav$'
          AND file_size = 10
          AND duration = 1.0
    """,
    "summaries": """
        SELECT count(*) FROM summaries
        WHERE content IN ('user a summary', 'user b summary')
           OR content LIKE 'private orphan%'
    """,
}


TIMESTAMP_QUERIES = {
    "users": """
        SELECT min(created_at), max(created_at) FROM users
        WHERE username LIKE 'user\\_%' ESCAPE '\\'
          AND email LIKE '%@example.test'
    """,
    "cases": """
        SELECT min(created_at), max(created_at) FROM cases
        WHERE title LIKE 'case\\_%' ESCAPE '\\'
    """,
    "tasks": """
        SELECT min(created_at), max(created_at) FROM tasks
        WHERE filename IN ('restricted.wav', 'orphan.wav')
    """,
}


def _json_value(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return value


def build_report(database_url: str) -> dict:
    url = make_url(database_url)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            counts = {
                name: connection.execute(text(query)).scalar_one()
                for name, query in COUNT_QUERIES.items()
            }
            timestamp_ranges = {}
            for name, query in TIMESTAMP_QUERIES.items():
                minimum, maximum = connection.execute(text(query)).one()
                timestamp_ranges[name] = {
                    "minimum": _json_value(minimum),
                    "maximum": _json_value(maximum),
                }

        inspector = inspect(engine)
        candidate_tables = set(COUNT_QUERIES)
        foreign_key_fanout = []
        for table_name in inspector.get_table_names():
            for foreign_key in inspector.get_foreign_keys(table_name):
                referred_table = foreign_key.get("referred_table")
                if referred_table in candidate_tables:
                    foreign_key_fanout.append(
                        {
                            "source_table": table_name,
                            "source_columns": foreign_key.get("constrained_columns", []),
                            "target_table": referred_table,
                            "target_columns": foreign_key.get("referred_columns", []),
                        }
                    )

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "mode": "read_only",
            "database": {
                "driver": url.drivername,
                "host": url.host,
                "port": url.port,
                "name": url.database,
            },
            "candidate_counts": counts,
            "candidate_timestamp_ranges": timestamp_ranges,
            "foreign_key_fanout": sorted(
                foreign_key_fanout,
                key=lambda item: (item["target_table"], item["source_table"]),
            ),
            "warning": (
                "Candidates are pattern matches, not deletion authorization. "
                "Back up and review every candidate set before cleanup."
            ),
        }
    finally:
        engine.dispose()


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL"))
    parser.add_argument("--output", help="Optional JSON output path")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Reserved for an approved cleanup implementation; always refused for safety",
    )
    args = parser.parse_args()

    if not args.database_url:
        parser.error("DATABASE_URL or --database-url is required")
    if args.apply:
        parser.error(
            "Cleanup is intentionally disabled. Review the audit, create a backup, "
            "and obtain explicit approval before implementing deletion."
        )

    report = build_report(args.database_url)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(serialized + "\n")
    print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
