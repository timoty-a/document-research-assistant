"""Database tests require an explicit flag and always target dra_test."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import Settings
from app.db import assert_project_database, create_db_engine


def pytest_addoption(parser):
    parser.addoption("--database", action="store_true", help="Enable dra_test integration tests")


@pytest.fixture(scope="session")
def test_engine(request):
    if not request.config.getoption("--database"):
        pytest.skip("Use --database after provisioning the dedicated dra_test database")
    local = Settings()
    if local.test_db_password is None:
        pytest.fail("TEST_DB_PASSWORD is required for explicit database tests")
    settings = Settings(
        _env_file=None,
        app_env="test",
        db_host=local.db_host,
        db_port=local.db_port,
        db_name="dra_test",
        db_user="dra_test",
        db_password=local.test_db_password,
        test_db_password=None,
    )
    engine = create_db_engine(settings)
    patch = pytest.MonkeyPatch()
    try:
        # Verify identity before any migration or test write.
        with engine.connect() as connection:
            assert_project_database(connection, settings)
        for key, value in {
            "APP_ENV": "test", "DB_NAME": "dra_test", "DB_USER": "dra_test",
            "DB_HOST": settings.db_host, "DB_PORT": str(settings.db_port),
            "DB_PASSWORD": settings.db_password.get_secret_value(),
        }.items():
            patch.setenv(key, value)
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        yield engine
    finally:
        patch.undo()
        engine.dispose()


@pytest.fixture
def db_connection(test_engine):
    # Every test row rolls back; never truncate tables or drop a database.
    with test_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()
