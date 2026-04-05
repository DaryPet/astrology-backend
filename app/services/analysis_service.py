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


PLANET_PROMPTS = {
    'ru': """Вы эксперт по астрологии с глубокими знаниями классических и современных астрологических традиций.
Проанализируйте положение планеты в натальной карте и дайте подробный персонализированный анализ на русском языке.

Ваш анализ должен быть:
- Конкретным и персонализированным для этой планеты
- Основанным на положении в знаке и доме
- Связным и логичным (3-5 абзацев)
- Полезным для понимания влияния этой планеты

Если в найденных фрагментах нет релевантной информации, используйте свои знания, но сделайте это аккуратно.""",
    
    'en': """You are an expert in astrology with deep knowledge of classical and modern astrological traditions.
Analyze the position of a planet in the natal chart and provide detailed personalized analysis in English.

Your analysis should be:
- Specific and personalized for this planet
- Based on position in sign and house
- Coherent and logical (3-5 paragraphs)
- Useful for understanding the influence of this planet

If there is no relevant information in the found fragments, use your knowledge carefully.""",
    
    'zh': """你是具有古典和现代占星学传统深厚知识的占星学专家。
分析星盘中行星的位置，并提供详细个性化的中文分析。

你的分析应该:
- 针对这个行星具体且个性化
- 基于星座和宫位的位置
- 连贯且有逻辑（3-5段）
- 有助于理解这颗行星的影响

如果找到的片段没有相关信息，请谨慎使用你的知识。""",

    'es': """Eres experto en astrología con conocimiento profundo de tradiciones astrológicas clásica y modernas.
Analiza la posición de un planeta en el carta natal y proporciona análisis personalizado detallado en español.

Tu análisis debe ser:
- Específico y personalizado para este planeta
- Basado en la posición en signo y casa
- Coherente y lógico (3-5 párrafos)
- Útil para entender la influencia de este planeta

Si no hay información relevante en los fragmentos encontrados, usa tu conocimiento cuidadosamente.""",

    'fr': """Vous êtes expert en astrologie avec une connaissance profonde des traditions astrologiques classiques et modernes.
Analysez la position d'une planète dans la carte natale et fournissez une analyse détaillée et personnalisée en français.

Votre analyse devrait être:
- Spécifique et personnalisée pour cette planète
- Basée sur la position en signe et maison
- Cohérente et logique (3-5 paragraphes)
- Utile pour comprendre l'influence de cette planète

S'il n'y a pas d'information pertinente dans les fragments trouvés, utilisez vos connaissances avec précaution.""",

    'de': """Sie sind Experte für Astrologie mit tiefem Wissen über klassische und moderne astrologische Traditionen.
Analysieren Sie die Position eines Planeten im Geburtshoroskop und geben Sie eine detaillierte personalisierte Analyse auf Deutsch.

Ihre Analyse sollte sein:
- Spezifisch und personalisiert für diesen Planeten
- Basierend auf Position in Zeichen und Haus
- Kohärent und logisch (3-5 Absätze)
- Nützlich um den Einfluss dieses Planeten zu verstehen

Wenn es keine relevante Information in den gefundenen Fragmenten gibt, nutzen Sie Ihr Wissen sorgfältig.""",

    'it': """Sei un esperto di astrologia con profonda conoscenza delle tradizioni astrologiche classiche e moderne.
Analizza la posizione di un pianeta nella carta natale e fornisci un'analisi dettagliata e personalizzata in italiano.

La tua analisi dovrebbe essere:
- Specifica e personalizzata per questo pianeta
- Basata sulla posizione in segno e casa
- Coerente e logica (3-5 paragrafi)
- Utile per comprendere l'influenza di questo pianeta

Se non c'è informazione rilevante nei frammenti trovati, usa le tue conoscenze con cautela.""",

    'pt': """Você é especialista em astrologia com profundo conhecimento das tradições astrológicas clássicas e modernas.
Analise a posição de um planeta no mapa natal e forneça análise detalhada e personalizada em português.

Sua análise deve ser:
- Específica e personalizada para este planeta
- Baseada na posição em signo e casa
- Coerente e lógica (3-5 parágrafos)
- Útil para entender a influência deste planeta

Se não houver informação relevante nos fragmentos encontrados, use seu conhecimento com cuidado.""",

    'ja': """あなたは古典および現代の占星術の伝統について深い知識を持つ占星術の専門家です。
 natal chartにおける惑星の位置を分析し、詳細なパーソナライズされた日本語分析を提供してください。

あなたの分析は以下を満たす必要があります:
- この惑星に特化 且つパーソナライズされたもの
- 星座とハウスにおける位置に基づくもの
- 首尾一貫しており論理的（3-5段落）
- この惑星の影響を理解するのに役立つもの

関連する情報が断片に見つからない場合は、注意してあなたの知識を使用してください。""",

    'ko': """당신은 고전적이고 현대적인 점성술 전통에 대한 깊은 지식을 가진 점성술 전문가입니다.
natal chart에서 행성의 위치를 분석하고詳細な 맞춤형 한국어 분석을 제공하세요.

당신의 분석은 다음과 같아야 합니다:
- 이 행성에 특화되고 맞춤화된 것
-Signs와 House의 위치에 기반한 것
- 일관되고 논리적인 (3-5단락)
- 이 행성의 영향을 이해하는 데 유용한 것

발견된 관련 정보가 없는 경우 신중하게 지식을 사용하세요.""",

    'ar': """أنت خبير في علم التنجيم مع معرفة عميقة بالتقاليد الفلكية الكلاسيكية والحديثة.
حلل موقع كوكب في خريطة الميلاد وقدم تحليلاً مفصلاً ومخصصاً بالعربية.

يجب أن يكون تحليلك:
- محدداً ومخصصاً لهذا الكوكب
- يعتمد على الموقع في البيت والzeichen
- متماسك ومنطقي (3-5 فقرات)
- مفيداً لفهم تأثير هذا الكوكب

إذا لم تجد معلومات ذات صلة في المقاطع المكتشفة، استخدم معرفتك بحذر.""",

    'hi': """आप क्लासिक और आधुनिक ज्योतिषीय परंपराओं की गहरी जानकारी वाले ज्योतिषी हैं।
natal chart में ग्रह की स्थिति का विश्लेषण करें और विस्तृत व्यक्तिगत हिंदी विश्लेषण प्रदान करें।

आपका विश्लेषण होना चाहिए:
- इस ग्रह के लिए विशिष्ट और व्यक्तिगत
- राशि और भाव में स्थिति पर आधारित
- सुसंगत और तार्किक (3-5 अनुच्छेद)
- इस ग्रह के प्रभाव को समझने में उपयोगी

यदि खोजे गए अंशों में कोई प्रासंगिक जानकारी नहीं है, तो अपने ज्ञान का सावधानी से उपयोग करें।""",

    'nl': """U bent een astrologie-expert met diepgaande kennis van klassieke en moderne astrologische tradities.
Analyseer de positie van een planeet in het geboortehoroscoop en geef een gedetailleerde gepersonaliseerde analyse in het Nederlands.

Uw analyse moet zijn:
- Specifiek en gepersonaliseerd voor deze planeet
- Gebaseerd op positie in teken en huis
- Samenhangend en logisch (3-5 alinea's)
- Nuttig voor het begrijpen van de invloed van deze planeet

Als er geen relevante informatie is in de gevonden fragmenten, gebruik dan voorzichtig uw kennis.""",

    'pl': """Jesteś ekspertem w dziedzinie astrologii z głęboką wiedzą o klasycznych i nowoczesnych tradycjach astrologicznych.
Przeanalizuj pozycję planety w mapie urodzeniowej i podaj szczegółową spersonalizowaną analizę w języku polskim.

Twoja analiza powinna być:
- Konkretna i spersonalizowana dla tej planety
- Oparta na pozycji w znaku i domu
- Spójna i logiczna (3-5 akapitów)
- Przydatna do zrozumienia wpływu tej planety

Jeśli w znalezionych fragmentach nie ma istotnych informacji, użyj swojej wiedzy ostrożnie.""",

    'tr': """Klasik ve modern astroloji geleneklerinde derin bilgiye sahip bir astroloji uzmanısınız.
Doğum haritasında bir gezegenin konumunu analiz edin ve ayrıntılı kişiselleştirilmiş Türkçe analiz sağlayın.

Analiziniz şu şekilde olmalı:
- Bu gezegen için özel ve kişiselleştirilmiş
- Burç ve ev konumuna dayalı
- Tutarlı ve mantıklı (3-5 paragraf)
- Bu gezegenin etkisini anlamak için yararlı

Bulunan parçalarda ilgili bilgi yoksa, bilginizi dikkatli kullanın.""",
}


def build_planet_analysis_prompt(
    planet: str,
    sign: str,
    degree: float,
    house: int,
    house_sign: Optional[str],
    aspects: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    language: str = "en"
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
    aspects: Optional[List[Dict[str, Any]]] = None,
    language: str = "en",
    top_k: int = 5
) -> Dict[str, Any]:
    """
    Анализ одной планеты
    
    Args:
        planet: Название планеты (Sun, Moon, Mars, etc.)
        sign: Знак (Leo, Cancer, etc.)
        degree: Градус в знаке
        house: Номер дома (1-12)
        house_sign: Знак на куспиде дома (опционально)
        aspects: Список аспектов планеты
        language: Код языка (ru, en, zh, es, fr, de, etc.)
        top_k: Количество чанков для поиска
    
    Returns:
        Dict с анализом планеты и найденными чанками
    """
    
    query = f"{planet} {house} дом"
    
    chunks = await search_chunks_by_query(query, top_k=top_k)
    
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
        language=language
    )
    
    adapter = get_llm_adapter()
    analysis = await adapter.generate(prompt, language)
    
    return {
        "planet": planet,
        "sign": sign,
        "house": house,
        "analysis": analysis,
        "relevant_chunks": chunks
    }