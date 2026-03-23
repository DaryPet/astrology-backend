from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime
import json
import time
from typing import List, Dict, Any, Optional

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
                # Проверяем качество результата
                lat, lon = location.latitude, location.longitude
                
                # Валидация координат
                if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                    raise ValueError(f"Invalid coordinates: ({lat}, {lon})")
                
                # Проверяем, что это не океан/пустыня (минимальная населенность)
                # Для астрологии все равно, но для UX лучше
                
                result = (lat, lon)
                # Сохраняем в кэш
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
    
    # Если все провайдеры не сработали - ВОЗВРАЩАЕМ ОШИБКУ, а не Moscow!
    # Для астрологии лучше ошибка, чем неправильные координаты
    error_msg = f"Cannot geocode location: '{place}'. Last error: {last_error}"
    print(f"❌ CRITICAL: {error_msg}")
    
    # Вызываем исключение вместо возврата Moscow
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

def autocomplete_place(query: str) -> List[Dict[str, Any]]:
    """Возвращает список мест для автодополнения с улучшенным форматированием и поиском"""
    if len(query) < 2:
        return []
    
    try:
        # Пробуем поиск на русском
        locations_ru = geolocator.geocode(query, exactly_one=False, limit=8, language='ru')
        
        # Пробуем поиск на английском (для международных городов)
        locations_en = []
        if len(query) > 2:  # Только для достаточно длинных запросов
            try:
                locations_en = geolocator.geocode(query, exactly_one=False, limit=4, language='en')
            except:
                pass
        
        # Объединяем результаты, убирая дубликаты
        all_locations = []
        seen_coords = set()
        
        if locations_ru:
            for loc in locations_ru:
                coord_key = f"{loc.latitude:.4f},{loc.longitude:.4f}"
                if coord_key not in seen_coords:
                    seen_coords.add(coord_key)
                    all_locations.append(('ru', loc))
        
        if locations_en:
            for loc in locations_en:
                coord_key = f"{loc.latitude:.4f},{loc.longitude:.4f}"
                if coord_key not in seen_coords:
                    seen_coords.add(coord_key)
                    all_locations.append(('en', loc))
        
        if not all_locations:
            return []
        
        # Сортируем по релевантности (крупные города сначала)
        def location_score(loc):
            """Оценка релевантности локации"""
            address = loc[1].address.lower()
            query_lower = query.lower()
            
            # Бонус за точное совпадение в начале названия
            if address.startswith(query_lower):
                return 10
            # Бонус за столицы и крупные города
            if any(city in address for city in ['москва', 'санкт-петербург', 'киев', 'минск', 'нью-йорк', 'лондон', 'париж', 'берлин']):
                return 5
            return 1
        
        all_locations.sort(key=location_score, reverse=True)
        
        results = []
        for lang, loc in all_locations[:10]:  # Ограничиваем 10 результатами
            address = loc.address
            address_parts = address.split(', ')
            
            # Форматируем отображаемое имя
            if len(address_parts) >= 2:
                # Город, регион/страна
                display_name = f"{address_parts[0]}, {address_parts[1]}"
            else:
                display_name = address_parts[0]
            
            # Определяем таймзону для этого места
            timezone_str = get_timezone(loc.latitude, loc.longitude)
            
            # Определяем тип места (город, деревня и т.д.)
            place_type = "city"
            address_lower = address.lower()
            if any(word in address_lower for word in ['деревня', 'село', 'поселок', 'village', 'town']):
                place_type = "village"
            elif any(word in address_lower for word in ['область', 'регион', 'район', 'region', 'district']):
                place_type = "region"
            
            results.append({
                "name": address,  # Полный адрес
                "display_name": display_name,  # Краткое отображаемое имя
                "address": address,  # Полный адрес (для обратной совместимости)
                "lat": loc.latitude,
                "lon": loc.longitude,
                "latitude": loc.latitude,  # Дублирование для совместимости
                "longitude": loc.longitude,  # Дублирование для совместимости
                "timezone": timezone_str,  # Добавляем таймзону
                "type": place_type,  # Тип места
                "country": address_parts[-1] if address_parts else ""  # Страна
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
    - birth_place: Название места (точное название города/места)
    - timezone: Временная зона (IANA, например "Europe/Moscow")
    - house_system: Система домов (Placidus, Equal, WholeSign, etc.)
    """
    # Получаем ТОЧНЫЕ координаты из названия места
    # Для астрологии критически важна точность - нет fallback на Москву!
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

@router.post("/transits")
async def calculate_transits_direct(request: TransitRequest):
    """
    Расчёт текущих транзитов к натальной карте
    
    Требует:
    - birth_date, birth_place, timezone - данные натальной карты
    - transit_date - дата транзитов
    """
    # Получаем ТОЧНЫЕ координаты из названия места
    try:
        lat, lon = get_coordinates(request.birth_place)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot determine coordinates for location: '{request.birth_place}'. "
                   f"Please enter a valid city name. Error: {str(e)}"
        )
    
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
    # Получаем ТОЧНЫЕ координаты для первой карты
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