"""
Модуль аутентификации с современными практиками
- JWT access + refresh tokens
- Bcrypt хеширование паролей
- Зависимости от конфигурации
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.db.database import get_db
from app.models.models import User
from app.schemas.schemas import TokenPayload

# Security schemes
security = HTTPBearer(auto_error=False)

# Password hashing context - используем pbkdf2_sha256 как fallback
pwd_context = CryptContext(
    schemes=["pbkdf2_sha256", "bcrypt"],
    deprecated="auto",
    pbkdf2_sha256__default_rounds=30000
)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Проверка пароля"""
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """Хеширование пароля"""
    return pwd_context.hash(password)


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    """Создание access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "type": "access",
        "iat": datetime.utcnow()
    })
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_refresh_token(data: Dict[str, Any]) -> str:
    """Создание refresh token"""
    to_encode = data.copy()
    
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    
    to_encode.update({
        "exp": expire,
        "type": "refresh",
        "iat": datetime.utcnow()
    })
    
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> Optional[TokenPayload]:
    """Верификация JWT токена"""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        
        # Проверяем обязательные поля
        email: str = payload.get("sub")
        exp: int = payload.get("exp")
        token_type: str = payload.get("type")
        
        if email is None or exp is None or token_type is None:
            return None
            
        # Проверяем тип токена
        if token_type not in ["access", "refresh"]:
            return None
            
        return TokenPayload(sub=email, exp=exp, type=token_type)
        
    except JWTError:
        return None


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: AsyncSession = Depends(get_db)
) -> Optional[User]:
    """Получение текущего пользователя из access token"""
    if credentials is None:
        return None
    
    token = credentials.credentials
    token_data = verify_token(token)
    
    if token_data is None or token_data.type != "access":
        return None
    
    # Ищем пользователя в базе данных
    result = await db.execute(select(User).where(User.email == token_data.sub))
    user = result.scalar_one_or_none()
    
    return user


async def get_current_active_user(
    current_user: Optional[User] = Depends(get_current_user)
) -> User:
    """Получение активного пользователя (требует аутентификации)"""
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима аутентификация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user


async def get_current_user_optional(
    current_user: Optional[User] = Depends(get_current_user)
) -> Optional[User]:
    """Опциональное получение пользователя (для публичных маршрутов)"""
    return current_user


def create_tokens_for_user(user: User) -> Dict[str, str]:
    """Создание пары токенов для пользователя"""
    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})
    
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer"
    }


async def authenticate_user(db: AsyncSession, email: str, password: str) -> Optional[User]:
    """Аутентификация пользователя по email и паролю"""
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    
    if not user:
        return None
    if not verify_password(password, user.password):
        return None
    
    return user