from typing import List, Dict, Any, Optional
from datetime import datetime
from app.services.search_service import (
    search_chunks_by_query,
    search_chunks_simple,
)
from app.services.llm_adapter import get_llm_adapter
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template
from app.services.analysis_service import search_chunks_all_books, generate_summary


JEFF_GREEN_BOOK_ID = 26


def build_synastry_aspect_prompt(
    planet1: str,
    planet2: str,
    aspect_name: str,
    aspect_name_ru: Optional[str],
    orb: float,
    chunks: List[Dict[str, Any]],
    language: str = "en"
) -> str:
    """Построить промпт для анализа аспекта синастрии"""
    
    prompt_parts = []
    labels = get_labels(language)
    system_prompt = get_template('synastry_aspect', language)
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
    top_k: int = 5
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
        language=language
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
    language: str = "ru",
    top_k_per_book: int = 1
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

    # 1. Расчёт аспектов синастрии
    synastry_result = calculate_synastry(chart1_data, chart2_data)
    aspects = synastry_result.get('aspects', [])

    # 1.5 Расчёт house overlay
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
        chunks = await search_chunks_all_books(query, top_k_per_book=top_k_per_book)
        return f"{p1} {asp_ru} {p2} (орб: {orb}°)", chunks

    # 4. Параллельный RAG-поиск по ключевым планетам
    key_planets = ['Pluto', 'NorthNode', 'SouthNode', 'Saturn', 'Sun', 'Moon', 'Ascendant', 'Venus', 'Mars', 'Jupiter']

    async def search_planet_synastry(planet_name: str, chart_num: int, chart_data: Dict) -> tuple:
        # Проверяем есть ли планета в карте
        planets = chart_data.get('planets', {})
        if planet_name not in planets and planet_name != 'Ascendant':
            return f"Planet {planet_name} (Chart {chart_num})", []

        query = f"{planet_name} synastry partner"
        chunks = await search_chunks_all_books(query, top_k_per_book=top_k_per_book)
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
    synastry_template = get_template("synastry", language)

    # Подготовка списка аспектов
    aspects_list = []
    for asp in aspects:
        p1 = asp.get('planet1', '?')
        p2 = asp.get('planet2', '?')
        asp_ru = asp.get('aspect_ru', asp.get('aspect', '?'))
        orb = asp.get('orb', 0)
        aspects_list.append(f"{p1} {asp_ru} {p2} (орб: {orb}°)")

    aspects_str = "\n".join(aspects_list) if aspects_list else "Нет аспектов"

    # Формируем информацию об оверлеях
    overlays_str = "\n=== ОВЕРЛЕИ ДОМОВ ===\n"
    overlays_str += "\nПланеты партнера 1 в домах партнера 2:\n"
    for p_name, house_num in overlays["planets_1_in_houses_2"].items():
        overlays_str += f"\n  {p_name} в доме {house_num}"
    
    overlays_str += "\n\nПланеты партнера 2 в домах партнера 1:\n"
    for p_name, house_num in overlays["planets_2_in_houses_1"].items():
        overlays_str += f"\n  {p_name} в доме {house_num}"

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
        "created_at": datetime.utcnow()
    }
