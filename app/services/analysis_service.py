from typing import List, Dict, Any, Optional
from app.services.search_service import (
    search_chunks_by_query,
    search_chunks_simple,
    parse_astrology_query,
    build_search_context,
)
from app.services.llm_adapter import generate_analysis, get_llm_adapter
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template


PLANET_TO_BOOK_ID = {
    "Pluto": 8,
    "Saturn": 20,
    "Neptune": 7,
    "North Node": 6,
    "South Node": 6,
}


def build_analysis_prompt(
    user_query: str,
    chart_data: Optional[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    language: str = "en"
) -> str:
    """Построить промпт для LLM"""
    
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
    Основная функция для поиска и анализа астрологического запроса
    """
    
    parsed_query = parse_astrology_query(query)
    query_language = parsed_query.get('language', 'en')
    
    chunks = await search_chunks_by_query(query, top_k=top_k, chart_data=chart_data)
    
    if not chunks:
        chunks = await search_chunks_simple(query, top_k=top_k)
    
    context = build_search_context(chart_data, chunks)
    
    prompt = build_analysis_prompt(query, chart_data, chunks, query_language)
    
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


async def simple_analyze(
    query: str,
    book_context: str,
    language: str = "en"
) -> str:
    """Простой анализ текста без поиска по БД"""
    prompt = f"""Вы эксперт по астрологии. Проанализируйте следующий контекст и ответьте на вопрос пользователя.

Контекст из книг:
{book_context}

Вопрос: {query}

Ответьте подробно на языке запроса."""
    
    return await generate_analysis(prompt, language)


def build_planet_analysis_prompt(
    planet: str,
    sign: str,
    degree: float,
    house: int,
    house_sign: Optional[str],
    aspects: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    language: str = "en",
    is_retrograde: bool = False
) -> str:
    """Построить промпт для анализа конкретной планеты"""
    
    prompt_parts = []
    labels = get_labels(language)
    system_prompt = get_template('planet', language)
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
    
    prompt_parts.append(f"\n\n{labels['analysis']}")
    prompt_parts.append(labels['please_analyze_planet'])
    
    return "\n".join(prompt_parts)


async def analyze_planet(
    planet: str,
    sign: str,
    degree: float,
    house: int,
    house_sign: Optional[str] = None,
    is_retrograde: bool = False,
    aspects: Optional[List[Dict[str, Any]]] = None,
    language: str = "en",
    top_k: int = 20
) -> Dict[str, Any]:
    """
    Анализ одной планеты
    """
    
    PLANET_TO_RU = {
        'pluto': 'плутон', 'saturn': 'сатурн', 'venus': 'венера',
        'mars': 'марс', 'mercury': 'меркурий', 'jupiter': 'юпитер',
        'sun': 'солнце', 'moon': 'луна', 'uranus': 'уран',
        'neptune': 'нептун', 'north node': 'раху', 'south node': 'кету',
        'lilith': 'лилит', 'chiron': 'хирон', 'nnode': 'раху', 'snode': 'кету'
    }
    
    SIGN_TO_RU = {
        'aries': 'овен', 'taurus': 'телец', 'gemini': 'близнецы',
        'cancer': 'рак', 'leo': 'лев', 'virgo': 'дева',
        'libra': 'весы', 'scorpio': 'скорпион', 'sagittarius': 'стрелец',
        'capricorn': 'козерог', 'aquarius': 'водолей', 'pisces': 'рыбы'
    }
    
    planet_ru = PLANET_TO_RU.get(planet.lower(), planet)
    sign_ru = SIGN_TO_RU.get(sign.lower(), '') if sign else ''
    
    book_id = PLANET_TO_BOOK_ID.get(planet.capitalize())
    if not book_id:
        book_id = None
    
    house_words = {
        1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', 
        6: 'sixth', 7: 'seventh', 8: 'eighth', 9: 'ninth', 
        10: 'tenth', 11: 'eleventh', 12: 'twelfth'
    }
    house_word = house_words.get(house, str(house))
    
    if sign:
        query = f"{planet.lower()} {house_word} house {sign.lower()}"
    else:
        query = f"{planet.lower()} {house_word} house"
    
    chunks = await search_chunks_by_query(query, top_k=top_k, book_id=book_id)
    
    if not chunks:
        chunks = await search_chunks_simple(query, top_k=top_k)
    
    prompt = build_planet_analysis_prompt(
        planet=planet,
        sign=sign,
        degree=degree,
        house=house,
        house_sign=house_sign,
        aspects=aspects or [],
        chunks=chunks,
        language=language,
        is_retrograde=is_retrograde
    )
    
    adapter = get_llm_adapter()
    analysis = await adapter.generate(prompt, language)
    
    return {
        "planet": planet,
        "sign": sign,
        "house": house,
        "is_retrograde": is_retrograde,
        "analysis": analysis,
        "relevant_chunks": chunks
    }


async def get_top_books(top_k: int = 5) -> List[Dict[str, Any]]:
    """Получить топ-K книг из БД через Supabase (по дате создания)"""
    from supabase import create_client
    from app.core.config import settings
    
    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        response = supabase.table("books").select("id,title,content,language").order("created_at", desc=True).limit(top_k).execute()
        
        if response.data:
            return [
                {
                    "id": book["id"],
                    "title": book["title"],
                    "content": book["content"],
                    "language": book.get("language")
                }
                for book in response.data
            ]
        return []
    except Exception as e:
        print(f"Error getting books: {e}")
        return []


async def full_chart_analysis(
    chart_data: Dict[str, Any],
    language: str = "ru",
    top_books: int = 5 # ИСПРАВЛЕНО: уменьшено с 5 до 1 (5 полных книг не влезут в контекст LLM)
) -> Dict[str, Any]:
    """
    Полный анализ натальной карты - ОДИН промпт, ОДИН вызов LLM
    """
    from app.services.llm_adapter import get_llm_adapter
    
    adapter = get_llm_adapter()
    labels = get_labels(language)
    
    books = await get_top_books(top_books)
    
    if not books:
        return {
            "analysis": "Книги не найдены в базе данных.",
            "book_analyses": [],
            "chart_summary": {}
        }
    
    # ВНИМАНИЕ: читаем ВЕСЬ текст книг (без обрезки).
    # Убедитесь, что top_books=1 и размер книги не превышает ~300к символов,
    # иначе LLM вернёт ошибку превышения контекста.
    # Для анализа нескольких книг используйте RAG endpoints (/analysis/planet, /analysis/query).
    
    aspects = chart_data.get('aspects', [])
    aspects_list = []
    for asp in aspects:
        p1 = asp.get('planet1', '?')
        p2 = asp.get('planet2', '?')
        asp_ru = asp.get('aspect_ru', '?')
        aspects_list.append(f"{p1} {asp_ru} {p2}")
    aspects_str = "\n".join(aspects_list) if aspects_list else "Нет аспектов"
    
    books_content = ""
    
    nodes_book = None
    other_books = []
    for book in books:
        if book.get('id') == 22:
            nodes_book = book
        else:
            other_books.append(book)
    
    if nodes_book:
         # Ограничиваем размер контента чтобы не превысить лимит токенов LLM
         content = nodes_book.get('content', '')[:400000]
         books_content += f"\n\n--- КНИГА ОБ УЗЛАХ И ПЛУТОНЕ ---\n{content}"
    
    for i, book in enumerate(other_books, 1):
        # ИСПРАВЛЕНО: убрали обрезку [:10000], читаем всю книгу
        #   content = book.get('content', '')[:10000]
        # books_content += f"\n\n--- Другие книги ---\n{content}"
        content = book.get('content', '')
        books_content += f"\n\n--- КНИГА {i}: {book.get('title', '')} ---\n{content}"
    
    prompt = get_template('synthesis', language)
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)
    
    prompt += f"\n\n=== {labels['natal_chart_label']} ==="
    prompt += f"\nСолнце: {chart_data.get('sun_sign_ru', '?')} в {chart_data.get('sun_sign', '?')}"
    prompt += f"\nЛуна: {chart_data.get('moon_sign_ru', '?')} в {chart_data.get('moon_sign', '?')}"
    prompt += f"\nАсцендент: {chart_data.get('ascendant_ru', '?')} в {chart_data.get('ascendant', '?')}"
    
    planets = chart_data.get('planets', {})
    prompt += f"\n=== {labels['planets']} ==="
    for planet_name, planet_data in sorted(planets.items()):
        sign = planet_data.get('sign', '?')
        sign_ru = planet_data.get('sign_ru', sign)
        house = planet_data.get('house', '?')
        is_retro = planet_data.get('is_retrograde', False)
        rx_str = " (ретроградная)" if is_retro else ""
        prompt += f"\n{planet_name}: в {sign_ru}, {labels['house']} {house}{rx_str}"
    
    houses = chart_data.get('houses', {})
    prompt += f"\n=== {labels['houses']} ==="
    for house_num in range(1, 13):
        if str(house_num) in houses:
            h = houses[str(house_num)]
            prompt += f"\n{labels['house_num']} {house_num}: {h.get('sign_ru', '?')}"
    
    try:
        full_analysis = await adapter.generate(prompt, language)
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
    
    chart_summary = {
        "sun_sign": chart_data.get('sun_sign', '?'),
        "sun_sign_ru": chart_data.get('sun_sign_ru', '?'),
        "moon_sign": chart_data.get('moon_sign', '?'),
        "moon_sign_ru": chart_data.get('moon_sign_ru', '?'),
        "ascendant": chart_data.get('ascendant', '?'),
        "ascendant_ru": chart_data.get('ascendant_ru', '?'),
        "planets_count": len(chart_data.get('planets', {})),
    }
    
    return {
        "analysis": full_analysis,
        "book_analyses": [{"title": b["title"], "analysis": "Использован в общем анализе"} for b in books],
        "chart_summary": chart_summary,
        "language": language
    }
