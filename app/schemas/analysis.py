from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class PlanetAnalysisRequest(BaseModel):
    """Запрос на анализ одной планеты"""
    planet: str
    sign: str
    degree: float = Field(..., ge=0, le=30)
    house: Optional[int] = Field(None, ge=1, le=12)
    house_sign: Optional[str] = None
    is_retrograde: Optional[bool] = False  # Важно для анализа - ретроградная или директная планета
    aspects: Optional[List[Dict[str, Any]]] = None
    language: str  # Код языка: ru, en, zh, es, fr, de, it, pt и т.д.
    chart_data: Optional[Dict[str, Any]] = None  # Данные натальной карты для извлечения is_retrograde


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