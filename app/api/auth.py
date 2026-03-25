"""
Роутер для аутентификации
- Регистрация
- Вход
- Выход
- Обновление токена
- Получение информации о пользователе
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status, Response
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import (
    UserRegister, UserLogin, UserResponse, Token,
    RefreshTokenRequest, UserUpdate
)
from app.auth import (
    get_password_hash, authenticate_user,
    create_tokens_for_user, verify_token,
    create_access_token, get_current_active_user,
    get_current_user_optional
)

router = APIRouter(prefix="/auth", tags=["authentication"])
security = HTTPBearer(auto_error=False)


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(
    user_data: UserRegister,
    db: AsyncSession = Depends(get_db)
):
    """
    Регистрация нового пользователя
    - Только email и пароль
    - Имя опционально
    - Возвращает access и refresh токены
    """
    # Проверяем существует ли пользователь с таким email
    result = await db.execute(select(User).where(User.email == user_data.email))
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Пользователь с таким email уже существует"
        )
    
    # Создаем нового пользователя
    hashed_password = get_password_hash(user_data.password)
    now = datetime.utcnow()
    
    db_user = User(
        email=user_data.email,
        password=hashed_password,
        name=user_data.name,
        created_at=now,
        updated_at=now
    )
    
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    
    # Создаем токены
    tokens = create_tokens_for_user(db_user)
    
    return Token(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
        user=UserResponse.from_orm(db_user)
    )


@router.post("/login", response_model=Token)
async def login(
    user_data: UserLogin,
    db: AsyncSession = Depends(get_db)
):
    """
    Вход пользователя
    - Проверка email и пароля
    - Возвращает access и refresh токены
    """
    user = await authenticate_user(db, user_data.email, user_data.password)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Создаем токены
    tokens = create_tokens_for_user(user)
    
    return Token(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
        user=UserResponse.from_orm(user)
    )


@router.post("/refresh", response_model=Token)
async def refresh_token(
    token_data: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Обновление access token с помощью refresh token
    """
    # Верифицируем refresh token
    token_payload = verify_token(token_data.refresh_token)
    
    if not token_payload or token_payload.type != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Недействительный refresh token"
        )
    
    # Ищем пользователя
    result = await db.execute(select(User).where(User.email == token_payload.sub))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден"
        )
    
    # Создаем новую пару токенов
    tokens = create_tokens_for_user(user)
    
    return Token(
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        token_type=tokens["token_type"],
        user=UserResponse.from_orm(user)
    )


@router.post("/logout")
async def logout():
    """
    Выход пользователя
    - На клиенте нужно удалить токены
    - На сервере можно добавить blacklist токенов в будущем
    """
    return {"message": "Успешный выход из системы"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: User = Depends(get_current_active_user)
):
    """
    Получение информации о текущем пользователе
    """
    return UserResponse.from_orm(current_user)


@router.put("/me", response_model=UserResponse)
async def update_current_user(
    user_data: UserUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Обновление данных текущего пользователя
    """
    # Обновляем только переданные поля
    if user_data.name is not None:
        current_user.name = user_data.name
    if user_data.birth_date is not None:
        current_user.birth_date = user_data.birth_date
    if user_data.birth_time is not None:
        current_user.birth_time = user_data.birth_time
    if user_data.birth_place is not None:
        current_user.birth_place = user_data.birth_place
    
    current_user.updated_at = datetime.utcnow()
    
    await db.commit()
    await db.refresh(current_user)
    
    return UserResponse.from_orm(current_user)