"""Credential validation and established hashing; no request-value logging."""
from functools import lru_cache
from threading import BoundedSemaphore

from email_validator import validate_email
from pydantic import BaseModel, ConfigDict, SecretStr, field_validator
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

HASH_CONCURRENCY = 2
_slots = BoundedSemaphore(HASH_CONCURRENCY)
passwords = PasswordHash((Argon2Hasher(memory_cost=65536, time_cost=3, parallelism=4),))


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)
    email: str
    password: SecretStr

    @field_validator("email")
    @classmethod
    def bounded_email(cls, value):
        if len(value) > 320 or len(value.encode("utf-8")) > 1024 or "\x00" in value:
            raise ValueError("Invalid credentials")
        return value.strip()

    @field_validator("password")
    @classmethod
    def bounded_password(cls, value):
        raw = value.get_secret_value()
        if not 15 <= len(raw) <= 128 or len(raw.encode("utf-8")) > 512:
            raise ValueError("Invalid credentials")
        return value

    def identity(self):
        address = validate_email(self.email, check_deliverability=False, allow_smtputf8=False)
        key = address.ascii_email.lower()
        if len(key.encode("ascii")) > 254:
            raise ValueError("Invalid credentials")
        return address.normalized, key


def hash_password(value: SecretStr) -> str:
    with _slots:
        return passwords.hash(value.get_secret_value())


@lru_cache(maxsize=1)
def dummy_hash():
    return hash_password(SecretStr("Synthetic dummy verification password only"))


def verify_password(value: SecretStr, encoded: str | None):
    # Initialize before acquiring the semaphore: dummy initialization hashes too.
    target = encoded if encoded is not None else dummy_hash()
    with _slots:
        try:
            return passwords.verify_and_update(value.get_secret_value(), target)
        except (UnknownHashError, ValueError):
            from app.auth.service import AuthError
            raise AuthError(503, "unavailable", "Service is temporarily unavailable.") from None
