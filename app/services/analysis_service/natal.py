from typing import List, Dict, Any, AsyncGenerator
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template
from app.services.prompt_templates.languages import normalize_language
from app.services.text_verification import (
    find_fabricated_positions_layered,
    fix_fabricated_positions_layered,
    find_fabricated_aspect_types_single,
    find_fabricated_houses_single,
    find_undercovered_aspects_generic,
)


from app.services.analysis_service._shared import (
    HOUSE_WORDS,
    NATAL_BOOK_IDS,
    _fetch_book_titles,
    _localized,
    _planet_display,
    search_chunks_by_book_ids,
    stream_verified_analysis,
)


async def _prepare_natal_analysis(
    chart_data: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    Shared prep for full_chart_analysis_v2 and its streaming twin
    (full_chart_analysis_v2_stream): everything from "no prompt yet" to "prompt/
    layers/aspects ready for one LLM call". Split out by
    plans/streaming-analysis-backend.md (step 2a) purely to let the streaming
    path reuse this without duplicating it — behavior is unchanged, this is the
    same code full_chart_analysis_v2 used to run inline.

    [v2] Full natal chart analysis — HYBRID approach:
    - For each planet/aspect, do a targeted RAG search across ALL books
    - Assemble a structured prompt

    Advantages vs full_chart_analysis (v1):
    - All books participate in the analysis (not just the top 5)
    - No context-overflow problem (418K tokens)
    - Each planet/aspect gets relevant fragments
    """
    import asyncio
    import time as _time
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    # Per-phase timing. Added because the log only ever showed "Sending final
    # prompt": everything happening BEFORE the LLM call was unmeasurable, so the
    # gap between the 71s prompt-to-response and the ~5 minutes users observe
    # had nothing to be attributed to.
    _t_start = _time.perf_counter()

    adapter = get_llm_adapter()
    labels = get_labels(language)

    planets = chart_data.get("planets", {})
    aspects = chart_data.get("aspects", [])
    houses = chart_data.get("houses", {})
    houses_meta = chart_data.get("houses_meta", {})

    # Limits the number of concurrent requests to Supabase — same reason as
    # synastry/progressions/transits (synastry_service.py:599). With the switch
    # to NATAL_BOOK_IDS (3 books instead of the whole library, user decision
    # 2026-08-02) each search_chunks_by_book_ids call makes 3 calls to the
    # thread pool (one search_chunks_hybrid per book; book titles come via
    # book_titles, with no separate request per call — see _fetch_book_titles).
    # 8 tasks × 3 = 24 concurrent thread-pool calls, within the same budget
    # as before (was 12 × 2 = 24 with search_chunks_all_books).
    search_semaphore = asyncio.Semaphore(8)

    # Book titles — one request for the whole analysis, not per RAG sub-request.
    book_titles = await _fetch_book_titles(NATAL_BOOK_IDS)
    _t_titles = _time.perf_counter()

    # --- Step 1: Parallel RAG search for each planet ---
    async def search_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        # Handle Pars Fortuna
        search_name = "pars fortuna" if planet_name.lower() in ["ft", "pars fortuna", "part of fortune", "fortuna", "парс фортуны"] else planet_name.lower()
        query = f"{search_name} {house_word} house {sign.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, NATAL_BOOK_IDS, book_titles, top_k_per_book=top_k_per_book)
        return planet_name, chunks

    # --- Step 2: Parallel RAG search for each aspect ---
    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("planet1", "")
        p2 = asp.get("planet2", "")
        asp_type = asp.get("aspect", asp.get("aspect_ru", ""))
        query = f"{p1.lower()} {asp_type.lower()} {p2.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, NATAL_BOOK_IDS, book_titles, top_k_per_book=5)
        return f"{p1} {asp_type} {p2}", chunks

    print(f"[full_chart_analysis_v2] Starting parallel RAG for {len(planets)} planets and {len(aspects)} aspects")

    planet_tasks = [search_planet(name, data) for name, data in planets.items()]
    aspect_tasks = [search_aspect(asp) for asp in aspects]  # ALL aspects, no cutoff

    # Add Pars Fortuna search task
    pf = houses_meta.get('pars_fortuna', {})
    if pf:
        async def search_pars_fortuna():
            query = "pars fortuna (парс фортуны) дом"
            async with search_semaphore:
                chunks = await search_chunks_by_book_ids(query, NATAL_BOOK_IDS, book_titles, top_k_per_book=top_k_per_book)
            return "Pars Fortuna", chunks
        planet_tasks.append(search_pars_fortuna())

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)
    _t_rag = _time.perf_counter()

    # --- Step 3: Assemble the structured prompt ---
    prompt_parts = []

    # System prompt (use the existing synthesis template)
    synthesis_template = get_template("synthesis", language, mode)

    # Aspects for the template — planet names and aspect name are translated
    # per language (used to take p1/p2 as the raw English key, with asp_ru
    # unconditionally Russian text even for uk/en; because of this, the prompt
    # instruction "bold formula exactly as given in the list" dragged
    # untranslated names into the headings, even though in free text the model
    # corrected itself — see analysis_service.py INSIGHTS.md).
    aspects_list = []
    for asp in aspects:
        p1 = _planet_display(asp.get("planet1", "?"), language)
        p2 = _planet_display(asp.get("planet2", "?"), language)
        asp_name = _localized(asp, "aspect", language, asp.get("aspect", "?"))
        aspects_list.append(f"{p1} {asp_name} {p2}")
    _no_aspects = {'ru': "Нет аспектов", 'uk': "Немає аспектів", 'en': "No aspects"}
    aspects_str = "\n".join(aspects_list) if aspects_list else _no_aspects.get(normalize_language(language), _no_aspects['en'])

    # Assemble book content as structured excerpts (not whole books)
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

    # Substitute into the template
    prompt = synthesis_template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # Natal chart data
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

    # The "layer" for post-generation text checking — for natal there's only
    # one (unlike progressions/transits, which have two): find_fabricated_positions_layered/
    # fix_fabricated_positions_layered work fine with a single layer — "fabricated"
    # (the sign doesn't exist in the chart at all) doesn't need an attribution
    # marker, only "layer_confused" does, and with one layer it's always empty (see plan:
    # app/services/specs/natal_synastry_pattern_plan.md).
    natal_chart_like = {
        'planets': planets,
        'ascendant': chart_data.get('ascendant'),
        'ascendant_ru': chart_data.get('ascendant_ru'),
        'ascendant_uk': chart_data.get('ascendant_uk'),
    }
    layers = {'natal': natal_chart_like}

    _t_prompt = _time.perf_counter()

    return {
        'adapter': adapter,
        'prompt': prompt,
        'layers': layers,
        'aspects': aspects,
        'natal_chart_like': natal_chart_like,
        'timings': {
            't_start': _t_start,
            't_titles': _t_titles,
            't_rag': _t_rag,
            't_prompt': _t_prompt,
        },
    }

async def full_chart_analysis_v2(
    chart_data: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    [v2] Full natal chart analysis — HYBRID approach: RAG search per planet/
    aspect + prompt assembly via _prepare_natal_analysis, one final LLM call,
    then the fix/detect anti-fabrication pass. Behavior unchanged by the
    step-2a refactor (plans/streaming-analysis-backend.md) — this is the same
    code that used to run inline in this function.
    """
    import time as _time

    prep = await _prepare_natal_analysis(chart_data, language, top_k_per_book, mode)
    adapter = prep['adapter']
    prompt = prep['prompt']
    layers = prep['layers']
    aspects = prep['aspects']
    natal_chart_like = prep['natal_chart_like']
    _t_start = prep['timings']['t_start']
    _t_titles = prep['timings']['t_titles']
    _t_rag = prep['timings']['t_rag']
    _t_prompt = prep['timings']['t_prompt']

    # --- Step 4: One final LLM call ---
    print(f"[full_chart_analysis_v2] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    try:
        full_analysis = await adapter.generate(prompt, language)
        _t_llm = _time.perf_counter()

        if language in ('ru', 'en', 'uk'):
            # Positions: only fixes what doesn't exist in the chart at all.
            # Detection runs first so the log can distinguish "nothing was
            # wrong" from "something was wrong and got repaired silently".
            found = find_fabricated_positions_layered(full_analysis, layers, language=language)
            fabricated = found.get('fabricated', [])
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if fabricated or unresolved:
                print(
                    f"[full_chart_analysis_v2] Position check: found {len(fabricated)}, "
                    f"fixed {len(fabricated) - len(unresolved)}, unresolved {len(unresolved)}"
                    + (f": {unresolved}" if unresolved else "")
                )
            else:
                print("[full_chart_analysis_v2] Position check: OK, no fabricated positions found")

            # Detection only — the claimed aspect type is checked against the
            # actually calculated one (chart_data['aspects']). No layer/partner
            # attribution — there's one chart, two planets in a bold heading
            # are unambiguous on their own.
            fabricated_aspects = find_fabricated_aspect_types_single(full_analysis, aspects, language=language)
            if fabricated_aspects:
                print(f"[full_chart_analysis_v2] Fabricated aspect types detected (not fixed): {fabricated_aspects}")
            else:
                print("[full_chart_analysis_v2] Aspect-type check: OK, no fabricated aspect types")

            # Detection only, from prose — the text is left alone, nothing added.
            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[full_chart_analysis_v2] Undercovered aspects detected (not filled): {undercovered}")
            else:
                print(f"[full_chart_analysis_v2] Coverage check: OK, all {len(aspects)} aspects covered")

            # Detection only — the planet's house named in the text is checked
            # against the real house from the chart (within the sentence where
            # the planet appears). Not fixed — risk of drifting out of sync
            # with the text's agreement (see find_fabricated_houses_single's docstring).
            fabricated_houses = find_fabricated_houses_single(full_analysis, natal_chart_like, language=language)
            if fabricated_houses:
                print(f"[full_chart_analysis_v2] Fabricated house claims detected (not fixed): {fabricated_houses}")
            else:
                print("[full_chart_analysis_v2] House check: OK, no fabricated house claims")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[full_chart_analysis_v2] LLM error: {e}")

    # _t_llm is unset if generate() raised, so fall back to the prompt mark:
    # that attributes the elapsed time to the LLM phase rather than to verify.
    _t_llm = locals().get('_t_llm', _t_prompt)
    _t_end = _time.perf_counter()
    print(
        "[timing] full_chart_analysis_v2"
        f" titles={_t_titles - _t_start:.1f}s"
        f" rag={_t_rag - _t_titles:.1f}s"
        f" build={_t_prompt - _t_rag:.1f}s"
        f" llm={_t_llm - _t_prompt:.1f}s"
        f" verify={_t_end - _t_llm:.1f}s"
        f" total={_t_end - _t_start:.1f}s"
    )

    return {
        "analysis": full_analysis,
        "language": language,
        "version": "v2_hybrid_rag"
    }

async def full_chart_analysis_v2_stream(
    chart_data: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of full_chart_analysis_v2
    (plans/streaming-analysis-backend.md, step 2г). Same prep
    (_prepare_natal_analysis), same finalize pipeline (fix + the three
    detect-only checks) — only the delivery differs: verified paragraphs
    stream out via stream_verified_analysis instead of waiting for the whole
    text. The `final` event always carries the same canonical JSON
    full_chart_analysis_v2 would have returned.
    """
    import time as _time

    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_natal_analysis(chart_data, language, top_k_per_book, mode)
    adapter = prep['adapter']
    prompt = prep['prompt']
    layers = prep['layers']
    aspects = prep['aspects']
    natal_chart_like = prep['natal_chart_like']
    timings = prep['timings']

    _t_llm_end = None
    _t_verify_end = None

    async def finalize(buffer: str, released: str) -> Dict[str, Any]:
        nonlocal _t_llm_end, _t_verify_end
        _t_llm_end = _time.perf_counter()

        full_analysis = buffer
        if language in ('ru', 'en', 'uk'):
            # Detection runs before the fix so the log can distinguish "nothing
            # was wrong" from "something was wrong and got repaired silently" —
            # fix_* only reports what it could NOT repair.
            found = find_fabricated_positions_layered(full_analysis, layers, language=language)
            fabricated = found.get('fabricated', [])
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if fabricated or unresolved:
                print(
                    f"[full_chart_analysis_v2_stream] Position check: found {len(fabricated)}, "
                    f"fixed {len(fabricated) - len(unresolved)}, unresolved {len(unresolved)}"
                    + (f": {unresolved}" if unresolved else "")
                )
            else:
                print("[full_chart_analysis_v2_stream] Position check: OK, no fabricated positions found")

            fabricated_aspects = find_fabricated_aspect_types_single(full_analysis, aspects, language=language)
            if fabricated_aspects:
                print(f"[full_chart_analysis_v2_stream] Fabricated aspect types detected (not fixed): {fabricated_aspects}")
            else:
                print("[full_chart_analysis_v2_stream] Aspect-type check: OK, no fabricated aspect types")

            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[full_chart_analysis_v2_stream] Undercovered aspects detected (not filled): {undercovered}")
            else:
                print(f"[full_chart_analysis_v2_stream] Coverage check: OK, all {len(aspects)} aspects covered")

            fabricated_houses = find_fabricated_houses_single(full_analysis, natal_chart_like, language=language)
            if fabricated_houses:
                print(f"[full_chart_analysis_v2_stream] Fabricated house claims detected (not fixed): {fabricated_houses}")
            else:
                print("[full_chart_analysis_v2_stream] House check: OK, no fabricated house claims")

        if not full_analysis.startswith(released):
            # NOT a plain equality check on purpose: `released` legitimately
            # stops short of `full_analysis` by the last, `\n\n`-unterminated
            # paragraph on EVERY normal run (stream_verified_analysis only
            # releases up to the last paragraph boundary it has seen — the
            # final paragraph never gets one). Comparing with `!=` fired on
            # every request and buried the one case this log actually exists
            # to catch: the fix pass changing something inside the prefix
            # already shown to the user (a real planet/sign/house/aspect
            # mismatch between what was streamed and the canonical pass) —
            # 2026-08-10, see app/services/INSIGHTS.md.
            print(
                "[stream_mismatch] full_chart_analysis_v2_stream"
                f" released={released!r} canonical={full_analysis!r}"
            )

        _t_verify_end = _time.perf_counter()
        return {
            "analysis": full_analysis,
            "language": language,
            "version": "v2_hybrid_rag"
        }

    fix_fn = lambda text: fix_fabricated_positions_layered(text, layers, language=language)

    print(f"[full_chart_analysis_v2_stream] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")
    yield {"event": "stage", "data": {"stage": "generating"}}

    _first_delta_at = None
    error_occurred = False
    async for event in stream_verified_analysis(adapter, prompt, language, fix_fn, finalize):
        if event["event"] == "delta" and _first_delta_at is None:
            _first_delta_at = _time.perf_counter()
        elif event["event"] == "error":
            error_occurred = True
        yield event

    _t_end = _time.perf_counter()
    if error_occurred:
        print(
            "[timing] full_chart_analysis_v2_stream"
            f" titles={timings['t_titles'] - timings['t_start']:.1f}s"
            f" rag={timings['t_rag'] - timings['t_titles']:.1f}s"
            f" build={timings['t_prompt'] - timings['t_rag']:.1f}s"
            f" error total={_t_end - timings['t_start']:.1f}s"
        )
        return

    first_delta = (
        f"{_first_delta_at - timings['t_prompt']:.1f}s" if _first_delta_at is not None else "n/a"
    )
    _t_llm = _t_llm_end if _t_llm_end is not None else timings['t_prompt']
    _t_verify = _t_verify_end if _t_verify_end is not None else _t_llm
    print(
        "[timing] full_chart_analysis_v2_stream"
        f" titles={timings['t_titles'] - timings['t_start']:.1f}s"
        f" rag={timings['t_rag'] - timings['t_titles']:.1f}s"
        f" build={timings['t_prompt'] - timings['t_rag']:.1f}s"
        f" llm={_t_llm - timings['t_prompt']:.1f}s"
        f" verify={_t_verify - _t_llm:.1f}s"
        f" first_delta={first_delta}"
        f" total={_t_end - timings['t_start']:.1f}s"
    )



# ============================================================
# OLD CODE (v1) — kept for rollback, do not delete
# ============================================================

async def get_top_books(top_k: int = 5) -> List[Dict[str, Any]]:
    """Get the top K books from the DB via Supabase (by creation date)"""
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
    top_books: int = 1  # FIXED: reduced from 5 to 1 (5 full books won't fit in the LLM's context)
) -> Dict[str, Any]:
    """
    Full natal chart analysis - ONE prompt, ONE LLM call
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
    
    # NOTE: reads the ENTIRE text of the books (no truncation).
    # Make sure top_books=1 and the book size doesn't exceed ~300k characters,
    # otherwise the LLM will return a context-overflow error.
    # For analyzing multiple books, use the RAG endpoints (/analysis/planet, /analysis/query).
    
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
         # Limit the content size so as not to exceed the LLM's token limit
         content = nodes_book.get('content', '')[:400000]
         books_content += f"\n\n--- КНИГА ОБ УЗЛАХ И ПЛУТОНЕ ---\n{content}"

    for i, book in enumerate(other_books, 1):
        # FIXED: removed the [:10000] truncation, read the whole book
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
    


# END OF full_chart_analysis ↑
