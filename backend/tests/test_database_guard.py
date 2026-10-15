from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from app.config import Settings
from app.db import assert_project_database


@pytest.mark.parametrize("changes", [
    {},
    {"name": "unrelated"}, {"role": "postgres"}, {"owner": "unrelated"},
    {"marker": None}, {"marker": "document-research-assistant:test"},
    {"rolsuper": True}, {"rolcreatedb": True}, {"rolcreaterole": True},
    {"rolreplication": True}, {"rolbypassrls": True},
])
def test_guard_accepts_only_verified_database(changes):
    row = dict(
        name="dra_dev", role="dra_dev", owner="dra_dev",
        marker="document-research-assistant:development", rolsuper=False,
        rolcreatedb=False, rolcreaterole=False, rolreplication=False, rolbypassrls=False,
    )
    row.update(changes)
    connection = Mock()
    connection.execute.return_value.mappings.return_value.one.return_value = row
    settings = Settings(
        _env_file=None, db_password="synthetic-password", test_db_password=None,
        app_env="development", db_name="dra_dev", db_user="dra_dev",
    )
    outcome = pytest.raises(RuntimeError, match="identity mismatch") if changes else nullcontext()
    with outcome:
        assert_project_database(connection, settings)
