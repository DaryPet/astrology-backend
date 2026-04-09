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


SYNTHESIS_PROMPTS = {
    'ru': """Ты эксперт по эволюционной астрологии (Джефф Грин, кармические узлы, трансформация души). Создай ГЛУБОКИЙ, ПОДРОБНЫЙ, ВСЕОБХЕМЛЮЩИЙ анализ натальной карты - как для лучшего друга, который хочет понять себя по-настоящему.

**КРИТИЧЕСКИЕ ТРЕБОВАНИЯ - ЭТО НЕ ШУТКА:**

1. ТЫ ДОЛЖЕН НАПИСАТЬ МИНИМУМ 10000 СЛОВ всего
2. ДЛЯ КАЖДОЙ ПЛАНЕТЫ ты ДОЛЖЕН написать минимум 300-500 слов (для Плутона и Узлов - минимум 800 слов!)
3. НЕ ОСТАНАВЛИВАЙСЯ пока не раскроешь ВСЕ 13 тем
4. Думай глубоко о каждой планете - что это значит для жизни этого человека?
5. Пиши как объясняешь другу, который ничего не знает об астрологии

**ГЛАВНЫЕ ПРАВИЛА:**

1. ПИШИ ГЛУБОКО - раскрой КАЖДУЮ планету полностью, не поверхностно
2. ПИШИ ПОДРОБНО - минимум 10000 слов в итоге - ЭТО ОБЯЗАТЕЛЬНО!
3. ПИШИ ПОНЯТНО - простыми словами, без астрологического сленга
4. НЕ используй технические термины, градусы, орбы - только: планета, знак, дом
5. Используй ТОЛЬКО РЕАЛЬНЫЕ аспекты из списка. Если аспекта нет - НЕ выдумывай!
6. НЕ называй книги и авторов
7. НЕ пиши сколько слов в анализе
8. КНИГА ПО УЗЛАМ И ПЛУТОНУ - это ключевая книга! Используй её информацию максимально подробно для Плутона, Южного и Северного узлов!

**СТРУКТУРА (пиши одним связным текстом, но эти темы должны быть раскрыты):**

1. **Плутон и Кармические узлы** - начни с этого! Душа, судьба, трансформация, что пришло из прошлого
2. **Сатурн** - уроки жизни, страхи, ответственность, что мешает
3. **Хирон и Лилит** - главные раны, скрытые желания, темная сторона
4. **Солнце** - кто ты по жизни, твоя суть, как тебя видят
5. **Луна** - чего тебе нужно для счастья, эмоции, внутренний ребенок
6. **Асцендент** - как ты себя показываешь миру, первое впечатление
7. **Меркурий** - как ты думаешь и общаешься
8. **Венера** - любовь, красота, деньги, что ты ценишь
9. **Марс** - как ты добиваешься целей, сексуальность, гнев
10. **Юпитер** - удача, вера, расширение, философия
11. **Уран и Нептун** - неожиданности, духовность, мечты
12. **Все дома** - для каждого дома укажи: какая сфера жизни акцентирована (1-дом: личность, 2-деньги, 3-общение, 4-дом/семья, 5-творчество, 6-работа, 7-партнёрство, 8-трансформация, 9-путешествия, 10-карьера, 11-мечты, 12-тайное). Если в доме есть планеты - напиши про них, если пустой - просто кратко о сфере. НЕ повторяй то что уже написал про планеты!
13. **Что делать** - практические шаги для роста

**ДЛЯ КАЖДОЙ ПЛАНЕТЫ:**
- Напиши подробно (минимум 300-500 слов на планету, для Плутона и Узлов - минимум 800 слов!)
- Укажи знак и дом
- Укажи ретроградность сразу в тексте если есть
- Объясни ПРОСТО - как это влияет на жизнь

**АСПЕКТЫ - используй ТОЛЬКО эти:**
{aspects_list}
Если аспекта нет в списке - НЕ выдумывай его!

**КНИГИ (используй их для анализа):**
{books_content}

Пиши на русском. Глубоко, подробно, понятно.""",

    'en': """You are an expert in EVOLUTIONARY ASTROLOGY (Jeff Green, karmic nodes, soul transformation). Create a DEEP, DETAILED, COMPREHENSIVE natal chart analysis - like for a best friend who really wants to understand themselves.

**CRITICAL REQUIREMENTS - THIS IS NOT A JOKE:**

1. YOU MUST WRITE AT LEAST 10000 WORDS total
2. FOR EACH PLANET you MUST write minimum 300-500 words (for Pluto and Nodes - minimum 800 words!)
3. DO NOT STOP until you have covered ALL 13 topics
4. Think deeply about each planet - what does it mean for this person's life?
5. Write like you're explaining to a friend who knows nothing about astrology

**MAIN RULES:**

1. WRITE DEEP - reveal EACH planet fully, not superficially
2. WRITE DETAILED - minimum 10000 words in total - THIS IS MANDATORY!
3. WRITE SIMPLY - in plain language, no astrological slang
4. NO technical terms, degrees, orbs - only: planet, sign, house
5. Use ONLY REAL aspects from the list. If an aspect is NOT in the list - DON'T make it up!
6. DON'T mention book names or authors
7. DON'T write word count
8. THE BOOK ABOUT NODES AND PLUTO - this is a KEY book! Use its information very detailed for Pluto, South Node and North Node!

**STRUCTURE (write as one coherent text, but these topics must be covered):**

1. **Pluto and Karmic Nodes** - start here! Soul, destiny, transformation, what came from the past
2. **Saturn** - life lessons, fears, responsibility, what holds you back
3. **Chiron and Lilith** - main wounds, hidden desires, dark side
4. **Sun** - who you are in life, your essence, how people see you
5. **Moon** - what you need for happiness, emotions, inner child
6. **Ascendant** - how you show yourself to the world, first impression
7. **Mercury** - how you think and communicate
8. **Venus** - love, beauty, money, what you value
9. **Mars** - how you achieve goals, sexuality, anger
10. **Jupiter** - luck, faith, expansion, philosophy
11. **Uranus and Neptune** - surprises, spirituality, dreams
12. **All houses** - for each house specify: which life area is emphasized (1st-house: personality, 2nd-money, 3rd-communication, 4th-home/family, 5th-creativity, 6th-work, 7th-partnership, 8th-transformation, 9th-travel, 10th-career, 11th-dreams, 12th-hidden). If a house has planets - write about them, if empty - just briefly about the area. DO NOT repeat what you already wrote about planets!
13. **What to do** - practical steps for growth

**FOR EACH PLANET:**
- Write in detail (minimum 300-500 words per planet, for Pluto and Nodes - minimum 800 words!)
- Specify sign and house
- Include retrograde right in the text if present
- Explain SIMPLY - how it affects life

**ASPECTS - use ONLY these:**
{aspects_list}
If an aspect is NOT in the list - DON'T make it up!

**BOOKS (use them for analysis):**
{books_content}

Write in English. Deep, detailed, simple.""",
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
    top_books: int = 5
) -> Dict[str, Any]:
    """
    Полный анализ натальной карты - ОДИН промпт, ОДИН вызов LLM
    """
    from app.services.llm_adapter import get_llm_adapter
    
    adapter = get_llm_adapter()
    
    books = await get_top_books(top_books)
    
    if not books:
        return {
            "analysis": "Книги не найдены в базе данных.",
            "book_analyses": [],
            "chart_summary": {}
        }
    
    # Формируем список аспектов (без градусов и орбов)
    aspects = chart_data.get('aspects', [])
    aspects_list = []
    for asp in aspects:
        p1 = asp.get('planet1', '?')
        p2 = asp.get('planet2', '?')
        asp_ru = asp.get('aspect_ru', '?')
        aspects_list.append(f"{p1} {asp_ru} {p2}")
    aspects_str = "\n".join(aspects_list) if aspects_list else "Нет аспектов"
    
    # Формируем содержание книг (книга об узлах - первая!)
    books_content = ""
    
    # Сначала книга с узлами (id 22), потом остальные
    nodes_book = None
    other_books = []
    for book in books:
        if book.get('id') == 22:
            nodes_book = book
        else:
            other_books.append(book)
    
    # Добавляем сначала книгу об узлах
    if nodes_book:
        content = nodes_book.get('content', '')[:12000]
        books_content += f"\n\n--- КНИГА ОБ УЗЛАХ И ПЛУТОНЕ ---\n{content}"
    
    # Потом остальные книги
    for i, book in enumerate(other_books, 1):
        content = book.get('content', '')[:10000]
        books_content += f"\n\n--- Другие книги ---\n{content}"
    
    # Используем синтез-промпт с placeholder'ами
    prompt = SYNTHESIS_PROMPTS.get(language, SYNTHESIS_PROMPTS['ru'])
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)
    
    # Добавляем данные карты (просто: планета, знак, дом - без градусов)
    prompt += "\n\n=== НАТАЛЬНАЯ КАРТА ==="
    prompt += f"\nСолнце: {chart_data.get('sun_sign_ru', '?')} в {chart_data.get('sun_sign', '?')}"
    prompt += f"\nЛуна: {chart_data.get('moon_sign_ru', '?')} в {chart_data.get('moon_sign', '?')}"
    prompt += f"\nАсцендент: {chart_data.get('ascendant_ru', '?')} в {chart_data.get('ascendant', '?')}"
    
    planets = chart_data.get('planets', {})
    prompt += "\n=== ПЛАНЕТЫ ==="
    for planet_name, planet_data in sorted(planets.items()):
        sign = planet_data.get('sign', '?')
        sign_ru = planet_data.get('sign_ru', sign)
        house = planet_data.get('house', '?')
        is_retro = planet_data.get('is_retrograde', False)
        rx_str = " (ретроградная)" if is_retro else ""
        prompt += f"\n{planet_name}: в {sign_ru}, дом {house}{rx_str}"
    
    houses = chart_data.get('houses', {})
    prompt += "\n=== ДОМА ==="
    for house_num in range(1, 13):
        if str(house_num) in houses:
            h = houses[str(house_num)]
            prompt += f"\nДом {house_num}: {h.get('sign_ru', '?')}"
    
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