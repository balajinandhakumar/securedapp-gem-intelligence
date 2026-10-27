from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserBase(BaseModel):
    email: EmailStr
    name: str = Field(..., min_length=1, max_length=255)
    role: str = "reviewer"
    active: bool = True


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserResponse(UserBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
