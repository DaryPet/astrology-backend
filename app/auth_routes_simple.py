"""
Простой роутер аутентификации - НЕ трогает существующий код
Добавляется как отдельный роутер в main.py
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr, validator
import re
from typing import Optional

from app.db.database import get_db, engine
from app.auth_models import AuthUser, AuthBase
from app.auth_simple import (
    get_password_hash, authenticate_user,
    create_access_token, get_current_user,
    get_current_active_user
)

router = APIRouter(tags=["authentication"])


# Схемы Pydantic
class UserRegister(BaseModel):
    """Схема для регистрации"""
    email: EmailStr
    password: str
    name: Optional[str] = None
    
    @validator('password')
    def validate_password(cls, v):
        """Валидация пароля"""
        if len(v) < 8:
            raise ValueError('Пароль должен содержать минимум 8 символов')
        if not re.search(r'[A-Za-z]', v):
            raise ValueError('Пароль должен содержать буквы')
        if not re.search(r'\d', v):
            raise ValueError('Пароль должен содержать цифры')
        return v


class UserLogin(BaseModel):
    """Схема для входа"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Схема токена"""
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    """Схема ответа пользователя"""
    id: int
    email: str
    name: Optional[str]
    created_at: datetime
    
    class Config:
        from_attributes = True


@router.post("/api/auth/register", response_model=Token)
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """Регистрация пользователя"""
    # Проверяем существование пользователя
    result = await db.execute(select(AuthUser).where(AuthUser.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже существует"
        )
    
    # Создаем пользователя
    hashed_password = get_password_hash(user_data.password)
    now = datetime.utcnow()
    
    db_user = AuthUser(
        email=user_data.email,
        password=hashed_password,
        name=user_data.name,
        created_at=now,
        updated_at=now
    )
    
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    
    # Создаем токен
    access_token = create_access_token(data={"sub": db_user.email})
    
    return Token(access_token=access_token)


@router.post("/api/auth/login", response_model=Token)
async def login(
    user_data: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """Вход пользователя"""
    user = await authenticate_user(db, user_data.email, user_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль"
        )
    
    # Создаем токен
    access_token = create_access_token(data={"sub": user.email})
    
    return Token(access_token=access_token)


@router.get("/api/auth/me", response_model=UserResponse)
async def get_me(
    current_user: AuthUser = Depends(get_current_active_user)
):
    """Получение информации о текущем пользователе"""
    return UserResponse.from_orm(current_user)


@router.post("/api/auth/logout")
async def logout():
    """Выход пользователя"""
    return {"message": "Успешный выход из системы"}


@router.get("/api/dashboard")
async def dashboard(
    current_user: AuthUser = Depends(get_current_active_user)
):
    """Пустой dashboard - требует аутентификации"""
    return {
        "message": "Добро пожаловать в dashboard!",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name
        },
        "data": None  # Для будущих данных
    }