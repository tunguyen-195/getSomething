import os
import re
import sys

import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url


load_dotenv()


def _build_test_database_url() -> URL:
    explicit_url = os.getenv("TEST_DATABASE_URL")
    if explicit_url:
        test_url = make_url(explicit_url)
    else:
        configured_url = os.getenv("DATABASE_URL")
        if configured_url:
            test_url = make_url(configured_url)
        else:
            database_name = os.getenv("POSTGRES_DB", "speech_to_info")
            test_url = URL.create(
                "postgresql",
                username=os.getenv("POSTGRES_USER", "postgres"),
                password=os.getenv("POSTGRES_PASSWORD", "postgres"),
                host=os.getenv("POSTGRES_HOST", "localhost"),
                port=int(os.getenv("POSTGRES_PORT", "5432")),
                database=database_name,
            )

        database_name = test_url.database or "speech_to_info"
        if not database_name.endswith("_test"):
            database_name = f"{database_name}_test"
        test_url = test_url.set(database=database_name)

    database_name = test_url.database or ""
    if not re.fullmatch(r"[A-Za-z0-9_]+_test", database_name):
        raise RuntimeError(
            "Refusing to run tests: TEST_DATABASE_URL must target a database whose name ends with '_test'"
        )
    return test_url


def _ensure_test_database(test_url: URL) -> None:
    database_name = test_url.database
    maintenance_database = os.getenv("TEST_DATABASE_ADMIN_DB", "postgres")
    maintenance_url = test_url.set(database=maintenance_database)
    maintenance_engine = create_engine(maintenance_url, isolation_level="AUTOCOMMIT")
    try:
        with maintenance_engine.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        maintenance_engine.dispose()


TEST_DATABASE_URL = _build_test_database_url()
_ensure_test_database(TEST_DATABASE_URL)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL.render_as_string(hide_password=False)

os.environ["ENVIRONMENT"] = "test"
os.environ["DEBUG"] = "true"
os.environ["AUTH_ENABLED"] = "false"
os.environ["DEV_AUTH_BYPASS"] = "true"
os.environ["DEV_USER_ID"] = "1"
os.environ["INIT_DB_ON_STARTUP"] = "false"
os.environ["INITIAL_ADMIN_PASSWORD"] = "test-admin-password"
os.environ["SECRET_KEY"] = "test-secret-key-with-enough-length-1234567890"
os.environ["RATE_LIMIT_ENABLED"] = "false"

# Add the project root directory to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))


from src.database.config.database import Base, SessionLocal, engine, get_db  # noqa: E402
from src.database.init_db import init_db  # noqa: E402
from src.database.models import models as _models  # noqa: E402,F401
from src.main import app  # noqa: E402


def _override_get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def isolated_test_database():
    """Reset only the dedicated PostgreSQL test database for every test."""
    Base.metadata.drop_all(bind=engine)
    init_db(create_schema=True)
    try:
        yield
    finally:
        Base.metadata.drop_all(bind=engine)
