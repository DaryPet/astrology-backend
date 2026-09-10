from fastapi import APIRouter, Depends, HTTPException, Request
from datetime import datetime
import asyncio
import json
import time
from typing import List, Dict, Any, Optional
from slowapi import Limiter
from slowapi.util import get_remote_address

# Initialize Swiss Ephemeris via helper (sets Moshier mode)
from app import swephelper
from app.schemas.schemas import (
    UserCreate, UserResponse, NatalChartCreate, NatalChartResponse,
    InterpretationCreate, InterpretationResponse, BookCreate, BookResponse,
    QueryRequest, SynastryRequest, NatalChartRequest, NatalChartResponseFull,
    TransitRequest, SynastryRequestDirect
)
from app.schemas.analysis import SynastryAnalysisRequest, ProgressionsRequest, ProgressionsAnalysisRequest, TransitsRequest, TransitsAnalysisRequest, ProgressedSynastryRequest, ProgressedSynastryAnalysisRequest, ProgressedSynastryAspectRequest, ProgressedSynastryAspectResponse, DailyForecastRequest
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
from app.core.config import settings

# Rate limiter for endpoints
limiter = Limiter(key_func=get_remote_address)

# Geocoding (LocationIQ) and timezone detection
import httpx
from timezonefinder import TimezoneFinder

# Initialize the timezone finder
tf = TimezoneFinder()

# Geocoding cache (simplified in-memory cache)
_geocode_cache = {}
_cache_ttl = 3600  # 1 hour

# Natal chart analysis cache (protection against repeat LLM calls)
_analysis_cache = {}  # key: "birth_date|birth_place" -> (result_dict, timestamp)
_ANALYSIS_CACHE_TTL = 300  # 5 minutes
_ANALYSIS_CACHE_MAX_SIZE = 1000  # max 1000 entries

async def get_coordinates(place: str) -> tuple:
    """
    Get precise coordinates from a place name for astrological calculations

    Coordinate precision is critical for astrology.
    Returns precise coordinates or raises an exception.
    """
    cache_key = f"geocode:{place.lower().strip()}"

    # Check the cache
    if cache_key in _geocode_cache:
        cached_data, timestamp = _geocode_cache[cache_key]
        if time.time() - timestamp < _cache_ttl:
            return cached_data

    attempts = [{"accept-language": "ru"}, {"accept-language": "en"}]
    last_error = None

    async with httpx.AsyncClient(timeout=8.0) as client:
        for params_extra in attempts:
            try:
                resp = await client.get(
                    "https://api.locationiq.com/v1/search",
                    params={
                        "key": settings.LOCATIONIQ_ACCESS_TOKEN,
                        "q": place,
                        "format": "json",
                        "limit": 1,
                        **params_extra,
                    },
                )
                if resp.status_code == 200 and resp.json():
                    loc = resp.json()[0]
                    lat, lon = float(loc["lat"]), float(loc["lon"])

                    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                        raise ValueError(f"Invalid coordinates: ({lat}, {lon})")

                    result = (lat, lon)
                    _geocode_cache[cache_key] = (result, time.time())

                    print(f"Geocode success for '{place}': ({lat:.6f}, {lon:.6f})")
                    return result
            except Exception as e:
                last_error = str(e)
                print(f"Geocoding error for '{place}' ({params_extra}): {e}")
                continue

    error_msg = f"Cannot geocode location: '{place}'. Last error: {last_error}"
    print(f"❌ CRITICAL: {error_msg}")
    raise ValueError(error_msg)


def get_timezone(lat: float, lon: float) -> Optional[str]:
    """Determine the timezone from coordinates"""
    try:
        timezone_str = tf.timezone_at(lat=lat, lng=lon)
        if timezone_str:
            return timezone_str
        
        # If we didn't find an exact match, try nearby
        timezone_str = tf.closest_timezone_at(lat=lat, lng=lon)
        return timezone_str or "UTC"
    except Exception as e:
        print(f"Timezone detection error for ({lat}, {lon}): {e}")
        return "UTC"

async def autocomplete_place(query: str, lang: Optional[str] = None) -> List[Dict[str, Any]]:
    """Returns a list of places for autocomplete with improved formatting and search"""
    if len(query) < 2:
        return []

    # Determine the language if not passed
    if lang is None:
        if any('\u0400' <= c <= '\u04FF' for c in query):
            lang = 'ru'
        else:
            lang = 'en'

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(
                "https://api.locationiq.com/v1/autocomplete",
                params={
                    "key": settings.LOCATIONIQ_ACCESS_TOKEN,
                    "q": query,
                    "limit": 10,
                    "accept-language": lang,
                },
            )
        if resp.status_code != 200:
            print(f"Autocomplete error for '{query}': HTTP {resp.status_code} {resp.text}")
            return []
        locations = resp.json()
        if not locations:
            return []

        # Sort by relevance (major cities first)
        def location_score(loc):
            address = loc["display_name"].lower()
            query_lower = query.lower()
            if address.startswith(query_lower):
                return 10
            return 1

        sorted_locations = sorted(locations, key=location_score, reverse=True)

        results = []
        for loc in sorted_locations[:10]:
            address = loc["display_name"]
            address_parts = address.split(', ')

            if len(address_parts) >= 2:
                display_name = f"{address_parts[0]}, {address_parts[1]}"
            else:
                display_name = address_parts[0]

            lat, lon = float(loc["lat"]), float(loc["lon"])
            timezone_str = get_timezone(lat, lon)

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
                "lat": lat,
                "lon": lon,
                "latitude": lat,
                "longitude": lon,
                "timezone": timezone_str,
                "type": place_type,
                "country": address_parts[-1] if address_parts else ""
            })

        return results
    except Exception as e:
        print(f"Autocomplete error for '{query}': {e}")
        return []

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime

# Initialize Swiss Ephemeris via helper (sets Moshier mode)
from app import swephelper

from app.schemas.schemas import (
    UserCreate, UserResponse, NatalChartCreate, NatalChartResponse,
    InterpretationCreate, InterpretationResponse, BookCreate, BookResponse,
    QueryRequest, SynastryRequest, NatalChartRequest, NatalChartResponseFull,
    TransitRequest, SynastryRequestDirect, AnalysisRequest, AnalysisResponse
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

@router.post("/books/process")
async def process_book_api(filename: str):
    """Process a book: download from Supabase -> parse -> split into chunks -> save to the DB"""
    from app.services.book_processor import process_book_async
    result = await process_book_async(filename)
    return result


# ============================================
# GEOCODE SERVICES
# ============================================

@router.get("/geocode/coordinates")
async def geocode_coordinates(lat: float, lon: float):
    """
    Get the timezone from coordinates
    """
    return {"timezone": get_timezone(lat, lon)}

@router.get("/geocode/autocomplete")
async def geocode_autocomplete(q: str, lang: Optional[str] = None):
    """
    Autocomplete for a city input

    Returns a list of candidate cities for the entered text
    Supports the lang parameter to force a language ('ru', 'en')
    If no language is given, it's auto-detected from the input text
    """
    results = await autocomplete_place(q, lang)
    return results


# ============================================
# NATAL CHART CALCULATION (without DB)
# ============================================

@router.post("/chart/calculate")
async def calculate_natal_chart(request: NatalChartRequest) -> NatalChartResponseFull:
    """
    Calculate a natal chart directly (without saving to the DB)

    Requires:
    - birth_date: Date and time of birth
    - birth_place: Place name (exact city/place name)
    - timezone: Timezone (IANA, e.g. "Europe/Moscow")
    - house_system: House system (Placidus, Equal, WholeSign, etc.)
    """
    # Validate input before processing
    if not request.birth_place or request.birth_place.strip() == '':
        if request.latitude is None or request.longitude is None:
            raise HTTPException(
                status_code=400,
                detail="Either 'birth_place' or both 'latitude' and 'longitude' must be provided. "
                       "Please enter a valid birth location."
            )
    
    # Get PRECISE coordinates from the place name
    # Precision is critical for astrology - no fallback to Moscow!
    # Use the coordinates that were passed, or determine them ourselves
    if request.latitude is not None and request.longitude is not None:
        lat, lon = request.latitude, request.longitude
    else:
        try:
            lat, lon = await get_coordinates(request.birth_place)
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
        'sun_sign_uk': chart.get('sun_sign_uk'),
        'moon_sign': chart['moon_sign'],
        'moon_sign_ru': chart['moon_sign_ru'],
        'moon_sign_uk': chart.get('moon_sign_uk'),
        'ascendant': chart['ascendant'],
        'ascendant_ru': chart['ascendant_ru'],
        'ascendant_uk': chart.get('ascendant_uk'),
        'ascendant_degree': chart['ascendant_degree'],
        'mc': chart['mc'],
        'mc_ru': chart['mc_ru'],
        'mc_uk': chart.get('mc_uk'),
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
    Direct synastry calculation between two charts
    """
    # Get PRECISE coordinates for the first chart
    # Use the coordinates that were passed, or determine them ourselves
    if request.chart1.latitude is not None and request.chart1.longitude is not None:
        lat1, lon1 = request.chart1.latitude, request.chart1.longitude
    else:
        try:
            lat1, lon1 = await get_coordinates(request.chart1.birth_place)
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
    
    # Get PRECISE coordinates for the second chart
    # Use the coordinates that were passed, or determine them ourselves
    if request.chart2.latitude is not None and request.chart2.longitude is not None:
        lat2, lon2 = request.chart2.latitude, request.chart2.longitude
    else:
        try:
            lat2, lon2 = await get_coordinates(request.chart2.birth_place)
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
    if payload.stream:
        from fastapi.responses import StreamingResponse
        from app.services.synastry_service import analyze_synastry_aspect_stream
        return StreamingResponse(
            _sse(analyze_synastry_aspect_stream(
                planet1=payload.planet1,
                planet2=payload.planet2,
                aspect_name=payload.aspect_name,
                aspect_name_ru=payload.aspect_name_ru,
                orb=payload.orb,
                language=payload.language,
                top_k=20,
                mode=payload.mode
            )),
            media_type="text/event-stream",
        )

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
    Search and analyze an astrological query

    Main endpoint for:
    1. Searching relevant book excerpts for the query
    2. Building a natal chart (if data is provided)
    3. Analysis via LLM using the chart's context

    Request:
    - query: str (e.g. "Saturn 7th house")
    - chart_data: Optional[NatalChartRequest] - data for building the chart
    - top_k: int = 5 - number of chunks to analyze

    Response:
    - query: the original query
    - query_language: the detected language
    - parsed_query: extracted astrological entities
    - chart_data: the calculated natal chart (if provided)
    - relevant_chunks: found excerpts with a similarity score
    - analysis: the LLM's analysis result
    """
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
    Search and analyze an astrological query WITH a natal chart

    Same as /analysis/query, but calculates a natal chart
    from the given birth data
    """
    from app.services.analysis_service import analyze_astrology_query
    
    chart_data = None
    
    if payload.chart_data:
        birth_request = payload.chart_data
        
        if birth_request.latitude is not None and birth_request.longitude is not None:
            lat, lon = birth_request.latitude, birth_request.longitude
        else:
            try:
                lat, lon = await get_coordinates(birth_request.birth_place)
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
                'sun_sign_uk': chart.get('sun_sign_uk'),
                'moon_sign': chart['moon_sign'],
                'moon_sign_ru': chart['moon_sign_ru'],
                'moon_sign_uk': chart.get('moon_sign_uk'),
                'ascendant': chart['ascendant'],
                'ascendant_ru': chart['ascendant_ru'],
                'ascendant_uk': chart.get('ascendant_uk'),
                'mc': chart['mc'],
                'mc_ru': chart['mc_ru'],
                'mc_uk': chart.get('mc_uk'),
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
    Analysis of a single planet on click/hover
    """
    from app.services.analysis_service import analyze_planet
    
    # The Nodes are always retrograde — hardcoded ahead of any logic
    if payload.planet in ('NorthNode', 'North Node', 'SouthNode', 'South Node'):
        is_retrograde = True
    else:
        is_retrograde = payload.is_retrograde
        if not is_retrograde and payload.chart_data:
            planets_data = payload.chart_data.get('planets', {})
            planet_key = payload.planet.replace(' ', '')
            planet_data = planets_data.get(planet_key) or planets_data.get(payload.planet, {})
            is_retrograde = planet_data.get('is_retrograde', False)

    if payload.stream:
        from fastapi.responses import StreamingResponse
        from app.services.analysis_service import analyze_planet_stream
        return StreamingResponse(
            _sse(analyze_planet_stream(
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
            )),
            media_type="text/event-stream",
        )

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


_SSE_HEARTBEAT_SECONDS = 15


def _sse(gen):
    """Wrap an event-dict async generator as SSE frames.

    Each yielded {"event": <type>, "data": <dict>} becomes
    "event: <type>\\ndata: <json>\\n\\n". Data is always JSON — analysis text
    contains its own newlines, which would otherwise break SSE framing.
    Contract: plans/streaming-analysis-backend.md (event table, step 4).

    Heartbeat: the RAG phase + first-paragraph generation can stay silent for
    tens of seconds, long enough for an intermediate proxy to kill an
    apparently-idle connection. While waiting for the next real event, this
    emits an SSE comment (`: ping\\n\\n`) every `_SSE_HEARTBEAT_SECONDS` —
    comments are part of the SSE spec, carry no data, and a conformant
    frontend parser ignores them. The wait uses `asyncio.wait` (not
    `wait_for`) specifically so a timeout does NOT cancel the in-flight
    `__anext__()` — it just re-polls the same pending fetch on the next lap.
    """
    async def _wrapped():
        it = gen.__aiter__()
        pending = asyncio.ensure_future(it.__anext__())
        try:
            while True:
                done, _ = await asyncio.wait({pending}, timeout=_SSE_HEARTBEAT_SECONDS)
                if not done:
                    yield ": ping\n\n"
                    continue
                try:
                    event = pending.result()
                except StopAsyncIteration:
                    break
                pending = asyncio.ensure_future(it.__anext__())
                event_type = event.get("event", "message")
                data = json.dumps(event.get("data", {}), ensure_ascii=False)
                yield f"event: {event_type}\ndata: {data}\n\n"
        finally:
            pending.cancel()
    return _wrapped()


@router.post("/analysis/full")
async def full_chart_analysis_endpoint(request: FullAnalysisRequest):
    """
    Full natal chart analysis based on all books (10+ pages)

    Protection against repeated LLM calls:
    - Key = birth_date + birth_place
    - Cache lasts 5 minutes
    """
    from app.services.analysis_service import full_chart_analysis_v2 as do_full_analysis
    from datetime import datetime

    _t_req = time.perf_counter()

    # === CACHE CHECK ===
    # cache_key = f"{request.birth_date}|{request.birth_place}"
    cache_key = f"{request.birth_date}|{request.birth_place}|{request.mode}|{request.language}"

#     # BECAME:
# cache_key = None  # temporarily disable cache

    if cache_key in _analysis_cache:
        cached_result, timestamp = _analysis_cache[cache_key]
        if time.time() - timestamp < _ANALYSIS_CACHE_TTL:
            # Cache is fresh! Returning WITHOUT an LLM call!
            print(f"[CACHE] Returning cached analysis for {cache_key}")
            return {
                **cached_result,
                "from_cache": True,
                "cached_at": datetime.fromtimestamp(timestamp).isoformat()
            }
        else:
            # Cache expired - remove it
            del _analysis_cache[cache_key]
    
    chart_data = None
    
    if request.chart_data:
        chart_data = request.chart_data
    elif request.birth_date:
        if request.latitude is not None and request.longitude is not None:
            lat, lon = request.latitude, request.longitude
        else:
            try:
                lat, lon = await get_coordinates(request.birth_place)
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
            'sun_sign_uk': chart.get('sun_sign_uk'),
            'moon_sign': chart['moon_sign'],
            'moon_sign_ru': chart['moon_sign_ru'],
            'moon_sign_uk': chart.get('moon_sign_uk'),
            'ascendant': chart['ascendant'],
            'ascendant_ru': chart['ascendant_ru'],
            'ascendant_uk': chart.get('ascendant_uk'),
            'mc': chart['mc'],
            'mc_ru': chart['mc_ru'],
            'mc_uk': chart.get('mc_uk'),
            'planets': chart['planets'],
            'houses': {str(k): v for k, v in chart['houses'].items()},
            'houses_meta': chart.get('houses_meta', {}),
            'meta': chart.get('meta', {}),
            'aspects': aspects,
        }
    
    if not chart_data:
        raise HTTPException(status_code=400, detail="Either chart_data or birth_date must be provided")

    # Geocoding + Swiss Ephemeris, i.e. everything before the analysis starts.
    _t_chart = time.perf_counter()

    if request.stream:
        from app.services.analysis_service import full_chart_analysis_v2_stream
        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            _sse(full_chart_analysis_v2_stream(chart_data=chart_data, language=request.language, mode=request.mode)),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    result = await do_full_analysis(chart_data=chart_data, language=request.language,  mode=request.mode)

    _t_done = time.perf_counter()
    print(
        "[timing] /analysis/full"
        f" prepare={_t_chart - _t_req:.1f}s"
        f" analysis={_t_done - _t_chart:.1f}s"
        f" total={_t_done - _t_req:.1f}s"
    )

    # === SAVE TO CACHE ===
    # Clear old entries if the cache is full
    if len(_analysis_cache) >= _ANALYSIS_CACHE_MAX_SIZE:
        oldest_key = next(iter(_analysis_cache))
        del _analysis_cache[oldest_key]
    
    _analysis_cache[cache_key] = (result, time.time())
    print(f"[CACHE] Saved analysis to cache: {cache_key}")
    
    return {
        'analysis': result['analysis'],
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
    Chat with a personal astrologer agent.
    - Hybrid RAG: search books by the question + by planets
    - Takes the conversation history into account
    - Answers in the context of the natal chart and the full analysis
    """

    chart_type = payload.chart_data.get('type')

    if payload.stream:
        from fastapi.responses import StreamingResponse
        if chart_type == 'synastry':
            from app.services.synastry_service import chat_with_synastry_astrologer_stream
            gen = chat_with_synastry_astrologer_stream(
                question=payload.question,
                chart_data=payload.chart_data,
                full_analysis=payload.summary,
                chat_history=[msg.dict() for msg in payload.chat_history],
                language=payload.language,
                relationship_context=payload.relationship_context
            )
        elif chart_type == 'progressions':
            from app.services.analysis_service import chat_with_progressions_astrologer_stream
            gen = chat_with_progressions_astrologer_stream(
                question=payload.question,
                chart_data=payload.chart_data,
                full_analysis=payload.summary,
                chat_history=[msg.dict() for msg in payload.chat_history],
                language=payload.language
            )
        elif chart_type == 'progressed_synastry':
            from app.services.analysis_service import chat_with_progressed_synastry_astrologer_stream
            gen = chat_with_progressed_synastry_astrologer_stream(
                question=payload.question,
                chart_data=payload.chart_data,
                full_analysis=payload.summary,
                chat_history=[msg.dict() for msg in payload.chat_history],
                language=payload.language,
                relationship_context=payload.relationship_context
            )
        else:
            from app.services.analysis_service import chat_with_astrologer_stream
            gen = chat_with_astrologer_stream(
                question=payload.question,
                chart_data=payload.chart_data,
                full_analysis=payload.summary,
                chat_history=[msg.dict() for msg in payload.chat_history],
                language=payload.language
            )
        return StreamingResponse(_sse(gen), media_type="text/event-stream")

    if chart_type == 'synastry':
        from app.services.synastry_service import chat_with_synastry_astrologer
        result = await chat_with_synastry_astrologer(
            question=payload.question,
            chart_data=payload.chart_data,
            full_analysis=payload.summary,
            chat_history=[msg.dict() for msg in payload.chat_history],
            language=payload.language,
            relationship_context=payload.relationship_context
        )
    elif chart_type == 'progressions':
        from app.services.analysis_service import chat_with_progressions_astrologer
        result = await chat_with_progressions_astrologer(
            question=payload.question,
            chart_data=payload.chart_data,
            full_analysis=payload.summary,
            chat_history=[msg.dict() for msg in payload.chat_history],
            language=payload.language
        )
    elif chart_type == 'progressed_synastry':
        from app.services.analysis_service import chat_with_progressed_synastry_astrologer
        result = await chat_with_progressed_synastry_astrologer(
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
    Full in-depth synastry analysis (hybrid method v2)

    Requires:
    - chart1: first chart's data (birth_date, birth_place, etc.)
    - chart2: second chart's data
    - language: analysis language (ru/en)

    Returns a full synastry analysis (10000+ words),
    using a hybrid search across all books for each aspect.
    """
    from app.services.synastry_service import full_synastry_analysis_v2
    from app.utils.astrology_v2 import calculate_planet_positions, calculate_aspects
    from datetime import datetime
    
    # Function to calculate a chart
    async def calculate_chart(chart_req, chart_num: int):
        # Get coordinates
        if chart_req.latitude is not None and chart_req.longitude is not None:
            lat, lon = chart_req.latitude, chart_req.longitude
        else:
            try:
                lat, lon = await get_coordinates(chart_req.birth_place)
            except ValueError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot determine coordinates for chart {chart_num}: {str(e)}"
                )
        
        # Parse the birth time
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
        
        # Apply the timezone
        if chart_req.timezone:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(chart_req.timezone)
                if birth_datetime.tzinfo is None:
                    birth_datetime = birth_datetime.replace(tzinfo=tz)
            except:
                pass
        
        # Calculate the chart
        chart = calculate_planet_positions(
            birth_date=birth_datetime,
            birth_place=chart_req.birth_place,
            lat=lat,
            lon=lon,
            timezone_str=chart_req.timezone,
            house_system=chart_req.house_system or 'Placidus'
        )
        
        # Add aspects
        aspects = calculate_aspects(chart['planets'])
        chart['aspects'] = aspects

        return chart

    # Calculate both charts
    chart1_data = await calculate_chart(payload.chart1, 1)
    chart2_data = await calculate_chart(payload.chart2, 2)

    # Determine the language
    language = payload.language or "ru"

    synastry_aspects = calculate_synastry(chart1_data, chart2_data).get('aspects', [])

    if payload.stream:
        from app.services.synastry_service import full_synastry_analysis_v2_stream
        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            _sse(full_synastry_analysis_v2_stream(
                chart1_data=chart1_data,
                chart2_data=chart2_data,
                aspects=synastry_aspects,
                overlays=payload.overlays,
                language=language,
                top_k_per_book=payload.top_k_per_book,
                mode=payload.mode,
                relationship_context=payload.relationship_context
            )),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Run the full synastry analysis
    result = await full_synastry_analysis_v2(
        chart1_data=chart1_data,
        chart2_data=chart2_data,
        aspects=synastry_aspects,
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
    Determine synastry relationship types (with streaming support)

    Takes a finished full synastry analysis
    and returns percentages for each relationship type.
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
# SECONDARY PROGRESSIONS
# Access for authenticated users only —
# the feature is tied to SAVED charts (like chat)
# ============================================

def _prepare_birth_datetime(birth_date, birth_time: Optional[str], tz_str: Optional[str]):
    """Unified birth-date prep (time + timezone) — avoids duplicating this code"""
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


async def _resolve_coordinates(latitude: Optional[float], longitude: Optional[float], birth_place: Optional[str]):
    """Coordinates: as given, or geocoded from the place name"""
    if latitude is not None and longitude is not None:
        return latitude, longitude
    if not birth_place or not birth_place.strip():
        raise HTTPException(
            status_code=400,
            detail="Either 'birth_place' or both 'latitude' and 'longitude' must be provided."
        )
    try:
        return await get_coordinates(birth_place)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot determine coordinates for location: '{birth_place}'. Error: {str(e)}"
        )


async def _resolve_transit_coordinates(
    transit_lat: Optional[float],
    transit_lon: Optional[float],
    transit_place: Optional[str],
    natal_lat: Optional[float] = None,
    natal_lon: Optional[float] = None
) -> tuple:
    """Transit location coordinates: as given, geocoded, or else the natal coordinates"""
    if transit_lat is not None and transit_lon is not None:
        return transit_lat, transit_lon
    if transit_place and transit_place.strip():
        try:
            return await get_coordinates(transit_place)
        except ValueError as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot determine coordinates for transit location: '{transit_place}'. Error: {str(e)}"
            )
    # Fallback: use the natal coordinates
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
    Secondary progressions calculation ("day for a year") via Swiss Ephemeris.

    Returns progressed planets (with natal houses), progressed
    ASC/MC/houses, and aspects of the progressions to the natal chart (1.5° orb).
    Requires authorization — this feature is only available for saved charts.
    """
    lat, lon = await _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
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
    AI analysis of secondary progressions: RAG search over the same books + LLM
    ('progressions' template, simple/advanced modes, ru/en languages).

    Protection against repeated LLM calls: in-memory cache keyed by
    birth_date|birth_place|period|mode|language (same TTL as the full analysis).
    """
    from app.services.analysis_service import progressions_analysis
    from datetime import datetime as dt

    # --- Progressions: take ready-made from the request, or calculate on the backend ---
    progressions = payload.progression_data
    if not progressions:
        if not payload.birth_date:
            raise HTTPException(status_code=400, detail="Either 'progression_data' or birth data must be provided")
        lat, lon = await _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
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

    # --- Natal chart: from the request, or reconstructed from progressions meta ---
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

    if payload.stream:
        from app.services.analysis_service import progressions_analysis_stream
        from fastapi.responses import StreamingResponse

        # Stream branch stands BEFORE the cache read/write below (unlike
        # /analysis/full's cache-before-stream — see app/api/INSIGHTS.md,
        # 2026-08-10 open question) — a stream:true request must always get
        # an SSE response, never a cached plain-JSON one; the streamed result
        # also isn't written back into _analysis_cache.
        return StreamingResponse(
            _sse(progressions_analysis_stream(
                natal_chart=natal_chart,
                progressions=progressions,
                language=payload.language,
                top_k_per_book=payload.top_k_per_book,
                mode=payload.mode or 'advanced',
            )),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Cache (same mechanism as /analysis/full) ---
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

    # Attach the calculated data — the frontend can show it without a second request
    result["progression_data"] = progressions

    if len(_analysis_cache) < _ANALYSIS_CACHE_MAX_SIZE:
        _analysis_cache[cache_key] = (result, time.time())

    return result


@router.post("/transits")
@limiter.limit("20/minute")
async def calculate_transits_endpoint(request: Request, payload: TransitsRequest, user = Depends(get_current_user)):
    """
    Transits for a specific day (defaults to today; any day in the past
    or future works). Real planet positions via Swiss Ephemeris, overlaid
    on the natal chart: transit planets' natal houses are calculated from the
    CORRECT natal cusps, not recalculated ones.

    The transit location (transit_place/latitude/longitude) determines the
    transit houses and lunar phase — matters for correct interpretation at
    the current location. Requires authorization — only available for saved charts.
    """
    lat, lon = await _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
    birth_datetime = _prepare_birth_datetime(payload.birth_date, payload.birth_time, payload.timezone)

    # Transit place coordinates (if not specified — use the natal ones)
    transit_lat, transit_lon = await _resolve_transit_coordinates(
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
    AI analysis of the day's transits: RAG search over the same books + LLM
    ('transits' template, simple/advanced modes, ru/en languages).

    Cache: in-memory, keyed by birth_date|birth_place|date|mode|language.

    The transit location (transit_place/latitude/longitude) determines the
    transit houses and lunar phase — matters for correct interpretation at
    the current location.
    """
    from app.services.analysis_service import transits_analysis
    from datetime import datetime as dt

    # --- Transits: take ready-made from the request, or calculate on the backend ---
    transits = payload.transit_data
    # Transit place coordinates (will be determined if needed)
    transit_lat = payload.transit_latitude
    transit_lon = payload.transit_longitude

    if not transits:
        if not payload.birth_date:
            raise HTTPException(status_code=400, detail="Either 'transit_data' or birth data must be provided")
        lat, lon = await _resolve_coordinates(payload.latitude, payload.longitude, payload.birth_place)
        birth_datetime = _prepare_birth_datetime(payload.birth_date, payload.birth_time, payload.timezone)

        # Transit place coordinates (if not specified — use the natal ones)
        transit_lat, transit_lon = await _resolve_transit_coordinates(
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

    # --- Natal chart for the overlay ---
    # Take the READY-MADE natal chart from chart_data (it came from the frontend
    # and already contains the correct houses — the same ones the natal analysis shows).
    # DO NOT recalculate: recalculating could give a different ASC and break the houses.
    natal_chart = payload.natal_chart
    if not natal_chart:
        raise HTTPException(status_code=400, detail="natal_chart is required")

    if payload.stream:
        from app.services.analysis_service import transits_analysis_stream
        from fastapi.responses import StreamingResponse

        # Stream branch stands BEFORE the cache read/write below — same
        # reasoning as /analysis/progressions (see the comment there).
        return StreamingResponse(
            _sse(transits_analysis_stream(
                natal_chart=natal_chart,
                transits=transits,
                language=payload.language,
                top_k_per_book=payload.top_k_per_book,
                mode=payload.mode or 'advanced',
                transit_place=payload.transit_place,
                transit_lat=transit_lat,
                transit_lon=transit_lon,
            )),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Cache (same mechanism as /analysis/progressions) ---
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

    # Attach the calculated data — the frontend can show it without a second request
    result["transit_data"] = transits

    _analysis_cache[cache_key] = (result, time.time())
    return result


@router.post("/daily-forecast")
@limiter.limit("5/minute")
async def daily_forecast_endpoint(request: Request, payload: DailyForecastRequest, user = Depends(get_current_user)):
    """
    Match-day forecast: a HYBRID method based on the EVENT CHART (Frawley, Sports
    Astrology, ch. 2) + classical dignities of the 1/7 significators (see
    plans/daily-forecast-hybrid-method.md — a deliberate departure from the
    book's explicit ban on mixing methods, based on empirical tests).
    INPUT: only the time (target_date, local; transit_timezone) and place
    (transit_place or transit_latitude/longitude) of the match start.
    Natal data is NOT needed (natal_chart is optional — only a personal note for the LLM).
    Chart for the match time+place (Placidus): Lords 1/10 = favorite, Lords 7/4 = opponent;
    ch. 2 testimonies — positions near cusps (2-3°), the Moon's final aspect, Fortune's
    antiscion, Fortune's dispositor, the nodes, combustion 2°, Pluto/Uranus/Saturn;
    hybrid testimonies (Lord 1/7 only) — essential dignity, angularity of the
    planet's own house, retrogradation.
    Response: favorite/opponent (3 sentences each) + verdict + significator_card
    (deterministic card of the 1/7 significators). No numeric score (score/
    category) is output — only a qualitative verdict (match_type).
    The LLM is chosen by the frontend (llm_provider/llm_model, including OpenRouter).
    Spec: app/services/specs/daily_forecast_event_chart_plan.md
    """
    from app.services.daily_forecast_service import daily_forecast_analysis
    from datetime import datetime as dt

    target_date = payload.target_date
    if target_date is not None and target_date.tzinfo is None:
        tz_name = payload.transit_timezone or payload.timezone
        if tz_name:
            try:
                from zoneinfo import ZoneInfo
                target_date = target_date.replace(tzinfo=ZoneInfo(tz_name))
            except Exception as e:
                print(f"[daily-forecast] transit timezone error: {e}")

    # --- Transits: taken ready-made from the request or calculated (same path as /analysis/transits) ---
    transits = payload.transit_data
    transit_lat = payload.transit_latitude
    transit_lon = payload.transit_longitude

    # FRAWLEY (Sports Astrology, ch. 2, "The Method"): an EVENT chart is judged
    # with Placidus — "Use Placidus houses, as with any event chart".
    # Regiomontanus is only for horary QUESTIONS (ch. 1), which is a different method.
    effective_house_system = payload.house_system or 'Placidus'

    # EVENT CHART (Frawley ch. 2): cast ONLY for the time (target_date)
    # and place (transit_place / transit_latitude+longitude) of the match start.
    # Natal / birth_* data is NOT used in this method.
    if not transits:
        if target_date is None:
            raise HTTPException(status_code=400, detail="Either 'transit_data' or 'target_date' (event kick-off time) must be provided")
        transit_lat, transit_lon = await _resolve_transit_coordinates(
            payload.transit_latitude, payload.transit_longitude, payload.transit_place
        )
        try:
            transits = calculate_transits(
                # calculate_transits is a shared function; we pass it the match moment
                # and get a clean event chart back (transit_planets + transit_houses)
                birth_date=target_date,
                birth_place=payload.transit_place or '',
                target_date=target_date,
                lat=transit_lat,
                lon=transit_lon,
                timezone_str=payload.transit_timezone or payload.timezone,
                house_system=effective_house_system,  # FRAWLEY: Placidus for the event chart (ch. 2)
                transit_lat=transit_lat,
                transit_lon=transit_lon,
                exact_time=True,  # exact match start time — do not shift midnight to noon
            )
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Transits calculation error: {str(e)}")

    # Without houses there is nothing to judge the event chart by (the whole method is built
    # on cusps/Lords) — the house calculation may have failed silently (calculate_transits
    # swallows house-calc errors for other endpoints, where houses are optional) or arrived
    # empty in transit_data.
    if not transits.get('transit_houses'):
        raise HTTPException(status_code=502, detail="House calculation failed for the event chart — check coordinates/time")

    # natal_chart is no longer required: it only fed the natal note (a personal
    # accent for the LLM) and does not affect the event chart calculation/scoring.
    natal_chart = payload.natal_chart or {}

    # --- Cache (same mechanism as /analysis/transits; the key includes the model) ---
    meta = transits.get('meta', {})
    period = transits.get('period', '')
    transit_loc = f"{transit_lat},{transit_lon}" if transit_lat is not None else "natal"
    target_time = target_date.isoformat() if target_date else ''
    cache_key = (
        f"daily|{meta.get('birth_date')}|{meta.get('birth_place')}|{period}|{target_time}"
        f"|{payload.language}|{transit_loc}|{payload.llm_provider}|{payload.llm_model}|{effective_house_system}"
        f"|{payload.moon_range_degrees}|{payload.extra_time_possible}"
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


async def _chart_request_to_person(chart_req, name: Optional[str] = None) -> dict:
    """ChartRequest → dict for calculate_progressed_synastry (unified partner format)"""
    lat, lon = await _resolve_coordinates(chart_req.latitude, chart_req.longitude, chart_req.birth_place)
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
    Progressed synastry: each partner is progressed by the "day for a year"
    method to their own age on a single target date (defaults to today; any
    day works). Returns three layers: progressed synastry (prog↔prog),
    overlay onto the natal chart (crosswise), and dynamics relative to the
    natal synastry. Only available for saved synastry charts (requires authorization).
    """
    person1 = await _chart_request_to_person(payload.chart1, getattr(payload.chart1, 'name', None))
    person2 = await _chart_request_to_person(payload.chart2, getattr(payload.chart2, 'name', None))

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
    AI analysis of progressed synastry (RAG + LLM, 'progressed_synastry'
    template, simple/advanced modes, ru/en). Cache keyed by
    progsyn|p1|p2|date|mode|language (same TTL as the other analyses).
    """
    from app.services.analysis_service import progressed_synastry_analysis
    from datetime import datetime as dt

    # --- Calculated data: ready-made from the request, or recalculate ---
    progressed_synastry = payload.progressed_synastry_data
    if not progressed_synastry:
        if not payload.chart1 or not payload.chart2:
            raise HTTPException(status_code=400, detail="Either 'progressed_synastry_data' or chart1+chart2 must be provided")
        person1 = await _chart_request_to_person(payload.chart1, getattr(payload.chart1, 'name', None))
        person2 = await _chart_request_to_person(payload.chart2, getattr(payload.chart2, 'name', None))
        try:
            progressed_synastry = calculate_progressed_synastry(
                person1=person1, person2=person2,
                target_date=payload.target_date,
                house_system=payload.house_system or 'Placidus',
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Progressed synastry calculation error: {str(e)}")

    if payload.stream:
        from app.services.analysis_service import progressed_synastry_analysis_stream
        from fastapi.responses import StreamingResponse

        # Stream branch stands BEFORE the cache read/write below — same
        # reasoning as /analysis/progressions and /analysis/transits (see the
        # comments there / the plan's step 4g): a stream:true request must
        # always get an SSE response, and the streamed result isn't written
        # back into _analysis_cache.
        return StreamingResponse(
            _sse(progressed_synastry_analysis_stream(
                progressed_synastry=progressed_synastry,
                language=payload.language,
                top_k_per_book=payload.top_k_per_book,
                mode=payload.mode or 'advanced',
                relationship_context=payload.relationship_context,
            )),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # --- Cache ---
    period = progressed_synastry.get('period', '')
    p1n = (progressed_synastry.get('person1') or {}).get('name', 'p1')
    p2n = (progressed_synastry.get('person2') or {}).get('name', 'p2')
    cache_key = f"progsyn|{p1n}|{p2n}|{period}|{payload.mode}|{payload.language}|{payload.relationship_context}"

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
        relationship_context=payload.relationship_context,
    )

    result["progressed_synastry_data"] = progressed_synastry
    _analysis_cache[cache_key] = (result, time.time())
    return result


@router.post("/analysis/progressed-synastry/aspect", response_model=ProgressedSynastryAspectResponse)
@limiter.limit("15/minute")
async def analyze_progressed_synastry_aspect_endpoint(request: Request, payload: ProgressedSynastryAspectRequest, user = Depends(get_current_user)):
    """
    Analysis of a single progressed-synastry aspect (clicking an aspect on the frontend).
    Modeled on /synastry/aspect, see specs/progressed_synastry_aspect_click_plan.md.
    """
    from app.services.analysis_service import analyze_progressed_synastry_aspect

    if payload.stream:
        from fastapi.responses import StreamingResponse
        from app.services.analysis_service import analyze_progressed_synastry_aspect_stream
        return StreamingResponse(
            _sse(analyze_progressed_synastry_aspect_stream(
                planet1=payload.planet1,
                planet2=payload.planet2,
                aspect_name=payload.aspect_name,
                layer=payload.layer,
                aspect_name_ru=payload.aspect_name_ru,
                aspect_name_uk=payload.aspect_name_uk,
                orb=payload.orb,
                applying=payload.applying,
                house1=payload.planet1_house,
                house2=payload.planet2_house,
                partner1_name=payload.person1_name,
                partner2_name=payload.person2_name,
                language=payload.language,
                mode=payload.mode or 'advanced',
            )),
            media_type="text/event-stream",
        )

    return await analyze_progressed_synastry_aspect(
        planet1=payload.planet1,
        planet2=payload.planet2,
        aspect_name=payload.aspect_name,
        layer=payload.layer,
        aspect_name_ru=payload.aspect_name_ru,
        aspect_name_uk=payload.aspect_name_uk,
        orb=payload.orb,
        applying=payload.applying,
        house1=payload.planet1_house,
        house2=payload.planet2_house,
        partner1_name=payload.person1_name,
        partner2_name=payload.person2_name,
        language=payload.language,
        mode=payload.mode or 'advanced',
    )
