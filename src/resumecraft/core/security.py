import uuid

import jwt
from jwt import PyJWKClient

from resumecraft.core.config import Settings
from resumecraft.schemas.auth import CurrentUser


class AuthConfigError(Exception):
    """Raised when auth is not configured (no secret, no JWKS URL)."""


def decode_supabase_token(token: str, settings: Settings) -> CurrentUser:
    """Validate a Supabase JWT and extract the user id from the `sub` claim.

    Uses RS256 via JWKS when RC_SUPABASE_JWKS_URL is set (prod), otherwise
    falls back to HS256 with the project's JWT secret (dev).
    """
    if settings.supabase_jwks_url:
        signing_key = PyJWKClient(settings.supabase_jwks_url).get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token, signing_key.key, algorithms=["RS256"], options={"verify_aud": False}
        )
    elif settings.supabase_jwt_secret is not None:
        payload = jwt.decode(
            token,
            settings.supabase_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            options={"verify_aud": False},
        )
    else:
        raise AuthConfigError("Set RC_SUPABASE_JWT_SECRET or RC_SUPABASE_JWKS_URL")

    return CurrentUser(user_id=uuid.UUID(payload["sub"]))
