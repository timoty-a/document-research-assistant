"""Temporary isolated HTTP backend for frontend trials; only dra_test is writable.

Run from the repository root with .venv/bin/python frontend/scripts/test_backend.py.
Stop with Ctrl+C. Only this process's generated schema is removed on normal exit.
"""
import sys
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))

import uvicorn
from alembic import command
from alembic.config import Config
from sqlalchemy import event
from app.config import Settings
from app.db import assert_project_database, create_db_engine
from app.main import create_app


def main():
    local = Settings()
    if local.test_db_password is None:
        raise SystemExit('Configure TEST_DB_PASSWORD privately before running this trial.')
    settings = Settings(_env_file=None, app_env='test', db_name='dra_test', db_user='dra_test',
                        db_host=local.db_host, db_port=local.db_port,
                        db_password=local.test_db_password)
    engine = create_db_engine(settings)
    schema = 'dra_frontend_trial_' + uuid4().hex
    created = False
    app = create_app(settings)
    try:
        with engine.begin() as connection:
            assert_project_database(connection, settings)
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        created = True

        @event.listens_for(app.state.engine, 'connect')
        def private_search_path(dbapi, record):
            previous = dbapi.autocommit
            dbapi.autocommit = True
            with dbapi.cursor() as cursor:
                cursor.execute(f'SET search_path TO "{schema}"')
            dbapi.autocommit = previous

        with app.state.engine.begin() as connection:
            config = Config(str(Path(__file__).resolve().parents[2] / 'backend' / 'alembic.ini'))
            config.attributes.update(connection=connection, settings=settings)
            command.upgrade(config, 'head')
        print('Isolated frontend trial: verified dra_test role/database; private temporary schema.')
        uvicorn.run(app, host='127.0.0.1', port=8000, access_log=False, proxy_headers=False)
    finally:
        app.state.engine.dispose()
        if created:
            with engine.begin() as connection:
                assert_project_database(connection, settings)
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            print('Removed only this trial schema. Existing test records were preserved.')
        engine.dispose()


if __name__ == '__main__':
    main()
