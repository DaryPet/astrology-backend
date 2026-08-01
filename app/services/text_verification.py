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
from app.services.prompt_templates.languages import normalize_language

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
    'Pluto': r'Плутон\w*', 'NorthNode': r'Северн\w*\s+[Уу]з(?:ел\w*|л\w*)',
    'SouthNode': r'Южн\w*\s+[Уу]з(?:ел\w*|л\w*)', 'Chiron': r'Хирон\w*',
    'Lilith': r'Лилит\w*', 'Ascendant': r'Асцендент\w*', 'Vertex': r'Вертекс\w*',
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
    'Lilith': r'\bLilith\b', 'Ascendant': r'\bAscendant\b', 'Vertex': r'\bVertex\b',
}

ASPECT_STEM_EN = {
    'Conjunction': r'\bConjunction\b', 'Opposition': r'\bOpposition\b',
    'Trine': r'\bTrine\b', 'Square': r'\bSquare\b', 'Sextile': r'\bSextile\b',
}

# ============================================================
# Українська
# ============================================================
# Українська, як і російська, відмінює іменники за відмінком ("Хірона",
# "в опозиції", "секстилі") — тому стеми з \w* і окрема таблиця форм знака
# (місцевий відмінок -> називний), той самий підхід, що і в RU-блоці вище.

# Місцевий відмінок знаків зодіаку ("Місяць У РАКУ") -> називний ("Рак"),
# як він зберігається в chart_data (sign_uk). Перевірено реальним виводом
# LLM (DeepSeek, natal analysis, 2026-07): "Венера у Леві в 7-му домі" —
# форма "у Леві" підтверджена на практиці, не лише теоретично виведена.
SIGN_LOCATIVE_TO_NOMINATIVE_UK = {
    'Овні': 'Овен', 'Тельці': 'Телець', 'Близнюках': 'Близнюки',
    'Раку': 'Рак', 'Леві': 'Лев', 'Діві': 'Діва',
    'Терезах': 'Терези', 'Скорпіоні': 'Скорпіон', 'Стрільці': 'Стрілець',
    'Козерозі': 'Козеріг', 'Водолії': 'Водолій', 'Рибах': 'Риби',
}

# Стеми українських назв планет — початок слова, бо в тексті планета
# відмінюється ("Хірона", "Північним Вузлом"), а не стоїть у називному.
# NorthNode/SouthNode: "вузол" має випадний голосний "о" в непрямих
# відмінках (вузол -> вузла, вузлі) — той самий випадок, що й РОС. "узел",
# структура патерну ідентична PLANET_STEM_RU.
PLANET_STEM_UK = {
    'Sun': r'Сонц\w*', 'Moon': r'Місяц\w*', 'Mercury': r'Меркурі\w*',
    'Venus': r'Венер\w*', 'Mars': r'Марс\w*', 'Jupiter': r'Юпітер\w*',
    'Saturn': r'Сатурн\w*', 'Uranus': r'Уран\w*', 'Neptune': r'Нептун\w*',
    'Pluto': r'Плутон\w*', 'NorthNode': r'Північн\w*\s+[Вв]уз(?:ол\w*|л\w*)',
    'SouthNode': r'Південн\w*\s+[Вв]уз(?:ол\w*|л\w*)', 'Chiron': r'Хірон\w*',
    'Lilith': r'Ліліт\w*', 'Ascendant': r'Асцендент\w*', 'Vertex': r'Вертекс\w*',
}

# Стеми аспектів — та сама причина: "в опозиції", "З'єднання", "секстилі".
ASPECT_STEM_UK = {
    'Conjunction': r"[Зз]'?єднан\w*", 'Opposition': r'[Оо]позиці\w*',
    'Trine': r'[Тт]ригон\w*', 'Square': r'[Кк]вадрат\w*',
    'Sextile': r'[Сс]екстил\w*',
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
    'Lilith': 'Лилит', 'Ascendant': 'Асцендент', 'Vertex': 'Вертекс',
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
_COP_OUT_PHRASES_UK = [
    "розібран", "вже обговорюва", "вже опис", "вже сказа", "вже говорили",
    "дивись вище", "див. вище", "як уже", "як ми вже",
]

SHALLOW_ASPECT_CHAR_THRESHOLD = 220

# ============================================================
# Диспетчер по языку — единая точка выбора таблицы вместо разбросанных
# `X if is_ru else Y` по всему файлу. `lang` уже нормализован через
# normalize_language() перед использованием этих словарей.
# ============================================================
PLANET_STEM_BY_LANG = {'ru': PLANET_STEM_RU, 'uk': PLANET_STEM_UK, 'en': PLANET_STEM_EN}
ASPECT_STEM_BY_LANG = {'ru': ASPECT_STEM_RU, 'uk': ASPECT_STEM_UK, 'en': ASPECT_STEM_EN}
PLANET_DISPLAY_BY_LANG = {'ru': PLANET_RU, 'uk': PLANET_UK, 'en': PLANET_EN}
COP_OUT_PHRASES_BY_LANG = {'ru': _COP_OUT_PHRASES_RU, 'uk': _COP_OUT_PHRASES_UK, 'en': _COP_OUT_PHRASES_EN}
# 'в тексте'/'на деле'/'заголовок' и т.п. — подписи внутри диагностических
# сообщений о несовпадении (не матчатся регэкспами, просто текст лога).
_MSG_LABELS_BY_LANG = {
    'ru': {'in_text': 'в тексте', 'actually': 'на деле', 'header': 'заголовок'},
    'uk': {'in_text': 'у тексті', 'actually': 'насправді', 'header': 'заголовок'},
    'en': {'in_text': 'in text', 'actually': 'actually', 'header': 'header'},
}


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
    Ближайший маркер одного из layer_keys, предшествующий найденной фразе —
    но только в ПРЕДЕЛАХ ТЕКУЩЕГО ПРЕДЛОЖЕНИЯ (после последней точки/!/? в
    preceding_text), не по всему marker_window.

    Без этого ограничения на живых прогонах (прогрессии и транзиты, см.
    app/services/specs/*_synastry_pattern_plan.md) находились ложные
    layer_confused: в предложении вида "Прогрессивная Луна секстиль натальный
    Меркурий (...). Твои чувства (Луна в Овне/12 дом)..." маркер "натальный"
    (относящийся к Меркурию) текстово ближе к повторному упоминанию "Луна в
    Овне" во ВТОРОМ предложении, чем "Прогрессивная" из ПЕРВОГО — по всему
    окну "ближайший" оказывался чужим. Ограничение текущим предложением не
    даёт заглянуть в предыдущее предложение и подхватить чужой маркер; если в
    текущем предложении маркера нет вообще — возвращаем None (как и раньше
    для случая "не смогли атрибутировать"), а не гадаем.

    Если layer_keys содержит РОВНО один слой (натальная карта без второй
    стороны — см. app/services/specs/natal_synastry_pattern_plan.md),
    атрибуция и так однозначна: возвращаем этот единственный слой без поиска
    маркера вообще — с одним слоем маркер в промпте не пишется намеренно (см.
    план), и поиск его отсутствия иначе всегда возвращал бы None, оставляя
    даже заведомо выдуманные позиции неисправленными (unresolved).
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
            continue  # совпадает хоть с одним слоем — не трогаем

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
    Обобщение find_fabricated_aspect_types (synastry_service.py) на слои вместо
    партнёров. aspects — список aspects_to_natal, что строит
    calculate_progressions/calculate_transits (astrology_v2.py): key1/key2 —
    имена полей истинной пары (по умолчанию planet1/planet2 — калькулятор их
    не варьирует: первый слой — всегда planet1 (прогрессивная/транзитная),
    второй — всегда planet2 (натальная)). Только детекция, ничего не правит.
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
            continue  # ноль или несколько слов аспекта в одном заголовке — пропускаем

        pair = (assigned[layer1], assigned[layer2])
        true_aspect = truth.get(pair)
        if true_aspect is None:
            continue  # такой пары нет в расчёте вообще — не наш случай

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
        para = _find_aspect_coverage(full_analysis, asp.get(key1), asp.get(key2), language)
        is_cop_out = bool(para) and any(phrase in para.lower() for phrase in cop_out_phrases)
        if not para or len(para) < SHALLOW_ASPECT_CHAR_THRESHOLD or is_cop_out:
            missing.append(label_for(asp))

    return missing


# ============================================================
# Одна карта без сторон (натальная синтез-карта) — общее
# ============================================================
# В отличие от find_fabricated_aspect_types (synastry_service.py) и
# find_fabricated_aspect_types_layered (выше) — здесь нет атрибуции по
# партнёру/слою вообще, потому что карта одна: две планеты в жирном
# markdown-заголовке однозначны сами по себе, без маркера "чья". План:
# app/services/specs/natal_synastry_pattern_plan.md.

def find_fabricated_aspect_types_single(
    text: str,
    aspects: List[Dict[str, Any]],
    language: str,
    key1: str = 'planet1',
    key2: str = 'planet2',
) -> List[str]:
    """
    Сверяет жирные markdown-заголовки вида "<Планета1> <Аспект> <Планета2>"
    с реально посчитанным типом аспекта для этой пары — для карт с одной
    стороной (натал), без атрибуции по партнёру/слою. Пара планет в
    calculate_aspects (astrology_v2.py) неупорядочена — в отличие от
    синастрии, одна и та же пара не может быть двумя разными реальными
    аспектами одновременно, поэтому ключ truth — frozenset({p1, p2}).

    Пропускает (не флагует) заголовок, если в нём найдено не ровно 2 планеты
    или не ровно 1 тип аспекта — неоднозначность не разрешаем угадыванием
    (тот же принцип, что у find_fabricated_aspect_types /
    find_fabricated_aspect_types_layered). Только детекция, ничего не правит.
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
            continue  # не ровно две РАЗНЫЕ планеты — не наш случай

        aspect_hits = []
        for aspect_en, stem_pattern in aspect_stems.items():
            for m in re.finditer(stem_pattern, header):
                aspect_hits.append(aspect_en)
        if len(aspect_hits) != 1:
            continue  # тип не назван явно, либо назван неоднозначно

        pair = frozenset(planet_hits)
        true_aspect = truth.get(pair)
        if true_aspect is None:
            continue  # такой пары нет в расчёте вообще — не наш случай

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
# Проверка ДОМА (натал, одна карта) — общее
# ============================================================
# Отдельно от знака: у дома нет фиксированного числа словоформ, как у 12
# знаков ("в Овне", "во Льве" — конечный список), поэтому дом ищется не
# regex-парой "<Планета> в <Дом>" целиком, а по слову "дом"/"house" в том же
# предложении, что и планета — то же ограничение текущим предложением, что и
# у _nearest_preceding_layer (без него число дома из одного предложения
# ложно приписалось бы планете из соседнего). Только детекция — правка риск-
# ованнее, чем у знака: замена номера дома в живой прозе может разъехаться с
# согласованием в остальной части того же предложения ("в 7-м доме" vs
# "седьмой дом" в одном месте). План: app/services/specs/natal_synastry_pattern_plan.md.

_HOUSE_WORD_RU = r'(?:дом|доме|дома|домов|домах)\b'
_HOUSE_NUMBER_RU = re.compile(
    rf'(?:(\d{{1,2}})[-–]?\s*(?:й|м|го|ом)?\s*{_HOUSE_WORD_RU}|{_HOUSE_WORD_RU}\s*(\d{{1,2}}))',
    re.IGNORECASE,
)
_HOUSE_NUMBER_EN = re.compile(
    r'(?:(\d{1,2})(?:st|nd|rd|th)?\s*house|house\s*(?:number\s*)?(\d{1,2}))',
    re.IGNORECASE,
)

# Украинский: LLM реально использует ОБА слова для "дома" — "будинок" (слово
# из наших prompt_labels.py) И "дім" (более разговорное — подтверждено живым
# выводом DeepSeek, natal analysis 2026-07: "Венера у Леві в 7-му домі"
# использует форму "домі", родовое слово "дім", не "будинку"). Обе формы
# должны матчиться, иначе реальный текст модели пройдёт мимо регэкспа.
_HOUSE_WORD_UK = r'(?:будинок|будинку|будинки|будинків|будинках|дім|дому|дома|домі|доми|домів|домах)\b'
_HOUSE_NUMBER_UK = re.compile(
    rf'(?:(\d{{1,2}})[-–]?\s*(?:й|му|го|ому|ім|м)?\s*{_HOUSE_WORD_UK}|{_HOUSE_WORD_UK}\s*(\d{{1,2}}))',
    re.IGNORECASE,
)

_BOLD_HEADER_RE = re.compile(r'\*\*[^*\n]{1,240}\*\*')
_SENTENCE_OR_HEADER_BOUNDARY_RE = re.compile(r'\*\*[^*\n]{1,240}\*\*|[.!?]\s+')

# Присоединительный союз после запятой почти всегда значит новое подлежащее
# ("Марс ... в 6-м доме, И квадрат с Солнцем ..." — дом относится к Марсу,
# а не к Солнцу, хотя оба в одном "предложении" по точкам). EN: то же для
# and/but. UK: "і"/"й"/"а"/"але". Без этого разбиения дом ложно приписывался
# бы любой другой планете, упомянутой в том же предложении, что и настоящий
# владелец дома.
_CLAUSE_BREAK_RU = re.compile(r',\s*(?:и|а|но)\s+')
_CLAUSE_BREAK_EN = re.compile(r',\s*(?:and|but)\s+')
_CLAUSE_BREAK_UK = re.compile(r',\s*(?:і|й|а|але)\s+')

HOUSE_PATTERN_BY_LANG = {'ru': _HOUSE_NUMBER_RU, 'uk': _HOUSE_NUMBER_UK, 'en': _HOUSE_NUMBER_EN}
CLAUSE_BREAK_BY_LANG = {'ru': _CLAUSE_BREAK_RU, 'uk': _CLAUSE_BREAK_UK, 'en': _CLAUSE_BREAK_EN}


def _sentence_span(text: str, pos: int) -> "tuple[int, int]":
    """
    Границы предложения, содержащего pos — по точке/!/? И по границе жирного
    markdown-заголовка (**...**), в обе стороны. Заголовок — это отдельный
    смысловой блок, а не часть следующего предложения: без этой границы
    "**11. Уран и Нептун ...**\nУран в Скорпионе в 8-м доме" считалось бы
    одним предложением, и дом Урана ложно приписался бы Нептуну из заголовка.
    Если pos внутри самого заголовка — предложение это и есть весь заголовок.
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
    Сужает _sentence_span до пункта (clause) внутри предложения, разделённого
    запятой+союзом ("и"/"а"/"но" — RU, "and"/"but" — EN). См. докстринг
    _CLAUSE_BREAK_RU — без этого сужения дом ложно приписывался бы другой
    планете, упомянутой в том же предложении после присоединительного союза.
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
    Сверяет упоминания дома рядом с планетой ("<Планета> ... в N-м доме") с
    реальным домом планеты в натальной карте. Только детекция, ничего не
    правит (см. модуль-докстринг раздела выше — почему).

    Ищет номер дома только в ПРЕДЕЛАХ ТЕКУЩЕГО ПУНКТА (clause) — предложение,
    ограниченное ещё и границей жирного заголовка и запятой+союзом (см.
    _clause_span) — где встретилось имя планеты. Если в пункте 0 или больше 1
    РАЗНЫХ номеров дома, пропускает (неоднозначно, не гадаем, тот же принцип,
    что и у остальных проверок в этом модуле). Несколько планет в одном
    пункте с одним номером дома — не ошибка (например, "Плутон и Луна в том
    же 7-м доме" — обеим планетам законно приписывается один дом). Асцендент/
    MC не проверяются — у них нет числового поля 'house' в чарте (дом 1/10
    определяется по куспиду, а не хранится как отдельное значение).
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
                continue  # 0 или неоднозначно (несколько разных номеров) — пропускаем

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
