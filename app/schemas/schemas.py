from pydantic import BaseModel, EmailStr, Field, validator
from datetime import datetime
from typing import Optional, Dict, List, Any
import re

# ============================================================================
# АУТЕНТИФИКАЦИЯ
# ============================================================================

class UserRegister(BaseModel):
    """Схема для регистрации пользователя"""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=72)  # Bcrypt ограничение 72 байта
    name: Optional[str] = Field(None, max_length=100)
    
    @validator('password')
    def validate_password(cls, v):
        """Валидация пароля: минимум 8 символов, буквы и цифры"""
        if len(v) < 8:
            raise ValueError('Пароль должен содержать минимум 8 символов')
        if len(v) > 72:
            raise ValueError('Пароль не должен превышать 72 символа')
        if not re.search(r'[A-Za-z]', v):
            raise ValueError('Пароль должен содержать буквы')
        if not re.search(r'\d', v):
            raise ValueError('Пароль должен содержать цифры')
        return v

class UserLogin(BaseModel):
    """Схема для входа пользователя"""
    email: EmailStr
    password: str

class UserUpdate(BaseModel):
    """Схема для обновления данных пользователя"""
    name: Optional[str] = Field(None, max_length=100)
    birth_date: Optional[datetime] = None
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None

class UserResponse(BaseModel):
    """Схема для ответа с данными пользователя"""
    id: int
    email: str
    name: Optional[str] = None
    birth_date: Optional[datetime] = None
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True

class Token(BaseModel):
    """Схема для JWT токенов"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserResponse

class TokenPayload(BaseModel):
    """Схема для payload JWT токена"""
    sub: str  # email пользователя
    exp: int  # expiration timestamp
    type: str  # token type: "access" or "refresh"

class RefreshTokenRequest(BaseModel):
    """Схема для запроса обновления токена"""
    refresh_token: str

# ============================================================================
# АСТРОЛОГИЧЕСКИЕ СХЕМЫ (оставляем как есть)
# ============================================================================

class PlanetPosition(BaseModel):
    planet: str
    sign: str
    degree: float
    house: Optional[int] = None

class NatalChartCreate(BaseModel):
    user_id: int

class NatalChartResponse(BaseModel):
    id: int
    user_id: int
    sun_sign: Optional[str] = None
    moon_sign: Optional[str] = None
    ascendant: Optional[str] = None
    planets: Optional[str] = None
    houses: Optional[str] = None
    aspects: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True

class InterpretationCreate(BaseModel):
    chart_id: int
    type: str  # "natal", "solar_return", "transit", "synastry"

class InterpretationResponse(BaseModel):
    id: int
    chart_id: int
    type: str
    interpretation: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class BookCreate(BaseModel):
    title: str
    content: str

class BookResponse(BookCreate):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

class QueryRequest(BaseModel):
    query: str

class SynastryRequest(BaseModel):
    chart1_id: int
    chart2_id: int

# Natal Chart Calculation Request (without DB)
class NatalChartRequest(BaseModel):
    """Request for direct natal chart calculation"""
    birth_date: datetime
    birth_time: Optional[str] = None
    birth_place: str
    latitude: Optional[float] = None  # Optional - backend can determine from birth_place
    longitude: Optional[float] = None  # Optional - backend can determine from birth_place
    timezone: Optional[str] = None  # IANA timezone (e.g., "Europe/Moscow")
    house_system: Optional[str] = "Placidus"

class NatalChartResponseFull(BaseModel):
    """Full natal chart response"""
    sun_sign: str
    sun_sign_ru: str
    moon_sign: str
    moon_sign_ru: str
    ascendant: str
    ascendant_ru: str
    ascendant_degree: float
    mc: str
    mc_ru: str
    mc_degree: float
    planets: Dict[str, Any]
    houses: Dict[str, Any]
    houses_meta: Dict[str, Any]
    meta: Dict[str, Any]
    aspects: List[Dict[str, Any]]

class TransitRequest(BaseModel):
    """Request for transit calculation"""
    birth_date: datetime
    birth_time: Optional[str] = None
    birth_place: str
    latitude: Optional[float] = None  # Optional - backend can determine from birth_place
    longitude: Optional[float] = None  # Optional - backend can determine from birth_place
    timezone: Optional[str] = None
    transit_date: datetime

class SynastryRequestDirect(BaseModel):
    """Direct synastry calculation request"""
    chart1: NatalChartRequest
    chart2: NatalChartRequest
