from typing import List, Dict, Any, Optional
from app.services.search_service import (
    search_chunks_by_query,
    search_chunks_simple,
    parse_astrology_query,
    build_search_context,
)
from app.services.llm_adapter import generate_analysis, get_llm_adapter

# Маппинг планет на book_id для приоритетного поиска
# Если планета указана - ищем сначала в этой книге, потом во всех остальных
# Все остальные планеты → book_id = 21
PLANET_TO_BOOK_ID = {
    # Специфические книги для определенных планет
    "Pluto": 8,
    "Saturn": 20,
    "Neptune": 7,
    "North Node": 6,
    "South Node": 6,
}


ANALYSIS_PROMPTS = {
    'ru': """Вы эксперт по астрологии с глубокими знаниями классических и современных астрологических традиций. 
Проанализируйте найденные фрагменты из астрологических книг в контексте натальной карты и запроса пользователя.
Дайте подробный, персонализированный анализ на русском языке.

Используйте:
- Натальную карту для определения положения планет в домах, использщовать данные полученные при расчетах! не выдумывать!
- Найденные фрагменты из книг как справочный материал и основной материал! 
- Запрос пользователя как основу для анализа

Ваш анализ должен быть:
- Конкретным и персонализированным
- Основанным на фактах из натальной карты
- Связным и логичным
- Полезным для пользователя
 - содержать конкретные детали из натальной карты и найденных фрагментов, чтобы поддержать ваши выводы
 - писать на основе каких книг найденных фрагментов вы делаете выводы."

Если в найденных фрагментах нет релевантной информации - написать что информация не найдена""",
    
    'en': """You are an expert in astrology with deep knowledge of classical and modern astrological traditions.
Analyze the found fragments from astrology books in the context of the natal chart and user query.
Provide detailed, personalized analysis in English.

Use:
- Natal chart to determine planetary positions in houses
- Found book fragments as reference material
- User query as the basis for analysis

Your analysis should be:
- Specific and personalized
- Based on facts from the natal chart
- Coherent and logical
- Useful for the user

If there is no relevant information in the found fragments, write that the information was not found.""",
 
}


def build_analysis_prompt(
    user_query: str,
    chart_data: Optional[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    language: str = "en"
) -> str:
    """Построить промпт для LLM"""
    
    prompt_parts = []
    
    system_prompt = ANALYSIS_PROMPTS.get(language, ANALYSIS_PROMPTS['en'])
    prompt_parts.append(system_prompt)
    
    prompt_parts.append("\n\n=== ЗАПРОС ПОЛЬЗОВАТЕЛЯ / USER QUERY ===")
    prompt_parts.append(user_query)
    
    if chart_data:
        prompt_parts.append("\n\n=== НАТАЛЬНАЯ КАРТА / NATAL CHART ===")
        
        planets = chart_data.get('planets', {})
        prompt_parts.append("\nПланеты в домах / Planets in houses:")
        for planet_name, planet_data in planets.items():
            sign = planet_data.get('sign', 'Unknown')
            sign_ru = planet_data.get('sign_ru', sign)
            degree = planet_data.get('degree', 0)
            house = planet_data.get('house', '?')
            prompt_parts.append(f"  {planet_name}: {sign} {degree}° (дом {house})")
        
        houses = chart_data.get('houses', {})
        prompt_parts.append("\nКуспиды домов / House cusps:")
        for house_num in range(1, 13):
            if house_num in houses:
                house_data = houses[house_num]
                cusp = house_data.get('cusp_longitude', 0)
                sign = house_data.get('sign', 'Unknown')
                prompt_parts.append(f"  House {house_num}: {sign} {cusp:.1f}°")
        
        houses_meta = chart_data.get('houses_meta', {})
        if houses_meta:
            pf = houses_meta.get('pars_fortuna', {})
            if pf:
                prompt_parts.append(f"\nPars Fortuna: {pf.get('sign', '?')} {pf.get('degree', 0)}° (дом {pf.get('house', '?')})")
    
    if chunks:
        prompt_parts.append("\n\n=== НАЙДЕННЫЕ ФРАГМЕНТЫ ИЗ КНИГ / FOUND BOOK FRAGMENTS ===")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')
            if len(text) > 600:
                text = text[:600] + "..."
            prompt_parts.append(f"\n[Фрагмент {i}]:\n{text}")
    
    prompt_parts.append("\n\n=== АНАЛИЗ / ANALYSIS ===")
    prompt_parts.append("Пожалуйста, дайте подробный анализ. / Please provide detailed analysis.")
    
    return "\n".join(prompt_parts)


async def analyze_astrology_query(
    query: str,
    chart_data: Optional[Dict[str, Any]] = None,
    top_k: int = 5,
    llm_provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    Основная функция для поиска и анализа астрологического запроса
    
    Args:
        query: Запрос пользователя (например "Сатурн 7 дом")
        chart_data: Данные натальной карты (опционально)
        top_k: Количество чанков для поиска
        llm_provider: LLM провайдер (опционально)
    
    Returns:
        Dict с результатами анализа
    """
    
    parsed_query = parse_astrology_query(query)
    query_language = parsed_query.get('language', 'en')
    
    chunks = await search_chunks_by_query(query, top_k=top_k, chart_data=chart_data)
    
    if not chunks:
        chunks = await search_chunks_simple(query, top_k=top_k)
    
    context = build_search_context(chart_data, chunks)
    
    prompt = build_analysis_prompt(query, chart_data, chunks, query_language)
    
    adapter = get_llm_adapter(llm_provider)
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


PLANET_PROMPTS = {
    'ru': """Вы эксперт по астрологии с глубокими знаниями классических и современных астрологических традиций.
Проанализируйте положение планеты в натальной карте и дайте подробный персонализированный анализ на русском языке.

Ваш анализ должен быть:
- Конкретным и персонализированным для этой планеты
- Основанным на положении в знаке и доме
- Связным и логичным (3-5 абзацев)
- Полезным для понимания влияния этой планеты
- Используй ТОЛЬКО информацию из найденных чанков

В АНАЛИЗЕ ОБЯЗАТЕЛЬНО УЧТИ:
- Если планета ретроградная (Rx) - объясни как это влияет на её проявление (обращённость внутрь, задержка, переосмысление)
- Если планета директная (D) - объясни её прямое, активное проявление

ВАЖНО:
- НЕ придумывай названия книг, авторов или источников
- НЕ ссылайся на книги, которых нет в предоставленных фрагментах
- Если в чанках недостаточно информации - честно напиши "Информация не найдена"

При цитировании указывай ТОЛЬКО те книги, которые реально есть в предоставленных фрагментах.""",
    
    'en': """You are an expert in astrology with deep knowledge of classical and modern astrological traditions.
Analyze the position of a planet in the natal chart and provide detailed personalized analysis in English.

Your analysis should be:
- Specific and personalized for this planet
- Based on position in sign and house
- Coherent and logical (3-5 paragraphs)
- Useful for understanding the influence of this planet
- Use ONLY information from the found chunks

IN YOUR ANALYSIS YOU MUST CONSIDER:
- If the planet is retrograde (Rx) - explain how this affects its manifestation (introspection, delay, reconsideration)
- If the planet is direct (D) - explain its direct, active manifestation

IMPORTANT:
- Do NOT make up book titles, authors or sources
- Do NOT cite books that are not in the provided fragments
- If there is not enough information in chunks - honestly say "Information not found"

When citing, mention ONLY the books that are actually in the provided fragments.""",
      

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
    is_retrograde: bool = False
) -> str:
    """Построить промпт для анализа конкретной планеты"""
    
    prompt_parts = []
    
    # Получить промпт для нужного языка, fallback на 'en'
    system_prompt = PLANET_PROMPTS.get(language, PLANET_PROMPTS['en'])
    prompt_parts.append(system_prompt)
    
    prompt_parts.append("\n\n=== ДАННЫЕ ПЛАНЕТЫ / PLANET DATA ===")
    prompt_parts.append(f"Планета / Planet: {planet}")
    prompt_parts.append(f"Знак / Sign: {sign}")
    prompt_parts.append(f"Градус / Degree: {degree}°")
    prompt_parts.append(f"Дом / House: {house}")
    prompt_parts.append(f"Знак на куспиде дома / House sign: {house_sign}")
    prompt_parts.append(f"Движение / Motion: {'Ретроградная (Rx)' if is_retrograde else 'Директная (D)'} / {'Retrograde (Rx)' if is_retrograde else 'Direct (D)'}")
    
    if aspects:
        prompt_parts.append("\nАспекты планеты / Planet aspects:")
        for asp in aspects:
            prompt_parts.append(f"  - {asp.get('aspect', 'Unknown')} to {asp.get('planet', 'Unknown')} (orb: {asp.get('orb', 0)}°)")
    
    if chunks:
        prompt_parts.append("\n\n=== НАЙДЕННЫЕ ФРАГМЕНТЫ ИЗ КНИГ / FOUND BOOK FRAGMENTS ===")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')
            if len(text) > 600:
                text = text[:600] + "..."
            prompt_parts.append(f"\n[Фрагмент {i}]:\n{text}")
    
    prompt_parts.append("\n\n=== АНАЛИЗ / ANALYSIS ===")
    prompt_parts.append("Пожалуйста, дайте подробный анализ этой планеты. / Please provide detailed analysis of this planet.")
    
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
    
    Args:
        planet: Название планеты (Sun, Moon, Mars, etc.)
        sign: Знак (Leo, Cancer, etc.)
        degree: Градус в знаке
        house: Номер дома (1-12)
        house_sign: Знак на куспиде дома (опционально)
        is_retrograde: Ретроградная ли планета (True = ретроградная, False = директная)
        aspects: Список аспектов планеты
        language: Код языка (ru, en, zh, es, fr, de, etc.)
        top_k: Количество чанков для поиска
    
    Returns:
        Dict с анализом планеты и найденными чанками
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
    
    # Определяем book_id по планете
    book_id = PLANET_TO_BOOK_ID.get(planet.capitalize())
    # Если планеты нет в словаре - ищем по всем книгам (book_id = None)
    if not book_id:
        book_id = None
    
    # Формируем запрос для гибридного поиска (BM25 + Vector)
    # Ключевые слова для BM25: планета + дом + знак
    house_words = {
        1: 'first', 2: 'second', 3: 'third', 4: 'fourth', 5: 'fifth', 
        6: 'sixth', 7: 'seventh', 8: 'eighth', 9: 'ninth', 
        10: 'tenth', 11: 'eleventh', 12: 'twelfth'
    }
    house_word = house_words.get(house, str(house))
    
    # Формат: "pluto seventh house libra" - для лучшего BM25 совпадения
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