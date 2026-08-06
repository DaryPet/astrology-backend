import re
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.services.search_service import (
    search_chunks_by_query,
    search_chunks_simple,
)
from app.services.llm_adapter import get_llm_adapter
from app.services.prompt_labels import get_labels
from app.services.prompt_templates import get_template, get_relationship_context_prompt
from app.services.analysis_service import search_chunks_all_books, generate_summary
from app.services.text_verification import (
    SIGN_PREPOSITIONAL_TO_NOMINATIVE,
    SIGN_NOMINATIVE_TO_PREPOSITIONAL,
    SIGN_LOCATIVE_TO_NOMINATIVE_UK,
    ZODIAC_SIGNS_EN,
    PLANET_STEM_RU,
    ASPECT_STEM_RU,
    PLANET_STEM_EN,
    ASPECT_STEM_EN,
    PLANET_STEM_UK,
    ASPECT_STEM_UK,
    _ASPECT_HEADER_RE,
)
from app.services.prompt_templates.languages import normalize_language


JEFF_GREEN_BOOK_ID = 26

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

# Language dispatcher — a single point for picking the table instead of scattered
# `X if is_ru else Y`, the same trick as in text_verification.py.
PLANET_DISPLAY_BY_LANG = {'ru': PLANET_RU, 'uk': PLANET_UK, 'en': PLANET_EN}
PLANET_STEM_BY_LANG = {'ru': PLANET_STEM_RU, 'uk': PLANET_STEM_UK, 'en': PLANET_STEM_EN}
ASPECT_STEM_BY_LANG = {'ru': ASPECT_STEM_RU, 'uk': ASPECT_STEM_UK, 'en': ASPECT_STEM_EN}
SIGN_FORMS_BY_LANG = {'ru': SIGN_PREPOSITIONAL_TO_NOMINATIVE, 'uk': SIGN_LOCATIVE_TO_NOMINATIVE_UK, 'en': ZODIAC_SIGNS_EN}
_SIGN_NOMINATIVE_TO_FORM_UK = {v: k for k, v in SIGN_LOCATIVE_TO_NOMINATIVE_UK.items()}
CONNECTOR_BY_LANG = {'ru': r"\s+в\s+", 'uk': r"\s+[ув]\s+", 'en': r"\s+in\s+"}
JOINER_BY_LANG = {'ru': 'в', 'uk': 'у', 'en': 'in'}
_MSG_LABELS_BY_LANG = {
    'ru': {'in_text': 'в тексте', 'actually': 'на деле'},
    'uk': {'in_text': 'у тексті', 'actually': 'насправді'},
    'en': {'in_text': 'in text', 'actually': 'actually'},
}


def find_fabricated_planet_positions(
    text: str,
    chart1_data: Dict[str, Any],
    chart2_data: Dict[str, Any],
    language: str = 'ru',
) -> List[str]:
    """
    Ищет в готовом тексте утверждения вида "<Планета> в <Знаке>"
    ("<Planet> in <Sign>" для английского) и сверяет их с реальными позициями
    планет в обеих картах. Возвращает список фраз, для которых такого
    сочетания планета+знак нет ни в одной карте — то есть модель выдумала
    позицию (план: plans/synastry-before-batching.md, п.5).

    Ловит только явное расхождение планета/знак; не проверяет дом.

    Английский проще русского здесь: знак не склоняется ("in Cancer" что в
    начале, что в середине фразы), поэтому дополнительная таблица форм
    (как SIGN_PREPOSITIONAL_TO_NOMINATIVE для русского) не нужна.
    """
    lang = normalize_language(language)
    connector = CONNECTOR_BY_LANG[lang]
    display = PLANET_DISPLAY_BY_LANG[lang]
    sign_key = 'sign' if lang == 'en' else f'sign_{lang}'
    asc_key = 'ascendant' if lang == 'en' else f'ascendant_{lang}'

    valid_pairs = set()
    for chart in (chart1_data, chart2_data):
        for p_name, p_data in chart.get('planets', {}).items():
            planet_name = display.get(p_name)
            sign = p_data.get(sign_key)
            if planet_name and sign:
                valid_pairs.add((planet_name, sign))
        asc_sign = chart.get(asc_key)
        if asc_sign:
            valid_pairs.add((display['Ascendant'], asc_sign))

    if not valid_pairs:
        return []

    planet_names = display.values()
    sign_forms = SIGN_FORMS_BY_LANG[lang]
    planet_pattern = "|".join(re.escape(n) for n in planet_names)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")

    mismatches = []
    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = sign_forms[sign_form] if lang in ('ru', 'uk') else sign_form
        if (planet_name, sign_nom) not in valid_pairs:
            joiner = JOINER_BY_LANG[lang]
            mismatches.append(f"{planet_name} {joiner} {sign_form}")

    return mismatches


_PARTNER_MARKER_RE_SRC = r"[Пп]артн[её]р\w*\s*(1|2)"
_PARTNER_MARKER_RE_SRC_EN = r"[Pp]artner\s*(1|2)"
# Ukrainian "партнер" is spelled without "ё" (that letter doesn't exist at
# all in the Ukrainian alphabet) — otherwise the same pattern as Russian.
_PARTNER_MARKER_RE_SRC_UK = r"[Пп]артнер\w*\s*(1|2)"
_PARTNER_MARKER_SRC_BY_LANG = {
    'ru': _PARTNER_MARKER_RE_SRC, 'uk': _PARTNER_MARKER_RE_SRC_UK, 'en': _PARTNER_MARKER_RE_SRC_EN,
}


def fix_fabricated_planet_positions(
    text: str,
    chart1_data: Dict[str, Any],
    chart2_data: Dict[str, Any],
    language: str = 'ru',
) -> "tuple[str, List[str]]":
    """
    Заменяет в готовом тексте выдуманные позиции планет ("<Планета> в <Знаке>"
    / "<Planet> in <Sign>", которого нет ни в одной карте) на верный знак —
    строковой заменой, без повторного вызова LLM (план:
    plans/synastry-before-batching.md, п.5). Полная перегенерация всего
    документа при каждой ошибке съедала ~15 минут и не гарантированно чинила
    суть — регулярка со словарём карты дешевле и надёжнее для этого
    конкретного класса ошибок.

    Партнёр (чья карта верна) определяется по ближайшему предшествующему
    упоминанию "Партнёр 1/2" / "Partner 1/2" в тексте. Если такого упоминания
    нет рядом, или планета отсутствует в определённой карте — фраза не
    трогается и попадает в список unresolved (её стоит показать в логах).

    Для английского замена проще: знак не склоняется, "правильная форма"
    знака — он сам же, без таблицы конверсии как для русского.

    Возвращает (исправленный текст, список нерешённых расхождений).
    """
    lang = normalize_language(language)
    connector = CONNECTOR_BY_LANG[lang]
    joiner = JOINER_BY_LANG[lang]
    display = PLANET_DISPLAY_BY_LANG[lang]
    sign_key = 'sign' if lang == 'en' else f'sign_{lang}'
    asc_key = 'ascendant' if lang == 'en' else f'ascendant_{lang}'
    nominative_to_form = {'ru': SIGN_NOMINATIVE_TO_PREPOSITIONAL, 'uk': _SIGN_NOMINATIVE_TO_FORM_UK}.get(lang)

    def correct_sign_for(planet_name: str, chart_data: Dict[str, Any]) -> Optional[str]:
        if planet_name == display['Ascendant']:
            return chart_data.get(asc_key)
        for p_name, p_data in chart_data.get('planets', {}).items():
            if display.get(p_name) == planet_name:
                return p_data.get(sign_key)
        return None

    valid_pairs = set()
    for chart in (chart1_data, chart2_data):
        for p_name, p_data in chart.get('planets', {}).items():
            planet_name = display.get(p_name)
            sign = p_data.get(sign_key)
            if planet_name and sign:
                valid_pairs.add((planet_name, sign))
        asc_sign = chart.get(asc_key)
        if asc_sign:
            valid_pairs.add((display['Ascendant'], asc_sign))

    if not valid_pairs:
        return text, []

    planet_names = display.values()
    sign_forms = SIGN_FORMS_BY_LANG[lang]
    planet_pattern = "|".join(re.escape(n) for n in planet_names)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")
    partner_re = re.compile(_PARTNER_MARKER_SRC_BY_LANG[lang])

    unresolved: List[str] = []
    pieces: List[str] = []
    last_end = 0

    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = sign_forms[sign_form] if lang in ('ru', 'uk') else sign_form
        if (planet_name, sign_nom) in valid_pairs:
            continue  # correct, leave it alone

        window_start = max(0, m.start() - 400)
        preceding = text[window_start:m.start()]
        partner_matches = list(partner_re.finditer(preceding))
        chart_data = None
        if partner_matches:
            chart_num = partner_matches[-1].group(1)
            chart_data = chart1_data if chart_num == '1' else chart2_data

        correct_sign = correct_sign_for(planet_name, chart_data) if chart_data else None
        if not correct_sign:
            unresolved.append(f"{planet_name} {joiner} {sign_form}")
            continue

        correct_form = nominative_to_form.get(correct_sign, correct_sign) if nominative_to_form else correct_sign
        pieces.append(text[last_end:m.start()])
        pieces.append(f"{planet_name} {joiner} {correct_form}")
        last_end = m.end()

    pieces.append(text[last_end:])
    return "".join(pieces), unresolved


# Synastry-specific partner marker next to the planet in the aspect heading —
# unlike PLANET_STEM_RU/ASPECT_STEM_RU (moved to text_verification.py), this
# concept only exists for synastry (two charts); natal/transits don't have
# it, so it stays here.
_ASPECT_PARTNER_MARKER_RE = re.compile(r"[Пп]артн[её]р\w*\s*(1|2)")
_ASPECT_PARTNER_MARKER_RE_EN = re.compile(r"[Pp]artner\s*(1|2)")
_ASPECT_PARTNER_MARKER_RE_UK = re.compile(r"[Пп]артнер\w*\s*(1|2)")
_ASPECT_PARTNER_MARKER_RE_BY_LANG = {
    'ru': _ASPECT_PARTNER_MARKER_RE, 'uk': _ASPECT_PARTNER_MARKER_RE_UK, 'en': _ASPECT_PARTNER_MARKER_RE_EN,
}


def attribute_header_planets_to_partners(header: str, language: str = 'ru') -> Optional[Dict[str, str]]:
    """
    Для одного жирного markdown-заголовка вида "<Планета> Партнёра N ... к
    <Планета> Партнёра M" ("<Planet> Partner N ... <Planet> Partner M" для
    английского) возвращает {'1': planet_en, '2': planet_en}, если ровно две
    планеты однозначно привязаны к обоим партнёрам, иначе None.

    Общий кусок логики для find_fabricated_aspect_types и для
    tests/check_aspect_coverage.py + tests/judge_synastry.py — важно, что
    один и тот же неупорядоченный набор планет (Сатурн-Хирон) может встречать
    в тексте ДВАЖДЫ как два РАЗНЫХ реальных аспекта: Сатурн(П1)-Хирон(П2) и
    Хирон(П1)-Сатурн(П2) — у каждого своя орбита и свой тип. Проверка "оба
    имени встречаются в абзаце" (без разбора, кому что принадлежит) путает
    эти два разных аспекта друг с другом — так нашлись ложные "противоречия"
    на живом прогоне (см. plans/synastry-aspect-type-verification.md).
    """
    lang = normalize_language(language)
    partner_re = _ASPECT_PARTNER_MARKER_RE_BY_LANG[lang]
    planet_stems = PLANET_STEM_BY_LANG[lang]

    partner_markers = [(m.start(), m.group(1)) for m in partner_re.finditer(header)]
    if len(partner_markers) < 2:
        return None

    planet_hits = []  # (position, planet_en)
    for planet_en, stem_pattern in planet_stems.items():
        for m in re.finditer(stem_pattern, header):
            planet_hits.append((m.start(), planet_en))
    if len(planet_hits) != 2:
        return None  # we expect exactly two planets in the heading — otherwise it's ambiguous

    planet_hits.sort(key=lambda x: x[0])
    assigned: Dict[str, str] = {}
    for pos, planet_en in planet_hits:
        following = [pn for ppos, pn in partner_markers if ppos >= pos]
        if not following:
            return None
        partner_num = following[0]
        if partner_num in assigned:
            return None
        assigned[partner_num] = planet_en

    if set(assigned.keys()) != {'1', '2'}:
        return None
    return assigned


def find_paragraph_for_pair(
    text: str, planet1_en: str, planet2_en: str, language: str = 'ru'
) -> Optional[str]:
    """
    Находит абзац (заголовок + текст до следующего заголовка), где planet1_en
    привязан ИМЕННО к Партнёру 1, а planet2_en — ИМЕННО к Партнёру 2 (порядок
    важен — так же, как в aspects из calculate_synastry). Не путает два разных
    реальных аспекта одной неупорядоченной пары планет (см.
    attribute_header_planets_to_partners). Возвращает самый длинный такой
    абзац, если их несколько; None, если ни одного не найдено.
    """
    headers = list(_ASPECT_HEADER_RE.finditer(text))
    best: Optional[str] = None
    for i, header_match in enumerate(headers):
        attribution = attribute_header_planets_to_partners(header_match.group(1), language=language)
        if attribution != {'1': planet1_en, '2': planet2_en}:
            continue
        para_start = header_match.start()
        para_end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        paragraph = text[para_start:para_end]
        if best is None or len(paragraph) > len(best):
            best = paragraph
    return best


def find_fabricated_aspect_types(
    text: str, aspects: List[Dict[str, Any]], language: str = 'ru'
) -> List[str]:
    """
    Ищет в жирных markdown-заголовках готового текста утверждения вида
    "<Планета> Партнёра N ... <аспект> ... <Планета> Партнёра M" ("<Planet>
    Partner N ... <aspect> ... <Planet> Partner M" для английского) и сверяет
    заявленный тип аспекта с реально посчитанным (calculate_synastry) для
    этой пары планета+партнёр. Возвращает список описаний расхождений —
    план: plans/synastry-aspect-type-verification.md.

    Только детекция, ничего не правит и не удаляет — при 51 аспекте и
    2 партнёрах строковая замена рискует сломать согласование (у "оппозиция"
    и "квадрат" разный род на русском), чинить предлагается точечной
    регенерацией абзаца, не входит в этот прогон.

    Находит только то, что оформлено жирным заголовком с явной пометкой
    "Партнёра 1/2" / "Partner 1/2" у каждой планеты — как реально пишет
    модель на этом промпте (см. правило 13, prompt_templates.py). Аспекты,
    разобранные внутри обычного абзаца без такого заголовка, не проверяются —
    это известное ограничение (недооценка, не переоценка числа ошибок).
    """
    lang = normalize_language(language)
    aspect_stems = ASPECT_STEM_BY_LANG[lang]
    partner_word = {'ru': 'Партнёра', 'uk': 'Партнера', 'en': 'Partner'}[lang]

    # planet1 in aspects is always chart 1 (Partner 1), planet2 is always chart 2
    # (Partner 2): that's how calculate_synastry (astrology_v2.py) builds it, the
    # order never varies. The same unordered pair of planets can produce
    # TWO different entries (Saturn,Chiron) and (Chiron,Saturn) — these are two
    # distinct real aspects, keying by the ordered pair doesn't confuse them.
    truth: Dict[tuple, str] = {}
    for asp in aspects:
        truth[(asp.get('planet1'), asp.get('planet2'))] = asp.get('aspect')

    if not truth:
        return []

    mismatches: List[str] = []

    for header_match in _ASPECT_HEADER_RE.finditer(text):
        header = header_match.group(1)

        assigned = attribute_header_planets_to_partners(header, language=language)
        if assigned is None:
            continue

        aspect_hits = []  # (position, aspect_en)
        for aspect_en, stem_pattern in aspect_stems.items():
            for m in re.finditer(stem_pattern, header):
                aspect_hits.append((m.start(), aspect_en))
        if len(aspect_hits) != 1:
            continue  # zero or several aspect words in one heading — skip

        pair = (assigned['1'], assigned['2'])
        true_aspect = truth.get(pair)
        if true_aspect is None:
            continue  # this pair isn't in the calculation at all — not our case, not counted as an error

        stated_aspect = aspect_hits[0][1]
        if stated_aspect != true_aspect:
            display = PLANET_DISPLAY_BY_LANG[lang]
            p1_name = display.get(pair[0], pair[0])
            p2_name = display.get(pair[1], pair[1])
            true_label = true_aspect
            if lang in ('ru', 'uk'):
                true_label = next(
                    (a.get(f'aspect_{lang}') for a in aspects if a.get('planet1') == pair[0] and a.get('planet2') == pair[1]),
                    true_aspect,
                )
            msg = _MSG_LABELS_BY_LANG[lang]
            header_word = {'ru': 'заголовок', 'uk': 'заголовок', 'en': 'header'}[lang]
            mismatches.append(
                f"{p1_name} {partner_word} 1 — {p2_name} {partner_word} 2: "
                f"{msg['in_text']} «{stated_aspect}», "
                f"{msg['actually']} «{true_label}» "
                f"({header_word}: {header.strip()[:120]})"
            )

    return mismatches


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
COP_OUT_PHRASES_BY_LANG = {'ru': _COP_OUT_PHRASES_RU, 'uk': _COP_OUT_PHRASES_UK, 'en': _COP_OUT_PHRASES_EN}

SHALLOW_ASPECT_CHAR_THRESHOLD = 220


def _find_aspect_coverage(text: str, planet1_en: str, planet2_en: str, language: str) -> Optional[str]:
    """
    Лучший найденный абзац для пары планет — поиск по реальному тексту, а не
    по markdown-разметке: модель не обязана оформлять аспект жирным
    заголовком, и в проверке это не должно быть требованием (см. обсуждение
    2026-07-23 — прежняя версия зависела от find_paragraph_for_pair и жирных
    заголовков и пропускала реально разобранные аспекты, написанные обычной
    прозой). Ищем по стемам с учётом склонения (PLANET_STEM_RU/EN — те же,
    что для сверки типа аспекта), а не по точному имени — проза склоняет
    имя планеты по падежу ("Плутона", "Сатурном").
    """
    lang = normalize_language(language)
    stems = PLANET_STEM_BY_LANG[lang]
    display = PLANET_DISPLAY_BY_LANG[lang]
    p1_pattern = stems.get(planet1_en, re.escape(display.get(planet1_en, planet1_en)))
    p2_pattern = stems.get(planet2_en, re.escape(display.get(planet2_en, planet2_en)))

    best = None
    for para in re.split(r"\n\s*\n", text):
        if re.search(p1_pattern, para) and re.search(p2_pattern, para):
            if best is None or len(para) > len(best):
                best = para
    return best


def find_undercovered_aspects(
    full_analysis: str,
    aspects: List[Dict[str, Any]],
    language: str,
) -> List[str]:
    """
    Только детекция (тот же принцип, что find_fabricated_aspect_types): для
    каждого аспекта из списка проверяет, получил ли он реальный разбор (не
    пропущен и не свёрнут в отсылку "разобрано выше"). Текст анализа не
    трогает и ничего не дописывает — пользователь дозаписанный текст больше
    не видит (раньше видел, как хвост в конце ответа — снято по просьбе
    пользователя 2026-07-23, реальный разбор дублировался, а неточная
    детекция по жирным заголовкам иногда дублировала и то, что уже было
    разобрано). Возвращает список недоразобранных аспектов в виде читаемых
    меток — для серверного лога.
    """
    lang = normalize_language(language)
    cop_out_phrases = COP_OUT_PHRASES_BY_LANG[lang]
    display = PLANET_DISPLAY_BY_LANG[lang]
    partner_word = {'ru': 'Партнёра', 'uk': 'Партнера', 'en': 'Partner'}[lang]
    orb_word = {'ru': 'орб', 'uk': 'орбіс', 'en': 'orb'}[lang]

    def label_for(asp: Dict[str, Any]) -> str:
        p1 = display.get(asp.get('planet1'), asp.get('planet1'))
        p2 = display.get(asp.get('planet2'), asp.get('planet2'))
        asp_word = asp.get(f'aspect_{lang}') if lang in ('ru', 'uk') else asp.get('aspect')
        return f"{p1} ({partner_word} 1) {asp_word} {p2} ({partner_word} 2) ({orb_word} {asp.get('orb')}°)"

    missing: List[str] = []
    for asp in aspects:
        para = _find_aspect_coverage(full_analysis, asp.get('planet1'), asp.get('planet2'), language)
        is_cop_out = bool(para) and any(phrase in para.lower() for phrase in cop_out_phrases)
        if not para or len(para) < SHALLOW_ASPECT_CHAR_THRESHOLD or is_cop_out:
            missing.append(label_for(asp))

    return missing


def build_synastry_aspect_prompt(
    planet1: str,
    planet2: str,
    aspect_name: str,
    aspect_name_ru: Optional[str],
    orb: float,
    chunks: List[Dict[str, Any]],
    language: str = "en",
    mode: Optional[str] = 'advanced'
) -> str:
    """Построить промпт для анализа аспекта синастрии"""
    
    lang = normalize_language(language)
    if lang in ('ru', 'uk'):
        display = PLANET_DISPLAY_BY_LANG[lang]
        planet1 = display.get(planet1, planet1)
        planet2 = display.get(planet2, planet2)
    
    prompt_parts = []
    labels = get_labels(language)
    system_prompt = get_template('synastry_aspect', language, mode)
    prompt_parts.append(system_prompt)
    
    prompt_parts.append(f"\n\n{labels['aspect_data']}")
    prompt_parts.append(f"{labels['planet1']}: {planet1}")
    prompt_parts.append(f"{labels['planet2']}: {planet2}")
    aspect_display = f"{aspect_name} ({aspect_name_ru})" if aspect_name_ru else aspect_name
    prompt_parts.append(f"{labels['aspect_type']}: {aspect_display}")
    prompt_parts.append(f"{labels['orb']}: {orb}°")
    
    if chunks:
        prompt_parts.append(f"\n\n{labels['found_fragments']}")
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get('text', '')
            if len(text) > 300:
                text = text[:300] + "..."
            prompt_parts.append(f"\n[{labels['fragment']} {i}]:\n{text}")
    else:
        # Explicit note when no fragments found
        prompt_parts.append(f"\n\n=== ПРИМЕЧАНИЕ О ДОСТУПНЫХ ИСТОЧНИКАХ ===")
        prompt_parts.append("В библиотеке не найдено специфических фрагментов по данному аспекту синастрии. Анализ должен быть основан на общих принципах эволюционной синастрии и данных карт.")
    
    prompt_parts.append(f"\n\n{labels['analysis']}")
    prompt_parts.append(labels['please_analyze_synastry_aspect'])
    
    return "\n".join(prompt_parts)


async def analyze_synastry_aspect(
    planet1: str,
    planet2: str,
    aspect_name: str,
    aspect_name_ru: Optional[str] = None,
    orb: float = 0.0,
    language: str = "en",
    top_k: int = 5,
    mode: str = 'advanced'
) -> Dict[str, Any]:
    """
    Анализ конкретного аспекта в синастрии
    """
    
    if language == "ru" and aspect_name_ru:
        query = f"{planet1.lower()} {aspect_name_ru.lower()} {planet2.lower()} синастрия"
    else:
        query = f"{planet1} {aspect_name} {planet2} synastry"
    
    chunks = await search_chunks_by_query(query, top_k=top_k, book_id=JEFF_GREEN_BOOK_ID)
    
    if not chunks:
        chunks = await search_chunks_by_query(query, top_k=top_k)
    
    if not chunks:
        chunks = await search_chunks_simple(query, top_k=top_k)
    
    prompt = build_synastry_aspect_prompt(
        planet1=planet1,
        planet2=planet2,
        aspect_name=aspect_name,
        aspect_name_ru=aspect_name_ru,
        orb=orb,
        chunks=chunks,
        language=language,
        mode=mode
    )
    
    adapter = get_llm_adapter()
    analysis = await adapter.generate(prompt, language)
    
    return {
        "planet1": planet1,
        "planet2": planet2,
        "aspect": aspect_name,
        "aspect_ru": aspect_name_ru,
        "orb": orb,
        "analysis": analysis,
        "relevant_chunks": chunks
    }


async def full_synastry_analysis_v2(
    chart1_data: Dict[str, Any],
    chart2_data: Dict[str, Any],
    aspects: Optional[List[Dict[str, Any]]] = None,
    overlays: Optional[Dict[str, Any]] = None,
    language: str = "ru",
    top_k_per_book: int = 1,
    mode: str = 'advanced',
    relationship_context: Optional[str] = None

) -> Dict[str, Any]:
    """
    [v2] Полный анализ синастрии — ГИБРИДНЫЙ подход:
    - Для каждого аспекта синастрии делаем точечный RAG-поиск по ВСЕМ книгам
    - Для ключевых планет обеих карт делаем RAG-поиск
    - Собираем структурированный промпт
    - Один финальный вызов LLM

    Преимущества:
    - Все книги участвуют в анализе
    - Нет проблемы с превышением контекста
    - Каждый аспект получает релевантные фрагменты
    """
    import asyncio
    from app.utils.astrology_v2 import calculate_synastry, ASPECTS_RU, get_house_for_longitude

    adapter = get_llm_adapter()
    labels = get_labels(language)

    # 1. Calculate synastry aspects (if not passed directly)
    if not aspects:
        synastry_result = calculate_synastry(chart1_data, chart2_data)
        aspects = synastry_result.get('aspects', [])

    # 1.5 Calculate the house overlay (if not passed)
    if not overlays:
        overlays = {"planets_1_in_houses_2": {}, "planets_2_in_houses_1": {}}

        houses_2 = chart2_data.get('houses', {})
        houses_1 = chart1_data.get('houses', {})

        # Partner 1's planets in partner 2's houses
        for p_name, p_data in chart1_data.get('planets', {}).items():
            lon = p_data.get('full_degree', 0)
            house_num = get_house_for_longitude(lon, houses_2)
            if house_num:
                overlays["planets_1_in_houses_2"][p_name] = house_num

        # Partner 2's planets in partner 1's houses
        for p_name, p_data in chart2_data.get('planets', {}).items():
            lon = p_data.get('full_degree', 0)
            house_num = get_house_for_longitude(lon, houses_1)
            if house_num:
                overlays["planets_2_in_houses_1"][p_name] = house_num

    # 2. Experiment from plans/synastry-before-batching.md: all aspects, no cutoff.
    # calculate_synastry (astrology_v2.py) already sorts them by the same priority.
    top_aspects = aspects

    print(f"[full_synastry_analysis_v2] Total aspects: {len(aspects)}, sent to RAG search: {len(top_aspects)}")

    # 3. Parallel RAG search over aspects
    # The semaphore limits the number of concurrent requests to Supabase. Without
    # it, asyncio.gather fires all ~64 tasks at once, while run_sync_in_thread
    # (asyncio.to_thread) caps the pool at ~32 threads — with 44 aspects this
    # produced 34 of 64 requests failing with "[Errno 35] Resource
    # temporarily unavailable" on a real run (plan: plans/synastry-before-batching.md).
    # The semaphore doesn't reduce coverage — the same aspects and planets are
    # still all searched, just not in a single burst.
    search_semaphore = asyncio.Semaphore(12)

    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get('planet1', '')
        p2 = asp.get('planet2', '')
        asp_type = asp.get('aspect', '')
        orb = asp.get('orb', 0)
        asp_ru = asp.get('aspect_ru', asp_type)

        # Build the search query
        query = f"{p1} {asp_type} {p2} synastry"
        async with search_semaphore:
            chunks = await search_chunks_by_query(query, top_k=top_k_per_book, book_id=JEFF_GREEN_BOOK_ID)
        return f"{p1} {asp_ru} {p2} (орб: {orb}°)", chunks

    # 4. Parallel RAG search over key planets
    key_planets = ['Pluto', 'NorthNode', 'SouthNode', 'Saturn', 'Sun', 'Moon', 'Ascendant', 'Venus', 'Mars', 'Jupiter']

    async def search_planet_synastry(planet_name: str, chart_num: int, chart_data: Dict) -> tuple:
        # Check whether the planet is in the chart
        planets = chart_data.get('planets', {})
        if planet_name not in planets and planet_name != 'Ascendant':
            return f"Planet {planet_name} (Chart {chart_num})", []

        query = f"{planet_name} synastry partner"
        async with search_semaphore:
            chunks = await search_chunks_by_query(query, top_k=top_k_per_book, book_id=JEFF_GREEN_BOOK_ID)
        return f"Planet {planet_name} (Chart {chart_num})", chunks

    # Launch the parallel search
    aspect_tasks = [search_aspect(asp) for asp in top_aspects]

    planet_tasks_chart1 = [
        search_planet_synastry(p, 1, chart1_data) for p in key_planets
    ]
    planet_tasks_chart2 = [
        search_planet_synastry(p, 2, chart2_data) for p in key_planets
    ]

    all_tasks = aspect_tasks + planet_tasks_chart1 + planet_tasks_chart2
    results = await asyncio.gather(*all_tasks, return_exceptions=True)

    print(f"[full_synastry_analysis_v2] RAG search completed. Tasks: {len(all_tasks)}")

    # 5. Assemble the prompt
    synastry_template = get_template("synastry", language, mode)
    
    # Add relationship context to prompt
    context_prompt = get_relationship_context_prompt(relationship_context, language)
    if context_prompt:
        synastry_template = synastry_template + context_prompt

    # Prepare the list of aspects
    aspects_list = []
    for asp in aspects:
        p1 = asp.get('planet1', '?')
        p2 = asp.get('planet2', '?')
        asp_ru = asp.get('aspect_ru', asp.get('aspect', '?'))
        orb = asp.get('orb', 0)

        # Take the signs from the aspect itself (already added on the backend/UI)
        p1_sign = asp.get('planet1_sign', '')
        p2_sign = asp.get('planet2_sign', '')

        # Fallback: if the aspect has no signs, take them from the charts (for locally calculated aspects)
        if not p1_sign and chart1_data and 'planets' in chart1_data:
            p1_planet_data = chart1_data['planets'].get(p1, {})
            p1_sign = p1_planet_data.get('sign_ru', p1_planet_data.get('sign', ''))

        if not p2_sign and chart2_data and 'planets' in chart2_data:
            p2_planet_data = chart2_data['planets'].get(p2, {})
            p2_sign = p2_planet_data.get('sign_ru', p2_planet_data.get('sign', ''))

        # Translate planet names to Russian if needed
        if language == 'ru':
            p1_display = PLANET_RU.get(p1, p1)
            p2_display = PLANET_RU.get(p2, p2)
        else:
            p1_display = p1
            p2_display = p2
            
        aspects_list.append(f"ПАРТНЕР1:{p1_display} ({p1_sign}) {asp_ru} ПАРТНЕР2:{p2_display} ({p2_sign}) (орб: {orb}°)")

    aspects_str = "\n".join(aspects_list) if aspects_list else "Нет аспектов"

    # Build the overlay info
    PLANET_NAMES_RU = {
        'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
        'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
        'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
        'Pluto': 'Плутон', 'NorthNode': 'Северный узел',
        'SouthNode': 'Южный узел', 'Lilith': 'Лилит', 'Chiron': 'Хирон'
    }

    overlays_str = "\n=== ОВЕРЛЕИ ДОМОВ ===\n"
    overlays_str += "\nПланеты партнера 1 в домах партнера 2:\n"
    for p_name, house_num in overlays["planets_1_in_houses_2"].items():
        p_ru = PLANET_NAMES_RU.get(p_name, p_name)
        overlays_str += f"\n  {p_ru} в доме {house_num}"

    overlays_str += "\n\nПланеты партнера 2 в домах партнера 1:\n"
    for p_name, house_num in overlays["planets_2_in_houses_1"].items():
        p_ru = PLANET_NAMES_RU.get(p_name, p_name)
        overlays_str += f"\n  {p_ru} в доме {house_num}"

    # Assemble book excerpts - aspects
    books_content = "\n=== ФРАГМЕНТЫ ПО АСПЕКТАМ СИНАСТРИИ ===\n"
    # Deterministic source accounting per aspect — how many chunks and from
    # which book were actually found. Not via the LLM (the model can't reliably
    # count metadata about its own input), but straight from the search results.
    aspect_sources_debug = []
    for i, result in enumerate(results[:len(top_aspects)]):
        if isinstance(result, Exception):
            print(f"[full_synastry_analysis_v2] Aspect search error: {result}")
            aspect_sources_debug.append((f"аспект #{i+1} (ошибка поиска)", 0, [], str(result)))
            continue
        asp_label, chunks = result
        book_titles = sorted({(c.get("book_title") or "?") for c in chunks})
        aspect_sources_debug.append((asp_label, len(chunks), book_titles, None))
        if chunks:
            books_content += f"\n【АСПЕКТ: {asp_label}】\n"
            for j, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")
                book_title = chunk.get("book_title", "")
                books_content += f"[{j}] ({book_title}):\n{text}\n"

    # Assemble book excerpts - planets
    books_content += "\n=== ФРАГМЕНТЫ ПО ПЛАНЕТАМ ===\n"
    for i, result in enumerate(results[len(top_aspects):], start=len(top_aspects)):
        if isinstance(result, Exception):
            print(f"[full_synastry_analysis_v2] Planet search error: {result}")
            continue
        planet_label, chunks = result
        if chunks:
            books_content += f"\n【{planet_label.upper()}】\n"
            for j, chunk in enumerate(chunks, 1):
                text = chunk.get("text", "")
                book_title = chunk.get("book_title", "")
                books_content += f"[{j}] ({book_title}):\n{text}\n"

    # Substitute into the template
    prompt = synastry_template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # Chart data goes into the prompt once, via the template placeholders below
    # (used to also be duplicated in a "=== CHART N ===" block — plan
    # plans/synastry-before-batching.md, item 4: duplicates and mixed-language
    # sign entries on the same line confused the model during generation).
    planets1 = chart1_data.get('planets', {})
    houses1 = chart1_data.get('houses', {})
    planets2 = chart2_data.get('planets', {})
    houses2 = chart2_data.get('houses', {})

    # Substitute data into the template (for compatibility with {planets_1}, {houses_1}, etc.)
    prompt = prompt.replace("{sun_sign_1}", chart1_data.get('sun_sign_ru', '?'))
    prompt = prompt.replace("{moon_sign_1}", chart1_data.get('moon_sign_ru', '?'))
    prompt = prompt.replace("{ascendant_1}", chart1_data.get('ascendant_ru', '?'))

    # Build the planet and house lines for the template
    planets_1_str = ""
    for p_name, p_data in sorted(planets1.items()):
        sign_ru = p_data.get('sign_ru', p_data.get('sign', '?'))
        house = p_data.get('house', '?')
        rx_str = " (ретроградная)" if p_data.get('is_retrograde', False) else ""
        planets_1_str += f"\n  {p_name}: в {sign_ru}, дом {house}{rx_str}"
    prompt = prompt.replace("{planets_1}", planets_1_str)

    houses_1_str = ""
    for house_num in range(1, 13):
        key = str(house_num)
        if key in houses1:
            h = houses1[key]
            houses_1_str += f"\n  Дом {house_num}: {h.get('sign_ru', '?')}"
    prompt = prompt.replace("{houses_1}", houses_1_str)

    prompt = prompt.replace("{sun_sign_2}", chart2_data.get('sun_sign_ru', '?'))
    prompt = prompt.replace("{moon_sign_2}", chart2_data.get('moon_sign_ru', '?'))
    prompt = prompt.replace("{ascendant_2}", chart2_data.get('ascendant_ru', '?'))

    planets_2_str = ""
    for p_name, p_data in sorted(planets2.items()):
        sign_ru = p_data.get('sign_ru', p_data.get('sign', '?'))
        house = p_data.get('house', '?')
        planets_2_str += f"\n  {p_name}: в {sign_ru}, дом {house}"
    prompt = prompt.replace("{planets_2}", planets_2_str)

    houses_2_str = ""
    for house_num in range(1, 13):
        key = str(house_num)
        if key in houses2:
            h = houses2[key]
            houses_2_str += f"\n  Дом {house_num}: {h.get('sign_ru', '?')}"
    prompt = prompt.replace("{houses_2}", houses_2_str)
    prompt = prompt.replace("{house_overlays}", overlays_str)

    # 6. Call the LLM
    print(f"[full_synastry_analysis_v2] Sending prompt to LLM (~{len(prompt)//4} tokens estimated)")

    # One call — no regenerating the whole document when an error is found.
    # It used to resend the whole ~240k-token prompt from scratch (up to 3
    # times) whenever positions mismatched — that took ~15 minutes per request
    # and didn't reliably fix the substance (plan: plans/synastry-before-batching.md,
    # item 5). Instead, the error is now fixed instantly via a string
    # replacement keyed off the chart data.
    full_analysis = ""
    try:
        full_analysis = await adapter.generate(prompt, language)

        if language in ('ru', 'en', 'uk'):
            full_analysis, unresolved = fix_fabricated_planet_positions(
                full_analysis, chart1_data, chart2_data, language=language
            )
            if unresolved:
                print(f"[full_synastry_analysis_v2] Unresolved position mismatches (left as-is): {unresolved}")

            # Detection only (plan: plans/synastry-aspect-type-verification.md)
            # — the text is left alone, so as not to mask the real error rate
            # until a decision is made on fixing it.
            fabricated_aspects = find_fabricated_aspect_types(full_analysis, aspects, language=language)
            if fabricated_aspects:
                print(f"[full_synastry_analysis_v2] Fabricated aspect types detected (not fixed): {fabricated_aspects}")

            # Detection only, from the text (not markdown headings) — the
            # response text is left alone, nothing is appended for the user.
            undercovered = find_undercovered_aspects(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[full_synastry_analysis_v2] Undercovered aspects detected (not filled): {undercovered}")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[full_synastry_analysis_v2] LLM error: {e}")

    # 6.5 Source summary per aspect — how many chunks and from which book were
    # actually found for each aspect. Exact numbers from the code, not the LLM.
    # Server log only: not to be mixed into the user-facing text.
    print("[full_synastry_analysis_v2] Источники по аспектам:")
    for label, count, book_titles, error in aspect_sources_debug:
        if error:
            print(f"  {label}: поиск не выполнен ({error})")
            continue
        titles_str = ", ".join(book_titles) if book_titles else "—"
        print(f"  {label}: {count} чанков, книги: {titles_str}")

    # 7. Short summary (first 500 chars)
    summary = full_analysis[:500].rsplit('. ', 1)[0] if len(full_analysis) > 500 else full_analysis

    # 8. Return the result
    return {
        "chart1_summary": {
            "sun_sign": chart1_data.get('sun_sign', '?'),
            "sun_sign_ru": chart1_data.get('sun_sign_ru', '?'),
            "moon_sign": chart1_data.get('moon_sign', '?'),
            "moon_sign_ru": chart1_data.get('moon_sign_ru', '?'),
            "ascendant": chart1_data.get('ascendant', '?'),
            "ascendant_ru": chart1_data.get('ascendant_ru', '?'),
        },
        "chart2_summary": {
            "sun_sign": chart2_data.get('sun_sign', '?'),
            "sun_sign_ru": chart2_data.get('sun_sign_ru', '?'),
            "moon_sign": chart2_data.get('moon_sign', '?'),
            "moon_sign_ru": chart2_data.get('moon_sign_ru', '?'),
            "ascendant": chart2_data.get('ascendant', '?'),
            "ascendant_ru": chart2_data.get('ascendant_ru', '?'),
        },
        "aspects": aspects,
        "overlays": overlays,
        "analysis": full_analysis,
        "summary": summary,
        "relevant_chunks": [],
        "language": language,
        "relationship_context": relationship_context,
        "created_at": datetime.utcnow()
    }

async def chat_with_synastry_astrologer(
    question: str,
    chart_data: Dict[str, Any],
    full_analysis: str,
    chat_history: List[Dict[str, str]],
    language: str = "ru",
    relationship_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Чат с астрологом по синастрии
    """
    from app.services.search_service import search_chunks_by_query

    adapter = get_llm_adapter()

    chart1 = chart_data.get('chart1', {})
    chart2 = chart_data.get('chart2', {})
    aspects = chart_data.get('aspects', [])
    overlays = chart_data.get('overlays', {})

    lang = normalize_language(language)
    display = PLANET_DISPLAY_BY_LANG[lang]
    sign_key = 'sign' if lang == 'en' else f'sign_{lang}'
    sun_key = 'sun_sign' if lang == 'en' else f'sun_sign_{lang}'
    moon_key = 'moon_sign' if lang == 'en' else f'moon_sign_{lang}'
    asc_key = 'ascendant' if lang == 'en' else f'ascendant_{lang}'
    house_word = {'ru': 'дом', 'uk': 'будинок', 'en': 'house'}[lang]
    orb_word = {'ru': 'орб', 'uk': 'орбіс', 'en': 'orb'}[lang]
    partner_word = {'ru': 'Партнёра', 'uk': 'Партнера', 'en': 'Partner'}[lang]

    # RAG search on the question
    chunks = await search_chunks_by_query(question, top_k=10, book_id=JEFF_GREEN_BOOK_ID)
    if not chunks:
        chunks = await search_chunks_by_query(question, top_k=10)

    books_context = ""
    if chunks:
        books_context = {
            'ru': "\n=== ФРАГМЕНТЫ ПО ВОПРОСУ ===\n",
            'uk': "\n=== ФРАГМЕНТИ ЗА ЗАПИТОМ ===\n",
            'en': "\n=== BOOK FRAGMENTS ===\n",
        }[lang]
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text", "")[:400]
            book_title = chunk.get("book_title", "")
            books_context += f"[{i}] ({book_title}):\n{text}\n"

    def planets_str(planets_dict):
        result = ""
        for pn, pd in planets_dict.items():
            sign = pd.get(sign_key, pd.get('sign', '?'))
            house = pd.get('house', '?')
            degree = round(pd.get('degree', 0), 1)
            retro = " (Rx)" if pd.get('is_retrograde') else ""
            result += f"  {pn}: {sign} {degree}° {house_word} {house}{retro}\n"
        return result

    aspects_str = ""
    for asp in aspects:
        p1 = display.get(asp.get('planet1', ''), asp.get('planet1', ''))
        p2 = display.get(asp.get('planet2', ''), asp.get('planet2', ''))
        asp_word = asp.get(f'aspect_{lang}', asp.get('aspect', '')) if lang in ('ru', 'uk') else asp.get('aspect', '')
        orb = asp.get('orb', 0)
        aspects_str += f"  {p1} {asp_word} {p2} ({orb_word}: {orb}°)\n"

    overlays_str = ""
    p1_in_h2 = overlays.get('planets_1_in_houses_2', {})
    p2_in_h1 = overlays.get('planets_2_in_houses_1', {})
    for p, h in p1_in_h2.items():
        p_display = display.get(p, p)
        if lang == 'ru':
            overlays_str += f"  {p_display} Партнёра 1 в доме {h} Партнёра 2\n"
        elif lang == 'uk':
            overlays_str += f"  {p_display} Партнера 1 у будинку {h} Партнера 2\n"
        else:
            overlays_str += f"  {p_display} of Partner 1 in house {h} of Partner 2\n"
    for p, h in p2_in_h1.items():
        p_display = display.get(p, p)
        if lang == 'ru':
            overlays_str += f"  {p_display} Партнёра 2 в доме {h} Партнёра 1\n"
        elif lang == 'uk':
            overlays_str += f"  {p_display} Партнера 2 у будинку {h} Партнера 1\n"
        else:
            overlays_str += f"  {p_display} of Partner 2 in house {h} of Partner 1\n"

    context_instruction = get_relationship_context_prompt(relationship_context, language) if relationship_context else ""

    if lang == 'ru':
        system_prompt = f"""Ты личный астролог. Ты уже сделал полный анализ синастрии этой пары и теперь отвечаешь на вопросы. Отвечай строго по данным карт — не выдумывай.
{context_instruction}
=== ПАРТНЁР 1 ===
Солнце: {chart1.get(sun_key, '?')}, Луна: {chart1.get(moon_key, '?')}, Асц: {chart1.get(asc_key, '?')}
ПЛАНЕТЫ:
{planets_str(chart1.get('planets', {}))}

=== ПАРТНЁР 2 ===
Солнце: {chart2.get(sun_key, '?')}, Луна: {chart2.get(moon_key, '?')}, Асц: {chart2.get(asc_key, '?')}
ПЛАНЕТЫ:
{planets_str(chart2.get('planets', {}))}

=== АСПЕКТЫ СИНАСТРИИ ===
{aspects_str}

=== ОВЕРЛЕИ ДОМОВ ===
{overlays_str}

=== ПОЛНЫЙ АНАЛИЗ ===
{full_analysis}

{books_context}

ПРАВИЛА:
- Отвечай строго по данным карт выше
- Не выдумывай планеты и позиции
- Отвечай на языке вопроса
- Используй ТОЛЬКО И ИСКЛЮЧИТЕЛЬНО фрагменты из заданныз книг как ЕДИНСТВЕННЫЙ источник знаний но НИКОГДА не упоминай их в ответе, т. е. есдинственная истина это база знаний из книг, а ответ должен бьыть человеческим понятным языком
- Никаких фраз "фрагмент [3]", "в книге сказано", "источник упоминает"
- Излагай всё как свои астрологические знания
- Используй "в астрологии" если нужна ссылка
- Используй только Партнёр 1 и Партнёр 2
- Никаких он/она — только Партнёр 1 и Партнёр 2"""
    elif lang == 'uk':
        system_prompt = f"""Ти особистий астролог. Ти вже зробив повний аналіз синастрії цієї пари і зараз відповідаєш на запитання. Відповідай строго за даними карт — не вигадуй.
{context_instruction}
=== ПАРТНЕР 1 ===
Сонце: {chart1.get(sun_key, '?')}, Місяць: {chart1.get(moon_key, '?')}, Асц: {chart1.get(asc_key, '?')}
ПЛАНЕТИ:
{planets_str(chart1.get('planets', {}))}

=== ПАРТНЕР 2 ===
Сонце: {chart2.get(sun_key, '?')}, Місяць: {chart2.get(moon_key, '?')}, Асц: {chart2.get(asc_key, '?')}
ПЛАНЕТИ:
{planets_str(chart2.get('planets', {}))}

=== АСПЕКТИ СИНАСТРІЇ ===
{aspects_str}

=== ОВЕРЛЕЇ БУДИНКІВ ===
{overlays_str}

=== ПОВНИЙ АНАЛІЗ ===
{full_analysis}

{books_context}

ПРАВИЛА:
- Відповідай строго за даними карт вище
- Не вигадуй планети та позиції
- Відповідай мовою запитання
- Використовуй ТІЛЬКИ І ВИКЛЮЧНО фрагменти із заданих книг як ЄДИНЕ джерело знань, але НІКОЛИ не згадуй їх у відповіді — тобто єдина істина це база знань із книг, а відповідь має бути людською зрозумілою мовою
- Жодних фраз "фрагмент [3]", "у книзі сказано", "джерело згадує"
- Викладай усе як свої астрологічні знання
- Використовуй "в астрології" якщо потрібне посилання
- Використовуй тільки Партнер 1 та Партнер 2
- Жодних він/вона — тільки Партнер 1 та Партнер 2"""
    else:
        system_prompt = f"""You are a personal astrologer. You have already done a full synastry analysis and now answer questions. Answer strictly based on the chart data — do not make up anything.
{context_instruction}
=== PARTNER 1 ===
Sun: {chart1.get(sun_key, '?')}, Moon: {chart1.get(moon_key, '?')}, Asc: {chart1.get(asc_key, '?')}
PLANETS:
{planets_str(chart1.get('planets', {}))}

=== PARTNER 2 ===
Sun: {chart2.get(sun_key, '?')}, Moon: {chart2.get(moon_key, '?')}, Asc: {chart2.get(asc_key, '?')}
PLANETS:
{planets_str(chart2.get('planets', {}))}

=== SYNASTRY ASPECTS ===
{aspects_str}

=== HOUSE OVERLAYS ===
{overlays_str}

=== FULL ANALYSIS ===
{full_analysis}

{books_context}

RULES:
- Answer strictly based on chart data above
- Do not make up planets or positions
- Answer in the language of the question
- Use fragments as knowledge source but NEVER mention them in the answer
- Do NOT say "Fragment [3]", "the book says", "the source mentions"
- Present all insights as your own astrological expertise
- Use "in astrology" if a reference is needed
- Use only Partner 1 and Partner 2
- No he/she — only Partner 1 and Partner 2"""

    messages = [{"role": "system", "content": system_prompt}]
    for msg in chat_history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": question})

    answer = await adapter.generate_with_messages(messages, language)

    return {
        "answer": answer,
        "relevant_chunks": chunks
    }