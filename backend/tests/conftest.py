"""Every database mutation/migration uses a unique schema in verified dra_test."""
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, insert

from app.config import Settings
from app.db import assert_project_database, create_db_engine


BACKEND = Path(__file__).resolve().parents[1]


def pytest_addoption(parser):
    parser.addoption("--database", action="store_true", help="Enable isolated dra_test integration tests")


def migrate(engine, settings, revision="head"):
    with engine.begin() as connection:
        config = Config(str(BACKEND / "alembic.ini"))
        config.attributes.update(connection=connection, settings=settings)
        command.upgrade(config, revision)


def scoped_engine(settings, schema):
    engine = create_db_engine(settings)

    @event.listens_for(engine, "connect")
    def path(dbapi, record):
        # Generated identifier only. Set outside transactions so rollbacks do not
        # restore public search_path. No fallback to public tables is permitted.
        prior = dbapi.autocommit
        dbapi.autocommit = True
        with dbapi.cursor() as cursor:
            cursor.execute(f'SET search_path TO "{schema}"')
        dbapi.autocommit = prior
    return engine


@contextmanager
def isolated_database(settings, revision="head"):
    assert settings.app_env == "test" and settings.db_name == settings.db_user == "dra_test"
    admin = create_db_engine(settings)
    schema = "dra_test_" + uuid4().hex
    engines = []
    created = False
    try:
        with admin.begin() as connection:
            assert_project_database(connection, settings)
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            created = True

        def make_engine():
            engine = scoped_engine(settings, schema)
            engines.append(engine)
            return engine

        engine = make_engine()
        migrate(engine, settings, revision)
        from app.main import create_app

        def make_app():
            app = create_app(settings)
            app.state.engine.dispose()
            app.state.engine = make_engine()
            return app

        yield SimpleNamespace(engine=engine, settings=settings, schema=schema,
                              make_engine=make_engine, make_app=make_app)
    finally:
        for engine in engines:
            engine.dispose()
        if created:
            with admin.begin() as connection:
                assert_project_database(connection, settings)
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


@pytest.fixture(scope="session")
def test_settings(request):
    if not request.config.getoption("--database"):
        pytest.skip("Use --database for isolated dra_test integration tests")
    local = Settings()
    if local.test_db_password is None:
        pytest.fail("TEST_DB_PASSWORD is required for explicit database tests")
    return Settings(_env_file=None, app_env="test", db_host=local.db_host, db_port=local.db_port,
                    db_name="dra_test", db_user="dra_test", db_password=local.test_db_password,
                    ai_enabled=False, groq_api_key=None)


@pytest.fixture(scope="session")
def test_engine(test_settings):
    with isolated_database(test_settings) as database:
        yield database.engine


@pytest.fixture
def db_connection(test_engine):
    with test_engine.connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.fixture
def auth_database(test_settings):
    with isolated_database(test_settings) as database:
        yield database


@pytest.fixture
def api_database(test_settings):
    """Existing document contract tests receive a genuine persisted identity."""
    from app.auth.models import User
    from app.auth.service import new_session, utcnow
    from app.auth.security import dummy_hash
    with isolated_database(test_settings) as database:
        with database.engine.begin() as connection:
            user = connection.scalar(insert(User).values(email="synthetic@example.com", email_key="synthetic@example.com", password_hash=dummy_hash()).returning(User.id))
            raw, identity = new_session(connection, user, utcnow())
        original_make_app = database.make_app

        def make_app():
            app = original_make_app()
            app.state.test_auth = (raw, identity.csrf_token)
            return app
        database.make_app = make_app
        database.user_id = user
        yield database


# Share HTTP/auth fixtures with transaction-focused tests.
from auth_helpers import Browser, Clock

@pytest.fixture
def browsers(auth_database):
    clock = Clock()
    clients = []

    def make():
        browser = Browser(auth_database, clock)
        clients.append(browser)
        return browser
    yield make, clock, auth_database
    for browser in clients:
        browser.client.close()
        browser.app.state.engine.dispose()
