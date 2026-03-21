from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime

# Initialize Swiss Ephemeris via helper (sets Moshier mode)
from app import swephelper

from app.db.database import get_db
from app.models.models import User, NatalChart, ChartInterpretation, Book
from app.schemas.schemas import (
    UserCreate, UserResponse, NatalChartCreate, NatalChartResponse,
    InterpretationCreate, InterpretationResponse, BookCreate, BookResponse,
    QueryRequest, SynastryRequest
)
# v1 removed - using Swiss Ephemeris only
from app.utils.astrology_v2 import (
    calculate_planet_positions, calculate_aspects,
    calculate_solar_return, calculate_synastry
)
import json

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
import json
from datetime import datetime
from zoneinfo import ZoneInfo

# Инициализируем геокодер (бесплатный Nominatim)
geolocator = Nominatim(user_agent="astrology_app_v2")

# Инициализируем определитель часового пояса
try:
    from timezonefinder import TimezoneFinder
    tz_finder = TimezoneFinder()
except Exception:
    tz_finder = None

def get_coordinates_and_tz(place: str) -> tuple:
    """Получить координаты и часовой пояс из названия места"""
    try:
        location = geolocator.geocode(place, timeout=10)
        if location:
            lat, lon = location.latitude, location.longitude
            
            # Определяем часовой пояс
            timezone_str = None
            if tz_finder:
                try:
                    timezone_str = tz_finder.timezone_at(lng=lon, lat=lat)
                except Exception:
                    pass
            
            return (lat, lon, timezone_str)
    except GeocoderTimedOut:
        pass
    except Exception as e:
        print(f"Geocoding error: {e}")
    
    # Fallback - Москва
    return (55.7558, 37.6173, "Europe/Moscow")

def get_timezone_offset(timezone_str: str, dt: datetime) -> float:
    """Получить смещение часового пояса в часах от UTC"""
    if not timezone_str:
        return 0.0
    try:
        tz = ZoneInfo(timezone_str)
        # Получаем UTC смещение для данного времени
        local_dt = dt.replace(tzinfo=tz)
        offset = local_dt.utcoffset().total_seconds() / 3600
        return offset
    except Exception:
        return 0.0

# Legacy функция для совместимости
def get_coordinates(place: str) -> tuple:
    """Получить координаты из названия места (старый интерфейс)"""
    lat, lon, _ = get_coordinates_and_tz(place)
    return (lat, lon)

router = APIRouter()

# Users
@router.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
    db_user = User(
        name=user.name,
        birth_date=user.birth_date,
        birth_time=user.birth_time,
        birth_place=user.birth_place,
        created_at=datetime.utcnow()
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Natal Charts - Swiss Ephemeris
@router.post("/charts", response_model=NatalChartResponse)
async def create_chart(chart: NatalChartCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.id == chart.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Геокодирование + часовой пояс
    lat, lon, timezone_str = get_coordinates_and_tz(user.birth_place)
    
    # Конвертируем местное время в UTC для Swiss Ephemeris
    # ИСПРАВЛЕНИЕ: объединяем дату и время
    birth_dt_local = user.birth_date
    if user.birth_time:
        # birth_time stored as "HH:MM" string
        time_parts = user.birth_time.split(':')
        if len(time_parts) == 2:
            from datetime import time as dt_time
            birth_time_obj = dt_time(int(time_parts[0]), int(time_parts[1]))
            birth_dt_local = datetime.combine(user.birth_date, birth_time_obj)
    
    birth_dt_utc = birth_dt_local
    if timezone_str:
        try:
            import pytz
            from datetime import timedelta
            
            # Для исторических дат - используем правильный часовой пояс с учётом DST
            # СССР использовал декретное время + летнее время
            # До 1990: Москва = UTC+3 (декретное), летом +1 = UTC+4
            
            is_ukraine = 'Kyiv' in timezone_str or 'Kiev' in timezone_str
            
            if is_ukraine and user.birth_date.year < 1990:
                # Для Украины до 1990: декретно +3, летом +4
                # Летнее время: с последнего марта по последнее октября
                month = user.birth_date.month
                if month >= 4 and month <= 10:
                    # Летнее время UTC+4
                    moscow_tz = pytz.timezone('Europe/Moscow')
                    # Moscow summer time was UTC+4
                    import datetime as dt
                    summer_time = dt.timezone(dt.timedelta(hours=4))
                    birth_dt_utc = birth_dt_local.replace(tzinfo=summer_time).astimezone(pytz.UTC).replace(tzinfo=None)
                else:
                    # Зимнее время UTC+3
                    moscow_tz = pytz.timezone('Europe/Moscow')
                    import datetime as dt
                    winter_time = dt.timezone(dt.timedelta(hours=3))
                    birth_dt_utc = birth_dt_local.replace(tzinfo=winter_time).astimezone(pytz.UTC).replace(tzinfo=None)
            else:
                # Для других мест используем современный часовой пояс
                tz = pytz.timezone(timezone_str)
                localized_dt = tz.localize(user.birth_date.replace(tzinfo=None))
                birth_dt_utc = localized_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        except Exception as e:
            print(f"Timezone conversion error: {e}")
    
    # Calculate planetary positions (Swiss Ephemeris)
    positions = calculate_planet_positions(birth_dt_utc, user.birth_place, lat, lon)
    
    # Calculate aspects with ASC and MC
    aspects = calculate_aspects(
        positions['planets'],
        asc_longitude=positions.get('ascendant_full'),
        mc_longitude=positions.get('mc_full'),
        houses=positions.get('houses')
    )
    
    db_chart = NatalChart(
        user_id=user.id,
        sun_sign=positions.get('sun_sign'),
        moon_sign=positions.get('moon_sign'),
        ascendant=positions.get('ascendant'),
        planets=json.dumps(positions['planets']),
        houses=json.dumps(positions.get('houses', {})),
        aspects=json.dumps(aspects),
        created_at=datetime.utcnow()
    )
    db.add(db_chart)
    await db.commit()
    await db.refresh(db_chart)
    return db_chart

@router.get("/charts/{chart_id}", response_model=NatalChartResponse)
async def get_chart(chart_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    return chart

# Interpretations
@router.post("/charts/{chart_id}/interpret", response_model=InterpretationResponse)
async def interpret_chart(chart_id: int, interpretation: InterpretationCreate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    
    # Generate interpretation using AI (simplified)
    planets = json.loads(chart.planets) if chart.planets else {}
    interpretation_text = f"Натальная карта {chart.sun_sign} солнечного знака. "
    interpretation_text += f"Луна в {chart.moon_sign}. Асцендент {chart.ascendant}. "
    interpretation_text += "Это базовая интерпретация. Для полной версии требуется AI."
    
    db_interp = ChartInterpretation(
        chart_id=chart_id,
        type=interpretation.type,
        interpretation=interpretation_text,
        created_at=datetime.utcnow()
    )
    db.add(db_interp)
    await db.commit()
    await db.refresh(db_interp)
    return db_interp

# Solar Return
@router.get("/charts/{chart_id}/solar-return")
async def get_solar_return(chart_id: int, year: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    
    result = await db.execute(select(User).where(User.id == chart.user_id))
    user = result.scalar_one()
    
    solar = calculate_solar_return(user.birth_date, year)
    return solar

# Transits
@router.get("/charts/{chart_id}/transits")
async def get_transits(chart_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
    chart = result.scalar_one_or_none()
    if not chart:
        raise HTTPException(status_code=404, detail="Chart not found")
    
    transits = calculate_transits(chart.created_at, datetime.utcnow())
    return transits

# Synastry
@router.post("/synastry")
async def create_synastry(request: SynastryRequest, db: AsyncSession = Depends(get_db)):
    result1 = await db.execute(select(NatalChart).where(NatalChart.id == request.chart1_id))
    chart1 = result1.scalar_one_or_none()
    if not chart1:
        raise HTTPException(status_code=404, detail="First chart not found")
    
    result2 = await db.execute(select(NatalChart).where(NatalChart.id == request.chart2_id))
    chart2 = result2.scalar_one_or_none()
    if not chart2:
        raise HTTPException(status_code=404, detail="Second chart not found")
    
    planets1 = json.loads(chart1.planets) if chart1.planets else {}
    planets2 = json.loads(chart2.planets) if chart2.planets else {}
    
    synastry = calculate_synastry(
        {'planets': planets1},
        {'planets': planets2}
    )
    return synastry

# Books
@router.post("/books", response_model=BookResponse)
async def create_book(book: BookCreate, db: AsyncSession = Depends(get_db)):
    db_book = Book(
        title=book.title,
        content=book.content,
        created_at=datetime.utcnow()
    )
    db.add(db_book)
    await db.commit()
    await db.refresh(db_book)
    return db_book

@router.get("/books")
async def get_books(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book))
    books = result.scalars().all()
    return books

@router.post("/books/{book_id}/query")
async def query_book(book_id: int, request: QueryRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Book).where(Book.id == book_id))
    book = result.scalar_one_or_none()
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Simple search (in production, use vector DB)
    content_lower = book.content.lower()
    query_lower = request.query.lower()
    
    if query_lower in content_lower:
        # Find context around the match
        idx = content_lower.find(query_lower)
        start = max(0, idx - 200)
        end = min(len(book.content), idx + len(request.query) + 200)
        context = book.content[start:end]
        return {"result": context, "book_title": book.title}
    
    return {"result": "No match found", "book_title": book.title}
