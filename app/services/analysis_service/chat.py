from typing import List, Dict, Any, AsyncGenerator
from app.services.search_service import (
    search_chunks_by_query,
)


from app.services.analysis_service._shared import (
    search_chunks_all_books,
    stream_chat_reply,
)


async def _prepare_chat_with_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru"
) -> Dict[str, Any]:
    """
    Shared prep for chat_with_astrologer and its streaming twin
    (chat_with_astrologer_stream): hybrid RAG search + messages build, same
    split as _prepare_natal_analysis — behavior unchanged, this is the same
    code chat_with_astrologer used to run inline.
    """
    import asyncio
    from app.services.llm_adapter import get_llm_adapter

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

    return {
        "adapter": adapter,
        "messages": messages,
        "question_chunks": question_chunks if not isinstance(question_chunks, Exception) else []
    }

async def chat_with_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru"
) -> Dict[str, Any]:
    """
    Chat with the astrologer agent — HYBRID approach
    """
    prep = await _prepare_chat_with_astrologer(question, chart_data, full_analysis, chat_history, language)
    answer = await prep["adapter"].generate_with_messages(prep["messages"], language)

    return {
        "answer": answer,
        "relevant_chunks": prep["question_chunks"]
    }

async def chat_with_astrologer_stream(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru"
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of chat_with_astrologer — typewriter delivery for the
    chat modal. No anti-fabrication fix runs on chat replies today (see
    chat_with_astrologer), so this goes through stream_chat_reply (raw token
    relay), not stream_verified_analysis (paragraph-buffered + fix_fn).
    """
    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_chat_with_astrologer(question, chart_data, full_analysis, chat_history, language)

    async def finalize(buffer: str) -> Dict[str, Any]:
        return {
            "answer": buffer,
            "relevant_chunks": prep["question_chunks"]
        }

    yield {"event": "stage", "data": {"stage": "generating"}}
    async for event in stream_chat_reply(prep["adapter"], prep["messages"], language, finalize):
        yield event
