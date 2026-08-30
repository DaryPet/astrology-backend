from typing import Dict, Any, Optional, AsyncGenerator
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template
from app.services.prompt_templates.languages import normalize_language
from app.services.text_verification import (
    find_fabricated_positions_layered,
    fix_fabricated_positions_layered,
    find_fabricated_aspect_types_layered,
    find_undercovered_aspects_generic,
)


from app.services.analysis_service._shared import (
    HOUSE_WORDS,
    TRANSITS_PROGRESSIONS_BOOK_IDS,
    _fetch_book_titles,
    _localized,
    _localized2,
    _planet_display,
    search_chunks_by_book_ids,
    stream_verified_analysis,
)


async def _prepare_transits_analysis(
    natal_chart: Dict[str, Any],
    transits: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced',
    transit_place: Optional[str] = None,
    transit_lat: Optional[float] = None,
    transit_lon: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Shared prep for transits_analysis and its streaming twin
    (transits_analysis_stream): everything from "no prompt yet" to
    "prompt/aspects/layers ready for one LLM call". Split out by
    plans/streaming-rollout-synastry-progressions-transits.md (step 3а) —
    mirrors _prepare_progressions_analysis — behavior unchanged, this is the
    same code transits_analysis used to run inline.

    AI analysis of the day's transits — the same hybrid approach as progressions:
    - targeted RAG search (transiting planets in natal houses + aspects to natal)
    - assembling a structured prompt (the 'transits' template, advanced/simple)

    transit_place/lat/lon — the place where the person is at the moment of the
    transit. This matters for interpreting the transit houses and moon phase.
    """
    import asyncio
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_labels import get_labels
    from app.services.prompt_templates import get_template

    adapter = get_llm_adapter()
    labels = get_labels(language)

    t_planets = transits.get("transit_planets", {})
    aspects = transits.get("aspects_to_natal", [])
    natal_summary = transits.get("natal_summary", {})
    natal_planets = (natal_chart or {}).get("planets", {})

    # Slow transits = the main themes of the period; fast ones = the flavor of the day
    slow_aspects = [a for a in aspects if a.get("is_slow")]
    fast_aspects = [a for a in aspects if not a.get("is_slow")]

    # Limits the number of concurrent requests to Supabase — same reason as
    # synastry and progressions (synastry_service.py:599). For transits ALL
    # aspects are searched (aspect_pool below), noticeably more requests than
    # progressions — here the semaphore isn't a future safeguard, it's needed already.
    # With the switch to TRANSITS_PROGRESSIONS_BOOK_IDS (2 books instead of
    # "priority + the whole catalog", user decision 2026-08-02) each call
    # makes 2 calls to the thread pool, not 3 like search_chunks_priority_book
    # used to — the same win as in progressions.
    search_semaphore = asyncio.Semaphore(12)

    # Book titles — one request for the whole analysis, not per RAG sub-request.
    book_titles = await _fetch_book_titles(TRANSITS_PROGRESSIONS_BOOK_IDS)

    # --- Step 1: Parallel RAG search ---
    async def search_transit_planet(planet_name: str, planet_data: Dict) -> tuple:
        sign = planet_data.get("sign", "")
        house = planet_data.get("natal_house", "")
        house_word = HOUSE_WORDS.get(house, str(house))
        query = f"transit {planet_name.lower()} {sign.lower()} {house_word} house"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return planet_name, chunks

    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get("transit", asp.get("planet1", ""))
        p2 = asp.get("natal", asp.get("planet2", ""))
        asp_type = asp.get("aspect", "")
        query = f"transit {p1.lower()} {asp_type.lower()} natal {p2.lower()}"
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(query, TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5)
        return f"{p1} {asp_type} {p2}", chunks

    async def search_lunar_phase() -> tuple:
        phase = (transits.get("lunar_phase") or {}).get("phase", "")
        if not phase:
            return "Lunar Phase", []
        async with search_semaphore:
            chunks = await search_chunks_by_book_ids(
                f"lunar phase {phase.lower()} moon", TRANSITS_PROGRESSIONS_BOOK_IDS, book_titles, top_k_per_book=5
            )
        return f"Lunar Phase: {phase}", chunks

    # Planets to search: slow ones with aspects + Moon and Sun (the day)
    search_planet_names = []
    for a in slow_aspects:
        name = a.get("transit")
        if name and name not in search_planet_names:
            search_planet_names.append(name)
    for name in ("Moon", "Sun"):
        if name in t_planets and name not in search_planet_names:
            search_planet_names.append(name)

    planet_tasks = [
        search_transit_planet(name, t_planets[name])
        for name in search_planet_names if name in t_planets
    ]
    planet_tasks.append(search_lunar_phase())

    # Aspects: all slow + all fast, for a complete analysis
    aspect_pool = slow_aspects + fast_aspects
    aspect_tasks = [search_aspect(asp) for asp in aspect_pool]

    print(f"[transits_analysis] Parallel RAG: {len(planet_tasks)} planet queries, {len(aspect_tasks)} aspect queries")

    planet_results = await asyncio.gather(*planet_tasks, return_exceptions=True)
    aspect_results = await asyncio.gather(*aspect_tasks, return_exceptions=True)

    # --- Step 2: Assemble the structured prompt ---
    template = get_template("transits", language, mode)

    # NOTE on the 'transit_house' field here: in aspects_to_natal (calculate_transits,
    # astrology_v2.py:1230) it's the NATAL house of the transit planet (which natal
    # house it's "moving through"), NOT the house in the current place's transit
    # chart — that's in 'transit_planet_transit_house' (:1232). The same key
    # 'transit_house' in t_planets[X] (:1205 below) means something DIFFERENT — the
    # real transit house. Don't confuse the two when reading/editing — plan:
    # app/services/specs/transits_synastry_pattern_plan.md.
    lang = normalize_language(language)

    def fmt_aspect(asp: Dict) -> str:
        p1 = asp.get("transit", asp.get("planet1", "?"))
        p2 = asp.get("natal", asp.get("planet2", "?"))
        p1_display = _planet_display(p1, language)
        p2_display = _planet_display(p2, language)
        orb_val = asp.get("orb", "?")
        natal_house_of_transit_planet = asp.get("transit_house", "?")  # see the comment above
        current_transit_house = asp.get("transit_planet_transit_house", "?")
        if current_transit_house == "?":
            transit_house_str = ""
        elif lang == 'ru':
            transit_house_str = f", транзитный дом {current_transit_house}"
        elif lang == 'uk':
            transit_house_str = f", транзитний дім {current_transit_house}"
        else:
            transit_house_str = f", transit house {current_transit_house}"
        ret_mark = ""
        if asp.get("is_return"):
            ret_mark = {
                'ru': " [ВОЗВРАТ ПЛАНЕТЫ!]",
                'uk': " [ПОВЕРНЕННЯ ПЛАНЕТИ!]",
                'en': " [PLANETARY RETURN!]",
            }[lang]
        if lang == 'ru':
            asp_name = asp.get("aspect_ru", asp.get("aspect", "?"))
            applying_str = "сходящийся" if asp.get("applying") else "расходящийся"
            return (f"ТРАНЗИТНЫЙ:{p1_display} (в {asp.get('transit_sign', '?')}, идёт по натальному дому {natal_house_of_transit_planet}{transit_house_str}) "
                    f"{asp_name} НАТАЛЬНЫЙ:{p2_display} (в {asp.get('natal_sign', '?')}, дом {asp.get('natal_house', '?')}) "
                    f"— орб {orb_val}°, {applying_str}{ret_mark}")
        if lang == 'uk':
            asp_name = asp.get("aspect_uk", asp.get("aspect", "?"))
            applying_str = "аплікуючий" if asp.get("applying") else "сепаруючий"
            return (f"ТРАНЗИТНА:{p1_display} (у {asp.get('transit_sign', '?')}, проходить по натальному будинку {natal_house_of_transit_planet}{transit_house_str}) "
                    f"{asp_name} НАТАЛЬНА:{p2_display} (у {asp.get('natal_sign', '?')}, будинок {asp.get('natal_house', '?')}) "
                    f"— орбіс {orb_val}°, {applying_str}{ret_mark}")
        applying_str = "applying" if asp.get("applying") else "separating"
        return (f"TRANSITING:{p1_display} (in {asp.get('transit_sign', '?')}, moving through natal house {natal_house_of_transit_planet}{transit_house_str}) "
                f"{asp.get('aspect', '?')} NATAL:{p2_display} (in {asp.get('natal_sign', '?')}, house {asp.get('natal_house', '?')}) "
                f"— orb {orb_val}°, {applying_str}{ret_mark}")

    _NO_SLOW_ASPECTS = {
        'ru': "Нет точных аспектов от медленных планет",
        'uk': "Немає точних аспектів від повільних планет",
        'en': "No exact aspects from slow planets",
    }
    _NO_FAST_ASPECTS = {
        'ru': "Нет точных аспектов от быстрых планет",
        'uk': "Немає точних аспектів від швидких планет",
        'en': "No exact aspects from fast planets",
    }
    _SLOW_HEADER = {
        'ru': "【МЕДЛЕННЫЕ ПЛАНЕТЫ — главные темы периода】\n",
        'uk': "【ПОВІЛЬНІ ПЛАНЕТИ — головні теми періоду】\n",
        'en': "【SLOW PLANETS — main themes of the period】\n",
    }
    _FAST_HEADER = {
        'ru': "\n\n【БЫСТРЫЕ ПЛАНЕТЫ — окраска именно этого дня】\n",
        'uk': "\n\n【ШВИДКІ ПЛАНЕТИ — забарвлення саме цього дня】\n",
        'en': "\n\n【FAST PLANETS — the flavor of this specific day】\n",
    }
    slow_str = "\n".join(fmt_aspect(a) for a in slow_aspects) if slow_aspects else _NO_SLOW_ASPECTS[lang]
    fast_str = "\n".join(fmt_aspect(a) for a in fast_aspects) if fast_aspects else _NO_FAST_ASPECTS[lang]
    aspects_str = _SLOW_HEADER[lang] + slow_str + _FAST_HEADER[lang] + fast_str

    # Book excerpts
    planet_chunks_text = ""
    for result in planet_results:
        if isinstance(result, Exception):
            continue
        section_name, chunks = result
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
        if chunks:
            aspect_chunks_text += f"\n\n【АСПЕКТ: {asp_label}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:600]
                book_title = chunk.get("book_title", "")
                aspect_chunks_text += f"[{i}] ({book_title}):\n{text}\n"

    books_content = f"""
=== ФРАГМЕНТЫ ПО ТРАНЗИТНЫМ ПЛАНЕТАМ (из всех книг) ===
{planet_chunks_text}

=== ФРАГМЕНТЫ ПО АСПЕКТАМ ТРАНЗИТОВ (из всех книг) ===
{aspect_chunks_text}
"""

    prompt = template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # --- Transits data ---
    # Data language via _localized()/_planet_display() — this whole block
    # (except the transit place and Asc/MC) used to be hardcoded in Russian
    # regardless of language, then extended to 3-way instead of a binary
    # is_ru. Plan: app/services/specs/transits_synastry_pattern_plan.md.
    period = transits.get("period", "?")
    prompt += f"\n\n{labels['transits_data_header']}"
    prompt += f"\n{labels['day_label']}: {period}"

    # Transit place info
    transit_summary = transits.get("transit_summary", {})
    if transit_lat is not None and transit_lon is not None:
        location_name = transit_place or labels['not_specified']
        prompt += f"\n{labels['transit_place_label']}: {location_name} ({labels['coordinates_label']}: {transit_lat:.4f}°, {transit_lon:.4f}°)"

    transit_asc = transit_summary.get("ascendant")
    transit_mc = transit_summary.get("mc")
    if transit_asc or transit_mc:
        asc_sign = _localized(transit_asc, "sign", language, "?") if transit_asc else "?"
        mc_sign = _localized(transit_mc, "sign", language, "?") if transit_mc else "?"
        prompt += f"\n{labels['transiting_ascendant_label']}: {asc_sign}"
        prompt += f"\n{labels['transiting_mc_label']}: {mc_sign}"

    lunar_phase = transits.get("lunar_phase") or {}
    if lunar_phase:
        phase_name = _localized(lunar_phase, "phase", language, "?")
        prompt += f"\n{labels['day_lunar_phase_label']}: {phase_name} ({labels['moon_sun_angle_label']} {lunar_phase.get('angle', '?')}°)"

    # Layer prefix (ТРАНЗИТНАЯ:/TRANSITING:) before EVERY planet line, not
    # just in the block heading — otherwise find_fabricated_positions_layered
    # below won't be able to attribute a position to a layer by the nearest marker.
    TRANSIT_ORDER = ["Moon", "Sun", "Mercury", "Venus", "Mars", "Jupiter", "Saturn",
                     "Uranus", "Neptune", "Pluto", "NorthNode", "SouthNode", "Chiron", "Lilith"]
    prompt += f"\n\n{labels['transit_planets_header']}"
    for planet_name in TRANSIT_ORDER:
        planet_data = t_planets.get(planet_name)
        if not planet_data:
            continue
        planet_display = _planet_display(planet_name, language)
        sign_display = _localized(planet_data, "sign", language, "?")
        degree = planet_data.get("degree", "?")
        # Here 'natal_house'/'transit_house' in t_planets[X] are NOT the same
        # values as the same-named fields in aspects_to_natal (see the comment
        # by fmt_aspect above): here natal_house = the planet's natal house,
        # transit_house = the real house in the current place's transit chart.
        house = planet_data.get("natal_house", "?")
        transit_house = planet_data.get("transit_house", "?")
        rx_str = labels['retrograde_inline'] if planet_data.get("is_retrograde") else ""
        slow_str2 = labels['slow_planet_marker'] if planet_data.get("is_slow") else ""
        try:
            degree_str = f"{float(degree):.1f}°"
        except (TypeError, ValueError):
            degree_str = f"{degree}°"
        prompt += (f"\n{labels['layer_transit']}: {planet_display}: {degree_str} {sign_display}, "
                   f"{labels['natal_house_word']} {house}, {labels['transit_house_word']} {transit_house}{rx_str}{slow_str2}")

    # The full natal chart — the basis for the overlay
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

    # "Layers" for post-generation text checking — transit position vs natal
    # position of the SAME planet (the same pattern as progressions, see
    # progressions_synastry_pattern_plan.md). Shape —
    # {'planets': {...}, 'ascendant':, 'ascendant_ru':} — the natal layer is
    # passed as-is, transit is built from the same transit_summary fields.
    transit_chart_like = {
        'planets': t_planets,
        'ascendant': transit_asc.get('sign') if transit_asc else None,
        'ascendant_ru': transit_asc.get('sign_ru') if transit_asc else None,
        'ascendant_uk': transit_asc.get('sign_uk') if transit_asc else None,
    }
    layers = {'transit': transit_chart_like, 'natal': natal_chart or {}}

    return {
        'adapter': adapter,
        'prompt': prompt,
        'aspects': aspects,
        'layers': layers,
        'period': period,
        'lunar_phase': lunar_phase,
        'slow_aspects': slow_aspects,
        'fast_aspects': fast_aspects,
    }

async def transits_analysis(
    natal_chart: Dict[str, Any],
    transits: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced',
    transit_place: Optional[str] = None,
    transit_lat: Optional[float] = None,
    transit_lon: Optional[float] = None,
) -> Dict[str, Any]:
    """
    AI analysis of the day's transits — RAG search + prompt assembly via
    _prepare_transits_analysis, one final LLM call, then the fix/detect
    anti-fabrication pass. Behavior unchanged by the step-3а refactor
    (plans/streaming-rollout-synastry-progressions-transits.md) — this is the
    same code that used to run inline in this function.
    """
    prep = await _prepare_transits_analysis(
        natal_chart, transits, language, top_k_per_book, mode, transit_place, transit_lat, transit_lon
    )
    adapter = prep['adapter']
    prompt = prep['prompt']
    aspects = prep['aspects']
    layers = prep['layers']
    period = prep['period']
    lunar_phase = prep['lunar_phase']
    slow_aspects = prep['slow_aspects']
    fast_aspects = prep['fast_aspects']

    # --- Step 3: One final LLM call ---
    print(f"[transits_analysis] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")

    try:
        full_analysis = await adapter.generate(prompt, language)

        if language in ('ru', 'en', 'uk'):
            # Positions: only fixes what doesn't exist in ANY layer.
            # Detection runs first so the log can distinguish "nothing was
            # wrong" from "something was wrong and got repaired silently".
            # Deliberately a separate pass from the layer_confused detection
            # below, which stays on the FIXED text as before.
            _found = find_fabricated_positions_layered(full_analysis, layers, language=language)
            _fabricated = _found.get('fabricated', [])
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if _fabricated or unresolved:
                print(
                    f"[transits_analysis] Position check: found {len(_fabricated)}, "
                    f"fixed {len(_fabricated) - len(unresolved)}, unresolved {len(unresolved)}"
                    + (f": {unresolved}" if unresolved else "")
                )
            else:
                print("[transits_analysis] Position check: OK, no fabricated positions found")

            # Layer confused — log only, never fixed.
            position_issues = find_fabricated_positions_layered(full_analysis, layers, language=language)
            if position_issues.get('layer_confused'):
                print(f"[transits_analysis] Layer-confused positions detected (not fixed): {position_issues['layer_confused']}")
            else:
                print("[transits_analysis] Layer-confusion check: OK, no layer-confused positions")

            # Detection only — the claimed transit→natal aspect type is
            # checked against the actually calculated one (aspects_to_natal).
            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, aspects, language=language, layer_keys=('transit', 'natal')
            )
            if fabricated_aspects:
                print(f"[transits_analysis] Fabricated aspect types detected (not fixed): {fabricated_aspects}")
            else:
                print("[transits_analysis] Aspect-type check: OK, no fabricated aspect types")

            # Detection only, from prose.
            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[transits_analysis] Undercovered aspects detected (not filled): {undercovered}")
            else:
                print(f"[transits_analysis] Coverage check: OK, all {len(aspects)} aspects covered")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[transits_analysis] LLM error: {e}")

    return {
        "analysis": full_analysis,
        "transits_summary": {
            "period": period,
            "lunar_phase": lunar_phase.get("phase"),
            "lunar_phase_ru": lunar_phase.get("phase_ru"),
            "slow_aspects_count": len(slow_aspects),
            "fast_aspects_count": len(fast_aspects),
            "returns": [a.get("transit") for a in aspects if a.get("is_return")],
        },
        "language": language,
        "version": "transits_v1_hybrid_rag"
    }

async def transits_analysis_stream(
    natal_chart: Dict[str, Any],
    transits: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 5,
    mode: str = 'advanced',
    transit_place: Optional[str] = None,
    transit_lat: Optional[float] = None,
    transit_lon: Optional[float] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of transits_analysis
    (plans/streaming-rollout-synastry-progressions-transits.md, step 3б). Same
    prep (_prepare_transits_analysis), same finalize pipeline (fix +
    layer-confused detect + aspect-type detect + coverage detect) — only the
    delivery differs. The `final` event carries the same canonical JSON
    transits_analysis would have returned.
    """
    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_transits_analysis(
        natal_chart, transits, language, top_k_per_book, mode, transit_place, transit_lat, transit_lon
    )
    adapter = prep['adapter']
    prompt = prep['prompt']
    aspects = prep['aspects']
    layers = prep['layers']
    period = prep['period']
    lunar_phase = prep['lunar_phase']
    slow_aspects = prep['slow_aspects']
    fast_aspects = prep['fast_aspects']

    async def finalize(buffer: str, released: str) -> Dict[str, Any]:
        full_analysis = buffer
        if language in ('ru', 'en', 'uk'):
            # Detection runs before the fix so the log can distinguish "nothing
            # was wrong" from "something was wrong and got repaired silently" —
            # fix_* only reports what it could NOT repair. Deliberately a
            # separate pass from the layer_confused detection below, which
            # stays on the FIXED text, same as the non-stream pipeline.
            _found = find_fabricated_positions_layered(full_analysis, layers, language=language)
            _fabricated = _found.get('fabricated', [])
            full_analysis, unresolved = fix_fabricated_positions_layered(
                full_analysis, layers, language=language
            )
            if _fabricated or unresolved:
                print(
                    f"[transits_analysis_stream] Position check: found {len(_fabricated)}, "
                    f"fixed {len(_fabricated) - len(unresolved)}, unresolved {len(unresolved)}"
                    + (f": {unresolved}" if unresolved else "")
                )
            else:
                print("[transits_analysis_stream] Position check: OK, no fabricated positions found")

            position_issues = find_fabricated_positions_layered(full_analysis, layers, language=language)
            if position_issues.get('layer_confused'):
                print(f"[transits_analysis_stream] Layer-confused positions detected (not fixed): {position_issues['layer_confused']}")
            else:
                print("[transits_analysis_stream] Layer-confusion check: OK, no layer-confused positions")

            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, aspects, language=language, layer_keys=('transit', 'natal')
            )
            if fabricated_aspects:
                print(f"[transits_analysis_stream] Fabricated aspect types detected (not fixed): {fabricated_aspects}")
            else:
                print("[transits_analysis_stream] Aspect-type check: OK, no fabricated aspect types")

            undercovered = find_undercovered_aspects_generic(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[transits_analysis_stream] Undercovered aspects detected (not filled): {undercovered}")
            else:
                print(f"[transits_analysis_stream] Coverage check: OK, all {len(aspects)} aspects covered")

        if not full_analysis.startswith(released):
            print(
                "[stream_mismatch] transits_analysis_stream"
                f" released={released!r} canonical={full_analysis!r}"
            )

        return {
            "analysis": full_analysis,
            "transits_summary": {
                "period": period,
                "lunar_phase": lunar_phase.get("phase"),
                "lunar_phase_ru": lunar_phase.get("phase_ru"),
                "slow_aspects_count": len(slow_aspects),
                "fast_aspects_count": len(fast_aspects),
                "returns": [a.get("transit") for a in aspects if a.get("is_return")],
            },
            "language": language,
            "version": "transits_v1_hybrid_rag"
        }

    fix_fn = lambda text: fix_fabricated_positions_layered(text, layers, language=language)

    print(f"[transits_analysis_stream] Sending final prompt to LLM (~{len(prompt)//4} tokens estimated)")
    yield {"event": "stage", "data": {"stage": "generating"}}

    async for event in stream_verified_analysis(adapter, prompt, language, fix_fn, finalize):
        yield event
