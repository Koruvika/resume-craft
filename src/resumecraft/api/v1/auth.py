"""Auth endpoints: register, login, and the current user.

Registering and authenticating are separate steps: `POST /auth/register`
returns the account, not a token — `POST /auth/login` is still required.
"""

from fastapi import APIRouter, HTTPException, status

from resumecraft.api.deps import CurrentUserDep, DbSession, SettingsDep
from resumecraft.core.security import create_access_token
from resumecraft.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    TokenOut,
    UserOut,
)
from resumecraft.services import user_service
from resumecraft.services.user_service import (
    AuthenticationError,
    EmailAlreadyRegisteredError,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, db: DbSession) -> UserOut:
    try:
        user = await user_service.register(db, body)
    except EmailAlreadyRegisteredError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        ) from None
    return UserOut.model_validate(user)


@router.post("/login", response_model=TokenOut)
async def login(body: LoginRequest, db: DbSession, settings: SettingsDep) -> TokenOut:
    try:
        user = await user_service.authenticate(db, body.email, body.password)
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password"
        ) from None
    token = create_access_token(user.id, settings=settings)
    return TokenOut(access_token=token, expires_in=settings.access_token_expire_minutes * 60)


@router.get("/me", response_model=UserOut)
async def read_me(db: DbSession, user: CurrentUserDep) -> UserOut:
    try:
        current = await user_service.get(db, user.user_id)
    except LookupError:
        # A token whose account is gone must not resolve.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        ) from None
    return UserOut.model_validate(current)
