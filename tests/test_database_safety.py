import os

from sqlalchemy.engine import make_url

from src.database.config.database import SQLALCHEMY_DATABASE_URL, engine


def test_pytest_uses_dedicated_test_database():
    configured = make_url(SQLALCHEMY_DATABASE_URL)
    bound = make_url(str(engine.url))

    assert configured.database and configured.database.endswith("_test")
    assert bound.database and bound.database.endswith("_test")
    assert os.environ["DATABASE_URL"] == configured.render_as_string(hide_password=False)


def test_live_database_name_is_never_the_pytest_target():
    production_name = os.getenv("POSTGRES_DB", "speech_to_info")
    test_name = make_url(SQLALCHEMY_DATABASE_URL).database

    if not production_name.endswith("_test"):
        assert test_name != production_name
