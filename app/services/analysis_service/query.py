from typing import List, Dict, Any, Optional, AsyncGenerator
from app.services.search_service import (
    search_chunks_by_query,
    search_chunks_simple,
    parse_astrology_query,
    build_search_context,
)
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template


from app.services.analysis_service._shared import (
    PLANET_TO_BOOK_ID,
    stream_verified_analysis,
)


def build_analysis_prompt(
    user_query: str,
    chart_data: Optional[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    language: str = "en"
) -> str:
    """Build the prompt for the LLM"""
    
    prompt_parts = []
    labels = get_labels(language)
    system_prompt = get_template('analysis', language)
    prompt_parts.append(system_prompt)
    
    prompt_parts.append(f"\n\n{labels['query']}")
    prompt_parts.append(user_query)
    
    if chart_data:
        prompt_parts.append(f"\n\n{labels['natal_chart']}")
        
        planets = chart_data.get('planets', {})
        prompt_parts.append(f"\n{labels['planets_in_houses']}")
        for planet_name, planet_data in planets.items():
            sign = planet_data.get('sign', 'Unknown')
            degree = planet_data.get('degree', 0)
            house = planet_data.get('house', '?')
            prompt_parts.append(f"  {planet_name}: {sign} {degree}° ({labels['house']} {house})")
        
        houses = chart_data.get('houses', {})
        prompt_parts.append(f"\n{labels['house_cusps']}")
        for house_num in range(1, 13):
            if house_num in houses:
                house_data = houses[house_num]
                cusp = house_data.get('cusp_longitude', 0)
                sign = house_data.get('sign', 'Unknown')
                prompt_parts.append(f"  {labels['house_num']} {house_num}: {sign} {cusp:.1f}°")
        
        houses_meta = chart_data.get('houses_meta', {})
        if houses_meta:
            pf = houses_meta.get('pars_fortuna', {})
            if pf:
                prompt_parts.append(f"\n{labels['pars_fortuna']}: {pf.get('sign', '?')} {pf.get('degree', 0)}° ({labels['house']} {pf.get('house', '?')})")
    
    if chunks:
        prompt_parts.append(f"\n\n{labels['found_fragments']}")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')
            if len(text) > 600:
                text = text[:600] + "..."
            prompt_parts.append(f"\n[{labels['fragment']} {i}]:\n{text}")
    else:
        # Explicit note when no fragments found
        prompt_parts.append(f"\n\n=== ПРИМЕЧАНИЕ О ДОСТУПНЫХ ИСТОЧНИКАХ ===")
        prompt_parts.append("В библиотеке не найдено релевантных фрагментов по данному запросу. Анализ должен быть основан на общих принципах эволюционной астрологии и предоставленных данных натальной карты.")
    
    prompt_parts.append(f"\n\n{labels['analysis']}")
    prompt_parts.append(labels['please_analyze'])
    
    return "\n".join(prompt_parts)

async def analyze_astrology_query(
    query: str,
    chart_data: Optional[Dict[str, Any]] = None,
    top_k: int = 5,
    llm_provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    Main function for searching and analyzing an astrological query
    """
    
    parsed_query = parse_astrology_query(query)
    query_language = parsed_query.get('language', 'en')
    
    chunks = await search_chunks_by_query(query, top_k=top_k, chart_data=chart_data)
    
    if not chunks:
        chunks = await search_chunks_simple(query, top_k=top_k)
    
    context = build_search_context(chart_data, chunks)
    
    prompt = build_analysis_prompt(query, chart_data, chunks, query_language)

    from app.services.llm_adapter import get_llm_adapter
    adapter = get_llm_adapter(llm_provider or None)
    analysis = await adapter.generate(prompt, query_language)
    
    return {
        'query': query,
        'query_language': query_language,
        'parsed_query': parsed_query,
        'chart_data': chart_data,
        'relevant_chunks': chunks,
        'analysis': analysis,
    }

def build_planet_analysis_prompt(
    planet: str,
    sign: str,
    degree: float,
    house: int,
    house_sign: Optional[str],
    aspects: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    language: str = "en",
    is_retrograde: bool = False,
    mode: str = 'advanced'
) -> str:
    """Build the prompt for analyzing a specific planet"""
    
    prompt_parts = []
    labels = get_labels(language)
    system_prompt = get_template('planet', language, mode)
    prompt_parts.append(system_prompt)
    
    motion_str = labels['retrograde'] if is_retrograde else labels['direct']
    
    prompt_parts.append(f"\n\n{labels['planet_data']}")
    prompt_parts.append(f"{labels['planet']}: {planet}")
    prompt_parts.append(f"{labels['sign']}: {sign}")
    prompt_parts.append(f"{labels['degree']}: {degree}°")
    prompt_parts.append(f"{labels['house']}: {house}")
    if house_sign:
        prompt_parts.append(f"{labels['house_sign']}: {house_sign}")
    prompt_parts.append(f"{labels['motion']}: {motion_str}")
    
    if aspects:
        prompt_parts.append(f"\n{labels['planet_aspects']}")
        for asp in aspects:
            prompt_parts.append(f"  - {asp.get('aspect', 'Unknown')} to {asp.get('planet', 'Unknown')} (orb: {asp.get('orb', 0)}°)")
    
    if chunks:
        prompt_parts.append(f"\n\n{labels['found_fragments']}")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')
            if len(text) > 600:
                text = text[:600] + "..."
            prompt_parts.append(f"\n[{labels['fragment']} {i}]:\n{text}")
    else:
        # Explicit note when no fragments found
        prompt_parts.append(f"\n\n=== ПРИМЕЧАНИЕ О ДОСТУПНЫХ ИСТОЧНИКАХ ===")
        prompt_parts.append("В библиотеке не найдено специфических текстовых фрагментов по данной конфигурации планеты. Анализ должен быть основан на общих принципах эволюционной астрологии.")
    
    prompt_parts.append(f"\n\n{labels['analysis']}")
    prompt_parts.append(labels['please_analyze_planet'])
    
    return "\n".join(prompt_parts)

async def _prepare_planet_analysis(
    planet: str,
    sign: str,
    degree: float,
    house: int,
    house_sign: Optional[str] = None,
    is_retrograde: bool = False,
    aspects: Optional[List[Dict[str, Any]]] = None,
    language: str = "en",
    top_k: int = 20,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    Shared prep for analyze_planet and its streaming twin
    (analyze_planet_stream): RAG search + prompt build, same split as
    _prepare_natal_analysis/_prepare_synastry_analysis — behavior unchanged,
    this is the same code analyze_planet used to run inline.
    """

    PLANET_TO_RU = {
        'pluto': 'плутон', 'saturn': 'сатурн', 'venus': 'венера',
        'mars': 'марс', 'mercury': 'меркурий', 'jupiter': 'юпитер',
        'sun': 'солнце', 'moon': 'луна', 'uranus': 'уран',
        'neptune': 'нептун', 'north node': 'раху', 'south node': 'кету',
        'lilith': 'лилит', 'chiron': 'хирон', 'nnode': 'раху', 'snode': 'кету',
        'ft': 'pars fortuna', 'fortuna': 'pars fortuna', 'pars fortuna': 'pars fortuna',
        'part of fortune': 'pars fortuna', 'парс фортуны': 'pars fortuna'
    }

    SIGN_TO_RU = {
        'aries': 'овен', 'taurus': 'телец', 'gemini': 'близнецы',
        'cancer': 'рак', 'leo': 'лев', 'virgo': 'дева',
        'libra': 'весы', 'scorpio': 'скорпион', 'sagittarius': 'стрелец',
        'capricorn': 'козерог', 'aquarius': 'водолей', 'pisces': 'рыбы'
    }

    planet_ru = PLANET_TO_RU.get(planet.lower(), planet)
    sign_ru = SIGN_TO_RU.get(sign.lower(), '') if sign else ''

    # Use proper name for display and search
    pars_fortuna_names = ['ft', 'fortuna', 'pars fortuna', 'part of fortune', 'парс фортуны']
    if planet.lower() in pars_fortuna_names:
        display_planet = "Pars Fortuna (Парс Фортуны)"
        search_planet = "pars fortuna"
    else:
        display_planet = planet
        search_planet = planet.lower()

    book_id = PLANET_TO_BOOK_ID.get(planet.capitalize())
    if not book_id:
        book_id = None

    house_words = {
        1: 'first', 2: 'second', 3: 'third', 4: 'fourth',
        5: 'fifth', 6: 'sixth', 7: 'seventh', 8: 'eighth',
        9: 'ninth', 10: 'tenth', 11: 'eleventh', 12: 'twelfth'
    }
    house_word = house_words.get(house, str(house))

    if sign:
        query = f"{search_planet} {house_word} house {sign.lower()}"
    else:
        query = f"{search_planet} {house_word} house"

    chunks = await search_chunks_by_query(query, top_k=top_k, book_id=book_id)

    if not chunks:
        chunks = await search_chunks_simple(query, top_k=top_k)

    prompt = build_planet_analysis_prompt(
        planet=display_planet,
        sign=sign,
        degree=degree,
        house=house,
        house_sign=house_sign,
        aspects=aspects or [],
        chunks=chunks,
        language=language,
        is_retrograde=is_retrograde,
        mode=mode
    )

    from app.services.llm_adapter import get_llm_adapter
    return {
        "prompt": prompt,
        "chunks": chunks,
        "adapter": get_llm_adapter(),
    }

async def analyze_planet(
    planet: str,
    sign: str,
    degree: float,
    house: int,
    house_sign: Optional[str] = None,
    is_retrograde: bool = False,
    aspects: Optional[List[Dict[str, Any]]] = None,
    language: str = "en",
    top_k: int = 20,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    Analysis of a single planet
    """
    prep = await _prepare_planet_analysis(
        planet, sign, degree, house, house_sign, is_retrograde,
        aspects, language, top_k, mode
    )
    analysis = await prep["adapter"].generate(prep["prompt"], language)

    return {
        "planet": planet,
        "sign": sign,
        "house": house,
        "is_retrograde": is_retrograde,
        "analysis": analysis,
        "relevant_chunks": prep["chunks"]
    }

async def analyze_planet_stream(
    planet: str,
    sign: str,
    degree: float,
    house: int,
    house_sign: Optional[str] = None,
    is_retrograde: bool = False,
    aspects: Optional[List[Dict[str, Any]]] = None,
    language: str = "en",
    top_k: int = 20,
    mode: str = 'advanced'
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of analyze_planet. analyze_planet never runs an
    anti-fabrication fix pass on its output (single generate() call, text
    returned as-is) — fix_fn is therefore the identity function, same as
    progressed_synastry_analysis_stream's `lambda text: (text, [])`
    (analysis_service.py, see INSIGHTS.md 2026-08-12). Still routed through
    stream_verified_analysis rather than a bespoke raw-relay path, so the SSE
    event contract (stage/delta/final/error) matches every other streaming
    endpoint.
    """
    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_planet_analysis(
        planet, sign, degree, house, house_sign, is_retrograde,
        aspects, language, top_k, mode
    )

    async def finalize(buffer: str, released: str) -> Dict[str, Any]:
        return {
            "planet": planet,
            "sign": sign,
            "house": house,
            "is_retrograde": is_retrograde,
            "analysis": buffer,
            "relevant_chunks": prep["chunks"]
        }

    fix_fn = lambda text: (text, [])

    yield {"event": "stage", "data": {"stage": "generating"}}
    async for event in stream_verified_analysis(prep["adapter"], prep["prompt"], language, fix_fn, finalize):
        yield event
