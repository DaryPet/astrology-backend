from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


class PlanetAnalysisRequest(BaseModel):
    """Запрос на анализ одной планеты"""
    planet: str
    sign: str
    degree: float = Field(..., ge=0, le=30)
    house: Optional[int] = Field(None, ge=1, le=12)
    house_sign: Optional[str] = None
    is_retrograde: Optional[bool] = False
    aspects: Optional[List[Dict[str, Any]]] = None
    language: str
    chart_data: Optional[Dict[str, Any]] = None


class PlanetAspectInfo(BaseModel):
    """Информация об аспекте планеты"""
    aspect: str
    planet: str
    orb: float


class PlanetAnalysisResponse(BaseModel):
    """Ответ с анализом планеты"""
    planet: str
    sign: str
    house: int
    is_retrograde: bool = False
    analysis: str
    relevant_chunks: List[Dict[str, Any]] = []


class FullAnalysisRequest(BaseModel):
    """Запрос на полный анализ натальной карты"""
    chart_data: Optional[Dict[str, Any]] = None
    
    birth_date: Optional[datetime] = None
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    house_system: Optional[str] = "Placidus"
    
    language: str = "ru"
    top_books: int = 5


class BookAnalysisResult(BaseModel):
    """Результат анализа одной книги"""
    book_id: int
    title: str
    analysis: str


class FullAnalysisResponse(BaseModel):
    """Ответ с полным анализом натальной карты"""
    analysis: str
    book_analyses: List[BookAnalysisResult]
    chart_summary: Dict[str, Any]
    language: str
    created_at: datetime