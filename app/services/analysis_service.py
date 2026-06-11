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


# Числительные домов для RAG-запросов (используется в full_chart_analysis_v2 и progressions_analysis)
HOUSE_WORDS = {
    1: "first", 2: "second", 3: "third", 4: "fourth",
    5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth",
    9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth"
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
#     [v2] Гибридный RAG: берёт топ-N чанков из КАЖДОЙ книги отдельно.
#     Гарантирует что все книги участвуют в анализе.
#     """
#     from supabase import create_client
#     from app.core.config import settings
#     from app.services.search_service import search_chunks_hybrid

#     try:
#         supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
#         books_response = supabase.table("books").select("id, title").execute()

#         if not books_response.data:
#             return []

#         # Параллельный поиск по всем книгам через asyncio.gather
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


async def search_chunks_all_books(
    query: str,
    top_k_per_book: int = 3
) -> List[Dict[str, Any]]:
    """
    [v2] Гибридный RAG: ОДИН запрос ко всем книгам сразу.
    Устраняет проблему множественных вызовов RPC.
    """
    from supabase import create_client
    from app.core.config import settings
    from app.services.search_service import search_chunks_hybrid
    from app.services.supabase_async import run_sync_in_thread

    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        
        # 1. Получаем список книг для маппинга названий
        # Оборачиваем синхронный вызов в async executor чтобы не блокировать event loop
        table_call = supabase.table("books").select("id, title")
        books_response = await run_sync_in_thread(table_call.execute)
        if not books_response.data:
            return []
        
        book_map = {b["id"]: b.get("title", "") for b in books_response.data}
        total_books = len(books_response.data)
        
        # 2. ОДИН запрос без фильтра по book_id.
        # Запрашиваем больше чанков, чтобы охватить все книги
        chunks = await search_chunks_hybrid(
            query,
            top_k=top_k_per_book * total_books 
        )
        
        # 3. Добавляем названия книг
        if chunks:
            for chunk in chunks:
                chunk["book_title"] = book_map.get(chunk.get("book_id", ""), "")
        
        # Удаляем дубликаты
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
    top_k_per_book: int = 3,
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
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    adapter = get_llm_adapter()
    labels = get_labels(language)

    planets = chart_data.get("planets", {})
    aspects = chart_data.get("aspects", [])
    houses = chart_data.get("houses", {})
    houses_meta = chart_data.get("houses_meta", {})

    # --- Шаг 1: Параллельный RAG-поиск по каждой планете ---
    async def search_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        # Handle Pars Fortuna
        search_name = "pars fortuna" if planet_name.lower() in ["ft", "pars fortuna", "part of fortune", "fortuna", "парс фортуны"] else planet_name.lower()
        query = f"{search_name} {house_word} house {sign.lower()}"
        chunks = await search_chunks_all_books(query, top_k_per_book=top_k_per_book)
        return planet_name, chunks

    # --- Шаг 2: Параллельный RAG-поиск по каждому аспекту ---
    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("planet1", "")
        p2 = asp.get("planet2", "")
        asp_type = asp.get("aspect", asp.get("aspect_ru", ""))
        query = f"{p1.lower()} {asp_type.lower()} {p2.lower()}"
        chunks = await search_chunks_all_books(query, top_k_per_book=2)
        return f"{p1} {asp_type} {p2}", chunks

    print(f"[full_chart_analysis_v2] Starting parallel RAG for {len(planets)} planets and {len(aspects)} aspects")

    planet_tasks = [search_planet(name, data) for name, data in planets.items()]
    aspect_tasks = [search_aspect(asp) for asp in aspects]  # Топ-10 аспектов

    # Add Pars Fortuna search task
    pf = houses_meta.get('pars_fortuna', {})
    if pf:
        async def search_pars_fortuna():
            query = "pars fortuna (парс фортуны) дом"
            chunks = await search_chunks_all_books(query, top_k_per_book=top_k_per_book)
            return "Pars Fortuna", chunks
        planet_tasks.append(search_pars_fortuna())

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)

    # --- Шаг 3: Сборка структурированного промпта ---
    prompt_parts = []

    # Системный промпт (используем существующий шаблон synthesis)
    synthesis_template = get_template("synthesis", language, mode)

    # Аспекты для шаблона
    aspects_list = []
    for asp in aspects:
        p1 = asp.get("planet1", "?")
        p2 = asp.get("planet2", "?")
        asp_ru = asp.get("aspect_ru", asp.get("aspect", "?"))
        aspects_list.append(f"{p1} {asp_ru} {p2}")
    aspects_str = "\n".join(aspects_list) if aspects_list else "Нет аспектов"

    # Собираем контент книг как структурированные фрагменты (не целые книги)
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

    # Подставляем в шаблон
    prompt = synthesis_template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # Данные натальной карты
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

    # --- Шаг 4: Один финальный вызов LLM ---
    print(f"[full_chart_analysis_v2] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    try:
        full_analysis = await adapter.generate(prompt, language)
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"

    # --- Шаг 5: Генерация краткого резюме (summary) ---
    summary = await generate_summary(full_analysis, language)

    return {
        "analysis": full_analysis,
        "summary": summary,
        "book_analyses": [],
        "chart_summary": {
            "sun_sign": chart_data.get("sun_sign", "?"),
            "sun_sign_ru": chart_data.get("sun_sign_ru", "?"),
            "moon_sign": chart_data.get("moon_sign", "?"),
            "moon_sign_ru": chart_data.get("moon_sign_ru", "?"),
            "ascendant": chart_data.get("ascendant", "?"),
            "ascendant_ru": chart_data.get("ascendant_ru", "?"),
            "planets_count": len(planets),
        },
        "language": language,
        "version": "v2_hybrid_rag"
    }


# ============================================================
# SECONDARY PROGRESSIONS ANALYSIS (анализ вторичных прогрессий)
# ============================================================

async def progressions_analysis(
    natal_chart: Dict[str, Any],
    progressions: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 2,
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

    # В прогрессиях интерпретационно значимы личные планеты (внешние почти не двигаются)
    PERSONAL_PLANETS = ["Sun", "Moon", "Mercury", "Venus", "Mars"]

    # --- Шаг 1: Параллельный RAG-поиск ---
    async def search_progressed_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("natal_house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        query = f"progressed {planet_name.lower()} {sign.lower()} {house_word} house"
        chunks = await search_chunks_all_books(query, top_k_per_book=top_k_per_book)
        return planet_name, chunks

    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("progressed", asp.get("planet1", ""))
        p2 = asp.get("natal", asp.get("planet2", ""))
        asp_type = asp.get("aspect", "")
        query = f"progressed {p1.lower()} {asp_type.lower()} natal {p2.lower()}"
        chunks = await search_chunks_all_books(query, top_k_per_book=2)
        return f"{p1} {asp_type} {p2}", chunks

    async def search_general() -> tuple:
        chunks = await search_chunks_all_books(
            "secondary progressions progressed chart day for a year",
            top_k_per_book=top_k_per_book
        )
        return "Secondary Progressions", chunks

    planet_tasks = [
        search_progressed_planet(name, prog_planets[name])
        for name in PERSONAL_PLANETS if name in prog_planets
    ]
    # Планеты, сменившие знак относительно натала — поворотные точки, ищем и их
    for name, data in prog_planets.items():
        if data.get("changed_sign") and name not in PERSONAL_PLANETS:
            planet_tasks.append(search_progressed_planet(name, data))
    planet_tasks.append(search_general())

    aspect_tasks = [search_aspect(asp) for asp in aspects[:10]]

    print(f"[progressions_analysis] Parallel RAG: {len(planet_tasks)} planet queries, {len(aspect_tasks)} aspect queries")

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)

    # --- Шаг 2: Сборка структурированного промпта ---
    template = get_template("progressions", language, mode)

    # Список аспектов прогрессий к наталу
    aspects_list = []
    for asp in aspects:
        p1 = asp.get("progressed", asp.get("planet1", "?"))
        p2 = asp.get("natal", asp.get("planet2", "?"))
        asp_ru = asp.get("aspect_ru", asp.get("aspect", "?"))
        if language == 'ru':
            aspects_list.append(f"Прогрессивный {p1} {asp_ru} натальный {p2}")
        else:
            aspects_list.append(f"Progressed {p1} {asp.get('aspect', '?')} natal {p2}")
    aspects_str = "\n".join(aspects_list) if aspects_list else (
        "Точных аспектов к натальной карте сейчас нет" if language == 'ru'
        else "No exact aspects to the natal chart right now"
    )

    # Фрагменты книг
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

    # --- Данные прогрессий ---
    age = progressions.get("age_years", "?")
    period = progressions.get("period", "?")

    prompt += f"\n\n=== ДАННЫЕ ВТОРИЧНЫХ ПРОГРЕССИЙ ==="
    prompt += f"\nВозраст: {age}"
    prompt += f"\nПериод: {period}"

    prog_asc = progressions.get("progressed_ascendant", {})
    prog_mc = progressions.get("progressed_mc", {})
    if prog_asc:
        prompt += f"\nПрогрессивный Асцендент: {prog_asc.get('sign_ru', prog_asc.get('sign', '?'))}"
    if prog_mc:
        prompt += f"\nПрогрессивный MC: {prog_mc.get('sign_ru', prog_mc.get('sign', '?'))}"

    prompt += f"\n\n=== ПРОГРЕССИВНЫЕ ПЛАНЕТЫ (знак, натальный дом) ==="
    for planet_name in PERSONAL_PLANETS + [n for n in prog_planets if n not in PERSONAL_PLANETS]:
        planet_data = prog_planets.get(planet_name)
        if not planet_data:
            continue
        sign_ru = planet_data.get("sign_ru", planet_data.get("sign", "?"))
        house = planet_data.get("natal_house", "?")
        rx_str = " (ретроградная)" if planet_data.get("is_retrograde") else ""
        changed = ""
        if planet_data.get("changed_sign") and planet_data.get("natal_sign"):
            natal_sign_ru = natal_planets.get(planet_name, {}).get("sign_ru", planet_data.get("natal_sign"))
            changed = f" — СМЕНИЛА ЗНАК (в натале была в {natal_sign_ru})"
        prompt += f"\n{planet_name}: в {sign_ru}, {labels.get('house', 'дом')} {house}{rx_str}{changed}"

    prompt += f"\n\n=== НАТАЛЬНАЯ ОСНОВА ==="
    prompt += f"\nСолнце: {natal_summary.get('sun_sign_ru', natal_chart.get('sun_sign_ru', '?'))}"
    prompt += f"\nЛуна: {natal_summary.get('moon_sign_ru', natal_chart.get('moon_sign_ru', '?'))}"
    prompt += f"\nАсцендент: {natal_summary.get('ascendant_ru', natal_chart.get('ascendant_ru', '?'))}"

    # --- Шаг 3: Один финальный вызов LLM ---
    print(f"[progressions_analysis] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    try:
        full_analysis = await adapter.generate(prompt, language)
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"

    # --- Шаг 4: Краткое резюме ---
    summary = await generate_summary(full_analysis, language)

    prog_moon = prog_planets.get("Moon", {})
    prog_sun = prog_planets.get("Sun", {})

    return {
        "analysis": full_analysis,
        "summary": summary,
        "progressions_summary": {
            "period": period,
            "age_years": age,
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


# ============================================================
# СТАРЫЙ КОД (v1) — оставлен для отката, не удалять
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
    top_books: int = 1  # ИСПРАВЛЕНО: уменьшено с 5 до 1 (5 полных книг не влезут в контекст LLM)
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
    


# ТУТ КОНЕЦ full_chart_analysis ↑

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
    
    # Если ни одного фрагмента не нашлось — добавляем явное примечание
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

    # 1. Краткая сводка карты (только ключевые позиции)
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

    # 2. Поиск релевантных чанков по вопросу
    chunks = await search_chunks_by_query(question, top_k=top_k, chart_data=chart_data)

    # 3. Сборка промпта
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

    # 4. Генерация ответа
    answer = await adapter.generate(prompt, language)

    return {
        "answer": answer,
        "relevant_chunks": chunks
    }