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
            result = swe.calc_ut(jd, planet_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
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
        # North Node and South Node are always retrograde in astrology
        if planet_name in ('NorthNode', 'SouthNode'):
            is_retrograde = True
        else:
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
        'is_retrograde': True,  # South Node всегда ретрограден в астрологии
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


def get_house_for_longitude(longitude: float, houses: Dict) -> Optional[int]:
    """
    Определяет номер дома (1-12) по долготе планеты и куспидам домов.
    """
    cusps = []
    for i in range(1, 13):
        key = str(i) if str(i) in houses else i
        if key in houses:
            cusps.append(houses[key]['cusp_longitude'])
        else:
            return None
    
    # House system: cusps[i] is start of house i+1
    for i in range(12):
        start_cusp = cusps[i]
        end_cusp = cusps[(i + 1) % 12]
        
        if start_cusp <= end_cusp:
            if start_cusp <= longitude < end_cusp:
                return i + 1
        else:  # wrap around (house 12 crosses 0 Aries)
            if longitude >= start_cusp or longitude < end_cusp:
                return i + 1
    return None


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


# ============================================================
# SECONDARY PROGRESSIONS (Вторичные прогрессии, «день за год»)
# ============================================================

TROPICAL_YEAR = 365.2422  # тропический год в днях
PROGRESSION_ORB = 1.5     # тугой орб для аспектов прогрессий (стандарт 1-1.5°)


def _datetime_to_utc_jd(dt: datetime) -> float:
    """Конвертация datetime (aware или naive-как-UTC) в Julian Day (UT)"""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return swe.utc_to_jd(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, swe.GREG_CAL)[0]


# Прогрессивная лунная фаза (угол Луна−Солнце) — ядро интерпретации вторичных прогрессий.
# 8 фаз по 45°: ключевые этапы ~30-летнего цикла внутреннего развития.
LUNAR_PHASES = [
    (0,   'New Moon',          'Новолуние'),
    (45,  'Crescent',          'Растущий серп'),
    (90,  'First Quarter',     'Первая четверть'),
    (135, 'Gibbous',           'Растущая выпуклая'),
    (180, 'Full Moon',         'Полнолуние'),
    (225, 'Disseminating',     'Рассеивающая'),
    (270, 'Last Quarter',      'Последняя четверть'),
    (315, 'Balsamic',          'Бальзамическая'),
]


def get_progressed_lunar_phase(sun_longitude: float, moon_longitude: float) -> Dict[str, Any]:
    """Определить прогрессивную лунную фазу по углу Луна−Солнце (0-360°)"""
    angle = (moon_longitude - sun_longitude) % 360
    phase_en, phase_ru = LUNAR_PHASES[0][1], LUNAR_PHASES[0][2]
    for start_deg, en, ru in LUNAR_PHASES:
        if angle >= start_deg:
            phase_en, phase_ru = en, ru
    return {
        'angle': round(angle, 2),
        'phase': phase_en,
        'phase_ru': phase_ru,
    }


def calculate_secondary_progressions(
    birth_date: datetime,
    birth_place: str,
    target_date: Optional[datetime] = None,
    lat: float = None,
    lon: float = None,
    timezone_str: str = None,
    house_system: str = 'Placidus',
    orb: float = PROGRESSION_ORB,
) -> Dict[str, Any]:
    """
    Расчёт вторичных прогрессий (Secondary Progressions) через Swiss Ephemeris.

    Метод «день за год»: каждый день после рождения символически равен
    одному году жизни. Прогрессивный Julian Day:
        progressed_jd = natal_jd + (target_jd - natal_jd) / TROPICAL_YEAR

    Возвращает:
    - прогрессивные позиции планет (+ натальный дом каждой прогрессивной планеты)
    - прогрессивные ASC/MC и дома (вторичные угловые: дома на прогрессивный JD
      по натальным координатам)
    - аспекты прогрессивных планет к натальным (тугой орб)
    - возраст и период
    """
    # 1. Натальная карта — переиспользуем основной расчёт
    natal = calculate_planet_positions(
        birth_date, birth_place, lat, lon, timezone_str, house_system
    )
    natal_jd = natal['meta']['jd']

    # 2. Дата, на которую строим прогрессии (по умолчанию — сейчас, UTC)
    if target_date is None:
        target_date = datetime.now(timezone.utc)
    target_jd = _datetime_to_utc_jd(target_date)

    # 3. Формула «день за год»
    age_years = (target_jd - natal_jd) / TROPICAL_YEAR
    if age_years < 0:
        age_years = 0.0
    progressed_jd = natal_jd + age_years

    # 4. Прогрессивные планеты
    progressed_planets: Dict[str, Any] = {}
    for planet_name, planet_id in PLANETS.items():
        if planet_name == 'SouthNode':
            continue  # рассчитаем после NorthNode
        try:
            result = swe.calc_ut(progressed_jd, planet_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
            longitude = result[0][0]
            speed = result[0][3] if len(result[0]) > 3 else 0
        except Exception as e:
            print(f"[progressions] {planet_name} calc error: {e}")
            continue

        sign_en, sign_ru = get_zodiac_sign(longitude)
        is_retrograde = True if planet_name == 'NorthNode' else speed < 0
        natal_planet = natal['planets'].get(planet_name, {})
        prog_house = get_house_for_longitude(longitude, natal['houses'])
        natal_planet_house = natal_planet.get('house')

        progressed_planets[planet_name] = {
            'planet': planet_name,
            'sign': sign_en,
            'sign_ru': sign_ru,
            'degree': round(get_zodiac_degree(longitude), 4),
            'full_degree': round(longitude, 4),
            'speed': round(speed, 4) if speed else 0,
            'is_retrograde': is_retrograde,
            # дом прогрессивной планеты в НАТАЛЬНОЙ системе домов (стандарт интерпретации)
            'natal_house': prog_house,
            # сменила ли планета знак относительно натала — ключевой маркер для анализа
            'changed_sign': sign_en != natal_planet.get('sign'),
            'natal_sign': natal_planet.get('sign'),
            # дом, в котором планета была в натале, и факт перехода в другой дом —
            # не менее важный маркер, чем смена знака
            'natal_planet_house': natal_planet_house,
            'changed_house': (natal_planet_house is not None and prog_house != natal_planet_house),
            'natal_degree': natal_planet.get('degree'),
        }

    # SouthNode — противоположно NorthNode
    if 'NorthNode' in progressed_planets:
        nn_longitude = progressed_planets['NorthNode']['full_degree']
        sn_longitude = (nn_longitude + 180) % 360
        sn_sign_en, sn_sign_ru = get_zodiac_sign(sn_longitude)
        natal_sn = natal['planets'].get('SouthNode', {})
        sn_house = get_house_for_longitude(sn_longitude, natal['houses'])
        sn_natal_house = natal_sn.get('house')
        progressed_planets['SouthNode'] = {
            'planet': 'SouthNode',
            'sign': sn_sign_en,
            'sign_ru': sn_sign_ru,
            'degree': round(get_zodiac_degree(sn_longitude), 4),
            'full_degree': round(sn_longitude, 4),
            'speed': round(-progressed_planets['NorthNode']['speed'], 4),
            'is_retrograde': True,
            'natal_house': sn_house,
            'changed_sign': sn_sign_en != natal_sn.get('sign'),
            'natal_sign': natal_sn.get('sign'),
            'natal_planet_house': sn_natal_house,
            'changed_house': (sn_natal_house is not None and sn_house != sn_natal_house),
            'natal_degree': natal_sn.get('degree'),
        }

    # Chiron (как в натальном расчёте — с обработкой ошибок эфемерид)
    chiron_id = MINOR_PLANETS.get('Chiron')
    if chiron_id is not None:
        try:
            result = swe.calc_ut(progressed_jd, chiron_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
            if result and len(result[0]) > 0 and result[0][0] >= 0:
                longitude = result[0][0]
                speed = result[0][3] if len(result[0]) > 3 else 0
                sign_en, sign_ru = get_zodiac_sign(longitude)
                natal_chiron = natal['planets'].get('Chiron', {})
                ch_house = get_house_for_longitude(longitude, natal['houses'])
                ch_natal_house = natal_chiron.get('house')
                progressed_planets['Chiron'] = {
                    'planet': 'Chiron',
                    'sign': sign_en,
                    'sign_ru': sign_ru,
                    'degree': round(get_zodiac_degree(longitude), 4),
                    'full_degree': round(longitude, 4),
                    'speed': round(speed, 4) if speed else 0,
                    'is_retrograde': speed < 0,
                    'natal_house': ch_house,
                    'changed_sign': sign_en != natal_chiron.get('sign'),
                    'natal_sign': natal_chiron.get('sign'),
                    'natal_planet_house': ch_natal_house,
                    'changed_house': (ch_natal_house is not None and ch_house != ch_natal_house),
                    'natal_degree': natal_chiron.get('degree'),
                }
        except Exception as e:
            print(f"[progressions] Chiron calc error: {e}")

    # 5. Прогрессивные углы и дома (вторичные угловые на натальных координатах)
    eff_lat = lat if lat is not None else 0.0
    eff_lon = lon if lon is not None else 0.0
    progressed_houses_data = calculate_houses(progressed_jd, eff_lat, eff_lon, house_system)

    # 6. Аспекты прогрессивных планет к натальным (тугой орб)
    # Для определения сходящийся/расходящийся считаем позиции чуть позже (+0.1 JD ≈ +36 дней жизни)
    future_longitudes: Dict[str, float] = {}
    for p_name, p_data in progressed_planets.items():
        speed = p_data.get('speed', 0) or 0
        future_longitudes[p_name] = (p_data['full_degree'] + speed * 0.1) % 360

    aspects_to_natal: List[Dict[str, Any]] = []
    for p_name, p_data in progressed_planets.items():
        for n_name, n_data in natal['planets'].items():
            diff = abs(p_data['full_degree'] - n_data['full_degree'])
            if diff > 180:
                diff = 360 - diff

            for aspect_degree, aspect_name in ASPECTS.items():
                deviation = abs(diff - aspect_degree)
                if deviation <= orb:
                    # Сходящийся: через +0.1 JD орб уменьшается (аспект идёт к точности)
                    f_diff = abs(future_longitudes[p_name] - n_data['full_degree'])
                    if f_diff > 180:
                        f_diff = 360 - f_diff
                    applying = abs(f_diff - aspect_degree) < deviation

                    aspects_to_natal.append({
                        'progressed': p_name,
                        'natal': n_name,
                        # дублируем под planet1/planet2 для совместимости с UI-компонентами аспектов
                        'planet1': p_name,
                        'planet2': n_name,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'orb': round(deviation, 2),
                        'exactness': round(100 - deviation / orb * 100, 1),
                        'applying': applying,  # сходящийся (True) / расходящийся (False)
                        'progressed_sign': p_data['sign'],
                        'natal_sign': n_data['sign'],
                        # контекст натальной планеты — нужен LLM для оверлея с наталом
                        'natal_house': n_data.get('house'),
                        'progressed_house': p_data.get('natal_house'),
                    })
                    break

    # Сортируем по точности (самые точные — самые важные в прогрессиях)
    aspects_to_natal.sort(key=lambda x: x['orb'])

    # 7. Прогрессивная лунная фаза — главный маркер этапа ~30-летнего цикла
    lunar_phase = None
    if 'Sun' in progressed_planets and 'Moon' in progressed_planets:
        lunar_phase = get_progressed_lunar_phase(
            progressed_planets['Sun']['full_degree'],
            progressed_planets['Moon']['full_degree'],
        )

    # 8. Тайминги: через сколько лет Солнце и Луна сменят знак
    # (speed = °/эфемеридный день; в прогрессиях 1 день = 1 год жизни)
    for key in ('Sun', 'Moon'):
        p = progressed_planets.get(key)
        if p and p.get('speed') and p['speed'] > 0.001:
            remaining_deg = 30 - p['degree']
            p['years_to_next_sign'] = round(remaining_deg / p['speed'], 1)

    # Нормализованный период (YYYY-MM) — используется как ключ кэширования анализа
    period = target_date.strftime('%Y-%m')

    return {
        'type': 'progressions',
        'method': 'secondary',  # вторичные прогрессии («день за год»)
        'period': period,
        'age_years': round(age_years, 2),
        'target_date': target_date.isoformat(),
        'natal_jd': round(natal_jd, 6),
        'progressed_jd': round(progressed_jd, 6),
        'progressed_planets': progressed_planets,
        'lunar_phase': lunar_phase,
        'progressed_ascendant': progressed_houses_data['ascendant'],
        'progressed_mc': progressed_houses_data['mc'],
        'progressed_houses': progressed_houses_data['houses'],
        'aspects_to_natal': aspects_to_natal,
        'natal_summary': {
            'sun_sign': natal['sun_sign'],
            'sun_sign_ru': natal['sun_sign_ru'],
            'moon_sign': natal['moon_sign'],
            'moon_sign_ru': natal['moon_sign_ru'],
            'ascendant': natal['ascendant'],
            'ascendant_ru': natal['ascendant_ru'],
        },
        'meta': {
            'house_system': house_system,
            'orb': orb,
            'birth_date': birth_date.isoformat() if hasattr(birth_date, 'isoformat') else str(birth_date),
            'birth_place': birth_place,
            'latitude': lat,
            'longitude': lon,
            'timezone': timezone_str,
        },
    }


# ============================================================
# ТРАНЗИТЫ ПО ДНЯМ
# ============================================================

# Орбы транзитов: тугие, день-специфичные. Луна шире (проходит знак за 2.5 дня).
TRANSIT_ORB = 2.0
TRANSIT_MOON_ORB = 3.0

# Медленные планеты — большие темы периода; быстрые — окраска конкретного дня
SLOW_TRANSIT_PLANETS = {'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto', 'NorthNode', 'SouthNode', 'Chiron'}


def calculate_transits(
    birth_date: datetime,
    birth_place: str,
    target_date: Optional[datetime] = None,
    lat: float = None,
    lon: float = None,
    timezone_str: str = None,
    house_system: str = 'Placidus',
    natal_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Транзиты на конкретный день: реальные позиции планет на target_date,
    наложенные на натальную карту.

    natal_override — готовая натальная карта (planets+houses) из БД. Если
    передана, её дома/планеты используются как есть (это гарантирует те же
    дома, что в натальном анализе). Иначе натал считается заново.

    Возвращает:
    - транзитные позиции планет (+ НАТАЛЬНЫЙ дом каждой транзитной планеты —
      какая сфера натальной жизни активирована)
    - аспекты транзитных планет к натальным (тугие орбы, сходящийся/расходящийся)
    - лунную фазу дня (реальная фаза Луны)
    - период = YYYY-MM-DD (ключ кэширования анализа)
    """
    # 1. Натальная карта: готовая из БД (приоритет) или пересчёт
    if natal_override and natal_override.get('planets') and natal_override.get('houses'):
        natal = natal_override
    else:
        natal = calculate_planet_positions(
            birth_date, birth_place, lat, lon, timezone_str, house_system
        )

    # 2. День транзита (по умолчанию — сейчас, UTC; полдень для устойчивости позиций)
    if target_date is None:
        target_date = datetime.now(timezone.utc)
    if target_date.hour == 0 and target_date.minute == 0:
        # Дата без времени → берём полдень UTC (середина дня)
        target_date = target_date.replace(hour=12)
    transit_jd = _datetime_to_utc_jd(target_date)

    # Транзитные дома — дома, построенные на момент транзита по координатам места.
    # Дают второй угол зрения: в каком ТРАНЗИТНОМ доме находится планета сейчас
    # (в дополнение к натальному дому, по которому она «идёт» относительно рождения).
    try:
        transit_houses_data = calculate_houses(transit_jd, lat, lon, house_system)
        transit_houses = transit_houses_data['houses']
    except Exception as e:
        print(f"[transits] transit houses error: {e}")
        transit_houses = None

    # 3. Транзитные планеты
    transit_planets: Dict[str, Any] = {}
    for planet_name, planet_id in PLANETS.items():
        if planet_name == 'SouthNode':
            continue
        try:
            result = swe.calc_ut(transit_jd, planet_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
            longitude = result[0][0]
            speed = result[0][3] if len(result[0]) > 3 else 0
        except Exception as e:
            print(f"[transits] {planet_name} calc error: {e}")
            continue

        sign_en, sign_ru = get_zodiac_sign(longitude)
        is_retrograde = True if planet_name == 'NorthNode' else speed < 0
        natal_planet = natal['planets'].get(planet_name, {})

        transit_planets[planet_name] = {
            'planet': planet_name,
            'sign': sign_en,
            'sign_ru': sign_ru,
            'degree': round(get_zodiac_degree(longitude), 4),
            'full_degree': round(longitude, 4),
            'speed': round(speed, 4) if speed else 0,
            'is_retrograde': is_retrograde,
            # дом транзитной планеты в НАТАЛЬНОЙ системе домов — ключ интерпретации
            'natal_house': get_house_for_longitude(longitude, natal['houses']),
            'transit_house': get_house_for_longitude(longitude, transit_houses) if transit_houses else None,
            'is_slow': planet_name in SLOW_TRANSIT_PLANETS,
            # позиция этой же планеты в натале — для контекста (возвраты и т.п.)
            'natal_sign': natal_planet.get('sign'),
            'natal_planet_house': natal_planet.get('house'),
        }

    # SouthNode — противоположно NorthNode
    if 'NorthNode' in transit_planets:
        nn = transit_planets['NorthNode']
        sn_longitude = (nn['full_degree'] + 180) % 360
        sn_sign_en, sn_sign_ru = get_zodiac_sign(sn_longitude)
        natal_sn = natal['planets'].get('SouthNode', {})
        transit_planets['SouthNode'] = {
            'planet': 'SouthNode',
            'sign': sn_sign_en,
            'sign_ru': sn_sign_ru,
            'degree': round(get_zodiac_degree(sn_longitude), 4),
            'full_degree': round(sn_longitude, 4),
            'speed': round(-nn['speed'], 4),
            'is_retrograde': True,
            'natal_house': get_house_for_longitude(sn_longitude, natal['houses']),
            'transit_house': get_house_for_longitude(sn_longitude, transit_houses) if transit_houses else None,
            'is_slow': True,
            'natal_sign': natal_sn.get('sign'),
            'natal_planet_house': natal_sn.get('house'),
        }

    # Chiron
    chiron_id = MINOR_PLANETS.get('Chiron')
    if chiron_id is not None:
        try:
            result = swe.calc_ut(transit_jd, chiron_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
            if result and len(result[0]) > 0 and result[0][0] >= 0:
                longitude = result[0][0]
                speed = result[0][3] if len(result[0]) > 3 else 0
                sign_en, sign_ru = get_zodiac_sign(longitude)
                natal_chiron = natal['planets'].get('Chiron', {})
                transit_planets['Chiron'] = {
                    'planet': 'Chiron',
                    'sign': sign_en,
                    'sign_ru': sign_ru,
                    'degree': round(get_zodiac_degree(longitude), 4),
                    'full_degree': round(longitude, 4),
                    'speed': round(speed, 4) if speed else 0,
                    'is_retrograde': speed < 0,
                    'natal_house': get_house_for_longitude(longitude, natal['houses']),
                    'transit_house': get_house_for_longitude(longitude, transit_houses) if transit_houses else None,
                    'is_slow': True,
                    'natal_sign': natal_chiron.get('sign'),
                    'natal_planet_house': natal_chiron.get('house'),
                }
        except Exception as e:
            print(f"[transits] Chiron calc error: {e}")

    # 4. Аспекты транзитных планет к натальным
    # Сходящийся/расходящийся: позиции через +0.2 суток (≈5 часов)
    future_longitudes: Dict[str, float] = {}
    for t_name, t_data in transit_planets.items():
        speed = t_data.get('speed', 0) or 0
        future_longitudes[t_name] = (t_data['full_degree'] + speed * 0.2) % 360

    aspects_to_natal: List[Dict[str, Any]] = []
    for t_name, t_data in transit_planets.items():
        max_orb = TRANSIT_MOON_ORB if t_name == 'Moon' else TRANSIT_ORB
        for n_name, n_data in natal['planets'].items():
            diff = abs(t_data['full_degree'] - n_data['full_degree'])
            if diff > 180:
                diff = 360 - diff

            for aspect_degree, aspect_name in ASPECTS.items():
                deviation = abs(diff - aspect_degree)
                if deviation <= max_orb:
                    f_diff = abs(future_longitudes[t_name] - n_data['full_degree'])
                    if f_diff > 180:
                        f_diff = 360 - f_diff
                    applying = abs(f_diff - aspect_degree) < deviation

                    aspects_to_natal.append({
                        'transit': t_name,
                        'natal': n_name,
                        'planet1': t_name,
                        'planet2': n_name,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'orb': round(deviation, 2),
                        'exactness': round(100 - deviation / max_orb * 100, 1),
                        'applying': applying,
                        'is_slow': t_data.get('is_slow', False),
                        'transit_sign': t_data['sign'],
                        'natal_sign': n_data['sign'],
                        'natal_house': n_data.get('house'),
                        # дом транзитной планеты в натальной карте (по чему «идёт»)
                        'transit_house': t_data.get('natal_house'),
                        # дом транзитной планеты в транзитной карте (где она сейчас)
                        'transit_planet_transit_house': t_data.get('transit_house'),
                        # «возврат» — транзитная планета на своём натальном месте
                        'is_return': (t_name == n_name and aspect_name == 'Conjunction'),
                    })
                    break

    # Медленные и точные — первыми (главные темы), потом быстрые
    aspects_to_natal.sort(key=lambda x: (not x['is_slow'], x['orb']))

    # 5. Лунная фаза дня (реальная)
    lunar_phase = None
    if 'Sun' in transit_planets and 'Moon' in transit_planets:
        lunar_phase = get_progressed_lunar_phase(
            transit_planets['Sun']['full_degree'],
            transit_planets['Moon']['full_degree'],
        )

    period = target_date.strftime('%Y-%m-%d')

    return {
        'type': 'transits',
        'period': period,
        'target_date': target_date.isoformat(),
        'transit_jd': round(transit_jd, 6),
        'transit_planets': transit_planets,
        'lunar_phase': lunar_phase,
        'aspects_to_natal': aspects_to_natal,
        'natal_summary': {
            'sun_sign': natal['sun_sign'],
            'sun_sign_ru': natal['sun_sign_ru'],
            'moon_sign': natal['moon_sign'],
            'moon_sign_ru': natal['moon_sign_ru'],
            'ascendant': natal['ascendant'],
            'ascendant_ru': natal['ascendant_ru'],
        },
        'meta': {
            'birth_date': birth_date.isoformat() if hasattr(birth_date, 'isoformat') else str(birth_date),
            'birth_place': birth_place,
            'house_system': house_system,
            'latitude': lat,
            'longitude': lon,
            'timezone': timezone_str,
        },
    }


# ============================================================
# ПРОГРЕССИВНАЯ СИНАСТРИЯ
# ============================================================

# Орб для межкарточных прогрессивных аспектов — тугой, как в прогрессиях
PROGRESSED_SYNASTRY_ORB = 1.5


def _cross_aspects(
    planets_a: Dict[str, Any],
    planets_b: Dict[str, Any],
    houses_b_for_a: Optional[Dict] = None,
    houses_a_for_b: Optional[Dict] = None,
    orb: float = PROGRESSED_SYNASTRY_ORB,
    label_a: str = 'a',
    label_b: str = 'b',
) -> List[Dict[str, Any]]:
    """
    Межкарточные аспекты: планеты A к планетам B.
    Опционально определяет дом планеты A в системе домов B и наоборот.
    Считает сходящийся/расходящийся через скорости планет.
    """
    aspects: List[Dict[str, Any]] = []
    for a_name, a_data in planets_a.items():
        a_lon = a_data.get('full_degree')
        if a_lon is None:
            continue
        a_speed = a_data.get('speed', 0) or 0
        for b_name, b_data in planets_b.items():
            b_lon = b_data.get('full_degree')
            if b_lon is None:
                continue
            b_speed = b_data.get('speed', 0) or 0

            diff = abs(a_lon - b_lon)
            if diff > 180:
                diff = 360 - diff

            for aspect_degree, aspect_name in ASPECTS.items():
                deviation = abs(diff - aspect_degree)
                if deviation <= orb:
                    # сходящийся/расходящийся: позиции через +0.1 «дня» (≈ часть года)
                    fa = (a_lon + a_speed * 0.1) % 360
                    fb = (b_lon + b_speed * 0.1) % 360
                    fdiff = abs(fa - fb)
                    if fdiff > 180:
                        fdiff = 360 - fdiff
                    applying = abs(fdiff - aspect_degree) < deviation

                    entry = {
                        'planet1': a_name,  # планета партнёра A
                        'planet2': b_name,  # планета партнёра B
                        'person1': label_a,
                        'person2': label_b,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'orb': round(deviation, 2),
                        'exactness': round(100 - deviation / orb * 100, 1),
                        'applying': applying,
                        'sign1': a_data.get('sign'),
                        'sign2': b_data.get('sign'),
                    }
                    # дом планеты A в карте B (планета A «гостит» в доме B)
                    if houses_b_for_a:
                        entry['planet1_house_in_2'] = get_house_for_longitude(a_lon, houses_b_for_a)
                    if houses_a_for_b:
                        entry['planet2_house_in_1'] = get_house_for_longitude(b_lon, houses_a_for_b)
                    aspects.append(entry)
                    break

    aspects.sort(key=lambda x: x['orb'])
    return aspects


def calculate_progressed_synastry(
    person1: Dict[str, Any],
    person2: Dict[str, Any],
    target_date: Optional[datetime] = None,
    house_system: str = 'Placidus',
) -> Dict[str, Any]:
    """
    Прогрессивная синастрия — три слоя чтения отношений во времени.

    Каждый партнёр прогрессируется методом «день за год» НА СВОЙ возраст
    на одну целевую дату. Затем строятся слои:

      Слой 1 — ПРОГРЕССИВНАЯ СИНАСТРИЯ:
        аспекты прогр.планеты A ↔ прогр.планеты B (+ дома: прогр.планета A
        в прогрессивных домах B и наоборот). Текущий «сезон» отношений.

      Слой 2 — ПЕРЕКРЁСТНОЕ НАЛОЖЕНИЕ НА НАТАЛ:
        прогр.планеты A → натальные планеты B, и прогр.планеты B → натал A.
        Как развитие каждого активирует изначальную карту партнёра.

      Слой 3 — ДИНАМИКА vs НАТАЛЬНАЯ СИНАСТРИЯ:
        что изменилось относительно натальной синастрии (появилось/ушло).

    person1/person2 — словари с ключами:
      birth_date (datetime), birth_place, lat, lon, timezone, [name]
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc)

    # --- Прогрессии каждого партнёра (на свой возраст, одна дата) ---
    prog1 = calculate_secondary_progressions(
        birth_date=person1['birth_date'], birth_place=person1.get('birth_place', ''),
        target_date=target_date, lat=person1.get('lat'), lon=person1.get('lon'),
        timezone_str=person1.get('timezone'), house_system=house_system,
    )
    prog2 = calculate_secondary_progressions(
        birth_date=person2['birth_date'], birth_place=person2.get('birth_place', ''),
        target_date=target_date, lat=person2.get('lat'), lon=person2.get('lon'),
        timezone_str=person2.get('timezone'), house_system=house_system,
    )

    # --- Натальные карты (для слоёв 2 и 3) ---
    natal1 = calculate_planet_positions(
        person1['birth_date'], person1.get('birth_place', ''),
        person1.get('lat'), person1.get('lon'), person1.get('timezone'), house_system,
    )
    natal2 = calculate_planet_positions(
        person2['birth_date'], person2.get('birth_place', ''),
        person2.get('lat'), person2.get('lon'), person2.get('timezone'), house_system,
    )

    p1_planets = prog1['progressed_planets']
    p2_planets = prog2['progressed_planets']
    p1_houses = prog1['progressed_houses']
    p2_houses = prog2['progressed_houses']

    # === Слой 1: прогрессивная синастрия (прогр A ↔ прогр B) ===
    progressed_synastry_aspects = _cross_aspects(
        p1_planets, p2_planets,
        houses_b_for_a=p2_houses, houses_a_for_b=p1_houses,
        label_a='person1', label_b='person2',
    )

    # === Слой 2: перекрёстное наложение на натал ===
    # прогр.A → натал B
    prog1_to_natal2 = _cross_aspects(
        p1_planets, natal2['planets'],
        houses_b_for_a=natal2['houses'],
        label_a='person1_progressed', label_b='person2_natal',
    )
    # прогр.B → натал A
    prog2_to_natal1 = _cross_aspects(
        p2_planets, natal1['planets'],
        houses_b_for_a=natal1['houses'],
        label_a='person2_progressed', label_b='person1_natal',
    )

    # === Слой 3: динамика относительно натальной синастрии ===
    natal_synastry = calculate_synastry(natal1, natal2)
    natal_pairs = {
        (a['planet1'], a['planet2'], a['aspect']) for a in natal_synastry['aspects']
    }
    progressed_pairs = {
        (a['planet1'], a['planet2'], a['aspect']) for a in progressed_synastry_aspects
    }
    new_aspects = [a for a in progressed_synastry_aspects
                   if (a['planet1'], a['planet2'], a['aspect']) not in natal_pairs]
    faded_aspects = [a for a in natal_synastry['aspects']
                     if (a['planet1'], a['planet2'], a['aspect']) not in progressed_pairs]

    # Прогрессивные лунные фазы обоих — ключевой эмоциональный маркер
    return {
        'type': 'progressed_synastry',
        'target_date': target_date.isoformat(),
        'period': target_date.strftime('%Y-%m-%d'),
        'person1': {
            'name': person1.get('name'),
            'age_years': prog1['age_years'],
            'progressed_planets': p1_planets,
            'progressed_houses': p1_houses,
            'progressed_ascendant': prog1['progressed_ascendant'],
            'lunar_phase': prog1.get('lunar_phase'),
            'natal_summary': prog1.get('natal_summary'),
        },
        'person2': {
            'name': person2.get('name'),
            'age_years': prog2['age_years'],
            'progressed_planets': p2_planets,
            'progressed_houses': p2_houses,
            'progressed_ascendant': prog2['progressed_ascendant'],
            'lunar_phase': prog2.get('lunar_phase'),
            'natal_summary': prog2.get('natal_summary'),
        },
        # Слой 1
        'progressed_synastry_aspects': progressed_synastry_aspects,
        # Слой 2
        'cross_overlay': {
            'prog1_to_natal2': prog1_to_natal2,
            'prog2_to_natal1': prog2_to_natal1,
        },
        # Слой 3
        'dynamics': {
            'natal_synastry_aspects': natal_synastry['aspects'],
            'new_aspects': new_aspects,        # появились в прогрессии
            'faded_aspects': faded_aspects,    # были в натале, нет в прогрессии
            'natal_total': natal_synastry['total_aspects'],
            'progressed_total': len(progressed_synastry_aspects),
        },
    }
