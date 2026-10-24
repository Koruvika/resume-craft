"""Auth DTOs and the authenticated principal."""

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from resumecraft.core.security import BCRYPT_MAX_BYTES

#: Length rather than composition rules, per NIST SP 800-63B: forced symbols and
#: digits push people towards `Password1!` while a longer passphrase is genuinely
#: harder.
PASSWORD_MIN_LENGTH = 12


def _within_bcrypt_input_limit(value: str) -> str:
    """Refuse a password bcrypt would only partly read.

    bcrypt reads at most 72 **bytes**, so a character count is not a sufficient
    guard: 25 Japanese characters are 75 bytes. Checked here so the caller gets
    a 422 naming the field instead of a 500 from inside the hasher.
    """
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(
            f"must be at most {BCRYPT_MAX_BYTES} bytes once UTF-8 encoded "
            f"(this is {len(value.encode('utf-8'))}); bcrypt ignores anything beyond that"
        )
    return value


Password = Annotated[str, AfterValidator(_within_bcrypt_input_limit)]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: Password = Field(min_length=PASSWORD_MIN_LENGTH, max_length=BCRYPT_MAX_BYTES)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=BCRYPT_MAX_BYTES)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the token expires")


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    is_active: bool
    created_at: datetime


class CurrentUser(BaseModel):
    """Authenticated principal extracted from the access token."""

    user_id: uuid.UUID
