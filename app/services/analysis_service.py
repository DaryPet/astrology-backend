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
from app.services.prompt_templates.languages import normalize_language
from app.services.text_verification import (
    PLANET_RU,
    PLANET_EN,
    PLANET_UK,
    find_fabricated_positions_layered,
    fix_fabricated_positions_layered,
    find_fabricated_aspect_types_layered,
    find_fabricated_aspect_types_single,
    find_fabricated_houses_single,
    find_undercovered_aspects_generic,
)


PLANET_TO_BOOK_ID = {
    "Pluto": 8,
    "Saturn": 20,
    "Neptune": 7,
    "North Node": 6,
    "South Node": 6,
}


# House ordinal words for RAG queries (used in full_chart_analysis_v2 and progressions_analysis)
HOUSE_WORDS = {
    1: "first", 2: "second", 3: "third", 4: "fourth",
    5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth",
    9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth"
}


def _planet_display(planet_name: str, language: str) -> str:
    """PLANET_RU/PLANET_UK/PLANET_EN lookup by language, 3-way replacement for
    the old `PLANET_RU.get(x) if is_ru else PLANET_EN.get(x)` binary pattern."""
    lang = normalize_language(language)
    table = {'ru': PLANET_RU, 'uk': PLANET_UK, 'en': PLANET_EN}[lang]
    return table.get(planet_name, planet_name)


def _lang_key(base: str, language: str) -> str:
    """'sign' -> 'sign_ru'/'sign_uk'/'sign' depending on language — 3-way
    replacement for the old `f"{base}_ru" if is_ru else base` binary pattern."""
    lang = normalize_language(language)
    return base if lang == 'en' else f"{base}_{lang}"


def _localized(d: dict, key: str, language: str, default=None):
    """d.get(key_ru/key_uk/key) based on language — 3-way replacement for the
    old `d.get(key_ru if is_ru else key, default)` binary pattern."""
    return d.get(_lang_key(key, language), d.get(key, default))


def _localized2(d1: dict, d2: dict, key: str, language: str, default=None):
    """Same as _localized but tries d1 then d2 at the SAME localized key
    before falling back to default — matches the old cascading pattern
    `d1.get(key_ru if is_ru else key, d2.get(key_ru if is_ru else key, default))`."""
    k = _lang_key(key, language)
    return d1.get(k, d2.get(k, default))


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
    is_retrograde: bool = False,
    mode: str = 'advanced'
) -> str:
    """Построить промпт для анализа конкретной планеты"""
    
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
    Анализ одной планеты
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


# async def search_chunks_all_books(
#     query: str,
#     top_k_per_book: int = 3
# ) -> List[Dict[str, Any]]:
#     """
#     [v2] Hybrid RAG: takes the top-N chunks from EACH book separately.
#     Guarantees that every book participates in the analysis.
#     """
#     from supabase import create_client
#     from app.core.config import settings
#     from app.services.search_service import search_chunks_hybrid

#     try:
#         supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
#         books_response = supabase.table("books").select("id, title").execute()

#         if not books_response.data:
#             return []

#         # Parallel search across all books via asyncio.gather
#         import asyncio

#         async def search_one_book(book: Dict[str, Any]) -> List[Dict[str, Any]]:
#             chunks = await search_chunks_hybrid(
#                 query,
#                 top_k=top_k_per_book,
#                 book_id=book["id"]
#             )
#             for chunk in chunks:
#                 chunk["book_title"] = book.get("title", "")
#             return chunks

#         results = await asyncio.gather(
#             *[search_one_book(book) for book in books_response.data],
#             return_exceptions=True
#         )

#         all_chunks = []
#         seen_ids = set()
#         for result in results:
#             if isinstance(result, Exception):
#                 print(f"[search_chunks_all_books] Book search error: {result}")
#                 continue
#             for chunk in result:
#                 chunk_id = chunk.get("id")
#                 if chunk_id not in seen_ids:
#                     seen_ids.add(chunk_id)
#                     all_chunks.append(chunk)

#         print(f"[search_chunks_all_books] Total unique chunks: {len(all_chunks)} from {len(books_response.data)} books")
#         return all_chunks

#     except Exception as e:
#         print(f"[search_chunks_all_books] Error: {e}")
#         return []



# Priority books for the predictive methods (id from the books table):
# 29 — "Predictive Astrology: The Eagle and the Lark" (Bernadette Brady) — progressions
# 28 — "Planets in Transit: Life Cycles for Living" (Robert Hand) — transits
PROGRESSIONS_PRIORITY_BOOK_ID = 29
TRANSITS_PRIORITY_BOOK_ID = 28

# User decision (2026-08-02): narrow the RAG for the natal chart (all
# languages) from searching the whole library (~8 books, some of which are
# specialized for OTHER methods — 26 synastry, 28/29 transits/progressions)
# down to a fixed list of relevant books. 22 is the main source (highest
# priority), 25 and 23 supplement it.
NATAL_BOOK_IDS = [22, 25, 23]

# Transits and progressions — same principle: a fixed list instead of "one
# priority book + the entire rest of the catalog" (what search_chunks_priority_book
# used to do). Both methods use the same narrow set (28, 29), rather than
# different priority books each.
TRANSITS_PROGRESSIONS_BOOK_IDS = [28, 29]


async def _fetch_book_titles(book_ids: List[int]) -> Dict[int, str]:
    """
    Названия книг по списку id — один запрос на весь анализ (натальный/
    транзиты/прогрессии), а не на каждый RAG-подзапрос по планете/аспекту,
    как было в search_chunks_all_books/search_chunks_priority_book (там
    таблица books запрашивалась заново на каждый вызов).
    """
    from supabase import create_client
    from app.core.config import settings
    from app.services.supabase_async import run_sync_in_thread

    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        table_call = supabase.table("books").select("id, title").in_("id", book_ids)
        response = await run_sync_in_thread(table_call.execute)
        return {b["id"]: b.get("title", "") for b in (response.data or [])}
    except Exception as e:
        print(f"[_fetch_book_titles] Error: {e}")
        return {}


async def search_chunks_by_book_ids(
    query: str,
    book_ids: List[int],
    book_titles: Dict[int, str],
    top_k_per_book: int = 3,
) -> List[Dict[str, Any]]:
    """
    RAG-поиск, ограниченный конкретным фиксированным списком книг — не всей
    библиотекой (search_chunks_all_books) и не "одна приоритетная + весь
    остальной каталог" (search_chunks_priority_book). Один параллельный
    search_chunks_hybrid на каждую книгу из book_ids; названия книг переданы
    готовыми через book_titles (см. _fetch_book_titles) — не запрашиваются
    здесь заново на каждый подзапрос.
    """
    import asyncio as _asyncio
    from app.services.search_service import search_chunks_hybrid

    results = await _asyncio.gather(
        *[search_chunks_hybrid(query, top_k=top_k_per_book, book_id=bid) for bid in book_ids],
        return_exceptions=True,
    )
    unique: List[Dict[str, Any]] = []
    seen = set()
    for r in results:
        if isinstance(r, Exception):
            print(f"[search_chunks_by_book_ids] Error: {r}")
            continue
        for chunk in (r or []):
            c_id = chunk.get("id")
            if c_id and c_id in seen:
                continue
            if c_id:
                seen.add(c_id)
            chunk["book_title"] = book_titles.get(chunk.get("book_id"), "")
            unique.append(chunk)
    return unique


async def search_chunks_priority_book(
    query: str,
    priority_book_id: int,
    top_k_priority: int = 4,
    top_k_others: int = 4,
) -> List[Dict[str, Any]]:
    """
    RAG с приоритетной книгой: сначала чанки из профильной книги метода
    (фильтр book_id), затем дополнение из остальных книг. Приоритетные — первыми.
    """
    import asyncio as _asyncio
    from supabase import create_client
    from app.core.config import settings
    from app.services.search_service import search_chunks_hybrid
    from app.services.supabase_async import run_sync_in_thread

    try:
        priority_task = search_chunks_hybrid(query, top_k=top_k_priority, book_id=priority_book_id)
        others_task = search_chunks_hybrid(query, top_k=top_k_others)
        priority_chunks, other_chunks = await _asyncio.gather(priority_task, others_task)

        # Book titles
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        table_call = supabase.table("books").select("id, title")
        books_response = await run_sync_in_thread(table_call.execute)
        book_map = {b["id"]: b.get("title", "") for b in (books_response.data or [])}

        # Priority ones first, then the rest; dedup by chunk id
        unique: List[Dict[str, Any]] = []
        seen = set()
        for chunk in (priority_chunks or []) + (other_chunks or []):
            c_id = chunk.get("id")
            if c_id and c_id in seen:
                continue
            if c_id:
                seen.add(c_id)
            chunk["book_title"] = book_map.get(chunk.get("book_id", ""), "")
            unique.append(chunk)

        n_priority = len(priority_chunks or [])
        print(f"[priority_book_search] book {priority_book_id}: {n_priority} priority + {len(unique) - n_priority} others")
        return unique
    except Exception as e:
        print(f"[priority_book_search] Error: {e}")
        return []


async def search_chunks_all_books(
    query: str,
    top_k_per_book: int = 3
) -> List[Dict[str, Any]]:
    """
    [v2] Hybrid RAG: ONE request across all books at once.
    Eliminates the problem of multiple RPC calls.
    """
    from supabase import create_client
    from app.core.config import settings
    from app.services.search_service import search_chunks_hybrid
    from app.services.supabase_async import run_sync_in_thread

    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

        # 1. Get the list of books to map titles
        # Wrap the sync call in an async executor so it doesn't block the event loop
        table_call = supabase.table("books").select("id, title")
        books_response = await run_sync_in_thread(table_call.execute)
        if not books_response.data:
            return []

        book_map = {b["id"]: b.get("title", "") for b in books_response.data}
        total_books = len(books_response.data)

        # 2. ONE request with no book_id filter.
        # Request more chunks to cover all the books
        chunks = await search_chunks_hybrid(
            query,
            top_k=top_k_per_book * total_books
        )

        # 3. Add the book titles
        if chunks:
            for chunk in chunks:
                chunk["book_title"] = book_map.get(chunk.get("book_id", ""), "")

        # Remove duplicates
        unique_chunks = []
        seen_ids = set()
        for chunk in chunks:
            c_id = chunk.get("id")
            if c_id and c_id not in seen_ids:
                seen_ids.add(c_id)
                unique_chunks.append(chunk)
        
        print(f"[search_chunks_all_books] Total unique chunks: {len(unique_chunks)} from {total_books} books")
        return unique_chunks

    except Exception as e:
        print(f"[search_chunks_all_books] Error: {e}")
        return []


async def generate_summary(text: str, language: str = "ru") -> str:
    """
    Generate a short summary (~500 characters) from the given text using LLM.
    Falls back to truncated text if LLM fails.
    """
    from app.services.llm_adapter import get_llm_adapter

    adapter = get_llm_adapter()
    # Truncate input to avoid excessive token usage
    max_input = 100000
    truncated = text[:max_input]

    if language == "ru":
        prompt = f"Сделай краткое резюме этого анализа на 500 символов:\n{truncated}"
    else:
        prompt = f"Summarize this analysis in about 500 characters:\n{truncated}"

    try:
        summary = await adapter.generate(prompt, language)
        # Cap summary length
        if len(summary) > 600:
            summary = summary[:600].rsplit('. ', 1)[0]
        return summary
    except Exception as e:
        print(f"Error generating summary: {e}")
        return truncated[:500]


async def full_chart_analysis_v2(
    chart_data: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    [v2] Полный анализ натальной карты — ГИБРИДНЫЙ подход:
    - Для каждой планеты/аспекта делаем точечный RAG-поиск по ВСЕМ книгам
    - Собираем структурированный промпт
    - Один финальный вызов LLM

    Преимущества vs full_chart_analysis (v1):
    - Все книги участвуют в анализе (не только топ-5)
    - Нет проблемы с превышением контекста (418K токенов)
    - Каждая планета/аспект получает релевантные фрагменты
    """
    import asyncio
    import time as _time
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    # Per-phase timing. Added because the log only ever showed "Sending final
    # prompt": everything happening BEFORE the LLM call was unmeasurable, so the
    # gap between the 71s prompt-to-response and the ~5 minutes users observe
    # had nothing to be attributed to.
    _t_start = _time.perf_counter()

    adapter = get_llm_adapter()
    labels = get_labels(language)

    planets = chart_data.get("planets", {})
    aspects = chart_data.get("aspects", [])
    houses = chart_data.get("houses", {})
    houses_meta = chart_data.get("houses_meta", {})

    # Limits the number of concurrent requests to Supabase — same reason as
    # synastry/progressions/transits (synastry_service.py:599). With the switch
    # to NATAL_BOOK_IDS (3 books instead of the whole library, user decision
    # 2026-08-02) each search_chunks_by_book_ids call makes 3 calls to the
    # thread pool (one search_chunks_hybrid per book; book titles come via
    # book_titles, with no separate request per call — see _fetch_book_titles).
    # 8 tasks × 3 = 24 concurrent thread-pool calls, within the same budget
    # as before (was 12 × 2 = 24 with search_chunks_all_books).
    search_semaphore = asyncio.Semaphore(8)

    # Book titles — one request for the whole analysis, not per RAG sub-request.
    book_titles = await _fetch_book_titles(NATAL_BOOK_IDS)
    _t_titles = _time.perf_counter()

    # --- Step 1: Parallel RAG search for each planet ---
    async def search_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        # Handle Pars Fortuna
        search_name = "pars fortuna" if planet_name.lower() in ["ft", "pars fortuna", "part of fortune", "fortuna", "парс фортуны"] else planet_name.lower()
        query = f"{search_name} {house_word} house {sign.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, NATAL_BOOK_IDS, book_titles, top_k_per_book=top_k_per_book)
        return planet_name, chunks

    # --- Step 2: Parallel RAG search for each aspect ---
    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("planet1", "")
        p2 = asp.get("planet2", "")
        asp_type = asp.get("aspect", asp.get("aspect_ru", ""))
        query = f"{p1.lower()} {asp_type.lower()} {p2.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, NATAL_BOOK_IDS, book_titles, top_k_per_book=5)
        return f"{p1} {asp_type} {p2}", chunks

    print(f"[full_chart_analysis_v2] Starting parallel RAG for {len(planets)} planets and {len(aspects)} aspects")

    planet_tasks = [search_planet(name, data) for name, data in planets.items()]
    aspect_tasks = [search_aspect(asp) for asp in aspects]  # ALL aspects, no cutoff

    # Add Pars Fortuna search task
    pf = houses_meta.get('pars_fortuna', {})
    if pf:
        async def search_pars_fortuna():
            query = "pars fortuna (парс фортуны) дом"
            async with search_semaphore:
                chunks = await search_chunks_by_book_ids(query, NATAL_BOOK_IDS, book_titles, top_k_per_book=top_k_per_book)
            return "Pars Fortuna", chunks
        planet_tasks.append(search_pars_fortuna())

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)
    _t_rag = _time.perf_counter()

    # --- Step 3: Assemble the structured prompt ---
    prompt_parts = []

    # System prompt (use the existing synthesis template)
    synthesis_template = get_template("synthesis", language, mode)

    # Aspects for the template — planet names and aspect name are translated
    # per language (used to take p1/p2 as the raw English key, with asp_ru
    # unconditionally Russian text even for uk/en; because of this, the prompt
    # instruction "bold formula exactly as given in the list" dragged
    # untranslated names into the headings, even though in free text the model
    # corrected itself — see analysis_service.py INSIGHTS.md).
    aspects_list = []
    for asp in aspects:
        p1 = _planet_display(asp.get("planet1", "?"), language)
        p2 = _planet_display(asp.get("planet2", "?"), language)
        asp_name = _localized(asp, "aspect", language, asp.get("aspect", "?"))
        aspects_list.append(f"{p1} {asp_name} {p2}")
    _no_aspects = {'ru': "Нет аспектов", 'uk': "Немає аспектів", 'en': "No aspects"}
    aspects_str = "\n".join(aspects_list) if aspects_list else _no_aspects.get(normalize_language(language), _no_aspects['en'])

    # Assemble book content as structured excerpts (not whole books)
    planet_chunks_text = ""
    for result in planet_results:
        if isinstance(result, Exception):
            continue
        planet_name, chunks = result
        if chunks:
            planet_chunks_text += f"\n\n【{planet_name.upper()}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:800]
                book_title = chunk.get("book_title", "")
                planet_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    aspect_chunks_text = ""
    for result in aspect_results:
        if isinstance(result, Exception):
            continue
        asp_label, chunks = result
        if chunks:
            aspect_chunks_text += f"\n\n【АСПЕКТ: {asp_label}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:600]
                book_title = chunk.get("book_title", "")
                aspect_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    books_content = f"""
=== ФРАГМЕНТЫ ПО ПЛАНЕТАМ (из всех книг) ===
{planet_chunks_text}

=== ФРАГМЕНТЫ ПО АСПЕКТАМ (из всех книг) ===
{aspect_chunks_text}
"""

    # Substitute into the template
    prompt = synthesis_template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # Natal chart data
    prompt += f"\n\n=== {labels.get('natal_chart_label', 'НАТАЛЬНАЯ КАРТА')} ==="
    prompt += f"\nСолнце: {chart_data.get('sun_sign_ru', '?')} в {chart_data.get('sun_sign', '?')}"
    prompt += f"\nЛуна: {chart_data.get('moon_sign_ru', '?')} в {chart_data.get('moon_sign', '?')}"
    prompt += f"\nАсцендент: {chart_data.get('ascendant_ru', '?')} в {chart_data.get('ascendant', '?')}"

    prompt += f"\n=== {labels.get('planets', 'ПЛАНЕТЫ')} ==="
    for planet_name, planet_data in sorted(planets.items()):
        sign = planet_data.get("sign", "?")
        sign_ru = planet_data.get("sign_ru", sign)
        house = planet_data.get("house", "?")
        is_retro = planet_data.get("is_retrograde", False)
        rx_str = " (ретроградная)" if is_retro else ""
        prompt += f"\n{planet_name}: в {sign_ru}, {labels.get('house', 'дом')} {house}{rx_str}"

    # Add Pars Fortuna
    pf = houses_meta.get('pars_fortuna', {})
    if pf:
        pf_sign = pf.get('sign', '?')
        pf_sign_ru = pf.get('sign_ru', pf_sign)
        pf_house = pf.get('house', '?')
        prompt += f"\nPars Fortuna (Парс Фортуны): в {pf_sign_ru}, дом {pf_house}"

    prompt += f"\n=== {labels.get('houses', 'ДОМА')} ==="
    for house_num in range(1, 13):
        key = str(house_num)
        if key in houses:
            h = houses[key]
            prompt += f"\n{labels.get('house_num', 'Дом')} {house_num}: {h.get('sign_ru', '?')}"

    # --- Step 4: One final LLM call ---
    print(f"[full_chart_analysis_v2] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    # The "layer" for post-generation text checking — for natal there's only
    # one (unlike progressions/transits, which have two): find_fabricated_positions_layered/
    # fix_fabricated_positions_layered work fine with a single layer — "fabricated"
    # (the sign doesn't exist in the chart at all) doesn't need an attribution
    # marker, only "layer_confused" does, and with one layer it's always empty (see plan:
    # app/services/specs/natal_synastry_pattern_plan.md).
    natal_chart_like = {
        'planets': planets,
        'ascendant': chart_data.get('ascendant'),
        'ascendant_ru': chart_data.get('ascendant_ru'),
        'ascendant_uk': chart_data.get('ascendant_uk'),
    }
    layers = {'natal': natal_chart_like}

    _t_prompt = _time.perf_counter()

    try:
        full_analysis = await adapter.generate(prompt, language)
        _t_llm = _time.perf_counter()

        if language in ('ru', 'en', 'uk'):
            # Positions: only fixes what doesn't exist in the chart at all.
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if unresolved:
                print(f"[full_chart_analysis_v2] Unresolved position mismatches (left as-is): {unresolved}")

            # Detection only — the claimed aspect type is checked against the
            # actually calculated one (chart_data['aspects']). No layer/partner
            # attribution — there's one chart, two planets in a bold heading
            # are unambiguous on their own.
            fabricated_aspects = find_fabricated_aspect_types_single(full_analysis, aspects, language=language)
            if fabricated_aspects:
                print(f"[full_chart_analysis_v2] Fabricated aspect types detected (not fixed): {fabricated_aspects}")

            # Detection only, from prose — the text is left alone, nothing added.
            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[full_chart_analysis_v2] Undercovered aspects detected (not filled): {undercovered}")

            # Detection only — the planet's house named in the text is checked
            # against the real house from the chart (within the sentence where
            # the planet appears). Not fixed — risk of drifting out of sync
            # with the text's agreement (see find_fabricated_houses_single's docstring).
            fabricated_houses = find_fabricated_houses_single(full_analysis, natal_chart_like, language=language)
            if fabricated_houses:
                print(f"[full_chart_analysis_v2] Fabricated house claims detected (not fixed): {fabricated_houses}")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[full_chart_analysis_v2] LLM error: {e}")

    # _t_llm is unset if generate() raised, so fall back to the prompt mark:
    # that attributes the elapsed time to the LLM phase rather than to verify.
    _t_llm = locals().get('_t_llm', _t_prompt)
    _t_end = _time.perf_counter()
    print(
        "[timing] full_chart_analysis_v2"
        f" titles={_t_titles - _t_start:.1f}s"
        f" rag={_t_rag - _t_titles:.1f}s"
        f" build={_t_prompt - _t_rag:.1f}s"
        f" llm={_t_llm - _t_prompt:.1f}s"
        f" verify={_t_end - _t_llm:.1f}s"
        f" total={_t_end - _t_start:.1f}s"
    )

    return {
        "analysis": full_analysis,
        "language": language,
        "version": "v2_hybrid_rag"
    }


# ============================================================
# SECONDARY PROGRESSIONS ANALYSIS
# ============================================================

async def progressions_analysis(
    natal_chart: Dict[str, Any],
    progressions: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    AI-анализ вторичных прогрессий — тот же гибридный подход, что и full_chart_analysis_v2:
    - точечный RAG-поиск по тем же книгам (прогрессивные личные планеты + аспекты к наталу)
    - сборка структурированного промпта (шаблон 'progressions', advanced/simple)
    - один финальный вызов LLM + краткое summary
    """
    import asyncio
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    adapter = get_llm_adapter()
    labels = get_labels(language)

    prog_planets = progressions.get("progressed_planets", {})
    aspects = progressions.get("aspects_to_natal", [])
    natal_summary = progressions.get("natal_summary", {})
    natal_planets = (natal_chart or {}).get("planets", {})

    # In progressions the personal planets carry interpretive weight (outer planets barely move)
    PERSONAL_PLANETS = ["Sun", "Moon", "Mercury", "Venus", "Mars"]

    # Limits the number of concurrent requests to Supabase — same reason as
    # synastry (full_synastry_analysis_v2, synastry_service.py:599).
    # With the switch to TRANSITS_PROGRESSIONS_BOOK_IDS (fixed 2 books instead
    # of "priority + the entire rest of the catalog", user decision
    # 2026-08-02) each search_chunks_by_book_ids call makes 2 calls to the
    # thread pool (not 3, like search_chunks_priority_book used to make —
    # priority + others + a separate book-titles request per call).
    # 12 tasks × 2 = 24 — even safer than before (was 12 × 3 = 36, a
    # documented unresolved bug, specs/semaphore_thread_pool_sizing_bug.md;
    # this switch closes it as a side effect).
    search_semaphore = asyncio.Semaphore(12)

    # Book titles — one request for the whole analysis, not per RAG sub-request.
    book_titles = await _fetch_book_titles(TRANSITS_PROGRESSIONS_BOOK_IDS)

    # --- Step 1: Parallel RAG search ---
    # Progressions/transits books — a fixed list (28, 29), not one priority
    # book + the whole catalog.
    async def search_progressed_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("natal_house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        query = f"progressed {planet_name.lower()} {sign.lower()} {house_word} house"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return planet_name, chunks

    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("progressed", asp.get("planet1", ""))
        p2 = asp.get("natal", asp.get("planet2", ""))
        asp_type = asp.get("aspect", "")
        query = f"progressed {p1.lower()} {asp_type.lower()} natal {p2.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return f"{p1} {asp_type} {p2}", chunks

    async def search_general() -> tuple:
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(
                "secondary progressions progressed chart day for a year",
                TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5
            )
        return "Secondary Progressions", chunks

    async def search_lunar_phase() -> tuple:
        phase = (progressions.get("lunar_phase") or {}).get("phase", "")
        if not phase:
            return "Lunar Phase", []
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(
                f"progressed lunar phase {phase.lower()} moon cycle",
                TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5
            )
        return f"Progressed Lunar Phase: {phase}", chunks

    planet_tasks = [
        search_progressed_planet(name, prog_planets[name])
        for name in PERSONAL_PLANETS if name in prog_planets
    ]
    # Planets that changed sign relative to the natal — turning points, search for them too
    for name, data in prog_planets.items():
        if data.get("changed_sign") and name not in PERSONAL_PLANETS:
            planet_tasks.append(search_progressed_planet(name, data))
    planet_tasks.append(search_general())
    planet_tasks.append(search_lunar_phase())

    # Used to have an aspects[:10] cutoff, while the prompt still demanded "cover ALL"
    # aspects from aspects_list (which is built from the FULL list below) — aspects
    # past the 10th had no chunks at all. There are few aspects in progressions
    # (1.5° orb), so removing the cutoff doesn't blow up the prompt the way it
    # could for synastry with its 44-64 aspects.
    aspect_tasks = [search_aspect(asp) for asp in aspects]

    print(f"[progressions_analysis] Parallel RAG: {len(planet_tasks)} planet queries, {len(aspect_tasks)} aspect queries")

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)

    # --- Step 2: Assemble the structured prompt ---
    template = get_template("progressions", language, mode)

    # List of progressions-to-natal aspects — with full context for the overlay:
    # progressed planet's position, natal position and HOUSE, orb, applying/separating
    aspects_list = []
    for asp in aspects:
        p1 = asp.get("progressed", asp.get("planet1", "?"))
        p2 = asp.get("natal", asp.get("planet2", "?"))
        orb_val = asp.get("orb", "?")
        n_house = asp.get("natal_house", "?")
        p_house = asp.get("progressed_house", "?")
        # Explicit layer prefix (ПРОГРЕССИВНЫЙ:/НАТАЛЬНЫЙ:, uppercase, without
        # gender-declining the planet — the same trick as ПАРТНЕР1:/ПАРТНЕР2:
        # in synastry_service.py) + the translated planet name: this used to
        # be an undeclared internal key ("Прогрессивный Moon"), not the
        # display name. Distinguishes the progressed and natal position of
        # the SAME planet — plan:
        # app/services/specs/progressions_synastry_pattern_plan.md.
        if language == 'ru':
            p1_display = PLANET_RU.get(p1, p1)
            p2_display = PLANET_RU.get(p2, p2)
            asp_name = asp.get("aspect_ru", asp.get("aspect", "?"))
            applying_str = "сходящийся" if asp.get("applying") else "расходящийся"
            aspects_list.append(
                f"ПРОГРЕССИВНЫЙ:{p1_display} (в {asp.get('progressed_sign', '?')}, натальный дом {p_house}) "
                f"{asp_name} НАТАЛЬНЫЙ:{p2_display} (в {asp.get('natal_sign', '?')}, дом {n_house}) "
                f"— орб {orb_val}°, {applying_str}"
            )
        elif language == 'uk':
            p1_display = _planet_display(p1, 'uk')
            p2_display = _planet_display(p2, 'uk')
            asp_name = asp.get("aspect_uk", asp.get("aspect", "?"))
            applying_str = "аплікуючий" if asp.get("applying") else "сепаруючий"
            aspects_list.append(
                f"ПРОГРЕСИВНА:{p1_display} (у {asp.get('progressed_sign', '?')}, натальний будинок {p_house}) "
                f"{asp_name} НАТАЛЬНА:{p2_display} (у {asp.get('natal_sign', '?')}, будинок {n_house}) "
                f"— орбіс {orb_val}°, {applying_str}"
            )
        else:
            p1_display = PLANET_EN.get(p1, p1)
            p2_display = PLANET_EN.get(p2, p2)
            applying_str = "applying" if asp.get("applying") else "separating"
            aspects_list.append(
                f"PROGRESSED:{p1_display} (in {asp.get('progressed_sign', '?')}, natal house {p_house}) "
                f"{asp.get('aspect', '?')} NATAL:{p2_display} (in {asp.get('natal_sign', '?')}, house {n_house}) "
                f"— orb {orb_val}°, {applying_str}"
            )
    aspects_str = "\n".join(aspects_list) if aspects_list else (
        "Точних аспектів до натальної карти зараз немає" if language == 'uk'
        else "Точных аспектов к натальной карте сейчас нет" if language == 'ru'
        else "No exact aspects to the natal chart right now"
    )

    # Book excerpts
    planet_chunks_text = ""
    for result in planet_results:
        if isinstance(result, Exception):
            continue
        section_name, chunks = result
        if chunks:
            planet_chunks_text += f"\n\n【{section_name.upper()}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:800]
                book_title = chunk.get("book_title", "")
                planet_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    aspect_chunks_text = ""
    for result in aspect_results:
        if isinstance(result, Exception):
            continue
        asp_label, chunks = result
        if chunks:
            aspect_chunks_text += f"\n\n【АСПЕКТ: {asp_label}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:600]
                book_title = chunk.get("book_title", "")
                aspect_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    books_content = f"""
=== ФРАГМЕНТЫ ПО ПРОГРЕССИВНЫМ ПЛАНЕТАМ (из всех книг) ===
{planet_chunks_text}

=== ФРАГМЕНТЫ ПО АСПЕКТАМ ПРОГРЕССИЙ (из всех книг) ===
{aspect_chunks_text}
"""

    prompt = template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # --- Progressions data ---
    # Data language (sign/sign_ru/sign_uk, PLANET_RU/PLANET_UK/PLANET_EN) via
    # _localized()/_planet_display() — this whole block used to be hardcoded
    # in Russian REGARDLESS of language (the template above was already
    # bilingual, but the data wasn't), then extended to 3-way instead of a
    # binary is_ru. Plan: app/services/specs/progressions_synastry_pattern_plan.md.
    age = progressions.get("age_years", "?")
    period = progressions.get("period", "?")

    prompt += f"\n\n{labels['progressions_data_header']}"
    prompt += f"\n{labels['age']}: {age}"
    prompt += f"\n{labels['period']}: {period}"

    # Progressed lunar phase — the stage of the ~30-year cycle, the main context for the whole analysis
    lunar_phase = progressions.get("lunar_phase") or {}
    if lunar_phase:
        phase_name = _localized(lunar_phase, "phase", language, "?")
        prompt += f"\n{labels['progressed_lunar_phase_label']}: {phase_name} ({labels['moon_sun_angle_label']} {lunar_phase.get('angle', '?')}°)"

    prog_asc = progressions.get("progressed_ascendant", {})
    prog_mc = progressions.get("progressed_mc", {})
    if prog_asc:
        asc_sign = _localized(prog_asc, "sign", language, "?")
        prompt += f"\n{labels['progressed_ascendant_label']}: {asc_sign}"
    if prog_mc:
        mc_sign = _localized(prog_mc, "sign", language, "?")
        prompt += f"\n{labels['progressed_mc_label']}: {mc_sign}"

    # Layer prefix (ПРОГРЕССИВНАЯ:/PROGRESSED:) before EVERY planet line, not
    # just in the block heading — otherwise find_fabricated_positions_layered
    # below won't be able to attribute a position to a layer by the nearest marker.
    prompt += f"\n\n{labels['progressed_planets_header']}"
    for planet_name in PERSONAL_PLANETS + [n for n in prog_planets if n not in PERSONAL_PLANETS]:
        planet_data = prog_planets.get(planet_name)
        if not planet_data:
            continue
        planet_display = _planet_display(planet_name, language)
        sign_display = _localized(planet_data, "sign", language, "?")
        degree = planet_data.get("degree", "?")
        house = planet_data.get("natal_house", "?")
        rx_str = labels['retrograde_inline'] if planet_data.get("is_retrograde") else ""
        markers = []
        if planet_data.get("changed_sign") and planet_data.get("natal_sign"):
            natal_planet_data = natal_planets.get(planet_name, {})
            natal_sign_display = natal_planet_data.get(_lang_key("sign", language), planet_data.get("natal_sign"))
            markers.append(labels['changed_sign_marker'].format(sign=natal_sign_display))
        if planet_data.get("changed_house") and planet_data.get("natal_planet_house"):
            markers.append(labels['changed_house_marker'].format(house=planet_data['natal_planet_house']))
        if planet_data.get("years_to_next_sign") is not None:
            markers.append(labels['years_to_next_sign_marker'].format(years=planet_data['years_to_next_sign']))
        markers_str = " — " + "; ".join(markers) if markers else ""
        try:
            degree_str = f"{float(degree):.1f}°"
        except (TypeError, ValueError):
            degree_str = f"{degree}°"
        prompt += f"\n{labels['layer_progressed']}: {planet_display}: {degree_str} {sign_display}, {labels['house_word']} {house}{rx_str}{markers_str}"

    # The full natal chart — without it a "progression over natal" overlay is impossible
    prompt += f"\n\n{labels['natal_chart_overlay_header']}"
    sun_display = _planet_display('Sun', language)
    moon_display = _planet_display('Moon', language)
    asc_display = _planet_display('Ascendant', language)
    natal_sun_sign = _localized2(natal_summary, natal_chart, "sun_sign", language, "?")
    natal_moon_sign = _localized2(natal_summary, natal_chart, "moon_sign", language, "?")
    natal_asc_sign = _localized2(natal_summary, natal_chart, "ascendant", language, "?")
    prompt += f"\n{labels['layer_natal']}: {sun_display}: {natal_sun_sign}"
    prompt += f"\n{labels['layer_natal']}: {moon_display}: {natal_moon_sign}"
    prompt += f"\n{labels['layer_natal']}: {asc_display}: {natal_asc_sign}"
    if natal_planets:
        prompt += f"\n{labels['natal_planets_list_label']}"
        for n_name, n_data in natal_planets.items():
            n_display = _planet_display(n_name, language)
            n_sign = _localized(n_data, "sign", language, "?")
            n_house = n_data.get("house", "?")
            n_rx = labels['retrograde_short'] if n_data.get("is_retrograde") else ""
            prompt += f"\n  {labels['layer_natal']}: {n_display}: {n_sign}, {labels['house_word']} {n_house}{n_rx}"

    # --- Step 3: One final LLM call ---
    print(f"[progressions_analysis] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    # "Layers" for post-generation text checking — progressed position vs
    # natal position of the SAME planet (a generalization of the "Partner 1/2"
    # pattern from synastry_service.py into text_verification.py). Shape —
    # {'planets': {...}, 'ascendant':, 'ascendant_ru':} — the same as
    # natal_chart, so the natal layer is passed as-is, and progressed is
    # built from the same fields.
    progressed_chart_like = {
        'planets': prog_planets,
        'ascendant': prog_asc.get('sign'),
        'ascendant_ru': prog_asc.get('sign_ru'),
        'ascendant_uk': prog_asc.get('sign_uk'),
    }
    layers = {'progressed': progressed_chart_like, 'natal': natal_chart or {}}

    try:
        full_analysis = await adapter.generate(prompt, language)

        if language in ('ru', 'en', 'uk'):
            # Positions: only fixes what doesn't exist in ANY layer —
            # the same as fix_fabricated_planet_positions in synastry
            # (union check), generalized to layers. Plan:
            # app/services/specs/progressions_synastry_pattern_plan.md.
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if unresolved:
                print(f"[progressions_analysis] Unresolved position mismatches (left as-is): {unresolved}")

            # Layer confused (sign is correct, but not for the layer the
            # marker claimed) — log only, never fixed (see
            # find_fabricated_positions_layered's docstring).
            position_issues = find_fabricated_positions_layered(full_analysis, layers, language=language)
            if position_issues.get('layer_confused'):
                print(f"[progressions_analysis] Layer-confused positions detected (not fixed): {position_issues['layer_confused']}")

            # Detection only — the claimed progression→natal aspect type is
            # checked against the actually calculated one (aspects_to_natal).
            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, aspects, language=language, layer_keys=('progressed', 'natal')
            )
            if fabricated_aspects:
                print(f"[progressions_analysis] Fabricated aspect types detected (not fixed): {fabricated_aspects}")

            # Detection only, from prose — the text is left alone, nothing added.
            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[progressions_analysis] Undercovered aspects detected (not filled): {undercovered}")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[progressions_analysis] LLM error: {e}")

    prog_moon = prog_planets.get("Moon", {})
    prog_sun = prog_planets.get("Sun", {})

    return {
        "analysis": full_analysis,
        "progressions_summary": {
            "period": period,
            "age_years": age,
            "lunar_phase": (progressions.get("lunar_phase") or {}).get("phase"),
            "lunar_phase_ru": (progressions.get("lunar_phase") or {}).get("phase_ru"),
            "progressed_moon_sign": prog_moon.get("sign", "?"),
            "progressed_moon_sign_ru": prog_moon.get("sign_ru", "?"),
            "progressed_moon_house": prog_moon.get("natal_house"),
            "progressed_sun_sign": prog_sun.get("sign", "?"),
            "progressed_sun_sign_ru": prog_sun.get("sign_ru", "?"),
            "sun_changed_sign": prog_sun.get("changed_sign", False),
            "aspects_count": len(aspects),
        },
        "language": language,
        "version": "progressions_v1_hybrid_rag"
    }



async def transits_analysis(
    natal_chart: Dict[str, Any],
    transits: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced',
    transit_place: Optional[str] = None,
    transit_lat: Optional[float] = None,
    transit_lon: Optional[float] = None,
) -> Dict[str, Any]:
    """
    AI-анализ транзитов дня — гибридный подход как у прогрессий:
    - точечный RAG-поиск (транзитные планеты в натальных домах + аспекты к наталу)
    - сборка структурированного промпта (шаблон 'transits', advanced/simple)
    - один финальный вызов LLM + краткое summary

    transit_place/lat/lon — место, где человек находится в момент транзита.
    Это важно для интерпретации транзитных домов и лунной фазы.
    """
    import asyncio
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    adapter = get_llm_adapter()
    labels = get_labels(language)

    t_planets = transits.get("transit_planets", {})
    aspects = transits.get("aspects_to_natal", [])
    natal_summary = transits.get("natal_summary", {})
    natal_planets = (natal_chart or {}).get("planets", {})

    # Slow transits = the main themes of the period; fast ones = the flavor of the day
    slow_aspects = [a for a in aspects if a.get("is_slow")]
    fast_aspects = [a for a in aspects if not a.get("is_slow")]

    # Limits the number of concurrent requests to Supabase — same reason as
    # synastry and progressions (synastry_service.py:599). For transits ALL
    # aspects are searched (aspect_pool below), noticeably more requests than
    # progressions — here the semaphore isn't a future safeguard, it's needed already.
    # With the switch to TRANSITS_PROGRESSIONS_BOOK_IDS (2 books instead of
    # "priority + the whole catalog", user decision 2026-08-02) each call
    # makes 2 calls to the thread pool, not 3 like search_chunks_priority_book
    # used to — the same win as in progressions.
    search_semaphore = asyncio.Semaphore(12)

    # Book titles — one request for the whole analysis, not per RAG sub-request.
    book_titles = await _fetch_book_titles(TRANSITS_PROGRESSIONS_BOOK_IDS)

    # --- Step 1: Parallel RAG search ---
    async def search_transit_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("natal_house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        query = f"transit {planet_name.lower()} {sign.lower()} {house_word} house"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return planet_name, chunks

    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("transit", asp.get("planet1", ""))
        p2 = asp.get("natal", asp.get("planet2", ""))
        asp_type = asp.get("aspect", "")
        query = f"transit {p1.lower()} {asp_type.lower()} natal {p2.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return f"{p1} {asp_type} {p2}", chunks

    async def search_lunar_phase() -> tuple:
        phase = (transits.get("lunar_phase") or {}).get("phase", "")
        if not phase:
            return "Lunar Phase", []
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(
                f"lunar phase {phase.lower()} moon", TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5
            )
        return f"Lunar Phase: {phase}", chunks

    # Planets to search: slow ones with aspects + Moon and Sun (the day)
    search_planet_names = []
    for a in slow_aspects:
        name = a.get("transit")
        if name and name not in search_planet_names:
            search_planet_names.append(name)
    for name in ("Moon", "Sun"):
        if name in t_planets and name not in search_planet_names:
            search_planet_names.append(name)

    planet_tasks = [
        search_transit_planet(name, t_planets[name])
        for name in search_planet_names if name in t_planets
    ]
    planet_tasks.append(search_lunar_phase())

    # Aspects: all slow + all fast, for a complete analysis
    aspect_pool = slow_aspects + fast_aspects
    aspect_tasks = [search_aspect(asp) for asp in aspect_pool]

    print(f"[transits_analysis] Parallel RAG: {len(planet_tasks)} planet queries, {len(aspect_tasks)} aspect queries")

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)

    # --- Step 2: Assemble the structured prompt ---
    template = get_template("transits", language, mode)

    # NOTE on the 'transit_house' field here: in aspects_to_natal (calculate_transits,
    # astrology_v2.py:1230) it's the NATAL house of the transit planet (which natal
    # house it's "moving through"), NOT the house in the current place's transit
    # chart — that's in 'transit_planet_transit_house' (:1232). The same key
    # 'transit_house' in t_planets[X] (:1205 below) means something DIFFERENT — the
    # real transit house. Don't confuse the two when reading/editing — plan:
    # app/services/specs/transits_synastry_pattern_plan.md.
    lang = normalize_language(language)

    def fmt_aspect(asp: Dict) -> str:
        p1 = asp.get("transit", asp.get("planet1", "?"))
        p2 = asp.get("natal", asp.get("planet2", "?"))
        p1_display = _planet_display(p1, language)
        p2_display = _planet_display(p2, language)
        orb_val = asp.get("orb", "?")
        natal_house_of_transit_planet = asp.get("transit_house", "?")  # see the comment above
        current_transit_house = asp.get("transit_planet_transit_house", "?")
        if current_transit_house == "?":
            transit_house_str = ""
        elif lang == 'ru':
            transit_house_str = f", транзитный дом {current_transit_house}"
        elif lang == 'uk':
            transit_house_str = f", транзитний дім {current_transit_house}"
        else:
            transit_house_str = f", transit house {current_transit_house}"
        ret_mark = ""
        if asp.get("is_return"):
            ret_mark = {
                'ru': " [ВОЗВРАТ ПЛАНЕТЫ!]",
                'uk': " [ПОВЕРНЕННЯ ПЛАНЕТИ!]",
                'en': " [PLANETARY RETURN!]",
            }[lang]
        if lang == 'ru':
            asp_name = asp.get("aspect_ru", asp.get("aspect", "?"))
            applying_str = "сходящийся" if asp.get("applying") else "расходящийся"
            return (f"ТРАНЗИТНЫЙ:{p1_display} (в {asp.get('transit_sign', '?')}, идёт по натальному дому {natal_house_of_transit_planet}{transit_house_str}) "
                    f"{asp_name} НАТАЛЬНЫЙ:{p2_display} (в {asp.get('natal_sign', '?')}, дом {asp.get('natal_house', '?')}) "
                    f"— орб {orb_val}°, {applying_str}{ret_mark}")
        if lang == 'uk':
            asp_name = asp.get("aspect_uk", asp.get("aspect", "?"))
            applying_str = "аплікуючий" if asp.get("applying") else "сепаруючий"
            return (f"ТРАНЗИТНА:{p1_display} (у {asp.get('transit_sign', '?')}, проходить по натальному будинку {natal_house_of_transit_planet}{transit_house_str}) "
                    f"{asp_name} НАТАЛЬНА:{p2_display} (у {asp.get('natal_sign', '?')}, будинок {asp.get('natal_house', '?')}) "
                    f"— орбіс {orb_val}°, {applying_str}{ret_mark}")
        applying_str = "applying" if asp.get("applying") else "separating"
        return (f"TRANSITING:{p1_display} (in {asp.get('transit_sign', '?')}, moving through natal house {natal_house_of_transit_planet}{transit_house_str}) "
                f"{asp.get('aspect', '?')} NATAL:{p2_display} (in {asp.get('natal_sign', '?')}, house {asp.get('natal_house', '?')}) "
                f"— orb {orb_val}°, {applying_str}{ret_mark}")

    _NO_SLOW_ASPECTS = {
        'ru': "Нет точных аспектов от медленных планет",
        'uk': "Немає точних аспектів від повільних планет",
        'en': "No exact aspects from slow planets",
    }
    _NO_FAST_ASPECTS = {
        'ru': "Нет точных аспектов от быстрых планет",
        'uk': "Немає точних аспектів від швидких планет",
        'en': "No exact aspects from fast planets",
    }
    _SLOW_HEADER = {
        'ru': "【МЕДЛЕННЫЕ ПЛАНЕТЫ — главные темы периода】\n",
        'uk': "【ПОВІЛЬНІ ПЛАНЕТИ — головні теми періоду】\n",
        'en': "【SLOW PLANETS — main themes of the period】\n",
    }
    _FAST_HEADER = {
        'ru': "\n\n【БЫСТРЫЕ ПЛАНЕТЫ — окраска именно этого дня】\n",
        'uk': "\n\n【ШВИДКІ ПЛАНЕТИ — забарвлення саме цього дня】\n",
        'en': "\n\n【FAST PLANETS — the flavor of this specific day】\n",
    }
    slow_str = "\n".join(fmt_aspect(a) for a in slow_aspects) if slow_aspects else _NO_SLOW_ASPECTS[lang]
    fast_str = "\n".join(fmt_aspect(a) for a in fast_aspects) if fast_aspects else _NO_FAST_ASPECTS[lang]
    aspects_str = _SLOW_HEADER[lang] + slow_str + _FAST_HEADER[lang] + fast_str

    # Book excerpts
    planet_chunks_text = ""
    for result in planet_results:
        if isinstance(result, Exception):
            continue
        section_name, chunks = result
        if chunks:
            planet_chunks_text += f"\n\n【{section_name.upper()}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:800]
                book_title = chunk.get("book_title", "")
                planet_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    aspect_chunks_text = ""
    for result in aspect_results:
        if isinstance(result, Exception):
            continue
        asp_label, chunks = result
        if chunks:
            aspect_chunks_text += f"\n\n【АСПЕКТ: {asp_label}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:600]
                book_title = chunk.get("book_title", "")
                aspect_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    books_content = f"""
=== ФРАГМЕНТЫ ПО ТРАНЗИТНЫМ ПЛАНЕТАМ (из всех книг) ===
{planet_chunks_text}

=== ФРАГМЕНТЫ ПО АСПЕКТАМ ТРАНЗИТОВ (из всех книг) ===
{aspect_chunks_text}
"""

    prompt = template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # --- Transits data ---
    # Data language via _localized()/_planet_display() — this whole block
    # (except the transit place and Asc/MC) used to be hardcoded in Russian
    # regardless of language, then extended to 3-way instead of a binary
    # is_ru. Plan: app/services/specs/transits_synastry_pattern_plan.md.
    period = transits.get("period", "?")
    prompt += f"\n\n{labels['transits_data_header']}"
    prompt += f"\n{labels['day_label']}: {period}"

    # Transit place info
    transit_summary = transits.get("transit_summary", {})
    if transit_lat is not None and transit_lon is not None:
        location_name = transit_place or labels['not_specified']
        prompt += f"\n{labels['transit_place_label']}: {location_name} ({labels['coordinates_label']}: {transit_lat:.4f}°, {transit_lon:.4f}°)"

    transit_asc = transit_summary.get("ascendant")
    transit_mc = transit_summary.get("mc")
    if transit_asc or transit_mc:
        asc_sign = _localized(transit_asc, "sign", language, "?") if transit_asc else "?"
        mc_sign = _localized(transit_mc, "sign", language, "?") if transit_mc else "?"
        prompt += f"\n{labels['transiting_ascendant_label']}: {asc_sign}"
        prompt += f"\n{labels['transiting_mc_label']}: {mc_sign}"

    lunar_phase = transits.get("lunar_phase") or {}
    if lunar_phase:
        phase_name = _localized(lunar_phase, "phase", language, "?")
        prompt += f"\n{labels['day_lunar_phase_label']}: {phase_name} ({labels['moon_sun_angle_label']} {lunar_phase.get('angle', '?')}°)"

    # Layer prefix (ТРАНЗИТНАЯ:/TRANSITING:) before EVERY planet line, not
    # just in the block heading — otherwise find_fabricated_positions_layered
    # below won't be able to attribute a position to a layer by the nearest marker.
    TRANSIT_ORDER = ["Moon", "Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
                     "Uranus", "Neptune", "Pluto", "NorthNode", "SouthNode", "Chiron", "Lilith"]
    prompt += f"\n\n{labels['transit_planets_header']}"
    for planet_name in TRANSIT_ORDER:
        planet_data = t_planets.get(planet_name)
        if not planet_data:
            continue
        planet_display = _planet_display(planet_name, language)
        sign_display = _localized(planet_data, "sign", language, "?")
        degree = planet_data.get("degree", "?")
        # Here 'natal_house'/'transit_house' in t_planets[X] are NOT the same
        # values as the same-named fields in aspects_to_natal (see the comment
        # by fmt_aspect above): here natal_house = the planet's natal house,
        # transit_house = the real house in the current place's transit chart.
        house = planet_data.get("natal_house", "?")
        transit_house = planet_data.get("transit_house", "?")
        rx_str = labels['retrograde_inline'] if planet_data.get("is_retrograde") else ""
        slow_str2 = labels['slow_planet_marker'] if planet_data.get("is_slow") else ""
        try:
            degree_str = f"{float(degree):.1f}°"
        except (TypeError, ValueError):
            degree_str = f"{degree}°"
        prompt += (f"\n{labels['layer_transit']}: {planet_display}: {degree_str} {sign_display}, "
                   f"{labels['natal_house_word']} {house}, {labels['transit_house_word']} {transit_house}{rx_str}{slow_str2}")

    # The full natal chart — the basis for the overlay
    prompt += f"\n\n{labels['natal_chart_overlay_header']}"
    sun_display = _planet_display('Sun', language)
    moon_display = _planet_display('Moon', language)
    asc_display = _planet_display('Ascendant', language)
    natal_sun_sign = _localized2(natal_summary, natal_chart, "sun_sign", language, "?")
    natal_moon_sign = _localized2(natal_summary, natal_chart, "moon_sign", language, "?")
    natal_asc_sign = _localized2(natal_summary, natal_chart, "ascendant", language, "?")
    prompt += f"\n{labels['layer_natal']}: {sun_display}: {natal_sun_sign}"
    prompt += f"\n{labels['layer_natal']}: {moon_display}: {natal_moon_sign}"
    prompt += f"\n{labels['layer_natal']}: {asc_display}: {natal_asc_sign}"
    if natal_planets:
        prompt += f"\n{labels['natal_planets_list_label']}"
        for n_name, n_data in natal_planets.items():
            n_display = _planet_display(n_name, language)
            n_sign = _localized(n_data, "sign", language, "?")
            n_house = n_data.get("house", "?")
            n_rx = labels['retrograde_short'] if n_data.get("is_retrograde") else ""
            prompt += f"\n  {labels['layer_natal']}: {n_display}: {n_sign}, {labels['house_word']} {n_house}{n_rx}"

    # --- Step 3: One final LLM call ---
    print(f"[transits_analysis] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    # "Layers" for post-generation text checking — transit position vs natal
    # position of the SAME planet (the same pattern as progressions, see
    # progressions_synastry_pattern_plan.md). Shape —
    # {'planets': {...}, 'ascendant':, 'ascendant_ru':} — the natal layer is
    # passed as-is, transit is built from the same transit_summary fields.
    transit_chart_like = {
        'planets': t_planets,
        'ascendant': transit_asc.get('sign') if transit_asc else None,
        'ascendant_ru': transit_asc.get('sign_ru') if transit_asc else None,
        'ascendant_uk': transit_asc.get('sign_uk') if transit_asc else None,
    }
    layers = {'transit': transit_chart_like, 'natal': natal_chart or {}}

    try:
        full_analysis = await adapter.generate(prompt, language)

        if language in ('ru', 'en', 'uk'):
            # Positions: only fixes what doesn't exist in ANY layer.
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if unresolved:
                print(f"[transits_analysis] Unresolved position mismatches (left as-is): {unresolved}")

            # Layer confused — log only, never fixed.
            position_issues = find_fabricated_positions_layered(full_analysis, layers, language=language)
            if position_issues.get('layer_confused'):
                print(f"[transits_analysis] Layer-confused positions detected (not fixed): {position_issues['layer_confused']}")

            # Detection only — the claimed transit→natal aspect type is
            # checked against the actually calculated one (aspects_to_natal).
            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, aspects, language=language, layer_keys=('transit', 'natal')
            )
            if fabricated_aspects:
                print(f"[transits_analysis] Fabricated aspect types detected (not fixed): {fabricated_aspects}")

            # Detection only, from prose.
            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[transits_analysis] Undercovered aspects detected (not filled): {undercovered}")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[transits_analysis] LLM error: {e}")

    return {
        "analysis": full_analysis,
        "transits_summary": {
            "period": period,
            "lunar_phase": lunar_phase.get("phase"),
            "lunar_phase_ru": lunar_phase.get("phase_ru"),
            "slow_aspects_count": len(slow_aspects),
            "fast_aspects_count": len(fast_aspects),
            "returns": [a.get("transit") for a in aspects if a.get("is_return")],
        },
        "language": language,
        "version": "transits_v1_hybrid_rag"
    }



def _collect_progressed_synastry_layers(
    p1: Dict[str, Any], p2: Dict[str, Any],
    layer1: List[Dict[str, Any]], prog1_to_natal2: List[Dict[str, Any]], prog2_to_natal1: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Именованные слои (планета -> знак) для find_fabricated_positions_layered.

    ВАЖНО: 4 отдельных слоя (p1_progressed/p2_progressed/p1_natal/p2_natal),
    НЕ один смёрженный словарь — у одной и той же планеты (например, Луны)
    одновременно 4 РАЗНЫХ валидных знака (прогр.1 ≠ натал.1 ≠ прогр.2 ≠
    натал.2), а find_fabricated_positions_layered объединяет валидные пары
    через set() ПО СЛОЯМ (planet, sign) — объединение работает корректно
    только между отдельными слоями, не внутри одного плоского словаря
    "планета -> один знак" (там просто негде хранить 4 значения на ключ).

    progressed_synastry не хранит полные натальные карты партнёров —
    natal_summary даёт только Sun/Moon/Ascendant (astrology_v2.py:1061-1068).
    Остальные натальные планеты (Меркурий, Марс и т.д.) восстанавливаем из
    sign1/sign2 самих аспектов cross_overlay — единственное место, где они
    встречаются. planet1 в аспектах — всегда прогрессивная планета стороны
    "a", planet2 в cross_overlay — всегда натальная планета принимающей
    стороны (см. calculate_progressed_synastry, astrology_v2.py:1499-1509).
    """
    from app.utils.astrology_v2 import ZODIAC_SIGNS, ZODIAC_SIGNS_RU, ZODIAC_SIGNS_UK
    en_to_ru = dict(zip(ZODIAC_SIGNS, ZODIAC_SIGNS_RU))
    en_to_uk = dict(zip(ZODIAC_SIGNS, ZODIAC_SIGNS_UK))

    def from_sign_en(sign_en: Optional[str]) -> Dict[str, Optional[str]]:
        return {'sign': sign_en, 'sign_ru': en_to_ru.get(sign_en), 'sign_uk': en_to_uk.get(sign_en)}

    layers: Dict[str, Any] = {
        'p1_progressed': {'planets': dict(p1.get("progressed_planets") or {})},
        'p2_progressed': {'planets': dict(p2.get("progressed_planets") or {})},
    }
    for idx, person in ((1, p1), (2, p2)):
        ns = person.get("natal_summary") or {}
        layers[f'p{idx}_natal'] = {
            'planets': {
                'Sun': {'sign': ns.get("sun_sign"), 'sign_ru': ns.get("sun_sign_ru"), 'sign_uk': en_to_uk.get(ns.get("sun_sign"))},
                'Moon': {'sign': ns.get("moon_sign"), 'sign_ru': ns.get("moon_sign_ru"), 'sign_uk': en_to_uk.get(ns.get("moon_sign"))},
            },
            'ascendant': ns.get("ascendant"),
            'ascendant_ru': ns.get("ascendant_ru"),
            'ascendant_uk': en_to_uk.get(ns.get("ascendant")),
        }

    for asp in (layer1 or []):
        if asp.get("planet1"):
            layers['p1_progressed']['planets'].setdefault(asp["planet1"], from_sign_en(asp.get("sign1")))
        if asp.get("planet2"):
            layers['p2_progressed']['planets'].setdefault(asp["planet2"], from_sign_en(asp.get("sign2")))
    for asp in (prog1_to_natal2 or []):
        if asp.get("planet1"):
            layers['p1_progressed']['planets'].setdefault(asp["planet1"], from_sign_en(asp.get("sign1")))
        if asp.get("planet2"):
            layers['p2_natal']['planets'].setdefault(asp["planet2"], from_sign_en(asp.get("sign2")))
    for asp in (prog2_to_natal1 or []):
        if asp.get("planet1"):
            layers['p2_progressed']['planets'].setdefault(asp["planet1"], from_sign_en(asp.get("sign1")))
        if asp.get("planet2"):
            layers['p1_natal']['planets'].setdefault(asp["planet2"], from_sign_en(asp.get("sign2")))

    return layers


async def progressed_synastry_analysis(
    progressed_synastry: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 2,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    AI-анализ прогрессивной синастрии — три слоя:
      1) прогрессивная синастрия (прогр A ↔ прогр B)
      2) наложение на натал (прогр A → натал B и наоборот)
      3) динамика относительно натальной синастрии
    Приоритетная книга — Brady "The Eagle and the Lark" (id=29, прогностика).
    """
    import asyncio
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_templates import get_template

    adapter = get_llm_adapter()

    p1 = progressed_synastry.get("person1", {})
    p2 = progressed_synastry.get("person2", {})
    _default_names = {
        'ru': ("первый партнёр", "второй партнёр"),
        'uk': ("перший партнер", "другий партнер"),
        'en': ("the first partner", "the second partner"),
    }
    _dn1, _dn2 = _default_names.get(language, _default_names['en'])
    name1 = p1.get("name") or _dn1
    name2 = p2.get("name") or _dn2

    layer1 = progressed_synastry.get("progressed_synastry_aspects", [])
    cross = progressed_synastry.get("cross_overlay", {})
    prog1_to_natal2 = cross.get("prog1_to_natal2", [])
    prog2_to_natal1 = cross.get("prog2_to_natal1", [])
    dynamics = progressed_synastry.get("dynamics", {})

    # --- Step 1: RAG search (priority book id=29, predictive) ---
    async def search_aspect(asp: Dict, kind: str) -> tuple:
        p_a = asp.get("planet1", "")
        p_b = asp.get("planet2", "")
        asp_type = asp.get("aspect", "")
        query = f"progressed {p_a.lower()} {asp_type.lower()} {p_b.lower()} synastry relationship"
        chunks = await search_chunks_priority_book(query, PROGRESSIONS_PRIORITY_BOOK_ID, top_k_priority=3, top_k_others=2)
        return f"[{kind}] {p_a} {asp_type} {p_b}", chunks

    async def search_lunar(person_label: str, phase: str) -> tuple:
        if not phase:
            return f"Lunar {person_label}", []
        chunks = await search_chunks_priority_book(
            f"progressed moon {phase.lower()} relationship synastry",
            PROGRESSIONS_PRIORITY_BOOK_ID, top_k_priority=2, top_k_others=top_k_per_book
        )
        return f"Progressed Moon ({person_label}): {phase}", chunks

    # Search the most exact aspects of each layer (limiting the number of RPCs)
    tasks = []
    for asp in layer1[:6]:
        tasks.append(search_aspect(asp, "L1"))
    for asp in prog1_to_natal2[:3]:
        tasks.append(search_aspect(asp, "L2"))
    for asp in prog2_to_natal1[:3]:
        tasks.append(search_aspect(asp, "L2"))
    ph1 = (p1.get("lunar_phase") or {}).get("phase", "")
    ph2 = (p2.get("lunar_phase") or {}).get("phase", "")
    tasks.append(search_lunar(name1, ph1))
    tasks.append(search_lunar(name2, ph2))

    print(f"[progressed_synastry_analysis] Parallel RAG: {len(tasks)} queries")
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # --- Step 2: Format aspects by layer ---
    def fmt(asp: Dict, cross_houses: bool = False) -> str:
        p_a = _planet_display(asp.get("planet1", "?"), language)
        p_b = _planet_display(asp.get("planet2", "?"), language)
        orb_val = asp.get("orb", "?")
        if language == 'ru':
            sign1 = asp.get('sign1_ru', asp.get('sign1', '?'))
            sign2 = asp.get('sign2_ru', asp.get('sign2', '?'))
            asp_name = asp.get("aspect_ru", asp.get("aspect", "?"))
            applying_str = "набирает силу" if asp.get("applying") else "завершается"
            base = f"{p_a} ({sign1}) {asp_name} {p_b} ({sign2}) — орб {orb_val}°, {applying_str}"
        elif language == 'uk':
            sign1 = asp.get('sign1_uk', asp.get('sign1', '?'))
            sign2 = asp.get('sign2_uk', asp.get('sign2', '?'))
            asp_name = asp.get("aspect_uk", asp.get("aspect", "?"))
            applying_str = "аплікуючий" if asp.get("applying") else "сепаруючий"
            base = f"{p_a} ({sign1}) {asp_name} {p_b} ({sign2}) — орбіс {orb_val}°, {applying_str}"
        else:
            sign1 = asp.get('sign1', '?')
            sign2 = asp.get('sign2', '?')
            asp_name = asp.get("aspect", "?")
            applying_str = "gaining strength" if asp.get("applying") else "wrapping up"
            base = f"{p_a} ({sign1}) {asp_name} {p_b} ({sign2}) — orb {orb_val}°, {applying_str}"
        h1 = asp.get("planet1_house_in_2")
        h2 = asp.get("planet2_house_in_1")
        houses = []
        house_word = "дом" if language == 'ru' else "будинок" if language == 'uk' else "house"
        if h1:
            houses.append(f"{p_a}→{house_word} {h1}")
        if h2:
            houses.append(f"{p_b}→{house_word} {h2}")
        if houses:
            base += " (" + ", ".join(houses) + ")"
        return base

    L = {
        'ru': {
            'l1': f"【СЛОЙ 1 — Прогрессивная синастрия: {name1} ↔ {name2}】",
            'l2a': f"【СЛОЙ 2 — Прогрессии {name1} → натальная карта {name2}】",
            'l2b': f"【СЛОЙ 2 — Прогрессии {name2} → натальная карта {name1}】",
            'l3new': "【СЛОЙ 3 — НОВЫЕ аспекты (появились в прогрессии)】",
            'l3fade': "【СЛОЙ 3 — Натальные аспекты, сейчас НЕ активные】",
            'none': "(нет точных аспектов)",
        },
        'en': {
            'l1': f"【LAYER 1 — Progressed synastry: {name1} ↔ {name2}】",
            'l2a': f"【LAYER 2 — {name1}'s progressions → {name2}'s natal chart】",
            'l2b': f"【LAYER 2 — {name2}'s progressions → {name1}'s natal chart】",
            'l3new': "【LAYER 3 — NEW aspects (appeared in progression)】",
            'l3fade': "【LAYER 3 — Natal aspects NOT active now】",
            'none': "(no exact aspects)",
        },
        'uk': {
            'l1': f"【ШАР 1 — Прогресивна синастрія: {name1} ↔ {name2}】",
            'l2a': f"【ШАР 2 — Прогресії {name1} → натальна карта {name2}】",
            'l2b': f"【ШАР 2 — Прогресії {name2} → натальна карта {name1}】",
            'l3new': "【ШАР 3 — НОВІ аспекти (з'явилися в прогресії)】",
            'l3fade': "【ШАР 3 — Натальні аспекти, зараз НЕ активні】",
            'none': "(немає точних аспектів)",
        }
    }[language if language in ('ru', 'en', 'uk') else 'en']

    def block(title, items, **kw):
        body = "\n".join(fmt(a, **kw) for a in items) if items else L['none']
        return f"{title}\n{body}"

    aspects_list = "\n\n".join([
        block(L['l1'], layer1, cross_houses=True),
        block(L['l2a'], prog1_to_natal2),
        block(L['l2b'], prog2_to_natal1),
        block(L['l3new'], dynamics.get("new_aspects", []), cross_houses=True),
        block(L['l3fade'], dynamics.get("faded_aspects", [])),
    ])

    # --- Step 3: Book excerpts ---
    books_content = ""
    for result in results:
        if isinstance(result, Exception):
            continue
        label, chunks = result
        if chunks:
            books_content += f"\n\n【{label}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:700]
                book_title = chunk.get("book_title", "")
                books_content += f"[{i}] ({book_title}):\n{text}\n"

    # --- Step 4: Assemble the prompt ---
    template = get_template("progressed_synastry", language, mode)
    prompt = template.replace("{aspects_list}", aspects_list).replace("{books_content}", books_content)

    # Partner data
    _partner_headers = {
        'ru': "=== ДАННЫЕ ПАРТНЁРОВ ===",
        'uk': "=== ДАНІ ПАРТНЕРІВ ===",
        'en': "=== PARTNER DATA ===",
    }
    prompt += f"\n\n{_partner_headers.get(language, _partner_headers['en'])}"
    for label, person in ((name1, p1), (name2, p2)):
        lp = person.get("lunar_phase") or {}
        phase_key = "phase_ru" if language == 'ru' else "phase_uk" if language == 'uk' else "phase"
        phase = lp.get(phase_key, lp.get("phase", "?"))
        ns = person.get("natal_summary") or {}
        age_word = "вік" if language == 'uk' else "age" if language == 'en' else "возраст"
        moon_phase_word = "Прогресивна місячна фаза" if language == 'uk' \
            else "Progressed lunar phase" if language == 'en' else "Прогрессивная лунная фаза"
        prog_label_prefix = "Прогр." if language != 'en' else "Prog."
        prompt += f"\n\n{label} ({age_word} {person.get('age_years', '?')}):"
        prompt += f"\n  {moon_phase_word}: {phase}"
        prog_planets = person.get("progressed_planets", {})
        for key in ("Moon", "Sun", "Venus", "Mars", "Mercury"):
            pd = prog_planets.get(key)
            if pd:
                sign_key = "sign_ru" if language == 'ru' else "sign_uk" if language == 'uk' else "sign"
                sign = pd.get(sign_key, pd.get("sign", "?"))
                rx = " R" if pd.get("is_retrograde") else ""
                prompt += f"\n  {prog_label_prefix}{_planet_display(key, language)}: {sign}{rx}"

    dyn = dynamics
    _dyn_labels = {
        'ru': "=== ДИНАМИКА: натальная синастрия {n} аспектов → прогрессивная {p} ===",
        'uk': "=== ДИНАМІКА: натальна синастрія {n} аспектів → прогресивна {p} ===",
        'en': "=== DYNAMICS: natal synastry {n} aspects → progressed {p} ===",
    }
    _dyn_tmpl = _dyn_labels.get(language, _dyn_labels['en'])
    prompt += "\n\n" + _dyn_tmpl.format(n=dyn.get('natal_total', '?'), p=dyn.get('progressed_total', '?'))

    # --- Step 5: LLM ---
    print(f"[progressed_synastry_analysis] Final prompt ~{len(prompt)//4} tokens")
    try:
        full_analysis = await adapter.generate(prompt, language)

        if language in ('ru', 'en', 'uk'):
            _fabrication_layers = _collect_progressed_synastry_layers(
                p1, p2, layer1, prog1_to_natal2, prog2_to_natal1
            )
            position_issues = find_fabricated_positions_layered(
                full_analysis, _fabrication_layers, language=language
            )
            if position_issues.get('fabricated'):
                print(f"[progressed_synastry_analysis] Fabricated positions detected (not fixed): {position_issues['fabricated']}")

            # Aspect type — LAYER 2 only (prog.→natal): the prompt there really
            # does write "прогрессивная"/"натальная" next to the planet. For
            # LAYER 1 (prog.↔prog., both partners "progressed") this marker
            # axis doesn't distinguish the partners — not checked, a documented gap.
            cross_aspects = (prog1_to_natal2 or []) + (prog2_to_natal1 or [])
            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, cross_aspects, language=language, layer_keys=('progressed', 'natal')
            )
            if fabricated_aspects:
                print(f"[progressed_synastry_analysis] Fabricated aspect types detected (layer 2 only): {fabricated_aspects}")

            all_aspects = (layer1 or []) + cross_aspects
            undercovered = find_undercovered_aspects_generic(full_analysis, all_aspects, language=language)
            if undercovered:
                print(f"[progressed_synastry_analysis] Undercovered aspects detected: {undercovered}")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"

    return {
        "analysis": full_analysis,
        "progressed_synastry_summary": {
            "period": progressed_synastry.get("period"),
            "person1_name": p1.get("name"),
            "person2_name": p2.get("name"),
            "person1_lunar_phase": (p1.get("lunar_phase") or {}).get("phase"),
            "person2_lunar_phase": (p2.get("lunar_phase") or {}).get("phase"),
            "layer1_aspects": len(layer1),
            "new_aspects": len(dynamics.get("new_aspects", [])),
            "faded_aspects": len(dynamics.get("faded_aspects", [])),
        },
        "language": language,
        "version": "progressed_synastry_v1"
    }


async def analyze_progressed_synastry_aspect(
    planet1: str,
    planet2: str,
    aspect_name: str,
    layer: str,
    aspect_name_ru: Optional[str] = None,
    aspect_name_uk: Optional[str] = None,
    orb: float = 0.0,
    applying: Optional[bool] = None,
    house1: Optional[int] = None,
    house2: Optional[int] = None,
    partner1_name: Optional[str] = None,
    partner2_name: Optional[str] = None,
    language: str = "ru",
    mode: str = "advanced",
) -> Dict[str, Any]:
    """
    Анализ ОДНОГО аспекта прогрессивной синастрии (клик на аспект во фронте).
    Образец: analyze_synastry_aspect (synastry_service.py:534). См.
    specs/progressed_synastry_aspect_click_plan.md.

    layer — из какого из пяти блоков ответа /progressed-synastry взят аспект:
    'progressed' (Слой 1, прогр↔прогр), 'prog1_to_natal2'/'prog2_to_natal1'
    (Слой 2, кросс-наложение), 'new'/'faded' (Слой 3, динамика) — определяет
    формулировку разбора через PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT.

    house1/house2 — дом, в который попадает planet1/planet2 в карте ДРУГОГО
    партнёра (как planet1_house_in_2/planet2_house_in_1 в основном разборе).
    """
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_templates import get_template
    from app.services.prompt_templates.progressed_synastry import PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT

    lang = normalize_language(language)

    aspect_display = aspect_name
    if lang == 'ru' and aspect_name_ru:
        aspect_display = aspect_name_ru
    elif lang == 'uk' and aspect_name_uk:
        aspect_display = aspect_name_uk

    query = f"progressed {planet1.lower()} {aspect_display.lower()} {planet2.lower()} synastry relationship"
    chunks = await search_chunks_priority_book(query, PROGRESSIONS_PRIORITY_BOOK_ID, top_k_priority=4, top_k_others=4)

    layer_ctx_by_lang = PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT.get(lang, PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT['en'])
    layer_context = layer_ctx_by_lang.get(layer, layer_ctx_by_lang['progressed'])

    _labels = {
        'ru': {'partner': 'Партнёр', 'aspect': 'Аспект', 'applying': 'набирает силу', 'separating': 'завершается', 'house': 'дом'},
        'uk': {'partner': 'Партнер', 'aspect': 'Аспект', 'applying': 'набирає силу', 'separating': 'завершується', 'house': 'будинок'},
        'en': {'partner': 'Partner', 'aspect': 'Aspect', 'applying': 'gaining strength', 'separating': 'wrapping up', 'house': 'house'},
    }[lang if lang in ('ru', 'uk') else 'en']

    p1_label = partner1_name or f"{_labels['partner']} 1"
    p2_label = partner2_name or f"{_labels['partner']} 2"

    aspect_lines = [f"{p1_label}: {planet1}", f"{_labels['aspect']}: {aspect_display}", f"{p2_label}: {planet2}"]
    if applying is not None:
        aspect_lines.append(_labels['applying'] if applying else _labels['separating'])
    if house1:
        aspect_lines.append(f"{planet1} → {p2_label} {_labels['house']} {house1}")
    if house2:
        aspect_lines.append(f"{planet2} → {p1_label} {_labels['house']} {house2}")
    aspect_data = "\n".join(aspect_lines)

    books_content = ""
    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "")[:700]
        book_title = chunk.get("book_title", "")
        books_content += f"[{i}] ({book_title}):\n{text}\n\n"
    if not books_content:
        books_content = {
            'ru': "В библиотеке не найдено специфических фрагментов по этому аспекту.",
            'uk': "У бібліотеці не знайдено специфічних фрагментів щодо цього аспекту.",
            'en': "No specific fragments found in the library for this aspect.",
        }[lang if lang in ('ru', 'uk') else 'en']

    template = get_template("progressed_synastry_aspect", language, mode)
    prompt = (template
              .replace("{layer_context}", layer_context)
              .replace("{aspect_data}", aspect_data)
              .replace("{books_content}", books_content))

    adapter = get_llm_adapter()
    analysis = await adapter.generate(prompt, language)

    return {
        "planet1": planet1,
        "planet2": planet2,
        "aspect": aspect_name,
        "aspect_ru": aspect_name_ru,
        "aspect_uk": aspect_name_uk,
        "orb": orb,
        "layer": layer,
        "analysis": analysis,
        "relevant_chunks": chunks,
    }


# ============================================================
# OLD CODE (v1) — kept for rollback, do not delete
# ============================================================

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
    top_books: int = 1  # FIXED: reduced from 5 to 1 (5 full books won't fit in the LLM's context)
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
    
    # NOTE: reads the ENTIRE text of the books (no truncation).
    # Make sure top_books=1 and the book size doesn't exceed ~300k characters,
    # otherwise the LLM will return a context-overflow error.
    # For analyzing multiple books, use the RAG endpoints (/analysis/planet, /analysis/query).
    
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
         # Limit the content size so as not to exceed the LLM's token limit
         content = nodes_book.get('content', '')[:400000]
         books_content += f"\n\n--- КНИГА ОБ УЗЛАХ И ПЛУТОНЕ ---\n{content}"

    for i, book in enumerate(other_books, 1):
        # FIXED: removed the [:10000] truncation, read the whole book
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
    


# END OF full_chart_analysis ↑

async def chat_with_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru"
) -> Dict[str, Any]:
    """
    Чат с астрологом-агентом — ГИБРИДНЫЙ подход
    """
    import asyncio

    adapter = get_llm_adapter()
    planets = chart_data.get("planets", {})

    async def search_question():
        return await search_chunks_by_query(question, top_k=10, chart_data=chart_data)

    async def search_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("house", "")
        query = f"{planet_name.lower()} house {house} {sign.lower()}"
        chunks = await search_chunks_all_books(query, top_k_per_book=2)
        return planet_name, chunks

    planet_tasks = [search_planet(name, data) for name, data in planets.items()]
    question_chunks, *planet_results = await asyncio.gather(
        search_question(),
        *planet_tasks,
        return_exceptions=True
    )

    question_context = ""
    if question_chunks and not isinstance(question_chunks, Exception):
        question_context = "\n=== ФРАГМЕНТЫ ПО ВОПРОСУ ===\n"
        for i, chunk in enumerate(question_chunks, 1):
            text = chunk.get("text", "")
            book_title = chunk.get("book_title", "")
            question_context += f"[{i}] ({book_title}):\n{text}\n"

    planet_context = ""
    for result in planet_results:
        if isinstance(result, Exception):
            continue
        planet_name, chunks = result
        if chunks:
            planet_context += f"\n【{planet_name.upper()}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")
                book_title = chunk.get("book_title", "")
                planet_context += f"[{i}] ({book_title}):\n{text}\n"

    books_context = f"{question_context}\n=== ФРАГМЕНТЫ ПО ПЛАНЕТАМ ===\n{planet_context}"
    
    # If no fragments were found at all — add an explicit note
    if not question_context.strip() and not planet_context.strip():
        books_context = "В библиотеке не найдено релевантных фрагментов по этому вопросу. Используйте общие принципы эволюционной астрологии и данные натальной карты."
    
    planets_summary = ""
    for planet_name, planet_data in planets.items():
        sign = planet_data.get("sign", "?")
        sign_ru = planet_data.get("sign_ru", sign)
        house = planet_data.get("house", "?")
        degree = round(planet_data.get("degree", 0), 1)
        retro = " (Rx)" if planet_data.get("is_retrograde") else ""
        planets_summary += f"  {planet_name}: {sign_ru} {degree}° дом {house}{retro}\n"

    system_prompt = f"""You are a personal astrologer. You have already done a full analysis of this person's natal chart and now answer their questions.

=== NATAL CHART ===
Sun: {chart_data.get('sun_sign_ru', chart_data.get('sun_sign', '?'))}
Moon: {chart_data.get('moon_sign_ru', chart_data.get('moon_sign', '?'))}
Ascendant: {chart_data.get('ascendant_ru', chart_data.get('ascendant', '?'))}
MC: {chart_data.get('mc_ru', chart_data.get('mc', '?'))}

PLANETS:
{planets_summary}

=== FULL CHART ANALYSIS ===
{full_analysis}

=== KNOWLEDGE FROM ASTROLOGY BOOKS ===
{books_context}

RULES:
- Answer personally — you know this chart
- Use book fragments as knowledge source
- Answer in the language of the user's question
- Be specific, not general
- Remember the full conversation history
- Do NOT make up book titles or authors"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    answer = await adapter.generate_with_messages(messages, language)

    return {
        "answer": answer,
        "relevant_chunks": question_chunks if not isinstance(question_chunks, Exception) else []
    }


async def chat_with_astrologer_optimized(
    question: str,
    chart_data: Dict[str, Any],
    language: str = "ru",
    top_k: int = 5
) -> Dict[str, Any]:
    """
    Оптимизированный чат с астрологом — только вопрос и карта,
    без full_analysis и chat_history. Быстрый RAG-ответ.
    """
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    adapter = get_llm_adapter()
    labels = get_labels(language)

    # 1. Short chart summary (key positions only)
    chart_summary = f"""{labels.get('natal_chart_label', 'НАТАЛЬНАЯ КАРТА')}
Солнце: {chart_data.get('sun_sign_ru', chart_data.get('sun_sign', '?'))}
Луна: {chart_data.get('moon_sign_ru', chart_data.get('moon_sign', '?'))}
Асцендент: {chart_data.get('ascendant_ru', chart_data.get('ascendant', '?'))}"""

    planets = chart_data.get("planets", {})
    if planets:
        chart_summary += f"\n{labels.get('planets', 'ПЛАНЕТЫ')}:"
        for planet_name, planet_data in sorted(planets.items()):
            sign = planet_data.get("sign", "?")
            sign_ru = planet_data.get("sign_ru", sign)
            house = planet_data.get("house", "?")
            retro = " (Rx)" if planet_data.get("is_retrograde") else ""
            chart_summary += f"\n  {planet_name}: {sign_ru} дом {house}{retro}"

    # 2. Search for chunks relevant to the question
    chunks = await search_chunks_by_query(question, top_k=top_k, chart_data=chart_data)

    # 3. Assemble the prompt
    prompt_parts = []
    system_prompt = get_template('analysis', language)
    prompt_parts.append(system_prompt)

    prompt_parts.append(f"\n\n{labels['query']}")
    prompt_parts.append(question)

    prompt_parts.append(f"\n\n{chart_summary}")

    if chunks:
        prompt_parts.append(f"\n\n{labels['found_fragments']}")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')
            if len(text) > 600:
                text = text[:600] + "..."
            book_title = chunk.get('book_title', '')
            book_info = f" ({book_title})" if book_title else ""
            prompt_parts.append(f"\n[{labels['fragment']} {i}]{book_info}:\n{text}")
    else:
        # Explicit note when no fragments found
        prompt_parts.append(f"\n\n=== ПРИМЕЧАНИЕ О ДОСТУПНЫХ ИСТОЧНИКАХ ===")
        prompt_parts.append("В библиотеке не найдено релевантных фрагментов по данному вопросу. Анализ должен быть основан на общих принципах эволюционной астрологии и предоставленных данных натальной карты.")
    
    prompt_parts.append(f"\n\n{labels['analysis']}")
    prompt_parts.append(labels.get('please_analyze', 'Answer the question based on the chart and book fragments.'))

    prompt = "".join(prompt_parts)

    # 4. Generate the answer
    answer = await adapter.generate(prompt, language)

    return {
        "answer": answer,
        "relevant_chunks": chunks
    }