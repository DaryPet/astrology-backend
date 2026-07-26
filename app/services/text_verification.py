"""Общие словари/регулярки для сверки текста LLM (RU и EN) с реальными
астрологическими данными — знаки, планеты, аспекты, поиск жирных
markdown-заголовков.

Вынесено из synastry_service.py (план: plans/synastry-aspect-type-verification.md),
чтобы не дублировать при появлении такой же сверки для натальных карт,
транзитов, прогрессий — сами словари не специфичны для синастрии.

Синастрия-специфичная часть (привязка планеты к "Партнёру 1/2" / "Partner N")
здесь не живёт — это осталось в synastry_service.py, натал/транзиты этого
понятия не имеют вообще.

Русский и английский асимметричны нарочно: русский склоняет существительные
по падежу ("Хирона", "в оппозиции", "секстиле") — отсюда стемы с \\w* и
отдельная таблица предложный->именительный для знаков. Английский падежей не
знает — "Moon", "Chiron", "Square" пишутся одинаково в любой позиции
предложения, поэтому там просто точное слово в границах \\b, без стемов и без
таблицы форм знака.
"""
import re
from typing import Any, Dict, List, Optional

# ============================================================
# Русский
# ============================================================

# Предложный падеж знаков зодиака ("Луна В РАКЕ") -> именительный ("Рак"),
# как он хранится в chart_data (sign_ru). Позиции планет детерминированы —
# сверяем текст LLM с этим словарём вместо доверия модели на слово.
SIGN_PREPOSITIONAL_TO_NOMINATIVE = {
    'Овне': 'Овен', 'Тельце': 'Телец', 'Близнецах': 'Близнецы',
    'Раке': 'Рак', 'Льве': 'Лев', 'Деве': 'Дева',
    'Весах': 'Весы', 'Скорпионе': 'Скорпион', 'Стрельце': 'Стрелец',
    'Козероге': 'Козерог', 'Водолее': 'Водолей', 'Рыбах': 'Рыбы',
}

SIGN_NOMINATIVE_TO_PREPOSITIONAL = {v: k for k, v in SIGN_PREPOSITIONAL_TO_NOMINATIVE.items()}

# Стемы русских названий планет — не точная форма, а начало слова, потому что
# в тексте планета склоняется по падежу ("Хирона", "Северным Узлом"), а не
# стоит в именительном. \w* добирает окончание.
PLANET_STEM_RU = {
    'Sun': r'Со?лнц\w*', 'Moon': r'Лун\w*', 'Mercury': r'Меркури\w*',
    'Venus': r'Венер\w*', 'Mars': r'Марс\w*', 'Jupiter': r'Юпитер\w*',
    'Saturn': r'Сатурн\w*', 'Uranus': r'Уран\w*', 'Neptune': r'Нептун\w*',
    'Pluto': r'Плутон\w*', 'NorthNode': r'Северн\w*\s+[Уу]зл\w*',
    'SouthNode': r'Южн\w*\s+[Уу]зл\w*', 'Chiron': r'Хирон\w*',
    'Lilith': r'Лилит\w*', 'Ascendant': r'Асцендент\w*',
}

# Стемы аспектов — та же причина: "в оппозиции", "Соединение", "секстиле" —
# разные падежи одного из пяти слов. Ключ — как 'aspect' в данных из
# calculate_synastry (astrology_v2.py).
ASPECT_STEM_RU = {
    'Conjunction': r'[Сс]оединени\w*', 'Opposition': r'[Оо]ппозици\w*',
    'Trine': r'[Тт]ригон\w*', 'Square': r'[Кк]вадрат\w*',
    'Sextile': r'[Сс]екстил\w*',
}

# ============================================================
# English
# ============================================================

# Английский не склоняет существительные — знак в любом месте предложения
# пишется одинаково (в отличие от русского "в Раке"), отдельная таблица форм
# не нужна: слово из chart_data.sign и слово в тексте совпадают буквально.
ZODIAC_SIGNS_EN = {
    "Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
    "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces",
}

# Английские имена планет в тексте LLM совпадают с ключами chart_data.planets
# буквально (Moon, Chiron, ...) — переводной словарь, как PLANET_RU, не нужен.
# \b удерживает от случайных совпадений внутри других слов.
PLANET_STEM_EN = {
    'Sun': r'\bSun\b', 'Moon': r'\bMoon\b', 'Mercury': r'\bMercury\b',
    'Venus': r'\bVenus\b', 'Mars': r'\bMars\b', 'Jupiter': r'\bJupiter\b',
    'Saturn': r'\bSaturn\b', 'Uranus': r'\bUranus\b', 'Neptune': r'\bNeptune\b',
    'Pluto': r'\bPluto\b', 'NorthNode': r'\bNorth\s+Node\b',
    'SouthNode': r'\bSouth\s+Node\b', 'Chiron': r'\bChiron\b',
    'Lilith': r'\bLilith\b', 'Ascendant': r'\bAscendant\b',
}

ASPECT_STEM_EN = {
    'Conjunction': r'\bConjunction\b', 'Opposition': r'\bOpposition\b',
    'Trine': r'\bTrine\b', 'Square': r'\bSquare\b', 'Sextile': r'\bSextile\b',
}

# ============================================================
# Языко-нейтральное
# ============================================================

# Жирный markdown-заголовок — общий паттерн, не специфичный ни для языка, ни
# для аспектов синастрии; модель им же оформляет разделы в натале/транзитах.
_ASPECT_HEADER_RE = re.compile(r"\*\*([^*\n]{1,240})\*\*")


# ============================================================
# Отображаемые имена планет (RU/EN) — общие для всех методов
# ============================================================
# ДУБЛИРУЮТ одноимённые словари в synastry_service.py — не перенос:
# synastry_service.py остаётся полностью нетронутым (он рабочий, в проде, и
# его код здесь сознательно не трогается). Причина дублирования, а не общего
# импорта — цикл: synastry_service.py сам импортирует analysis_service.py
# (search_chunks_all_books, generate_summary), поэтому analysis_service.py не
# может импортировать эти константы из synastry_service.py напрямую, а без
# такого импорта их проще продублировать здесь для прогрессий, чем
# рефакторить синастрию. Если оба места разъедутся терминологией планет —
# это осознанный компромисс этого ТЗ, план:
# app/services/specs/progressions_synastry_pattern_plan.md. Сведение к одному
# источнику — отдельная задача на будущее, не в этом ТЗ.

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


# ============================================================
# Покрытие аспектов текстом (не по markdown, по прозе) — общее
# ============================================================
# Тоже дублирует synastry_service.py, по той же причине (см. выше) — не
# перенос, synastry_service.py не меняется.

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


# ============================================================
# Слои одной карты (прогрессивная/натальная, транзитная/натальная...)
# ============================================================
# Обобщение синастрийного паттерна "Партнёр 1/2" (synastry_service.py) на
# методы с ОДНОЙ картой, но несколькими её "версиями" одной и той же планеты
# — прогрессивная позиция vs натальная, позже транзитная vs натальная.
# Ключевое отличие от синастрии: там маркер "Партнёра N" стоит ПОСЛЕ планеты
# ("Луна Партнёра 1"), а здесь слой-слово стоит ПЕРЕД планетой ("прогрессивная
# Луна", "progressed Moon", "natal Sun") в обоих языках — поэтому функции
# ниже не копии синастрийных, а параметризованы направлением поиска маркера
# (marker_side). План: app/services/specs/progressions_synastry_pattern_plan.md.

LAYER_MARKER_PATTERNS = {
    'ru': {
        'progressed': r'[Пп]рогрессивн\w*',
        'natal': r'[Нн]атальн\w*',
        # заготовка на будущее (транзиты) — этим ТЗ нигде не подключается
        'transit': r'[Тт]ранзитн\w*',
    },
    'en': {
        'progressed': r'\b[Pp]rogressed\b',
        'natal': r'\b[Nn]atal\b',
        'transit': r'\b[Tt]ransit(?:ing)?\b',
    },
}


def attribute_header_planets_to_layers(
    header: str,
    language: str,
    layer_keys: "tuple[str, str]",
    marker_side: str = 'before',
) -> Optional[Dict[str, str]]:
    """
    Обобщение attribute_header_planets_to_partners (synastry_service.py) на
    произвольные текстовые слои одной карты вместо Партнёра 1/2. Возвращает
    {layer_key: planet_en}, если в заголовке ровно по одному маркеру каждого
    запрошенного слоя и ровно две планеты, однозначно приписанные каждая к
    своему ближайшему маркеру — иначе None.

    marker_side='before' (по умолчанию, для прогрессий/транзитов) — берём
    ближайший ПРЕДШЕСТВУЮЩИЙ маркер относительно планеты. marker_side='after'
    воспроизвёл бы синастрийную логику ("Партнёра N" после планеты) — здесь не
    используется, оставлено на случай переиспользования этой функции синастрией
    в будущем рефакторинге.
    """
    is_ru = language == 'ru'
    markers = LAYER_MARKER_PATTERNS['ru' if is_ru else 'en']
    planet_stems = PLANET_STEM_RU if is_ru else PLANET_STEM_EN

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
        return None  # ожидаем ровно две планеты в заголовке — иначе неоднозначно
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
    {отображаемое имя планеты: знак} из carte-like словаря вида
    {'planets': {planet_en: {'sign':, 'sign_ru':}}, 'ascendant':, 'ascendant_ru':}
    — форма, общая для натальной карты и для progressed_planets/prog_asc в
    progressions_analysis (analysis_service.py). Общий строительный блок для
    find_fabricated_positions_layered/fix_fabricated_positions_layered.
    """
    is_ru = language == 'ru'
    result: Dict[str, str] = {}
    for p_name, p_data in (chart_like.get('planets') or {}).items():
        display = PLANET_RU.get(p_name) if is_ru else PLANET_EN.get(p_name)
        sign = p_data.get('sign_ru') if is_ru else p_data.get('sign')
        if display and sign:
            result[display] = sign
    asc_sign = chart_like.get('ascendant_ru') if is_ru else chart_like.get('ascendant')
    if asc_sign:
        result['Асцендент' if is_ru else 'Ascendant'] = asc_sign
    return result


def _nearest_preceding_layer(preceding_text: str, language: str, layer_keys) -> Optional[str]:
    """Ближайший к концу окна маркер одного из layer_keys, предшествующий найденной фразе."""
    is_ru = language == 'ru'
    markers = LAYER_MARKER_PATTERNS['ru' if is_ru else 'en']
    best_key, best_pos = None, -1
    for key in layer_keys:
        pattern = markers.get(key)
        if not pattern:
            continue
        matches = list(re.finditer(pattern, preceding_text))
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
    Обобщение find_fabricated_planet_positions (synastry_service.py) на N
    именованных слоёв ОДНОЙ карты (например {'progressed': prog_chart_like,
    'natal': natal_chart}) вместо двух партнёров. Только детекция, текст не
    трогает — правку делает fix_fabricated_positions_layered, и не по тем же
    критериям (см. её докстринг).

    Возвращает два списка (строки для лога):
    - "fabricated" — знака нет НИ В ОДНОМ слое вообще (union всех слоёв, как в
      синастрии) — это по-настоящему выдуманная позиция.
    - "layer_confused" — знак существует у этой планеты, но в ДРУГОМ слое, чем
      назвал ближайший предшествующий маркер ("прогрессивная Луна в Раке", хотя
      Рак — натальный знак Луны). Это не выдумка данных, а перепутанная
      подпись слоя — сообщается отдельно и НИКОГДА не используется для
      авто-фикса: промпт сам провоцирует соседство обеих позиций одной и той
      же планеты (маркер смены знака "в натале была в X"), и правка по этому
      критерию рисковала бы переписать корректную фразу.
    """
    is_ru = language == 'ru'
    connector = r"\s+в\s+" if is_ru else r"\s+in\s+"
    joiner = "в" if is_ru else "in"

    per_layer_pairs = {key: _extract_layer_planet_signs(chart_like, language) for key, chart_like in layers.items()}
    all_pairs = set()
    for pairs in per_layer_pairs.values():
        for planet_name, sign in pairs.items():
            all_pairs.add((planet_name, sign))

    if not all_pairs:
        return {'fabricated': [], 'layer_confused': []}

    planet_names_display = PLANET_RU.values() if is_ru else PLANET_EN.values()
    sign_forms = SIGN_PREPOSITIONAL_TO_NOMINATIVE if is_ru else ZODIAC_SIGNS_EN
    planet_pattern = "|".join(re.escape(n) for n in planet_names_display)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")

    layer_keys = tuple(layers.keys())
    fabricated: List[str] = []
    layer_confused: List[str] = []

    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = SIGN_PREPOSITIONAL_TO_NOMINATIVE[sign_form] if is_ru else sign_form

        if (planet_name, sign_nom) not in all_pairs:
            fabricated.append(f"{planet_name} {joiner} {sign_form}")
            continue

        window_start = max(0, m.start() - marker_window)
        preceding = text[window_start:m.start()]
        claimed_layer = _nearest_preceding_layer(preceding, language, layer_keys)
        if claimed_layer is None:
            continue  # не можем атрибутировать — не флагуем, чтобы не давать ложных срабатываний

        claimed_sign = per_layer_pairs.get(claimed_layer, {}).get(planet_name)
        if claimed_sign == sign_nom:
            continue  # верно для заявленного слоя

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
    Аналог fix_fabricated_planet_positions (synastry_service.py), обобщённый на
    N слоёв. Правит СТРОГО те фразы, чей знак не существует НИ В ОДНОМ слое
    вообще (union-проверка "совпадает хоть с одним слоем — не трогаем", как в
    синастрии) — этого достаточно, чтобы не искалечить верную фразу с неверно
    приписанным слоем (тот случай — layer_confused у
    find_fabricated_positions_layered — сюда сознательно не входит, только лог).

    Слой (кто "прав") определяется по ближайшему ПРЕДШЕСТВУЮЩЕМУ вхождению
    маркера в окне marker_window. Если слой не определить или в нём нет данных
    по этой планете — фраза остаётся нетронутой и попадает в unresolved.

    Возвращает (исправленный текст, список нерешённых расхождений).
    """
    is_ru = language == 'ru'
    connector = r"\s+в\s+" if is_ru else r"\s+in\s+"
    joiner = "в" if is_ru else "in"

    per_layer_pairs = {key: _extract_layer_planet_signs(chart_like, language) for key, chart_like in layers.items()}
    all_pairs = set()
    for pairs in per_layer_pairs.values():
        for planet_name, sign in pairs.items():
            all_pairs.add((planet_name, sign))

    if not all_pairs:
        return text, []

    planet_names_display = PLANET_RU.values() if is_ru else PLANET_EN.values()
    sign_forms = SIGN_PREPOSITIONAL_TO_NOMINATIVE if is_ru else ZODIAC_SIGNS_EN
    planet_pattern = "|".join(re.escape(n) for n in planet_names_display)
    sign_pattern = "|".join(re.escape(f) for f in sign_forms)
    pattern = re.compile(rf"({planet_pattern}){connector}({sign_pattern})")

    layer_keys = tuple(layers.keys())
    unresolved: List[str] = []
    pieces: List[str] = []
    last_end = 0

    for m in pattern.finditer(text):
        planet_name, sign_form = m.group(1), m.group(2)
        sign_nom = SIGN_PREPOSITIONAL_TO_NOMINATIVE[sign_form] if is_ru else sign_form
        if (planet_name, sign_nom) in all_pairs:
            continue  # совпадает хоть с одним слоем — не трогаем

        window_start = max(0, m.start() - marker_window)
        preceding = text[window_start:m.start()]
        claimed_layer = _nearest_preceding_layer(preceding, language, layer_keys)
        correct_sign = per_layer_pairs.get(claimed_layer, {}).get(planet_name) if claimed_layer else None
        if not correct_sign:
            unresolved.append(f"{planet_name} {joiner} {sign_form}")
            continue

        correct_form = SIGN_NOMINATIVE_TO_PREPOSITIONAL.get(correct_sign, correct_sign) if is_ru else correct_sign
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
    Обобщение find_fabricated_aspect_types (synastry_service.py) на слои вместо
    партнёров. aspects — список aspects_to_natal, что строит
    calculate_progressions/calculate_transits (astrology_v2.py): key1/key2 —
    имена полей истинной пары (по умолчанию planet1/planet2 — калькулятор их
    не варьирует: первый слой — всегда planet1 (прогрессивная/транзитная),
    второй — всегда planet2 (натальная)). Только детекция, ничего не правит.
    """
    aspect_stems = ASPECT_STEM_RU if language == 'ru' else ASPECT_STEM_EN
    is_ru = language == 'ru'
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
            continue  # ноль или несколько слов аспекта в одном заголовке — пропускаем

        pair = (assigned[layer1], assigned[layer2])
        true_aspect = truth.get(pair)
        if true_aspect is None:
            continue  # такой пары нет в расчёте вообще — не наш случай

        stated_aspect = aspect_hits[0][1]
        if stated_aspect != true_aspect:
            p1_name = PLANET_RU.get(pair[0], pair[0]) if is_ru else PLANET_EN.get(pair[0], pair[0])
            p2_name = PLANET_RU.get(pair[1], pair[1]) if is_ru else PLANET_EN.get(pair[1], pair[1])
            true_label = true_aspect
            if is_ru:
                true_label = next(
                    (a.get('aspect_ru') for a in aspects if a.get(key1) == pair[0] and a.get(key2) == pair[1]),
                    true_aspect,
                )
            mismatches.append(
                f"{layer1}:{p1_name} — {layer2}:{p2_name}: "
                f"{'в тексте' if is_ru else 'in text'} «{stated_aspect}», "
                f"{'на деле' if is_ru else 'actually'} «{true_label}» "
                f"({'заголовок' if is_ru else 'header'}: {header.strip()[:120]})"
            )

    return mismatches


def find_undercovered_aspects_generic(
    full_analysis: str,
    aspects: List[Dict[str, Any]],
    language: str,
    key1: str = 'planet1',
    key2: str = 'planet2',
) -> List[str]:
    """
    Обобщение find_undercovered_aspects (synastry_service.py) без привязки к
    "Партнёру 1/2" в метке — для методов с двумя сторонами
    прогрессивная/натальная (или транзитная/натальная), а не двумя партнёрами.
    Та же логика: стемы, склонения, порог SHALLOW_ASPECT_CHAR_THRESHOLD,
    отсечение фраз-отсылок ("разобрано выше"). Только детекция, ничего не
    дописывает.

    Известное ограничение (то же, что у синастрийной версии): для аспекта
    планеты к самой себе (прогрессивная Луна — натальная Луна) поиск по двум
    одинаковым стемам тавтологичен и всегда даёт "покрыто" — недооценка, не
    переоценка числа проблем.
    """
    is_ru = language == 'ru'
    cop_out_phrases = _COP_OUT_PHRASES_RU if is_ru else _COP_OUT_PHRASES_EN

    def label_for(asp: Dict[str, Any]) -> str:
        p1 = PLANET_RU.get(asp.get(key1), asp.get(key1)) if is_ru else PLANET_EN.get(asp.get(key1), asp.get(key1))
        p2 = PLANET_RU.get(asp.get(key2), asp.get(key2)) if is_ru else PLANET_EN.get(asp.get(key2), asp.get(key2))
        asp_word = asp.get('aspect_ru') if is_ru else asp.get('aspect')
        return f"{p1} {asp_word} {p2} (орб {asp.get('orb')}°)" if is_ru \
            else f"{p1} {asp_word} {p2} (orb {asp.get('orb')}°)"

    missing: List[str] = []
    for asp in aspects:
        para = _find_aspect_coverage(full_analysis, asp.get(key1), asp.get(key2), language)
        is_cop_out = bool(para) and any(phrase in para.lower() for phrase in cop_out_phrases)
        if not para or len(para) < SHALLOW_ASPECT_CHAR_THRESHOLD or is_cop_out:
            missing.append(label_for(asp))

    return missing
