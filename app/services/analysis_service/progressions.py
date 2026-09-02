from typing import Dict, Any, AsyncGenerator, List
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template
from app.services.text_verification import (
    PLANET_RU,
    PLANET_EN,
    find_fabricated_positions_layered,
    fix_fabricated_positions_layered,
    find_fabricated_aspect_types_layered,
    find_undercovered_aspects_generic,
    find_return_mislabeling,
)


from app.services.analysis_service._shared import (
    HOUSE_WORDS,
    TRANSITS_PROGRESSIONS_BOOK_IDS,
    _fetch_book_titles,
    _lang_key,
    _localized,
    _localized2,
    _matches_technique,
    _planet_display,
    search_chunks_by_book_ids,
    stream_chat_reply,
    stream_verified_analysis,
)




# ============================================================
# SECONDARY PROGRESSIONS ANALYSIS
# ============================================================

async def _prepare_progressions_analysis(
    natal_chart: Dict[str, Any],
    progressions: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    Shared prep for progressions_analysis and its streaming twin
    (progressions_analysis_stream): everything from "no prompt yet" to
    "prompt/aspects/layers ready for one LLM call". Split out by
    plans/streaming-rollout-synastry-progressions-transits.md (step 2а) — same
    principle as _prepare_natal_analysis — behavior unchanged, this is the
    same code progressions_analysis used to run inline.

    AI analysis of secondary progressions — the same hybrid approach as full_chart_analysis_v2:
    - targeted RAG search across the same books (progressed personal planets + aspects to natal)
    - assembling a structured prompt (the 'progressions' template, advanced/simple)
    """
    import asyncio
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    adapter = get_llm_adapter()
    labels = get_labels(language)

    prog_planets = progressions.get("progressed_planets", {})
    aspects = progressions.get("aspects_to_natal", [])
    # Drop same-planet self-conjunctions (progressed X ↔ natal X) for the
    # slowest outer planets at the DATA layer, not via a prompt instruction —
    # a hard, explicit, per-planet prompt-only ban on "return"/"повернення"
    # wording was tried twice (2026-08-30) and the model violated it both
    # times anyway (first Pluto, then Neptune). Structurally, this aspect can
    # ONLY appear at all when the planet hasn't moved far enough to change
    # sign (a sign change is 30°+, far outside any conjunction orb) — so
    # removing it here removes exactly the "nothing new happened" case that
    # kept inviting the "planetary return" hallucination, more reliably than
    # any wording could. User decision: only these 3, not Saturn (which does
    # change sign within a lifetime, so its self-conjunction isn't the same
    # "stuck" case).
    _NO_SELF_CONJUNCTION_PLANETS = {'Pluto', 'Neptune', 'Uranus'}
    aspects = [
        a for a in aspects
        if not (
            a.get('planet1') == a.get('planet2')
            and a.get('planet1') in _NO_SELF_CONJUNCTION_PLANETS
            and a.get('aspect') == 'Conjunction'
        )
    ]
    natal_summary = progressions.get("natal_summary", {})
    natal_planets = (natal_chart or {}).get("planets", {})

    # In progressions the personal planets carry interpretive weight (outer planets barely move)
    PERSONAL_PLANETS = ["Sun", "Moon", "Mercury", "Venus", "Mars"]

    # Limits the number of concurrent requests to Supabase — same reason as
    # synastry (full_synastry_analysis_v2, synastry_service.py:599).
    # With the switch to TRANSITS_PROGRESSIONS_BOOK_IDS (fixed 2 books instead
    # of "priority + the entire rest of the catalog", user decision
    # 2026-08-02) each search_chunks_by_book_ids call makes 2 calls to the
    # thread pool (not 3, like search_chunks_priority_book used to make —
    # priority + others + a separate book-titles request per call).
    # 12 tasks × 2 = 24 — even safer than before (was 12 × 3 = 36, a
    # documented unresolved bug, specs/semaphore_thread_pool_sizing_bug.md;
    # this switch closes it as a side effect).
    search_semaphore = asyncio.Semaphore(12)

    # Book titles — one request for the whole analysis, not per RAG sub-request.
    book_titles = await _fetch_book_titles(TRANSITS_PROGRESSIONS_BOOK_IDS)

    # --- Step 1: Parallel RAG search ---
    # Progressions/transits books — a fixed list (28, 29), not one priority
    # book + the whole catalog.
    async def search_progressed_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("natal_house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        query = f"progressed {planet_name.lower()} {sign.lower()} {house_word} house"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return planet_name, chunks

    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("progressed", asp.get("planet1", ""))
        p2 = asp.get("natal", asp.get("planet2", ""))
        asp_type = asp.get("aspect", "")
        query = f"progressed {p1.lower()} {asp_type.lower()} natal {p2.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return f"{p1} {asp_type} {p2}", chunks

    async def search_general() -> tuple:
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(
                "secondary progressions progressed chart day for a year",
                TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5
            )
        return "Secondary Progressions", chunks

    async def search_lunar_phase() -> tuple:
        phase = (progressions.get("lunar_phase") or {}).get("phase", "")
        if not phase:
            return "Lunar Phase", []
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(
                f"progressed lunar phase {phase.lower()} moon cycle",
                TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5
            )
        return f"Progressed Lunar Phase: {phase}", chunks

    planet_tasks = [
        search_progressed_planet(name, prog_planets[name])
        for name in PERSONAL_PLANETS if name in prog_planets
    ]
    # Planets that changed sign relative to the natal — turning points, search for them too
    for name, data in prog_planets.items():
        if data.get("changed_sign") and name not in PERSONAL_PLANETS:
            planet_tasks.append(search_progressed_planet(name, data))
    planet_tasks.append(search_general())
    planet_tasks.append(search_lunar_phase())

    # Used to have an aspects[:10] cutoff, while the prompt still demanded "cover ALL"
    # aspects from aspects_list (which is built from the FULL list below) — aspects
    # past the 10th had no chunks at all. There are few aspects in progressions
    # (1.5° orb), so removing the cutoff doesn't blow up the prompt the way it
    # could for synastry with its 44-64 aspects.
    aspect_tasks = [search_aspect(asp) for asp in aspects]

    print(f"[progressions_analysis] Parallel RAG: {len(planet_tasks)} planet queries, {len(aspect_tasks)} aspect queries")

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)

    # --- Step 2: Assemble the structured prompt ---
    template = get_template("progressions", language, mode)

    # List of progressions-to-natal aspects — with full context for the overlay:
    # progressed planet's position, natal position and HOUSE, orb, applying/separating
    aspects_list = []
    for asp in aspects:
        p1 = asp.get("progressed", asp.get("planet1", "?"))
        p2 = asp.get("natal", asp.get("planet2", "?"))
        orb_val = asp.get("orb", "?")
        n_house = asp.get("natal_house", "?")
        p_house = asp.get("progressed_house", "?")
        # Explicit layer prefix (ПРОГРЕССИВНЫЙ:/НАТАЛЬНЫЙ:, uppercase, without
        # gender-declining the planet — the same trick as ПАРТНЕР1:/ПАРТНЕР2:
        # in synastry_service.py) + the translated planet name: this used to
        # be an undeclared internal key ("Прогрессивный Moon"), not the
        # display name. Distinguishes the progressed and natal position of
        # the SAME planet — plan:
        # app/services/specs/progressions_synastry_pattern_plan.md.
        if language == 'ru':
            p1_display = PLANET_RU.get(p1, p1)
            p2_display = PLANET_RU.get(p2, p2)
            asp_name = asp.get("aspect_ru", asp.get("aspect", "?"))
            applying_str = "сходящийся" if asp.get("applying") else "расходящийся"
            aspects_list.append(
                f"ПРОГРЕССИВНЫЙ:{p1_display} (в {asp.get('progressed_sign', '?')}, натальный дом {p_house}) "
                f"{asp_name} НАТАЛЬНЫЙ:{p2_display} (в {asp.get('natal_sign', '?')}, дом {n_house}) "
                f"— орб {orb_val}°, {applying_str}"
            )
        elif language == 'uk':
            p1_display = _planet_display(p1, 'uk')
            p2_display = _planet_display(p2, 'uk')
            asp_name = asp.get("aspect_uk", asp.get("aspect", "?"))
            applying_str = "аплікуючий" if asp.get("applying") else "сепаруючий"
            aspects_list.append(
                f"ПРОГРЕСИВНА:{p1_display} (у {asp.get('progressed_sign', '?')}, натальний будинок {p_house}) "
                f"{asp_name} НАТАЛЬНА:{p2_display} (у {asp.get('natal_sign', '?')}, будинок {n_house}) "
                f"— орбіс {orb_val}°, {applying_str}"
            )
        else:
            p1_display = PLANET_EN.get(p1, p1)
            p2_display = PLANET_EN.get(p2, p2)
            applying_str = "applying" if asp.get("applying") else "separating"
            aspects_list.append(
                f"PROGRESSED:{p1_display} (in {asp.get('progressed_sign', '?')}, natal house {p_house}) "
                f"{asp.get('aspect', '?')} NATAL:{p2_display} (in {asp.get('natal_sign', '?')}, house {n_house}) "
                f"— orb {orb_val}°, {applying_str}"
            )
    aspects_str = "\n".join(aspects_list) if aspects_list else (
        "Точних аспектів до натальної карти зараз немає" if language == 'uk'
        else "Точных аспектов к натальной карте сейчас нет" if language == 'ru'
        else "No exact aspects to the natal chart right now"
    )

    # Book excerpts. Chunk-level technique filter (_matches_technique) —
    # books 28/29 are shared between transits and progressions, and book 29
    # itself mixes both techniques, so a chunk can pass the book_id filter
    # and still be purely about the wrong technique (see _shared.py comment
    # for the real case this closes).
    # Dev-only visibility (server log, never shown to the user, never fed
    # back into the prompt): for each planet/aspect section, log whether the
    # model will be grounded in a real book excerpt or falls back to its own
    # knowledge per prompt_templates/progressions.py rule 6 ("Книга не
    # обязана покрывать каждую конфигурацию — работай своими знаниями").
    # Added so a developer can tell which parts of a given analysis are
    # book-sourced vs the model's own claim, without changing the response
    # itself. 2026-08-30.
    def _log_rag_source(label: str, kept_chunks: List[Dict[str, Any]]) -> None:
        if kept_chunks:
            book_ids = sorted({c.get("book_id") for c in kept_chunks if c.get("book_id") is not None})
            print(f"[progressions_analysis][RAG-SOURCE] {label}: grounded — book_ids={book_ids}, {len(kept_chunks)} chunks")
        else:
            print(f"[progressions_analysis][RAG-SOURCE] {label}: NO FRAGMENTS — model will answer from its own knowledge (prompt rule 6)")

    planet_chunks_text = ""
    for result in planet_results:
        if isinstance(result, Exception):
            continue
        section_name, chunks = result
        chunks = [c for c in chunks if _matches_technique(c.get("text", ""), 'progression')]
        _log_rag_source(section_name, chunks)
        if chunks:
            planet_chunks_text += f"\n\n【{section_name.upper()}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:800]
                book_title = chunk.get("book_title", "")
                planet_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    aspect_chunks_text = ""
    for result in aspect_results:
        if isinstance(result, Exception):
            continue
        asp_label, chunks = result
        chunks = [c for c in chunks if _matches_technique(c.get("text", ""), 'progression')]
        _log_rag_source(asp_label, chunks)
        if chunks:
            aspect_chunks_text += f"\n\n【АСПЕКТ: {asp_label}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:600]
                book_title = chunk.get("book_title", "")
                aspect_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    books_content = f"""
=== ФРАГМЕНТЫ ПО ПРОГРЕССИВНЫМ ПЛАНЕТАМ (из всех книг) ===
{planet_chunks_text}

=== ФРАГМЕНТЫ ПО АСПЕКТАМ ПРОГРЕССИЙ (из всех книг) ===
{aspect_chunks_text}
"""

    prompt = template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # --- Progressions data ---
    # Data language (sign/sign_ru/sign_uk, PLANET_RU/PLANET_UK/PLANET_EN) via
    # _localized()/_planet_display() — this whole block used to be hardcoded
    # in Russian REGARDLESS of language (the template above was already
    # bilingual, but the data wasn't), then extended to 3-way instead of a
    # binary is_ru. Plan: app/services/specs/progressions_synastry_pattern_plan.md.
    age = progressions.get("age_years", "?")
    period = progressions.get("period", "?")

    prompt += f"\n\n{labels['progressions_data_header']}"
    prompt += f"\n{labels['age']}: {age}"
    prompt += f"\n{labels['period']}: {period}"

    # Progressed lunar phase — the stage of the ~30-year cycle, the main context for the whole analysis
    lunar_phase = progressions.get("lunar_phase") or {}
    if lunar_phase:
        phase_name = _localized(lunar_phase, "phase", language, "?")
        prompt += f"\n{labels['progressed_lunar_phase_label']}: {phase_name} ({labels['moon_sun_angle_label']} {lunar_phase.get('angle', '?')}°)"

    prog_asc = progressions.get("progressed_ascendant", {})
    prog_mc = progressions.get("progressed_mc", {})
    if prog_asc:
        asc_sign = _localized(prog_asc, "sign", language, "?")
        prompt += f"\n{labels['progressed_ascendant_label']}: {asc_sign}"
    if prog_mc:
        mc_sign = _localized(prog_mc, "sign", language, "?")
        prompt += f"\n{labels['progressed_mc_label']}: {mc_sign}"

    # Layer prefix (ПРОГРЕССИВНАЯ:/PROGRESSED:) before EVERY planet line, not
    # just in the block heading — otherwise find_fabricated_positions_layered
    # below won't be able to attribute a position to a layer by the nearest marker.
    prompt += f"\n\n{labels['progressed_planets_header']}"
    for planet_name in PERSONAL_PLANETS + [n for n in prog_planets if n not in PERSONAL_PLANETS]:
        planet_data = prog_planets.get(planet_name)
        if not planet_data:
            continue
        planet_display = _planet_display(planet_name, language)
        sign_display = _localized(planet_data, "sign", language, "?")
        degree = planet_data.get("degree", "?")
        house = planet_data.get("natal_house", "?")
        rx_str = labels['retrograde_inline'] if planet_data.get("is_retrograde") else ""
        markers = []
        if planet_data.get("changed_sign") and planet_data.get("natal_sign"):
            natal_planet_data = natal_planets.get(planet_name, {})
            natal_sign_display = natal_planet_data.get(_lang_key("sign", language), planet_data.get("natal_sign"))
            markers.append(labels['changed_sign_marker'].format(sign=natal_sign_display))
        if planet_data.get("changed_house") and planet_data.get("natal_planet_house"):
            markers.append(labels['changed_house_marker'].format(house=planet_data['natal_planet_house']))
        if planet_data.get("years_to_next_sign") is not None:
            markers.append(labels['years_to_next_sign_marker'].format(years=planet_data['years_to_next_sign']))
        markers_str = " — " + "; ".join(markers) if markers else ""
        try:
            degree_str = f"{float(degree):.1f}°"
        except (TypeError, ValueError):
            degree_str = f"{degree}°"
        prompt += f"\n{labels['layer_progressed']}: {planet_display}: {degree_str} {sign_display}, {labels['house_word']} {house}{rx_str}{markers_str}"

    # The full natal chart — without it a "progression over natal" overlay is impossible
    prompt += f"\n\n{labels['natal_chart_overlay_header']}"
    sun_display = _planet_display('Sun', language)
    moon_display = _planet_display('Moon', language)
    asc_display = _planet_display('Ascendant', language)
    natal_sun_sign = _localized2(natal_summary, natal_chart, "sun_sign", language, "?")
    natal_moon_sign = _localized2(natal_summary, natal_chart, "moon_sign", language, "?")
    natal_asc_sign = _localized2(natal_summary, natal_chart, "ascendant", language, "?")
    prompt += f"\n{labels['layer_natal']}: {sun_display}: {natal_sun_sign}"
    prompt += f"\n{labels['layer_natal']}: {moon_display}: {natal_moon_sign}"
    prompt += f"\n{labels['layer_natal']}: {asc_display}: {natal_asc_sign}"
    if natal_planets:
        prompt += f"\n{labels['natal_planets_list_label']}"
        for n_name, n_data in natal_planets.items():
            n_display = _planet_display(n_name, language)
            n_sign = _localized(n_data, "sign", language, "?")
            n_house = n_data.get("house", "?")
            n_rx = labels['retrograde_short'] if n_data.get("is_retrograde") else ""
            prompt += f"\n  {labels['layer_natal']}: {n_display}: {n_sign}, {labels['house_word']} {n_house}{n_rx}"

    # "Layers" for post-generation text checking — progressed position vs
    # natal position of the SAME planet (a generalization of the "Partner 1/2"
    # pattern from synastry_service.py into text_verification.py). Shape —
    # {'planets': {...}, 'ascendant':, 'ascendant_ru':} — the same as
    # natal_chart, so the natal layer is passed as-is, and progressed is
    # built from the same fields.
    progressed_chart_like = {
        'planets': prog_planets,
        'ascendant': prog_asc.get('sign'),
        'ascendant_ru': prog_asc.get('sign_ru'),
        'ascendant_uk': prog_asc.get('sign_uk'),
    }
    layers = {'progressed': progressed_chart_like, 'natal': natal_chart or {}}

    return {
        'adapter': adapter,
        'prompt': prompt,
        'aspects': aspects,
        'layers': layers,
        'prog_planets': prog_planets,
        'period': period,
        'age': age,
    }

async def progressions_analysis(
    natal_chart: Dict[str, Any],
    progressions: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    AI analysis of secondary progressions — RAG search + prompt assembly via
    _prepare_progressions_analysis, one final LLM call, then the fix/detect
    anti-fabrication pass. Behavior unchanged by the step-2а refactor
    (plans/streaming-rollout-synastry-progressions-transits.md) — this is the
    same code that used to run inline in this function.
    """
    prep = await _prepare_progressions_analysis(natal_chart, progressions, language, top_k_per_book, mode)
    adapter = prep['adapter']
    prompt = prep['prompt']
    aspects = prep['aspects']
    layers = prep['layers']
    prog_planets = prep['prog_planets']
    period = prep['period']
    age = prep['age']

    # --- Step 3: One final LLM call ---
    print(f"[progressions_analysis] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    try:
        full_analysis = await adapter.generate(prompt, language)

        if language in ('ru', 'en', 'uk'):
            # Positions: only fixes what doesn't exist in ANY layer —
            # the same as fix_fabricated_planet_positions in synastry
            # (union check), generalized to layers. Plan:
            # app/services/specs/progressions_synastry_pattern_plan.md.
            # Detection runs first so the log can distinguish "nothing was
            # wrong" from "something was wrong and got repaired silently".
            _found = find_fabricated_positions_layered(full_analysis, layers, language=language)
            _fabricated = _found.get('fabricated', [])
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if _fabricated or unresolved:
                print(
                    f"[progressions_analysis] Position check: found {len(_fabricated)}, "
                    f"fixed {len(_fabricated) - len(unresolved)}, unresolved {len(unresolved)}"
                    + (f": {unresolved}" if unresolved else "")
                )
            else:
                print("[progressions_analysis] Position check: OK, no fabricated positions found")

            # Layer confused (sign is correct, but not for the layer the
            # marker claimed) — log only, never fixed (see
            # find_fabricated_positions_layered's docstring).
            position_issues = find_fabricated_positions_layered(full_analysis, layers, language=language)
            if position_issues.get('layer_confused'):
                print(f"[progressions_analysis] Layer-confused positions detected (not fixed): {position_issues['layer_confused']}")
            else:
                print("[progressions_analysis] Layer-confusion check: OK, no layer-confused positions")

            # Detection only — the claimed progression→natal aspect type is
            # checked against the actually calculated one (aspects_to_natal).
            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, aspects, language=language, layer_keys=('progressed', 'natal')
            )
            if fabricated_aspects:
                print(f"[progressions_analysis] Fabricated aspect types detected (not fixed): {fabricated_aspects}")
            else:
                print("[progressions_analysis] Aspect-type check: OK, no fabricated aspect types")

            # Detection only, from prose — the text is left alone, nothing added.
            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[progressions_analysis] Undercovered aspects detected (not filled): {undercovered}")
            else:
                print(f"[progressions_analysis] Coverage check: OK, all {len(aspects)} aspects covered")

            # Detect-only, no fix — see prompt rule 12 (prompt_templates/progressions.py)
            # and find_return_mislabeling's docstring for the case this tracks.
            return_mislabeling = find_return_mislabeling(full_analysis, language=language)
            if return_mislabeling:
                print(f"[progressions_analysis] Return-mislabeling detected (not fixed): {return_mislabeling}")
            else:
                print("[progressions_analysis] Return-mislabeling check: OK, no 'planetary return' language found")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[progressions_analysis] LLM error: {e}")

    prog_moon = prog_planets.get("Moon", {})
    prog_sun = prog_planets.get("Sun", {})

    return {
        "analysis": full_analysis,
        "progressions_summary": {
            "period": period,
            "age_years": age,
            "lunar_phase": (progressions.get("lunar_phase") or {}).get("phase"),
            "lunar_phase_ru": (progressions.get("lunar_phase") or {}).get("phase_ru"),
            "progressed_moon_sign": prog_moon.get("sign", "?"),
            "progressed_moon_sign_ru": prog_moon.get("sign_ru", "?"),
            "progressed_moon_house": prog_moon.get("natal_house"),
            "progressed_sun_sign": prog_sun.get("sign", "?"),
            "progressed_sun_sign_ru": prog_sun.get("sign_ru", "?"),
            "sun_changed_sign": prog_sun.get("changed_sign", False),
            "aspects_count": len(aspects),
        },
        "language": language,
        "version": "progressions_v1_hybrid_rag"
    }

async def progressions_analysis_stream(
    natal_chart: Dict[str, Any],
    progressions: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced'
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of progressions_analysis
    (plans/streaming-rollout-synastry-progressions-transits.md, step 2б). Same
    prep (_prepare_progressions_analysis), same finalize pipeline (fix +
    layer-confused detect + aspect-type detect + coverage detect) — only the
    delivery differs. The `final` event carries the same canonical JSON
    progressions_analysis would have returned.
    """
    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_progressions_analysis(natal_chart, progressions, language, top_k_per_book, mode)
    adapter = prep['adapter']
    prompt = prep['prompt']
    aspects = prep['aspects']
    layers = prep['layers']
    prog_planets = prep['prog_planets']
    period = prep['period']
    age = prep['age']

    async def finalize(buffer: str, released: str) -> Dict[str, Any]:
        full_analysis = buffer
        if language in ('ru', 'en', 'uk'):
            # Detection runs before the fix so the log can distinguish "nothing
            # was wrong" from "something was wrong and got repaired silently" —
            # fix_* only reports what it could NOT repair.
            _found = find_fabricated_positions_layered(full_analysis, layers, language=language)
            _fabricated = _found.get('fabricated', [])
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if _fabricated or unresolved:
                print(
                    f"[progressions_analysis_stream] Position check: found {len(_fabricated)}, "
                    f"fixed {len(_fabricated) - len(unresolved)}, unresolved {len(unresolved)}"
                    + (f": {unresolved}" if unresolved else "")
                )
            else:
                print("[progressions_analysis_stream] Position check: OK, no fabricated positions found")

            # Layer confused — log only, never fixed. Stays on the FIXED text
            # (a second, separate call), same as the non-stream pipeline.
            position_issues = find_fabricated_positions_layered(full_analysis, layers, language=language)
            if position_issues.get('layer_confused'):
                print(f"[progressions_analysis_stream] Layer-confused positions detected (not fixed): {position_issues['layer_confused']}")
            else:
                print("[progressions_analysis_stream] Layer-confusion check: OK, no layer-confused positions")

            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, aspects, language=language, layer_keys=('progressed', 'natal')
            )
            if fabricated_aspects:
                print(f"[progressions_analysis_stream] Fabricated aspect types detected (not fixed): {fabricated_aspects}")
            else:
                print("[progressions_analysis_stream] Aspect-type check: OK, no fabricated aspect types")

            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[progressions_analysis_stream] Undercovered aspects detected (not filled): {undercovered}")
            else:
                print(f"[progressions_analysis_stream] Coverage check: OK, all {len(aspects)} aspects covered")

            return_mislabeling = find_return_mislabeling(full_analysis, language=language)
            if return_mislabeling:
                print(f"[progressions_analysis_stream] Return-mislabeling detected (not fixed): {return_mislabeling}")
            else:
                print("[progressions_analysis_stream] Return-mislabeling check: OK, no 'planetary return' language found")

        if not full_analysis.startswith(released):
            print(
                "[stream_mismatch] progressions_analysis_stream"
                f" released={released!r} canonical={full_analysis!r}"
            )

        prog_moon = prog_planets.get("Moon", {})
        prog_sun = prog_planets.get("Sun", {})

        return {
            "analysis": full_analysis,
            "progressions_summary": {
                "period": period,
                "age_years": age,
                "lunar_phase": (progressions.get("lunar_phase") or {}).get("phase"),
                "lunar_phase_ru": (progressions.get("lunar_phase") or {}).get("phase_ru"),
                "progressed_moon_sign": prog_moon.get("sign", "?"),
                "progressed_moon_sign_ru": prog_moon.get("sign_ru", "?"),
                "progressed_moon_house": prog_moon.get("natal_house"),
                "progressed_sun_sign": prog_sun.get("sign", "?"),
                "progressed_sun_sign_ru": prog_sun.get("sign_ru", "?"),
                "sun_changed_sign": prog_sun.get("changed_sign", False),
                "aspects_count": len(aspects),
            },
            "language": language,
            "version": "progressions_v1_hybrid_rag"
        }

    fix_fn = lambda text: fix_fabricated_positions_layered(text, layers, language=language)

    print(f"[progressions_analysis_stream] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")
    yield {"event": "stage", "data": {"stage": "generating"}}

    async for event in stream_verified_analysis(adapter, prompt, language, fix_fn, finalize):
        yield event


# ============================================================
# PROGRESSIONS CHAT
# ============================================================

async def _prepare_chat_with_progressions_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru"
) -> Dict[str, Any]:
    """
    Shared prep for chat_with_progressions_astrologer and its streaming twin:
    hybrid RAG search (restricted to the progressions/transits book set —
    same TRANSITS_PROGRESSIONS_BOOK_IDS as _prepare_progressions_analysis) +
    messages build. Mirrors chat.py's _prepare_chat_with_astrologer, but
    reads a progressions-shaped chart_data — the same dict
    calculate_secondary_progressions/the /analysis/progressions endpoint
    returns (progressed_planets, natal_summary, lunar_phase,
    aspects_to_natal, period, age_years) — instead of a flat natal chart, and
    frames the system prompt around the progressed chart rather than "this
    person's natal chart" (see app/services/INSIGHTS.md, 2026-07-31 entry on
    chat.py's natal-chat language gap — this prep is 3-way localized from the
    start via _localized/_planet_display instead of copying that gap).

    Every entry in progressed_planets already carries its own natal_sign/
    natal_house/changed_sign/changed_house (astrology_v2.py:899-918) — no
    separate full natal_chart is needed here, only chart_data itself.
    """
    import asyncio
    from app.services.llm_adapter import get_llm_adapter
    from app.utils.astrology_v2 import ZODIAC_SIGNS, ZODIAC_SIGNS_RU, ZODIAC_SIGNS_UK

    adapter = get_llm_adapter()
    lang = language if language in ('ru', 'en', 'uk') else 'en'
    en_to_ru = dict(zip(ZODIAC_SIGNS, ZODIAC_SIGNS_RU))
    en_to_uk = dict(zip(ZODIAC_SIGNS, ZODIAC_SIGNS_UK))

    def _natal_sign_display(en_sign) -> str:
        if not en_sign:
            return "?"
        return {'ru': en_to_ru, 'uk': en_to_uk}.get(lang, {}).get(en_sign, en_sign)

    prog_planets = chart_data.get("progressed_planets", {}) or {}
    natal_summary = chart_data.get("natal_summary", {}) or {}
    lunar_phase = chart_data.get("lunar_phase") or {}
    aspects = chart_data.get("aspects_to_natal", []) or []
    period = chart_data.get("period", "?")
    age = chart_data.get("age_years", "?")

    PERSONAL_PLANETS = ["Sun", "Moon", "Mercury", "Venus", "Mars"]

    book_titles = await _fetch_book_titles(TRANSITS_PROGRESSIONS_BOOK_IDS)

    async def search_question():
        return await search_chunks_by_book_ids(question, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)

    async def search_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("natal_house", "")
        query = f"progressed {planet_name.lower()} {sign.lower()} house {house}"
        chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=2)
        return planet_name, chunks

    planet_tasks = [
        search_planet(name, prog_planets[name])
        for name in PERSONAL_PLANETS if name in prog_planets
    ]
    question_chunks, *planet_results = await asyncio.gather(
        search_question(), *planet_tasks, return_exceptions=True
    )

    question_context = ""
    if question_chunks and not isinstance(question_chunks, Exception):
        question_context = "\n=== FRAGMENTS ON THE QUESTION ===\n"
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

    books_context = f"{question_context}\n=== FRAGMENTS ON PROGRESSED PLANETS ===\n{planet_context}"
    if not question_context.strip() and not planet_context.strip():
        books_context = {
            'ru': "В библиотеке не найдено релевантных фрагментов по этому вопросу. Используйте общие принципы вторичных прогрессий.",
            'uk': "У бібліотеці не знайдено релевантних фрагментів щодо цього питання. Використовуйте загальні принципи вторинних прогресій.",
            'en': "No relevant fragments found in the library for this question. Use general secondary-progressions principles.",
        }[lang]

    planets_summary = ""
    for planet_name in PERSONAL_PLANETS + [n for n in prog_planets if n not in PERSONAL_PLANETS]:
        pd = prog_planets.get(planet_name)
        if not pd:
            continue
        p_display = _planet_display(planet_name, language)
        sign_display = _localized(pd, "sign", language, "?")
        house = pd.get("natal_house", "?")
        rx = " (Rx)" if pd.get("is_retrograde") else ""
        marker = ""
        if pd.get("changed_sign"):
            marker = f" [changed sign, natally {_natal_sign_display(pd.get('natal_sign'))}]"
        planets_summary += f"  {p_display}: {sign_display}, house {house}{rx}{marker}\n"

    aspects_list = []
    for asp in aspects[:15]:
        p1 = _planet_display(asp.get("progressed", asp.get("planet1", "?")), language)
        p2 = _planet_display(asp.get("natal", asp.get("planet2", "?")), language)
        asp_name = _localized(asp, "aspect", language, asp.get("aspect", "?"))
        orb_val = asp.get("orb", "?")
        aspects_list.append(f"PROGRESSED:{p1} {asp_name} NATAL:{p2} — orb {orb_val}°")
    aspects_str = "\n".join(aspects_list) if aspects_list else "—"

    natal_sun = _localized(natal_summary, "sun_sign", language, "?")
    natal_moon = _localized(natal_summary, "moon_sign", language, "?")
    natal_asc = _localized(natal_summary, "ascendant", language, "?")
    phase_name = _localized(lunar_phase, "phase", language, "?") if lunar_phase else "?"

    system_prompt = f"""You are a personal astrologer. You have already done a full analysis of this person's SECONDARY PROGRESSIONS (the progressed chart, age {age}, period {period}) and now answer their questions about it.

=== NATAL CHART (reference layer — do not present these as progressed) ===
Sun: {natal_sun}
Moon: {natal_moon}
Ascendant: {natal_asc}

=== PROGRESSED LUNAR PHASE ===
{phase_name}

=== PROGRESSED PLANETS (vs natal) ===
{planets_summary}

=== KEY PROGRESSED ASPECTS TO NATAL ===
{aspects_str}

=== FULL PROGRESSIONS ANALYSIS ===
{full_analysis}

=== KNOWLEDGE FROM ASTROLOGY BOOKS ===
{books_context}

RULES:
- Answer personally — you know this person's progressed chart
- Always distinguish PROGRESSED positions from NATAL positions explicitly — never present one as the other, never call a progressed position "natal" or vice versa
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

async def chat_with_progressions_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru"
) -> Dict[str, Any]:
    """
    Chat with the astrologer about secondary progressions — HYBRID approach.
    Modeled on chat_with_astrologer (chat.py).
    """
    prep = await _prepare_chat_with_progressions_astrologer(question, chart_data, full_analysis, chat_history, language)
    answer = await prep["adapter"].generate_with_messages(prep["messages"], language)

    return {
        "answer": answer,
        "relevant_chunks": prep["question_chunks"]
    }

async def chat_with_progressions_astrologer_stream(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru"
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of chat_with_progressions_astrologer — typewriter delivery
    for the chat modal. No anti-fabrication fix runs on chat replies (same as
    chat_with_astrologer_stream/chat_with_synastry_astrologer_stream), so
    this goes through stream_chat_reply (raw token relay), not
    stream_verified_analysis.
    """
    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_chat_with_progressions_astrologer(question, chart_data, full_analysis, chat_history, language)

    async def finalize(buffer: str) -> Dict[str, Any]:
        return {
            "answer": buffer,
            "relevant_chunks": prep["question_chunks"]
        }

    yield {"event": "stage", "data": {"stage": "generating"}}
    async for event in stream_chat_reply(prep["adapter"], prep["messages"], language, finalize):
        yield event
