from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.core.config import settings


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=settings.PASSWORD_MIN_LENGTH, max_length=128)
    full_name: str = Field(default="", max_length=160)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str
    is_active: bool
    is_admin: bool = False

    model_config = {"from_attributes": True}
