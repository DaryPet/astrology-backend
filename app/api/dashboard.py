"""
Роутер для защищенных маршрутов (dashboard)
- Требует аутентификации
- Пока пустой, для будущего расширения
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.models import User
from app.auth import get_current_active_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/")
async def get_dashboard(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Главная страница dashboard
    - Требует аутентификации
    - Пока возвращает базовую информацию
    - Место для будущего расширения
    """
    return {
        "message": "Добро пожаловать в ваш астрологический кабинет!",
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "has_astrology_data": current_user.birth_date is not None
        },
        "features": [
            {
                "name": "Сохраненные карты",
                "description": "Просмотр и управление вашими натальными картами",
                "available": False,
                "coming_soon": True
            },
            {
                "name": "Персональные прогнозы",
                "description": "Ежедневные астрологические прогнозы",
                "available": False,
                "coming_soon": True
            },
            {
                "name": "Синастрия",
                "description": "Совместимость с другими людьми",
                "available": False,
                "coming_soon": True
            }
        ],
        "stats": {
            "charts_saved": 0,
            "interpretations_generated": 0,
            "compatibility_checks": 0
        }
    }


@router.get("/profile")
async def get_dashboard_profile(
    current_user: User = Depends(get_current_active_user)
):
    """
    Профиль пользователя в dashboard
    """
    return {
        "user": {
            "id": current_user.id,
            "email": current_user.email,
            "name": current_user.name,
            "registration_date": current_user.created_at.isoformat(),
            "last_updated": current_user.updated_at.isoformat(),
            "astrology_data": {
                "has_birth_date": current_user.birth_date is not None,
                "has_birth_time": current_user.birth_time is not None,
                "has_birth_place": current_user.birth_place is not None
            }
        }
    }


@router.get("/settings")
async def get_dashboard_settings(
    current_user: User = Depends(get_current_active_user)
):
    """
    Настройки пользователя (заглушка)
    """
    return {
        "message": "Настройки будут доступны в будущих обновлениях",
        "available_settings": [],
        "coming_soon": True
    }