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
    summary: Optional[str] = None
    book_analyses: List[BookAnalysisResult]
    chart_summary: Dict[str, Any]
    language: str
    created_at: datetime


class SummaryRequest(BaseModel):
    """Запрос на генерацию краткого резюме"""
    text: str
    language: str = "en"


class SummaryResponse(BaseModel):
    """Ответ с кратким резюме"""
    summary: str

class ChatMessage(BaseModel):
    """Одно сообщение в истории чата"""
    role: str  # "user" или "assistant"
    content: str


class ChatRequest(BaseModel):
    """Запрос к астрологу-агенту"""
    question: str
    chart_data: Dict[str, Any]
    summary: str
    chat_history: List[ChatMessage] = []
    language: str = "ru"


class ChatResponse(BaseModel):
    """Ответ астролога-агента"""
    answer: str
    relevant_chunks: List[Dict[str, Any]] = []
class ChartRequest(BaseModel):
    """Запрос на данные одной карты (для синастрии)"""
    birth_date: datetime
    birth_time: Optional[str] = None
    birth_place: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    house_system: Optional[str] = "Placidus"


class SynastryAnalysisRequest(BaseModel):
    """Запрос на полный анализ синастрии"""
    chart1: ChartRequest
    chart2: ChartRequest
    language: Optional[str] = None
    top_k_per_book: int = 3


class SynastryAnalysisResponse(BaseModel):
    """Ответ с анализом синастрии"""
    chart1_summary: Dict[str, Any]
    chart2_summary: Dict[str, Any]
    aspects: List[Dict[str, Any]]
    overlays: Optional[Dict[str, Any]] = None
    analysis: str
    summary: Optional[str] = None
    relevant_chunks: List[Dict[str, Any]] = []
    language: str
    created_at: datetime


class SynastryChatRequest(BaseModel):
    """Запрос к астрологу-агенту по синастрии"""
    question: str
    chart1_data: Dict[str, Any]
    chart2_data: Dict[str, Any]
    synastry_aspects: List[Dict[str, Any]]
    full_analysis: Optional[str] = None
    chat_history: List[ChatMessage] = []
    language: Optional[str] = None


class SynastryChatResponse(BaseModel):
    """Ответ астролога-агента по синастрии"""
    answer: str
    relevant_chunks: List[Dict[str, Any]] = []


class SynastryAspectRequest(BaseModel):
    """Запрос на анализ аспекта синастрии"""
    planet1: str
    planet2: str
    aspect_name: str
    aspect_name_ru: Optional[str] = None
    orb: float = 0.0
    language: str = "en"


class SynastryAspectResponse(BaseModel):
    """Ответ с анализом аспекта синастрии"""
    planet1: str
    planet2: str
    aspect: str
    aspect_ru: Optional[str] = None
    orb: float
    analysis: str
    relevant_chunks: List[Dict[str, Any]] = []
