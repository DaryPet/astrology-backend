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
    mode: Optional[str] = 'advanced'
    stream: bool = False


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
    mode: Optional[str] = 'advanced'
    
    language: str = "ru"
    top_books: int = 5
    stream: bool = False


class BookAnalysisResult(BaseModel):
    """Результат анализа одной книги"""
    book_id: int
    title: str
    analysis: str


class FullAnalysisResponse(BaseModel):
    """Ответ с полным анализом натальной карты"""
    analysis: str
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
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    """Запрос к астрологу-агенту"""
    question: str
    chart_data: Dict[str, Any]
    summary: str
    chat_history: List[ChatMessage] = []
    language: str = "ru"
    relationship_context: Optional[str] = None  # "default", "relatives", "partner", "colleagues", "friends"
    stream: bool = False


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
    aspects: Optional[List[Dict[str, Any]]] = None
    overlays: Optional[Dict[str, Any]] = None
    language: Optional[str] = None
    top_k_per_book: int = 3
    mode: str = 'advanced'
    relationship_context: Optional[str] = None  # "default", "relatives", "partner", "colleagues", "friends"
    stream: bool = False


class SynastryAnalysisResponse(BaseModel):
    """Ответ с анализом синастрии"""
    chart1_summary: Dict[str, Any]
    chart2_summary: Dict[str, Any]
    aspects: List[Dict[str, Any]]
    overlays: Optional[Dict[str, Any]] = None
    analysis: str
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
    relationship_context: Optional[str] = None  # "default", "relatives", "partner", "colleagues", "friends"


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
    aspect_name_uk: Optional[str] = None
    orb: float = 0.0
    language: str = "en"
    mode: Optional[str] = 'advanced'
    stream: bool = False


class SynastryAspectResponse(BaseModel):
    """Ответ с анализом аспекта синастрии"""
    planet1: str
    planet2: str
    aspect: str
    aspect_ru: Optional[str] = None
    aspect_uk: Optional[str] = None
    orb: float
    analysis: str
    relevant_chunks: List[Dict[str, Any]] = []


class RelationshipTypeInfo(BaseModel):
    """Информация о типе отношений"""
    percentage: int
    label: str
    description: Optional[str] = None


class SynastryRelationshipRequest(BaseModel):
    """Запрос на определение типов отношений в синастрии"""
    # New format (preferred)
    full_analysis: Optional[str] = None
    # Old format (for backward compatibility)
    # chart1: Optional[Dict[str, Any]] = None
    # chart2: Optional[Dict[str, Any]] = None
    # aspects: Optional[List[Dict[str, Any]]] = None
    # overlays: Optional[Dict[str, Any]] = None
    
    language: str = "ru"
    stream: bool = False


class SynastryRelationshipResponse(BaseModel):
    """Ответ с типами отношений"""
    relationship_types: Dict[str, RelationshipTypeInfo]
    dominant_type: str
    analysis: str


# ============================================================
# SECONDARY PROGRESSIONS
# ============================================================

class ProgressionsRequest(BaseModel):
    """Запрос на расчёт вторичных прогрессий"""
    birth_date: datetime
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    house_system: Optional[str] = "Placidus"
    # Date to build progressions for (default — current moment)
    target_date: Optional[datetime] = None


class ProgressionsAnalysisRequest(BaseModel):
    """Запрос на AI-анализ вторичных прогрессий"""
    # Preferred path: the frontend sends ready-made data (no recalculation)
    natal_chart: Optional[Dict[str, Any]] = None       # natal chart chart_data
    progression_data: Optional[Dict[str, Any]] = None  # result of /api/progressions

    # Fallback: calculate on the backend from birth data
    birth_date: Optional[datetime] = None
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    house_system: Optional[str] = "Placidus"
    target_date: Optional[datetime] = None

    language: str = "ru"
    mode: Optional[str] = "advanced"
    top_k_per_book: int = 2
    stream: bool = False


class ProgressionsAnalysisResponse(BaseModel):
    """Ответ с анализом прогрессий"""
    analysis: str
    progressions_summary: Dict[str, Any]
    language: str
    created_at: datetime


class TransitsRequest(BaseModel):
    """Запрос на расчёт транзитов на конкретный день"""
    birth_date: datetime
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    house_system: Optional[str] = "Placidus"
    # Transit date (default — today); can be any past/future day
    target_date: Optional[datetime] = None
    # Ready-made natal chart from the DB (planets+houses) — so transit planet
    # houses are computed against the CORRECT natal cusps, not recalculated ones
    natal_chart: Optional[Dict[str, Any]] = None
    # Place to calculate transits for (defaults to the natal place's coordinates)
    transit_place: Optional[str] = None
    transit_latitude: Optional[float] = None
    transit_longitude: Optional[float] = None


class TransitsAnalysisRequest(BaseModel):
    """Запрос на AI-анализ транзитов дня"""
    # Preferred path: the frontend sends ready-made data (no recalculation)
    natal_chart: Optional[Dict[str, Any]] = None    # natal chart chart_data
    transit_data: Optional[Dict[str, Any]] = None   # result of /api/transits

    # Fallback: calculate on the backend from birth data
    birth_date: Optional[datetime] = None
    birth_time: Optional[str] = None
    birth_place: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: Optional[str] = None
    house_system: Optional[str] = "Placidus"
    target_date: Optional[datetime] = None

    language: str = "ru"
    mode: str = "advanced"  # simple | advanced
    top_k_per_book: int = 2
    stream: bool = False

    # Place to calculate transits for
    transit_place: Optional[str] = None
    transit_latitude: Optional[float] = None
    transit_longitude: Optional[float] = None


class DailyForecastRequest(TransitsAnalysisRequest):
    """Прогноз дня: те же входные данные, что у анализа транзитов,
    плюс выбор LLM с фронтенда."""
    llm_provider: Optional[str] = None  # claude | deepseek | gemini | openrouter; None = settings.LLM_PROVIDER
    llm_model: Optional[str] = None     # model slug for openrouter
    transit_timezone: Optional[str] = None  # IANA timezone of the transit place: time is treated as LOCAL
    # Метод карты события (Frawley, Sports Astrology гл. 2): ход Луны зависит от спорта.
    # Футбол 80+ мин = 5°, короткие форматы = 4°, однодневный крикет = 13°.
    moon_range_degrees: float = Field(default=5.0, gt=0, le=30, allow_inf_nan=False)
    extra_time_possible: bool = False   # +1° к ходу Луны, если возможно доп. время


class TransitsAnalysisResponse(BaseModel):
    analysis: str
    transits_summary: Optional[Dict[str, Any]] = None
    transit_data: Optional[Dict[str, Any]] = None


class ProgressedSynastryRequest(BaseModel):
    """Запрос расчёта прогрессивной синастрии (два партнёра)"""
    chart1: ChartRequest
    chart2: ChartRequest
    target_date: Optional[datetime] = None  # default — today; can be any day
    house_system: Optional[str] = "Placidus"


class ProgressedSynastryAnalysisRequest(BaseModel):
    """Запрос AI-анализа прогрессивной синастрии"""
    # Preferred path: the frontend sends ready-made calculation data
    progressed_synastry_data: Optional[Dict[str, Any]] = None
    # Partners' natal charts (for layers 2 and 3) — chart_data from the DB
    natal_chart1: Optional[Dict[str, Any]] = None
    natal_chart2: Optional[Dict[str, Any]] = None

    # Fallback: recalculate on the backend
    chart1: Optional[ChartRequest] = None
    chart2: Optional[ChartRequest] = None
    target_date: Optional[datetime] = None
    house_system: Optional[str] = "Placidus"

    language: str = "ru"
    mode: str = "advanced"  # simple | advanced
    top_k_per_book: int = 2
    relationship_context: Optional[str] = None
    stream: bool = False


class ProgressedSynastryAnalysisResponse(BaseModel):
    analysis: str
    progressed_synastry_summary: Optional[Dict[str, Any]] = None
    progressed_synastry_data: Optional[Dict[str, Any]] = None


class ProgressedSynastryAspectRequest(BaseModel):
    """Запрос на анализ одного аспекта прогрессивной синастрии (клик на аспект)"""
    planet1: str
    planet2: str
    aspect_name: str
    aspect_name_ru: Optional[str] = None
    aspect_name_uk: Optional[str] = None
    orb: float = 0.0
    # Which of the five /progressed-synastry response blocks the aspect was
    # taken from — determines how exactly to interpret it (see progressed_synastry_aspect_click_plan.md)
    layer: str  # "progressed" | "prog1_to_natal2" | "prog2_to_natal1" | "new" | "faded"
    applying: Optional[bool] = None
    planet1_house: Optional[int] = None
    planet2_house: Optional[int] = None
    person1_name: Optional[str] = None
    person2_name: Optional[str] = None
    language: str = "ru"
    mode: Optional[str] = 'advanced'
    stream: bool = False


class ProgressedSynastryAspectResponse(BaseModel):
    """Ответ с анализом одного аспекта прогрессивной синастрии"""
    planet1: str
    planet2: str
    aspect: str
    aspect_ru: Optional[str] = None
    aspect_uk: Optional[str] = None
    orb: float
    layer: str
    analysis: str
    relevant_chunks: List[Dict[str, Any]] = []
