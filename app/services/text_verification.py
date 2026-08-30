"""Shared dictionaries/regexes for checking LLM text (RU and EN) against real
astrological data — signs, planets, aspects, finding bold
markdown headings.

Split out of synastry_service.py (plan: plans/synastry-aspect-type-verification.md)
so the same check isn't duplicated when it's added for natal charts,
transits, progressions — the dictionaries themselves aren't synastry-specific.

The synastry-specific part (attributing a planet to "Партнёр 1/2" / "Partner N")
doesn't live here — that stays in synastry_service.py; natal/transits don't
have that concept at all.

Russian and English are deliberately asymmetric: Russian declines nouns
by case ("Хирона", "в оппозиции", "секстиле") — hence stems with \\w* and a
separate prepositional->nominative table for signs. English has no cases —
"Moon", "Chiron", "Square" are spelled the same in any position in a
sentence, so there it's just the exact word within \\b boundaries, no stems
and no sign-forms table.
"""
import re
from typing import Any, Dict, List, Optional
from app.services.prompt_templates.languages import normalize_language

# ============================================================
# Russian
# ============================================================

# Prepositional case of zodiac signs ("Луна В РАКЕ") -> nominative ("Рак"),
# how it's stored in chart_data (sign_ru). Planet positions are deterministic —
# we check the LLM's text against this dict instead of trusting the model's word.
SIGN_PREPOSITIONAL_TO_NOMINATIVE = {
    'Овне': 'Овен', 'Тельце': 'Телец', 'Близнецах': 'Близнецы',
    'Раке': 'Рак', 'Льве': 'Лев', 'Деве': 'Дева',
    'Весах': 'Весы', 'Скорпионе': 'Скорпион', 'Стрельце': 'Стрелец',
    'Козероге': 'Козерог', 'Водолее': 'Водолей', 'Рыбах': 'Рыбы',
}

SIGN_NOMINATIVE_TO_PREPOSITIONAL = {v: k for k, v in SIGN_PREPOSITIONAL_TO_NOMINATIVE.items()}

# Stems of Russian planet names — not the exact form, but the start of the
# word, because in the text the planet is declined by case ("Хирона",
# "Северным Узлом"), not in the nominative. \w* picks up the ending.
PLANET_STEM_RU = {
    'Sun': r'Со?лнц\w*', 'Moon': r'Лун\w*', 'Mercury': r'Меркури\w*',
    'Venus': r'Венер\w*', 'Mars': r'Марс\w*', 'Jupiter': r'Юпитер\w*',
    'Saturn': r'Сатурн\w*', 'Uranus': r'Уран\w*', 'Neptune': r'Нептун\w*',
    'Pluto': r'Плутон\w*', 'NorthNode': r'Северн\w*\s+[Уу]з(?:ел\w*|л\w*)',
    'SouthNode': r'Южн\w*\s+[Уу]з(?:ел\w*|л\w*)', 'Chiron': r'Хирон\w*',
    'Lilith': r'Лилит\w*', 'Ascendant': r'Асцендент\w*', 'Vertex': r'Вертекс\w*',
}

# Aspect stems — same reason: "в оппозиции", "Соединение", "секстиле" — are
# different cases of one of five words. Key matches 'aspect' in the data from
# calculate_synastry (astrology_v2.py).
ASPECT_STEM_RU = {
    'Conjunction': r'[Сс]оединени\w*', 'Opposition': r'[Оо]ппозици\w*',
    'Trine': r'[Тт]ригон\w*', 'Square': r'[Кк]вадрат\w*',
    'Sextile': r'[Сс]екстил\w*',
}

# ============================================================
# English
# ============================================================

# English doesn't decline nouns — a sign is written the same way anywhere in
# a sentence (unlike Russian "в Раке"), no separate forms table is needed:
# the word from chart_data.sign and the word in the text match literally.
ZODIAC_SIGNS_EN = {
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
}

# English planet names in the LLM's text match the chart_data.planets keys
# literally (Moon, Chiron, ...) — a translation dict like PLANET_RU isn't needed.
# \b prevents accidental matches inside other words.
PLANET_STEM_EN = {
    'Sun': r'\bSun\b', 'Moon': r'\bMoon\b', 'Mercury': r'\bMercury\b',
    'Venus': r'\bVenus\b', 'Mars': r'\bMars\b', 'Jupiter': r'\bJupiter\b',
    'Saturn': r'\bSaturn\b', 'Uranus': r'\bUranus\b', 'Neptune': r'\bNeptune\b',
    'Pluto': r'\bPluto\b', 'NorthNode': r'\bNorth\s+Node\b',
    'SouthNode': r'\bSouth\s+Node\b', 'Chiron': r'\bChiron\b',
    'Lilith': r'\bLilith\b', 'Ascendant': r'\bAscendant\b', 'Vertex': r'\bVertex\b',
}

ASPECT_STEM_EN = {
    'Conjunction': r'\bConjunction\b', 'Opposition': r'\bOpposition\b',
    'Trine': r'\bTrine\b', 'Square': r'\bSquare\b', 'Sextile': r'\bSextile\b',
}

# ============================================================
# Ukrainian
# ============================================================
# Ukrainian, like Russian, declines nouns by case ("Хірона",
# "в опозиції", "секстилі") — hence stems with \w* and a separate sign-forms
# table (locative -> nominative), the same approach as the RU block above.

# Locative case of zodiac signs ("Місяць У РАКУ") -> nominative ("Рак"),
# how it's stored in chart_data (sign_uk). Verified against real LLM output
# from an LLM (DeepSeek, natal analysis, 2026-07): "Венера у Леві в 7-му домі" —
# the "у Леві" form is confirmed in practice, not just derived theoretically.
SIGN_LOCATIVE_TO_NOMINATIVE_UK = {
    'Овні': 'Овен', 'Тельці': 'Телець', 'Близнюках': 'Близнюки',
    'Раку': 'Рак', 'Леві': 'Лев', 'Діві': 'Діва',
    'Терезах': 'Терези', 'Скорпіоні': 'Скорпіон', 'Стрільці': 'Стрілець',
    'Козерозі': 'Козеріг', 'Водолії': 'Водолій', 'Рибах': 'Риби',
}

# Stems of Ukrainian planet names — the start of the word, because in the
# text the planet is declined ("Хірона", "Північним Вузлом"), not nominative.
# NorthNode/SouthNode: "вузол" has a dropped vowel "о" in the oblique
# cases (вузол -> вузла, вузлі) — the same case as Russian "узел",
# the pattern structure is identical to PLANET_STEM_RU.
PLANET_STEM_UK = {
    'Sun': r'Сонц\w*', 'Moon': r'Місяц\w*', 'Mercury': r'Меркурі\w*',
    'Venus': r'Венер\w*', 'Mars': r'Марс\w*', 'Jupiter': r'Юпітер\w*',
    'Saturn': r'Сатурн\w*', 'Uranus': r'Уран\w*', 'Neptune': r'Нептун\w*',
    'Pluto': r'Плутон\w*', 'NorthNode': r'Північн\w*\s+[Вв]уз(?:ол\w*|л\w*)',
    'SouthNode': r'Південн\w*\s+[Вв]уз(?:ол\w*|л\w*)', 'Chiron': r'Хірон\w*',
    'Lilith': r'Ліліт\w*', 'Ascendant': r'Асцендент\w*', 'Vertex': r'Вертекс\w*',
}

# Aspect stems — the same reason: "в опозиції", "З'єднання", "секстилі".
ASPECT_STEM_UK = {
    'Conjunction': r"[Зз]'?єднан\w*", 'Opposition': r'[Оо]позиці\w*',
    'Trine': r'[Тт]ригон\w*', 'Square': r'[Кк]вадрат\w*',
    'Sextile': r'[Сс]екстил\w*',
}

# ============================================================
# Language-neutral
# ============================================================

# Bold markdown heading — a generic pattern, not specific to either the
# language or synastry aspects; the model uses it to format sections in the natal/transits output too.
_ASPECT_HEADER_RE = re.compile(r"\*\*([^*\n]{1,240})\*\*")


# ============================================================
# Planet display names (RU/EN) — shared across all methods
# ============================================================
# DUPLICATES the same-named dicts in synastry_service.py — not a move:
# synastry_service.py stays fully untouched (it's working, in prod, and its
# code here is deliberately not touched). The reason for duplication instead
# of a shared import is a cycle: synastry_service.py itself imports
# analysis_service.py (search_chunks_all_books, generate_summary), so
# analysis_service.py can't import these constants from synastry_service.py
# directly, and without that import it's simpler to duplicate them here for
# progressions than to refactor synastry. If the two places drift apart in
# planet terminology — that's a deliberate tradeoff of this TЗ, plan:
# app/services/specs/progressions_synastry_pattern_plan.md. Consolidating to
# one source is a separate future task, not part of this TЗ.

PLANET_RU = {
    'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
    'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
    'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
    'Pluto': 'Плутон', 'NorthNode': 'Северный Узел',
    'SouthNode': 'Южный Узел', 'Chiron': 'Хирон',
    'Lilith': 'Лилит', 'Ascendant': 'Асцендент', 'Vertex': 'Вертекс',
}

# English planet names in the LLM's text match these values literally
# (Sun, Moon, ..., "North Node") — unlike PLANET_RU this isn't a translation,
# just a normalized display name (NorthNode -> "North Node").
PLANET_EN = {
    'Sun': 'Sun', 'Moon': 'Moon', 'Mercury': 'Mercury',
    'Venus': 'Venus', 'Mars': 'Mars', 'Jupiter': 'Jupiter',
    'Saturn': 'Saturn', 'Uranus': 'Uranus', 'Neptune': 'Neptune',
    'Pluto': 'Pluto', 'NorthNode': 'North Node',
    'SouthNode': 'South Node', 'Chiron': 'Chiron',
    'Lilith': 'Lilith', 'Ascendant': 'Ascendant', 'Vertex': 'Vertex',
}

PLANET_UK = {
    'Sun': 'Сонце', 'Moon': 'Місяць', 'Mercury': 'Меркурій',
    'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпітер',
    'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
    'Pluto': 'Плутон', 'NorthNode': 'Північний Вузол',
    'SouthNode': 'Південний Вузол', 'Chiron': 'Хірон',
    'Lilith': 'Ліліт', 'Ascendant': 'Асцендент', 'Vertex': 'Вертекс',
}


# ============================================================
# Aspect coverage by text (not by markdown, by prose) — shared
# ============================================================
# Also duplicates synastry_service.py, for the same reason (see above) — not
# a move, synastry_service.py doesn't change.

# Reference phrases instead of a real breakdown ("covered above" etc.) — a
# signal that the aspect is formally mentioned but didn't get its own 200-300
# words (found in live runs on 2026-07-23, see plans/ — the model refers to
# another section instead of covering it again).
_COP_OUT_PHRASES_RU = [
    "разобран", "уже обсужда", "уже опис", "уже сказ", "уже говорили",
    "смотри выше", "см. выше", "как уже", "как мы уже",
]
_COP_OUT_PHRASES_EN = [
    "already covered", "already discussed", "as covered above",
    "as mentioned above", "see above", "as we discussed", "see the",
]
_COP_OUT_PHRASES_UK = [
    "розібран", "вже обговорюва", "вже опис", "вже сказа", "вже говорили",
    "дивись вище", "див. вище", "як уже", "як ми вже",
]

SHALLOW_ASPECT_CHAR_THRESHOLD = 220

# ============================================================
# Language dispatcher — a single point for picking the table instead of
# scattered `X if is_ru else Y` throughout the file. `lang` is already
# normalized via normalize_language() before these dicts are used.
# ============================================================
PLANET_STEM_BY_LANG = {'ru': PLANET_STEM_RU, 'uk': PLANET_STEM_UK, 'en': PLANET_STEM_EN}
ASPECT_STEM_BY_LANG = {'ru': ASPECT_STEM_RU, 'uk': ASPECT_STEM_UK, 'en': ASPECT_STEM_EN}
PLANET_DISPLAY_BY_LANG = {'ru': PLANET_RU, 'uk': PLANET_UK, 'en': PLANET_EN}
COP_OUT_PHRASES_BY_LANG = {'ru': _COP_OUT_PHRASES_RU, 'uk': _COP_OUT_PHRASES_UK, 'en': _COP_OUT_PHRASES_EN}
# 'в тексте'/'на деле'/'заголовок' etc. — labels inside diagnostic mismatch
# messages (not matched by regex, just log text).
_MSG_LABELS_BY_LANG = {
    'ru': {'in_text': 'в тексте', 'actually': 'на деле', 'header': 'заголовок'},
    'uk': {'in_text': 'у тексті', 'actually': 'насправді', 'header': 'заголовок'},
    'en': {'in_text': 'in text', 'actually': 'actually', 'header': 'header'},
}


def _find_aspect_coverage(text: str, planet1_en: str, planet2_en: str, language: str, aspect_en: Optional[str] = None) -> Optional[str]:
    """
    Best paragraph found for a pair of planets — searches the real text, not
    the markdown formatting: the model isn't required to format an aspect as
    a bold heading, and the check shouldn't demand that either (see the
    2026-07-23 discussion — the previous version relied on
    find_paragraph_for_pair and bold headings and missed aspects that were
    genuinely covered but written as plain prose). Searches by declension-aware
    stems (PLANET_STEM_RU/EN — the same ones used for the aspect-type check),
    not the exact name — prose declines the planet's name by case ("Pluto's",
    "with Saturn").

    aspect_en (optional): when given, a paragraph must ALSO contain this
    aspect's stem (ASPECT_STEM_BY_LANG) to count as coverage — both planet
    names appearing in the same paragraph for unrelated reasons (e.g. each
    covered in its own separate sentence) used to falsely count as "covered"
    even though the aspect between them was never actually discussed. Real
    case that exposed this: transiting Moon conjunct transiting Neptune/
    natal Mars-Lilith both silently passed as "OK" despite not being written
    about — 2026-08-30. Omit (None) to fall back to the old, looser behavior
    for any caller that doesn't have a reliable aspect name to check against.
    """
    lang = normalize_language(language)
    stems = PLANET_STEM_BY_LANG[lang]
    display = PLANET_DISPLAY_BY_LANG[lang]
    p1_pattern = stems.get(planet1_en, re.escape(display.get(planet1_en, planet1_en)))
    p2_pattern = stems.get(planet2_en, re.escape(display.get(planet2_en, planet2_en)))
    asp_pattern = ASPECT_STEM_BY_LANG[lang].get(aspect_en) if aspect_en else None

    best = None
    for para in re.split(r"\n\s*\n", text):
        if not (re.search(p1_pattern, para) and re.search(p2_pattern, para)):
            continue
        if asp_pattern and not re.search(asp_pattern, para):
            continue
        if best is None or len(para) > len(best):
            best = para
    return best


# ============================================================
# Layers of one chart (progressed/natal, transit/natal...)
# ============================================================
# Generalizes the synastry "Partner 1/2" pattern (synastry_service.py) to
# methods with a SINGLE chart but several "versions" of the same planet —
# progressed position vs natal, later transit vs natal.
# Key difference from synastry: there the "Partner N" marker sits AFTER the
# planet ("Луна Партнёра 1"), while here the layer word sits BEFORE the
# planet ("прогрессивная Луна", "progressed Moon", "natal Sun") in both
# languages — so the functions below aren't copies of the synastry ones, but
# are parameterized by the marker search direction (marker_side). Plan:
# app/services/specs/progressions_synastry_pattern_plan.md.

LAYER_MARKER_PATTERNS = {
    'ru': {
        'progressed': r'[Пп]рогрессивн\w*',
        'natal': r'[Нн]атальн\w*',
        # placeholder for the future (transits) — not wired up anywhere by this TЗ
        'transit': r'[Тт]ранзитн\w*',
    },
    'en': {
        'progressed': r'\b[Pp]rogressed\b',
        'natal': r'\b[Nn]atal\b',
        'transit': r'\b[Tt]ransit(?:ing)?\b',
    },
    'uk': {
        'progressed': r'[Пп]рогресивн\w*',
        'natal': r'[Нн]атальн\w*',
        'transit': r'[Тт]ранзитн\w*',
    },
}


def attribute_header_planets_to_layers(
    header: str,
    language: str,
    layer_keys: "tuple[str, str]",
    marker_side: str = 'before',
) -> Optional[Dict[str, str]]:
    """
    Generalizes attribute_header_planets_to_partners (synastry_service.py) to
    arbitrary text layers of a single chart instead of Partner 1/2. Returns
    {layer_key: planet_en} if the heading has exactly one marker for each
    requested layer and exactly two planets, each unambiguously attributed
    to its nearest marker — otherwise None.

    marker_side='before' (default, for progressions/transits) — takes the
    nearest PRECEDING marker relative to the planet. marker_side='after'
    would reproduce the synastry logic ("Партнёра N" after the planet) — not
    used here, left in place in case synastry reuses this function in a
    future refactor.
    """
    lang = normalize_language(language)
    markers = LAYER_MARKER_PATTERNS[lang]
    planet_stems = PLANET_STEM_BY_LANG[lang]

    marker_hits: List[tuple] = []
    for key in layer_keys:
        pattern = markers.get(key)
        if not pattern:
            continue
        for m in re.finditer(pattern, header):
            marker_hits.append((m.start(), key))
    if len(marker_hits) < 2:
        return None
    marker_hits.sort(key=lambda x: x[0])

    planet_hits: List[tuple] = []
    for planet_en, stem_pattern in planet_stems.items():
        for m in re.finditer(stem_pattern, header):
            planet_hits.append((m.start(), planet_en))
    if len(planet_hits) != 2:
        return None  # we expect exactly two planets in the heading — otherwise it's ambiguous
    planet_hits.sort(key=lambda x: x[0])

    assigned: Dict[str, str] = {}
    for pos, planet_en in planet_hits:
        if marker_side == 'before':
            candidates = [key for mpos, key in marker_hits if mpos <= pos]
            chosen = candidates[-1] if candidates else None
        else:
            candidates = [key for mpos, key in marker_hits if mpos >= pos]
            chosen = candidates[0] if candidates else None
        if chosen is None or chosen in assigned:
            return None
        assigned[chosen] = planet_en

    if set(assigned.keys()) != set(layer_keys):
        return None
    return assigned


def _extract_layer_planet_signs(chart_like: Dict[str, Any], language: str) -> Dict[str, str]:
    """
    {planet display name: sign} from a chart-like dict of the form
    {'planets': {planet_en: {'sign':, 'sign_ru':}}, 'ascendant':, 'ascendant_ru':}
    — the shape shared by a natal chart and by progressed_planets/prog_asc in
    progressions_analysis (analysis_service.py). Shared building block for
    find_fabricated_positions_layered/fix_fabricated_positions_layered.
    """
    lang = normalize_language(language)
    sign_key = 'sign' if lang == 'en' else f'sign_{lang}'
    asc_key = 'ascendant' if lang == 'en' else f'ascendant_{lang}'
    result: Dict[str, str] = {}
    for p_name, p_data in (chart_like.get('planets') or {}).items():
        display = PLANET_DISPLAY_BY_LANG[lang].get(p_name)
        sign = p_data.get(sign_key)
        if display and sign:
            result[display] = sign
    asc_sign = chart_like.get(asc_key)
    if asc_sign:
        result[PLANET_DISPLAY_BY_LANG[lang]['Ascendant']] = asc_sign
    return result


def _nearest_preceding_layer(preceding_text: str, language: str, layer_keys) -> Optional[str]:
    """
    Nearest marker among layer_keys preceding the found phrase — but only
    WITHIN THE CURRENT SENTENCE (after the last ./!/? in preceding_text), not
    across the whole marker_window.

    Without this restriction, live runs (progressions and transits, see
    app/services/specs/*_synastry_pattern_plan.md) produced false
    layer_confused results: in a sentence like "Progressed Moon sextile natal
    Mercury (...). Your feelings (Moon in Aries/12th house)..." the marker
    "natal" (belonging to Mercury) was textually closer to the repeated
    mention of "Moon in Aries" in the SECOND sentence than "Progressed" from
    the FIRST — searched over the whole window, the "nearest" one turned out
    to belong to someone else. Restricting to the current sentence keeps it
    from looking into the previous sentence and picking up someone else's
    marker; if there's no marker at all in the current sentence — returns
    None (same as before for the "couldn't attribute" case), rather than
    guessing.

    If layer_keys contains EXACTLY one layer (a natal chart with no second
    side — see app/services/specs/natal_synastry_pattern_plan.md), attribution
    is already unambiguous: returns that single layer without searching for a
    marker at all — with a single layer the prompt deliberately never writes
    a marker (see the plan), and searching for one that's absent would
    otherwise always return None, leaving even clearly fabricated positions
    unfixed (unresolved).
    """
    if len(layer_keys) == 1:
        return layer_keys[0]

    lang = normalize_language(language)
    markers = LAYER_MARKER_PATTERNS[lang]

    sentence_start = 0
    for m in re.finditer(r'[.!?]\s+', preceding_text):
        sentence_start = m.end()
    current_sentence = preceding_text[sentence_start:]

    best_key, best_pos = None, -1
    for key in layer_keys:
        pattern = markers.get(key)
        if not pattern:
            continue
        matches = list(re.finditer(pattern, current_sentence))
        if matches and matches[-1].start() > best_pos:
            best_pos = matches[-1].start()
            best_key = key
    return best_key


def find_fabricated_positions_layered(
    text: str,
    layers: Dict[str, Dict[str, Any]],
    language: str = 'ru',
    marker_window: int = 400,
) -> Dict[str, List[str]]:
    """
    Generalizes find_fabricated_planet_positions (synastry_service.py) to N
    named layers of a SINGLE chart (e.g. {'progressed': prog_chart_like,
    'natal': natal_chart}) instead of two partners. Detection only, doesn't
    touch the text — fixing is done by fix_fabricated_positions_layered, and
    not by the same criteria (see its docstring).

    Returns two lists (strings for the log):
    - "fabricated" — the sign doesn't exist in ANY layer at all (union of all
      layers, same as in synastry) — a genuinely made-up position.
    - "layer_confused" — the sign exists for this planet, but in a DIFFERENT
      layer than the nearest preceding marker claimed ("progressed Moon in
      Cancer", even though Cancer is the Moon's natal sign). This isn't
      fabricated data, it's a mixed-up layer label — reported separately and
      NEVER used for auto-fixing: the prompt itself provokes the two
      positions of the same planet sitting next to each other (a sign-change
      marker like "was in X natally"), and fixing by this criterion would
      risk rewriting a correct phrase.
    """
    lang = normalize_language(language)
    connector = {'ru': r"\s+в\s+", 'uk': r"\s+[ув]\s+", 'en': r"\s+in\s+"}[lang]
    joiner = {'ru': 'в', 'uk': 'у', 'en': 'in'}[lang]

    per_layer_pairs = {key: _extract_layer_planet_signs(chart_like, language) for key, chart_like in layers.items()}
    all_pairs = set()
    for pairs in per_layer_pairs.values():
        for planet_name, sign in pairs.items():
            all_pairs.add((planet_name, sign))

    if not all_pairs:
        return {'fabricated': [], 'layer_confused': []}

    planet_names_display = PLANET_DISPLAY_BY_LANG[lang].values()
    sign_forms = {'ru': SIGN_PREPOSITIONAL_TO_NOMINATIVE, 'uk': SIGN_LOCATIVE_TO_NOMINATIVE_UK, 'en': ZODIAC_SIGNS_EN}[lang]
    planet_pattern = "|".join(re.escape(n) for n in planet_names_display)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")

    layer_keys = tuple(layers.keys())
    fabricated: List[str] = []
    layer_confused: List[str] = []

    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = sign_forms[sign_form] if lang in ('ru', 'uk') else sign_form

        if (planet_name, sign_nom) not in all_pairs:
            fabricated.append(f"{planet_name} {joiner} {sign_form}")
            continue

        window_start = max(0, m.start() - marker_window)
        preceding = text[window_start:m.start()]
        claimed_layer = _nearest_preceding_layer(preceding, language, layer_keys)
        if claimed_layer is None:
            continue  # can't attribute it — don't flag it, to avoid false positives

        claimed_sign = per_layer_pairs.get(claimed_layer, {}).get(planet_name)
        if claimed_sign == sign_nom:
            continue  # correct for the claimed layer

        layer_confused.append(
            f"{planet_name} {joiner} {sign_form} (заявлено как «{claimed_layer}», "
            f"в этом слое на деле: {claimed_sign or '—'})"
        )

    return {'fabricated': fabricated, 'layer_confused': layer_confused}


def fix_fabricated_positions_layered(
    text: str,
    layers: Dict[str, Dict[str, Any]],
    language: str = 'ru',
    marker_window: int = 400,
) -> "tuple[str, List[str]]":
    """
    Counterpart to fix_fabricated_planet_positions (synastry_service.py),
    generalized to N layers. Fixes STRICTLY those phrases whose sign doesn't
    exist in ANY layer at all (union check "matches at least one layer —
    leave it alone", same as in synastry) — that's enough to avoid mangling a
    correct phrase with a wrongly-attributed layer (that case —
    layer_confused in find_fabricated_positions_layered — is deliberately
    excluded here, log only).

    The layer (who's "right") is determined by the nearest PRECEDING
    occurrence of a marker within the marker_window. If the layer can't be
    determined, or it has no data for this planet — the phrase is left
    untouched and goes into unresolved.

    Returns (corrected text, list of unresolved mismatches).
    """
    lang = normalize_language(language)
    connector = {'ru': r"\s+в\s+", 'uk': r"\s+[ув]\s+", 'en': r"\s+in\s+"}[lang]
    joiner = {'ru': 'в', 'uk': 'у', 'en': 'in'}[lang]

    per_layer_pairs = {key: _extract_layer_planet_signs(chart_like, language) for key, chart_like in layers.items()}
    all_pairs = set()
    for pairs in per_layer_pairs.values():
        for planet_name, sign in pairs.items():
            all_pairs.add((planet_name, sign))

    if not all_pairs:
        return text, []

    planet_names_display = PLANET_DISPLAY_BY_LANG[lang].values()
    sign_forms = {'ru': SIGN_PREPOSITIONAL_TO_NOMINATIVE, 'uk': SIGN_LOCATIVE_TO_NOMINATIVE_UK, 'en': ZODIAC_SIGNS_EN}[lang]
    nominative_to_form = {'ru': SIGN_NOMINATIVE_TO_PREPOSITIONAL, 'uk': {v: k for k, v in SIGN_LOCATIVE_TO_NOMINATIVE_UK.items()}}.get(lang)
    planet_pattern = "|".join(re.escape(n) for n in planet_names_display)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")

    layer_keys = tuple(layers.keys())
    unresolved: List[str] = []
    pieces: List[str] = []
    last_end = 0

    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = sign_forms[sign_form] if lang in ('ru', 'uk') else sign_form
        if (planet_name, sign_nom) in all_pairs:
            continue  # matches at least one layer — leave it alone

        window_start = max(0, m.start() - marker_window)
        preceding = text[window_start:m.start()]
        claimed_layer = _nearest_preceding_layer(preceding, language, layer_keys)
        correct_sign = per_layer_pairs.get(claimed_layer, {}).get(planet_name) if claimed_layer else None
        if not correct_sign:
            unresolved.append(f"{planet_name} {joiner} {sign_form}")
            continue

        correct_form = nominative_to_form.get(correct_sign, correct_sign) if nominative_to_form else correct_sign
        pieces.append(text[last_end:m.start()])
        pieces.append(f"{planet_name} {joiner} {correct_form}")
        last_end = m.end()

    pieces.append(text[last_end:])
    return "".join(pieces), unresolved


def find_fabricated_aspect_types_layered(
    text: str,
    aspects: List[Dict[str, Any]],
    language: str,
    layer_keys: "tuple[str, str]",
    key1: str = 'planet1',
    key2: str = 'planet2',
) -> List[str]:
    """
    Generalizes find_fabricated_aspect_types (synastry_service.py) to layers
    instead of partners. aspects — the aspects_to_natal list built by
    calculate_progressions/calculate_transits (astrology_v2.py): key1/key2 —
    the field names of the true pair (planet1/planet2 by default — the
    calculator never varies them: the first layer is always planet1
    (progressed/transiting), the second is always planet2 (natal)). Detection
    only, doesn't fix anything.
    """
    lang = normalize_language(language)
    aspect_stems = ASPECT_STEM_BY_LANG[lang]
    layer1, layer2 = layer_keys

    truth: Dict[tuple, str] = {}
    for asp in aspects:
        truth[(asp.get(key1), asp.get(key2))] = asp.get('aspect')

    if not truth:
        return []

    mismatches: List[str] = []
    for header_match in _ASPECT_HEADER_RE.finditer(text):
        header = header_match.group(1)
        assigned = attribute_header_planets_to_layers(header, language, layer_keys, marker_side='before')
        if assigned is None:
            continue

        aspect_hits = []
        for aspect_en, stem_pattern in aspect_stems.items():
            for m in re.finditer(stem_pattern, header):
                aspect_hits.append((m.start(), aspect_en))
        if len(aspect_hits) != 1:
            continue  # zero or several aspect words in one heading — skip

        pair = (assigned[layer1], assigned[layer2])
        true_aspect = truth.get(pair)
        if true_aspect is None:
            continue  # this pair isn't in the calculation at all — not our case

        stated_aspect = aspect_hits[0][1]
        if stated_aspect != true_aspect:
            display = PLANET_DISPLAY_BY_LANG[lang]
            p1_name = display.get(pair[0], pair[0])
            p2_name = display.get(pair[1], pair[1])
            true_label = true_aspect
            if lang in ('ru', 'uk'):
                true_label = next(
                    (a.get(f'aspect_{lang}') for a in aspects if a.get(key1) == pair[0] and a.get(key2) == pair[1]),
                    true_aspect,
                )
            msg = _MSG_LABELS_BY_LANG[lang]
            mismatches.append(
                f"{layer1}:{p1_name} — {layer2}:{p2_name}: "
                f"{msg['in_text']} «{stated_aspect}», "
                f"{msg['actually']} «{true_label}» "
                f"({msg['header']}: {header.strip()[:120]})"
            )

    return mismatches


_RETURN_WORD_BY_LANG = {
    'ru': r'\bвозврат\w*\b',
    'uk': r'\bповерненн\w*\b',
    'en': r'\breturn(?:s|ed|ing)?\b',
}


def find_return_mislabeling(text: str, language: str) -> List[str]:
    """
    Detect-only, log-only (no fix) — flags the model calling a progressed
    planet's conjunction to its OWN natal position a "planetary return" (a
    real concept, but a TRANSIT-only one; see prompt_templates/progressions.py
    rule 12, added 2026-08-30). This recurred even after the RAG chunk-filter
    fix (_matches_technique) because the fabrication comes from the model's
    own prior astrology "knowledge", not a retrieved book fragment — no
    RAG-side fix can catch it, hence a text-side detector instead.

    Flags a paragraph only when a return-word stem AND the same planet's
    stem appear TOGETHER, that planet mentioned at least twice in the
    paragraph (a proxy for "progressed X ... natal X") — a bare "let's
    return to the topic of Saturn" (single mention, ordinary narrative
    continuity per this same template's own "СВЯЗНОСТЬ"/"COHESION"
    instruction) is deliberately NOT flagged.
    """
    lang = normalize_language(language)
    return_pattern = _RETURN_WORD_BY_LANG.get(lang)
    if not return_pattern:
        return []
    stems = PLANET_STEM_BY_LANG[lang]

    findings: List[str] = []
    for para in re.split(r"\n\s*\n", text):
        if not re.search(return_pattern, para, re.I):
            continue
        for planet_en, stem in stems.items():
            if len(re.findall(stem, para)) >= 2:
                findings.append(f"{planet_en}: {para.strip()[:150]}")
    return findings


def find_undercovered_aspects_generic(
    full_analysis: str,
    aspects: List[Dict[str, Any]],
    language: str,
    key1: str = 'planet1',
    key2: str = 'planet2',
) -> List[str]:
    """
    Generalizes find_undercovered_aspects (synastry_service.py) without tying
    the label to "Партнёру 1/2" — for methods with two sides of
    progressed/natal (or transiting/natal), not two partners. Same logic:
    stems, declensions, the SHALLOW_ASPECT_CHAR_THRESHOLD threshold, cutting
    off reference phrases ("covered above"). Detection only, doesn't append
    anything.

    Known limitation (same as the synastry version): for an aspect of a
    planet to itself (progressed Moon — natal Moon), searching by two
    identical stems is tautological and always returns "covered" —
    undercounts problems, never overcounts them.
    """
    lang = normalize_language(language)
    cop_out_phrases = COP_OUT_PHRASES_BY_LANG[lang]

    def label_for(asp: Dict[str, Any]) -> str:
        display = PLANET_DISPLAY_BY_LANG[lang]
        p1 = display.get(asp.get(key1), asp.get(key1))
        p2 = display.get(asp.get(key2), asp.get(key2))
        asp_word = asp.get(f'aspect_{lang}') if lang in ('ru', 'uk') else asp.get('aspect')
        orb_word = {'ru': 'орб', 'uk': 'орбіс', 'en': 'orb'}[lang]
        return f"{p1} {asp_word} {p2} ({orb_word} {asp.get('orb')}°)"

    missing: List[str] = []
    for asp in aspects:
        para = _find_aspect_coverage(full_analysis, asp.get(key1), asp.get(key2), language, aspect_en=asp.get('aspect'))
        is_cop_out = bool(para) and any(phrase in para.lower() for phrase in cop_out_phrases)
        if not para or len(para) < SHALLOW_ASPECT_CHAR_THRESHOLD or is_cop_out:
            missing.append(label_for(asp))

    return missing


# ============================================================
# A single chart with no sides (natal synthesis chart) — shared
# ============================================================
# Unlike find_fabricated_aspect_types (synastry_service.py) and
# find_fabricated_aspect_types_layered (above) — there's no partner/layer
# attribution at all here, because there's only one chart: two planets in a
# bold markdown heading are unambiguous on their own, with no "whose" marker
# needed. Plan: app/services/specs/natal_synastry_pattern_plan.md.

def find_fabricated_aspect_types_single(
    text: str,
    aspects: List[Dict[str, Any]],
    language: str,
    key1: str = 'planet1',
    key2: str = 'planet2',
) -> List[str]:
    """
    Checks bold markdown headings of the form "<Planet1> <Aspect> <Planet2>"
    against the actually calculated aspect type for that pair — for charts
    with one side (natal), no partner/layer attribution. The planet pair in
    calculate_aspects (astrology_v2.py) is unordered — unlike synastry, the
    same pair can't be two different real aspects at once, so the truth key
    is frozenset({p1, p2}).

    Skips (doesn't flag) a heading if it doesn't have exactly 2 planets or
    exactly 1 aspect type — ambiguity isn't resolved by guessing (same
    principle as find_fabricated_aspect_types /
    find_fabricated_aspect_types_layered). Detection only, doesn't fix
    anything.
    """
    lang = normalize_language(language)
    planet_stems = PLANET_STEM_BY_LANG[lang]
    aspect_stems = ASPECT_STEM_BY_LANG[lang]

    truth: Dict[frozenset, str] = {}
    for asp in aspects:
        p1, p2 = asp.get(key1), asp.get(key2)
        if p1 and p2:
            truth[frozenset({p1, p2})] = asp.get('aspect')

    if not truth:
        return []

    mismatches: List[str] = []
    for header_match in _ASPECT_HEADER_RE.finditer(text):
        header = header_match.group(1)

        planet_hits = []
        for planet_en, stem_pattern in planet_stems.items():
            for m in re.finditer(stem_pattern, header):
                planet_hits.append(planet_en)
        if len(planet_hits) != 2 or planet_hits[0] == planet_hits[1]:
            continue  # not exactly two DIFFERENT planets — not our case

        aspect_hits = []
        for aspect_en, stem_pattern in aspect_stems.items():
            for m in re.finditer(stem_pattern, header):
                aspect_hits.append(aspect_en)
        if len(aspect_hits) != 1:
            continue  # the type isn't named explicitly, or is named ambiguously

        pair = frozenset(planet_hits)
        true_aspect = truth.get(pair)
        if true_aspect is None:
            continue  # this pair isn't in the calculation at all — not our case

        stated_aspect = aspect_hits[0]
        if stated_aspect != true_aspect:
            p1_en, p2_en = planet_hits
            display = PLANET_DISPLAY_BY_LANG[lang]
            p1_name = display.get(p1_en, p1_en)
            p2_name = display.get(p2_en, p2_en)
            true_label = true_aspect
            if lang in ('ru', 'uk'):
                true_label = next(
                    (a.get(f'aspect_{lang}') for a in aspects if frozenset({a.get(key1), a.get(key2)}) == pair),
                    true_aspect,
                )
            msg = _MSG_LABELS_BY_LANG[lang]
            mismatches.append(
                f"{p1_name} — {p2_name}: "
                f"{msg['in_text']} «{stated_aspect}», "
                f"{msg['actually']} «{true_label}» "
                f"({msg['header']}: {header.strip()[:120]})"
            )

    return mismatches


# ============================================================
# HOUSE check (natal, single chart) — shared
# ============================================================
# Different from sign checking: a house doesn't have a fixed number of word
# forms like the 12 signs do ("в Овне", "во Льве" — a finite list), so a house
# isn't found via a full "<Planet> in <House>" regex pair, but by the word
# "дом"/"house" being in the same sentence as the planet — the same
# current-sentence constraint as _nearest_preceding_layer (without it a house
# number from one sentence would get falsely attributed to a planet in the
# next one). Detection only — fixing is riskier than for signs: replacing a
# house number in live prose could get out of sync with agreement elsewhere
# in the same sentence ("в 7-м доме" vs "седьмой дом" in one place). Plan:
# app/services/specs/natal_synastry_pattern_plan.md.

_HOUSE_WORD_RU = r'(?:дом|доме|дома|домов|домах)\b'
_HOUSE_NUMBER_RU = re.compile(
    rf'(?:(\d{{1,2}})[-–]?\s*(?:й|м|го|ом)?\s*{_HOUSE_WORD_RU}|{_HOUSE_WORD_RU}\s*(\d{{1,2}}))',
    re.IGNORECASE,
)
_HOUSE_NUMBER_EN = re.compile(
    r'(?:(\d{1,2})(?:st|nd|rd|th)?\s*house|house\s*(?:number\s*)?(\d{1,2}))',
    re.IGNORECASE,
)

# Ukrainian: the LLM actually uses BOTH words for "house" — "будинок" (the word
# from our prompt_labels.py) AND "дім" (more colloquial — confirmed by real
# DeepSeek output, natal analysis 2026-07: "Венера у Леві в 7-му домі"
# uses the form "домі", root word "дім", not "будинку"). Both forms
# must match, or real model text would slip past the regex.
_HOUSE_WORD_UK = r'(?:будинок|будинку|будинки|будинків|будинках|дім|дому|дома|домі|доми|домів|домах)\b'
_HOUSE_NUMBER_UK = re.compile(
    rf'(?:(\d{{1,2}})[-–]?\s*(?:й|му|го|ому|ім|м)?\s*{_HOUSE_WORD_UK}|{_HOUSE_WORD_UK}\s*(\d{{1,2}}))',
    re.IGNORECASE,
)

_BOLD_HEADER_RE = re.compile(r'\*\*[^*\n]{1,240}\*\*')
_SENTENCE_OR_HEADER_BOUNDARY_RE = re.compile(r'\*\*[^*\n]{1,240}\*\*|[.!?]\s+')

# A connecting conjunction after a comma almost always signals a new subject
# ("Марс ... в 6-м доме, И квадрат с Солнцем ..." — the house belongs to Mars,
# not the Sun, even though both are in one "sentence" by punctuation). EN: same
# for and/but. UK: "і"/"й"/"а"/"але". Without this split, the house would be
# falsely attributed to any other planet mentioned in the same sentence as the
# actual house owner.
_CLAUSE_BREAK_RU = re.compile(r',\s*(?:и|а|но)\s+')
_CLAUSE_BREAK_EN = re.compile(r',\s*(?:and|but)\s+')
_CLAUSE_BREAK_UK = re.compile(r',\s*(?:і|й|а|але)\s+')

HOUSE_PATTERN_BY_LANG = {'ru': _HOUSE_NUMBER_RU, 'uk': _HOUSE_NUMBER_UK, 'en': _HOUSE_NUMBER_EN}
CLAUSE_BREAK_BY_LANG = {'ru': _CLAUSE_BREAK_RU, 'uk': _CLAUSE_BREAK_UK, 'en': _CLAUSE_BREAK_EN}


def _sentence_span(text: str, pos: int) -> "tuple[int, int]":
    """
    Bounds of the sentence containing pos — by ./!/? and by the boundary of a
    bold markdown heading (**...**), in both directions. A heading is a
    separate semantic block, not part of the next sentence: without this
    boundary, "**11. Uranus and Neptune ...**\nUranus in Scorpio in the 8th
    house" would be counted as one sentence, and Uranus's house would be
    falsely attributed to Neptune from the heading. If pos is inside the
    heading itself — the sentence is the whole heading.
    """
    for m in _BOLD_HEADER_RE.finditer(text):
        if m.start() <= pos < m.end():
            return m.start(), m.end()

    start = 0
    for m in _SENTENCE_OR_HEADER_BOUNDARY_RE.finditer(text[:pos]):
        start = m.end()
    end_match = _SENTENCE_OR_HEADER_BOUNDARY_RE.search(text, pos)
    end = end_match.start() if end_match else len(text)
    return start, end


def _clause_span(text: str, pos: int, language: str) -> "tuple[int, int]":
    """
    Narrows _sentence_span down to a clause within the sentence, split by
    comma+conjunction ("и"/"а"/"но" — RU, "and"/"but" — EN). See the
    _CLAUSE_BREAK_RU docstring — without this narrowing, a house would be
    falsely attributed to another planet mentioned in the same sentence after
    the connecting conjunction.
    """
    sent_start, sent_end = _sentence_span(text, pos)
    segment = text[sent_start:sent_end]
    rel_pos = pos - sent_start

    clause_break = CLAUSE_BREAK_BY_LANG[normalize_language(language)]
    breaks = [0] + [m.end() for m in clause_break.finditer(segment)] + [len(segment)]
    for i in range(len(breaks) - 1):
        if breaks[i] <= rel_pos < breaks[i + 1]:
            return sent_start + breaks[i], sent_start + breaks[i + 1]
    return sent_start, sent_end


def find_fabricated_houses_single(
    text: str,
    natal_chart_like: Dict[str, Any],
    language: str = 'ru',
) -> List[str]:
    """
    Checks house mentions next to a planet ("<Planet> ... in the Nth house")
    against the planet's real house in the natal chart. Detection only,
    doesn't fix anything (see the module docstring of the section above for
    why).

    Searches for the house number only WITHIN THE CURRENT CLAUSE — a sentence
    further bounded by a bold-heading boundary and comma+conjunction (see
    _clause_span) — where the planet's name was found. If the clause has 0 or
    more than 1 DIFFERENT house numbers, skips it (ambiguous, no guessing,
    same principle as the other checks in this module). Several planets in
    one clause with one house number isn't an error (e.g. "Pluto and the Moon
    in that same 7th house" — legitimately attributes one house to both
    planets). Ascendant/MC aren't checked — they have no numeric 'house'
    field in the chart (house 1/10 is determined by the cusp, not stored as a
    separate value).
    """
    lang = normalize_language(language)
    planet_stems = PLANET_STEM_BY_LANG[lang]
    house_pattern = HOUSE_PATTERN_BY_LANG[lang]
    display_table = PLANET_DISPLAY_BY_LANG[lang]

    real_houses: Dict[str, int] = {}
    for p_name, p_data in (natal_chart_like.get('planets') or {}).items():
        house = p_data.get('house')
        display = display_table.get(p_name)
        if display and isinstance(house, int):
            real_houses[display] = house

    if not real_houses:
        return []

    mismatches: List[str] = []
    seen: set = set()
    for planet_en, stem_pattern in planet_stems.items():
        display = display_table.get(planet_en)
        if display not in real_houses:
            continue
        for m in re.finditer(stem_pattern, text):
            clause_start, clause_end = _clause_span(text, m.start(), language)
            clause = text[clause_start:clause_end]

            numbers = set()
            for hm in house_pattern.finditer(clause):
                for g in hm.groups():
                    if g:
                        numbers.add(int(g))
            if len(numbers) != 1:
                continue  # 0 or ambiguous (several different numbers) — skip

            claimed_house = next(iter(numbers))
            if not (1 <= claimed_house <= 12):
                continue
            real_house = real_houses[display]
            if claimed_house != real_house:
                key = (display, claimed_house, clause_start)
                if key in seen:
                    continue
                seen.add(key)
                msg = _MSG_LABELS_BY_LANG[lang]
                house_word = {'ru': 'дом', 'uk': 'будинок', 'en': 'house'}[lang]
                mismatches.append(
                    f"{display}: {msg['in_text']} {house_word} {claimed_house}, "
                    f"{msg['actually']} {real_house} "
                    f"({clause.strip()[:120]})"
                )

    return mismatches
