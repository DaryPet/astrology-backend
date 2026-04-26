"""
Swiss Ephemeris - Золотой стандарт астрологии
Точность до долей секунды дуги
"""
# Use pre-initialized swisseph from helper
from app.swephelper import swe

from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Tuple, Optional
import math
from zoneinfo import ZoneInfo  # Python 3.9+

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

ZODIAC_SIGNS_RU = [
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"
]

# Все планеты включая LILITH (Black Moon)
PLANETS = {
    'Sun': swe.SUN,
    'Moon': swe.MOON,
    'Mercury': swe.MERCURY,
    'Venus': swe.VENUS,
    'Mars': swe.MARS,
    'Jupiter': swe.JUPITER,
    'Saturn': swe.SATURN,
    'Uranus': swe.URANUS,
    'Neptune': swe.NEPTUNE,
    'Pluto': swe.PLUTO,
    'NorthNode': swe.TRUE_NODE,  # Северный узел (Раху)
    'SouthNode': swe.TRUE_NODE,   # Южный узел (Кету)
    'Lilith': swe.MEAN_APOG,  # Black Moon - средняя апогея (работает в Moshier)
}

# Minor planets (asteroids) - требуют внешних эфемерид
MINOR_PLANETS = {
    'Chiron': swe.CHIRON,
    'Ceres': swe.CERES,
    'Pallas': swe.PALLAS,
    'Juno': swe.JUNO,
    'Vesta': swe.VESTA,
}

# Houses system codes for Swiss Ephemeris
HOUSE_SYSTEMS = {
    'Placidus': b'P',
    'Koch': b'K',
    'Porphyrius': b'O',
    'Regiomontanus': b'R',
    'Campanus': b'C',
    'Equal': b'E',
    'WholeSign': b'W',
}

ASPECTS = {
    0: 'Conjunction',      # Соединение
    60: 'Sextile',         # Секстиль
    90: 'Square',          # Квадрат
    120: 'Trine',          # Тригон
    180: 'Opposition',     # Оппозиция
}

ASPECTS_RU = {
    0: 'Соединение',
    60: 'Секстиль',
    90: 'Квадрат',
    120: 'Тригон',
    180: 'Оппозиция',
}

ORBS = {
    ('Sun', 'Moon'): 10,
    ('Sun', 'Mercury'): 8,
    ('Sun', 'Venus'): 8,
    ('Sun', 'Mars'): 8,
    ('Sun', 'Jupiter'): 10,
    ('Sun', 'Saturn'): 10,
    ('Sun', 'Uranus'): 8,
    ('Sun', 'Neptune'): 8,
    ('Sun', 'Pluto'): 8,
    ('Moon', 'Mercury'): 6,
    ('Moon', 'Venus'): 6,
    ('Moon', 'Mars'): 6,
    ('Moon', 'Jupiter'): 8,
    ('Moon', 'Saturn'): 8,
    ('Mercury', 'Venus'): 6,
    ('Mercury', 'Mars'): 6,
    ('Mercury', 'Jupiter'): 8,
    ('Mercury', 'Saturn'): 6,
    ('Venus', 'Mars'): 6,
    ('Venus', 'Jupiter'): 8,
    ('Venus', 'Saturn'): 8,
    ('Mars', 'Jupiter'): 8,
    ('Mars', 'Saturn'): 6,
    ('Jupiter', 'Saturn'): 8,
    ('Saturn', 'Uranus'): 6,
    ('Uranus', 'Neptune'): 6,
    ('Neptune', 'Pluto'): 6,
}


def get_zodiac_sign(degree: float) -> Tuple[str, str]:
    """Convert degree (0-360) to zodiac sign (EN, RU)"""
    index = int(degree / 30) % 12
    return ZODIAC_SIGNS[index], ZODIAC_SIGNS_RU[index]


def get_zodiac_degree(degree: float) -> float:
    """Get degree within zodiac sign (0-30)"""
    return degree % 30


def jd_to_datetime(jd: float) -> datetime:
    """Convert Julian Day to datetime"""
    return swe.jd_to_datetime(jd)


def datetime_to_jd(dt: datetime) -> float:
    """Convert datetime to Julian Day"""
    return swe.utc_to_jd(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, swe.GREG_CAL)[0]


def calculate_planet_position(planet_id: float, jd: float, lat: float, lon: float) -> Dict[str, Any]:
    """
    Расчёт позиции планеты с высокой точностью
    Использует Swiss Ephemeris (Moshier algorithm) - встроенные таблицы
    Точность: ~1 угловая секунда
    """
    # Используем Moshier ephemeris + FLG_SPEED для получения скорости
    flags = swe.FLG_MOSEPH | swe.FLG_SPEED
    
    # Get coordinates
    try:
        result = swe.calc_ut(jd, planet_id, flags)
    except Exception as e:
        return {
            'longitude': 0,
            'latitude': 0,
            'speed': 0,
            'sign': 'Unknown',
            'sign_ru': 'Неизвестно',
            'degree': 0,
            'full_degree': 0,
            'error': str(e)
        }
    
    # result[0] = долгота (эклиптическая)
    # result[1] = широта
    # result[2] = расстояние
    # result[3] = скорость по долготе
    # result[4] = астрономическая скорость
    
    longitude = result[0][0]
    latitude = result[0][1]
    speed = result[0][3] if len(result[0]) > 3 else 0
    
    # Знак зодиака
    sign_en, sign_ru = get_zodiac_sign(longitude)
    degree_in_sign = get_zodiac_degree(longitude)
    
    return {
        'longitude': longitude,  # 0-360
        'latitude': latitude,     # -90 to +90
        'speed': speed,           # градусов в день
        'sign': sign_en,
        'sign_ru': sign_ru,
        'degree': round(degree_in_sign, 4),
        'full_degree': round(longitude, 4),
    }


def calculate_houses(jd: float, lat: float, lon: float, house_system: str = 'Placidus') -> Dict[str, Any]:
    """
    Расчёт ВСЕХ 12 домов с использованием Swiss Ephemeris
    """
    flags = swe.FLG_MOSEPH
    hsys = HOUSE_SYSTEMS.get(house_system, b'P')
    
    # Получаем дома (кортеж: (cusps, ascmc))
    # houses[0] - массив куспидов (1-12 домов)
    # houses[1] - массив асцендента, MC, ARMC, и т.д.
    houses = swe.houses(jd, lat, lon, hsys)
    
    cusps = houses[0]  # 12 куспидов домов
    ascmc = houses[1]   # [ASC, MC, ARMC, Vertex, Equatorial ASC...]
    
    # Расшифровка ascmc:
    # ascmc[0] = ASC (Асцендент)
    # ascmc[1] = MC (Середина Неба)
    # ascmc[2] = ARMC (Anti-Meridian Co-Latitude)
    # ascmc[3] = Vertex
    # ascmc[4] = Equatorial Ascendant
    # ascmc[5] = Co-Ascendant (Koch)
    # ascmc[6] = Co-Ascendant (Munkasey)
    # ascmc[7] = Polar Ascendant
    
    house_names_en = [
        "1st House", "2nd House", "3rd House", "4th House", 
        "5th House", "6th House", "7th House", "8th House",
        "9th House", "10th House", "11th House", "12th House"
    ]
    
    house_names_ru = [
        "Дом 1", "Дом 2", "Дом 3", "Дом 4",
        "Дом 5", "Дом 6", "Дом 7", "Дом 8",
        "Дом 9", "Дом 10", "Дом 11", "Дом 12"
    ]
    
    house_planets = {
        'Sun': 10,  # Традиционно Солнце в 10 доме
        'Moon': 4,   # Луна в 4 доме
    }
    
    result_houses = {}
    for i, cusp in enumerate(cusps):
        cusp_longitude = cusp
        sign_en, sign_ru = get_zodiac_sign(cusp_longitude)
        result_houses[i+1] = {
            'house': i + 1,
            'name_en': house_names_en[i],
            'name_ru': house_names_ru[i],
            'cusp_longitude': round(cusp_longitude, 4),
            'sign': sign_en,
            'sign_ru': sign_ru,
            'degree': round(get_zodiac_degree(cusp_longitude), 4),
        }
    
    # ASC и MC из ascmc
    asc_longitude = ascmc[0]
    mc_longitude = ascmc[1]
    
    asc_sign_en, asc_sign_ru = get_zodiac_sign(asc_longitude)
    mc_sign_en, mc_sign_ru = get_zodiac_sign(mc_longitude)
    
    return {
        'houses': result_houses,
        'ascendant': {
            'longitude': round(asc_longitude, 4),
            'sign': asc_sign_en,
            'sign_ru': asc_sign_ru,
            'degree': round(get_zodiac_degree(asc_longitude), 4),
        },
        'mc': {
            'longitude': round(mc_longitude, 4),
            'sign': mc_sign_en,
            'sign_ru': mc_sign_ru,
            'degree': round(get_zodiac_degree(mc_longitude), 4),
        },
        'armc': round(ascmc[2], 4) if len(ascmc) > 2 else None,
        'vertex': round(ascmc[3], 4) if len(ascmc) > 3 else None,
        'house_system': house_system,
    }


def calculate_planet_positions(
    birth_date: datetime, 
    birth_place: str, 
    lat: float = None, 
    lon: float = None,
    timezone_str: str = None,
    house_system: str = 'Placidus'
) -> Dict[str, Any]:
    """
    Главная функция расчёта натальной карты
    Использует Swiss Ephemeris для максимальной точности
    
    Args:
        birth_date: Дата и время рождения (с timezone или UTC)
        birth_place: Название места рождения
        lat: Широта (если известна)
        lon: Долгота (если известна)
        timezone_str: IANA timezone строка (например 'Europe/Moscow')
        house_system: Система домов (Placidus, Koch, Equal, WholeSign, etc.)
    """
    # Если координаты не переданы, используем UTC
    if lat is None or lon is None:
        # Для простоты используем координаты 0,0 - нулевой меридиан
        lat, lon = 0.0, 0.0
    
    # Правильная конвертация времени в Julian Day
    # Если datetime уже с timezone - конвертируем в UTC
    # Если naive datetime и передан timezone_str - применяем timezone перед конвертацией
    if birth_date.tzinfo is not None:
        # datetime с timezone - конвертируем в UTC
        utc_dt = birth_date.astimezone(timezone.utc)
        year, month, day = utc_dt.year, utc_dt.month, utc_dt.day
        hour, minute, second = utc_dt.hour, utc_dt.minute, utc_dt.second
    elif timezone_str:
        # naive datetime + timezone string - применяем timezone
        try:
            tz = ZoneInfo(timezone_str)
            aware_dt = birth_date.replace(tzinfo=tz)
            utc_dt = aware_dt.astimezone(timezone.utc)
            year, month, day = utc_dt.year, utc_dt.month, utc_dt.day
            hour, minute, second = utc_dt.hour, utc_dt.minute, utc_dt.second
        except:
            # Если не удалось - считаем как UTC
            year, month, day = birth_date.year, birth_date.month, birth_date.day
            hour, minute, second = birth_date.hour, birth_date.minute, birth_date.second
    else:
        # naive datetime без timezone - считаем как UTC
        year, month, day = birth_date.year, birth_date.month, birth_date.day
        hour, minute, second = birth_date.hour, birth_date.minute, birth_date.second
    
    # Julian Day в UTC
    jd = swe.utc_to_jd(year, month, day, hour, minute, second, swe.GREG_CAL)[0]
    
    # Расчёт планет
    planets = {}
    
    # Основные планеты
    for planet_name, planet_id in PLANETS.items():
        if planet_name == 'SouthNode':
            continue  # Рассчитаем после NorthNode
        
        if planet_name == 'NorthNode':
            result = swe.calc_ut(jd, planet_id, swe.FLG_MOSEPH)
            longitude = result[0][0]
            speed = result[0][3] if len(result[0]) > 3 else 0
        elif planet_name == 'Lilith':
            # Black Moon - средняя апогея (MEAN_APOG)
            # Рассчитывается через Swiss Ephemeris как обычная планета
            pos = calculate_planet_position(planet_id, jd, lat, lon)
            longitude = pos['full_degree']
            speed = pos['speed']
        else:
            pos = calculate_planet_position(planet_id, jd, lat, lon)
            longitude = pos['full_degree']
            speed = pos['speed']
        
        sign_en, sign_ru = get_zodiac_sign(longitude)
        is_retrograde = speed < 0
        
        planets[planet_name] = {
            'planet': planet_name,
            'sign': sign_en,
            'sign_ru': sign_ru,
            'degree': round(get_zodiac_degree(longitude), 4),
            'full_degree': round(longitude, 4),
            'speed': round(speed, 4) if speed else 0,
            'is_retrograde': is_retrograde,
        }
    
    # Добавляем SouthNode (противоположно NorthNode)
    nn_longitude = planets['NorthNode']['full_degree']
    sn_longitude = (nn_longitude + 180) % 360
    sn_sign_en, sn_sign_ru = get_zodiac_sign(sn_longitude)
    planets['SouthNode'] = {
        'planet': 'SouthNode',
        'sign': sn_sign_en,
        'sign_ru': sn_sign_ru,
        'degree': round(get_zodiac_degree(sn_longitude), 4),
        'full_degree': round(sn_longitude, 4),
        'speed': round(-planets['NorthNode']['speed'], 4),
        'is_retrograde': planets['NorthNode']['is_retrograde'],
    }
    
    # Расчёт Chiron (малая планета/астероид)
    chiron_id = MINOR_PLANETS.get('Chiron')
    if chiron_id is not None:
        try:
            result = swe.calc_ut(jd, chiron_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
            if result and len(result[0]) > 0 and result[0][0] >= 0:
                longitude = result[0][0]
                speed = result[0][3] if len(result[0]) > 3 else 0
                
                sign_en, sign_ru = get_zodiac_sign(longitude)
                is_retrograde = speed < 0
                
                planets['Chiron'] = {
                    'planet': 'Chiron',
                    'sign': sign_en,
                    'sign_ru': sign_ru,
                    'degree': round(get_zodiac_degree(longitude), 4),
                    'full_degree': round(longitude, 4),
                    'speed': round(speed, 4) if speed else 0,
                    'is_retrograde': is_retrograde,
                }
                print(f"Chiron calculated successfully: {sign_en} {get_zodiac_degree(longitude):.2f}°")
            else:
                print(f"Chiron: invalid result from Swiss Ephemeris")
                planets['Chiron'] = {
                    'planet': 'Chiron',
                    'sign': 'Unknown',
                    'sign_ru': 'Неизвестно',
                    'degree': 0,
                    'full_degree': 0,
                    'speed': 0,
                    'is_retrograde': False,
                    'error': 'Invalid ephemeris data'
                }
        except Exception as e:
            print(f"Chiron calculation error: {e}")
            planets['Chiron'] = {
                'planet': 'Chiron',
                'sign': 'Unknown',
                'sign_ru': 'Неизвестно',
                'degree': 0,
                'full_degree': 0,
                'speed': 0,
                'is_retrograde': False,
                'error': str(e)
            }
    
    # Расчёт всех 12 домов
    houses_data = calculate_houses(jd, lat, lon, house_system)
    
    # Определяем планеты в домах
    # Для каждой планеты находим её дом
    for planet_name, planet_data in planets.items():
        planet_degree = planet_data['full_degree']
        # Ищем дом
        assigned_house = None
        for house_num in range(1, 13):
            cusp_current = houses_data['houses'][house_num]['cusp_longitude']
            cusp_next = houses_data['houses'][house_num % 12 + 1]['cusp_longitude']
            
            # Проверяем находится ли планета между куспидами
            if cusp_next > cusp_current:
                if cusp_current <= planet_degree < cusp_next:
                    assigned_house = house_num
                    break
            else:
                # Переход через 0° Овна
                if cusp_current <= planet_degree or planet_degree < cusp_next:
                    assigned_house = house_num
                    break
        
        if assigned_house:
            planets[planet_name]['house'] = assigned_house
    
# Calculate Pars Fortuna - correct formula based on day/night chart
    # All values in degrees (0-360)
    sun_full = planets['Sun']['full_degree']
    moon_full = planets['Moon']['full_degree']
    
    # Get full degrees
    asc_sign_idx = ZODIAC_SIGNS.index(houses_data['ascendant']['sign'])
    asc_full = asc_sign_idx * 30 + houses_data['ascendant']['degree']
    mc_sign_idx = ZODIAC_SIGNS.index(houses_data['mc']['sign'])
    mc_full = mc_sign_idx * 30 + houses_data['mc']['degree']
    
    # Determine if day chart (Sun above horizon, in houses 7-12)
    # Houses 7-12 = upper hemisphere (between DESC and IC)
    # From ASC: upper hemisphere is 90-270 degrees (wrapping through DESC)
    sun_from_asc = (sun_full - asc_full) % 360
    # Day = Sun in houses 7-12 (above horizon) = between 90 and 270 degrees from ASC
    is_day_chart = 90 <= sun_from_asc < 270
    
    # Calculate Pars Fortuna using FULL longitude for ASC
    if is_day_chart:
        # Day chart: ASC + Moon - Sun
        pars_fortuna = (asc_full + moon_full - sun_full) % 360
    else:
        # Night chart: ASC + Sun - Moon
        pars_fortuna = (asc_full + sun_full - moon_full) % 360
    
    # Get zodiac sign for Pars Fortuna
    pf_sign_en, pf_sign_ru = get_zodiac_sign(pars_fortuna)
    pf_degree = get_zodiac_degree(pars_fortuna)
    
    # Determine which house Pars Fortuna falls into
    houses_dict = houses_data['houses']
    pf_house = None
    for house_num in range(1, 13):
        cusp_current = houses_dict[house_num]['cusp_longitude']
        cusp_next = houses_dict[house_num % 12 + 1]['cusp_longitude']
        
        if cusp_next > cusp_current:
            if cusp_current <= pars_fortuna < cusp_next:
                pf_house = house_num
                break
        else:
            if cusp_current <= pars_fortuna or pars_fortuna < cusp_next:
                pf_house = house_num
                break
    
    # Determine which house Vertex falls into
    vertex_long = houses_data.get('vertex')
    vertex_house = None
    if vertex_long is not None:
        for house_num in range(1, 13):
            cusp_current = houses_dict[house_num]['cusp_longitude']
            cusp_next = houses_dict[house_num % 12 + 1]['cusp_longitude']
            
            if cusp_next > cusp_current:
                if cusp_current <= vertex_long < cusp_next:
                    vertex_house = house_num
                    break
            else:
                if cusp_current <= vertex_long or vertex_long < cusp_next:
                    vertex_house = house_num
                    break
    
    return {
        'sun_sign': planets['Sun']['sign'],
        'sun_sign_ru': planets['Sun']['sign_ru'],
        'moon_sign': planets['Moon']['sign'],
        'moon_sign_ru': planets['Moon']['sign_ru'],
        'ascendant': houses_data['ascendant']['sign'],
        'ascendant_ru': houses_data['ascendant']['sign_ru'],
        'ascendant_degree': houses_data['ascendant']['degree'],
        'mc': houses_data['mc']['sign'],
        'mc_ru': houses_data['mc']['sign_ru'],
        'mc_degree': houses_data['mc']['degree'],
        'planets': planets,
        'houses': houses_data['houses'],
        'houses_meta': {
            'house_system': house_system,
            'armc': houses_data.get('armc'),
            'vertex': {
                'longitude': round(vertex_long, 4) if vertex_long else None,
                'house': vertex_house,
            },
            'pars_fortuna': {
                'longitude': round(pars_fortuna, 4),
                'sign': pf_sign_en,
                'sign_ru': pf_sign_ru,
                'degree': round(pf_degree, 4),
                'house': pf_house,
            },
        },
        'meta': {
            'birth_date': birth_date.isoformat() if hasattr(birth_date, 'isoformat') else str(birth_date),
            'birth_place': birth_place,
            'latitude': lat,
            'longitude': lon,
            'timezone': timezone_str,
            'jd': round(jd, 6),
        }
    }


def calculate_aspects(planets: Dict[str, Any], orb_threshold: float = 8.0) -> List[Dict[str, Any]]:
    """
    Расчёт аспектов между планетами
    """
    aspects = []
    
    planet_list = list(planets.items())
    
    for i, (name1, data1) in enumerate(planet_list):
        for name2, data2 in planet_list[i+1:]:
            lon1 = data1['full_degree']
            lon2 = data2['full_degree']
            
            # Разница по кратчайшему пути
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            
            # Проверяем каждый аспект
            for aspect_degree, aspect_name in ASPECTS.items():
                # Орб для данной пары планет
                key = tuple(sorted([name1, name2]))
                orb = ORBS.get(key, 6)
                
                if abs(diff - aspect_degree) <= orb:
                    aspects.append({
                        'planet1': name1,
                        'planet2': name2,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'orb': round(abs(diff - aspect_degree), 2),
                        'exactness': round(100 - (abs(diff - aspect_degree) / orb * 100), 1),
                    })
                    break
    
    # Сортируем по точности
    aspects.sort(key=lambda x: x['exactness'], reverse=True)
    
    return aspects


def calculate_solar_return(birth_date: datetime, year: int, lat: float = None, lon: float = None) -> Dict[str, Any]:
    """
    Расчёт солярного возвращения (Solar Return)
    Солнце возвращается на ту же позицию, что и при рождении
    """
    if lat is None or lon is None:
        lat, lon = 55.7558, 37.6173
    
    # JD рождения
    birth_jd = swe.utc_to_jd(birth_date.year, birth_date.month, birth_date.day,
                              birth_date.hour, birth_date.minute, birth_date.second,
                              swe.GREG_CAL)[0]
    
    # Позиция Солнца при рождении
    sun_birth = calculate_planet_position(swe.SUN, birth_jd, lat, lon)
    sun_longitude_birth = sun_birth['full_degree']
    
    # Ищем дату солярного возвращения в нужном году
    # Примерная дата - день рождения в нужном году
    start_jd = swe.utc_to_jd(year, birth_date.month, birth_date.day,
                              birth_date.hour, birth_date.minute, birth_date.second,
                              swe.GREG_CAL)[0]
    
    # Ищем точное время, когда Солнце на нужной долготе
    # Swe.lun_occult_when_loc может помочь, но для Солнца используем итерацию
    
    # Сканируем несколько дней вокруг дня рождения
    best_jd = None
    best_diff = 360
    
    for day_offset in range(-2, 3):
        test_jd = start_jd + day_offset
        for hour in range(24):
            test_jd_hour = test_jd + hour / 24.0
            pos = calculate_planet_position(swe.SUN, test_jd_hour, lat, lon)
            diff = abs(pos['full_degree'] - sun_longitude_birth)
            if diff > 180:
                diff = 360 - diff
            
            if diff < best_diff:
                best_diff = diff
                best_jd = test_jd_hour
    
    if best_jd:
        solar_return_date = swe.jd_to_datetime(best_jd)
        return {
            'date': solar_return_date.isoformat(),
            'jd': best_jd,
            'sun_position': calculate_planet_position(swe.SUN, best_jd, lat, lon),
            'exactness': round(100 - best_diff * 10, 2),  # Процент точности
        }
    
    return None


def calculate_synastry(chart1: Dict[str, Any], chart2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Расчёт синастрии (совместимости двух карт)
    """
    aspects = []
    
    # Аспекты между планетами двух карт
    for planet1_name, planet1_data in chart1['planets'].items():
        for planet2_name, planet2_data in chart2['planets'].items():
            lon1 = planet1_data['full_degree']
            lon2 = planet2_data['full_degree']
            
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff
            
            for aspect_degree, aspect_name in ASPECTS.items():
                key = tuple(sorted([planet1_name, planet2_name]))
                orb = ORBS.get(key, 6)
                
                if abs(diff - aspect_degree) <= orb:
                    aspects.append({
                        'planet1': planet1_name,
                        'planet2': planet2_name,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'orb': round(abs(diff - aspect_degree), 2),
                    })
                    break
    
    # Сортируем по важности
    aspect_priority = {'Conjunction': 5, 'Opposition': 4, 'Trine': 3, 'Square': 2, 'Sextile': 1}
    aspects.sort(key=lambda x: aspect_priority.get(x['aspect'], 0), reverse=True)
    
    return {
        'aspects': aspects,
        'total_aspects': len(aspects),
    }


# Тестовая функция
if __name__ == "__main__":
    # Пример расчёта
    birth = datetime(1995, 3, 21, 12, 0, 0)
    
    # Москва
    lat, lon = 55.7558, 37.6173
    
    print("=== Расчёт натальной карты (Swiss Ephemeris) ===")
    print(f"Дата рождения: {birth}")
    print(f"Место: Москва ({lat}, {lon})")
    print()
    
    chart = calculate_planet_positions(birth, "Moscow", lat, lon)
    
    print("Солнце:", chart['sun_sign_ru'])
    print("Луна:", chart['moon_sign_ru'])
    print("Асцендент:", chart['ascendant_ru'])
    print("MC:", chart['mc_ru'])
    print()
    
    print("=== Планеты ===")
    for name, data in chart['planets'].items():
        print(f"{name}: {data['sign_ru']} {data['degree']}°")
    
    print()
    print("=== Аспекты ===")
    aspects = calculate_aspects(chart['planets'])
    for asp in aspects:
        print(f"{asp['planet1']} {asp['aspect_ru']} {asp['planet2']} (orb: {asp['orb']}°)")
    
    print()
    print("=== Солярное возвращение 2025 ===")
    sr = calculate_solar_return(birth, 2025, lat, lon)
    if sr:
        print(f"Дата: {sr['date']}")
        print(f"Точность: {sr['exactness']}%")
