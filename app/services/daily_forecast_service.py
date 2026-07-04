# app/services/daily_forecast_service.py
# Прогноз дня: аспекты транзитов к углам (ASC/MC/DSC/IC) и Колесу Фортуны,
# детерминированный score 1-10, RAG по приоритетной книге (Planets in Transit),
# строгий JSON-ответ LLM с fallback на расчетную оценку.
#
# Переиспользует существующую инфраструктуру:
# - transits = результат calculate_transits (astrology_v2)
# - search_chunks_priority_book + TRANSITS_PRIORITY_BOOK_ID (analysis_service)
# - get_llm_adapter (llm_adapter, с поддержкой provider+model)
import asyncio
import json
import re
from typing import Dict, Any, List, Optional, Tuple

from app.services.analysis_service import (
    search_chunks_priority_book,
    TRANSITS_PRIORITY_BOOK_ID,
)
from app.services.llm_adapter import get_llm_adapter

POINT_ORB = 2.0  # орб к углам и Фортуне

ASPECT_ANGLES = {
    'conjunction': 0, 'sextile': 60, 'square': 90, 'trine': 120, 'opposition': 180,
}
BASE_WEIGHT = {'trine': 2.0, 'sextile': 1.0, 'square': -2.0, 'opposition': -1.5}
# соединение: знак зависит от природы транзитной планеты
CONJ_WEIGHT = {
    'Venus': 2.0, 'Jupiter': 2.0,
    'Mars': -2.0, 'Saturn': -2.0, 'Pluto': -2.0,
    'Uranus': -0.5, 'Neptune': -0.5,
    'Sun': 0.5, 'Moon': 0.5, 'Mercury': 0.5,
}
PLANET_FACTOR = {
    'Venus': 1.3, 'Jupiter': 1.3,
    'Mars': 1.3, 'Saturn': 1.3, 'Pluto': 1.3,
    'Uranus': 1.1, 'Neptune': 1.1,
    'Sun': 1.2, 'Moon': 1.2, 'Mercury': 1.0,
}
SCORING_PLANETS = set(PLANET_FACTOR.keys())
SCORE_K = 0.35
MAX_PLANET_ORB = 6.0  # нормировка орба планетных аспектов из calculate_transits

# --- ВАРИАНТ Б: два слоя ---
# Быстрые планеты определяют ДЕНЬ (меняются за часы/дни).
FAST_PLANETS = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars'}
# Медленные — ФОН ПЕРИОДА (висят неделями/месяцами/годами), не события дня.
SLOW_PLANETS = {'Jupiter', 'Saturn', 'Uranus', 'Neptune', 'Pluto'}
# Фон влияет на оценку дня лишь модификатором, ограниченным ±1 балл.
BG_K = 0.08
BG_MODIFIER_CAP = 1.0
# Триггер: быстрая планета задевает натальную точку, находящуюся под медленным
# транзитом, — день «спускает курок» заряженной темы периода. Усиление веса.
TRIGGER_FACTOR = 1.3

# Характер фона по природе медленной планеты (для промпта LLM).
BG_CHARACTER = {
    'ru': {
        'Jupiter': 'расширяющий',
        'Saturn': 'ограничивающий, структурирующий',
        'Uranus': 'нестабильный, внезапный В ОБЕ СТОРОНЫ (и риски, и неожиданные возможности)',
        'Neptune': 'размывающий, иллюзорный',
        'Pluto': 'трансформирующий, кризисно-обновляющий',
    },
    'en': {
        'Jupiter': 'expansive',
        'Saturn': 'restricting, structuring',
        'Uranus': 'unstable, sudden IN BOTH DIRECTIONS (risks and unexpected opportunities alike)',
        'Neptune': 'dissolving, illusory',
        'Pluto': 'transformative, crisis-and-renewal',
    },
}

CATEGORY_BOUNDS = [
    (2, 'critical'), (4, 'challenging'), (6, 'neutral'), (8, 'favorable'), (10, 'excellent'),
]


# ---------- утилиты ----------

def _lon(value: Any) -> Optional[float]:
    """Долгота из значения: float или dict с full_degree/longitude/degree."""
    if isinstance(value, (int, float)):
        return float(value) % 360
    if isinstance(value, dict):
        for key in ('full_degree', 'longitude', 'degree'):
            if isinstance(value.get(key), (int, float)):
                return float(value[key]) % 360
    return None


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def category_for(score: float) -> str:
    for limit, name in CATEGORY_BOUNDS:
        if score <= limit:
            return name
    return 'excellent'


# ---------- углы и Колесо Фортуны ----------

def _cusp(houses: Dict[str, Any], num: int) -> Optional[float]:
    """Долгота куспида дома num; ключи могут быть int или str после JSON."""
    entry = houses.get(num) if num in houses else houses.get(str(num))
    if isinstance(entry, dict):
        return _lon(entry.get('cusp_longitude'))
    return _lon(entry)


def extract_angles(natal_chart: Dict[str, Any]) -> Dict[str, float]:
    """
    Углы из натальных куспидов: ASC = дом 1, MC = дом 10, DSC = дом 7, IC = дом 4.
    ВАЖНО: natal_chart['ascendant'] в этом приложении — ЗНАК (строка), не градус,
    поэтому берем точные долготы из houses[N]['cusp_longitude'].
    """
    houses = natal_chart.get('houses') or {}
    if not isinstance(houses, dict):
        return {}
    angles: Dict[str, float] = {}
    mapping = {'ASC': 1, 'IC': 4, 'DSC': 7, 'MC': 10}
    for name, num in mapping.items():
        lon = _cusp(houses, num)
        if lon is not None:
            angles[name] = lon
    # fallback: если куспидов 7/4 нет — производные от ASC/MC
    if 'DSC' not in angles and 'ASC' in angles:
        angles['DSC'] = (angles['ASC'] + 180) % 360
    if 'IC' not in angles and 'MC' in angles:
        angles['IC'] = (angles['MC'] + 180) % 360
    return angles


def compute_fortune(natal_chart: Dict[str, Any]) -> Tuple[Optional[float], Optional[bool]]:
    """
    Колесо Фортуны. ПРИОРИТЕТ — готовое значение из натальной карты
    (natal_chart['houses_meta']['pars_fortuna']['longitude'], считается в
    calculate_planet_positions): та же логика, что с natal_override — не
    пересчитываем, чтобы не разойтись с остальным приложением.
    Fallback: день = ASC + Moon - Sun, ночь = ASC + Sun - Moon
    (дневная карта — натальное Солнце в домах 7..12).
    Возвращает (fortune, is_day_chart).
    """
    planets = natal_chart.get('planets') or {}
    sun_house = None
    if isinstance(planets.get('Sun'), dict):
        sun_house = planets['Sun'].get('house')
    is_day = bool(sun_house and 7 <= int(sun_house) <= 12)

    # 1. Готовая Фортуна из карты
    houses_meta = natal_chart.get('houses_meta') or {}
    stored = _lon((houses_meta.get('pars_fortuna') or {}).get('longitude'))
    if stored is not None:
        return round(stored, 2), is_day

    # 2. Fallback-расчет
    angles = extract_angles(natal_chart)
    asc = angles.get('ASC')
    sun = _lon(planets.get('Sun'))
    moon = _lon(planets.get('Moon'))
    if asc is None or sun is None or moon is None:
        return None, None

    fortune = ((asc + moon - sun) if is_day else (asc + sun - moon)) % 360
    return round(fortune, 2), is_day


def compute_point_aspects(
    transit_planets: Dict[str, Any],
    natal_chart: Dict[str, Any],
    fortune: Optional[float],
) -> List[Dict[str, Any]]:
    """Аспекты транзитных планет к натальным углам и Колесу Фортуны (орб 2°)."""
    points = dict(extract_angles(natal_chart))
    if fortune is not None:
        points['Fortune'] = fortune

    # ASC-DSC и MC-IC — оси (ровно 180°): аспект к одному концу оси автоматически
    # дает зеркальный аспект к другому (conj ASC = opp DSC и т.д.). Это ОДИН
    # физический контакт — дедуплицируем по оси, оставляя сильнейшую трактовку.
    AXIS = {'ASC': 'AX_ASC', 'DSC': 'AX_ASC', 'MC': 'AX_MC', 'IC': 'AX_MC', 'Fortune': 'AX_FORTUNE'}

    best: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p_name, p_data in (transit_planets or {}).items():
        if p_name not in SCORING_PLANETS:
            continue
        p_lon = _lon(p_data)
        if p_lon is None:
            continue
        for point_name, point_lon in points.items():
            diff = _angle_diff(p_lon, point_lon)
            for asp_name, asp_angle in ASPECT_ANGLES.items():
                orb = abs(diff - asp_angle)
                if orb <= POINT_ORB:
                    entry = {
                        'transit': p_name,
                        'aspect': asp_name,
                        'natal': point_name,
                        'orb': round(orb, 2),
                        'is_point': True,
                        'weight': _aspect_weight(p_name, asp_name, orb, POINT_ORB),
                    }
                    key = (p_name, AXIS[point_name])
                    if key not in best or abs(entry['weight']) > abs(best[key]['weight']):
                        best[key] = entry
                    break

    aspects = list(best.values())
    aspects.sort(key=lambda a: abs(a['weight']), reverse=True)
    return aspects


# ---------- скоринг ----------

def _aspect_weight(planet: str, aspect: str, orb: float, max_orb: float) -> float:
    aspect = (aspect or '').lower()
    if aspect == 'conjunction':
        base = CONJ_WEIGHT.get(planet, 0.0)
    else:
        base = BASE_WEIGHT.get(aspect, 0.0)
    orb_factor = 1 - (min(orb, max_orb) / max_orb) * 0.5
    return round(base * orb_factor * PLANET_FACTOR.get(planet, 1.0), 2)


def score_planet_aspects(aspects_to_natal: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Веса для аспектов из calculate_transits (transit/planet1, natal/planet2, aspect, orb)."""
    scored = []
    for a in aspects_to_natal or []:
        planet = a.get('transit') or a.get('planet1') or ''
        target = a.get('natal') or a.get('planet2') or ''
        if planet not in SCORING_PLANETS:
            continue
        orb = float(a.get('orb', 0) or 0)
        scored.append({
            'transit': planet,
            'aspect': (a.get('aspect') or '').lower(),
            'natal': target,
            'orb': round(orb, 2),
            'is_point': False,
            'is_slow': bool(a.get('is_slow')),
            'weight': _aspect_weight(planet, a.get('aspect') or '', orb, MAX_PLANET_ORB),
        })
    scored.sort(key=lambda a: abs(a['weight']), reverse=True)
    return scored


def split_layers(all_aspects: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Разделение аспектов на слой ДНЯ (быстрые транзитные планеты)
    и слой ФОНА ПЕРИОДА (медленные)."""
    fast = [a for a in all_aspects if a['transit'] in FAST_PLANETS]
    slow = [a for a in all_aspects if a['transit'] in SLOW_PLANETS]
    for a in fast:
        a['layer'] = 'day'
    for a in slow:
        a['layer'] = 'background'
    return fast, slow


def mark_triggers(fast: List[Dict[str, Any]], slow: List[Dict[str, Any]]) -> None:
    """Триггеры: быстрая планета аспектирует натальную точку, находящуюся под
    медленным транзитом. Помечаем и усиливаем вес — день активирует тему периода."""
    charged_targets = {a['natal'] for a in slow}
    for a in fast:
        if a['natal'] in charged_targets:
            a['is_trigger'] = True
            a['weight'] = round(a['weight'] * TRIGGER_FACTOR, 2)
        else:
            a['is_trigger'] = False


def compute_base_score(fast: List[Dict[str, Any]],
                       slow: List[Dict[str, Any]]) -> Tuple[float, float]:
    """ВАРИАНТ Б: оценку дня формируют быстрые аспекты; медленный фон —
    только ограниченный модификатор (±BG_MODIFIER_CAP балла).
    Возвращает (base_score, bg_modifier)."""
    day_total = sum(a['weight'] for a in fast)
    bg_total = sum(a['weight'] for a in slow)
    bg_modifier = max(-BG_MODIFIER_CAP, min(BG_MODIFIER_CAP, bg_total * BG_K))
    score = round(min(10.0, max(1.0, 5.5 + day_total * SCORE_K + bg_modifier)), 1)
    return score, round(bg_modifier, 2)


# ---------- LLM ----------

_SYSTEM_RULES = {
    'ru': (
        "Ты профессиональный астролог. Оцени транзитный ДЕНЬ по рассчитанным аспектам "
        "и фрагментам из книги 'Planets in Transit' (Роберт Хэнд).\n"
        "Ответь СТРОГО валидным JSON без markdown и без текста вне JSON:\n"
        '{"score": <целое 1-10>, "summary": "<3-5 предложений на русском>"}\n'
        "Правила:\n"
        "- score = base_score, отклонение максимум на 1 и только если аспекты дня это обосновывают;\n"
        "- ДВА СЛОЯ: 'Аспекты дня' (быстрые планеты) определяют оценку и события дня; "
        "'Фон периода' (медленные планеты) — это НЕ события дня, а длительный контекст недель/месяцев. "
        "Никогда не подавай фоновые транзиты как события конкретного дня;\n"
        "- фон описывай отдельной краской по его характеру (указан для каждого фонового аспекта): "
        "например 'на фоне длительного трансформирующего квадрата Плутона...'. "
        "Уран в фоне — нестабильность В ОБЕ СТОРОНЫ: и внезапные риски, и внезапные возможности, не 'плохо';\n"
        "- аспекты с пометкой [ТРИГГЕР] — быстрая планета в этот день активирует натальную точку, "
        "заряженную медленным транзитом: таким аспектам уделяй особое внимание, это точки, где тема периода "
        "может проявиться именно сегодня;\n"
        "- если score <= 3 — прямо укажи вероятность критических событий и в каких сферах (по активированным домам);\n"
        "- если score >= 7 — укажи удачные знаки и сферы;\n"
        "- конкретно, без воды и без фраз вида 'звезды говорят'."
    ),
    'en': (
        "You are a professional astrologer. Rate the transit DAY using the calculated aspects "
        "and fragments from 'Planets in Transit' (Robert Hand).\n"
        "Reply with STRICTLY valid JSON, no markdown, no text outside JSON:\n"
        '{"score": <integer 1-10>, "summary": "<3-5 sentences>"}\n'
        "Rules:\n"
        "- score = base_score, deviation at most 1 and only if the day aspects justify it;\n"
        "- TWO LAYERS: 'Day aspects' (fast planets) define the score and the events of the day; "
        "'Period background' (slow planets) is NOT a same-day event but a weeks/months-long context. "
        "Never present background transits as events of this specific day;\n"
        "- describe the background separately by its stated character, e.g. 'against a long transformative "
        "Pluto square...'. Background Uranus means instability IN BOTH DIRECTIONS: sudden risks and sudden "
        "opportunities alike, not 'bad';\n"
        "- aspects marked [TRIGGER] mean a fast planet activates today a natal point charged by a slow transit: "
        "pay special attention — the period's theme may manifest exactly today;\n"
        "- if score <= 3 state the probability of critical events and in which life areas (by activated houses);\n"
        "- if score >= 7 name the lucky signs and areas;\n"
        "- be concrete, no filler."
    ),
}


def _parse_llm_json(raw: str) -> Optional[Dict[str, Any]]:
    if not raw or raw.startswith('Error:'):
        return None
    text = re.sub(r'^```(json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
    match = re.search(r'\{.*\}', text, flags=re.DOTALL)
    if match:
        text = match.group(0)
    try:
        data = json.loads(text)
        score = int(data['score'])
        if not 1 <= score <= 10:
            return None
        return {
            'score': score,
            'category': category_for(score),  # категорию считаем сами — всегда согласована
            'summary': str(data.get('summary', '')).strip(),
        }
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        return None


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get('content') or chunk.get('text') or chunk.get('chunk_text') or '')
    return str(chunk)


async def daily_forecast_analysis(
    natal_chart: Dict[str, Any],
    transits: Dict[str, Any],
    language: str = 'ru',
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Полный пайплайн прогноза дня. transits — результат calculate_transits."""
    t_planets = transits.get('transit_planets', {}) or {}
    aspects_to_natal = transits.get('aspects_to_natal', []) or []

    # 1. Скоринг (ВАРИАНТ Б, два слоя): аспекты дня (быстрые планеты) определяют
    # оценку; медленные — фон периода с ограниченным модификатором и триггерами.
    fortune, is_day = compute_fortune(natal_chart)
    planet_aspects = score_planet_aspects(aspects_to_natal)
    point_aspects = compute_point_aspects(t_planets, natal_chart, fortune)

    all_aspects = planet_aspects + point_aspects
    fast_aspects, slow_aspects = split_layers(all_aspects)
    mark_triggers(fast_aspects, slow_aspects)  # усиливает вес триггерных до скоринга
    base, bg_modifier = compute_base_score(fast_aspects, slow_aspects)
    base_cat = category_for(base)

    # ВСЕ аспекты без обрезки: к планетам, углам ASC/MC/DSC/IC и Колесу Фортуны
    key_aspects = list(all_aspects)
    key_aspects.sort(key=lambda a: abs(a['weight']), reverse=True)

    houses_activated = sorted({
        int(p.get('natal_house')) for p in t_planets.values()
        if isinstance(p, dict) and p.get('natal_house')
    })

    # 2. Параллельный RAG по ВСЕМ аспектам (приоритетная книга — Хэнд):
    #    к натальным планетам, к углам ASC/MC/DSC/IC и к Колесу Фортуны
    _POINT_QUERY_NAMES = {
        'ASC': 'ascendant', 'MC': 'midheaven',
        'DSC': 'descendant', 'IC': 'IC',
        'Fortune': 'part of fortune',
    }

    async def search_aspect(a: Dict[str, Any]):
        natal_name = _POINT_QUERY_NAMES.get(a['natal'], a['natal'].lower())
        query = f"transit {a['transit'].lower()} {a['aspect']} natal {natal_name}"
        chunks = await search_chunks_priority_book(
            query, TRANSITS_PRIORITY_BOOK_ID, top_k_priority=2, top_k_others=1
        )
        return query, chunks

    rag_results = await asyncio.gather(
        *[search_aspect(a) for a in key_aspects], return_exceptions=True
    )
    rag_blocks: List[str] = []
    for res in rag_results:
        if isinstance(res, Exception):
            continue
        query, chunks = res
        texts = [_chunk_text(c)[:600] for c in (chunks or [])[:2] if _chunk_text(c)]
        if texts:
            rag_blocks.append(f"[{query}]\n" + "\n".join(texts))

    # 3. Промпт: два блока — аспекты дня и фон периода
    lunar = (transits.get('lunar_phase') or {}).get('phase', '')
    bg_chars = BG_CHARACTER.get(language, BG_CHARACTER['en'])

    def _day_line(a):
        return (
            f"- transit {a['transit']} {a['aspect']} natal {a['natal']} "
            f"(orb {a['orb']}, weight {a['weight']:+})"
            + (" [angle/fortune]" if a['is_point'] else "")
            + (" [ТРИГГЕР]" if a.get('is_trigger') else "")
        )

    def _bg_line(a):
        return (
            f"- transit {a['transit']} {a['aspect']} natal {a['natal']} "
            f"(orb {a['orb']}, weight {a['weight']:+}, характер: {bg_chars.get(a['transit'], '-')})"
            + (" [angle/fortune]" if a['is_point'] else "")
        )

    fast_sorted = sorted(fast_aspects, key=lambda a: abs(a['weight']), reverse=True)
    slow_sorted = sorted(slow_aspects, key=lambda a: abs(a['weight']), reverse=True)
    day_lines = "\n".join(_day_line(a) for a in fast_sorted) or "нет"
    bg_lines = "\n".join(_bg_line(a) for a in slow_sorted) or "нет"

    prompt = (
        f"{_SYSTEM_RULES.get(language, _SYSTEM_RULES['en'])}\n\n"
        f"base_score: {base} (категория {base_cat}; вклад фона периода: {bg_modifier:+})\n"
        f"Активированные натальные дома: {houses_activated}\n"
        f"Лунная фаза: {lunar or '-'}\n"
        f"АСПЕКТЫ ДНЯ (быстрые планеты — определяют оценку и события дня):\n{day_lines}\n\n"
        f"ФОН ПЕРИОДА (медленные транзиты — длительный контекст, НЕ события дня):\n{bg_lines}\n\n"
        f"Фрагменты книги:\n" + ("\n\n".join(rag_blocks) if rag_blocks else "нет") + "\n\n"
        f"Дай оценку дня."
    )

    # 4. LLM + fallback на расчетную оценку
    llm_error: Optional[str] = None
    parsed: Optional[Dict[str, Any]] = None
    try:
        adapter = get_llm_adapter(provider, model)
        raw = await adapter.generate(prompt, language)
        parsed = _parse_llm_json(raw)
        if parsed is None:
            llm_error = (raw or 'empty response')[:200]
    except Exception as e:
        llm_error = str(e)[:200]

    if parsed is None:
        parsed = {'score': round(base), 'category': base_cat, 'summary': ''}

    return {
        **parsed,
        'base_score': base,
        'background_modifier': bg_modifier,
        'key_aspects': key_aspects,
        'houses_activated': houses_activated,
        'fortune': fortune,
        'is_day_chart': is_day,
        'lunar_phase': transits.get('lunar_phase'),
        'llm_error': llm_error,
        'llm_provider': provider,
        'llm_model': model,
    }