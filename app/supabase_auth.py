"""
Supabase аутентификация - замена локальной системы
Использует Supabase Auth для регистрации, входа и управления пользователями
"""
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr, validator
import re
import os

from supabase import create_client, Client

# Конфигурация Supabase
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://wsqknvxhdcernpgdeyte.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET", "")

# Инициализация Supabase клиента
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Security scheme
security = HTTPBearer(auto_error=False)


# Схемы Pydantic
class UserRegister(BaseModel):
    """Схема для регистрации через Supabase"""
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
    """Схема для входа через Supabase"""
    email: EmailStr
    password: str


class Token(BaseModel):
    """Схема токена от Supabase"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    expires_at: Optional[int] = None


class UserResponse(BaseModel):
    """Схема ответа пользователя"""
    id: str
    email: str
    name: Optional[str]
    email_confirmed_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class SupabaseUser(BaseModel):
    """Модель пользователя из Supabase"""
    id: str
    email: str
    user_metadata: Optional[Dict[str, Any]] = None
    email_confirmed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


async def supabase_register(email: str, password: str, name: Optional[str] = None) -> Dict[str, Any]:
    """
    Регистрация пользователя через Supabase
    Supabase автоматически отправляет email для подтверждения
    """
    try:
        # Регистрация в Supabase
        response = supabase.auth.sign_up({
            "email": email,
            "password": password,
            "options": {
                "data": {
                    "name": name,
                    "email_confirmed": False
                }
            }
        })
        
        # Supabase автоматически отправляет email для подтверждения
        # Пользователь не сможет войти пока не подтвердит email
        
        return {
            "user": response.user,
            "session": response.session,
            "message": "Регистрация успешна. Проверьте ваш email для подтверждения."
        }
    except Exception as e:
        error_msg = str(e)
        if "User already registered" in error_msg or "already exists" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким email уже существует"
            )
        elif "Password should be at least" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пароль должен содержать минимум 8 символов"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка регистрации: {error_msg}"
            )


async def supabase_login(email: str, password: str) -> Dict[str, Any]:
    """
    Вход пользователя через Supabase
    """
    try:
        # Вход в Supabase
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        # Проверяем подтвержден ли email
        user = response.user
        if not user.email_confirmed_at:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email не подтвержден. Проверьте вашу почту."
            )
        
        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer",
            "expires_in": response.session.expires_in,
            "expires_at": response.session.expires_at,
            "user": user
        }
    except Exception as e:
        error_msg = str(e)
        if "Invalid login credentials" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный email или пароль"
            )
        elif "Email not confirmed" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Email не подтвержден. Проверьте вашу почту."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка входа: {error_msg}"
            )


async def supabase_logout(access_token: str) -> Dict[str, Any]:
    """
    Выход пользователя из Supabase
    """
    try:
        # Устанавливаем токен для текущей сессии
        supabase.auth.set_session(access_token, "")
        
        # Выход
        supabase.auth.sign_out()
        
        return {"message": "Успешный выход из системы"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка выхода: {str(e)}"
        )


async def supabase_get_current_user(access_token: str) -> Optional[SupabaseUser]:
    """
    Получение текущего пользователя из Supabase по токену
    """
    try:
        # Получаем пользователя по токену
        response = supabase.auth.get_user(access_token)
        
        if not response.user:
            return None
        
        user = response.user
        return SupabaseUser(
            id=user.id,
            email=user.email,
            user_metadata=user.user_metadata,
            email_confirmed_at=user.email_confirmed_at,
            created_at=user.created_at,
            updated_at=user.updated_at
        )
    except Exception:
        return None


async def supabase_resend_confirmation(email: str) -> Dict[str, Any]:
    """
    Повторная отправка email для подтверждения
    """
    try:
        response = supabase.auth.resend({
            "type": "signup",
            "email": email
        })
        
        return {"message": "Email для подтверждения отправлен повторно"}
    except Exception as e:
        error_msg = str(e)
        if "already confirmed" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email уже подтвержден"
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Ошибка отправки email: {error_msg}"
            )


async def supabase_reset_password(email: str) -> Dict[str, Any]:
    """
    Сброс пароля через Supabase
    """
    try:
        response = supabase.auth.reset_password_email(email)
        return {"message": "Инструкции по сбросу пароля отправлены на email"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка сброса пароля: {str(e)}"
        )


async def get_current_user_from_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[SupabaseUser]:
    """
    Получение текущего пользователя из токена (для зависимостей FastAPI)
    """
    if not credentials:
        return None
    
    try:
        user = await supabase_get_current_user(credentials.credentials)
        return user
    except Exception:
        return None


async def get_current_active_user(
    current_user: Optional[SupabaseUser] = Depends(get_current_user_from_token)
) -> SupabaseUser:
    """
    Получение активного пользователя (требует аутентификации)
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Необходима аутентификация"
        )
    
    # Проверяем подтвержден ли email
    if not current_user.email_confirmed_at:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email не подтвержден. Проверьте вашу почту."
        )
    
    return current_user


# Функции для работы с Google OAuth
async def supabase_google_login(redirect_to: str = "http://localhost:12001/auth/callback") -> Dict[str, Any]:
    """
    Получение URL для входа через Google OAuth
    """
    try:
        response = supabase.auth.sign_in_with_oauth({
            "provider": "google",
            "options": {
                "redirect_to": redirect_to
            }
        })
        
        return {"url": response.url}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка Google OAuth: {str(e)}"
        )


async def supabase_handle_oauth_callback(code: str) -> Dict[str, Any]:
    """
    Обработка callback от OAuth провайдера
    """
    try:
        response = supabase.auth.exchange_code_for_session(code)
        
        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer",
            "expires_in": response.session.expires_in,
            "expires_at": response.session.expires_at,
            "user": response.user
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка OAuth callback: {str(e)}"
        )