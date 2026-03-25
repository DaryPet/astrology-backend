"""
Модели для аутентификации - НЕ трогает существующий код
Создает отдельную таблицу для пользователей аутентификации
"""
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime

# Создаем отдельную базу для аутентификации
AuthBase = declarative_base()


class AuthUser(AuthBase):
    """Модель пользователя для аутентификации"""
    __tablename__ = "auth_users"
    
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password = Column(String, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)