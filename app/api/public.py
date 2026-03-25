"""
Публичные API эндпоинты (не требуют аутентификации)
- Расчет натальных карт
- Расчет транзитов
- Расчет синастрии
- Геокодинг
"""
from fastapi import APIRouter, HTTPException
from datetime import datetime
import json
import time
from typing import List, Dict, Any, Optional

# Геокодинг и определение таймзон
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from timezonefinder import TimezoneFinder
import pytz

from app.schemas.schemas import (
    NatalChartRequest, NatalChartResponseFull,
    TransitRequest, SynastryRequestDirect
)
from app.utils.astrology_v2 import (
    calculate_planet_positions, calculate_aspects,
    calculate_solar_return, calculate_synastry,
    PLANETS, ASPECTS, ASPECTS_RU, ORBS, get_zodiac_sign, get_zodiac_degree
)
from app.swephelper import swe

router = APIRouter(prefix="", tags=["public"])

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
                    all_locations.append({
                        "name": loc.address,
                        "latitude": loc.latitude,
                        "longitude": loc.longitude,
                        "type": loc.raw.get("type", ""),
                        "importance": loc.raw.get("importance", 0)
                    })
        
        if locations_en:
            for loc in locations_en:
                coord_key = f"{loc.latitude:.4f},{loc.longitude:.4f}"
                if coord_key not in seen_coords:
                    seen_coords.add(coord_key)
                    all_locations.append({
                        "name": loc.address,
                        "latitude": loc.latitude,
                        "longitude": loc.longitude,
                        "type": loc.raw.get("type", ""),
                        "importance": loc.raw.get("importance", 0)
                    })
        
        # Сортируем по важности
        all_locations.sort(key=lambda x: x.get("importance", 0), reverse=True)
        
        return all_locations[:10]  # Ограничиваем количество результатов
        
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        print(f"Autocomplete geocoding timeout/unavailable for '{query}': {e}")
    except Exception as e:
        print(f"Autocomplete geocoding error for '{query}': {e}")
    
    return []


# ============================================================================
# РАСЧЕТ НАТАЛЬНОЙ КАРТЫ (публичный)
# ============================================================================

@router.post("/chart/calculate", response_model=NatalChartResponseFull)
async def calculate_natal_chart(request: NatalChartRequest):
    """
    Расчет натальной карты (публичный, не требует аутентификации)
    """
    # Получаем ТОЧНЫЕ координаты
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
                       f"Please enter a valid city name. Error: {str(e)}"
            )
    
    # Определяем таймзону если не указана
    timezone_str = request.timezone
    if not timezone_str:
        timezone_str = get_timezone(lat, lon)
    
    # Выполняем расчет
    chart_data = calculate_planet_positions(
        birth_date=request.birth_date,
        birth_place=request.birth_place,
        lat=lat,
        lon=lon,
        timezone_str=timezone_str,
        house_system=request.house_system
    )
    
    return chart_data


# ============================================================================
# ГЕОКОДИНГ (публичный)
# ============================================================================

@router.get("/geocode/coordinates")
async def geocode_coordinates(place: str):
    """
    Геокодирование: название места -> координаты (публичный)
    """
    try:
        lat, lon = get_coordinates(place)
        return {
            "place": place,
            "latitude": lat,
            "longitude": lon,
            "timezone": get_timezone(lat, lon)
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/geocode/autocomplete")
async def geocode_autocomplete(query: str):
    """
    Автодополнение мест (публичный)
    """
    results = autocomplete_place(query)
    return {"query": query, "results": results}


@router.get("/geocode/reverse")
async def reverse_geocode_endpoint(lat: float, lon: float):
    """
    Обратное геокодирование: координаты -> информация о месте (публичный)
    """
    return reverse_geocode(lat, lon)


# ============================================================================
# ТРАНЗИТЫ (публичный)
# ============================================================================

@router.post("/transits")
async def calculate_transits(request: TransitRequest):
    """
    Расчет транзитов (публичный, не требует аутентификации)
    """
    # Получаем координаты для натальной карты
    if request.latitude is not None and request.longitude is not None:
        lat, lon = request.latitude, request.longitude
    else:
        try:
            lat, lon = get_coordinates(request.birth_place)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine coordinates for location: '{request.birth_place}'. "
                       f"Please enter a valid city name. Error: {str(e)}"
            )
    
    # Определяем таймзону если не указана
    timezone_str = request.timezone
    if not timezone_str:
        timezone_str = get_timezone(lat, lon)
    
    # Рассчитываем натальную карту
    natal_chart = calculate_planet_positions(
        birth_date=request.birth_date,
        birth_place=request.birth_place,
        lat=lat,
        lon=lon,
        timezone_str=timezone_str,
    )
    
    # Рассчитываем транзиты
    transit_chart = calculate_planet_positions(
        birth_date=request.transit_date,
        birth_place=request.birth_place,
        lat=lat,
        lon=lon,
        timezone_str=timezone_str,
    )
    
    # Находим аспекты между транзитными и натальными планетами
    transit_aspects = []
    
    for t_planet, t_data in transit_chart['planets'].items():
        if t_planet not in natal_chart['planets']:
            continue
            
        n_data = natal_chart['planets'][t_planet]
        lon1 = t_data['full_degree']
        lon2 = n_data['full_degree']
        
        diff = abs(lon1 - lon2)
        if diff > 180:
            diff = 360 - diff
        
        for aspect_degree, aspect_name in ASPECTS.items():
            if abs(diff - aspect_degree) <= 6:  # Стандартный орбис для транзитов
                transit_aspects.append({
                    'transiting_planet': t_planet,
                    'natal_planet': t_planet,
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
        'transiting_planets': transit_chart['planets'],
        'aspects': transit_aspects,
    }


# ============================================================================
# SYNASTRY (публичный)
# ============================================================================

@router.post("/synastry/direct")
async def calculate_synastry_direct(request: SynastryRequestDirect):
    """
    Прямой расчёт синастрии между двумя картами (публичный)
    """
    # Получаем ТОЧНЫЕ координаты для первой карты
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