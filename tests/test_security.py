import time
import uuid

import jwt
import pytest

from resumecraft.core.config import Settings
from resumecraft.core.security import AuthConfigError, decode_supabase_token

SECRET = "test-secret"


def _make_token(secret: str, sub: str, expires_at: int | None = None) -> str:
    payload: dict = {"sub": sub, "exp": expires_at or int(time.time()) + 600}
    return jwt.encode(payload, secret, algorithm="HS256")


def test_decodes_valid_hs256_token() -> None:
    user_id = uuid.uuid4()
    settings = Settings(_env_file=None, supabase_jwt_secret=SECRET)
    token = _make_token(SECRET, str(user_id))
    current = decode_supabase_token(token, settings)
    assert current.user_id == user_id


def test_rejects_expired_token() -> None:
    settings = Settings(_env_file=None, supabase_jwt_secret=SECRET)
    token = _make_token(SECRET, str(uuid.uuid4()), expires_at=int(time.time()) - 10)
    with pytest.raises(jwt.InvalidTokenError):
        decode_supabase_token(token, settings)


def test_rejects_wrong_secret() -> None:
    settings = Settings(_env_file=None, supabase_jwt_secret=SECRET)
    token = _make_token("other-secret", str(uuid.uuid4()))
    with pytest.raises(jwt.InvalidTokenError):
        decode_supabase_token(token, settings)


def test_raises_when_unconfigured() -> None:
    settings = Settings(_env_file=None)
    token = _make_token(SECRET, str(uuid.uuid4()))
    with pytest.raises(AuthConfigError):
        decode_supabase_token(token, settings)
