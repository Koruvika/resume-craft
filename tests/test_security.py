import time
import uuid

import jwt
import pytest

from resumecraft.core.config import Settings
from resumecraft.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    needs_rehash,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_verify_password_never_raises_on_garbage() -> None:
    assert not verify_password("whatever", "not-a-bcrypt-hash")


def test_needs_rehash() -> None:
    low_cost = "$2b$04$" + "x" * 53
    assert needs_rehash(low_cost)
    assert not needs_rehash(hash_password("some long passphrase"))


def test_token_round_trip() -> None:
    settings = Settings(_env_file=None)
    user_id = uuid.uuid4()
    token = create_access_token(user_id, settings=settings)
    assert decode_access_token(token, settings) == user_id


def test_expired_token_rejected() -> None:
    settings = Settings(_env_file=None, access_token_expire_minutes=-10)
    token = create_access_token(uuid.uuid4(), settings=settings)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, settings)


def test_wrong_secret_rejected() -> None:
    token = create_access_token(uuid.uuid4(), settings=Settings(_env_file=None))
    other = Settings(_env_file=None, jwt_secret_key="a-completely-different-key")
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, other)


def test_token_requires_sub_claim() -> None:
    settings = Settings(_env_file=None)
    token = jwt.encode(
        {"exp": int(time.time()) + 600},
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, settings)
