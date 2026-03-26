"""
Роутер аутентификации через Supabase
Заменяет локальную систему аутентификации
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request
from pydantic import BaseModel
from typing import Optional

from app.supabase_auth import (
    UserRegister, UserLogin, Token, UserResponse, SupabaseUser,
    supabase_register, supabase_login, supabase_logout,
    supabase_get_current_user, supabase_resend_confirmation,
    supabase_reset_password, supabase_google_login,
    supabase_handle_oauth_callback, get_current_active_user
)

router = APIRouter(tags=["supabase-auth"])


@router.post("/api/supabase/register", response_model=dict)
async def register(user_data: UserRegister):
    """
    Регистрация через Supabase
    Supabase автоматически отправляет email для подтверждения
    """
    try:
        result = await supabase_register(
            email=user_data.email,
            password=user_data.password,
            name=user_data.name
        )
        
        # Возвращаем сообщение о необходимости подтверждения email
        return {
            "message": "Регистрация успешна! Проверьте ваш email для подтверждения.",
            "user_id": result["user"].id if result.get("user") else None,
            "email_sent": True
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка регистрации: {str(e)}"
        )


@router.post("/api/supabase/login", response_model=dict)
async def login(user_data: UserLogin):
    """
    Вход через Supabase
    Требует подтвержденного email
    """
    try:
        result = await supabase_login(
            email=user_data.email,
            password=user_data.password
        )
        
        return {
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": result["token_type"],
            "expires_in": result["expires_in"],
            "expires_at": result["expires_at"],
            "user": {
                "id": result["user"].id,
                "email": result["user"].email,
                "name": result["user"].user_metadata.get("name") if result["user"].user_metadata else None,
                "email_confirmed_at": result["user"].email_confirmed_at.isoformat() if result["user"].email_confirmed_at else None
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка входа: {str(e)}"
        )


@router.post("/api/supabase/logout")
async def logout(request: Request):
    """
    Выход из Supabase
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется токен для выхода"
        )
    
    access_token = auth_header.split(" ")[1]
    
    try:
        result = await supabase_logout(access_token)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка выхода: {str(e)}"
        )


@router.get("/api/supabase/me", response_model=dict)
async def get_me(current_user: SupabaseUser = Depends(get_current_active_user)):
    """
    Получение информации о текущем пользователе
    """
    return {
        "id": current_user.id,
        "email": current_user.email,
        "name": current_user.user_metadata.get("name") if current_user.user_metadata else None,
        "email_confirmed_at": current_user.email_confirmed_at.isoformat() if current_user.email_confirmed_at else None,
        "created_at": current_user.created_at.isoformat(),
        "updated_at": current_user.updated_at.isoformat()
    }


@router.post("/api/supabase/resend-confirmation")
async def resend_confirmation(email: str):
    """
    Повторная отправка email для подтверждения
    """
    try:
        result = await supabase_resend_confirmation(email)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка отправки email: {str(e)}"
        )


@router.post("/api/supabase/reset-password")
async def reset_password(email: str):
    """
    Сброс пароля
    """
    try:
        result = await supabase_reset_password(email)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка сброса пароля: {str(e)}"
        )


# Google OAuth эндпоинты
@router.get("/api/supabase/google/login")
async def google_login(redirect_to: str = "http://localhost:12001/auth/callback"):
    """
    Получение URL для входа через Google
    """
    try:
        result = await supabase_google_login(redirect_to)
        return result
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка Google OAuth: {str(e)}"
        )


@router.post("/api/supabase/oauth/callback")
async def oauth_callback(code: str):
    """
    Обработка callback от OAuth провайдера
    """
    try:
        result = await supabase_handle_oauth_callback(code)
        
        return {
            "access_token": result["access_token"],
            "refresh_token": result["refresh_token"],
            "token_type": result["token_type"],
            "expires_in": result["expires_in"],
            "expires_at": result["expires_at"],
            "user": {
                "id": result["user"].id,
                "email": result["user"].email,
                "name": result["user"].user_metadata.get("name") if result["user"].user_metadata else None,
                "email_confirmed_at": result["user"].email_confirmed_at.isoformat() if result["user"].email_confirmed_at else None
            }
        }
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка OAuth callback: {str(e)}"
        )


@router.get("/api/supabase/dashboard")
async def dashboard(current_user: SupabaseUser = Depends(get_current_active_user)):
    """
    Dashboard - требует аутентификации и подтвержденного email
    """
    return {
        "message": "Добро пожаловать в dashboard!",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.user_metadata.get("name") if current_user.user_metadata else None,
            "email_confirmed": bool(current_user.email_confirmed_at)
        },
        "data": {
            "welcome_message": "Вы успешно вошли в систему с использованием Supabase Auth",
            "features": [
                "Безопасная аутентификация",
                "Подтверждение email",
                "Вход через Google",
                "Сброс пароля",
                "Управление сессиями"
            ]
        }
    }


# Эндпоинт для проверки здоровья Supabase
@router.get("/api/supabase/health")
async def health_check():
    """
    Проверка подключения к Supabase
    """
    try:
        # Простая проверка подключения
        from app.supabase_auth import supabase
        # Пытаемся получить информацию о текущем проекте
        # (это безопасный запрос, не требующий аутентификации)
        response = supabase.table("").select("*").limit(1).execute()
        
        return {
            "status": "healthy",
            "supabase_connected": True,
            "message": "Supabase подключен успешно"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "supabase_connected": False,
            "message": f"Ошибка подключения к Supabase: {str(e)}"
        }


# Эндпоинт для обновления токена
@router.post("/api/supabase/refresh-token")
async def refresh_token(refresh_token: str):
    """
    Обновление access token с помощью refresh token
    """
    try:
        from app.supabase_auth import supabase
        response = supabase.auth.refresh_session(refresh_token)
        
        return {
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "token_type": "bearer",
            "expires_in": response.session.expires_in,
            "expires_at": response.session.expires_at
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Ошибка обновления токена: {str(e)}"
        )