"""Registration, credential checks, and reading the current user.

Registration is open, so every method here is reachable by anyone with the URL.
That shapes three choices below: the constant work done for an unknown email,
the single error message shared by every authentication failure, and the
rehash-on-login upgrade path.
"""

import secrets
from functools import lru_cache

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.exceptions import AuthenticationError, EmailAlreadyRegisteredError
from resumecraft.core.security import hash_password, needs_rehash, verify_password
from resumecraft.db.models import User
from resumecraft.db.repositories import user as user_repo
from resumecraft.schemas.auth import RegisterRequest

#: One message for every way authentication can fail — wrong password, unknown
#: email, deactivated account. Telling them apart tells an attacker which emails
#: are registered.
_REJECTED = "Incorrect email or password"


@lru_cache(maxsize=1)
def _decoy_hash() -> str:
    """A hash to verify against when the email does not exist.

    Skipping the verify for an unknown email makes that path measurably faster
    than a wrong password, which turns response time into an account-existence
    oracle. Computed once, lazily, from bytes nobody holds — so it can never
    match a real password.
    """
    return hash_password(secrets.token_urlsafe(32))


async def register(session: AsyncSession, body: RegisterRequest) -> User:
    email = str(body.email).lower()

    # Checked first so the common case is a clean 409, but the insert is still
    # guarded below because two concurrent registrations both pass this check.
    if await user_repo.get_by_email(session, email) is not None:
        raise EmailAlreadyRegisteredError(email)

    user = User(email=email, password=hash_password(body.password))
    try:
        await user_repo.create(session, user)
    except IntegrityError as exc:
        raise EmailAlreadyRegisteredError(email) from exc
    await session.commit()
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await user_repo.get_by_email(session, email.lower())

    if user is None:
        verify_password(password, _decoy_hash())
        raise AuthenticationError(_REJECTED)

    if not verify_password(password, user.password):
        raise AuthenticationError(_REJECTED)

    if not user.is_active:
        # Checked after the password so a deactivated account cannot be
        # distinguished from a wrong one by anybody who does not already know
        # the password.
        raise AuthenticationError(_REJECTED)

    if needs_rehash(user.password):
        user.password = hash_password(password)
        await session.commit()

    return user


async def get(session: AsyncSession, user_id) -> User:
    user = await user_repo.get_by_id(session, user_id)
    if user is None:
        # Reachable with a token whose user has since been deactivated/deleted:
        # the token is still signed and unexpired, but the account behind it is
        # gone.
        raise LookupError(f"User {user_id} not found")
    return user
