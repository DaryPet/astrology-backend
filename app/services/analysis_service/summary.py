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
