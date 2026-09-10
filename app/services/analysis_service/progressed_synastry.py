from typing import List, Dict, Any, Optional, AsyncGenerator
from app.services.prompt_templates import get_template
from app.services.prompt_templates.languages import normalize_language
from app.services.text_verification import (
    find_fabricated_positions_layered,
    fix_fabricated_positions_layered,
    find_fabricated_aspect_types_layered,
    find_undercovered_aspects_generic,
)


from app.services.analysis_service._shared import (
    PROGRESSIONS_PRIORITY_BOOK_ID,
    _lang_key,
    _localized,
    _planet_display,
    dedup_chunk_sections,
    search_chunks_priority_book,
    stream_chat_reply,
    stream_verified_analysis,
)


def _collect_progressed_synastry_layers(
    p1: Dict[str, Any], p2: Dict[str, Any],
    layer1: List[Dict[str, Any]], prog1_to_natal2: List[Dict[str, Any]], prog2_to_natal1: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Named layers (planet -> sign) for find_fabricated_positions_layered.

    IMPORTANT: 4 separate layers (p1_progressed/p2_progressed/p1_natal/p2_natal),
    NOT one merged dict — the same planet (e.g. the Moon) simultaneously has
    4 DIFFERENT valid signs (progr.1 ≠ natal.1 ≠ progr.2 ≠ natal.2), and
    find_fabricated_positions_layered merges valid pairs via set() PER LAYER
    (planet, sign) — the merge only works correctly across separate layers,
    not within one flat "planet -> single sign" dict (there's simply nowhere
    to store 4 values per key).

    progressed_synastry doesn't store the partners' full natal charts —
    natal_summary only gives Sun/Moon/Ascendant (astrology_v2.py:1061-1068).
    The remaining natal planets (Mercury, Mars, etc.) are reconstructed from
    the sign1/sign2 of the cross_overlay aspects themselves — the only place
    they appear. planet1 in the aspects is always the progressed planet of
    side "a", planet2 in cross_overlay is always the natal planet of the
    receiving side (see calculate_progressed_synastry, astrology_v2.py:1499-1509).
    """
    from app.utils.astrology_v2 import ZODIAC_SIGNS, ZODIAC_SIGNS_RU, ZODIAC_SIGNS_UK
    en_to_ru = dict(zip(ZODIAC_SIGNS, ZODIAC_SIGNS_RU))
    en_to_uk = dict(zip(ZODIAC_SIGNS, ZODIAC_SIGNS_UK))

    def from_sign_en(sign_en: Optional[str]) -> Dict[str, Optional[str]]:
        return {'sign': sign_en, 'sign_ru': en_to_ru.get(sign_en), 'sign_uk': en_to_uk.get(sign_en)}

    layers: Dict[str, Any] = {
        'p1_progressed': {'planets': dict(p1.get("progressed_planets") or {})},
        'p2_progressed': {'planets': dict(p2.get("progressed_planets") or {})},
    }
    for idx, person in ((1, p1), (2, p2)):
        ns = person.get("natal_summary") or {}
        layers[f'p{idx}_natal'] = {
            'planets': {
                'Sun': {'sign': ns.get("sun_sign"), 'sign_ru': ns.get("sun_sign_ru"), 'sign_uk': en_to_uk.get(ns.get("sun_sign"))},
                'Moon': {'sign': ns.get("moon_sign"), 'sign_ru': ns.get("moon_sign_ru"), 'sign_uk': en_to_uk.get(ns.get("moon_sign"))},
            },
            'ascendant': ns.get("ascendant"),
            'ascendant_ru': ns.get("ascendant_ru"),
            'ascendant_uk': en_to_uk.get(ns.get("ascendant")),
        }

    for asp in (layer1 or []):
        if asp.get("planet1"):
            layers['p1_progressed']['planets'].setdefault(asp["planet1"], from_sign_en(asp.get("sign1")))
        if asp.get("planet2"):
            layers['p2_progressed']['planets'].setdefault(asp["planet2"], from_sign_en(asp.get("sign2")))
    for asp in (prog1_to_natal2 or []):
        if asp.get("planet1"):
            layers['p1_progressed']['planets'].setdefault(asp["planet1"], from_sign_en(asp.get("sign1")))
        if asp.get("planet2"):
            layers['p2_natal']['planets'].setdefault(asp["planet2"], from_sign_en(asp.get("sign2")))
    for asp in (prog2_to_natal1 or []):
        if asp.get("planet1"):
            layers['p2_progressed']['planets'].setdefault(asp["planet1"], from_sign_en(asp.get("sign1")))
        if asp.get("planet2"):
            layers['p1_natal']['planets'].setdefault(asp["planet2"], from_sign_en(asp.get("sign2")))

    return layers

async def _prepare_progressed_synastry_analysis(
    progressed_synastry: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 2,
    mode: str = 'advanced',
    relationship_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Shared prep for progressed_synastry_analysis and its streaming twin
    (progressed_synastry_analysis_stream): everything from "no prompt yet" to
    "prompt ready for one LLM call". Split out by
    plans/streaming-rollout-synastry-progressions-transits.md (step 4б) —
    same principle as the other three _prepare_X helpers — behavior
    unchanged, this is the same code progressed_synastry_analysis used to run
    inline. Also returns p1/p2/layer1/prog1_to_natal2/prog2_to_natal1/dynamics
    — everything finalize's detect-only checks need beyond prompt.

    AI analysis of progressed synastry — three layers:
      1) progressed synastry (progr A ↔ progr B)
      2) overlay onto natal (progr A → natal B and vice versa)
      3) dynamics relative to natal synastry
    Priority book — Brady "The Eagle and the Lark" (id=29, forecasting).
    """
    import asyncio
    import time as _time
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_templates import get_template, get_relationship_context_prompt

    # TEMPORARY — timing added to check whether the Пункт-1 dedup
    # (prompt-size cut) moves LLM latency at all; remove once answered.
    # See app/services/specs/progressed_synastry_rag_prompt_reduction_plan.md.
    _t_start = _time.perf_counter()

    adapter = get_llm_adapter()

    p1 = progressed_synastry.get("person1", {})
    p2 = progressed_synastry.get("person2", {})
    _default_names = {
        'ru': ("первый партнёр", "второй партнёр"),
        'uk': ("перший партнер", "другий партнер"),
        'en': ("the first partner", "the second partner"),
    }
    _dn1, _dn2 = _default_names.get(language, _default_names['en'])
    name1 = p1.get("name") or _dn1
    name2 = p2.get("name") or _dn2

    layer1 = progressed_synastry.get("progressed_synastry_aspects", [])
    cross = progressed_synastry.get("cross_overlay", {})
    prog1_to_natal2 = cross.get("prog1_to_natal2", [])
    prog2_to_natal1 = cross.get("prog2_to_natal1", [])
    dynamics = progressed_synastry.get("dynamics", {})

    # --- Step 1: RAG search (priority book id=29, predictive) ---
    async def search_aspect(asp: Dict, kind: str) -> tuple:
        p_a = asp.get("planet1", "")
        p_b = asp.get("planet2", "")
        asp_type = asp.get("aspect", "")
        query = f"progressed {p_a.lower()} {asp_type.lower()} {p_b.lower()} synastry relationship"
        chunks = await search_chunks_priority_book(query, PROGRESSIONS_PRIORITY_BOOK_ID, top_k_priority=3, top_k_others=2)
        return f"[{kind}] {p_a} {asp_type} {p_b}", chunks

    async def search_lunar(person_label: str, phase: str) -> tuple:
        if not phase:
            return f"Lunar {person_label}", []
        chunks = await search_chunks_priority_book(
            f"progressed moon {phase.lower()} relationship synastry",
            PROGRESSIONS_PRIORITY_BOOK_ID, top_k_priority=2, top_k_others=top_k_per_book
        )
        return f"Progressed Moon ({person_label}): {phase}", chunks

    # Search the most exact aspects of each layer (limiting the number of RPCs)
    tasks = []
    for asp in layer1[:6]:
        tasks.append(search_aspect(asp, "L1"))
    for asp in prog1_to_natal2[:3]:
        tasks.append(search_aspect(asp, "L2"))
    for asp in prog2_to_natal1[:3]:
        tasks.append(search_aspect(asp, "L2"))
    ph1 = (p1.get("lunar_phase") or {}).get("phase", "")
    ph2 = (p2.get("lunar_phase") or {}).get("phase", "")
    tasks.append(search_lunar(name1, ph1))
    tasks.append(search_lunar(name2, ph2))

    print(f"[progressed_synastry_analysis] Parallel RAG: {len(tasks)} queries")
    results = await asyncio.gather(*tasks, return_exceptions=True)
    # Dedup chunks repeated across the 14 queries (same book id=29 searched
    # by many semantically-adjacent aspect queries) — see
    # specs/progressed_synastry_rag_prompt_reduction_plan.md, Пункт 1. Search
    # itself is unaffected: every RPC above still ran, this only prevents the
    # same chunk being pasted into books_content more than once.
    sections = [r for r in results if not isinstance(r, Exception)]
    sections = dedup_chunk_sections(sections)
    _t_rag = _time.perf_counter()  # TEMPORARY, see note above

    # --- Step 2: Format aspects by layer ---
    # partner_markers=True is used ONLY for layer1 (progressed A <-> progressed
    # B) — the one layer where "progressed"/"natal" wording can't tell the two
    # partners apart (see app/services/INSIGHTS.md, 2026-08-01 "Chose NOT to
    # run aspect-type fabrication checking... on layer 1"). Tags "Партнёр 1"/
    # "Партнёр 2" mirror synastry_service.py's _prepare_synastry_analysis
    # ("ПАРТНЕР1:"/"ПАРТНЕР2:" in its aspects_list) — same wording
    # find_fabricated_aspect_types/attribute_header_planets_to_partners
    # already know how to read, reused as-is for layer1's fabrication check
    # below instead of writing a new attribution function.
    _partner_tags = {
        'ru': ("Партнёр 1", "Партнёр 2"),
        'uk': ("Партнер 1", "Партнер 2"),
        'en': ("Partner 1", "Partner 2"),
    }
    _p1_tag, _p2_tag = _partner_tags.get(language, _partner_tags['en'])

    def fmt(asp: Dict, cross_houses: bool = False, partner_markers: bool = False) -> str:
        p_a = _planet_display(asp.get("planet1", "?"), language)
        p_b = _planet_display(asp.get("planet2", "?"), language)
        orb_val = asp.get("orb", "?")
        # Partner tag sits in the SAME parenthetical as the sign, right after
        # the planet — not before it. attribute_header_planets_to_partners
        # (synastry_service.py) only accepts a marker that comes AT OR AFTER
        # the planet's position in the header; putting it before would never
        # match. This also mirrors how the sign already reliably survives
        # into the model's own text (same bracket, proven pattern) instead of
        # introducing a new one for the partner tag alone.
        tag1 = f"{_p1_tag}, " if partner_markers else ""
        tag2 = f"{_p2_tag}, " if partner_markers else ""
        if language == 'ru':
            sign1 = asp.get('sign1_ru', asp.get('sign1', '?'))
            sign2 = asp.get('sign2_ru', asp.get('sign2', '?'))
            asp_name = asp.get("aspect_ru", asp.get("aspect", "?"))
            applying_str = "набирает силу" if asp.get("applying") else "завершается"
            base = f"{p_a} ({tag1}{sign1}) {asp_name} {p_b} ({tag2}{sign2}) — орб {orb_val}°, {applying_str}"
        elif language == 'uk':
            sign1 = asp.get('sign1_uk', asp.get('sign1', '?'))
            sign2 = asp.get('sign2_uk', asp.get('sign2', '?'))
            asp_name = asp.get("aspect_uk", asp.get("aspect", "?"))
            applying_str = "аплікуючий" if asp.get("applying") else "сепаруючий"
            base = f"{p_a} ({tag1}{sign1}) {asp_name} {p_b} ({tag2}{sign2}) — орбіс {orb_val}°, {applying_str}"
        else:
            sign1 = asp.get('sign1', '?')
            sign2 = asp.get('sign2', '?')
            asp_name = asp.get("aspect", "?")
            applying_str = "gaining strength" if asp.get("applying") else "wrapping up"
            base = f"{p_a} ({tag1}{sign1}) {asp_name} {p_b} ({tag2}{sign2}) — orb {orb_val}°, {applying_str}"
        h1 = asp.get("planet1_house_in_2")
        h2 = asp.get("planet2_house_in_1")
        houses = []
        house_word = "дом" if language == 'ru' else "будинок" if language == 'uk' else "house"
        if h1:
            houses.append(f"{p_a}→{house_word} {h1}")
        if h2:
            houses.append(f"{p_b}→{house_word} {h2}")
        if houses:
            base += " (" + ", ".join(houses) + ")"
        return base

    L = {
        'ru': {
            'l1': f"【СЛОЙ 1 — Прогрессивная синастрия: Партнёр 1 = {name1} ↔ Партнёр 2 = {name2}】",
            'l2a': f"【СЛОЙ 2 — Прогрессии {name1} → натальная карта {name2}】",
            'l2b': f"【СЛОЙ 2 — Прогрессии {name2} → натальная карта {name1}】",
            'l3new': "【СЛОЙ 3 — НОВЫЕ аспекты (появились в прогрессии)】",
            'l3fade': "【СЛОЙ 3 — Натальные аспекты, сейчас НЕ активные】",
            'none': "(нет точных аспектов)",
        },
        'en': {
            'l1': f"【LAYER 1 — Progressed synastry: Partner 1 = {name1} <-> Partner 2 = {name2}】",
            'l2a': f"【LAYER 2 — {name1}'s progressions → {name2}'s natal chart】",
            'l2b': f"【LAYER 2 — {name2}'s progressions → {name1}'s natal chart】",
            'l3new': "【LAYER 3 — NEW aspects (appeared in progression)】",
            'l3fade': "【LAYER 3 — Natal aspects NOT active now】",
            'none': "(no exact aspects)",
        },
        'uk': {
            'l1': f"【ШАР 1 — Прогресивна синастрія: Партнер 1 = {name1} ↔ Партнер 2 = {name2}】",
            'l2a': f"【ШАР 2 — Прогресії {name1} → натальна карта {name2}】",
            'l2b': f"【ШАР 2 — Прогресії {name2} → натальна карта {name1}】",
            'l3new': "【ШАР 3 — НОВІ аспекти (з'явилися в прогресії)】",
            'l3fade': "【ШАР 3 — Натальні аспекти, зараз НЕ активні】",
            'none': "(немає точних аспектів)",
        }
    }[language if language in ('ru', 'en', 'uk') else 'en']

    def block(title, items, **kw):
        body = "\n".join(fmt(a, **kw) for a in items) if items else L['none']
        return f"{title}\n{body}"

    aspects_list = "\n\n".join([
        block(L['l1'], layer1, cross_houses=True, partner_markers=True),
        block(L['l2a'], prog1_to_natal2),
        block(L['l2b'], prog2_to_natal1),
        block(L['l3new'], dynamics.get("new_aspects", []), cross_houses=True),
        block(L['l3fade'], dynamics.get("faded_aspects", [])),
    ])

    # --- Step 3: Book excerpts (post-dedup — see `sections` above) ---
    books_content = ""
    for label, chunks in sections:
        if chunks:
            books_content += f"\n\n【{label}】\n"
            for i, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")[:700]
                book_title = chunk.get("book_title", "")
                books_content += f"[{i}] ({book_title}):\n{text}\n"

    # --- Step 4: Assemble the prompt ---
    template = get_template("progressed_synastry", language, mode)
    # Same relationship_context mechanism as full_synastry_analysis_v2
    # (synastry_service.py:794) — reused as-is rather than duplicated, since
    # RELATIONSHIP_CONTEXT_PROMPTS' wording isn't synastry-specific. Without
    # this the prompt always wrote in a romantic-couple frame regardless of
    # what relationship_context the request carried.
    context_prompt = get_relationship_context_prompt(relationship_context, language) if relationship_context else ""
    if context_prompt:
        template = template + context_prompt
    prompt = template.replace("{aspects_list}", aspects_list).replace("{books_content}", books_content)

    # Partner data
    _partner_headers = {
        'ru': "=== ДАННЫЕ ПАРТНЁРОВ ===",
        'uk': "=== ДАНІ ПАРТНЕРІВ ===",
        'en': "=== PARTNER DATA ===",
    }
    prompt += f"\n\n{_partner_headers.get(language, _partner_headers['en'])}"
    for label, person in ((name1, p1), (name2, p2)):
        lp = person.get("lunar_phase") or {}
        phase_key = "phase_ru" if language == 'ru' else "phase_uk" if language == 'uk' else "phase"
        phase = lp.get(phase_key, lp.get("phase", "?"))
        ns = person.get("natal_summary") or {}
        age_word = "вік" if language == 'uk' else "age" if language == 'en' else "возраст"
        moon_phase_word = "Прогресивна місячна фаза" if language == 'uk' \
            else "Progressed lunar phase" if language == 'en' else "Прогрессивная лунная фаза"
        prog_label_prefix = "Прогр." if language != 'en' else "Prog."
        prompt += f"\n\n{label} ({age_word} {person.get('age_years', '?')}):"
        prompt += f"\n  {moon_phase_word}: {phase}"
        prog_planets = person.get("progressed_planets", {})
        for key in ("Moon", "Sun", "Venus", "Mars", "Mercury"):
            pd = prog_planets.get(key)
            if pd:
                sign_key = "sign_ru" if language == 'ru' else "sign_uk" if language == 'uk' else "sign"
                sign = pd.get(sign_key, pd.get("sign", "?"))
                rx = " R" if pd.get("is_retrograde") else ""
                prompt += f"\n  {prog_label_prefix}{_planet_display(key, language)}: {sign}{rx}"

    dyn = dynamics
    _dyn_labels = {
        'ru': "=== ДИНАМИКА: натальная синастрия {n} аспектов → прогрессивная {p} ===",
        'uk': "=== ДИНАМІКА: натальна синастрія {n} аспектів → прогресивна {p} ===",
        'en': "=== DYNAMICS: natal synastry {n} aspects → progressed {p} ===",
    }
    _dyn_tmpl = _dyn_labels.get(language, _dyn_labels['en'])
    prompt += "\n\n" + _dyn_tmpl.format(n=dyn.get('natal_total', '?'), p=dyn.get('progressed_total', '?'))

    _t_prompt = _time.perf_counter()  # TEMPORARY, see note above

    return {
        'adapter': adapter,
        'prompt': prompt,
        'p1': p1,
        'p2': p2,
        'layer1': layer1,
        'prog1_to_natal2': prog1_to_natal2,
        'prog2_to_natal1': prog2_to_natal1,
        'dynamics': dynamics,
        'timings': {'t_start': _t_start, 't_rag': _t_rag, 't_prompt': _t_prompt},  # TEMPORARY
    }

async def progressed_synastry_analysis(
    progressed_synastry: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 2,
    mode: str = 'advanced',
    relationship_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    AI analysis of progressed synastry — RAG search + prompt assembly via
    _prepare_progressed_synastry_analysis, one final LLM call, then the
    anti-fabrication pass: fabricated planet positions are detected AND fixed
    (fix_fabricated_positions_layered, mirroring progressions_analysis);
    fabricated aspect types are detected only, for both layer 1 (partner-tag
    attribution — see fmt()'s partner_markers) and layer 2 (progressed/natal
    marker attribution) — see plans/progressed-synastry-validation-gaps.md.
    """
    import time as _time  # TEMPORARY, see _prepare_progressed_synastry_analysis note

    prep = await _prepare_progressed_synastry_analysis(progressed_synastry, language, top_k_per_book, mode, relationship_context)
    adapter = prep['adapter']
    prompt = prep['prompt']
    p1 = prep['p1']
    p2 = prep['p2']
    layer1 = prep['layer1']
    prog1_to_natal2 = prep['prog1_to_natal2']
    prog2_to_natal1 = prep['prog2_to_natal1']
    dynamics = prep['dynamics']
    _t_start = prep['timings']['t_start']
    _t_rag = prep['timings']['t_rag']
    _t_prompt = prep['timings']['t_prompt']

    # --- Step 5: LLM ---
    print(f"[progressed_synastry_analysis] Final prompt ~{len(prompt)//4} tokens")
    try:
        full_analysis = await adapter.generate(prompt, language)
        _t_llm = _time.perf_counter()  # TEMPORARY

        if language in ('ru', 'en', 'uk'):
            _fabrication_layers = _collect_progressed_synastry_layers(
                p1, p2, layer1, prog1_to_natal2, prog2_to_natal1
            )
            position_issues = find_fabricated_positions_layered(
                full_analysis, _fabrication_layers, language=language
            )
            if position_issues.get('fabricated'):
                print(f"[progressed_synastry_analysis] Fabricated positions detected (not fixed): {position_issues['fabricated']}")
            else:
                print("[progressed_synastry_analysis] Position check: OK, no fabricated positions")

            full_analysis, _ = fix_fabricated_positions_layered(
                full_analysis, _fabrication_layers, language=language
            )

            # Aspect type — LAYER 2 (prog.→natal): the prompt there writes
            # "прогрессивная"/"натальная" next to the planet, so
            # find_fabricated_aspect_types_layered's progressed/natal marker
            # axis attributes each side correctly.
            cross_aspects = (prog1_to_natal2 or []) + (prog2_to_natal1 or [])
            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, cross_aspects, language=language, layer_keys=('progressed', 'natal')
            )

            # Aspect type — LAYER 1 (prog.↔prog. between the two partners):
            # "progressed"/"natal" wording can't distinguish the partners here
            # (both sides are "progressed") — fixed by tagging each planet
            # with "Партнёр 1/2" in the aspects_list (see fmt()'s
            # partner_markers above) and reusing synastry_service.py's own
            # partner-marker attribution as-is, since the tag wording matches
            # what it already looks for. Closes the gap documented in
            # app/services/INSIGHTS.md (2026-08-01, "Chose NOT to run
            # aspect-type fabrication checking... on layer 1").
            from app.services.synastry_service import find_fabricated_aspect_types as _find_fab_aspect_types_partner
            fabricated_layer1_aspects = _find_fab_aspect_types_partner(full_analysis, layer1 or [], language=language)

            if fabricated_aspects or fabricated_layer1_aspects:
                print(f"[progressed_synastry_analysis] Fabricated aspect types detected — layer 2: {fabricated_aspects}, layer 1: {fabricated_layer1_aspects}")
            else:
                print("[progressed_synastry_analysis] Aspect-type check: OK, no fabricated aspect types (layer 1 + layer 2)")

            all_aspects = (layer1 or []) + cross_aspects
            undercovered = find_undercovered_aspects_generic(full_analysis, all_aspects, language=language)
            if undercovered:
                print(f"[progressed_synastry_analysis] Undercovered aspects detected: {undercovered}")
            else:
                print(f"[progressed_synastry_analysis] Coverage check: OK, all {len(all_aspects)} aspects covered")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[progressed_synastry_analysis] LLM error: {e}")

    # TEMPORARY timing block — remove together with the marks above once the
    # dedup-vs-latency question is answered.
    _t_llm = locals().get('_t_llm', _t_prompt)
    _t_end = _time.perf_counter()
    print(
        "[timing] progressed_synastry_analysis"
        f" rag={_t_rag - _t_start:.1f}s"
        f" build={_t_prompt - _t_rag:.1f}s"
        f" llm={_t_llm - _t_prompt:.1f}s"
        f" verify={_t_end - _t_llm:.1f}s"
        f" total={_t_end - _t_start:.1f}s"
    )

    return {
        "analysis": full_analysis,
        "progressed_synastry_summary": {
            "period": progressed_synastry.get("period"),
            "person1_name": p1.get("name"),
            "person2_name": p2.get("name"),
            "person1_lunar_phase": (p1.get("lunar_phase") or {}).get("phase"),
            "person2_lunar_phase": (p2.get("lunar_phase") or {}).get("phase"),
            "layer1_aspects": len(layer1),
            "new_aspects": len(dynamics.get("new_aspects", [])),
            "faded_aspects": len(dynamics.get("faded_aspects", [])),
        },
        "language": language,
        "version": "progressed_synastry_v1"
    }

async def progressed_synastry_analysis_stream(
    progressed_synastry: Dict[str, Any],
    language: str = "ru",
    top_k_per_book: int = 2,
    mode: str = 'advanced',
    relationship_context: Optional[str] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of progressed_synastry_analysis
    (plans/streaming-rollout-synastry-progressions-transits.md, step 4в). Same
    prep (_prepare_progressed_synastry_analysis), same finalize pipeline —
    only the delivery differs.

    `fix_fn` applies fix_fabricated_positions_layered against
    `_fabrication_layers`, mirroring the non-stream path and the natal/
    progressions/transits streaming callers — no longer an identity stub
    (see plans/progressed-synastry-validation-gaps.md, Этап 1). Aspect-type
    fabrication stays detect-only for both layers (layer 1 via partner-tag
    attribution, layer 2 via progressed/natal marker attribution) — same as
    the non-stream twin.
    """
    import time as _time  # TEMPORARY, see _prepare_progressed_synastry_analysis note

    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_progressed_synastry_analysis(progressed_synastry, language, top_k_per_book, mode, relationship_context)
    adapter = prep['adapter']
    prompt = prep['prompt']
    p1 = prep['p1']
    p2 = prep['p2']
    layer1 = prep['layer1']
    prog1_to_natal2 = prep['prog1_to_natal2']
    prog2_to_natal1 = prep['prog2_to_natal1']
    dynamics = prep['dynamics']
    _t_start = prep['timings']['t_start']
    _t_rag = prep['timings']['t_rag']
    _t_prompt = prep['timings']['t_prompt']
    _t_llm_end = None  # TEMPORARY

    # Computed here (not inside finalize) so fix_fn — a separate closure
    # defined below, called incrementally per-paragraph by
    # stream_verified_analysis BEFORE finalize ever runs — can also see it.
    # Bug fixed 2026-08-22: this used to be computed only inside finalize,
    # so fix_fn's reference to it raised NameError on the very first
    # paragraph of every real streamed request (caught via a live traceback,
    # not by the earlier synthetic-only testing — see
    # app/services/INSIGHTS.md). Mirrors full_chart_analysis_v2_stream's
    # `layers = prep['layers']` placement.
    _fabrication_layers = _collect_progressed_synastry_layers(
        p1, p2, layer1, prog1_to_natal2, prog2_to_natal1
    )

    async def finalize(buffer: str, released: str) -> Dict[str, Any]:
        nonlocal _t_llm_end
        _t_llm_end = _time.perf_counter()  # TEMPORARY
        full_analysis = buffer
        if language in ('ru', 'en', 'uk'):
            position_issues = find_fabricated_positions_layered(
                full_analysis, _fabrication_layers, language=language
            )
            if position_issues.get('fabricated'):
                print(f"[progressed_synastry_analysis_stream] Fabricated positions detected (not fixed): {position_issues['fabricated']}")
            else:
                print("[progressed_synastry_analysis_stream] Position check: OK, no fabricated positions")

            full_analysis, _ = fix_fabricated_positions_layered(
                full_analysis, _fabrication_layers, language=language
            )

            cross_aspects = (prog1_to_natal2 or []) + (prog2_to_natal1 or [])
            fabricated_aspects = find_fabricated_aspect_types_layered(
                full_analysis, cross_aspects, language=language, layer_keys=('progressed', 'natal')
            )

            # Layer 1 aspect-type check — see the non-stream twin's comment
            # for why this reuses synastry_service.py's partner-marker
            # attribution instead of the progressed/natal marker axis.
            from app.services.synastry_service import find_fabricated_aspect_types as _find_fab_aspect_types_partner
            fabricated_layer1_aspects = _find_fab_aspect_types_partner(full_analysis, layer1 or [], language=language)

            if fabricated_aspects or fabricated_layer1_aspects:
                print(f"[progressed_synastry_analysis_stream] Fabricated aspect types detected — layer 2: {fabricated_aspects}, layer 1: {fabricated_layer1_aspects}")
            else:
                print("[progressed_synastry_analysis_stream] Aspect-type check: OK, no fabricated aspect types (layer 1 + layer 2)")

            all_aspects = (layer1 or []) + cross_aspects
            undercovered = find_undercovered_aspects_generic(full_analysis, all_aspects, language=language)
            if undercovered:
                print(f"[progressed_synastry_analysis_stream] Undercovered aspects detected: {undercovered}")
            else:
                print(f"[progressed_synastry_analysis_stream] Coverage check: OK, all {len(all_aspects)} aspects covered")

        if not full_analysis.startswith(released):
            # fix_fn now applies fix_fabricated_positions_layered incrementally
            # per paragraph; `released` is the fully corrected prefix, and
            # `full_analysis` (below) has also been fixed in this same finalize
            # call, so the prefix check remains valid.
            print(
                "[stream_mismatch] progressed_synastry_analysis_stream"
                f" released={released!r} canonical={full_analysis!r}"
            )

        return {
            "analysis": full_analysis,
            "progressed_synastry_summary": {
                "period": progressed_synastry.get("period"),
                "person1_name": p1.get("name"),
                "person2_name": p2.get("name"),
                "person1_lunar_phase": (p1.get("lunar_phase") or {}).get("phase"),
                "person2_lunar_phase": (p2.get("lunar_phase") or {}).get("phase"),
                "layer1_aspects": len(layer1),
                "new_aspects": len(dynamics.get("new_aspects", [])),
                "faded_aspects": len(dynamics.get("faded_aspects", [])),
            },
            "language": language,
            "version": "progressed_synastry_v1"
        }

    # Real fix function — applies fix_fabricated_positions_layered to the
    # finalized analysis text, mirroring the non-stream path. Previously
    # identity stub (lambda text: (text, [])), see
    # plans/progressed-synastry-validation-gaps.md:62 — consensus was that
    # this was a deliberate design choice for parity, but now both paths
    # apply the same fix, so consistency is maintained.
    fix_fn = lambda text: fix_fabricated_positions_layered(text, _fabrication_layers, language=language)

    print(f"[progressed_synastry_analysis_stream] Final prompt ~{len(prompt)//4} tokens")
    yield {"event": "stage", "data": {"stage": "generating"}}

    async for event in stream_verified_analysis(adapter, prompt, language, fix_fn, finalize):
        yield event

    # TEMPORARY timing block — remove together with the marks above once the
    # dedup-vs-latency question is answered. finalize() runs inside
    # stream_verified_analysis, so _t_llm_end is set by the time the loop
    # above finishes (falls back to _t_prompt if the stream errored before
    # ever calling finalize).
    _t_end = _time.perf_counter()
    _t_llm = _t_llm_end if _t_llm_end is not None else _t_prompt
    print(
        "[timing] progressed_synastry_analysis_stream"
        f" rag={_t_rag - _t_start:.1f}s"
        f" build={_t_prompt - _t_rag:.1f}s"
        f" llm={_t_llm - _t_prompt:.1f}s"
        f" verify={_t_end - _t_llm:.1f}s"
        f" total={_t_end - _t_start:.1f}s"
    )

async def _prepare_progressed_synastry_aspect_analysis(
    planet1: str,
    planet2: str,
    aspect_name: str,
    layer: str,
    aspect_name_ru: Optional[str] = None,
    aspect_name_uk: Optional[str] = None,
    applying: Optional[bool] = None,
    house1: Optional[int] = None,
    house2: Optional[int] = None,
    partner1_name: Optional[str] = None,
    partner2_name: Optional[str] = None,
    language: str = "ru",
    mode: str = "advanced",
) -> Dict[str, Any]:
    """
    Shared prep for analyze_progressed_synastry_aspect and its streaming twin
    (analyze_progressed_synastry_aspect_stream): RAG search + prompt build,
    same split as _prepare_natal_analysis/_prepare_synastry_analysis —
    behavior unchanged, this is the same code
    analyze_progressed_synastry_aspect used to run inline.
    """
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_templates import get_template
    from app.services.prompt_templates.progressed_synastry import PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT

    lang = normalize_language(language)

    aspect_display = aspect_name
    if lang == 'ru' and aspect_name_ru:
        aspect_display = aspect_name_ru
    elif lang == 'uk' and aspect_name_uk:
        aspect_display = aspect_name_uk

    query = f"progressed {planet1.lower()} {aspect_display.lower()} {planet2.lower()} synastry relationship"
    chunks = await search_chunks_priority_book(query, PROGRESSIONS_PRIORITY_BOOK_ID, top_k_priority=4, top_k_others=4)

    layer_ctx_by_lang = PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT.get(lang, PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT['en'])
    layer_context = layer_ctx_by_lang.get(layer, layer_ctx_by_lang['progressed'])

    _labels = {
        'ru': {'partner': 'Партнёр', 'aspect': 'Аспект', 'applying': 'набирает силу', 'separating': 'завершается', 'house': 'дом'},
        'uk': {'partner': 'Партнер', 'aspect': 'Аспект', 'applying': 'набирає силу', 'separating': 'завершується', 'house': 'будинок'},
        'en': {'partner': 'Partner', 'aspect': 'Aspect', 'applying': 'gaining strength', 'separating': 'wrapping up', 'house': 'house'},
    }[lang if lang in ('ru', 'uk') else 'en']

    p1_label = partner1_name or f"{_labels['partner']} 1"
    p2_label = partner2_name or f"{_labels['partner']} 2"

    aspect_lines = [f"{p1_label}: {planet1}", f"{_labels['aspect']}: {aspect_display}", f"{p2_label}: {planet2}"]
    if applying is not None:
        aspect_lines.append(_labels['applying'] if applying else _labels['separating'])
    if house1:
        aspect_lines.append(f"{planet1} → {p2_label} {_labels['house']} {house1}")
    if house2:
        aspect_lines.append(f"{planet2} → {p1_label} {_labels['house']} {house2}")
    aspect_data = "\n".join(aspect_lines)

    books_content = ""
    for i, chunk in enumerate(chunks, 1):
        text = chunk.get("text", "")[:700]
        book_title = chunk.get("book_title", "")
        books_content += f"[{i}] ({book_title}):\n{text}\n\n"
    if not books_content:
        books_content = {
            'ru': "В библиотеке не найдено специфических фрагментов по этому аспекту.",
            'uk': "У бібліотеці не знайдено специфічних фрагментів щодо цього аспекту.",
            'en': "No specific fragments found in the library for this aspect.",
        }[lang if lang in ('ru', 'uk') else 'en']

    template = get_template("progressed_synastry_aspect", language, mode)
    prompt = (template
              .replace("{layer_context}", layer_context)
              .replace("{aspect_data}", aspect_data)
              .replace("{books_content}", books_content))

    return {
        "prompt": prompt,
        "chunks": chunks,
        "adapter": get_llm_adapter(),
    }

async def analyze_progressed_synastry_aspect(
    planet1: str,
    planet2: str,
    aspect_name: str,
    layer: str,
    aspect_name_ru: Optional[str] = None,
    aspect_name_uk: Optional[str] = None,
    orb: float = 0.0,
    applying: Optional[bool] = None,
    house1: Optional[int] = None,
    house2: Optional[int] = None,
    partner1_name: Optional[str] = None,
    partner2_name: Optional[str] = None,
    language: str = "ru",
    mode: str = "advanced",
) -> Dict[str, Any]:
    """
    Analysis of a SINGLE progressed-synastry aspect (click on an aspect in the
    frontend). Modeled on: analyze_synastry_aspect (synastry_service.py:534).
    See specs/progressed_synastry_aspect_click_plan.md.

    layer — which of the five blocks in the /progressed-synastry response the
    aspect was taken from: 'progressed' (Layer 1, progr↔progr),
    'prog1_to_natal2'/'prog2_to_natal1' (Layer 2, cross-overlay),
    'new'/'faded' (Layer 3, dynamics) — determines the wording of the
    breakdown via PROGRESSED_SYNASTRY_ASPECT_LAYER_CONTEXT.

    house1/house2 — the house that planet1/planet2 falls into on the OTHER
    partner's chart (like planet1_house_in_2/planet2_house_in_1 in the main
    breakdown).
    """
    prep = await _prepare_progressed_synastry_aspect_analysis(
        planet1, planet2, aspect_name, layer, aspect_name_ru, aspect_name_uk,
        applying, house1, house2, partner1_name, partner2_name, language, mode
    )
    analysis = await prep["adapter"].generate(prep["prompt"], language)

    return {
        "planet1": planet1,
        "planet2": planet2,
        "aspect": aspect_name,
        "aspect_ru": aspect_name_ru,
        "aspect_uk": aspect_name_uk,
        "orb": orb,
        "layer": layer,
        "analysis": analysis,
        "relevant_chunks": prep["chunks"],
    }

async def analyze_progressed_synastry_aspect_stream(
    planet1: str,
    planet2: str,
    aspect_name: str,
    layer: str,
    aspect_name_ru: Optional[str] = None,
    aspect_name_uk: Optional[str] = None,
    orb: float = 0.0,
    applying: Optional[bool] = None,
    house1: Optional[int] = None,
    house2: Optional[int] = None,
    partner1_name: Optional[str] = None,
    partner2_name: Optional[str] = None,
    language: str = "ru",
    mode: str = "advanced",
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of analyze_progressed_synastry_aspect.
    analyze_progressed_synastry_aspect never runs an anti-fabrication fix
    pass on its output (single generate() call, text returned as-is) —
    fix_fn is therefore the identity function, same as
    progressed_synastry_analysis_stream's `lambda text: (text, [])`. Still
    routed through stream_verified_analysis rather than a bespoke raw-relay
    path, so the SSE event contract (stage/delta/final/error) matches every
    other streaming endpoint.
    """
    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_progressed_synastry_aspect_analysis(
        planet1, planet2, aspect_name, layer, aspect_name_ru, aspect_name_uk,
        applying, house1, house2, partner1_name, partner2_name, language, mode
    )

    async def finalize(buffer: str, released: str) -> Dict[str, Any]:
        return {
            "planet1": planet1,
            "planet2": planet2,
            "aspect": aspect_name,
            "aspect_ru": aspect_name_ru,
            "aspect_uk": aspect_name_uk,
            "orb": orb,
            "layer": layer,
            "analysis": buffer,
            "relevant_chunks": prep["chunks"],
        }

    fix_fn = lambda text: (text, [])

    yield {"event": "stage", "data": {"stage": "generating"}}
    async for event in stream_verified_analysis(prep["adapter"], prep["prompt"], language, fix_fn, finalize):
        yield event


# ============================================================
# PROGRESSED SYNASTRY CHAT
# ============================================================

async def _prepare_chat_with_progressed_synastry_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru",
    relationship_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Shared prep for chat_with_progressed_synastry_astrologer and its
    streaming twin: RAG search (priority book id=29, same as
    _prepare_progressed_synastry_analysis) + messages build. Mirrors
    synastry_service.py's _prepare_chat_with_synastry_astrologer, but reads
    the progressed_synastry-shaped chart_data — the same dict
    calculate_progressed_synastry/the /analysis/progressed-synastry endpoint
    returns (person1, person2, progressed_synastry_aspects, cross_overlay,
    dynamics) — instead of a flat two-person natal synastry chart (chart1/
    chart2/aspects/overlays), and frames the system prompt around the
    PROGRESSED synastry rather than "this couple's synastry".
    """
    from app.services.llm_adapter import get_llm_adapter
    from app.services.prompt_templates import get_relationship_context_prompt

    adapter = get_llm_adapter()
    lang = language if language in ('ru', 'en', 'uk') else 'en'

    p1 = chart_data.get("person1", {}) or {}
    p2 = chart_data.get("person2", {}) or {}
    _default_names = {
        'ru': ("первый партнёр", "второй партнёр"),
        'uk': ("перший партнер", "другий партнер"),
        'en': ("the first partner", "the second partner"),
    }
    name1 = p1.get("name") or _default_names[lang][0]
    name2 = p2.get("name") or _default_names[lang][1]

    layer1 = chart_data.get("progressed_synastry_aspects", []) or []
    cross = chart_data.get("cross_overlay", {}) or {}
    prog1_to_natal2 = cross.get("prog1_to_natal2", []) or []
    prog2_to_natal1 = cross.get("prog2_to_natal1", []) or []

    chunks = await search_chunks_priority_book(question, PROGRESSIONS_PRIORITY_BOOK_ID, top_k_priority=6, top_k_others=4)

    books_context = ""
    if chunks:
        books_context = "\n=== FRAGMENTS ON THE QUESTION ===\n"
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text", "")[:600]
            book_title = chunk.get("book_title", "")
            books_context += f"[{i}] ({book_title}):\n{text}\n"
    else:
        books_context = {
            'ru': "В библиотеке не найдено релевантных фрагментов по этому вопросу. Используйте общие принципы прогрессивной синастрии.",
            'uk': "У бібліотеці не знайдено релевантних фрагментів щодо цього питання. Використовуйте загальні принципи прогресивної синастрії.",
            'en': "No relevant fragments found in the library for this question. Use general progressed-synastry principles.",
        }[lang]

    def fmt_short(asp: Dict) -> str:
        p_a = _planet_display(asp.get("planet1", "?"), language)
        p_b = _planet_display(asp.get("planet2", "?"), language)
        asp_name = _localized(asp, "aspect", language, asp.get("aspect", "?"))
        orb_val = asp.get("orb", "?")
        return f"{p_a} {asp_name} {p_b} — orb {orb_val}°"

    def block(items: List[Dict], n: int = 8) -> str:
        items = items[:n]
        return "\n".join(fmt_short(a) for a in items) if items else "—"

    layer1_str = block(layer1)
    l2a_str = block(prog1_to_natal2)
    l2b_str = block(prog2_to_natal1)

    context_instruction = get_relationship_context_prompt(relationship_context, language) if relationship_context else ""

    system_prompt = f"""You are a relationship astrologer. You have already done a full analysis of {name1} and {name2}'s PROGRESSED SYNASTRY and now answer questions about it.
{context_instruction}
=== LAYER 1 — Progressed synastry: {name1} <-> {name2} ===
{layer1_str}

=== LAYER 2 — {name1}'s progressions -> {name2}'s natal chart ===
{l2a_str}

=== LAYER 2 — {name2}'s progressions -> {name1}'s natal chart ===
{l2b_str}

=== FULL PROGRESSED SYNASTRY ANALYSIS ===
{full_analysis}

=== KNOWLEDGE FROM ASTROLOGY BOOKS ===
{books_context}

RULES:
- Answer personally — you know this couple's progressed synastry
- Use only {name1} / {name2} — no he/she
- Always distinguish PROGRESSED positions from NATAL positions explicitly — never present one as the other
- Use book fragments as knowledge source but NEVER mention them in the answer
- Do NOT say "fragment [3]", "the book says", "the source mentions"
- Present all insights as your own astrological expertise
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
        "chunks": chunks
    }

async def chat_with_progressed_synastry_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru",
    relationship_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Chat with the astrologer about a progressed synastry. Modeled on
    chat_with_synastry_astrologer (synastry_service.py).
    """
    prep = await _prepare_chat_with_progressed_synastry_astrologer(
        question, chart_data, full_analysis, chat_history, language, relationship_context
    )
    answer = await prep["adapter"].generate_with_messages(prep["messages"], language)

    return {
        "answer": answer,
        "relevant_chunks": prep["chunks"]
    }

async def chat_with_progressed_synastry_astrologer_stream(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru",
    relationship_context: Optional[str] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Streaming twin of chat_with_progressed_synastry_astrologer — typewriter
    delivery for the chat modal. No anti-fabrication fix runs on chat replies
    today (same as the other three chat variants), so this goes through
    stream_chat_reply (raw token relay), not stream_verified_analysis.
    """
    yield {"event": "stage", "data": {"stage": "searching"}}

    prep = await _prepare_chat_with_progressed_synastry_astrologer(
        question, chart_data, full_analysis, chat_history, language, relationship_context
    )

    async def finalize(buffer: str) -> Dict[str, Any]:
        return {
            "answer": buffer,
            "relevant_chunks": prep["chunks"]
        }

    yield {"event": "stage", "data": {"stage": "generating"}}
    async for event in stream_chat_reply(prep["adapter"], prep["messages"], language, finalize):
        yield event
