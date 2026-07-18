from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import json
import time
from typing import List, Dict, Any, Optional
from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize Swiss Ephemeris via helper (sets Moshier mode)
from app import swephelper
from app.db.database import get_db
from app.models.models import User, NatalChart, ChartInterpretation, Book, BookChunk, FullChartAnalysis
from app.schemas.schemas import (
    UserCreate, UserResponse, NatalChartCreate, NatalChartResponse,
    InterpretationCreate, InterpretationResponse, BookCreate, BookResponse,
    QueryRequest, SynastryRequest, NatalChartRequest, NatalChartResponseFull,
    TransitRequest, SynastryRequestDirect, BookChunkResponse
)
from app.schemas.analysis import SynastryAnalysisRequest, ProgressionsRequest, ProgressionsAnalysisRequest, TransitsRequest, TransitsAnalysisRequest, ProgressedSynastryRequest, ProgressedSynastryAnalysisRequest, DailyForecastRequest
from app.utils.astrology_v2 import (
    calculate_planet_positions, calculate_aspects,
    calculate_solar_return, calculate_synastry,
    calculate_secondary_progressions,
    calculate_transits,
    calculate_progressed_synastry,
    PLANETS, ASPECTS, ASPECTS_RU, ORBS, get_zodiac_sign, get_zodiac_degree,
    get_house_for_longitude
)
from app.swephelper import swe
from app.auth import get_current_user

# Rate limiter for endpoints
limiter = Limiter(key_func=get_remote_address)

# Геокодинг и определение таймзон
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from timezonefinder import TimezoneFinder
import pytz

# Инициализируем геокодер (бесплатный Nominatim)
geolocator = Nominatim(user_agent="astrology_app_v3", timeout=10)

# Инициализируем определитель таймзон
tf = TimezoneFinder()

# Кэш для геокодинга (упрощенный in-memory кэш)
_geocode_cache = {}
_reverse_geocode_cache = {}
_cache_ttl = 3600  # 1 час

# Кэш для анализа натальной карты (защита от повторных LLM вызовов)
_analysis_cache = {}  # key: "birth_date|birth_place" -> (result_dict, timestamp)
_ANALYSIS_CACHE_TTL = 300  # 5 минут
_ANALYSIS_CACHE_MAX_SIZE = 1000  # макс 1000 записей

def get_coordinates(place: str) -> tuple:
    """
    Получить точные координаты из названия места для астрологических расчетов
    
    Для астрологии критически важна точность координат.
    Возвращает точные координаты или вызывает исключение.
    """
    cache_key = f"geocode:{place.lower().strip()}"
    
    # Проверяем кэш
    if cache_key in _geocode_cache:
        cached_data, timestamp = _geocode_cache[cache_key]
        if time.time() - timestamp < _cache_ttl:
            return cached_data
    
    # Список провайдеров геокодинга (резервные на случай недоступности)
    providers = [
        # Основной - Nominatim (OpenStreetMap)
        lambda p: geolocator.geocode(p, timeout=8, language='ru', exactly_one=True),
        # Резервный поиск на английском
        lambda p: geolocator.geocode(p, timeout=8, language='en', exactly_one=True),
        # Поиск с viewbox для улучшения точности (Европа)
        lambda p: geolocator.geocode(p, timeout=8, viewbox=[-10, 35, 40, 70], bounded=False),
        # Поиск с viewbox (Азия)
        lambda p: geolocator.geocode(p, timeout=8, viewbox=[60, 10, 150, 60], bounded=False),
        # Поиск с viewbox (Америка)
        lambda p: geolocator.geocode(p, timeout=8, viewbox=[-130, 10, -60, 60], bounded=False),
    ]
    
    last_error = None
    
    for i, geocode_func in enumerate(providers):
        try:
            location = geocode_func(place)
            if location:
                lat, lon = location.latitude, location.longitude
                
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    raise ValueError(f"Invalid coordinates: ({lat}, {lon})")
                
                result = (lat, lon)
                _geocode_cache[cache_key] = (result, time.time())
                
                print(f"Geocode success for '{place}': ({lat:.6f}, {lon:.6f}) via provider {i}")
                return result
                
        except (GeocoderTimedOut, GeocoderUnavailable) as e:
            last_error = f"Provider {i} timeout: {e}"
            print(f"Geocoding provider {i} failed for '{place}': {e}")
            continue
        except Exception as e:
            last_error = f"Provider {i} error: {e}"
            print(f"Geocoding provider {i} error for '{place}': {e}")
            continue
    
    error_msg = f"Cannot geocode location: '{place}'. Last error: {last_error}"
    print(f"❌ CRITICAL: {error_msg}")
    raise ValueError(error_msg)


def reverse_geocode(lat: float, lon: float) -> Dict[str, Any]:
    """Обратное геокодирование: координаты -> информация о месте"""
    cache_key = f"reverse:{lat:.4f}:{lon:.4f}"
    
    # Проверяем кэш
    if cache_key in _reverse_geocode_cache:
        cached_data, timestamp = _reverse_geocode_cache[cache_key]
        if time.time() - timestamp < _cache_ttl:
            return cached_data
    
    try:
        location = geolocator.reverse(f"{lat}, {lon}", timeout=10, language='ru')
        if location:
            address = location.address
            
            # Парсим адрес для получения компонентов
            address_parts = address.split(', ')
            city = address_parts[0] if len(address_parts) > 0 else ""
            region = address_parts[1] if len(address_parts) > 1 else ""
            country = address_parts[-1] if len(address_parts) > 1 else ""
            
            # Определяем таймзону
            timezone_str = get_timezone(lat, lon)
            
            result = {
                "address": address,
                "city": city,
                "region": region,
                "country": country,
                "timezone": timezone_str,
                "latitude": lat,
                "longitude": lon
            }
            
            # Сохраняем в кэш
            _reverse_geocode_cache[cache_key] = (result, time.time())
            return result
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        print(f"Reverse geocoding timeout/unavailable for ({lat}, {lon}): {e}")
    except Exception as e:
        print(f"Reverse geocoding error for ({lat}, {lon}): {e}")
    
    # Fallback
    return {
        "address": f"{lat}, {lon}",
        "city": "",
        "region": "",
        "country": "",
        "timezone": get_timezone(lat, lon) or "UTC",
        "latitude": lat,
        "longitude": lon
    }

def get_timezone(lat: float, lon: float) -> Optional[str]:
    """Определить таймзону по координатам"""
    try:
        timezone_str = tf.timezone_at(lat=lat, lng=lon)
        if timezone_str:
            return timezone_str
        
        # Если не нашли точную, пробуем nearby
        timezone_str = tf.closest_timezone_at(lat=lat, lng=lon)
        return timezone_str or "UTC"
    except Exception as e:
        print(f"Timezone detection error for ({lat}, {lon}): {e}")
        return "UTC"

def autocomplete_place(query: str, lang: Optional[str] = None) -> List[Dict[str, Any]]:
    """Возвращает список мест для автодополнения с улучшенным форматированием и поиском"""
    if len(query) < 2:
        return []
    
    # Определить язык если не передан
    if lang is None:
        if any('\u0400' <= c <= '\u04FF' for c in query):
            lang = 'ru'
        else:
            lang = 'en'
    
    try:
        locations = geolocator.geocode(query, exactly_one=False, limit=10, language=lang)
        
        if not locations:
            return []
        
        # Сортируем по релевантности (крупные города сначала)
        def location_score(loc):
            address = loc.address.lower()
            query_lower = query.lower()
            if address.startswith(query_lower):
                return 10
            return 1
        
        sorted_locations = sorted(locations, key=location_score, reverse=True)
        
        results = []
        for loc in sorted_locations[:10]:
            address = loc.address
            address_parts = address.split(', ')
            
            if len(address_parts) >= 2:
                display_name = f"{address_parts[0]}, {address_parts[1]}"
            else:
                display_name = address_parts[0]
            
            timezone_str = get_timezone(loc.latitude, loc.longitude)
            
            place_type = "city"
            address_lower = address.lower()
            if any(word in address_lower for word in ['деревня', 'село', 'поселок', 'village', 'town']):
                place_type = "village"
            elif any(word in address_lower for word in ['область', 'регион', 'район', 'region', 'district']):
                place_type = "region"
            
            results.append({
                "name": address,
                "display_name": display_name,
                "address": address,
                "lat": loc.latitude,
                "lon": loc.longitude,
                "latitude": loc.latitude,
                "longitude": loc.longitude,
                "timezone": timezone_str,
                "type": place_type,
                "country": address_parts[-1] if address_parts else ""
            })
        
        return results
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        print(f"Autocomplete timeout/unavailable for '{query}': {e}")
        return []
    except Exception as e:
        print(f"Autocomplete error for '{query}': {e}")
        return []

router = APIRouter()

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
from app.models.models import User, NatalChart, ChartInterpretation, Book, FullChartAnalysis
from app.schemas.schemas import (
    UserCreate, UserResponse, NatalChartCreate, NatalChartResponse,
    InterpretationCreate, InterpretationResponse, BookCreate, BookResponse,
    QueryRequest, SynastryRequest, NatalChartRequest, NatalChartResponseFull,
    TransitRequest, SynastryRequestDirect, AnalysisRequest, AnalysisResponse,
    ParsedQuery, RelevantChunk
)
from app.schemas.analysis import (PlanetAnalysisRequest, PlanetAnalysisResponse, FullAnalysisRequest, ChatRequest, ChatResponse, SummaryRequest, SummaryResponse, SynastryAspectRequest, SynastryAspectResponse, SynastryRelationshipRequest)
from app.utils.astrology_v2 import (
    calculate_planet_positions, calculate_aspects,
    calculate_solar_return, calculate_synastry,
    PLANETS, ASPECTS, ASPECTS_RU, ORBS, get_zodiac_sign, get_zodiac_degree
)
from app.swephelper import swe
import json
from app.services.synastry_service import analyze_synastry_aspect

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
    
    # ТОЧНОЕ геокодирование для астрологических расчетов
    try:
        lat, lon = get_coordinates(user.birth_place)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot determine coordinates for user location: '{user.birth_place}'. "
                   f"Please update user profile with valid city name. Error: {str(e)}"
        )
    
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


@router.post("/books/import")
async def import_book(
    file_path: str,
    title: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Import a book from file system.
    Parses PDF/EPUB/DOCX/TXT, chunks into 500-word pieces with 50-word overlap,
    and saves to database.
    """
    from app.services.book_parser import parse_file
    from app.services.chunker import chunk_text
    
    parsed = parse_file(file_path)
    
    book = Book(
        title=title,
        content=parsed["text"],
        language=parsed["language"],
        format=parsed["format"],
        created_at=datetime.utcnow()
    )
    db.add(book)
    await db.flush()
    
    chunks = chunk_text(parsed["text"], chunk_size=500, overlap=50)
    
    for idx, chunk in enumerate(chunks):
        book_chunk = BookChunk(
            book_id=book.id,
            chunk_index=idx,
            text=chunk["text"],
            word_count=chunk["word_count"]
        )
        db.add(book_chunk)
    
    await db.commit()
    await db.refresh(book)
    
    return {"id": book.id, "title": book.title, "chunks_count": len(chunks)}


@router.post("/books/process")
async def process_book_api(
    filename: str,
    db: AsyncSession = Depends(get_db)
):
    """Обработать книгу: скачать из Supabase -> парсить -> нарезать на чанки -> сохранить в БД"""
    from app.services.book_processor import process_book_async
    result = await process_book_async(filename)
    return result


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
# GEOCODE SERVICES
# ============================================

@router.get("/geocode/coordinates")
async def geocode_coordinates(lat: float, lon: float):
    """
    Получить информацию о месте по координатам
    
    Возвращает адрес, город, страну и таймзону для заданных координат
    """
    result = reverse_geocode(lat, lon)
    return result

@router.get("/geocode/autocomplete")
async def geocode_autocomplete(q: str, lang: Optional[str] = None):
    """
    Автодополнение для ввода города
    
    Возвращает список возможных городов по введённому тексту
    Поддерживает параметр lang для принудительного указания языка ('ru', 'en')
    Если язык не указан - определяется автоматически по входному тексту
    """
    results = autocomplete_place(q, lang)
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
    - birth_place: Название места (точное название города/места)
    - timezone: Временная зона (IANA, например "Europe/Moscow")
    - house_system: Система домов (Placidus, Equal, WholeSign, etc.)
    """
    # Validate input before processing
    if not request.birth_place or request.birth_place.strip() == '':
        if request.latitude is None or request.longitude is None:
            raise HTTPException(
                status_code=400,
                detail="Either 'birth_place' or both 'latitude' and 'longitude' must be provided. "
                       "Please enter a valid birth location."
            )
    
    # Получаем ТОЧНЫЕ координаты из названия места
    # Для астрологии критически важна точность - нет fallback на Москву!
    # Используем переданные координаты или определяем сами
    if request.latitude is not None and request.longitude is not None:
        lat, lon = request.latitude, request.longitude
    else:
        try:
            lat, lon = get_coordinates(request.birth_place)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine coordinates for location: '{request.birth_place}'. "
                       f"Please enter a valid city name (e.g., 'Moscow, Russia', 'New York, USA'). "
                       f"Error: {str(e)}"
            )
    
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



# ============================================
# SYNASTRY (Direct calculation)
# ============================================

@router.post("/synastry/direct")
async def calculate_synastry_direct(request: SynastryRequestDirect):
    """
    Прямой расчёт синастрии между двумя картами
    """
    # Получаем ТОЧНЫЕ координаты для первой карты
    # Используем переданные координаты или определяем сами
    if request.chart1.latitude is not None and request.chart1.longitude is not None:
        lat1, lon1 = request.chart1.latitude, request.chart1.longitude
    else:
        try:
            lat1, lon1 = get_coordinates(request.chart1.birth_place)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine coordinates for first location: '{request.chart1.birth_place}'. "
                       f"Please enter a valid city name. Error: {str(e)}"
            )
    
    # Calculate first chart
    chart1 = calculate_planet_positions(
        birth_date=request.chart1.birth_date,
        birth_place=request.chart1.birth_place,
        lat=lat1,
        lon=lon1,
        timezone_str=request.chart1.timezone,
    )
    
    # Получаем ТОЧНЫЕ координаты для второй карты
    # Используем переданные координаты или определяем сами
    if request.chart2.latitude is not None and request.chart2.longitude is not None:
        lat2, lon2 = request.chart2.latitude, request.chart2.longitude
    else:
        try:
            lat2, lon2 = get_coordinates(request.chart2.birth_place)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine coordinates for second location: '{request.chart2.birth_place}'. "
                       f"Please enter a valid city name. Error: {str(e)}"
            )
    
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
    
    # House overlays: planets from one chart in houses of the other
    planets_1_in_houses_2 = {}
    for p_name, p_data in chart1['planets'].items():
        house = get_house_for_longitude(p_data['full_degree'], chart2['houses'])
        if house:
            planets_1_in_houses_2[p_name] = house

    planets_2_in_houses_1 = {}
    for p_name, p_data in chart2['planets'].items():
        house = get_house_for_longitude(p_data['full_degree'], chart1['houses'])
        if house:
            planets_2_in_houses_1[p_name] = house

    return {
        'chart1': {
            'sun_sign': chart1['sun_sign'],
            'moon_sign': chart1['moon_sign'],
            'ascendant': chart1['ascendant'],
            'planets': chart1['planets'],
             'houses': {str(k): v for k, v in chart1['houses'].items()},
            'meta': chart1.get('meta', {}),
        },
        'chart2': {
            'sun_sign': chart2['sun_sign'],
            'moon_sign': chart2['moon_sign'],
            'ascendant': chart2['ascendant'],
            'planets': chart2['planets'],
             'houses': {str(k): v for k, v in chart2['houses'].items()},
            'meta': chart2.get('meta', {}),
        },
        'aspects': aspects,
        'total_aspects': len(aspects),
        'overlays': {
            'planets_1_in_houses_2': planets_1_in_houses_2,
            'planets_2_in_houses_1': planets_2_in_houses_1,
        }
    }


@router.post("/synastry/aspect", response_model=SynastryAspectResponse)
@limiter.limit("15/minute")
async def analyze_synastry_aspect_endpoint(request: Request, payload: SynastryAspectRequest, user = Depends(get_current_user)):
    """
    Analyze a specific synastry aspect between two planets
    """
    return await analyze_synastry_aspect(
        planet1=payload.planet1,
        planet2=payload.planet2,
        aspect_name=payload.aspect_name,
        aspect_name_ru=payload.aspect_name_ru,
        orb=payload.orb,
        language=payload.language,
        top_k=20,
        mode=payload.mode
    )


@router.post("/analysis/query")
@limiter.limit("10/minute")
async def analyze_query(request: Request, payload: AnalysisRequest, user = Depends(get_current_user)) -> AnalysisResponse:
    """
    Поиск и анализ астрологического запроса
    
    Основной endpoint для:
    1. Поиска релевантных кусков из книг по запросу
    2. Построения натальной карты (если переданы данные)
    3. Анализа через LLM с использованием контекста карты
    
    Request:
    - query: str (например "Сатурн 7 дом" или "Saturn 7th house")
    - chart_data: Optional[NatalChartRequest] - данные для построения карты
    - top_k: int = 5 - количество чанков для анализа
    
    Response:
    - query: исходный запрос
    - query_language: определённый язык
    - parsed_query: извлечённые астрологические сущности
    - chart_data: рассчитанная натальная карта (если передана)
    - relevant_chunks: найденные куски с similarity score
    - analysis: результат анализа от LLM
    """
    from app.services.search_service import parse_astrology_query
    from app.services.analysis_service import analyze_astrology_query
    
    result = await analyze_astrology_query(
        query=payload.query,
        chart_data=None,
        top_k=payload.top_k
    )
    
    return {
        'query': result['query'],
        'query_language': result['query_language'],
        'parsed_query': result['parsed_query'],
        'chart_data': result.get('chart_data'),
        'relevant_chunks': result['relevant_chunks'],
        'analysis': result['analysis'],
    }


@router.post("/analysis/query-with-chart")
@limiter.limit("10/minute")
async def analyze_query_with_chart(request: Request, payload: AnalysisRequest, user = Depends(get_current_user)) -> AnalysisResponse:
    """
    Поиск и анализ астрологического запроса С натальной картой
    
    То же что /analysis/query, но с расчётом натальной карты
    на основе переданных данных рождения
    """
    from app.services.analysis_service import analyze_astrology_query
    
    chart_data = None
    
    if payload.chart_data:
        birth_request = payload.chart_data
        
        if birth_request.latitude is not None and birth_request.longitude is not None:
            lat, lon = birth_request.latitude, birth_request.longitude
        else:
            try:
                lat, lon = get_coordinates(birth_request.birth_place)
            except ValueError as e:
                lat, lon = None, None
        
        if lat and lon:
            birth_datetime = birth_request.birth_date
            if birth_request.birth_time:
                try:
                    time_parts = birth_request.birth_time.split(':')
                    hour = int(time_parts[0])
                    minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                    from datetime import time
                    birth_datetime = birth_datetime.replace(hour=hour, minute=minute)
                except:
                    pass
            
            if birth_request.timezone:
                try:
                    from zoneinfo import ZoneInfo
                    tz = ZoneInfo(birth_request.timezone)
                    if birth_datetime.tzinfo is None:
                        birth_datetime = birth_datetime.replace(tzinfo=tz)
                except:
                    pass
            
            chart = calculate_planet_positions(
                birth_date=birth_datetime,
                birth_place=birth_request.birth_place,
                lat=lat,
                lon=lon,
                timezone_str=birth_request.timezone,
                house_system=birth_request.house_system or 'Placidus'
            )
            
            aspects = calculate_aspects(chart['planets'])
            
            chart_data = {
                'sun_sign': chart['sun_sign'],
                'sun_sign_ru': chart['sun_sign_ru'],
                'moon_sign': chart['moon_sign'],
                'moon_sign_ru': chart['moon_sign_ru'],
                'ascendant': chart['ascendant'],
                'ascendant_ru': chart['ascendant_ru'],
                'mc': chart['mc'],
                'mc_ru': chart['mc_ru'],
                'planets': chart['planets'],
                'houses': {str(k): v for k, v in chart['houses'].items()},
                'houses_meta': chart.get('houses_meta', {}),
                'meta': chart.get('meta', {}),
                'aspects': aspects,
            }
    
    result = await analyze_astrology_query(
        query=payload.query,
        chart_data=chart_data,
        top_k=payload.top_k
    )
    
    return {
        'query': result['query'],
        'query_language': result['query_language'],
        'parsed_query': result['parsed_query'],
        'chart_data': result.get('chart_data'),
        'relevant_chunks': result['relevant_chunks'],
        'analysis': result['analysis'],
    }


@router.post("/analysis/planet")
@limiter.limit("10/minute")
async def analyze_planet_endpoint(
    request: Request,
    payload: PlanetAnalysisRequest,
    user = Depends(get_current_user)
) -> PlanetAnalysisResponse:
    """
    Анализ одной планеты по клику/hover
    """
    from app.services.analysis_service import analyze_planet
    
    # Узлы всегда ретроградны — хардкод до любой логики
    if payload.planet in ('NorthNode', 'North Node', 'SouthNode', 'South Node'):
        is_retrograde = True
    else:
        is_retrograde = payload.is_retrograde
        if not is_retrograde and payload.chart_data:
            planets_data = payload.chart_data.get('planets', {})
            planet_key = payload.planet.replace(' ', '')
            planet_data = planets_data.get(planet_key) or planets_data.get(payload.planet, {})
            is_retrograde = planet_data.get('is_retrograde', False)
    
    result = await analyze_planet(
        planet=payload.planet,
        sign=payload.sign,
        degree=payload.degree,
        house=payload.house or 1,
        house_sign=payload.house_sign,
        is_retrograde=is_retrograde or False,
        aspects=payload.aspects,
        language=payload.language,
        top_k=20,
        mode=payload.mode
    )
    
    return result


@router.post("/analysis/full")
async def full_chart_analysis_endpoint(request: FullAnalysisRequest, db: AsyncSession = Depends(get_db)):
    """
    Полный анализ натальной карты на основе всех книг (10+ страниц)
    
    Защита от повторных LLM вызовов:
    - Ключ = birth_date + birth_place
    - Кэш действует 5 минут
    """
    from app.services.analysis_service import full_chart_analysis_v2 as do_full_analysis
    from datetime import datetime
    
    # === ПРОВЕРКА КЭША ===
    # cache_key = f"{request.birth_date}|{request.birth_place}"
    cache_key = f"{request.birth_date}|{request.birth_place}|{request.mode}"

#     # СТАЛО:
# cache_key = None  # временно отключить кэш
    
    if cache_key in _analysis_cache:
        cached_result, timestamp = _analysis_cache[cache_key]
        if time.time() - timestamp < _ANALYSIS_CACHE_TTL:
            # Кэш свежий! Возвращаем БЕЗ LLM вызова!
            print(f"[CACHE] Returning cached analysis for {cache_key}")
            return {
                **cached_result,
                "from_cache": True,
                "cached_at": datetime.fromtimestamp(timestamp).isoformat()
            }
        else:
            # Кэш истёк - удаляем
            del _analysis_cache[cache_key]
    
    chart_data = None
    
    if request.chart_data:
        chart_data = request.chart_data
    elif request.birth_date:
        if request.latitude is not None and request.longitude is not None:
            lat, lon = request.latitude, request.longitude
        else:
            try:
                lat, lon = get_coordinates(request.birth_place)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=f"Cannot determine coordinates: {str(e)}")
        
        birth_datetime = request.birth_date
        if request.birth_time:
            try:
                time_parts = request.birth_time.split(':')
                hour = int(time_parts[0])
                minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                birth_datetime = birth_datetime.replace(hour=hour, minute=minute)
            except:
                pass
        
        if request.timezone:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(request.timezone)
                if birth_datetime.tzinfo is None:
                    birth_datetime = birth_datetime.replace(tzinfo=tz)
            except:
                pass
        
        chart = calculate_planet_positions(
            birth_date=birth_datetime,
            birth_place=request.birth_place,
            lat=lat,
            lon=lon,
            timezone_str=request.timezone,
            house_system=request.house_system or 'Placidus'
        )
        
        aspects = calculate_aspects(chart['planets'])
        
        chart_data = {
            'sun_sign': chart['sun_sign'],
            'sun_sign_ru': chart['sun_sign_ru'],
            'moon_sign': chart['moon_sign'],
            'moon_sign_ru': chart['moon_sign_ru'],
            'ascendant': chart['ascendant'],
            'ascendant_ru': chart['ascendant_ru'],
            'mc': chart['mc'],
            'mc_ru': chart['mc_ru'],
            'planets': chart['planets'],
            'houses': {str(k): v for k, v in chart['houses'].items()},
            'houses_meta': chart.get('houses_meta', {}),
            'meta': chart.get('meta', {}),
            'aspects': aspects,
        }
    
    if not chart_data:
        raise HTTPException(status_code=400, detail="Either chart_data or birth_date must be provided")
    
    result = await do_full_analysis(chart_data=chart_data, language=request.language,  mode=request.mode)
    
    # === СОХРАНЯЕМ В БД ===
    try:
        db_analysis = FullChartAnalysis(
            user_id=None,  # TODO: получить из аутентификации
            full_analysis=result['analysis'],
            summary=result.get('summary', ''),
            book_analyses=result.get('book_analyses', []),
            chart_data=json.dumps(chart_data),
            language=result.get('language', 'ru'),
            created_at=datetime.utcnow()
        )
        db.add(db_analysis)
        await db.commit()
        await db.refresh(db_analysis)
    except Exception as e:
        print(f"Error saving analysis to DB: {e}")
    
    # === СОХРАНЯЕМ В КЭШ ===
    # Очищаем старые записи если кэш полный
    if len(_analysis_cache) >= _ANALYSIS_CACHE_MAX_SIZE:
        oldest_key = next(iter(_analysis_cache))
        del _analysis_cache[oldest_key]
    
    _analysis_cache[cache_key] = (result, time.time())
    print(f"[CACHE] Saved analysis to cache: {cache_key}")
    
    return {
        'analysis': result['analysis'],
        'summary': result.get('summary', ''),
        'book_analyses': result['book_analyses'],
        'chart_summary': result['chart_summary'],
        'language': result['language'],
        'created_at': datetime.utcnow().isoformat()
    }


@router.post("/generate-summary", response_model=SummaryResponse)
async def generate_summary_endpoint(request: SummaryRequest):
    """
    Generate a short summary from the provided text.
    This endpoint is used by the frontend to create summaries of analysis.
    """
    from app.services.analysis_service import generate_summary
    
    summary = await generate_summary(request.text, request.language)
    
    return {"summary": summary}


@router.post("/analysis/chat")
@limiter.limit("20/minute")
async def chat_with_astrologer_endpoint(request: Request, payload: ChatRequest, user = Depends(get_current_user)) -> ChatResponse:
    """
    Чат с персональным астрологом-агентом.
    - Гибридный RAG: поиск по книгам по вопросу + по планетам
    - Учитывает историю диалога
    - Отвечает в контексте натальной карты и полного анализа
    """
    # from app.services.analysis_service import chat_with_astrologer
 
    # result = await chat_with_astrologer(
    #     question=payload.question,
    #     chart_data=payload.chart_data,
    #     full_analysis=payload.summary,
    #     chat_history=[msg.dict() for msg in payload.chat_history],
    #     language=payload.language
    # )

    if payload.chart_data.get('type') == 'synastry':
        from app.services.synastry_service import chat_with_synastry_astrologer
        result = await chat_with_synastry_astrologer(
            question=payload.question,
            chart_data=payload.chart_data,
            full_analysis=payload.summary,
            chat_history=[msg.dict() for msg in payload.chat_history],
            language=payload.language,
            relationship_context=payload.relationship_context
        )
    else:
        from app.services.analysis_service import chat_with_astrologer
        result = await chat_with_astrologer(
            question=payload.question,
            chart_data=payload.chart_data,
            full_analysis=payload.summary,
            chat_history=[msg.dict() for msg in payload.chat_history],
            language=payload.language
        )
 
    return ChatResponse(
        answer=result["answer"],
        relevant_chunks=result["relevant_chunks"]
    )


@router.post("/analysis/synastry/full")
@limiter.limit("5/minute")
async def full_synastry_analysis_endpoint(request: Request, payload: SynastryAnalysisRequest, user = Depends(get_current_user)):
    """
    Полный глубокий анализ синастрии (гибридный метод v2)
    
    Требует:
    - chart1: данные первой карты (birth_date, birth_place, и т.д.)
    - chart2: данные второй карты
    - language: язык анализа (ru/en)
    
    Возвращает полный анализ синастрии (10000+ слов),
    используя гибридный поиск по всем книгам для каждого аспекта.
    """
    from app.services.synastry_service import full_synastry_analysis_v2
    from app.utils.astrology_v2 import calculate_planet_positions, calculate_aspects
    from datetime import datetime
    
    # Функция для расчёта карты
    async def calculate_chart(chart_req, chart_num: int):
        # Получаем координаты
        if chart_req.latitude is not None and chart_req.longitude is not None:
            lat, lon = chart_req.latitude, chart_req.longitude
        else:
            try:
                lat, lon = get_coordinates(chart_req.birth_place)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot determine coordinates for chart {chart_num}: {str(e)}"
                )
        
        # Парсим время рождения
        birth_datetime = chart_req.birth_date
        if chart_req.birth_time:
            try:
                time_parts = chart_req.birth_time.split(':')
                hour = int(time_parts[0])
                minute = int(time_parts[1]) if len(time_parts) > 1 else 0
                second = int(time_parts[2]) if len(time_parts) > 2 else 0
                birth_datetime = birth_datetime.replace(hour=hour, minute=minute, second=second)
            except:
                pass
        
        # Применяем таймзону
        if chart_req.timezone:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(chart_req.timezone)
                if birth_datetime.tzinfo is None:
                    birth_datetime = birth_datetime.replace(tzinfo=tz)
            except:
                pass
        
        # Рассчитываем карту
        chart = calculate_planet_positions(
            birth_date=birth_datetime,
            birth_place=chart_req.birth_place,
            lat=lat,
            lon=lon,
            timezone_str=chart_req.timezone,
            house_system=chart_req.house_system or 'Placidus'
        )
        
        # Добавляем аспекты
        aspects = calculate_aspects(chart['planets'])
        chart['aspects'] = aspects
        
        return chart
    
    # Рассчитываем обе карты
    chart1_data = await calculate_chart(payload.chart1, 1)
    chart2_data = await calculate_chart(payload.chart2, 2)
    
    # Определяем язык
    language = payload.language or "ru"
    
    # Выполняем полный анализ синастрии
    result = await full_synastry_analysis_v2(
        chart1_data=chart1_data,
        chart2_data=chart2_data,
        aspects=calculate_synastry(chart1_data, chart2_data).get('aspects', []),
        overlays=payload.overlays,
        language=language,
        top_k_per_book=payload.top_k_per_book,
        mode=payload.mode,
        relationship_context=payload.relationship_context
    )
    
    return result


@router.post("/synastry/relationship-types")
@limiter.limit("10/minute")
async def analyze_relationship_types_endpoint(request: Request, payload: SynastryRelationshipRequest, user = Depends(get_current_user)):
    """
    Определить типы отношений в синастрии (с поддержкой стриминга)
    
    Принимает готовый полный анализ синастрии
    и возвращает проценты для каждого типа отношений.
    """
    from app.services.synastry_relationship_service import (
        analyze_relationship_types,
        stream_relationship_types
    )
    from fastapi.responses import StreamingResponse
    
    if payload.stream:
        return StreamingResponse(
            stream_relationship_types(
                full_analysis=payload.full_analysis,
                language=payload.language
            ),
            media_type="text/plain"
        )
    
    result = await analyze_relationship_types(
        full_analysis=payload.full_analysis,
        language=payload.language
    )
    
    return result


# ============================================
# SECONDARY PROGRESSIONS (Вторичные прогрессии)
# Доступ только для авторизованных пользователей —
# фича привязана к СОХРАНЁННЫМ картам (как чат)
# ============================================

def _prepare_birth_datetime(birth_date, birth_time: Optional[str], tz_str: Optional[str]):
    """Единая подготовка даты рождения (время + таймзона) — без дублирования кода"""
    birth_datetime = birth_date
    if birth_time:
        try:
            time_parts = birth_time.split(':')
            hour = int(time_parts[0])
            minute = int(time_parts[1]) if len(time_parts) > 1 else 0
            second = int(time_parts[2]) if len(time_parts) > 2 else 0
            birth_datetime = birth_datetime.replace(hour=hour, minute=minute, second=second)
        except Exception:
            pass
    if tz_str:
        try:
            from zoneinfo import ZoneInfo
            if birth_datetime.tzinfo is None:
                birth_datetime = birth_datetime.replace(tzinfo=ZoneInfo(tz_str))
        except Exception as e:
            print(f"Timezone error: {e}")
    return birth_datetime


def _resolve_coordinates(latitude: Optional[float], longitude: Optional[float], birth_place: Optional[str]):
    """Координаты: переданные или геокодинг по названию места"""
    if latitude is not None and longitude is not None:
        return latitude, longitude
    if not birth_place or not birth_place.strip():
        raise HTTPException(
            status_code=400,
            detail="Either 'birth_place' or both 'latitude' and 'longitude' must be provided."
        )
    try:
        return get_coordinates(birth_place)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot determine coordinates for location: '{birth_place}'. Error: {str(e)}"
        )


def _resolve_transit_coordinates(
    transit_lat: Optional[float],
    transit_lon: Optional[float],
    transit_place: Optional[str],
    natal_lat: Optional[float] = None,
    natal_lon: Optional[float] = None
) -> tuple:
    """Координаты места транзита: переданные или геокодинг, иначе — натальные координаты"""
    if transit_lat is not None and transit_lon is not None:
        return transit_lat, transit_lon
    if transit_place and transit_place.strip():
        try:
            return get_coordinates(transit_place)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine coordinates for transit location: '{transit_place}'. Error: {str(e)}"
            )
    # Fallback: используем натальные координаты
    if natal_lat is not None and natal_lon is not None:
        return natal_lat, natal_lon
    raise HTTPException(
        status_code=400,
        detail="Transit location required: provide 'transit_latitude'/'transit_longitude' or 'transit_place'."
    )


@router.post("/progressions")
@limiter.limit("15/minute")
async def calculate_progressions_endpoint(request: Request, payload: ProgressionsRequest, user = Depends(get_current_user)):
    """
    Расчёт вторичных прогрессий («день за год») через Swiss Ephemeris.

    Возвращает прогрессивные планеты (с натальными домами), прогрессивные
    ASC/MC/дома и аспекты прогрессий к натальной карте (орб 1.5°).
    Требует авторизацию — функция доступна только для сохранённых карт.
    """
    lat, lon = _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
    birth_datetime = _prepare_birth_datetime(payload.birth_date, payload.birth_time, payload.timezone)

    try:
        result = calculate_secondary_progressions(
            birth_date=birth_datetime,
            birth_place=payload.birth_place or '',
            target_date=payload.target_date,
            lat=lat,
            lon=lon,
            timezone_str=payload.timezone,
            house_system=payload.house_system or 'Placidus',
        )
    except Exception as e:
        print(f"[progressions] calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"Progressions calculation error: {str(e)}")

    return result


@router.post("/analysis/progressions")
@limiter.limit("5/minute")
async def progressions_analysis_endpoint(request: Request, payload: ProgressionsAnalysisRequest, user = Depends(get_current_user)):
    """
    AI-анализ вторичных прогрессий: RAG-поиск по тем же книгам + LLM
    (шаблон 'progressions', режимы simple/advanced, языки ru/en).

    Защита от повторных LLM-вызовов: in-memory кэш по ключу
    birth_date|birth_place|period|mode|language (TTL как у полного анализа).
    """
    from app.services.analysis_service import progressions_analysis
    from datetime import datetime as dt

    # --- Прогрессии: берём готовые из запроса или считаем на бэкенде ---
    progressions = payload.progression_data
    if not progressions:
        if not payload.birth_date:
            raise HTTPException(status_code=400, detail="Either 'progression_data' or birth data must be provided")
        lat, lon = _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
        birth_datetime = _prepare_birth_datetime(payload.birth_date, payload.birth_time, payload.timezone)
        try:
            progressions = calculate_secondary_progressions(
                birth_date=birth_datetime,
                birth_place=payload.birth_place or '',
                target_date=payload.target_date,
                lat=lat,
                lon=lon,
                timezone_str=payload.timezone,
                house_system=payload.house_system or 'Placidus',
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Progressions calculation error: {str(e)}")

    # --- Натальная карта: из запроса или восстановление из meta прогрессий ---
    natal_chart = payload.natal_chart
    if not natal_chart:
        meta = progressions.get('meta', {})
        if not meta.get('birth_date'):
            raise HTTPException(status_code=400, detail="'natal_chart' is required when it cannot be derived")
        try:
            birth_dt = dt.fromisoformat(meta['birth_date'])
            natal_chart = calculate_planet_positions(
                birth_date=birth_dt,
                birth_place=meta.get('birth_place', ''),
                lat=meta.get('latitude'),
                lon=meta.get('longitude'),
                timezone_str=meta.get('timezone'),
                house_system=meta.get('house_system', 'Placidus'),
            )
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Cannot rebuild natal chart: {str(e)}")

    # --- Кэш (тот же механизм, что у /analysis/full) ---
    meta = progressions.get('meta', {})
    period = progressions.get('period', '')
    cache_key = f"progressions|{meta.get('birth_date')}|{meta.get('birth_place')}|{period}|{payload.mode}|{payload.language}"

    if cache_key in _analysis_cache:
        cached_result, timestamp = _analysis_cache[cache_key]
        if time.time() - timestamp < _ANALYSIS_CACHE_TTL:
            print(f"[CACHE] Returning cached progressions analysis for {cache_key}")
            return {
                **cached_result,
                "from_cache": True,
                "cached_at": dt.fromtimestamp(timestamp).isoformat()
            }
        else:
            del _analysis_cache[cache_key]

    result = await progressions_analysis(
        natal_chart=natal_chart,
        progressions=progressions,
        language=payload.language,
        top_k_per_book=payload.top_k_per_book,
        mode=payload.mode or 'advanced',
    )

    # Прикладываем расчётные данные — фронтенд может показать их без второго запроса
    result["progression_data"] = progressions

    if len(_analysis_cache) < _ANALYSIS_CACHE_MAX_SIZE:
        _analysis_cache[cache_key] = (result, time.time())

    return result


@router.post("/transits")
@limiter.limit("20/minute")
async def calculate_transits_endpoint(request: Request, payload: TransitsRequest, user = Depends(get_current_user)):
    """
    Транзиты на конкретный день (по умолчанию — сегодня; можно любой день
    прошлого или будущего). Реальные позиции планет через Swiss Ephemeris,
    наложенные на натальную карту: натальные дома транзитных
    планет считались по ВЕРНЫМ натальным куспидам, а не по пересчитанным.

    Место транзита (transit_place/latitude/longitude) определяет транзитные дома
    и лунную фазу — важно для корректной интерпретации в текущем месте пребывания.
    Требует авторизацию — доступно только для сохранённых карт.
    """
    lat, lon = _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
    birth_datetime = _prepare_birth_datetime(payload.birth_date, payload.birth_time, payload.timezone)

    # Координаты места транзита (если не указаны — используем натальные)
    transit_lat, transit_lon = _resolve_transit_coordinates(
        payload.transit_latitude, payload.transit_longitude, payload.transit_place, lat, lon
    )

    try:
        result = calculate_transits(
            birth_date=birth_datetime,
            birth_place=payload.birth_place or '',
            target_date=payload.target_date,
            lat=lat,
            lon=lon,
            timezone_str=payload.timezone,
            house_system=payload.house_system or 'Placidus',
            natal_override=payload.natal_chart,
            transit_lat=transit_lat,
            transit_lon=transit_lon,
        )
    except Exception as e:
        print(f"[transits] calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"Transits calculation error: {str(e)}")

    return result


@router.post("/analysis/transits")
@limiter.limit("5/minute")
async def transits_analysis_endpoint(request: Request, payload: TransitsAnalysisRequest, user = Depends(get_current_user)):
    """
    AI-анализ транзитов дня: RAG-поиск по тем же книгам + LLM
    (шаблон 'transits', режимы simple/advanced, языки ru/en).

    Кэш: in-memory по ключу birth_date|birth_place|date|mode|language.

    Место транзита (transit_place/latitude/longitude) определяет транзитные дома
    и лунную фазу — важно для корректной интерпретации в текущем месте пребывания.
    """
    from app.services.analysis_service import transits_analysis
    from datetime import datetime as dt

    # --- Транзиты: берём готовые из запроса или считаем на бэкенде ---
    transits = payload.transit_data
    # Координаты места транзита (будут определены при необходимости)
    transit_lat = payload.transit_latitude
    transit_lon = payload.transit_longitude

    if not transits:
        if not payload.birth_date:
            raise HTTPException(status_code=400, detail="Either 'transit_data' or birth data must be provided")
        lat, lon = _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
        birth_datetime = _prepare_birth_datetime(payload.birth_date, payload.birth_time, payload.timezone)

        # Координаты места транзита (если не указаны — используем натальные)
        transit_lat, transit_lon = _resolve_transit_coordinates(
            payload.transit_latitude, payload.transit_longitude, payload.transit_place, lat, lon
        )

        try:
            transits = calculate_transits(
                birth_date=birth_datetime,
                birth_place=payload.birth_place or '',
                target_date=payload.target_date,
                lat=lat,
                lon=lon,
                timezone_str=payload.timezone,
                house_system=payload.house_system or 'Placidus',
                natal_override=payload.natal_chart,
                transit_lat=transit_lat,
                transit_lon=transit_lon,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transits calculation error: {str(e)}")

    # --- Натальная карта для оверлея ---
    # Берём ГОТОВУЮ натальную карту из chart_data (она пришла с фронта и уже
    # содержит правильные дома — те же, что показывает натальный анализ).
    # НЕ пересчитываем: пересчёт может дать другой ASC и сломать дома.
    natal_chart = payload.natal_chart
    if not natal_chart:
        raise HTTPException(status_code=400, detail="natal_chart is required")

    # --- Кэш (тот же механизм, что у /analysis/progressions) ---
    meta = transits.get('meta', {})
    period = transits.get('period', '')
    transit_loc = f"{payload.transit_latitude},{payload.transit_longitude}" if payload.transit_latitude else "natal"
    cache_key = f"transits|{meta.get('birth_date')}|{meta.get('birth_place')}|{period}|{payload.mode}|{payload.language}|{transit_loc}"

    if cache_key in _analysis_cache:
        cached_result, timestamp = _analysis_cache[cache_key]
        if time.time() - timestamp < _ANALYSIS_CACHE_TTL:
            print(f"[CACHE] Returning cached transits analysis for {cache_key}")
            return {
                **cached_result,
                "from_cache": True,
                "cached_at": dt.fromtimestamp(timestamp).isoformat()
            }
        else:
            del _analysis_cache[cache_key]

    result = await transits_analysis(
        natal_chart=natal_chart,
        transits=transits,
        language=payload.language,
        top_k_per_book=payload.top_k_per_book,
        mode=payload.mode or 'advanced',
        transit_place=payload.transit_place,
        transit_lat=transit_lat,
        transit_lon=transit_lon,
    )

    # Прикладываем расчётные данные — фронтенд может показать их без второго запроса
    result["transit_data"] = transits

    _analysis_cache[cache_key] = (result, time.time())
    return result


@router.post("/daily-forecast")
@limiter.limit("5/minute")
async def daily_forecast_endpoint(request: Request, payload: DailyForecastRequest, user = Depends(get_current_user)):
    """
    Прогноз дня матча: ГИБРИДНЫЙ метод на основе КАРТЫ СОБЫТИЯ (Frawley, Sports
    Astrology, гл. 2) + классических достоинств значителей 1/7 (см.
    plans/daily-forecast-hybrid-method.md — сознательное отступление от
    прямого запрета книги смешивать методы, по итогам эмпирических тестов).
    ВХОД: только время (target_date, местное; transit_timezone) и место
    (transit_place или transit_latitude/longitude) начала матча.
    Натальные данные НЕ нужны (natal_chart опционален — лишь личная сноска для LLM).
    Карта на время+место матча (Placidus): Lords 1/10 = фаворит, Lords 7/4 = соперник;
    свидетельства гл.2 — положения у куспидов (2-3°), финальный аспект Луны, антисция
    Фортуны, диспозитор Фортуны, узлы, комбустия 2°, Плутон/Уран/Сатурн;
    гибридные свидетельства (только Lord 1/7) — эссенциальное достоинство,
    угловатость собственного дома, ретроградность.
    Ответ: favorite/opponent (по 3 предложения) + verdict + significator_card
    (детерминированная карточка значителей 1/7). Числовая оценка (score/
    category) НЕ выводится — только качественный вердикт (match_type).
    LLM выбирается с фронта (llm_provider/llm_model, включая OpenRouter).
    Спека: app/services/specs/daily_forecast_event_chart_plan.md
    """
    from app.services.daily_forecast_service import daily_forecast_analysis
    from datetime import datetime as dt

    # БАГ 1 FIX: время транзита введено как МЕСТНОЕ время места транзита.
    # Локализуем naive datetime по таймзоне места транзита (fallback — натальная);
    # дальше _datetime_to_utc_jd корректно конвертирует aware datetime в UTC.
    # Иначе "14:00 Торонто" и "14:00 Барселона" дали бы одинаковые позиции планет.
    target_date = payload.target_date
    if target_date is not None and target_date.tzinfo is None:
        tz_name = payload.transit_timezone or payload.timezone
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                target_date = target_date.replace(tzinfo=ZoneInfo(tz_name))
            except Exception as e:
                print(f"[daily-forecast] transit timezone error: {e}")

    # --- Транзиты: готовые из запроса или считаем (тот же путь, что /analysis/transits) ---
    transits = payload.transit_data
    transit_lat = payload.transit_latitude
    transit_lon = payload.transit_longitude

    # ФРОУЛИ (Sports Astrology, гл. 2, «The Method»): карта СОБЫТИЯ судится
    # по Плацидусу — «Use Placidus houses, as with any event chart».
    # Региомонтан — только для хорарных ВОПРОСОВ (гл. 1), это другой метод.
    effective_house_system = payload.house_system or 'Placidus'

    # КАРТА СОБЫТИЯ (Frawley гл. 2): строится ТОЛЬКО на время (target_date)
    # и место (transit_place / transit_latitude+longitude) начала матча.
    # Натальные / birth_* данные в этом методе НЕ используются.
    if not transits:
        if target_date is None:
            raise HTTPException(status_code=400, detail="Either 'transit_data' or 'target_date' (event kick-off time) must be provided")
        transit_lat, transit_lon = _resolve_transit_coordinates(
            payload.transit_latitude, payload.transit_longitude, payload.transit_place
        )
        try:
            transits = calculate_transits(
                # calculate_transits — общая функция; передаём ей момент матча,
                # получаем чистую карту события (transit_planets + transit_houses)
                birth_date=target_date,
                birth_place=payload.transit_place or '',
                target_date=target_date,
                lat=transit_lat,
                lon=transit_lon,
                timezone_str=payload.transit_timezone or payload.timezone,
                house_system=effective_house_system,  # ФРОУЛИ: Placidus для карты события (гл. 2)
                transit_lat=transit_lat,
                transit_lon=transit_lon,
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transits calculation error: {str(e)}")

    # natal_chart больше не обязателен: он шёл только в натальную сноску (личный
    # акцент для LLM) и на расчёт/скоринг карты события не влияет.
    natal_chart = payload.natal_chart or {}

    # --- Кэш (тот же механизм, что /analysis/transits; ключ включает модель) ---
    meta = transits.get('meta', {})
    period = transits.get('period', '')
    transit_loc = f"{transit_lat},{transit_lon}" if transit_lat is not None else "natal"
    target_time = target_date.isoformat() if target_date else ''
    cache_key = (
        f"daily|{meta.get('birth_date')}|{meta.get('birth_place')}|{period}|{target_time}"
        f"|{payload.language}|{transit_loc}|{payload.llm_provider}|{payload.llm_model}|{effective_house_system}"
    )

    if cache_key in _analysis_cache:
        cached_result, timestamp = _analysis_cache[cache_key]
        if time.time() - timestamp < _ANALYSIS_CACHE_TTL:
            print(f"[CACHE] Returning cached daily forecast for {cache_key}")
            return {
                **cached_result,
                "from_cache": True,
                "cached_at": dt.fromtimestamp(timestamp).isoformat()
            }
        else:
            del _analysis_cache[cache_key]

    result = await daily_forecast_analysis(
        natal_chart=natal_chart,
        transits=transits,
        language=payload.language,
        provider=payload.llm_provider,
        model=payload.llm_model,
        moon_range_degrees=payload.moon_range_degrees,
        extra_time_possible=payload.extra_time_possible,
    )
    result["transit_data"] = transits

    _analysis_cache[cache_key] = (result, time.time())
    return result


def _chart_request_to_person(chart_req, name: Optional[str] = None) -> dict:
    """ChartRequest → dict для calculate_progressed_synastry (единый формат партнёра)"""
    lat, lon = _resolve_coordinates(chart_req.latitude, chart_req.longitude, chart_req.birth_place)
    birth_dt = _prepare_birth_datetime(chart_req.birth_date, chart_req.birth_time, chart_req.timezone)
    return {
        'birth_date': birth_dt,
        'birth_place': chart_req.birth_place or '',
        'lat': lat,
        'lon': lon,
        'timezone': chart_req.timezone,
        'name': name,
    }


@router.post("/progressed-synastry")
@limiter.limit("15/minute")
async def calculate_progressed_synastry_endpoint(request: Request, payload: ProgressedSynastryRequest, user = Depends(get_current_user)):
    """
    Прогрессивная синастрия: каждый партнёр прогрессируется методом «день за год»
    на свой возраст на одну целевую дату (по умолчанию сегодня; можно любой день).
    Возвращает три слоя: прогрессивную синастрию (прогр↔прогр), наложение на
    натал (перекрёстно) и динамику относительно натальной синастрии.
    Доступно только для сохранённых синастрических карт (требует авторизацию).
    """
    person1 = _chart_request_to_person(payload.chart1, getattr(payload.chart1, 'name', None))
    person2 = _chart_request_to_person(payload.chart2, getattr(payload.chart2, 'name', None))

    try:
        result = calculate_progressed_synastry(
            person1=person1,
            person2=person2,
            target_date=payload.target_date,
            house_system=payload.house_system or 'Placidus',
        )
    except Exception as e:
        print(f"[progressed_synastry] calculation error: {e}")
        raise HTTPException(status_code=500, detail=f"Progressed synastry calculation error: {str(e)}")

    return result


@router.post("/analysis/progressed-synastry")
@limiter.limit("5/minute")
async def progressed_synastry_analysis_endpoint(request: Request, payload: ProgressedSynastryAnalysisRequest, user = Depends(get_current_user)):
    """
    AI-анализ прогрессивной синастрии (RAG + LLM, шаблон 'progressed_synastry',
    режимы simple/advanced, ru/en). Кэш по ключу
    progsyn|p1|p2|date|mode|language (TTL как у остальных анализов).
    """
    from app.services.analysis_service import progressed_synastry_analysis
    from datetime import datetime as dt

    # --- Расчётные данные: готовые из запроса или пересчёт ---
    progressed_synastry = payload.progressed_synastry_data
    if not progressed_synastry:
        if not payload.chart1 or not payload.chart2:
            raise HTTPException(status_code=400, detail="Either 'progressed_synastry_data' or chart1+chart2 must be provided")
        person1 = _chart_request_to_person(payload.chart1, getattr(payload.chart1, 'name', None))
        person2 = _chart_request_to_person(payload.chart2, getattr(payload.chart2, 'name', None))
        try:
            progressed_synastry = calculate_progressed_synastry(
                person1=person1, person2=person2,
                target_date=payload.target_date,
                house_system=payload.house_system or 'Placidus',
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Progressed synastry calculation error: {str(e)}")

    # --- Кэш ---
    period = progressed_synastry.get('period', '')
    p1n = (progressed_synastry.get('person1') or {}).get('name', 'p1')
    p2n = (progressed_synastry.get('person2') or {}).get('name', 'p2')
    cache_key = f"progsyn|{p1n}|{p2n}|{period}|{payload.mode}|{payload.language}"

    if cache_key in _analysis_cache:
        cached_result, timestamp = _analysis_cache[cache_key]
        if time.time() - timestamp < _ANALYSIS_CACHE_TTL:
            print(f"[CACHE] Returning cached progressed synastry analysis for {cache_key}")
            return {**cached_result, "from_cache": True, "cached_at": dt.fromtimestamp(timestamp).isoformat()}
        else:
            del _analysis_cache[cache_key]

    result = await progressed_synastry_analysis(
        progressed_synastry=progressed_synastry,
        language=payload.language,
        top_k_per_book=payload.top_k_per_book,
        mode=payload.mode or 'advanced',
    )

    result["progressed_synastry_data"] = progressed_synastry
    _analysis_cache[cache_key] = (result, time.time())
    return result
