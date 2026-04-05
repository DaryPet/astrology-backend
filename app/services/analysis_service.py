from typing import List, Dict, Any, Optional
from app.services.search_service import (
    search_chunks_by_query,
    search_chunks_simple,
    parse_astrology_query,
    build_search_context,
)
from app.services.llm_adapter import generate_analysis, get_llm_adapter


ANALYSIS_PROMPTS = {
    'ru': """Вы эксперт по астрологии с глубокими знаниями классических и современных астрологических традиций. 
Проанализируйте найденные фрагменты из астрологических книг в контексте натальной карты и запроса пользователя.
Дайте подробный, персонализированный анализ на русском языке.

Используйте:
- Натальную карту для определения положения планет в домах
- Найденные фрагменты из книг как справочный материал
- Запрос пользователя как основу для анализа

Ваш анализ должен быть:
- Конкретным и персонализированным
- Основанным на фактах из натальной карты
- Связным и логичным
- Полезным для пользователя

Если в найденных фрагментах нет релевантной информации, используйте свои знания, но сделайте это аккуратно.""",
    
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

If there is no relevant information in the found fragments, use your knowledge carefully.""",
    
    'es': """Eres experto en astrología con conocimiento profundo de tradiciones astrológicas clásica y modernas.
Analiza los fragmentos encontrados de libros de astrología en el contexto de la carta natal y la consulta del usuario.
Proporciona un análisis detallado y personalizado en español.""",
    
    'de': """Sie sind Experte für Astrologie mit tiefem Wissen über klassische und moderne astrologische Traditionen.
Analysieren Sie die gefundenen Fragmente aus Astrologiebüchern im Kontext des Geburtshoroskops und der Anfrage des Benutzers.
Geben Sie eine detaillierte, personalisierte Analyse auf Deutsch.""",
    
    'fr': """Vous êtes expert en astrologie avec une connaissance profonde des traditions astrologiques classiques et modernes.
Analysez les fragments trouvés dans les livres d'astrologie dans le contexte de la carte natale et laquery de l'utilisateur.
Fournissez une analyse détaillée et personnalisée en français.""",
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