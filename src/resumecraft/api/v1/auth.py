"""Auth endpoints: register, login, and the current user.

Registering and authenticating are separate steps: `POST /auth/register`
returns the account, not a token — `POST /auth/login` is still required.
"""

from fastapi import APIRouter, status

from resumecraft.api.deps import CurrentUserDep, DbSession, SettingsDep
from resumecraft.api.responses import INVALID_INPUT, UNAUTHENTICATED, error
from resumecraft.core.exceptions import AuthenticationError
from resumecraft.core.security import create_access_token
from resumecraft.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenOut,
    UserOut,
)
from resumecraft.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        409: error(
            "The email already has an account (`email_already_registered`)",
            "email_already_registered",
            "Email already registered",
            {"email": "user@example.com"},
        ),
        422: INVALID_INPUT,
    },
)
async def register(body: RegisterRequest, db: DbSession) -> UserOut:
    user = await user_service.register(db, body)
    return UserOut.model_validate(user)


@router.post(
    "/login",
    response_model=TokenOut,
    responses={
        401: error(
            "Unknown email or wrong password — deliberately indistinguishable (`unauthenticated`)",
            "unauthenticated",
            "Incorrect email or password",
        ),
        422: INVALID_INPUT,
    },
)
async def login(body: LoginRequest, db: DbSession, settings: SettingsDep) -> TokenOut:
    user = await user_service.authenticate(db, body.email, body.password)
    token = create_access_token(user.id, settings=settings)
    return TokenOut(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.get("/me", response_model=UserOut, responses={401: UNAUTHENTICATED})
async def read_me(db: DbSession, user: CurrentUserDep) -> UserOut:
    try:
        current = await user_service.get(db, user.user_id)
    except LookupError:
        # A token whose account is gone must not resolve.
        raise AuthenticationError("Invalid token") from None
    return UserOut.model_validate(current)
