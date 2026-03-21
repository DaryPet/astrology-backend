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

# Minor planets available in Moshier
MINOR_PLANETS = {
    'Chiron': swe.CHIRON,
}

# Дополнительные астрологические точки (те что можно вычислить)
# Lilith, Fortune, Vertex вычисляются вручную внутри функции

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
    Расчёт Асцендента, MC и всех 12 домов (Placidus)
    """
    flags = swe.FLG_MOSEPH
    
    # hsys = 'P' для Placidus (система домов)
    hsys = b'P'
    
    # Получаем дома
    houses_data = swe.houses(jd, lat, lon, hsys)
    
    # houses[0] = массив куспидов домов (1-12)
    # houses[1] = массив колдун (ASC, MC, ARMC, RAMC, и т.д.)
    
    cusps = houses_data[0]  # куспиды 1-12 домов
    colors = houses_data[1]  # коллуны
    
    # ASC - 1-й дом
    asc_longitude = cusps[0]
    asc_sign_en, asc_sign_ru = get_zodiac_sign(asc_longitude)
    
    # MC - 10-й дом
    mc_longitude = cusps[9]
    mc_sign_en, mc_sign_ru = get_zodiac_sign(mc_longitude)
    
    # DSC - 7-й дом (противоположно ASC)
    dsc_longitude = (asc_longitude + 180) % 360
    dsc_sign_en, dsc_sign_ru = get_zodiac_sign(dsc_longitude)
    
    # IC - 4-й дом (противоположно MC)
    ic_longitude = (mc_longitude + 180) % 360
    ic_sign_en, ic_sign_ru = get_zodiac_sign(ic_longitude)
    
    # Формируем все дома
    house_names = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th', '11th', '12th']
    houses = {}
    for i, cusp in enumerate(cusps):
        sign_en, sign_ru = get_zodiac_sign(cusp)
        houses[house_names[i]] = {
            'cusp': round(cusp, 4),
            'sign': sign_en,
            'sign_ru': sign_ru,
            'degree': round(get_zodiac_degree(cusp), 4),
        }
    
    return {
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
        'descendant': {
            'longitude': round(dsc_longitude, 4),
            'sign': dsc_sign_en,
            'sign_ru': dsc_sign_ru,
            'degree': round(get_zodiac_degree(dsc_longitude), 4),
        },
        'ic': {
            'longitude': round(ic_longitude, 4),
            'sign': ic_sign_en,
            'sign_ru': ic_sign_ru,
            'degree': round(get_zodiac_degree(ic_longitude), 4),
        },
        'houses': houses,
    }


def calculate_planet_positions(birth_date: datetime, birth_place: str, lat: float = None, lon: float = None) -> Dict[str, Any]:
    """
    Главная функция расчёта натальной карты
    Использует Swiss Ephemeris для максимальной точности
    Включает: планеты, дома, астероиды, дополнительные точки, ретроградность
    """
    # Если координаты не переданы, используем UTC
    if lat is None or lon is None:
        lat, lon = 55.7558, 37.6173  # Москва по умолчанию
    
    # Julian Day
    jd = swe.utc_to_jd(birth_date.year, birth_date.month, birth_date.day, 
                       birth_date.hour, birth_date.minute, birth_date.second, 
                       swe.GREG_CAL)[0]
    
    # FLAGS с включенной скоростью для определения ретроградности
    flags = swe.FLG_MOSEPH | swe.FLG_SPEED
    
    # ===== ОСНОВНЫЕ ПЛАНЕТЫ =====
    planets = {}
    for planet_name, planet_id in PLANETS.items():
        try:
            result = swe.calc_ut(jd, planet_id, flags)
            longitude = result[0][0]
            speed = result[0][3] if len(result[0]) > 3 else 0
            
            sign_en, sign_ru = get_zodiac_sign(longitude)
            retrograde = speed < 0  # Отрицательная скорость = ретроградность
            
            planets[planet_name] = {
                'planet': planet_name,
                'sign': sign_en,
                'sign_ru': sign_ru,
                'degree': round(get_zodiac_degree(longitude), 4),
                'full_degree': round(longitude, 4),
                'speed': round(speed, 4),
                'retrograde': retrograde,
            }
        except Exception as e:
            print(f"Error calculating {planet_name}: {e}")
    
    # ===== УЗЛЫ =====
    # North Node
    try:
        result = swe.calc_ut(jd, PLANETS['NorthNode'], flags)
        nn_longitude = result[0][0]
        nn_sign_en, nn_sign_ru = get_zodiac_sign(nn_longitude)
        planets['NorthNode'] = {
            'planet': 'NorthNode',
            'sign': nn_sign_en,
            'sign_ru': nn_sign_ru,
            'degree': round(get_zodiac_degree(nn_longitude), 4),
            'full_degree': round(nn_longitude, 4),
        }
        
        # South Node (противоположно North Node)
        sn_longitude = (nn_longitude + 180) % 360
        sn_sign_en, sn_sign_ru = get_zodiac_sign(sn_longitude)
        planets['SouthNode'] = {
            'planet': 'SouthNode',
            'sign': sn_sign_en,
            'sign_ru': sn_sign_ru,
            'degree': round(get_zodiac_degree(sn_longitude), 4),
            'full_degree': round(sn_longitude, 4),
        }
    except Exception as e:
        print(f"Error calculating nodes: {e}")
    
    # ===== ДОПОЛНИТЕЛЬНЫЕ ТОЧКИ (Lilith, Chiron, Vertex, Fortune) =====
    # Lilith (Mean Apogee)
    try:
        result = swe.calc_ut(jd, swe.MEAN_MOON_APOG, flags)
        lilith_longitude = result[0][0]
        lilith_sign_en, lilith_sign_ru = get_zodiac_sign(lilith_longitude)
        planets['Lilith'] = {
            'planet': 'Lilith',
            'sign': lilith_sign_en,
            'sign_ru': lilith_sign_ru,
            'degree': round(get_zodiac_degree(lilith_longitude), 4),
            'full_degree': round(lilith_longitude, 4),
        }
    except Exception as e:
        print(f"Error calculating Lilith: {e}")
    
    # Chiron
    try:
        result = swe.calc_ut(jd, swe.CHIRON, flags)
        chiron_longitude = result[0][0]
        chiron_speed = result[0][3] if len(result[0]) > 3 else 0
        chiron_sign_en, chiron_sign_ru = get_zodiac_sign(chiron_longitude)
        planets['Chiron'] = {
            'planet': 'Chiron',
            'sign': chiron_sign_en,
            'sign_ru': chiron_sign_ru,
            'degree': round(get_zodiac_degree(chiron_longitude), 4),
            'full_degree': round(chiron_longitude, 4),
            'speed': round(chiron_speed, 4),
            'retrograde': chiron_speed < 0,
        }
    except Exception as e:
        print(f"Error calculating Chiron: {e}")
    
    # Vertex (требует внешних файлов, пробуем)
    try:
        result = swe.calc_ut(jd, swe.VERTEX, flags)
        vertex_longitude = result[0][0]
        vertex_sign_en, vertex_sign_ru = get_zodiac_sign(vertex_longitude)
        planets['Vertex'] = {
            'planet': 'Vertex',
            'sign': vertex_sign_en,
            'sign_ru': vertex_sign_ru,
            'degree': round(get_zodiac_degree(vertex_longitude), 4),
            'full_degree': round(vertex_longitude, 4),
        }
    except Exception as e:
        print(f"Vertex not available (needs external ephemeris files): {e}")
    
    # Fortune (Lot of Fortune)
    try:
        # Lot of Fortune = ASC + Moon - Sun
        if 'Sun' in planets and 'Moon' in planets:
            sun_deg = planets['Sun']['full_degree']
            moon_deg = planets['Moon']['full_degree']
            asc_deg = swe.houses(jd, lat, lon, b'P')[0][0]
            fortune_longitude = (asc_deg + moon_deg - sun_deg) % 360
            fortune_sign_en, fortune_sign_ru = get_zodiac_sign(fortune_longitude)
            planets['Fortune'] = {
                'planet': 'Fortune',
                'sign': fortune_sign_en,
                'sign_ru': fortune_sign_ru,
                'degree': round(get_zodiac_degree(fortune_longitude), 4),
                'full_degree': round(fortune_longitude, 4),
            }
    except Exception as e:
        print(f"Error calculating Fortune: {e}")
    
    # ===== ДОМА (Placidus) =====
    asc_mc = calculate_ascendant_mc(jd, lat, lon)
    
    # Определяем дом для каждой планеты
    cusps = asc_mc['houses']
    
    # Функция для определения дома планеты
    def get_planet_house(planet_longitude: float, cusps: List) -> int:
        for i, cusp in enumerate(cusps):
            next_cusp = cusps[(i + 1) % 12]
            if i == 11:  # 12th house
                if planet_longitude >= cusp or planet_longitude < next_cusp:
                    return 12
            else:
                if cusp <= planet_longitude < next_cusp:
                    return i + 1
                # Special case for wrap-around at 0
                if cusp > next_cusp:  # House spans 0 degrees
                    if planet_longitude >= cusp or planet_longitude < next_cusp:
                        return i + 1
        return 1  # Default
    
    # Используем ключи '1st', '2nd', etc которые уже есть в houses
    cusp_values = [cusps[h]['cusp'] for h in ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th', '10th', '11th', '12th']]
    
    # Добавляем номер дома каждой планете
    for planet_name, planet_data in planets.items():
        house = get_planet_house(planet_data['full_degree'], cusp_values)
        planets[planet_name]['house'] = house
    
    return {
        'sun_sign': planets['Sun']['sign'],
        'sun_sign_ru': planets['Sun']['sign_ru'],
        'moon_sign': planets['Moon']['sign'],
        'moon_sign_ru': planets['Moon']['sign_ru'],
        'ascendant': asc_mc['ascendant']['sign'],
        'ascendant_ru': asc_mc['ascendant']['sign_ru'],
        'ascendant_degree': asc_mc['ascendant']['degree'],
        'ascendant_full': asc_mc['ascendant']['longitude'],
        'mc': asc_mc['mc']['sign'],
        'mc_ru': asc_mc['mc']['sign_ru'],
        'mc_degree': asc_mc['mc']['degree'],
        'mc_full': asc_mc['mc']['longitude'],
        'descendant': asc_mc['descendant']['sign'],
        'descendant_ru': asc_mc['descendant']['sign_ru'],
        'ic': asc_mc['ic']['sign'],
        'ic_ru': asc_mc['ic']['sign_ru'],
        'planets': planets,
        'houses': asc_mc['houses'],
    }


def calculate_aspects(planets: Dict[str, Any], 
                       asc_longitude: float = None, 
                       mc_longitude: float = None,
                       houses: Dict = None,
                       orb_threshold: float = 8.0) -> List[Dict[str, Any]]:
    """
    Расчёт аспектов между планетами и угловыми точками (ASC, MC, DSC, IC)
    """
    aspects = []
    
    # Добавляем угловые точки к списку планет для расчёта аспектов
    points_to_calc = dict(planets)
    
    if asc_longitude is not None:
        asc_sign, asc_sign_ru = get_zodiac_sign(asc_longitude)
        points_to_calc['Ascendant'] = {
            'planet': 'Ascendant',
            'sign': asc_sign,
            'sign_ru': asc_sign_ru,
            'degree': round(get_zodiac_degree(asc_longitude), 4),
            'full_degree': round(asc_longitude, 4),
        }
    
    if mc_longitude is not None:
        mc_sign, mc_sign_ru = get_zodiac_sign(mc_longitude)
        points_to_calc['MC'] = {
            'planet': 'MC',
            'sign': mc_sign,
            'sign_ru': mc_sign_ru,
            'degree': round(get_zodiac_degree(mc_longitude), 4),
            'full_degree': round(mc_longitude, 4),
        }
    
    # DSC (противоположно ASC)
    if asc_longitude is not None:
        dsc_longitude = (asc_longitude + 180) % 360
        dsc_sign, dsc_sign_ru = get_zodiac_sign(dsc_longitude)
        points_to_calc['Descendant'] = {
            'planet': 'Descendant',
            'sign': dsc_sign,
            'sign_ru': dsc_sign_ru,
            'degree': round(get_zodiac_degree(dsc_longitude), 4),
            'full_degree': round(dsc_longitude, 4),
        }
    
    # IC (противоположно MC)
    if mc_longitude is not None:
        ic_longitude = (mc_longitude + 180) % 360
        ic_sign, ic_sign_ru = get_zodiac_sign(ic_longitude)
        points_to_calc['IC'] = {
            'planet': 'IC',
            'sign': ic_sign,
            'sign_ru': ic_sign_ru,
            'degree': round(get_zodiac_degree(ic_longitude), 4),
            'full_degree': round(ic_longitude, 4),
        }
    
    # Орбы для угловых точек (меньше чем для планет)
    ANGLE_ORBS = {
        ('Sun', 'Ascendant'): 5,
        ('Moon', 'Ascendant'): 5,
        ('Mercury', 'Ascendant'): 4,
        ('Venus', 'Ascendant'): 4,
        ('Mars', 'Ascendant'): 4,
        ('Jupiter', 'Ascendant'): 5,
        ('Saturn', 'Ascendant'): 5,
        ('Sun', 'MC'): 5,
        ('Moon', 'MC'): 5,
    }
    
    planet_list = list(points_to_calc.items())
    
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
                orb = ANGLE_ORBS.get(key, ORBS.get(key, 6))
                
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
