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
    relationship_context: Optional[str] = None  # "default", "relatives", "partner", "colleagues", "friends"


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
    # Новый формат (предпочтительный)
    full_analysis: Optional[str] = None
    # Старый формат (для обратной совместимости)
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
# SECONDARY PROGRESSIONS (Вторичные прогрессии)
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
    # Дата, на которую строим прогрессии (по умолчанию — текущий момент)
    target_date: Optional[datetime] = None


class ProgressionsAnalysisRequest(BaseModel):
    """Запрос на AI-анализ вторичных прогрессий"""
    # Предпочтительный путь: фронтенд передаёт готовые данные (без повторного расчёта)
    natal_chart: Optional[Dict[str, Any]] = None       # chart_data натальной карты
    progression_data: Optional[Dict[str, Any]] = None  # результат /api/progressions

    # Fallback: расчёт на бэкенде из данных рождения
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


class ProgressionsAnalysisResponse(BaseModel):
    """Ответ с анализом прогрессий"""
    analysis: str
    summary: Optional[str] = None
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
    # День транзита (по умолчанию — сегодня); можно любой день прошлого/будущего
    target_date: Optional[datetime] = None
    # Готовая натальная карта из БД (planets+houses) — чтобы дома транзитных
    # планет считались по ВЕРНЫМ натальным куспидам, а не по пересчитанным
    natal_chart: Optional[Dict[str, Any]] = None
    # Место для расчёта транзитов (по умолчанию используются координаты натального места)
    transit_place: Optional[str] = None
    transit_latitude: Optional[float] = None
    transit_longitude: Optional[float] = None


class TransitsAnalysisRequest(BaseModel):
    """Запрос на AI-анализ транзитов дня"""
    # Предпочтительный путь: фронтенд передаёт готовые данные (без повторного расчёта)
    natal_chart: Optional[Dict[str, Any]] = None    # chart_data натальной карты
    transit_data: Optional[Dict[str, Any]] = None   # результат /api/transits

    # Fallback: расчёт на бэкенде из данных рождения
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

    # Место для расчёта транзитов
    transit_place: Optional[str] = None
    transit_latitude: Optional[float] = None
    transit_longitude: Optional[float] = None


class DailyForecastRequest(TransitsAnalysisRequest):
    """Прогноз дня: те же входные данные, что у анализа транзитов,
    плюс выбор LLM с фронтенда."""
    llm_provider: Optional[str] = None  # claude | deepseek | gemini | openrouter; None = settings.LLM_PROVIDER
    llm_model: Optional[str] = None     # слаг модели для openrouter
    transit_timezone: Optional[str] = None  # IANA-таймзона места транзита: время трактуется как МЕСТНОЕ
    # Метод карты события (Frawley, Sports Astrology гл. 2): ход Луны зависит от спорта.
    # Футбол 80+ мин = 5°, короткие форматы = 4°, однодневный крикет = 13°.
    moon_range_degrees: float = Field(default=5.0, gt=0, le=30, allow_inf_nan=False)
    extra_time_possible: bool = False   # +1° к ходу Луны, если возможно доп. время


class TransitsAnalysisResponse(BaseModel):
    analysis: str
    summary: str
    transits_summary: Optional[Dict[str, Any]] = None
    transit_data: Optional[Dict[str, Any]] = None


class ProgressedSynastryRequest(BaseModel):
    """Запрос расчёта прогрессивной синастрии (два партнёра)"""
    chart1: ChartRequest
    chart2: ChartRequest
    target_date: Optional[datetime] = None  # по умолчанию — сегодня; можно любой день
    house_system: Optional[str] = "Placidus"


class ProgressedSynastryAnalysisRequest(BaseModel):
    """Запрос AI-анализа прогрессивной синастрии"""
    # Предпочтительный путь: фронтенд передаёт готовые расчётные данные
    progressed_synastry_data: Optional[Dict[str, Any]] = None
    # Натальные карты партнёров (для слоёв 2 и 3) — chart_data из БД
    natal_chart1: Optional[Dict[str, Any]] = None
    natal_chart2: Optional[Dict[str, Any]] = None

    # Fallback: пересчёт на бэкенде
    chart1: Optional[ChartRequest] = None
    chart2: Optional[ChartRequest] = None
    target_date: Optional[datetime] = None
    house_system: Optional[str] = "Placidus"

    language: str = "ru"
    mode: str = "advanced"  # simple | advanced
    top_k_per_book: int = 2
    relationship_context: Optional[str] = None


class ProgressedSynastryAnalysisResponse(BaseModel):
    analysis: str
    summary: str
    progressed_synastry_summary: Optional[Dict[str, Any]] = None
    progressed_synastry_data: Optional[Dict[str, Any]] = None
