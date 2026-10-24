from typing import Annotated

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from resumecraft.core.config import Settings, get_settings
from resumecraft.core.exceptions import AuthenticationError
from resumecraft.core.security import decode_access_token
from resumecraft.db.session import get_session
from resumecraft.schemas.auth import CurrentUser

_bearer = HTTPBearer(auto_error=False)

DbSession = Annotated[AsyncSession, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: SettingsDep,
) -> CurrentUser:
    if credentials is None:
        raise AuthenticationError("Not authenticated")
    try:
        user_id = decode_access_token(credentials.credentials, settings)
    except (jwt.InvalidTokenError, KeyError, ValueError):
        raise AuthenticationError("Invalid token") from None
    return CurrentUser(user_id=user_id)


CurrentUserDep = Annotated[CurrentUser, Depends(get_current_user)]
