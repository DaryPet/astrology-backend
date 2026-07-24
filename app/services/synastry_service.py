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
    ZODIAC_SIGNS_EN,
    PLANET_STEM_RU,
    ASPECT_STEM_RU,
    PLANET_STEM_EN,
    ASPECT_STEM_EN,
    _ASPECT_HEADER_RE,
)


JEFF_GREEN_BOOK_ID = 26

PLANET_RU = {
    'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий',
    'Venus': 'Венера', 'Mars': 'Марс', 'Jupiter': 'Юпитер',
    'Saturn': 'Сатурн', 'Uranus': 'Уран', 'Neptune': 'Нептун',
    'Pluto': 'Плутон', 'NorthNode': 'Северный Узел',
    'SouthNode': 'Южный Узел', 'Chiron': 'Хирон',
    'Lilith': 'Лилит', 'Ascendant': 'Асцендент',
}

# Английские имена планет в тексте LLM совпадают с этими значениями буквально
# (Sun, Moon, ..., "North Node") — в отличие от PLANET_RU это не перевод,
# а просто нормализованное отображаемое имя (NorthNode -> "North Node").
PLANET_EN = {
    'Sun': 'Sun', 'Moon': 'Moon', 'Mercury': 'Mercury',
    'Venus': 'Venus', 'Mars': 'Mars', 'Jupiter': 'Jupiter',
    'Saturn': 'Saturn', 'Uranus': 'Uranus', 'Neptune': 'Neptune',
    'Pluto': 'Pluto', 'NorthNode': 'North Node',
    'SouthNode': 'South Node', 'Chiron': 'Chiron',
    'Lilith': 'Lilith', 'Ascendant': 'Ascendant',
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
    is_ru = language == 'ru'
    connector = r"\s+в\s+" if is_ru else r"\s+in\s+"

    valid_pairs = set()
    for chart in (chart1_data, chart2_data):
        for p_name, p_data in chart.get('planets', {}).items():
            planet_name = PLANET_RU.get(p_name) if is_ru else PLANET_EN.get(p_name)
            sign = p_data.get('sign_ru') if is_ru else p_data.get('sign')
            if planet_name and sign:
                valid_pairs.add((planet_name, sign))
        asc_sign = chart.get('ascendant_ru') if is_ru else chart.get('ascendant')
        if asc_sign:
            valid_pairs.add(('Асцендент' if is_ru else 'Ascendant', asc_sign))

    if not valid_pairs:
        return []

    planet_names = PLANET_RU.values() if is_ru else PLANET_EN.values()
    sign_forms = SIGN_PREPOSITIONAL_TO_NOMINATIVE if is_ru else ZODIAC_SIGNS_EN
    planet_pattern = "|".join(re.escape(n) for n in planet_names)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")

    mismatches = []
    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = SIGN_PREPOSITIONAL_TO_NOMINATIVE[sign_form] if is_ru else sign_form
        if (planet_name, sign_nom) not in valid_pairs:
            joiner = "в" if is_ru else "in"
            mismatches.append(f"{planet_name} {joiner} {sign_form}")

    return mismatches


_PARTNER_MARKER_RE_SRC = r"[Пп]артн[её]р\w*\s*(1|2)"
_PARTNER_MARKER_RE_SRC_EN = r"[Pp]artner\s*(1|2)"


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
    is_ru = language == 'ru'
    connector = r"\s+в\s+" if is_ru else r"\s+in\s+"
    joiner = "в" if is_ru else "in"

    def correct_sign_for(planet_name: str, chart_data: Dict[str, Any]) -> Optional[str]:
        asc_name = 'Асцендент' if is_ru else 'Ascendant'
        if planet_name == asc_name:
            return chart_data.get('ascendant_ru') if is_ru else chart_data.get('ascendant')
        for p_name, p_data in chart_data.get('planets', {}).items():
            translated = PLANET_RU.get(p_name) if is_ru else PLANET_EN.get(p_name)
            if translated == planet_name:
                return p_data.get('sign_ru') if is_ru else p_data.get('sign')
        return None

    valid_pairs = set()
    for chart in (chart1_data, chart2_data):
        for p_name, p_data in chart.get('planets', {}).items():
            planet_name = PLANET_RU.get(p_name) if is_ru else PLANET_EN.get(p_name)
            sign = p_data.get('sign_ru') if is_ru else p_data.get('sign')
            if planet_name and sign:
                valid_pairs.add((planet_name, sign))
        asc_sign = chart.get('ascendant_ru') if is_ru else chart.get('ascendant')
        if asc_sign:
            valid_pairs.add(('Асцендент' if is_ru else 'Ascendant', asc_sign))

    if not valid_pairs:
        return text, []

    planet_names = PLANET_RU.values() if is_ru else PLANET_EN.values()
    sign_forms = SIGN_PREPOSITIONAL_TO_NOMINATIVE if is_ru else ZODIAC_SIGNS_EN
    planet_pattern = "|".join(re.escape(n) for n in planet_names)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")
    partner_re = re.compile(_PARTNER_MARKER_RE_SRC if is_ru else _PARTNER_MARKER_RE_SRC_EN)

    unresolved: List[str] = []
    pieces: List[str] = []
    last_end = 0

    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = SIGN_PREPOSITIONAL_TO_NOMINATIVE[sign_form] if is_ru else sign_form
        if (planet_name, sign_nom) in valid_pairs:
            continue  # верно, не трогаем

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

        correct_form = SIGN_NOMINATIVE_TO_PREPOSITIONAL.get(correct_sign, correct_sign) if is_ru else correct_sign
        pieces.append(text[last_end:m.start()])
        pieces.append(f"{planet_name} {joiner} {correct_form}")
        last_end = m.end()

    pieces.append(text[last_end:])
    return "".join(pieces), unresolved


# Синастрия-специфичная пометка партнёра рядом с планетой в заголовке
# аспекта — в отличие от PLANET_STEM_RU/ASPECT_STEM_RU (вынесены в
# text_verification.py), это понятие есть только у синастрии (два чарта),
# натал/транзиты его не имеют — остаётся здесь.
_ASPECT_PARTNER_MARKER_RE = re.compile(r"[Пп]артн[её]р\w*\s*(1|2)")
_ASPECT_PARTNER_MARKER_RE_EN = re.compile(r"[Pp]artner\s*(1|2)")


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
    is_ru = language == 'ru'
    partner_re = _ASPECT_PARTNER_MARKER_RE if is_ru else _ASPECT_PARTNER_MARKER_RE_EN
    planet_stems = PLANET_STEM_RU if is_ru else PLANET_STEM_EN

    partner_markers = [(m.start(), m.group(1)) for m in partner_re.finditer(header)]
    if len(partner_markers) < 2:
        return None

    planet_hits = []  # (position, planet_en)
    for planet_en, stem_pattern in planet_stems.items():
        for m in re.finditer(stem_pattern, header):
            planet_hits.append((m.start(), planet_en))
    if len(planet_hits) != 2:
        return None  # ожидаем ровно две планеты в заголовке — иначе неоднозначно

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
    aspect_stems = ASPECT_STEM_RU if language == 'ru' else ASPECT_STEM_EN
    partner_word = "Партнёра" if language == 'ru' else "Partner"

    # planet1 в aspects — всегда карта 1 (Партнёр 1), planet2 — всегда карта 2
    # (Партнёр 2): так строит calculate_synastry (astrology_v2.py), порядок
    # не варьируется. Один и тот же неупорядоченный набор планет может дать
    # ДВЕ разных записи (Сатурн,Хирон) и (Хирон,Сатурн) — это два разных
    # реальных аспекта, ключ по упорядоченной паре их не путает.
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
            continue  # ноль или несколько слов аспекта в одном заголовке — пропускаем

        pair = (assigned['1'], assigned['2'])
        true_aspect = truth.get(pair)
        if true_aspect is None:
            continue  # такой пары нет в расчёте вообще — не наш случай, не считаем ошибкой

        stated_aspect = aspect_hits[0][1]
        if stated_aspect != true_aspect:
            if language == 'ru':
                p1_name = PLANET_RU.get(pair[0], pair[0])
                p2_name = PLANET_RU.get(pair[1], pair[1])
                true_label = next((a.get('aspect_ru') for a in aspects if a.get('planet1') == pair[0] and a.get('planet2') == pair[1]), true_aspect)
            else:
                p1_name = PLANET_EN.get(pair[0], pair[0])
                p2_name = PLANET_EN.get(pair[1], pair[1])
                true_label = true_aspect
            mismatches.append(
                f"{p1_name} {partner_word} 1 — {p2_name} {partner_word} 2: "
                f"{'в тексте' if language == 'ru' else 'in text'} «{stated_aspect}», "
                f"{'на деле' if language == 'ru' else 'actually'} «{true_label}» "
                f"({'заголовок' if language == 'ru' else 'header'}: {header.strip()[:120]})"
            )

    return mismatches


# Фразы-отсылки вместо реального разбора ("разобрано выше" и т.п.) — сигнал,
# что аспект формально упомянут, но не получил своих 200-300 слов (найдено
# на живых прогонах 2026-07-23, см. plans/ — модель ссылается на другой
# раздел вместо повторного разбора).
_COP_OUT_PHRASES_RU = [
    "разобран", "уже обсужда", "уже опис", "уже сказ", "уже говорили",
    "смотри выше", "см. выше", "как уже", "как мы уже",
]
_COP_OUT_PHRASES_EN = [
    "already covered", "already discussed", "as covered above",
    "as mentioned above", "see above", "as we discussed", "see the",
]

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
    is_ru = language == 'ru'
    stems = PLANET_STEM_RU if is_ru else PLANET_STEM_EN
    p1_pattern = stems.get(planet1_en, re.escape(PLANET_RU.get(planet1_en, planet1_en) if is_ru else planet1_en))
    p2_pattern = stems.get(planet2_en, re.escape(PLANET_RU.get(planet2_en, planet2_en) if is_ru else planet2_en))

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
    is_ru = language == 'ru'
    cop_out_phrases = _COP_OUT_PHRASES_RU if is_ru else _COP_OUT_PHRASES_EN

    def label_for(asp: Dict[str, Any]) -> str:
        p1 = PLANET_RU.get(asp.get('planet1'), asp.get('planet1')) if is_ru else PLANET_EN.get(asp.get('planet1'), asp.get('planet1'))
        p2 = PLANET_RU.get(asp.get('planet2'), asp.get('planet2')) if is_ru else PLANET_EN.get(asp.get('planet2'), asp.get('planet2'))
        asp_word = asp.get('aspect_ru') if is_ru else asp.get('aspect')
        partner_word = "Партнёра" if is_ru else "Partner"
        return f"{p1} ({partner_word} 1) {asp_word} {p2} ({partner_word} 2) (орб {asp.get('orb')}°)" if is_ru \
            else f"{p1} ({partner_word} 1) {asp_word} {p2} ({partner_word} 2) (orb {asp.get('orb')}°)"

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
    
    if language == 'ru':
        planet1 = PLANET_RU.get(planet1, planet1)
        planet2 = PLANET_RU.get(planet2, planet2)
    
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

    # 1. Расчёт аспектов синастрии (если не переданы напрямую)
    if not aspects:
        synastry_result = calculate_synastry(chart1_data, chart2_data)
        aspects = synastry_result.get('aspects', [])

    # 1.5 Расчёт house overlay (если не передан)
    if not overlays:
        overlays = {"planets_1_in_houses_2": {}, "planets_2_in_houses_1": {}}
        
        houses_2 = chart2_data.get('houses', {})
        houses_1 = chart1_data.get('houses', {})
        
        # Планеты партнера 1 в домах партнера 2
        for p_name, p_data in chart1_data.get('planets', {}).items():
            lon = p_data.get('full_degree', 0)
            house_num = get_house_for_longitude(lon, houses_2)
            if house_num:
                overlays["planets_1_in_houses_2"][p_name] = house_num
        
        # Планеты партнера 2 в домах партнера 1
        for p_name, p_data in chart2_data.get('planets', {}).items():
            lon = p_data.get('full_degree', 0)
            house_num = get_house_for_longitude(lon, houses_1)
            if house_num:
                overlays["planets_2_in_houses_1"][p_name] = house_num

    # 2. Эксперимент plans/synastry-before-batching.md: все аспекты, без среза.
    # calculate_synastry (astrology_v2.py) уже сортирует их тем же приоритетом.
    top_aspects = aspects

    print(f"[full_synastry_analysis_v2] Total aspects: {len(aspects)}, sent to RAG search: {len(top_aspects)}")

    # 3. Параллельный RAG-поиск по аспектам
    # Семафор ограничивает число одновременных запросов к Supabase. Без него
    # asyncio.gather запускает все ~64 задачи разом, а run_sync_in_thread
    # (asyncio.to_thread) держит пул максимум ~32 потока — при 44 аспектах
    # это на реальном прогоне давало 34 из 64 запросов с "[Errno 35] Resource
    # temporarily unavailable" (план: plans/synastry-before-batching.md).
    # Семафор не уменьшает охват — ищутся всё те же все аспекты и планеты,
    # просто не одним залпом.
    search_semaphore = asyncio.Semaphore(12)

    async def search_aspect(asp: Dict) -> tuple:
        p1 = asp.get('planet1', '')
        p2 = asp.get('planet2', '')
        asp_type = asp.get('aspect', '')
        orb = asp.get('orb', 0)
        asp_ru = asp.get('aspect_ru', asp_type)

        # Строим поисковый запрос
        query = f"{p1} {asp_type} {p2} synastry"
        async with search_semaphore:
            chunks = await search_chunks_by_query(query, top_k=top_k_per_book, book_id=JEFF_GREEN_BOOK_ID)
        return f"{p1} {asp_ru} {p2} (орб: {orb}°)", chunks

    # 4. Параллельный RAG-поиск по ключевым планетам
    key_planets = ['Pluto', 'NorthNode', 'SouthNode', 'Saturn', 'Sun', 'Moon', 'Ascendant', 'Venus', 'Mars', 'Jupiter']

    async def search_planet_synastry(planet_name: str, chart_num: int, chart_data: Dict) -> tuple:
        # Проверяем есть ли планета в карте
        planets = chart_data.get('planets', {})
        if planet_name not in planets and planet_name != 'Ascendant':
            return f"Planet {planet_name} (Chart {chart_num})", []

        query = f"{planet_name} synastry partner"
        async with search_semaphore:
            chunks = await search_chunks_by_query(query, top_k=top_k_per_book, book_id=JEFF_GREEN_BOOK_ID)
        return f"Planet {planet_name} (Chart {chart_num})", chunks

    # Запуск параллельного поиска
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

    # 5. Сборка промпта
    synastry_template = get_template("synastry", language, mode)
    
    # Add relationship context to prompt
    context_prompt = get_relationship_context_prompt(relationship_context, language)
    if context_prompt:
        synastry_template = synastry_template + context_prompt

    # Подготовка списка аспектов
    aspects_list = []
    for asp in aspects:
        p1 = asp.get('planet1', '?')
        p2 = asp.get('planet2', '?')
        asp_ru = asp.get('aspect_ru', asp.get('aspect', '?'))
        orb = asp.get('orb', 0)

        # Берем знаки из самого аспекта (они уже добавлены на бэкенде/UI)
        p1_sign = asp.get('planet1_sign', '')
        p2_sign = asp.get('planet2_sign', '')

        # Fallback: если в аспекте нет знаков, берем из карт (для локально рассчитанных аспектов)
        if not p1_sign and chart1_data and 'planets' in chart1_data:
            p1_planet_data = chart1_data['planets'].get(p1, {})
            p1_sign = p1_planet_data.get('sign_ru', p1_planet_data.get('sign', ''))

        if not p2_sign and chart2_data and 'planets' in chart2_data:
            p2_planet_data = chart2_data['planets'].get(p2, {})
            p2_sign = p2_planet_data.get('sign_ru', p2_planet_data.get('sign', ''))

        # Переводим названия планет на русский язык если нужно
        if language == 'ru':
            p1_display = PLANET_RU.get(p1, p1)
            p2_display = PLANET_RU.get(p2, p2)
        else:
            p1_display = p1
            p2_display = p2
            
        aspects_list.append(f"ПАРТНЕР1:{p1_display} ({p1_sign}) {asp_ru} ПАРТНЕР2:{p2_display} ({p2_sign}) (орб: {orb}°)")

    aspects_str = "\n".join(aspects_list) if aspects_list else "Нет аспектов"

    # Формируем информацию об оверлеях
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

    # Сборка фрагментов из книг - аспекты
    books_content = "\n=== ФРАГМЕНТЫ ПО АСПЕКТАМ СИНАСТРИИ ===\n"
    # Детерминированный учёт источников по каждому аспекту — сколько чанков
    # и из какой книги реально нашлось. Не через LLM (модель не умеет надёжно
    # считать метаданные своего же входа), а прямо из результатов поиска.
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

    # Сборка фрагментов из книг - планеты
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

    # Подставляем в шаблон
    prompt = synastry_template
    prompt = prompt.replace("{aspects_list}", aspects_str)
    prompt = prompt.replace("{books_content}", books_content)

    # Данные карт идут в промпт один раз, через плейсхолдеры шаблона ниже
    # (раньше дублировались ещё и блоком "=== КАРТА N ===" — план
    # plans/synastry-before-batching.md, п.4: дубли и разноязычные записи
    # знака в одной строке путают модель на этапе генерации).
    planets1 = chart1_data.get('planets', {})
    houses1 = chart1_data.get('houses', {})
    planets2 = chart2_data.get('planets', {})
    houses2 = chart2_data.get('houses', {})

    # Подставляем данные в шаблон (для совместимости с {planets_1}, {houses_1} и т.д.)
    prompt = prompt.replace("{sun_sign_1}", chart1_data.get('sun_sign_ru', '?'))
    prompt = prompt.replace("{moon_sign_1}", chart1_data.get('moon_sign_ru', '?'))
    prompt = prompt.replace("{ascendant_1}", chart1_data.get('ascendant_ru', '?'))

    # Формируем строки планет и домов для шаблона
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

    # 6. Вызов LLM
    print(f"[full_synastry_analysis_v2] Sending prompt to LLM (~{len(prompt)//4} tokens estimated)")

    # Один вызов — без перегенерации всего документа при найденной ошибке.
    # Раньше при расхождении позиций код пересылал весь ~240k-токенный промпт
    # заново (до 3 раз) — это давало ~15 минут на запрос и не гарантированно
    # чинило суть (план: plans/synastry-before-batching.md, п.5). Вместо этого
    # ошибка чинится мгновенно строковой заменой по словарю карты.
    full_analysis = ""
    try:
        full_analysis = await adapter.generate(prompt, language)

        if language in ('ru', 'en'):
            full_analysis, unresolved = fix_fabricated_planet_positions(
                full_analysis, chart1_data, chart2_data, language=language
            )
            if unresolved:
                print(f"[full_synastry_analysis_v2] Unresolved position mismatches (left as-is): {unresolved}")

            # Только детекция (план: plans/synastry-aspect-type-verification.md)
            # — текст не трогаем, чтобы не скрывать реальную частоту ошибки
            # до решения о починке.
            fabricated_aspects = find_fabricated_aspect_types(full_analysis, aspects, language=language)
            if fabricated_aspects:
                print(f"[full_synastry_analysis_v2] Fabricated aspect types detected (not fixed): {fabricated_aspects}")

            # Только детекция, по тексту (не по markdown-заголовкам) — текст
            # ответа не трогаем и ничего не дописываем пользователю.
            undercovered = find_undercovered_aspects(full_analysis, aspects, language=language)
            if undercovered:
                print(f"[full_synastry_analysis_v2] Undercovered aspects detected (not filled): {undercovered}")
    except Exception as e:
        full_analysis = f"Ошибка анализа: {str(e)}"
        print(f"[full_synastry_analysis_v2] LLM error: {e}")

    # 6.5 Сводка источников по аспектам — сколько чанков и из какой книги
    # реально нашлось на каждый аспект. Точные цифры из кода, не из LLM.
    # Только в серверный лог: в пользовательский текст не подмешивать.
    print("[full_synastry_analysis_v2] Источники по аспектам:")
    for label, count, book_titles, error in aspect_sources_debug:
        if error:
            print(f"  {label}: поиск не выполнен ({error})")
            continue
        titles_str = ", ".join(book_titles) if book_titles else "—"
        print(f"  {label}: {count} чанков, книги: {titles_str}")

    # 7. Краткое резюме (первые 500 символов)
    summary = full_analysis[:500].rsplit('. ', 1)[0] if len(full_analysis) > 500 else full_analysis

    # 8. Возврат результата
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

    # RAG поиск по вопросу
    chunks = await search_chunks_by_query(question, top_k=10, book_id=JEFF_GREEN_BOOK_ID)
    if not chunks:
        chunks = await search_chunks_by_query(question, top_k=10)

    books_context = ""
    if chunks:
        books_context = "\n=== ФРАГМЕНТЫ ПО ВОПРОСУ ===\n" if language == 'ru' else "\n=== BOOK FRAGMENTS ===\n"
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text", "")[:400]
            book_title = chunk.get("book_title", "")
            books_context += f"[{i}] ({book_title}):\n{text}\n"

    def planets_str(planets_dict):
        result = ""
        for pn, pd in planets_dict.items():
            sign_ru = pd.get('sign_ru', pd.get('sign', '?'))
            house = pd.get('house', '?')
            degree = round(pd.get('degree', 0), 1)
            retro = " (Rx)" if pd.get('is_retrograde') else ""
            result += f"  {pn}: {sign_ru} {degree}° дом {house}{retro}\n"
        return result

    aspects_str = ""
    for asp in aspects:
        p1 = PLANET_RU.get(asp.get('planet1', ''), asp.get('planet1', ''))
        p2 = PLANET_RU.get(asp.get('planet2', ''), asp.get('planet2', ''))
        asp_ru = asp.get('aspect_ru', asp.get('aspect', ''))
        orb = asp.get('orb', 0)
        aspects_str += f"  {p1} {asp_ru} {p2} (орб: {orb}°)\n"

    overlays_str = ""
    p1_in_h2 = overlays.get('planets_1_in_houses_2', {})
    p2_in_h1 = overlays.get('planets_2_in_houses_1', {})
    for p, h in p1_in_h2.items():
        if language == 'ru':
            overlays_str += f"  {PLANET_RU.get(p, p)} Партнёра 1 в доме {h} Партнёра 2\n"
        else:
            overlays_str += f"  {p} of Partner 1 in house {h} of Partner 2\n"
    for p, h in p2_in_h1.items():
        if language == 'ru':
            overlays_str += f"  {PLANET_RU.get(p, p)} Партнёра 2 в доме {h} Партнёра 1\n"
        else:
            overlays_str += f"  {p} of Partner 2 in house {h} of Partner 1\n"

    if language == 'ru':
        context_instruction = get_relationship_context_prompt(relationship_context, language) if relationship_context else ""
        system_prompt = f"""Ты личный астролог. Ты уже сделал полный анализ синастрии этой пары и теперь отвечаешь на вопросы. Отвечай строго по данным карт — не выдумывай.
{context_instruction}
=== ПАРТНЁР 1 ===
Солнце: {chart1.get('sun_sign_ru', '?')}, Луна: {chart1.get('moon_sign_ru', '?')}, Асц: {chart1.get('ascendant_ru', '?')}
ПЛАНЕТЫ:
{planets_str(chart1.get('planets', {}))}

=== ПАРТНЁР 2 ===
Солнце: {chart2.get('sun_sign_ru', '?')}, Луна: {chart2.get('moon_sign_ru', '?')}, Асц: {chart2.get('ascendant_ru', '?')}
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
    else:
        context_instruction = get_relationship_context_prompt(relationship_context, language) if relationship_context else ""
        system_prompt = f"""You are a personal astrologer. You have already done a full synastry analysis and now answer questions. Answer strictly based on the chart data — do not make up anything.
{context_instruction}
=== PARTNER 1 ===
Sun: {chart1.get('sun_sign_ru', '?')}, Moon: {chart1.get('moon_sign_ru', '?')}, Asc: {chart1.get('ascendant_ru', '?')}
PLANETS:
{planets_str(chart1.get('planets', {}))}

=== PARTNER 2 ===
Sun: {chart2.get('sun_sign_ru', '?')}, Moon: {chart2.get('moon_sign_ru', '?')}, Asc: {chart2.get('ascendant_ru', '?')}
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