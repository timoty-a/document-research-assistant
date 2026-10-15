import pytest
from pydantic import ValidationError

from app.config import Settings


def settings(**overrides):
    values = dict(
        _env_file=None, app_env="development", db_host="127.0.0.1", db_port=5432,
        db_name="dra_dev", db_user="dra_dev", db_password="synthetic-password",
        test_db_password=None,
    )
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("overrides", [
    {"db_port": 0}, {"db_port": 65536}, {"db_host": "remote.example.com"},
    {"db_name": "another_project"}, {"db_user": "postgres"},
    {"app_env": "test"}, {"db_name": "dra_test", "db_user": "dra_test"},
    {"db_password": ""}, {"db_password": "   "}, {"db_password": "REPLACE_PASSWORD"},
])
def test_invalid_or_mismatched_configuration_is_rejected(overrides):
    with pytest.raises(ValidationError):
        settings(**overrides)


def test_url_handles_special_characters_and_masks_password():
    config = settings(db_password="synthetic:@/%password")
    assert config.database_url.password == "synthetic:@/%password"
    assert "synthetic" not in str(config.database_url)
    assert "synthetic" not in repr(config)


def test_validation_message_does_not_display_secret():
    with pytest.raises(ValidationError) as error:
        settings(db_port=0, db_password="private-test-value")
    assert "private-test-value" not in str(error.value)


def test_test_environment_requires_test_role_and_database():
    config = settings(app_env="test", db_name="dra_test", db_user="dra_test")
    assert config.database_url.database == "dra_test"
