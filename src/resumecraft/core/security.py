"""Password hashing and local JWT access tokens.

Local-only auth (SSKF-AI pattern, simplified):

- Passwords: bcrypt. The hash records its own cost, so `needs_rehash` can raise the
  work factor later without forcing a reset. bcrypt reads at most 72 bytes of
  input; the register schema refuses longer input first so the caller gets a 422
  naming the field instead of a 500 from inside the hasher.
- Tokens: HS256, signed and verified by this service with `RC_JWT_SECRET_KEY`.
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from resumecraft.core.config import Settings

BCRYPT_ROUNDS = 12
BCRYPT_MAX_BYTES = 72


def hash_password(password: str) -> str:
    """Return a self-describing bcrypt hash (variant and cost included)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time verification. Returns False on every failure, never raises."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True when the stored hash was made with a lower work factor than we now use.

    Call after a successful `verify_password` and, if true, store `hash_password(...)`
    again at the next login — this is how the cost gets raised without a migration.
    """
    parts = hashed.split("$")
    if len(parts) < 4 or not parts[2].isdigit():
        return True
    return int(parts[2]) < BCRYPT_ROUNDS


def create_access_token(user_id: uuid.UUID, settings: Settings) -> str:
    """Sign an HS256 access token for `user_id`."""
    now = datetime.now(UTC)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key.get_secret_value(), algorithm="HS256")


def decode_access_token(token: str, settings: Settings) -> uuid.UUID:
    """Verify signature and expiry; return the user id from the `sub` claim.

    Raises `jwt.InvalidTokenError` (or KeyError/ValueError for a malformed `sub`)
    on any failure — the API layer maps those to a 401.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key.get_secret_value(),
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
    return uuid.UUID(payload["sub"])
