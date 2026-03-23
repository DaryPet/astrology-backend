# from fastapi import APIRouter, Depends, HTTPException
# from sqlalchemy.ext.asyncio import AsyncSession
# from sqlalchemy import select
# from datetime import datetime

# # Initialize Swiss Ephemeris via helper (sets Moshier mode)
# from app import swephelper

# from app.db.database import get_db
# from app.models.models import User, NatalChart, ChartInterpretation, Book
# from app.schemas.schemas import (
#     UserCreate, UserResponse, NatalChartCreate, NatalChartResponse,
#     InterpretationCreate, InterpretationResponse, BookCreate, BookResponse,
#     QueryRequest, SynastryRequest, NatalChartRequest, NatalChartResponseFull,
#     TransitRequest, SynastryRequestDirect
# )
# # from app.utils.astrology import (
# #     calculate_planet_positions as calc_positions_v1, calculate_aspects as calc_aspects_v1,
# #     calculate_solar_return as calc_sr_v1, calculate_transits, calculate_synastry as calc_syn_v1
# # )
# from app.utils.astrology_v2 import (
#     calculate_planet_positions, calculate_aspects,
#     calculate_solar_return, calculate_synastry,
#     PLANETS, ASPECTS, ASPECTS_RU, ORBS, get_zodiac_sign, get_zodiac_degree
# )
# from app.swephelper import swe
# import json

# from geopy.geocoders import Nominatim
# from geopy.exc import GeocoderTimedOut
# import json

# # Инициализируем геокодер (бесплатный Nominatim)
# geolocator = Nominatim(user_agent="astrology_app_v2")

# def get_coordinates(place: str) -> tuple:
#     """Получить координаты из названия места с помощью geocoding"""
#     try:
#         location = geolocator.geocode(place, timeout=10)
#         if location:
#             return (location.latitude, location.longitude)
#     except GeocoderTimedOut:
#         pass
#     except Exception as e:
#         print(f"Geocoding error: {e}")
    
#     # Fallback - возвращаем Moscow
#     return (55.7558, 37.6173)

# router = APIRouter()

# # Users
# @router.post("/users", response_model=UserResponse)
# async def create_user(user: UserCreate, db: AsyncSession = Depends(get_db)):
#     db_user = User(
#         name=user.name,
#         birth_date=user.birth_date,
#         birth_time=user.birth_time,
#         birth_place=user.birth_place,
#         created_at=datetime.utcnow()
#     )
#     db.add(db_user)
#     await db.commit()
#     await db.refresh(db_user)
#     return db_user

# @router.get("/users/{user_id}", response_model=UserResponse)
# async def get_user(user_id: int, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(User).where(User.id == user_id))
#     user = result.scalar_one_or_none()
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")
#     return user

# # Natal Charts - Swiss Ephemeris
# @router.post("/charts", response_model=NatalChartResponse)
# async def create_chart(chart: NatalChartCreate, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(User).where(User.id == chart.user_id))
#     user = result.scalar_one_or_none()
#     if not user:
#         raise HTTPException(status_code=404, detail="User not found")
    
#     # Простая геокодирование - для продвинутого нужно добавить geocoding
#     lat, lon = get_coordinates(user.birth_place)
    
#     # Calculate planetary positions (Swiss Ephemeris)
#     positions = calculate_planet_positions(user.birth_date, user.birth_place, lat, lon)
#     aspects = calculate_aspects(positions['planets'])
    
#     db_chart = NatalChart(
#         user_id=user.id,
#         sun_sign=positions.get('sun_sign'),
#         moon_sign=positions.get('moon_sign'),
#         ascendant=positions.get('ascendant'),
#         planets=json.dumps(positions['planets']),
#         houses=json.dumps(positions.get('houses', {})),
#         aspects=json.dumps(aspects),
#         created_at=datetime.utcnow()
#     )
#     db.add(db_chart)
#     await db.commit()
#     await db.refresh(db_chart)
#     return db_chart

# @router.get("/charts/{chart_id}", response_model=NatalChartResponse)
# async def get_chart(chart_id: int, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
#     chart = result.scalar_one_or_none()
#     if not chart:
#         raise HTTPException(status_code=404, detail="Chart not found")
#     return chart

# # Interpretations
# @router.post("/charts/{chart_id}/interpret", response_model=InterpretationResponse)
# async def interpret_chart(chart_id: int, interpretation: InterpretationCreate, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
#     chart = result.scalar_one_or_none()
#     if not chart:
#         raise HTTPException(status_code=404, detail="Chart not found")
    
#     # Generate interpretation using AI (simplified)
#     planets = json.loads(chart.planets) if chart.planets else {}
#     interpretation_text = f"Натальная карта {chart.sun_sign} солнечного знака. "
#     interpretation_text += f"Луна в {chart.moon_sign}. Асцендент {chart.ascendant}. "
#     interpretation_text += "Это базовая интерпретация. Для полной версии требуется AI."
    
#     db_interp = ChartInterpretation(
#         chart_id=chart_id,
#         type=interpretation.type,
#         interpretation=interpretation_text,
#         created_at=datetime.utcnow()
#     )
#     db.add(db_interp)
#     await db.commit()
#     await db.refresh(db_interp)
#     return db_interp

# # Solar Return
# @router.get("/charts/{chart_id}/solar-return")
# async def get_solar_return(chart_id: int, year: int, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
#     chart = result.scalar_one_or_none()
#     if not chart:
#         raise HTTPException(status_code=404, detail="Chart not found")
    
#     result = await db.execute(select(User).where(User.id == chart.user_id))
#     user = result.scalar_one()
    
#     solar = calculate_solar_return(user.birth_date, year)
#     return solar

# # Transits
# @router.get("/charts/{chart_id}/transits")
# async def get_transits(chart_id: int, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(NatalChart).where(NatalChart.id == chart_id))
#     chart = result.scalar_one_or_none()
#     if not chart:
#         raise HTTPException(status_code=404, detail="Chart not found")
    
#     transits = calculate_transits(chart.created_at, datetime.utcnow())
#     return transits

# # Synastry
# @router.post("/synastry")
# async def create_synastry(request: SynastryRequest, db: AsyncSession = Depends(get_db)):
#     result1 = await db.execute(select(NatalChart).where(NatalChart.id == request.chart1_id))
#     chart1 = result1.scalar_one_or_none()
#     if not chart1:
#         raise HTTPException(status_code=404, detail="First chart not found")
    
#     result2 = await db.execute(select(NatalChart).where(NatalChart.id == request.chart2_id))
#     chart2 = result2.scalar_one_or_none()
#     if not chart2:
#         raise HTTPException(status_code=404, detail="Second chart not found")
    
#     planets1 = json.loads(chart1.planets) if chart1.planets else {}
#     planets2 = json.loads(chart2.planets) if chart2.planets else {}
    
#     synastry = calculate_synastry(
#         {'planets': planets1},
#         {'planets': planets2}
#     )
#     return synastry

# # Books
# @router.post("/books", response_model=BookResponse)
# async def create_book(book: BookCreate, db: AsyncSession = Depends(get_db)):
#     db_book = Book(
#         title=book.title,
#         content=book.content,
#         created_at=datetime.utcnow()
#     )
#     db.add(db_book)
#     await db.commit()
#     await db.refresh(db_book)
#     return db_book

# @router.get("/books")
# async def get_books(db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(Book))
#     books = result.scalars().all()
#     return books

# @router.post("/books/{book_id}/query")
# async def query_book(book_id: int, request: QueryRequest, db: AsyncSession = Depends(get_db)):
#     result = await db.execute(select(Book).where(Book.id == book_id))
#     book = result.scalar_one_or_none()
#     if not book:
#         raise HTTPException(status_code=404, detail="Book not found")
    
#     # Simple search (in production, use vector DB)
#     content_lower = book.content.lower()
#     query_lower = request.query.lower()
    
#     if query_lower in content_lower:
#         # Find context around the match
#         idx = content_lower.find(query_lower)
#         start = max(0, idx - 200)
#         end = min(len(book.content), idx + len(request.query) + 200)
#         context = book.content[start:end]
#         return {"result": context, "book_title": book.title}
    
#     return {"result": "No match found", "book_title": book.title}


# # ============================================
# # NATAL CHART CALCULATION (without DB)
# # ============================================

# @router.post("/chart/calculate")
# async def calculate_natal_chart(request: NatalChartRequest) -> NatalChartResponseFull:
#     """
#     Расчёт натальной карты напрямую (без сохранения в БД)
    
#     Требует:
#     - birth_date: Дата и время рождения
#     - birth_place: Название места
#     - latitude: Широта
#     - longitude: Долгота
#     - timezone: Временная зона (IANA, например "Europe/Moscow")
#     - house_system: Система домов (Placidus, Equal, WholeSign, etc.)
#     """
#     # Используем переданные координаты
#     lat = request.latitude
#     lon = request.longitude
    
#     # Parse birth time if provided
#     birth_datetime = request.birth_date
#     if request.birth_time:
#         try:
#             # Try to parse time string like "14:30"
#             time_parts = request.birth_time.split(':')
#             hour = int(time_parts[0])
#             minute = int(time_parts[1]) if len(time_parts) > 1 else 0
#             second = int(time_parts[2]) if len(time_parts) > 2 else 0
#             from datetime import time
#             birth_datetime = birth_datetime.replace(hour=hour, minute=minute, second=second)
#         except:
#             pass
    
#     # Apply timezone if provided
#     if request.timezone:
#         try:
#             from zoneinfo import ZoneInfo
#             tz = ZoneInfo(request.timezone)
#             # If birth_datetime is naive, assume it's in the given timezone
#             if birth_datetime.tzinfo is None:
#                 birth_datetime = birth_datetime.replace(tzinfo=tz)
#         except Exception as e:
#             print(f"Timezone error: {e}")
    
#     # Calculate natal chart using Swiss Ephemeris v2
#     chart = calculate_planet_positions(
#         birth_date=birth_datetime,
#         birth_place=request.birth_place,
#         lat=lat,
#         lon=lon,
#         timezone_str=request.timezone,
#         house_system=request.house_system or 'Placidus'
#     )
    
#     # Calculate aspects
#     aspects = calculate_aspects(chart['planets'])
    
#     # Return full chart with aspects
#     return {
#         'sun_sign': chart['sun_sign'],
#         'sun_sign_ru': chart['sun_sign_ru'],
#         'moon_sign': chart['moon_sign'],
#         'moon_sign_ru': chart['moon_sign_ru'],
#         'ascendant': chart['ascendant'],
#         'ascendant_ru': chart['ascendant_ru'],
#         'ascendant_degree': chart['ascendant_degree'],
#         'mc': chart['mc'],
#         'mc_ru': chart['mc_ru'],
#         'mc_degree': chart.get('mc_degree', 0),
#         'planets': chart['planets'],
#     'houses': {str(k): v for k, v in chart['houses'].items()},
#         'houses_meta': chart.get('houses_meta', {}),
#         'meta': chart.get('meta', {}),
#         'aspects': aspects,
#     }


# # ============================================
# # TRANSITS CALCULATION
# # ============================================

# @router.post("/transits")
# async def calculate_transits_direct(request: TransitRequest):
#     """
#     Расчёт текущих транзитов к натальной карте
    
#     Требует:
#     - birth_date, birth_place, latitude, longitude, timezone - данные натальной карты
#     - transit_date - дата транзитов
#     """
#     # Get natal chart
#     natal = calculate_planet_positions(
#         birth_date=request.birth_date,
#         birth_place=request.birth_place,
#         lat=request.latitude,
#         lon=request.longitude,
#         timezone_str=request.timezone,
#     )
    
#     # Calculate transiting planets at transit_date
#     transit_datetime = request.transit_date
#     if request.timezone:
#         try:
#             from zoneinfo import ZoneInfo
#             tz = ZoneInfo(request.timezone)
#             if transit_datetime.tzinfo is None:
#                 transit_datetime = transit_datetime.replace(tzinfo=tz)
#         except:
#             pass
    
#     transit_jd = swe.utc_to_jd(
#         transit_datetime.year, transit_datetime.month, transit_datetime.day,
#         transit_datetime.hour, transit_datetime.minute, transit_datetime.second,
#         swe.GREG_CAL
#     )[0]
    
#     # Get transiting planets
#     transiting_planets = {}
#     for planet_name, planet_id in PLANETS.items():
#         if planet_name in ['SouthNode']:  # Skip duplicate
#             continue
#         try:
#             result = swe.calc_ut(transit_jd, planet_id, swe.FLG_MOSEPH)
#             longitude = result[0][0]
#             sign_en, sign_ru = get_zodiac_sign(longitude)
#             transiting_planets[planet_name] = {
#                 'planet': planet_name,
#                 'sign': sign_en,
#                 'sign_ru': sign_ru,
#                 'degree': round(get_zodiac_degree(longitude), 4),
#                 'full_degree': round(longitude, 4),
#             }
#         except:
#             pass
    
#     # Calculate aspects between transiting and natal planets
#     transit_aspects = []
#     for t_planet, t_data in transiting_planets.items():
#         for n_planet, n_data in natal['planets'].items():
#             lon1 = t_data['full_degree']
#             lon2 = n_data['full_degree']
            
#             diff = abs(lon1 - lon2)
#             if diff > 180:
#                 diff = 360 - diff
            
#             for aspect_degree, aspect_name in ASPECTS.items():
#                 key = tuple(sorted([t_planet, n_planet]))
#                 orb = ORBS.get(key, 6)
                
#                 if abs(diff - aspect_degree) <= orb:
#                     transit_aspects.append({
#                         'transiting': t_planet,
#                         'natal': n_planet,
#                         'aspect': aspect_name,
#                         'aspect_ru': ASPECTS_RU[aspect_degree],
#                         'orb': round(abs(diff - aspect_degree), 2),
#                         'transiting_sign': t_data['sign'],
#                         'natal_sign': n_data['sign'],
#                     })
#                     break
    
#     # Sort by importance
#     transit_aspects.sort(key=lambda x: x['orb'])
    
#     return {
#         'transit_date': request.transit_date.isoformat(),
#         'natal_date': request.birth_date.isoformat(),
#         'transiting_planets': transiting_planets,
#         'aspects': transit_aspects,
#     }


# # ============================================
# # SYNASTRY (Direct calculation)
# # ============================================

# @router.post("/synastry/direct")
# async def calculate_synastry_direct(request: SynastryRequestDirect):
#     """
#     Прямой расчёт синастрии между двумя картами
#     """
#     # Calculate first chart
#     chart1 = calculate_planet_positions(
#         birth_date=request.chart1.birth_date,
#         birth_place=request.chart1.birth_place,
#         lat=request.chart1.latitude,
#         lon=request.chart1.longitude,
#         timezone_str=request.chart1.timezone,
#     )
    
#     # Calculate second chart
#     chart2 = calculate_planet_positions(
#         birth_date=request.chart2.birth_date,
#         birth_place=request.chart2.birth_place,
#         lat=request.chart2.latitude,
#         lon=request.chart2.longitude,
#         timezone_str=request.chart2.timezone,
#     )
    
#     # Calculate synastry aspects
#     aspects = []
#     for p1_name, p1_data in chart1['planets'].items():
#         for p2_name, p2_data in chart2['planets'].items():
#             lon1 = p1_data['full_degree']
#             lon2 = p2_data['full_degree']
            
#             diff = abs(lon1 - lon2)
#             if diff > 180:
#                 diff = 360 - diff
            
#             for aspect_degree, aspect_name in ASPECTS.items():
#                 key = tuple(sorted([p1_name, p2_name]))
#                 orb = ORBS.get(key, 6)
                
#                 if abs(diff - aspect_degree) <= orb:
#                     aspects.append({
#                         'planet1': p1_name,
#                         'planet2': p2_name,
#                         'planet1_sign': p1_data['sign'],
#                         'planet2_sign': p2_data['sign'],
#                         'aspect': aspect_name,
#                         'aspect_ru': ASPECTS_RU[aspect_degree],
#                         'orb': round(abs(diff - aspect_degree), 2),
#                     })
#                     break
    
#     # Sort by importance
#     aspect_priority = {'Conjunction': 5, 'Opposition': 4, 'Trine': 3, 'Square': 2, 'Sextile': 1}
#     aspects.sort(key=lambda x: (aspect_priority.get(x['aspect'], 0), -x['orb']), reverse=True)
    
#     return {
#         'chart1': {
#             'sun_sign': chart1['sun_sign'],
#             'moon_sign': chart1['moon_sign'],
#             'ascendant': chart1['ascendant'],
#             'meta': chart1.get('meta', {}),
#         },
#         'chart2': {
#             'sun_sign': chart2['sun_sign'],
#             'moon_sign': chart2['moon_sign'],
#             'ascendant': chart2['ascendant'],
#             'meta': chart2.get('meta', {}),
#         },
#         'aspects': aspects,
#         'total_aspects': len(aspects),
#     }

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
    QueryRequest, SynastryRequest, NatalChartRequest, NatalChartResponseFull,
    TransitRequest, SynastryRequestDirect
)
from app.utils.astrology_v2 import (
    calculate_planet_positions, calculate_aspects,
    calculate_solar_return, calculate_synastry,
    PLANETS, ASPECTS, ASPECTS_RU, ORBS, get_zodiac_sign, get_zodiac_degree
)
from app.swephelper import swe
import json

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut

# Инициализируем геокодер (бесплатный Nominatim)
geolocator = Nominatim(user_agent="astrology_app_v2")

def get_coordinates(place: str) -> tuple:
    """Получить координаты из названия места с помощью geocoding"""
    try:
        location = geolocator.geocode(place, timeout=10)
        if location:
            return (location.latitude, location.longitude)
    except GeocoderTimedOut:
        pass
    except Exception as e:
        print(f"Geocoding error: {e}")
    
    # Fallback - возвращаем Moscow
    return (55.7558, 37.6173)

def autocomplete_place(query: str) -> list:
    """Возвращает список мест для автодополнения"""
    try:
        locations = geolocator.geocode(query, exactly_one=False, limit=5, language='ru')
        if locations:
            return [
                {
                    "name": loc.address,
                    "lat": loc.latitude,
                    "lon": loc.longitude,
                    "display_name": loc.address.split(',')[0]
                }
                for loc in locations
            ]
    except Exception as e:
        print(f"Autocomplete error: {e}")
    return []

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
    
    # Простая геокодирование - для продвинутого нужно добавить geocoding
    lat, lon = get_coordinates(user.birth_place)
    
    # Calculate planetary positions (Swiss Ephemeris)
    positions = calculate_planet_positions(user.birth_date, user.birth_place, lat, lon)
    aspects = calculate_aspects(positions['planets'])
    
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


# ============================================
# GEOCODE AUTOCOMPLETE
# ============================================

@router.get("/geocode/autocomplete")
async def geocode_autocomplete(q: str):
    """
    Автодополнение для ввода города
    
    Возвращает список возможных городов по введённому тексту
    """
    results = autocomplete_place(q)
    return results


# ============================================
# NATAL CHART CALCULATION (without DB)
# ============================================

@router.post("/chart/calculate")
async def calculate_natal_chart(request: NatalChartRequest) -> NatalChartResponseFull:
    """
    Расчёт натальной карты напрямую (без сохранения в БД)
    
    Требует:
    - birth_date: Дата и время рождения
    - birth_place: Название места
    - timezone: Временная зона (IANA, например "Europe/Moscow")
    - house_system: Система домов (Placidus, Equal, WholeSign, etc.)
    """
    # Получаем координаты из названия места
    lat, lon = get_coordinates(request.birth_place)
    
    # Parse birth time if provided
    birth_datetime = request.birth_date
    if request.birth_time:
        try:
            # Try to parse time string like "14:30"
            time_parts = request.birth_time.split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1]) if len(time_parts) > 1 else 0
            second = int(time_parts[2]) if len(time_parts) > 2 else 0
            from datetime import time
            birth_datetime = birth_datetime.replace(hour=hour, minute=minute, second=second)
        except:
            pass
    
    # Apply timezone if provided
    if request.timezone:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(request.timezone)
            # If birth_datetime is naive, assume it's in the given timezone
            if birth_datetime.tzinfo is None:
                birth_datetime = birth_datetime.replace(tzinfo=tz)
        except Exception as e:
            print(f"Timezone error: {e}")
    
    # Calculate natal chart using Swiss Ephemeris v2
    chart = calculate_planet_positions(
        birth_date=birth_datetime,
        birth_place=request.birth_place,
        lat=lat,
        lon=lon,
        timezone_str=request.timezone,
        house_system=request.house_system or 'Placidus'
    )
    
    # Calculate aspects
    aspects = calculate_aspects(chart['planets'])
    
    # Return full chart with aspects
    return {
        'sun_sign': chart['sun_sign'],
        'sun_sign_ru': chart['sun_sign_ru'],
        'moon_sign': chart['moon_sign'],
        'moon_sign_ru': chart['moon_sign_ru'],
        'ascendant': chart['ascendant'],
        'ascendant_ru': chart['ascendant_ru'],
        'ascendant_degree': chart['ascendant_degree'],
        'mc': chart['mc'],
        'mc_ru': chart['mc_ru'],
        'mc_degree': chart.get('mc_degree', 0),
        'planets': chart['planets'],
        'houses': {str(k): v for k, v in chart['houses'].items()},
        'houses_meta': chart.get('houses_meta', {}),
        'meta': chart.get('meta', {}),
        'aspects': aspects,
    }


# ============================================
# TRANSITS CALCULATION
# ============================================

@router.post("/transits")
async def calculate_transits_direct(request: TransitRequest):
    """
    Расчёт текущих транзитов к натальной карте
    
    Требует:
    - birth_date, birth_place, timezone - данные натальной карты
    - transit_date - дата транзитов
    """
    # Получаем координаты из названия места
    lat, lon = get_coordinates(request.birth_place)
    
    # Get natal chart
    natal = calculate_planet_positions(
        birth_date=request.birth_date,
        birth_place=request.birth_place,
        lat=lat,
        lon=lon,
        timezone_str=request.timezone,
    )
    
    # Calculate transiting planets at transit_date
    transit_datetime = request.transit_date
    if request.timezone:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(request.timezone)
            if transit_datetime.tzinfo is None:
                transit_datetime = transit_datetime.replace(tzinfo=tz)
        except:
            pass
    
    transit_jd = swe.utc_to_jd(
        transit_datetime.year, transit_datetime.month, transit_datetime.day,
        transit_datetime.hour, transit_datetime.minute, transit_datetime.second,
        swe.GREG_CAL
    )[0]
    
    # Get transiting planets
    transiting_planets = {}
    for planet_name, planet_id in PLANETS.items():
        if planet_name in ['SouthNode']:  # Skip duplicate
            continue
        try:
            result = swe.calc_ut(transit_jd, planet_id, swe.FLG_MOSEPH)
            longitude = result[0][0]
            sign_en, sign_ru = get_zodiac_sign(longitude)
            transiting_planets[planet_name] = {
                'planet': planet_name,
                'sign': sign_en,
                'sign_ru': sign_ru,
                'degree': round(get_zodiac_degree(longitude), 4),
                'full_degree': round(longitude, 4),
            }
        except:
            pass
    
    # Calculate aspects between transiting and natal planets
    transit_aspects = []
    for t_planet, t_data in transiting_planets.items():
        for n_planet, n_data in natal['planets'].items():
            lon1 = t_data['full_degree']
            lon2 = n_data['full_degree']
            
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            
            for aspect_degree, aspect_name in ASPECTS.items():
                key = tuple(sorted([t_planet, n_planet]))
                orb = ORBS.get(key, 6)
                
                if abs(diff - aspect_degree) <= orb:
                    transit_aspects.append({
                        'transiting': t_planet,
                        'natal': n_planet,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'orb': round(abs(diff - aspect_degree), 2),
                        'transiting_sign': t_data['sign'],
                        'natal_sign': n_data['sign'],
                    })
                    break
    
    # Sort by importance
    transit_aspects.sort(key=lambda x: x['orb'])
    
    return {
        'transit_date': request.transit_date.isoformat(),
        'natal_date': request.birth_date.isoformat(),
        'transiting_planets': transiting_planets,
        'aspects': transit_aspects,
    }


# ============================================
# SYNASTRY (Direct calculation)
# ============================================

@router.post("/synastry/direct")
async def calculate_synastry_direct(request: SynastryRequestDirect):
    """
    Прямой расчёт синастрии между двумя картами
    """
    # Получаем координаты для первой карты
    lat1, lon1 = get_coordinates(request.chart1.birth_place)
    
    # Calculate first chart
    chart1 = calculate_planet_positions(
        birth_date=request.chart1.birth_date,
        birth_place=request.chart1.birth_place,
        lat=lat1,
        lon=lon1,
        timezone_str=request.chart1.timezone,
    )
    
    # Получаем координаты для второй карты
    lat2, lon2 = get_coordinates(request.chart2.birth_place)
    
    # Calculate second chart
    chart2 = calculate_planet_positions(
        birth_date=request.chart2.birth_date,
        birth_place=request.chart2.birth_place,
        lat=lat2,
        lon=lon2,
        timezone_str=request.chart2.timezone,
    )
    
    # Calculate synastry aspects
    aspects = []
    for p1_name, p1_data in chart1['planets'].items():
        for p2_name, p2_data in chart2['planets'].items():
            lon1 = p1_data['full_degree']
            lon2 = p2_data['full_degree']
            
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            
            for aspect_degree, aspect_name in ASPECTS.items():
                key = tuple(sorted([p1_name, p2_name]))
                orb = ORBS.get(key, 6)
                
                if abs(diff - aspect_degree) <= orb:
                    aspects.append({
                        'planet1': p1_name,
                        'planet2': p2_name,
                        'planet1_sign': p1_data['sign'],
                        'planet2_sign': p2_data['sign'],
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'orb': round(abs(diff - aspect_degree), 2),
                    })
                    break
    
    # Sort by importance
    aspect_priority = {'Conjunction': 5, 'Opposition': 4, 'Trine': 3, 'Square': 2, 'Sextile': 1}
    aspects.sort(key=lambda x: (aspect_priority.get(x['aspect'], 0), -x['orb']), reverse=True)
    
    return {
        'chart1': {
            'sun_sign': chart1['sun_sign'],
            'moon_sign': chart1['moon_sign'],
            'ascendant': chart1['ascendant'],
            'meta': chart1.get('meta', {}),
        },
        'chart2': {
            'sun_sign': chart2['sun_sign'],
            'moon_sign': chart2['moon_sign'],
            'ascendant': chart2['ascendant'],
            'meta': chart2.get('meta', {}),
        },
        'aspects': aspects,
        'total_aspects': len(aspects),
    }