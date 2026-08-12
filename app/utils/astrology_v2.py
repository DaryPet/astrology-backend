"""
Swiss Ephemeris - the gold standard of astrology
Accurate to fractions of an arcsecond
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

ZODIAC_SIGNS_UK = [
    "Овен", "Телець", "Близнюки", "Рак", "Лев", "Діва",
    "Терези", "Скорпіон", "Стрілець", "Козеріг", "Водолій", "Риби"
]

# All planets including LILITH (Black Moon)
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
    'NorthNode': swe.TRUE_NODE,  # North Node (Rahu)
    'SouthNode': swe.TRUE_NODE,   # South Node (Ketu)
    'Lilith': swe.MEAN_APOG,  # Black Moon - mean apogee (works in Moshier)
}

# Minor planets (asteroids) - require external ephemerides
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
    0: 'Conjunction',
    60: 'Sextile',
    90: 'Square',
    120: 'Trine',
    180: 'Opposition',
}

ASPECTS_RU = {
    0: 'Соединение',
    60: 'Секстиль',
    90: 'Квадрат',
    120: 'Тригон',
    180: 'Оппозиция',
}

ASPECTS_UK = {
    0: "З'єднання",
    60: 'Секстиль',
    90: 'Квадрат',
    120: 'Тригон',
    180: 'Опозиція',
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


def get_zodiac_sign_uk(degree: float) -> str:
    """Convert degree (0-360) to zodiac sign name (UK).

    Separate from get_zodiac_sign() on purpose: that function's 2-tuple
    return is unpacked as `sign_en, sign_ru = get_zodiac_sign(...)` at 14
    call sites — widening it to a 3-tuple would break all of them at once.
    Callers that need the Ukrainian name call this alongside instead.
    """
    index = int(degree / 30) % 12
    return ZODIAC_SIGNS_UK[index]


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
    High-precision planet position calculation
    Uses Swiss Ephemeris (Moshier algorithm) - built-in tables
    Accuracy: ~1 arcsecond
    """
    # Use Moshier ephemeris + FLG_SPEED to get the speed
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
            'sign_uk': 'Невідомо',
            'degree': 0,
            'full_degree': 0,
            'error': str(e)
        }
    
    # result[0] = longitude (ecliptic)
    # result[1] = latitude
    # result[2] = distance
    # result[3] = speed in longitude
    # result[4] = astronomical speed
    
    longitude = result[0][0]
    latitude = result[0][1]
    speed = result[0][3] if len(result[0]) > 3 else 0
    
    # Zodiac sign
    sign_en, sign_ru = get_zodiac_sign(longitude)
    sign_uk = get_zodiac_sign_uk(longitude)
    degree_in_sign = get_zodiac_degree(longitude)

    return {
        'longitude': longitude,  # 0-360
        'latitude': latitude,     # -90 to +90
        'speed': speed,           # degrees per day
        'sign': sign_en,
        'sign_ru': sign_ru,
        'sign_uk': sign_uk,
        'degree': round(degree_in_sign, 4),
        'full_degree': round(longitude, 4),
    }


def calculate_houses(jd: float, lat: float, lon: float, house_system: str = 'Placidus') -> Dict[str, Any]:
    """
    Calculates ALL 12 houses using Swiss Ephemeris
    """
    flags = swe.FLG_MOSEPH
    hsys = HOUSE_SYSTEMS.get(house_system, b'P')
    
    # Get the houses (tuple: (cusps, ascmc))
    # houses[0] - array of cusps (houses 1-12)
    # houses[1] - array of ascendant, MC, ARMC, etc.
    houses = swe.houses(jd, lat, lon, hsys)

    cusps = houses[0]  # 12 house cusps
    ascmc = houses[1]   # [ASC, MC, ARMC, Vertex, Equatorial ASC...]

    # ascmc breakdown:
    # ascmc[0] = ASC (Ascendant)
    # ascmc[1] = MC (Midheaven)
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

    house_names_uk = [
        "Будинок 1", "Будинок 2", "Будинок 3", "Будинок 4",
        "Будинок 5", "Будинок 6", "Будинок 7", "Будинок 8",
        "Будинок 9", "Будинок 10", "Будинок 11", "Будинок 12"
    ]

    house_planets = {
        'Sun': 10,  # Traditionally the Sun in the 10th house
        'Moon': 4,   # The Moon in the 4th house
    }
    
    result_houses = {}
    for i, cusp in enumerate(cusps):
        cusp_longitude = cusp
        sign_en, sign_ru = get_zodiac_sign(cusp_longitude)
        result_houses[i+1] = {
            'house': i + 1,
            'name_en': house_names_en[i],
            'name_ru': house_names_ru[i],
            'name_uk': house_names_uk[i],
            'cusp_longitude': round(cusp_longitude, 4),
            'sign': sign_en,
            'sign_ru': sign_ru,
            'sign_uk': get_zodiac_sign_uk(cusp_longitude),
            'degree': round(get_zodiac_degree(cusp_longitude), 4),
        }

    # ASC and MC from ascmc
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
            'sign_uk': get_zodiac_sign_uk(asc_longitude),
            'degree': round(get_zodiac_degree(asc_longitude), 4),
        },
        'mc': {
            'longitude': round(mc_longitude, 4),
            'sign': mc_sign_en,
            'sign_ru': mc_sign_ru,
            'sign_uk': get_zodiac_sign_uk(mc_longitude),
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
    Main natal chart calculation function
    Uses Swiss Ephemeris for maximum accuracy

    Args:
        birth_date: Date and time of birth (with timezone or UTC)
        birth_place: Name of the birthplace
        lat: Latitude (if known)
        lon: Longitude (if known)
        timezone_str: IANA timezone string (e.g. 'Europe/Moscow')
        house_system: House system (Placidus, Koch, Equal, WholeSign, etc.)
    """
    # If coordinates aren't passed, use UTC
    if lat is None or lon is None:
        # For simplicity use coordinates 0,0 - the prime meridian
        lat, lon = 0.0, 0.0

    # Correct conversion of time to Julian Day
    # If the datetime already has a timezone - convert to UTC
    # If it's naive and timezone_str was passed - apply the timezone before converting
    if birth_date.tzinfo is not None:
        # datetime with a timezone - convert to UTC
        utc_dt = birth_date.astimezone(timezone.utc)
        year, month, day = utc_dt.year, utc_dt.month, utc_dt.day
        hour, minute, second = utc_dt.hour, utc_dt.minute, utc_dt.second
    elif timezone_str:
        # naive datetime + timezone string - apply the timezone
        try:
            tz = ZoneInfo(timezone_str)
            aware_dt = birth_date.replace(tzinfo=tz)
            utc_dt = aware_dt.astimezone(timezone.utc)
            year, month, day = utc_dt.year, utc_dt.month, utc_dt.day
            hour, minute, second = utc_dt.hour, utc_dt.minute, utc_dt.second
        except:
            # If it failed - treat as UTC
            year, month, day = birth_date.year, birth_date.month, birth_date.day
            hour, minute, second = birth_date.hour, birth_date.minute, birth_date.second
    else:
        # naive datetime with no timezone - treat as UTC
        year, month, day = birth_date.year, birth_date.month, birth_date.day
        hour, minute, second = birth_date.hour, birth_date.minute, birth_date.second

    # Julian Day in UTC
    jd = swe.utc_to_jd(year, month, day, hour, minute, second, swe.GREG_CAL)[0]

    # Calculate the planets
    planets = {}

    # Major planets
    for planet_name, planet_id in PLANETS.items():
        if planet_name == 'SouthNode':
            continue  # Calculate after NorthNode
        
        if planet_name == 'NorthNode':
            result = swe.calc_ut(jd, planet_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
            longitude = result[0][0]
            speed = result[0][3] if len(result[0]) > 3 else 0
        elif planet_name == 'Lilith':
            # Black Moon - mean apogee (MEAN_APOG)
            # Calculated via Swiss Ephemeris like a regular planet
            pos = calculate_planet_position(planet_id, jd, lat, lon)
            longitude = pos['full_degree']
            speed = pos['speed']
        else:
            pos = calculate_planet_position(planet_id, jd, lat, lon)
            longitude = pos['full_degree']
            speed = pos['speed']
        
        sign_en, sign_ru = get_zodiac_sign(longitude)
        sign_uk = get_zodiac_sign_uk(longitude)
        # North Node and South Node are always retrograde in astrology
        if planet_name in ('NorthNode', 'SouthNode'):
            is_retrograde = True
        else:
            is_retrograde = speed < 0

        planets[planet_name] = {
            'planet': planet_name,
            'sign': sign_en,
            'sign_ru': sign_ru,
            'sign_uk': sign_uk,
            'degree': round(get_zodiac_degree(longitude), 4),
            'full_degree': round(longitude, 4),
            'speed': round(speed, 4) if speed else 0,
            'is_retrograde': is_retrograde,
        }

    # Add SouthNode (opposite of NorthNode)
    nn_longitude = planets['NorthNode']['full_degree']
    sn_longitude = (nn_longitude + 180) % 360
    sn_sign_en, sn_sign_ru = get_zodiac_sign(sn_longitude)
    planets['SouthNode'] = {
        'planet': 'SouthNode',
        'sign': sn_sign_en,
        'sign_ru': sn_sign_ru,
        'sign_uk': get_zodiac_sign_uk(sn_longitude),
        'degree': round(get_zodiac_degree(sn_longitude), 4),
        'full_degree': round(sn_longitude, 4),
        'speed': round(-planets['NorthNode']['speed'], 4),
        'is_retrograde': True,  # South Node is always retrograde in astrology
    }

    # Calculate Chiron (minor planet/asteroid)
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
                    'sign_uk': get_zodiac_sign_uk(longitude),
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
                    'sign_uk': 'Невідомо',
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
                'sign_uk': 'Невідомо',
                'degree': 0,
                'full_degree': 0,
                'speed': 0,
                'is_retrograde': False,
                'error': str(e)
            }
    
    # Calculate all 12 houses
    houses_data = calculate_houses(jd, lat, lon, house_system)

    # Determine the houses for the planets
    # Find each planet's house
    for planet_name, planet_data in planets.items():
        planet_degree = planet_data['full_degree']
        # Look for the house
        assigned_house = None
        for house_num in range(1, 13):
            cusp_current = houses_data['houses'][house_num]['cusp_longitude']
            cusp_next = houses_data['houses'][house_num % 12 + 1]['cusp_longitude']

            # Check whether the planet is between the cusps
            if cusp_next > cusp_current:
                if cusp_current <= planet_degree < cusp_next:
                    assigned_house = house_num
                    break
            else:
                # Crossing over 0° Aries
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
        'sun_sign_uk': planets['Sun']['sign_uk'],
        'moon_sign': planets['Moon']['sign'],
        'moon_sign_ru': planets['Moon']['sign_ru'],
        'moon_sign_uk': planets['Moon']['sign_uk'],
        'ascendant': houses_data['ascendant']['sign'],
        'ascendant_ru': houses_data['ascendant']['sign_ru'],
        'ascendant_uk': houses_data['ascendant']['sign_uk'],
        'ascendant_degree': houses_data['ascendant']['degree'],
        'mc': houses_data['mc']['sign'],
        'mc_ru': houses_data['mc']['sign_ru'],
        'mc_uk': houses_data['mc']['sign_uk'],
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
                'sign_uk': get_zodiac_sign_uk(pars_fortuna),
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
    Calculates aspects between planets
    """
    aspects = []
    
    planet_list = list(planets.items())
    
    for i, (name1, data1) in enumerate(planet_list):
        for name2, data2 in planet_list[i+1:]:
            lon1 = data1['full_degree']
            lon2 = data2['full_degree']
            
            # Difference along the shortest path
            diff = abs(lon1 - lon2)
            if diff > 180:
                diff = 360 - diff

            # Check each aspect
            for aspect_degree, aspect_name in ASPECTS.items():
                # Orb for this pair of planets
                key = tuple(sorted([name1, name2]))
                orb = ORBS.get(key, 6)
                
                if abs(diff - aspect_degree) <= orb:
                    aspects.append({
                        'planet1': name1,
                        'planet2': name2,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'aspect_uk': ASPECTS_UK[aspect_degree],
                        'orb': round(abs(diff - aspect_degree), 2),
                        'exactness': round(100 - (abs(diff - aspect_degree) / orb * 100), 1),
                    })
                    break
    
    # Sort by exactness
    aspects.sort(key=lambda x: x['exactness'], reverse=True)

    return aspects


def calculate_solar_return(birth_date: datetime, year: int, lat: float = None, lon: float = None) -> Dict[str, Any]:
    """
    Solar Return calculation
    The Sun returns to the same position it held at birth
    """
    if lat is None or lon is None:
        lat, lon = 55.7558, 37.6173
    
    # Birth JD
    birth_jd = swe.utc_to_jd(birth_date.year, birth_date.month, birth_date.day,
                              birth_date.hour, birth_date.minute, birth_date.second,
                              swe.GREG_CAL)[0]

    # Sun's position at birth
    sun_birth = calculate_planet_position(swe.SUN, birth_jd, lat, lon)
    sun_longitude_birth = sun_birth['full_degree']

    # Look for the solar return date in the target year
    # Approximate date - the birthday in the target year
    start_jd = swe.utc_to_jd(year, birth_date.month, birth_date.day,
                              birth_date.hour, birth_date.minute, birth_date.second,
                              swe.GREG_CAL)[0]

    # Look for the exact moment when the Sun is at the target longitude
    # Swe.lun_occult_when_loc could help, but for the Sun we use iteration

    # Scan a few days around the birthday
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
            'exactness': round(100 - best_diff * 10, 2),  # Exactness percentage
        }
    
    return None


def calculate_synastry(chart1: Dict[str, Any], chart2: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synastry calculation (compatibility between two charts)
    """
    aspects = []
    
    # Aspects between the two charts' planets
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
                        'aspect_uk': ASPECTS_UK[aspect_degree],
                        'orb': round(abs(diff - aspect_degree), 2),
                    })
                    break
    
    # Sort by importance
    aspect_priority = {'Conjunction': 5, 'Opposition': 4, 'Trine': 3, 'Square': 2, 'Sextile': 1}
    aspects.sort(key=lambda x: aspect_priority.get(x['aspect'], 0), reverse=True)
    
    return {
        'aspects': aspects,
        'total_aspects': len(aspects),
    }


def get_house_for_longitude(longitude: float, houses: Dict) -> Optional[int]:
    """
    Determines the house number (1-12) from a planet's longitude and the house cusps.
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


# Test function
if __name__ == "__main__":
    # Example calculation
    birth = datetime(1995, 3, 21, 12, 0, 0)

    # Moscow
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
# SECONDARY PROGRESSIONS ("day for a year")
# ============================================================

TROPICAL_YEAR = 365.2422  # tropical year in days
PROGRESSION_ORB = 1.5     # tight orb for progression aspects (standard 1-1.5°)


def _datetime_to_utc_jd(dt: datetime) -> float:
    """Converts a datetime (aware or naive-as-UTC) to Julian Day (UT)"""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return swe.utc_to_jd(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, swe.GREG_CAL)[0]


# Progressed lunar phase (Moon−Sun angle) — the core of secondary progression interpretation.
# 8 phases of 45° each: key stages of the ~30-year cycle of inner development.
LUNAR_PHASES = [
    (0,   'New Moon',          'Новолуние',           'Молодик'),
    (45,  'Crescent',          'Растущий серп',       'Молодий серп'),
    (90,  'First Quarter',     'Первая четверть',     'Перша чверть'),
    (135, 'Gibbous',           'Растущая выпуклая',   'Зростаюча опукла'),
    (180, 'Full Moon',         'Полнолуние',          'Повний Місяць'),
    (225, 'Disseminating',     'Рассеивающая',        'Спадна опукла'),
    (270, 'Last Quarter',      'Последняя четверть',  'Остання чверть'),
    (315, 'Balsamic',          'Бальзамическая',      'Бальзамічна'),
]


def get_progressed_lunar_phase(sun_longitude: float, moon_longitude: float) -> Dict[str, Any]:
    """Determines the progressed lunar phase from the Moon-Sun angle (0-360°)"""
    angle = (moon_longitude - sun_longitude) % 360
    phase_en, phase_ru, phase_uk = LUNAR_PHASES[0][1], LUNAR_PHASES[0][2], LUNAR_PHASES[0][3]
    for start_deg, en, ru, uk in LUNAR_PHASES:
        if angle >= start_deg:
            phase_en, phase_ru, phase_uk = en, ru, uk
    return {
        'angle': round(angle, 2),
        'phase': phase_en,
        'phase_ru': phase_ru,
        'phase_uk': phase_uk,
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
    Secondary Progressions calculation via Swiss Ephemeris.

    "Day for a year" method: each day after birth symbolically equals one
    year of life. Progressed Julian Day:
        progressed_jd = natal_jd + (target_jd - natal_jd) / TROPICAL_YEAR

    Returns:
    - progressed planet positions (+ each progressed planet's natal house)
    - progressed ASC/MC and houses (secondary angles: houses at the
      progressed JD using the natal coordinates)
    - aspects of progressed planets to natal ones (tight orb)
    - age and period
    """
    # 1. Natal chart — reuse the main calculation
    natal = calculate_planet_positions(
        birth_date, birth_place, lat, lon, timezone_str, house_system
    )
    natal_jd = natal['meta']['jd']

    # 2. Date to build progressions for (default — now, UTC)
    if target_date is None:
        target_date = datetime.now(timezone.utc)
    target_jd = _datetime_to_utc_jd(target_date)

    # 3. "Day for a year" formula
    age_years = (target_jd - natal_jd) / TROPICAL_YEAR
    if age_years < 0:
        age_years = 0.0
    progressed_jd = natal_jd + age_years

    # 4. Progressed planets
    progressed_planets: Dict[str, Any] = {}
    for planet_name, planet_id in PLANETS.items():
        if planet_name == 'SouthNode':
            continue  # calculate after NorthNode
        try:
            result = swe.calc_ut(progressed_jd, planet_id, swe.FLG_MOSEPH | swe.FLG_SPEED)
            longitude = result[0][0]
            speed = result[0][3] if len(result[0]) > 3 else 0
        except Exception as e:
            print(f"[progressions] {planet_name} calc error: {e}")
            continue

        sign_en, sign_ru = get_zodiac_sign(longitude)
        sign_uk = get_zodiac_sign_uk(longitude)
        is_retrograde = True if planet_name == 'NorthNode' else speed < 0
        natal_planet = natal['planets'].get(planet_name, {})
        prog_house = get_house_for_longitude(longitude, natal['houses'])
        natal_planet_house = natal_planet.get('house')

        progressed_planets[planet_name] = {
            'planet': planet_name,
            'sign': sign_en,
            'sign_ru': sign_ru,
            'sign_uk': sign_uk,
            'degree': round(get_zodiac_degree(longitude), 4),
            'full_degree': round(longitude, 4),
            'speed': round(speed, 4) if speed else 0,
            'is_retrograde': is_retrograde,
            # progressed planet's house in the NATAL house system (interpretation standard)
            'natal_house': prog_house,
            # whether the planet changed sign relative to the natal — a key marker for analysis
            'changed_sign': sign_en != natal_planet.get('sign'),
            'natal_sign': natal_planet.get('sign'),
            # the house the planet was in natally, and whether it moved to a different house —
            # a marker no less important than a sign change
            'natal_planet_house': natal_planet_house,
            'changed_house': (natal_planet_house is not None and prog_house != natal_planet_house),
            'natal_degree': natal_planet.get('degree'),
        }

    # SouthNode — opposite of NorthNode
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
            'sign_uk': get_zodiac_sign_uk(sn_longitude),
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

    # Chiron (same as in the natal calculation — with ephemeris error handling)
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
                    'sign_uk': get_zodiac_sign_uk(longitude),
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

    # 5. Progressed angles and houses (secondary angulars on natal coordinates)
    eff_lat = lat if lat is not None else 0.0
    eff_lon = lon if lon is not None else 0.0
    progressed_houses_data = calculate_houses(progressed_jd, eff_lat, eff_lon, house_system)

    # 6. Progressed planets' aspects to the natal ones (tight orb)
    # To determine applying/separating, calculate positions a bit later (+0.1 JD ≈ +36 days of life)
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
                    # Applying: at +0.1 JD the orb shrinks (the aspect is moving toward exact)
                    f_diff = abs(future_longitudes[p_name] - n_data['full_degree'])
                    if f_diff > 180:
                        f_diff = 360 - f_diff
                    applying = abs(f_diff - aspect_degree) < deviation

                    aspects_to_natal.append({
                        'progressed': p_name,
                        'natal': n_name,
                        # duplicate under planet1/planet2 for compatibility with aspect UI components
                        'planet1': p_name,
                        'planet2': n_name,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'aspect_uk': ASPECTS_UK[aspect_degree],
                        'orb': round(deviation, 2),
                        'exactness': round(100 - deviation / orb * 100, 1),
                        'applying': applying,  # applying (True) / separating (False)
                        'progressed_sign': p_data['sign'],
                        'natal_sign': n_data['sign'],
                        # natal planet context — needed by the LLM for the natal overlay
                        'natal_house': n_data.get('house'),
                        'progressed_house': p_data.get('natal_house'),
                    })
                    break

    # Sort by exactness (most exact — most important in progressions)
    aspects_to_natal.sort(key=lambda x: x['orb'])

    # 7. Progressed lunar phase — the main marker of the ~30-year cycle stage
    lunar_phase = None
    if 'Sun' in progressed_planets and 'Moon' in progressed_planets:
        lunar_phase = get_progressed_lunar_phase(
            progressed_planets['Sun']['full_degree'],
            progressed_planets['Moon']['full_degree'],
        )

    # 8. Timings: how many years until the Sun and Moon change sign
    # (speed = °/ephemeris day; in progressions 1 day = 1 year of life)
    for key in ('Sun', 'Moon'):
        p = progressed_planets.get(key)
        if p and p.get('speed') and p['speed'] > 0.001:
            remaining_deg = 30 - p['degree']
            p['years_to_next_sign'] = round(remaining_deg / p['speed'], 1)

    # Normalized period (YYYY-MM) — used as the analysis cache key
    period = target_date.strftime('%Y-%m')

    return {
        'type': 'progressions',
        'method': 'secondary',  # secondary progressions ("day for a year")
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
# DAILY TRANSITS
# ============================================================

# Transit orbs: tight, day-specific. The Moon is wider (crosses a sign in 2.5 days).
TRANSIT_ORB = 2.0
TRANSIT_MOON_ORB = 3.0

# Slow planets — big themes of the period; fast ones — the flavor of a specific day
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
    transit_lat: Optional[float] = None,
    transit_lon: Optional[float] = None,
    transit_place: Optional[str] = None,
    exact_time: bool = False,
) -> Dict[str, Any]:
    """
    Transits for a specific day: real planet positions on target_date,
    overlaid on the natal chart.

    natal_override — a ready-made natal chart (planets+houses) from the DB.
    If passed, its houses/planets are used as-is (this guarantees the same
    houses as in the natal analysis). Otherwise the natal chart is calculated
    from scratch.

    transit_lat/transit_lon — coordinates of the transit location. If not
    given, the natal coordinates are used. This matters: transit houses are
    determined relative to where the person is at the moment of the transit.

    Returns:
    - transit planet positions (+ each transit planet's NATAL house — which
      area of natal life is activated)
    - transit houses (houses built on the transit location)
    - aspects of transit planets to natal ones (tight orbs, applying/separating)
    - the day's lunar phase (the real Moon phase)
    - period = YYYY-MM-DD (the analysis cache key)
    """
    # 1. Natal chart: ready-made from the DB (priority) or recalculated
    if natal_override and natal_override.get('planets') and natal_override.get('houses'):
        natal = natal_override
    else:
        natal = calculate_planet_positions(
            birth_date, birth_place, lat, lon, timezone_str, house_system
        )

    # 2. Transit day (default — now, UTC; noon for position stability)
    if target_date is None:
        target_date = datetime.now(timezone.utc)
    if not exact_time and target_date.hour == 0 and target_date.minute == 0:
        # Date with no time → use UTC noon (middle of the day).
        # exact_time=True (e.g. an exact start moment) disables
        # this heuristic — otherwise midnight moments would shift by 12h.
        target_date = target_date.replace(hour=12)
    transit_jd = _datetime_to_utc_jd(target_date)

    # Transit place coordinates: if not passed — use the natal ones
    eff_transit_lat = transit_lat if transit_lat is not None else lat
    eff_transit_lon = transit_lon if transit_lon is not None else lon
    if eff_transit_lat is None:
        eff_transit_lat = 0.0
    if eff_transit_lon is None:
        eff_transit_lon = 0.0

    # Transit houses — houses built for the transit moment using the transit place's coordinates.
    # Give a second angle: which TRANSIT house the planet is in right now
    # (in addition to the natal house it "moves through" relative to birth).
    try:
        transit_houses_data = calculate_houses(transit_jd, eff_transit_lat, eff_transit_lon, house_system)
        transit_houses = transit_houses_data['houses']
        transit_ascendant = transit_houses_data['ascendant']
        transit_mc = transit_houses_data['mc']
    except Exception as e:
        print(f"[transits] transit houses error: {e}")
        transit_houses = None
        transit_ascendant = None
        transit_mc = None

    # 3. Transit planets
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
            'sign_uk': get_zodiac_sign_uk(longitude),
            'degree': round(get_zodiac_degree(longitude), 4),
            'full_degree': round(longitude, 4),
            'speed': round(speed, 4) if speed else 0,
            'is_retrograde': is_retrograde,
            # transit planet's house in the NATAL house system — key to interpretation
            'natal_house': get_house_for_longitude(longitude, natal['houses']),
            'transit_house': get_house_for_longitude(longitude, transit_houses) if transit_houses else None,
            'is_slow': planet_name in SLOW_TRANSIT_PLANETS,
            # this same planet's natal position — for context (returns, etc.)
            'natal_sign': natal_planet.get('sign'),
            'natal_planet_house': natal_planet.get('house'),
        }

    # SouthNode — opposite of NorthNode
    if 'NorthNode' in transit_planets:
        nn = transit_planets['NorthNode']
        sn_longitude = (nn['full_degree'] + 180) % 360
        sn_sign_en, sn_sign_ru = get_zodiac_sign(sn_longitude)
        natal_sn = natal['planets'].get('SouthNode', {})
        transit_planets['SouthNode'] = {
            'planet': 'SouthNode',
            'sign': sn_sign_en,
            'sign_ru': sn_sign_ru,
            'sign_uk': get_zodiac_sign_uk(sn_longitude),
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
                    'sign_uk': get_zodiac_sign_uk(longitude),
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

    # 4. Transit planets' aspects to the natal ones
    # Applying/separating: positions +0.2 days ahead (≈5 hours)
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
                        'aspect_uk': ASPECTS_UK[aspect_degree],
                        'orb': round(deviation, 2),
                        'exactness': round(100 - deviation / max_orb * 100, 1),
                        'applying': applying,
                        'is_slow': t_data.get('is_slow', False),
                        'transit_sign': t_data['sign'],
                        'natal_sign': n_data['sign'],
                        'natal_house': n_data.get('house'),
                        # transit planet's house in the natal chart (what it's "moving through")
                        'transit_house': t_data.get('natal_house'),
                        # transit planet's house in the transit chart (where it is right now)
                        'transit_planet_transit_house': t_data.get('transit_house'),
                        # "return" — the transit planet is at its own natal position
                        'is_return': (t_name == n_name and aspect_name == 'Conjunction'),
                    })
                    break

    # Slow and exact ones first (main themes), then fast ones
    aspects_to_natal.sort(key=lambda x: (not x['is_slow'], x['orb']))

    # 5. Lunar phase of the day (real)
    lunar_phase = None
    if 'Sun' in transit_planets and 'Moon' in transit_planets:
        lunar_phase = get_progressed_lunar_phase(
            transit_planets['Sun']['full_degree'],
            transit_planets['Moon']['full_degree'],
        )

    period = target_date.strftime('%Y-%m-%d')

    # Transit place info for the frontend
    transit_location_info = None
    if transit_lat is not None and transit_lon is not None:
        transit_location_info = {
            'latitude': transit_lat,
            'longitude': transit_lon,
            'place_name': transit_place or birth_place,
        }

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
        'transit_summary': {
            'ascendant': transit_ascendant,
            'mc': transit_mc,
            'location': transit_location_info,
        },
        # Полная карта момента (12 куспидов со знаками) — нужна для хорарного
        # определения значителей (Lord 1/7/10) в daily_forecast_service.
        'transit_houses': transit_houses,
        'meta': {
            'birth_date': birth_date.isoformat() if hasattr(birth_date, 'isoformat') else str(birth_date),
            'birth_place': birth_place,
            'house_system': house_system,
            'latitude': lat,
            'longitude': lon,
            'timezone': timezone_str,
            'transit_latitude': transit_lat if transit_lat != lat else None,
            'transit_longitude': transit_lon if transit_lon != lon else None,
            'transit_place': transit_place,
        },
    }


# ============================================================
# PROGRESSED SYNASTRY
# ============================================================

# Orb for cross-chart progressed aspects — tight, like in progressions
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
    Cross-chart aspects: planets A to planets B.
    Optionally determines planet A's house in chart B's house system and vice versa.
    Determines applying/separating from the planets' speeds.
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
                    # applying/separating: positions +0.1 "day" ahead (≈ a fraction of a year)
                    fa = (a_lon + a_speed * 0.1) % 360
                    fb = (b_lon + b_speed * 0.1) % 360
                    fdiff = abs(fa - fb)
                    if fdiff > 180:
                        fdiff = 360 - fdiff
                    applying = abs(fdiff - aspect_degree) < deviation

                    entry = {
                        'planet1': a_name,  # partner A's planet
                        'planet2': b_name,  # partner B's planet
                        'person1': label_a,
                        'person2': label_b,
                        'aspect': aspect_name,
                        'aspect_ru': ASPECTS_RU[aspect_degree],
                        'aspect_uk': ASPECTS_UK[aspect_degree],
                        'orb': round(deviation, 2),
                        'exactness': round(100 - deviation / orb * 100, 1),
                        'applying': applying,
                        'sign1': a_data.get('sign'),
                        'sign1_ru': a_data.get('sign_ru'),
                        'sign1_uk': a_data.get('sign_uk'),
                        'sign2': b_data.get('sign'),
                        'sign2_ru': b_data.get('sign_ru'),
                        'sign2_uk': b_data.get('sign_uk'),
                    }
                    # planet A's house in chart B (planet A is "visiting" house B)
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
    Progressed synastry — three layers of reading the relationship over time.

    Each partner is progressed by the "day for a year" method TO THEIR OWN
    age on a single target date. Layers are then built:

      Layer 1 — PROGRESSED SYNASTRY:
        aspects of progressed planet A ↔ progressed planet B (+ houses:
        progressed planet A in B's progressed houses and vice versa). The
        relationship's current "season".

      Layer 2 — CROSS OVERLAY ONTO THE NATAL CHART:
        progressed planets A → natal planets B, and progressed planets B →
        natal A. How each partner's development activates the other's
        original chart.

      Layer 3 — DYNAMICS vs NATAL SYNASTRY:
        what has changed relative to the natal synastry (appeared/gone).

    person1/person2 — dicts with keys:
      birth_date (datetime), birth_place, lat, lon, timezone, [name]
    """
    if target_date is None:
        target_date = datetime.now(timezone.utc)

    # --- Each partner's progressions (at their own age, one date) ---
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

    # --- Natal charts (for layers 2 and 3) ---
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

    # === Layer 1: progressed synastry (prog A ↔ prog B) ===
    progressed_synastry_aspects = _cross_aspects(
        p1_planets, p2_planets,
        houses_b_for_a=p2_houses, houses_a_for_b=p1_houses,
        label_a='person1', label_b='person2',
    )

    # === Layer 2: cross overlay onto the natal charts ===
    # prog.A → natal B
    prog1_to_natal2 = _cross_aspects(
        p1_planets, natal2['planets'],
        houses_b_for_a=natal2['houses'],
        label_a='person1_progressed', label_b='person2_natal',
    )
    # prog.B → natal A
    prog2_to_natal1 = _cross_aspects(
        p2_planets, natal1['planets'],
        houses_b_for_a=natal1['houses'],
        label_a='person2_progressed', label_b='person1_natal',
    )

    # === Layer 3: dynamics relative to the natal synastry ===
    natal_synastry = calculate_synastry(natal1, natal2)
    # calculate_synastry() doesn't carry signs — enrich here so faded_aspects
    # (fed into progressed_synastry_analysis's fmt()) has them like _cross_aspects does.
    for a in natal_synastry['aspects']:
        p1_data = natal1['planets'].get(a['planet1'], {})
        p2_data = natal2['planets'].get(a['planet2'], {})
        a['sign1'] = p1_data.get('sign')
        a['sign1_ru'] = p1_data.get('sign_ru')
        a['sign1_uk'] = p1_data.get('sign_uk')
        a['sign2'] = p2_data.get('sign')
        a['sign2_ru'] = p2_data.get('sign_ru')
        a['sign2_uk'] = p2_data.get('sign_uk')
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

    # Both partners' progressed lunar phases — a key emotional marker
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
        # Layer 1
        'progressed_synastry_aspects': progressed_synastry_aspects,
        # Layer 2
        'cross_overlay': {
            'prog1_to_natal2': prog1_to_natal2,
            'prog2_to_natal1': prog2_to_natal1,
        },
        # Layer 3
        'dynamics': {
            'natal_synastry_aspects': natal_synastry['aspects'],
            'new_aspects': new_aspects,        # appeared in the progression
            'faded_aspects': faded_aspects,    # were natal, gone in the progression
            'natal_total': natal_synastry['total_aspects'],
            'progressed_total': len(progressed_synastry_aspects),
        },
    }
