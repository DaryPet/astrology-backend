import ephem
from datetime import datetime
from typing import List, Dict, Any
import json

ZODIAC_SIGNS = [
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"
]

PLANETS = ['Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto']

def get_zodiac_sign(degree: float) -> str:
    """Convert degree (0-360) to zodiac sign"""
    index = int(degree / 30) % 12
    return ZODIAC_SIGNS[index]

def get_zodiac_degree(degree: float) -> float:
    """Get degree within zodiac sign (0-30)"""
    return degree % 30

def calculate_planet_positions(birth_date: datetime, birth_place: str) -> Dict[str, Any]:
    """Calculate planetary positions for a natal chart"""
    # Parse coordinates from place (simple version)
    lat, lon = parse_location(birth_place)
    
    # Set observer location
    observer = ephem.Observer()
    observer.lat = str(lat)
    observer.lon = str(lon)
    observer.date = birth_date
    
    planets = {}
    for planet_name in PLANETS:
        try:
            if planet_name == 'Sun':
                body = ephem.Sun(observer)
            elif planet_name == 'Moon':
                body = ephem.Moon(observer)
            else:
                body = getattr(ephem, planet_name)(observer)
            
            # Get ecliptic coordinates
            ra = body.ra  # Right Ascension
            dec = body.dec  # Declination
            # Convert to ecliptic longitude
            sun = ephem.Sun(observer)
            lon = ephem.Ecliptic(ra, dec).lon
            lon_deg = float(lon) * 180 / 3.1415926535
            
            sign = get_zodiac_sign(lon_deg)
            sign_degree = get_zodiac_degree(lon_deg)
            
            planets[planet_name] = {
                "planet": planet_name,
                "sign": sign,
                "degree": round(sign_degree, 2),
                "raw_degree": round(lon_deg, 2)
            }
        except Exception as e:
            planets[planet_name] = {"planet": planet_name, "error": str(e)}
    
    # Calculate ASC and MC
    try:
        asc = ephem.ascendant(observer)
        asc_sign = get_zodiac_sign(float(asc) * 180 / 3.1415926535)
        mc = ephem.midnight(observer)
        mc_body = ephem.Mercury(mc)
        mc_ra = mc_body.ra
        mc_deg = float(mc_ra) * 180 / 3.1415926535 * 15  # Rough conversion
    except:
        asc_sign = "Unknown"
        mc_deg = 0
    
    return {
        "planets": planets,
        "ascendant": asc_sign,
        "midheaven": round(mc_deg, 2),
        "sun_sign": planets.get('Sun', {}).get('sign', 'Unknown'),
        "moon_sign": planets.get('Moon', {}).get('sign', 'Unknown')
    }

def parse_location(place: str) -> tuple:
    """Simple location parser - returns default coords"""
    # In production, use geocoding API
    # Default: Moscow
    return (55.7558, 37.6173)

def calculate_aspects(planets: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Calculate aspects between planets"""
    aspects = []
    orb = {
        "conjunction": 8,
        "sextile": 6,
        "square": 8,
        "trine": 8,
        "opposition": 8
    }
    
    planet_list = [p for p in PLANETS if p in planets and 'raw_degree' in planets[p]]
    
    for i, p1 in enumerate(planet_list):
        for p2 in planet_list[i+1:]:
            deg1 = planets[p1]['raw_degree']
            deg2 = planets[p2]['raw_degree']
            diff = abs(deg1 - deg2)
            if diff > 180:
                diff = 360 - diff
            
            # Check aspects
            if diff < orb["conjunction"]:
                aspects.append({"planet1": p1, "planet2": p2, "aspect": "Conjunction", "orb": round(diff, 2)})
            elif 84 < diff < 96:
                aspects.append({"planet1": p1, "planet2": p2, "aspect": "Square", "orb": round(abs(90 - diff), 2)})
            elif 114 < diff < 126:
                aspects.append({"planet1": p1, "planet2": p2, "aspect": "Trine", "orb": round(abs(120 - diff), 2)})
            elif 174 < diff < 186:
                aspects.append({"planet1": p1, "planet2": p2, "aspect": "Opposition", "orb": round(abs(180 - diff), 2)})
            elif 54 < diff < 66:
                aspects.append({"planet1": p1, "planet2": p2, "aspect": "Sextile", "orb": round(abs(60 - diff), 2)})
    
    return aspects

def calculate_solar_return(birth_date: datetime, year: int) -> Dict[str, Any]:
    """Calculate solar return for a given year"""
    # Find when Sun returns to birth Sun position
    target_date = datetime(year, birth_date.month, birth_date.day)
    
    observer = ephem.Observer()
    observer.date = target_date
    
    sun = ephem.Sun(observer)
    sun_lon = float(sun.ecliptic) * 180 / 3.1415926535
    
    return {
        "year": year,
        "date": target_date.isoformat(),
        "sun_longitude": round(sun_lon, 2),
        "sun_sign": get_zodiac_sign(sun_lon)
    }

def calculate_transits(birth_date: datetime, transit_date: datetime) -> Dict[str, Any]:
    """Calculate current planetary transits"""
    return calculate_planet_positions(transit_date, "transit")

def calculate_synastry(chart1: Dict[str, Any], chart2: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate synastry between two charts"""
    aspects = []
    
    for planet in PLANETS:
        if planet in chart1.get('planets', {}) and planet in chart2.get('planets', {}):
            deg1 = chart1['planets'][planet].get('raw_degree', 0)
            deg2 = chart2['planets'][planet].get('raw_degree', 0)
            diff = abs(deg1 - deg2)
            if diff > 180:
                diff = 360 - diff
            
            if diff < 10:
                aspects.append({
                    "planet": planet,
                    "aspect": "Conjunction",
                    "compatibility": "Strong" if diff < 3 else "Moderate"
                })
            elif 115 < diff < 125:
                aspects.append({
                    "planet": planet,
                    "aspect": "Trine",
                    "compatibility": "Strong"
                })
            elif 174 < diff < 186:
                aspects.append({
                    "planet": planet,
                    "aspect": "Opposition",
                    "compatibility": "Challenging"
                })
    
    return {"aspects": aspects}
