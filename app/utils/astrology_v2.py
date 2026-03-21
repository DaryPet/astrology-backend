"""
Swiss Ephemeris - Золотой стандарт астрологии
Точность до долей секунды дуги
"""
# Use pre-initialized swisseph from helper
from app.swephelper import swe

from datetime import datetime
from typing import Dict, Any, List, Tuple
import math

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

ZODIAC_SIGNS_RU = [
    "Овен", "Телец", "Близнецы", "Рак", "Лев", "Дева",
    "Весы", "Скорпион", "Стрелец", "Козерог", "Водолей", "Рыбы"
]

# Номера планет в Swiss Ephemeris
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
    'NorthNode': swe.TRUE_NODE,  # Северный узел - в Moshier
}

# Minor planets that ARE available in Moshier
MINOR_PLANETS = {
    'Chiron': swe.CHIRON,  # May require external files
    'Ceres': swe.CERES,
    'Pallas': swe.PALLAS,
    'Juno': swe.JUNO,
    'Vesta': swe.VESTA,
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
    # Используем Moshier ephemeris (встроенный, без внешних файлов)
    # Без FLG_SPEED чтобы не требовать внешние файлы
    flags = swe.FLG_MOSEPH
    
    # Get coordinates
    try:
        result = swe.calc_ut(jd, planet_id, flags)
    except Exception as e:
        # Minor planets might not be available in Moshier
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
    # speed may be 0 without FLG_SPEED flag
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


def calculate_ascendant_mc(jd: float, lat: float, lon: float) -> Dict[str, Any]:
    """
    Расчёт Асцендента и Середины Неба (MC)
    """
    flags = swe.FLG_MOSEPH
    
    # Расчёт ASC и MC
    # hsys = 'P' для Placidus (система домов)
    hsys = b'P'
    
    # Получаем дома
    houses = swe.houses(jd, lat, lon, hsys)
    
    # ASC - первый дом
    asc_longitude = houses[0][0]
    sign_en, sign_ru = get_zodiac_sign(asc_longitude)
    
    # MC - 10-й дом
    mc_longitude = houses[1][0]
    mc_sign_en, mc_sign_ru = get_zodiac_sign(mc_longitude)
    
    return {
        'ascendant': {
            'longitude': round(asc_longitude, 4),
            'sign': sign_en,
            'sign_ru': sign_ru,
            'degree': round(get_zodiac_degree(asc_longitude), 4),
        },
        'mc': {
            'longitude': round(mc_longitude, 4),
            'sign': mc_sign_en,
            'sign_ru': mc_sign_ru,
            'degree': round(get_zodiac_degree(mc_longitude), 4),
        }
    }


def calculate_planet_positions(birth_date: datetime, birth_place: str, lat: float = None, lon: float = None) -> Dict[str, Any]:
    """
    Главная функция расчёта натальной карты
    Использует Swiss Ephemeris для максимальной точности
    """
    # Если координаты не переданы, используем UTC
    if lat is None or lon is None:
        # Для простоты используем координаты 0,0
        # В реальном приложении нужно геокодирование
        lat, lon = 55.7558, 37.6173  # Москва по умолчанию
    
    # Julian Day
    jd = swe.utc_to_jd(birth_date.year, birth_date.month, birth_date.day, 
                       birth_date.hour, birth_date.minute, birth_date.second, 
                       swe.GREG_CAL)[0]
    
    # Расчёт планет
    planets = {}
    for planet_name, planet_id in PLANETS.items():
        if planet_name == 'NorthNode':
            # Узлы требуют специальной обработки
            result = swe.calc_ut(jd, planet_id, swe.FLG_MOSEPH)
            longitude = result[0][0]
        else:
            pos = calculate_planet_position(planet_id, jd, lat, lon)
            longitude = pos['full_degree']
            planets[planet_name] = {
                'planet': planet_name,
                'sign': pos['sign'],
                'sign_ru': pos['sign_ru'],
                'degree': pos['degree'],
                'full_degree': pos['full_degree'],
                'speed': round(pos['speed'], 4),
            }
    
    # Добавляем NorthNode
    result = swe.calc_ut(jd, PLANETS['NorthNode'], swe.FLG_MOSEPH)
    nn_longitude = result[0][0]
    nn_sign_en, nn_sign_ru = get_zodiac_sign(nn_longitude)
    planets['NorthNode'] = {
        'planet': 'NorthNode',
        'sign': nn_sign_en,
        'sign_ru': nn_sign_ru,
        'degree': round(get_zodiac_degree(nn_longitude), 4),
        'full_degree': round(nn_longitude, 4),
    }
    
    # Добавляем SouthNode (противоположно NorthNode)
    sn_longitude = (nn_longitude + 180) % 360
    sn_sign_en, sn_sign_ru = get_zodiac_sign(sn_longitude)
    planets['SouthNode'] = {
        'planet': 'SouthNode',
        'sign': sn_sign_en,
        'sign_ru': sn_sign_ru,
        'degree': round(get_zodiac_degree(sn_longitude), 4),
        'full_degree': round(sn_longitude, 4),
    }
    
    # Расчёт ASC и MC
    asc_mc = calculate_ascendant_mc(jd, lat, lon)
    
    # Определяем знак ASC
    sun_sign = planets['Sun']['sign']
    moon_sign = planets['Moon']['sign']
    
    return {
        'sun_sign': planets['Sun']['sign'],
        'sun_sign_ru': planets['Sun']['sign_ru'],
        'moon_sign': planets['Moon']['sign'],
        'moon_sign_ru': planets['Moon']['sign_ru'],
        'ascendant': asc_mc['ascendant']['sign'],
        'ascendant_ru': asc_mc['ascendant']['sign_ru'],
        'ascendant_degree': asc_mc['ascendant']['degree'],
        'mc': asc_mc['mc']['sign'],
        'mc_ru': asc_mc['mc']['sign_ru'],
        'planets': planets,
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
    for asp in aspects[:10]:
        print(f"{asp['planet1']} {asp['aspect_ru']} {asp['planet2']} (orb: {asp['orb']}°)")
    
    print()
    print("=== Солярное возвращение 2025 ===")
    sr = calculate_solar_return(birth, 2025, lat, lon)
    if sr:
        print(f"Дата: {sr['date']}")
        print(f"Точность: {sr['exactness']}%")
