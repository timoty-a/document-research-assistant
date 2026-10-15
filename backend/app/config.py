"""Validated local configuration; never render database passwords as text."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
    )

    app_env: Literal["development", "test"] = "development"
    db_host: Literal["127.0.0.1", "localhost"] = "127.0.0.1"
    db_port: int = Field(default=5432, ge=1, le=65535)
    db_name: Literal["dra_dev", "dra_test"] = "dra_dev"
    db_user: Literal["dra_dev", "dra_test"] = "dra_dev"
    db_password: SecretStr
    test_db_password: SecretStr | None = None

    @field_validator("db_password", "test_db_password")
    @classmethod
    def require_real_password(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            password = value.get_secret_value()
            if not password.strip() or password.startswith("REPLACE_"):
                raise ValueError("Set a non-empty local database password")
        return value

    @model_validator(mode="after")
    def match_database_target(self) -> "Settings":
        expected = "dra_test" if self.app_env == "test" else "dra_dev"
        if self.db_name != expected or self.db_user != expected:
            raise ValueError("Database and role must match the application environment")
        return self

    @property
    def database_url(self) -> URL:
        # URL.create safely handles special characters in passwords.
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password.get_secret_value(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )
