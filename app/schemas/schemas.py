from pydantic import BaseModel
from datetime import datetime
from typing import Optional, Dict, List, Any

class UserCreate(BaseModel):
    name: str
    birth_date: datetime
    birth_time: Optional[str] = None
    birth_place: str

class UserResponse(UserCreate):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True

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
    language: Optional[str] = None
    format: Optional[str] = None


class BookResponse(BookCreate):
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class BookChunkCreate(BaseModel):
    book_id: int
    chunk_index: Optional[int] = None
    text: str
    page_number: Optional[int] = None
    word_count: Optional[int] = None


class BookChunkResponse(BookChunkCreate):
    id: int
    
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
    sun_sign_uk: Optional[str] = None
    moon_sign: str
    moon_sign_ru: str
    moon_sign_uk: Optional[str] = None
    ascendant: str
    ascendant_ru: str
    ascendant_uk: Optional[str] = None
    ascendant_degree: float
    mc: str
    mc_ru: str
    mc_uk: Optional[str] = None
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


class AnalysisRequest(BaseModel):
    """Запрос на поиск и анализ астрологического запроса"""
    query: str
    chart_data: Optional[NatalChartRequest] = None
    top_k: int = 5


class ParsedQuery(BaseModel):
    """Результат парсинга астрологического запроса"""
    language: str = "en"
    planets: List[str] = []
    houses: List[int] = []
    signs: List[str] = []
    aspects: List[str] = []


class RelevantChunk(BaseModel):
    """Найденный чанк из книги"""
    id: int
    book_id: int
    text: str
    chunk_index: Optional[int] = None
    word_count: Optional[int] = None
    similarity_score: float = 0.0


class AnalysisResponse(BaseModel):
    """Ответ с результатами анализа"""
    query: str
    query_language: str
    parsed_query: ParsedQuery
    chart_data: Optional[Dict[str, Any]] = None
    relevant_chunks: List[Dict[str, Any]] = []
    analysis: str
