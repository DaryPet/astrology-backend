import re
from typing import Dict, Any, AsyncGenerator
from app.services.llm_adapter import get_llm_adapter


def build_relationship_types_prompt(full_analysis: str, language: str = "ru") -> str:
    """Построить промпт для определения типов отношений на основе готового анализа"""
    
    if language == "ru":
        prompt = f"""Основываясь на полном анализе синастрии ниже, определите процентное соотношение и краткое описание (одно предложение) для каждого типа отношений:

{full_analysis}

Определите проценты и описание для:
1. Вторые половинки
2. Друзья
3. Напарники по бизнесу
4. Духовные соратники

Ответьте СТРОГО в формате:
Вторые половинки: X% - [краткое описание]
Друзья: Y% - [краткое описание]
Напарники по бизнесу: Z% - [краткое описание]
Духовные соратники: W% - [краткое описание]
Доминирующий тип: [тип]

Типы и % должны определяться на сонове полного анализа + книг указанных для полного анализа! В обшей сумме % долдны составлять 100%!
Перед тем как отпределиться % в типах - ответить на такие вопросы: кто такие вторые половинки в эволюционной атсрологии? насколько интесивна карта? какие скопления планет в каких домах (если есть)? сколько прошлых жизней было до? какая у них карма? сколько % встречается с такими картами в среднем?
"""
    else:
        prompt = f"""Based on the full synastry analysis below, determine the percentage and a short description (one sentence) for each relationship type:

{full_analysis}

Determine percentages and descriptions for:
1. Romantic Partners
2. Friends
3. Business Partners
4. Spiritual Comrades

Answer in STRICT format:
Romantic Partners: X% - [short description]
Friends: Y% - [short description]
Business Partners: Z% - [short description]
Spiritual Comrades: W% - [short description]
Dominant type: [type]"""

    return prompt


def parse_relationship_response(response: str) -> Dict[str, Any]:
    """Парсить ответ LLM в структурированный формат"""
    result = {
        "relationship_types": {},
        "dominant_type": "",
        "analysis": response
    }
    
    # Look for percentages in Russian
    patterns_ru = {
        "romantic_partners": r"Вторые половинки:\s*(\d+)%\s*-\s*([^\n]+)",
        "friends": r"Друзья:\s*(\d+)%\s*-\s*([^\n]+)",
        "business_partners": r"Напарники по бизнесу:\s*(\d+)%\s*-\s*([^\n]+)",
        "spiritual_comrades": r"Духовные соратники:\s*(\d+)%\s*-\s*([^\n]+)",
        "dominant_type": r"Доминирующий тип:\s*([^\n]+)"
    }
    
    patterns_en = {
        "romantic_partners": r"Romantic Partners:\s*(\d+)%\s*-\s*([^\n]+)",
        "friends": r"Friends:\s*(\d+)%\s*-\s*([^\n]+)",
        "business_partners": r"Business Partners:\s*(\d+)%\s*-\s*([^\n]+)",
        "spiritual_comrades": r"Spiritual Comrades:\s*(\d+)%\s*-\s*([^\n]+)",
        "dominant_type": r"Dominant type:\s*([^\n]+)"
    }
    
    patterns = patterns_ru if "Вторые половинки" in response else patterns_en
    
    type_mapping = {
        "romantic_partners": "Вторые половинки" if patterns == patterns_ru else "Romantic Partners",
        "friends": "Друзья" if patterns == patterns_ru else "Friends",
        "business_partners": "Напарники по бизнесу" if patterns == patterns_ru else "Business Partners",
        "spiritual_comrades": "Духовные соратники" if patterns == patterns_ru else "Spiritual Comrades"
    }
    
    for key, pattern in patterns.items():
        match = re.search(pattern, response, re.IGNORECASE)
        if match:
            if key == "dominant_type":
                result["dominant_type"] = match.group(1).strip().lower()
            else:
                percentage = int(match.group(1))
                short_description = match.group(2).strip()
                result["relationship_types"][key] = {
                    "percentage": percentage,
                    "label": type_mapping[key],
                    "description": short_description
                }
    
    return result


async def analyze_relationship_types(
    full_analysis: str,
    language: str = "ru"
) -> Dict[str, Any]:
    """Определить типы отношений в синастрии на основе готового анализа"""
    
    adapter = get_llm_adapter()
    prompt = build_relationship_types_prompt(full_analysis, language)
    
    response = await adapter.generate(prompt, language)
    return parse_relationship_response(response)


async def stream_relationship_types(
    full_analysis: str,
    language: str = "ru"
) -> AsyncGenerator[str, None]:
    """Потоково отправлять обновления о типах отношений"""
    
    adapter = get_llm_adapter()
    prompt = build_relationship_types_prompt(full_analysis, language)
    
    # Check whether the adapter supports streaming
    if hasattr(adapter, 'generate_stream'):
        async for chunk in adapter.generate_stream(prompt, language):
            yield chunk
    else:
        # Fallback: regular generate, simulate streaming
        response = await adapter.generate(prompt, language)
        yield response