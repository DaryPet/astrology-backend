from typing import List, Dict, Any, Optional
from datetime import datetime
from app.services.search_service import (
    search_chunks_by_query,
    search_chunks_simple,
)
from app.services.llm_adapter import get_llm_adapter
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template, get_relationship_context_prompt
from app.services.analysis_service import search_chunks_all_books, generate_summary


JEFF_GREEN_BOOK_ID = 26

PLANET_RU = {
    'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
    'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
    'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
    'Pluto': 'Плутон', 'NorthNode': 'Северный Узел',
    'SouthNode': 'Южный Узел', 'Chiron': 'Хирон',
    'Lilith': 'Лилит', 'Ascendant': 'Асцендент',
}


def build_synastry_aspect_prompt(
    planet1: str,
    planet2: str,
    aspect_name: str,
    aspect_name_ru: Optional[str],
    orb: float,
    chunks: List[Dict[str, Any]],
    language: str = "en",
    mode: Optional[str] = 'advanced'
) -> str:
    """Построить промпт для анализа аспекта синастрии"""
    
    if language == 'ru':
        planet1 = PLANET_RU.get(planet1, planet1)
        planet2 = PLANET_RU.get(planet2, planet2)
    
    prompt_parts = []
    labels = get_labels(language)
    system_prompt = get_template('synastry_aspect', language, mode)
    prompt_parts.append(system_prompt)
    
    prompt_parts.append(f"\n\n{labels['aspect_data']}")
    prompt_parts.append(f"{labels['planet1']}: {planet1}")
    prompt_parts.append(f"{labels['planet2']}: {planet2}")
    aspect_display = f"{aspect_name} ({aspect_name_ru})" if aspect_name_ru else aspect_name
    prompt_parts.append(f"{labels['aspect_type']}: {aspect_display}")
    prompt_parts.append(f"{labels['orb']}: {orb}°")
    
    if chunks:
        prompt_parts.append(f"\n\n{labels['found_fragments']}")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')
            if len(text) > 300:
                text = text[:300] + "..."
            prompt_parts.append(f"\n[{labels['fragment']} {i}]:\n{text}")
    else:
        # Explicit note when no fragments found
        prompt_parts.append(f"\n\n=== ПРИМЕЧАНИЕ О ДОСТУПНЫХ ИСТОЧНИКАХ ===")
        prompt_parts.append("В библиотеке не найдено специфических фрагментов по данному аспекту синастрии. Анализ должен быть основан на общих принципах эволюционной синастрии и данных карт.")
    
    prompt_parts.append(f"\n\n{labels['analysis']}")
    prompt_parts.append(labels['please_analyze_synastry_aspect'])
    
    return "\n".join(prompt_parts)


async def analyze_synastry_aspect(
    planet1: str,
    planet2: str,
    aspect_name: str,
    aspect_name_ru: Optional[str] = None,
    orb: float = 0.0,
    language: str = "en",
    top_k: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    Анализ конкретного аспекта в синастрии
    """
    
    if language == "ru" and aspect_name_ru:
        query = f"{planet1.lower()} {aspect_name_ru.lower()} {planet2.lower()} синастрия"
    else:
        query = f"{planet1} {aspect_name} {planet2} synastry"
    
    chunks = await search_chunks_by_query(query, top_k=top_k, book_id=JEFF_GREEN_BOOK_ID)
    
    if not chunks:
        chunks = await search_chunks_by_query(query, top_k=top_k)
    
    if not chunks:
        chunks = await search_chunks_simple(query, top_k=top_k)
    
    prompt = build_synastry_aspect_prompt(
        planet1=planet1,
        planet2=planet2,
        aspect_name=aspect_name,
        aspect_name_ru=aspect_name_ru,
        orb=orb,
        chunks=chunks,
        language=language,
        mode=mode
    )
    
    adapter = get_llm_adapter()
    analysis = await adapter.generate(prompt, language)
    
    return {
        "planet1": planet1,
        "planet2": planet2,
        "aspect": aspect_name,
        "aspect_ru": aspect_name_ru,
        "orb": orb,
        "analysis": analysis,
        "relevant_chunks": chunks
    }


async def full_synastry_analysis_v2(
    chart1_data: Dict[str, Any],
    chart2_data: Dict[str, Any],
    aspects: Optional[List[Dict[str, Any]]] = None,
    overlays: Optional[Dict[str, Any]] = None,
    language: str = "ru",
    top_k_per_book: int = 1,
    mode: str = 'advanced',
    relationship_context: Optional[str] = None

) -> Dict[str, Any]:
    """
    [v2] Полный анализ синастрии — ГИБРИДНЫЙ подход:
    - Для каждого аспекта синастрии делаем точечный RAG-поиск по ВСЕМ книгам
    - Для ключевых планет обеих карт делаем RAG-поиск
    - Собираем структурированный промпт
    - Один финальный вызов LLM

    Преимущества:
    - Все книги участвуют в анализе
    - Нет проблемы с превышением контекста
    - Каждый аспект получает релевантные фрагменты
    """
    import asyncio
    from app.utils.astrology_v2 import calculate_synastry, ASPECTS_RU, get_house_for_longitude

    adapter = get_llm_adapter()
    labels = get_labels(language)

    # 1. Расчёт аспектов синастрии (если не переданы напрямую)
    if not aspects:
        synastry_result = calculate_synastry(chart1_data, chart2_data)
        aspects = synastry_result.get('aspects', [])

    # 1.5 Расчёт house overlay (если не передан)
    if not overlays:
        overlays = {"planets_1_in_houses_2": {}, "planets_2_in_houses_1": {}}
        
        houses_2 = chart2_data.get('houses', {})
        houses_1 = chart1_data.get('houses', {})
        
        # Планеты партнера 1 в домах партнера 2
        for p_name, p_data in chart1_data.get('planets', {}).items():
            lon = p_data.get('full_degree', 0)
            house_num = get_house_for_longitude(lon, houses_2)
            if house_num:
                overlays["planets_1_in_houses_2"][p_name] = house_num
        
        # Планеты партнера 2 в домах партнера 1
        for p_name, p_data in chart2_data.get('planets', {}).items():
            lon = p_data.get('full_degree', 0)
            house_num = get_house_for_longitude(lon, houses_1)
            if house_num:
                overlays["planets_2_in_houses_1"][p_name] = house_num

    # 2. Фильтрация значимых аспектов (топ по приоритету)
    aspect_priority = {'Conjunction': 5, 'Opposition': 4, 'Trine': 3, 'Square': 2, 'Sextile': 1}
    sorted_aspects = sorted(aspects, key=lambda x: aspect_priority.get(x.get('aspect', ''), 0), reverse=True)
    top_aspects = sorted_aspects[:5]  # Топ-15 аспектов

    print(f"[full_synastry_analysis_v2] Total aspects: {len(aspects)}, top aspects: {len(top_aspects)}")

    # 3. Параллельный RAG-поиск по аспектам
    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get('planet1', '')
        p2 = asp.get('planet2', '')
        asp_type = asp.get('aspect', '')
        orb = asp.get('orb', 0)
        asp_ru = asp.get('aspect_ru', asp_type)

        # Строим поисковый запрос
        query = f"{p1} {asp_type} {p2} synastry"
        chunks = await search_chunks_by_query(query, top_k=top_k_per_book, book_id=JEFF_GREEN_BOOK_ID)
        return f"{p1} {asp_ru} {p2} (орб: {orb}°)", chunks

    # 4. Параллельный RAG-поиск по ключевым планетам
    key_planets = ['Pluto', 'NorthNode', 'SouthNode', 'Saturn', 'Sun', 'Moon', 'Ascendant', 'Venus', 'Mars', 'Jupiter']

    async def search_planet_synastry(planet_name: str, chart_num: int, chart_data: Dict) -> tuple:
        # Проверяем есть ли планета в карте
        planets = chart_data.get('planets', {})
        if planet_name not in planets and planet_name != 'Ascendant':
            return f"Planet {planet_name} (Chart {chart_num})", []

        query = f"{planet_name} synastry partner"
        chunks = await search_chunks_by_query(query, top_k=top_k_per_book, book_id=JEFF_GREEN_BOOK_ID)
        return f"Planet {planet_name} (Chart {chart_num})", chunks

    # Запуск параллельного поиска
    aspect_tasks = [search_aspect(asp) for asp in top_aspects]

    planet_tasks_chart1 = [
        search_planet_synastry(p, 1, chart1_data) for p in key_planets
    ]
    planet_tasks_chart2 = [
        search_planet_synastry(p, 2, chart2_data) for p in key_planets
    ]

    all_tasks = aspect_tasks + planet_tasks_chart1 + planet_tasks_chart2
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    print(f"[full_synastry_analysis_v2] RAG search completed. Tasks: {len(all_tasks)}")

    # 5. Сборка промпта
    synastry_template = get_template("synastry", language, mode)
    
    # Add relationship context to prompt
    context_prompt = get_relationship_context_prompt(relationship_context, language)
    if context_prompt:
        synastry_template = synastry_template + context_prompt

    # Подготовка списка аспектов
    aspects_list = []
    for asp in aspects:
        p1 = asp.get('planet1', '?')
        p2 = asp.get('planet2', '?')
        asp_ru = asp.get('aspect_ru', asp.get('aspect', '?'))
        orb = asp.get('orb', 0)

        # Берем знаки из самого аспекта (они уже добавлены на бэкенде/UI)
        p1_sign = asp.get('planet1_sign', '')
        p2_sign = asp.get('planet2_sign', '')

        # Fallback: если в аспекте нет знаков, берем из карт (для локально рассчитанных аспектов)
        if not p1_sign and chart1_data and 'planets' in chart1_data:
            p1_planet_data = chart1_data['planets'].get(p1, {})
            p1_sign = p1_planet_data.get('sign_ru', p1_planet_data.get('sign', ''))

        if not p2_sign and chart2_data and 'planets' in chart2_data:
            p2_planet_data = chart2_data['planets'].get(p2, {})
            p2_sign = p2_planet_data.get('sign_ru', p2_planet_data.get('sign', ''))

        # Переводим названия планет на русский язык если нужно
        if language == 'ru':
            p1_display = PLANET_RU.get(p1, p1)
            p2_display = PLANET_RU.get(p2, p2)
        else:
            p1_display = p1
            p2_display = p2
            
        aspects_list.append(f"ПАРТНЕР1:{p1_display} ({p1_sign}) {asp_ru} ПАРТНЕР2:{p2_display} ({p2_sign}) (орб: {orb}°)")

    aspects_str = "\n".join(aspects_list) if aspects_list else "Нет аспектов"

    # Формируем информацию об оверлеях
    PLANET_NAMES_RU = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон', 'NorthNode': 'Северный узел',
        'SouthNode': 'Южный узел', 'Lilith': 'Лилит', 'Chiron': 'Хирон'
    }

    overlays_str = "\n=== ОВЕРЛЕИ ДОМОВ ===\n"
    overlays_str += "\nПланеты партнера 1 в домах партнера 2:\n"
    for p_name, house_num in overlays["planets_1_in_houses_2"].items():
        p_ru = PLANET_NAMES_RU.get(p_name, p_name)
        overlays_str += f"\n  {p_ru} в доме {house_num}"

    overlays_str += "\n\nПланеты партнера 2 в домах партнера 1:\n"
    for p_name, house_num in overlays["planets_2_in_houses_1"].items():
        p_ru = PLANET_NAMES_RU.get(p_name, p_name)
        overlays_str += f"\n  {p_ru} в доме {house_num}"

    # Сборка фрагментов из книг - аспекты
    books_content = "\n=== ФРАГМЕНТЫ ПО АСПЕКТАМ СИНАСТРИИ ===\n"
    for i, result in enumerate(results[:len(top_aspects)]):
        if isinstance(result, Exception):
            print(f"[full_synastry_analysis_v2] Aspect search error: {result}")
            continue
        asp_label, chunks = result
        if chunks:
            books_content += f"\n【АСПЕКТ: {asp_label}】\n"
            for j, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:200]
                book_title = chunk.get("book_title", "")
                books_content += f"[{j}] ({book_title}):\n{text}\n"

    # Сборка фрагментов из книг - планеты
    books_content += "\n=== ФРАГМЕНТЫ ПО ПЛАНЕТАМ ===\n"
    for i, result in enumerate(results[len(top_aspects):], start=len(top_aspects)):
        if isinstance(result, Exception):
            print(f"[full_synastry_analysis_v2] Planet search error: {result}")
            continue
        planet_label, chunks = result
        if chunks:
            books_content += f"\n【{planet_label.upper()}】\n"
            for j, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:150]
                book_title = chunk.get("book_title", "")
                books_content += f"[{j}] ({book_title}):\n{text}\n"

    # Подставляем в шаблон
    prompt = synastry_template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # Добавляем данные карты 1
    prompt += f"\n\n=== КАРТА 1 ==="
    prompt += f"\nСолнце: {chart1_data.get('sun_sign_ru', '?')} в {chart1_data.get('sun_sign', '?')}"
    prompt += f"\nЛуна: {chart1_data.get('moon_sign_ru', '?')} в {chart1_data.get('moon_sign', '?')}"
    prompt += f"\nАсцендент: {chart1_data.get('ascendant_ru', '?')} в {chart1_data.get('ascendant', '?')}"

    planets1 = chart1_data.get('planets', {})
    prompt += f"\n\nПЛАНЕТЫ КАРТЫ 1:"
    for p_name, p_data in sorted(planets1.items()):
        sign_ru = p_data.get('sign_ru', p_data.get('sign', '?'))
        house = p_data.get('house', '?')
        is_retro = p_data.get('is_retrograde', False)
        rx_str = " (ретроградная)" if is_retro else ""
        prompt += f"\n  {p_name}: в {sign_ru}, дом {house}{rx_str}"

    houses1 = chart1_data.get('houses', {})
    prompt += f"\n\nДОМА КАРТЫ 1:"
    for house_num in range(1, 13):
        key = str(house_num)
        if key in houses1:
            h = houses1[key]
            prompt += f"\n  Дом {house_num}: {h.get('sign_ru', '?')}"

    # Добавляем данные карты 2
    prompt += f"\n\n=== КАРТА 2 ==="
    prompt += f"\nСолнце: {chart2_data.get('sun_sign_ru', '?')} в {chart2_data.get('sun_sign', '?')}"
    prompt += f"\nЛуна: {chart2_data.get('moon_sign_ru', '?')} в {chart2_data.get('moon_sign', '?')}"
    prompt += f"\nАсцендент: {chart2_data.get('ascendant_ru', '?')} в {chart2_data.get('ascendant', '?')}"

    planets2 = chart2_data.get('planets', {})
    prompt += f"\n\nПЛАНЕТЫ КАРТЫ 2:"
    for p_name, p_data in sorted(planets2.items()):
        sign_ru = p_data.get('sign_ru', p_data.get('sign', '?'))
        house = p_data.get('house', '?')
        is_retro = p_data.get('is_retrograde', False)
        rx_str = " (ретроградная)" if is_retro else ""
        prompt += f"\n  {p_name}: в {sign_ru}, дом {house}{rx_str}"

    houses2 = chart2_data.get('houses', {})
    prompt += f"\n\nДОМА КАРТЫ 2:"
    for house_num in range(1, 13):
        key = str(house_num)
        if key in houses2:
            h = houses2[key]
            prompt += f"\n  Дом {house_num}: {h.get('sign_ru', '?')}"

    # Подставляем данные в шаблон (для совместимости с {planets_1}, {houses_1} и т.д.)
    prompt = prompt.replace("{sun_sign_1}", chart1_data.get('sun_sign_ru', '?'))
    prompt = prompt.replace("{moon_sign_1}", chart1_data.get('moon_sign_ru', '?'))
    prompt = prompt.replace("{ascendant_1}", chart1_data.get('ascendant_ru', '?'))

    # Формируем строки планет и домов для шаблона
    planets_1_str = ""
    for p_name, p_data in sorted(planets1.items()):
        sign_ru = p_data.get('sign_ru', p_data.get('sign', '?'))
        house = p_data.get('house', '?')
        planets_1_str += f"\n  {p_name}: в {sign_ru}, дом {house}"
    prompt = prompt.replace("{planets_1}", planets_1_str)

    houses_1_str = ""
    for house_num in range(1, 13):
        key = str(house_num)
        if key in houses1:
            h = houses1[key]
            houses_1_str += f"\n  Дом {house_num}: {h.get('sign_ru', '?')}"
    prompt = prompt.replace("{houses_1}", houses_1_str)

    prompt = prompt.replace("{sun_sign_2}", chart2_data.get('sun_sign_ru', '?'))
    prompt = prompt.replace("{moon_sign_2}", chart2_data.get('moon_sign_ru', '?'))
    prompt = prompt.replace("{ascendant_2}", chart2_data.get('ascendant_ru', '?'))

    planets_2_str = ""
    for p_name, p_data in sorted(planets2.items()):
        sign_ru = p_data.get('sign_ru', p_data.get('sign', '?'))
        house = p_data.get('house', '?')
        planets_2_str += f"\n  {p_name}: в {sign_ru}, дом {house}"
    prompt = prompt.replace("{planets_2}", planets_2_str)

    houses_2_str = ""
    for house_num in range(1, 13):
        key = str(house_num)
        if key in houses2:
            h = houses2[key]
            houses_2_str += f"\n  Дом {house_num}: {h.get('sign_ru', '?')}"
    prompt = prompt.replace("{houses_2}", houses_2_str)
    prompt = prompt.replace("{house_overlays}", overlays_str)

    # 6. Вызов LLM
    print(f"[full_synastry_analysis_v2] Sending prompt to LLM (~{len(prompt)//4} tokens estimated)")

    try:
        full_analysis = await adapter.generate(prompt, language)
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[full_synastry_analysis_v2] LLM error: {e}")

    # 7. Краткое резюме (первые 500 символов)
    summary = full_analysis[:500].rsplit('. ', 1)[0] if len(full_analysis) > 500 else full_analysis

    # 8. Возврат результата
    return {
        "chart1_summary": {
            "sun_sign": chart1_data.get('sun_sign', '?'),
            "sun_sign_ru": chart1_data.get('sun_sign_ru', '?'),
            "moon_sign": chart1_data.get('moon_sign', '?'),
            "moon_sign_ru": chart1_data.get('moon_sign_ru', '?'),
            "ascendant": chart1_data.get('ascendant', '?'),
            "ascendant_ru": chart1_data.get('ascendant_ru', '?'),
        },
        "chart2_summary": {
            "sun_sign": chart2_data.get('sun_sign', '?'),
            "sun_sign_ru": chart2_data.get('sun_sign_ru', '?'),
            "moon_sign": chart2_data.get('moon_sign', '?'),
            "moon_sign_ru": chart2_data.get('moon_sign_ru', '?'),
            "ascendant": chart2_data.get('ascendant', '?'),
            "ascendant_ru": chart2_data.get('ascendant_ru', '?'),
        },
        "aspects": aspects,
        "overlays": overlays,
        "analysis": full_analysis,
        "summary": summary,
        "relevant_chunks": [],
        "language": language,
        "relationship_context": relationship_context,
        "created_at": datetime.utcnow()
    }

async def chat_with_synastry_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru",
    relationship_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Чат с астрологом по синастрии
    """
    from app.services.search_service import search_chunks_by_query

    adapter = get_llm_adapter()

    chart1 = chart_data.get('chart1', {})
    chart2 = chart_data.get('chart2', {})
    aspects = chart_data.get('aspects', [])
    overlays = chart_data.get('overlays', {})

    # RAG поиск по вопросу
    chunks = await search_chunks_by_query(question, top_k=10, book_id=JEFF_GREEN_BOOK_ID)
    if not chunks:
        chunks = await search_chunks_by_query(question, top_k=10)

    books_context = ""
    if chunks:
        books_context = "\n=== ФРАГМЕНТЫ ПО ВОПРОСУ ===\n" if language == 'ru' else "\n=== BOOK FRAGMENTS ===\n"
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text", "")[:400]
            book_title = chunk.get("book_title", "")
            books_context += f"[{i}] ({book_title}):\n{text}\n"

    def planets_str(planets_dict):
        result = ""
        for pn, pd in planets_dict.items():
            sign_ru = pd.get('sign_ru', pd.get('sign', '?'))
            house = pd.get('house', '?')
            degree = round(pd.get('degree', 0), 1)
            retro = " (Rx)" if pd.get('is_retrograde') else ""
            result += f"  {pn}: {sign_ru} {degree}° дом {house}{retro}\n"
        return result

    aspects_str = ""
    for asp in aspects:
        p1 = PLANET_RU.get(asp.get('planet1', ''), asp.get('planet1', ''))
        p2 = PLANET_RU.get(asp.get('planet2', ''), asp.get('planet2', ''))
        asp_ru = asp.get('aspect_ru', asp.get('aspect', ''))
        orb = asp.get('orb', 0)
        aspects_str += f"  {p1} {asp_ru} {p2} (орб: {orb}°)\n"

    overlays_str = ""
    p1_in_h2 = overlays.get('planets_1_in_houses_2', {})
    p2_in_h1 = overlays.get('planets_2_in_houses_1', {})
    for p, h in p1_in_h2.items():
        if language == 'ru':
            overlays_str += f"  {PLANET_RU.get(p, p)} Партнёра 1 в доме {h} Партнёра 2\n"
        else:
            overlays_str += f"  {p} of Partner 1 in house {h} of Partner 2\n"
    for p, h in p2_in_h1.items():
        if language == 'ru':
            overlays_str += f"  {PLANET_RU.get(p, p)} Партнёра 2 в доме {h} Партнёра 1\n"
        else:
            overlays_str += f"  {p} of Partner 2 in house {h} of Partner 1\n"

    if language == 'ru':
        context_instruction = get_relationship_context_prompt(relationship_context, language) if relationship_context else ""
        system_prompt = f"""Ты личный астролог. Ты уже сделал полный анализ синастрии этой пары и теперь отвечаешь на вопросы. Отвечай строго по данным карт — не выдумывай.
{context_instruction}
=== ПАРТНЁР 1 ===
Солнце: {chart1.get('sun_sign_ru', '?')}, Луна: {chart1.get('moon_sign_ru', '?')}, Асц: {chart1.get('ascendant_ru', '?')}
ПЛАНЕТЫ:
{planets_str(chart1.get('planets', {}))}

=== ПАРТНЁР 2 ===
Солнце: {chart2.get('sun_sign_ru', '?')}, Луна: {chart2.get('moon_sign_ru', '?')}, Асц: {chart2.get('ascendant_ru', '?')}
ПЛАНЕТЫ:
{planets_str(chart2.get('planets', {}))}

=== АСПЕКТЫ СИНАСТРИИ ===
{aspects_str}

=== ОВЕРЛЕИ ДОМОВ ===
{overlays_str}

=== ПОЛНЫЙ АНАЛИЗ ===
{full_analysis}

{books_context}

ПРАВИЛА:
- Отвечай строго по данным карт выше
- Не выдумывай планеты и позиции
- Отвечай на языке вопроса
- Используй ТОЛЬКО И ИСКЛЮЧИТЕЛЬНО фрагменты из заданныз книг как ЕДИНСТВЕННЫЙ источник знаний но НИКОГДА не упоминай их в ответе, т. е. есдинственная истина это база знаний из книг, а ответ должен бьыть человеческим понятным языком
- Никаких фраз "фрагмент [3]", "в книге сказано", "источник упоминает"
- Излагай всё как свои астрологические знания
- Используй "в астрологии" если нужна ссылка
- Используй только Партнёр 1 и Партнёр 2
- Никаких он/она — только Партнёр 1 и Партнёр 2"""
    else:
        context_instruction = get_relationship_context_prompt(relationship_context, language) if relationship_context else ""
        system_prompt = f"""You are a personal astrologer. You have already done a full synastry analysis and now answer questions. Answer strictly based on the chart data — do not make up anything.
{context_instruction}
=== PARTNER 1 ===
Sun: {chart1.get('sun_sign_ru', '?')}, Moon: {chart1.get('moon_sign_ru', '?')}, Asc: {chart1.get('ascendant_ru', '?')}
PLANETS:
{planets_str(chart1.get('planets', {}))}

=== PARTNER 2 ===
Sun: {chart2.get('sun_sign_ru', '?')}, Moon: {chart2.get('moon_sign_ru', '?')}, Asc: {chart2.get('ascendant_ru', '?')}
PLANETS:
{planets_str(chart2.get('planets', {}))}

=== SYNASTRY ASPECTS ===
{aspects_str}

=== HOUSE OVERLAYS ===
{overlays_str}

=== FULL ANALYSIS ===
{full_analysis}

{books_context}

RULES:
- Answer strictly based on chart data above
- Do not make up planets or positions
- Answer in the language of the question
- Use fragments as knowledge source but NEVER mention them in the answer
- Do NOT say "Fragment [3]", "the book says", "the source mentions"
- Present all insights as your own astrological expertise
- Use "in astrology" if a reference is needed
- Use only Partner 1 and Partner 2
- No he/she — only Partner 1 and Partner 2"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    answer = await adapter.generate_with_messages(messages, language)

    return {
        "answer": answer,
        "relevant_chunks": chunks
    }