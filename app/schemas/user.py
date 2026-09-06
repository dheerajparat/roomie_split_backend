from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict, field_validator
from typing import Optional
from app.core.security import MAX_BCRYPT_PASSWORD_BYTES

class UserBase(BaseModel):
    email: EmailStr
    username: str
    full_name: str

class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def validate_bcrypt_password_length(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
            raise ValueError("Password cannot be longer than 72 bytes.")
        return value

class UserLogin(BaseModel):
    username_or_email: str
    password: str

class UserOut(UserBase):
    id: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut

class TokenData(BaseModel):
    user_id: Optional[int] = None
