# app/services/daily_forecast_service.py
# Прогноз дня матча: ГИБРИДНЫЙ метод на основе КАРТЫ СОБЫТИЯ (event chart) по
# книге John Frawley, «Sports Astrology» (2007), глава 2 «The Chart for the
# Event» — приоритетная книга RAG id=30.
# Спеки: app/services/specs/daily_forecast_event_chart_plan.md,
# plans/daily-forecast-hybrid-method.md (гибридный слой, см. ниже).
#
# База — метод карты события гл. 2 (НЕ хорарный метод главы 1). Фроули:
# «IT'S NOT THE SAME AS HORARY. DON'T MIX THE METHODS» и «FORGET ESSENTIAL
# DIGNITY. FORGET ACCIDENTAL DIGNITY. FORGET RECEPTIONS» — по книге эти
# понятия в карте события не работают.
#
# ГИБРИДНЫЙ СЛОЙ (сознательное отступление от прямого запрета книги, см.
# plans/daily-forecast-hybrid-method.md): по итогам месяца эмпирических
# тестов на реальных матчах для Lord 1 и Lord 7 (ТОЛЬКО главные значители, не
# 10/4) дополнительно считаются эссенциальное достоинство, угловатость их
# СОБСТВЕННОГО дома и ретроградность — классическая хорарная (гл.1-стиль)
# оценка. Тестимонии этого слоя помечены source='mixed'/[ГИБРИД], не ищутся в
# книге через RAG (книга прямо против них) и суммируются в тот же base_score
# наравне с тестимониями гл. 2. См. `_mixed_method_testimonies`,
# `_build_significator_card`.
#
# Карта: время+место НАЧАЛА матча (Placidus). Фаворит = 1-й дом (+10-й, дом его
# успеха), соперник = 7-й (+4-й = 10-й от 7-го). Свидетельства гл. 2:
#   A. Положения Lords 1/4/7/10 и их антисций в 2-3° от куспидов 1/4/7/10:
#      НА куспиде = контролирует дом, СРАЗУ ВНУТРИ = в плену у дома.
#   B. Луна = «поток событий»: её ФИНАЛЬНЫЙ применяющийся аспект в пределах
#      хода (спорт-зависимого) к Lord 1/10 -> фаворит, к Lord 7/4 -> соперник.
#      Аспект к Фортуне/её антисции — финален всегда. Граница знака — предел.
#   C. Фортуна (ВСЕГДА ASC+Луна-Солнце, без ночного переворота): антисция у
#      куспидов 1/7 — сильнейшее одиночное свидетельство; аспекты Lords 1/7
#      к ней; её диспозитор; её соединение с узлами.
#   D. Узлы: значитель conj Северный узел (<=2°) усилен, conj Южный ослаблен.
#   E. Комбустия: значитель в 2° от Солнца поражён. Кажими не существует.
#   F. Внешние планеты: Плутон на релевантном куспиде (против фаворита),
#      Уран к MC/Фортуне (за фаворита), Сатурн-малефик. Нептун — игнор.
#   G. ГИБРИД: эссенциальное достоинство + угловатость + ретроградность
#      Lord 1/7 (см. выше).
#
# Переиспользует: calculate_transits (astrology_v2) -> transit_houses (куспиды
# Плацидуса на момент матча) + transit_planets (включая NorthNode/SouthNode,
# Uranus/Neptune/Pluto, transit_house каждой планеты); RAG
# search_chunks_priority_book; get_llm_adapter.
# Натальная карта — только контекстная сноска, не участвует в скоринге.
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from app.services.analysis_service import search_chunks_priority_book
from app.utils.horary_tables import (
    classical_ruler, antiscion, TRADITIONAL_PLANETS,
    essential_dignity,
)
from app.utils.astrology_v2 import ZODIAC_SIGNS, ZODIAC_SIGNS_RU

# Приоритетная книга ПРОГНОЗА ДНЯ — sport_astrology (id=30).
# Обычные транзиты (/analysis/transits) используют свою книгу (28) — не трогаем.
DAILY_FORECAST_PRIORITY_BOOK_ID = 30

ASPECT_ANGLES = {
    'conjunction': 0, 'sextile': 60, 'square': 90, 'trine': 120, 'opposition': 180,
}
HARMONIOUS_ASPECTS = {'conjunction', 'trine', 'sextile'}  # для аспектов к Фортуне

# Орбы по книге (гл. 2): «Small measures of movement and certain narrowly
# prescribed house-placements are all that concern us».
CUSP_ORB = 3.0          # «sitting on the cusp, at most a couple of degrees before it;
                        #  tucked just inside, at most a couple of degrees inside» (2-3°)
FORTUNA_ASPECT_ORB = 5.0  # «keep to a limit of around 5 degrees»
NODE_ORB = 2.0          # «conjunctions only, within a couple of degrees at most»
COMBUST_ORB = 2.0       # «any significator within 2 degrees of the Sun is harmed»
OUTER_ORB = 1.5         # внешние планеты: «a degree or so away at most»
SATURN_ORB = 2.0        # Сатурн-малефик: тесное касание
MOON_RANGE_DEFAULT = 5.0  # футбол 80+ минут; +1° если возможно доп. время

RELEVANT_HOUSES = (1, 10, 7, 4)
FAVOURITE_HOUSES = {1, 10}
UNDERDOG_HOUSES = {7, 4}

# Веса свидетельств (тиры из спеки). Знак: + за фаворита, - за соперника.
W_MAIN_LORD_PLACEMENT = 2.5   # Lord 1/7 на/в куспиде — «will usually outweigh anything else»
W_SUCCESS_LORD_PLACEMENT = 1.5  # Lords 10/4 у куспидов
W_OWN_HOUSE_BONUS = 1.0       # свой дом: усиление, но «слабее доминирования над врагом»
W_FORTUNA_ANTISCION_PLACEMENT = 2.5  # «perhaps the most powerful of all»
W_MOON_FINAL_ASPECT = 2.0     # «Moon's final aspect wins»
W_MOON_PLACEMENT = 2.0        # Луна у куспида 1/10/7/4
W_MOON_EARLY_ASPECT = 0.3     # ранний (не финальный) аспект = «ранний перевес»
W_FORTUNA_ASPECT = 1.5        # conj/opp Lords 1/7 к Фортуне/антисции
W_FORTUNA_DISPOSITOR = 1.2
W_NODE = 1.2
W_COMBUSTION = 1.0
W_PLUTO = 1.5
W_URANUS = 1.0
W_SATURN_MALEFIC = 0.7
ANTISCION_FACTOR = 0.7        # антисции «not quite so compelling as bodily placements»
RETRO_ON_CUSP_FACTOR = 0.6    # ретроградная НА куспиде: позитив, но слабее прямой

# ГИБРИДНЫЙ СЛОЙ (НЕ из книги — сознательная эмпирика пользователя, см.
# plans/daily-forecast-hybrid-method.md). Книга гл.2 прямо требует
# «FORGET ESSENTIAL DIGNITY. FORGET ACCIDENTAL DIGNITY... DON'T MIX THE
# METHODS», но по итогам месяца реальных тестов классическая (гл.1-стиль)
# оценка Lord 1/7 по достоинству/угловатости/ретроградности повышает точность
# прогноза. Применяется ТОЛЬКО к Lord 1 и Lord 7 (не к Lord 10/4). Веса — не
# из книги, эмпирический выбор классической хорарной шкалы.
W_MIXED_DIGNITY = {
    'domicile': 1.0, 'exaltation': 1.75, 'detriment': -1.75, 'fall': -2.25,
    'peregrine': 0.0,
}
# Простая 3-уровневая шкала силы дома (angular/succedent/cadent), а НЕ полная
# точечная таблица Лилли: угловой = бонус, succedent = нейтрально («без
# бонуса»), кадентный = слабый минус. 8-й дом отдельно — «дом смерти»,
# выделен из succedent и трактуется как сильный минус независимо от того,
# что формально succedent. Подтверждено пользователем на реальных примерах
# (11-й succedent = нейтрально, 9-й кадентный = слабый минус, 8-й = сильный
# минус), см. plans/daily-forecast-hybrid-method.md.
ANGULAR_HOUSES = {1, 4, 7, 10}
CADENT_HOUSES = {3, 6, 9, 12}
EIGHTH_HOUSE = 8
HOUSE_STRENGTH = {h: 1.75 for h in ANGULAR_HOUSES}
HOUSE_STRENGTH.update({h: -1.0 for h in CADENT_HOUSES})
HOUSE_STRENGTH[EIGHTH_HOUSE] = -2.25
HOUSE_STRENGTH.update({h: 0.0 for h in (2, 5, 11)})  # succedent (кроме 8-го) — нейтрально
HOUSE_NICKNAME_RU = {6: 'болезни, слуги', 8: 'смерть', 12: 'тайные враги, заточение'}
W_MIXED_RETROGRADE = -1.0

DIGNITY_RU = {
    'domicile': 'Обитель', 'exaltation': 'Экзальтация', 'detriment': 'Изгнание',
    'fall': 'Падение', 'peregrine': 'Перегрин (нейтрально)',
}
DIGNITY_WARN = {'fall': '⚠️⚠️', 'detriment': '⚠️'}
DIGNITY_STAR = {'domicile': '⭐⭐', 'exaltation': '⭐'}
HOUSE_WARN = {h: '⚠️' for h in CADENT_HOUSES} | {EIGHTH_HOUSE: '⚠️'}
HOUSE_STAR = {h: '⭐' for h in ANGULAR_HOUSES}
SIGN_RU = dict(zip(ZODIAC_SIGNS, ZODIAC_SIGNS_RU))
SIGN_SYMBOLS = {
    'Aries': '♈', 'Taurus': '♉', 'Gemini': '♊', 'Cancer': '♋', 'Leo': '♌', 'Virgo': '♍',
    'Libra': '♎', 'Scorpio': '♏', 'Sagittarius': '♐', 'Capricorn': '♑', 'Aquarius': '♒',
    'Pisces': '♓',
}
PLANET_SYMBOLS = {
    'Sun': '☉', 'Moon': '☽', 'Mercury': '☿', 'Venus': '♀', 'Mars': '♂',
    'Jupiter': '♃', 'Saturn': '♄',
}
PLANET_RU = {
    'Sun': 'Солнце', 'Moon': 'Луна', 'Mercury': 'Меркурий', 'Venus': 'Венера',
    'Mars': 'Марс', 'Jupiter': 'Юпитер', 'Saturn': 'Сатурн',
}

OUTER_PLANETS = ('Uranus', 'Neptune', 'Pluto')


# ---------- утилиты ----------

def _lon(value: Any) -> Optional[float]:
    """Долгота из значения: float или dict с full_degree/longitude/degree/cusp_longitude."""
    if isinstance(value, (int, float)):
        return float(value) % 360
    if isinstance(value, dict):
        for key in ('full_degree', 'longitude', 'cusp_longitude', 'degree'):
            if isinstance(value.get(key), (int, float)):
                return float(value[key]) % 360
    return None


def _angle_diff(a: float, b: float) -> float:
    d = abs(a - b) % 360
    return min(d, 360 - d)


def _signed_offset(point: float, cusp: float) -> float:
    """Смещение точки относительно куспида вдоль зодиака в (-180, 180].
    Отрицательное = точка ПЕРЕД куспидом (применяется к нему),
    положительное = точка ЗА куспидом (внутри дома)."""
    d = (point - cusp) % 360
    return d - 360 if d > 180 else d


def _sign_of(longitude: float) -> int:
    return int(longitude // 30) % 12


def _closeness(orb: float, max_orb: float) -> float:
    """«The closer the stronger»: 1.0 вплотную -> 0.5 на границе орба."""
    if max_orb <= 0:
        return 1.0
    return max(0.5, 1.0 - (orb / max_orb) * 0.5)


# ---------- движок карты события ----------

class EventChart:
    """Разбор карты момента матча: значители, куспиды, Фортуна."""

    def __init__(self, transit_houses: Dict[Any, Any], transit_planets: Dict[str, Any],
                 moon_range: float = MOON_RANGE_DEFAULT):
        self.houses = transit_houses
        self.planets = transit_planets
        self.moon_range = moon_range
        self.notes: List[str] = []  # человекочитаемые пометки для листа суждения

        self.cusps: Dict[int, Optional[float]] = {
            n: _lon((self._house(n) or {}).get('cusp_longitude')) for n in range(1, 13)
        }
        self.asc = self.cusps.get(1)
        self.mc = self.cusps.get(10)

        # --- значители: Lords 1/10 = фаворит, Lords 7/4 = соперник ---
        raw = {n: classical_ruler((self._house(n) or {}).get('sign')) for n in RELEVANT_HOUSES}
        self.lords: Dict[int, Optional[str]] = dict(raw)

        # Луна = «поток событий». Если она правит 1-й/7-й — дом представляет её
        # ДИСПОЗИТОР; если 10-й/4-й — обходимся без этого лорда (книга, гл. 2).
        self.moon_substituted_for: Optional[int] = None
        for h in (1, 7):
            if self.lords.get(h) == 'Moon':
                moon = self.planets.get('Moon') or {}
                dispositor = classical_ruler(moon.get('sign'))
                self.lords[h] = dispositor
                self.moon_substituted_for = h
                self.notes.append(
                    f"Луна правит {h}-м домом: дом представляет её диспозитор {dispositor}, "
                    f"Луна остаётся «потоком событий»")
        for h in (10, 4):
            if self.lords.get(h) == 'Moon':
                self.lords[h] = None
                self.notes.append(f"Луна правит {h}-м домом успеха: обходимся без Lord {h}")

        # Конфликт ролей: одна планета правит домами обеих сторон или дом успеха
        # дублирует главный дом -> приоритет Lords 1/7, без Lords 10/4
        # (пример книги: Ювентус-Дортмунд, Lord10=Lord7 и Lord4=Lord1).
        main = {self.lords.get(1), self.lords.get(7)} - {None}
        for h in (10, 4):
            if self.lords.get(h) in main:
                self.notes.append(
                    f"Lord {h} ({self.lords[h]}) совпадает с главным значителем — "
                    f"приоритет Lords 1/7, без Lord {h}")
                self.lords[h] = None
        if self.lords.get(1) and self.lords.get(1) == self.lords.get(7):
            # Один управитель обоих главных домов (Рак/Козерог ASC после подмены и т.п.)
            self.notes.append("Lord 1 и Lord 7 — одна планета: суждение ненадёжно")

        # --- Фортуна: ВСЕГДА дневная формула, «Do I reverse in night charts? NEVER!» ---
        moon, sun = self.planets.get('Moon'), self.planets.get('Sun')
        self.fortuna: Optional[float] = None
        self.fortuna_antiscion: Optional[float] = None
        self.fortuna_dispositor: Optional[str] = None
        if self.asc is not None and moon and sun:
            self.fortuna = (self.asc + moon['full_degree'] - sun['full_degree']) % 360
            self.fortuna_antiscion = antiscion(self.fortuna)
            self.fortuna_dispositor = classical_ruler(self._sign_name(self.fortuna))

    def _house(self, num: int) -> Dict[str, Any]:
        return self.houses.get(num) or self.houses.get(str(num)) or {}

    @staticmethod
    def _sign_name(longitude: float) -> str:
        from app.utils.astrology_v2 import ZODIAC_SIGNS
        return ZODIAC_SIGNS[_sign_of(longitude)]

    def lord_side(self, house: int) -> int:
        """+1 = значитель фаворита, -1 = соперника."""
        return 1 if house in FAVOURITE_HOUSES else -1

    def planet_lon(self, name: Optional[str]) -> Optional[float]:
        p = self.planets.get(name) if name else None
        return _lon(p) if p else None


def _cusp_relation(point_lon: float, cusp_lon: float, cusp_sign: int) -> Optional[Tuple[str, float]]:
    """Отношение точки к куспиду по книге:
    ('on', orb) — до CUSP_ORB° ПЕРЕД куспидом, в знаке куспида: контролирует дом;
    ('inside', orb) — до CUSP_ORB° ЗА куспидом, в знаке куспида: в плену у дома.
    Другой знак = изоляция границей знака («sign boundaries act like insulators»)."""
    off = _signed_offset(point_lon, cusp_lon)
    if -CUSP_ORB <= off < 0 and _sign_of(point_lon) == cusp_sign:
        return 'on', abs(off)
    if 0 <= off <= CUSP_ORB and _sign_of(point_lon) == cusp_sign:
        return 'inside', off
    return None


def _lord_profile(chart: 'EventChart', lord_house: int) -> Optional[Dict[str, Any]]:
    """Профиль значителя (Lord 1 или Lord 7) для гибридного слоя: собственный
    дом, знак, эссенциальное достоинство, сила дома (angular/succedent/
    cadent+8-й, см. HOUSE_STRENGTH), ретроградность."""
    lord = chart.lords.get(lord_house)
    if not lord:
        return None
    data = chart.planets.get(lord) or {}
    lon = _lon(data)
    if lon is None:
        return None
    sign = data.get('sign') or chart._sign_name(lon)
    house_num = data.get('transit_house')
    sun_lon = chart.planet_lon('Sun')
    combust_orb = _angle_diff(lon, sun_lon) if (lord != 'Sun' and sun_lon is not None) else None
    return {
        'lord_house': lord_house,
        'planet': lord,
        'sign': sign,
        'degree_in_sign': round(lon % 30, 2),
        'house': house_num,
        'house_strength': HOUSE_STRENGTH.get(house_num, 0.0) if house_num else 0.0,
        'house_nickname': HOUSE_NICKNAME_RU.get(house_num),
        'dignity': essential_dignity(lord, sign),
        'retrograde': bool(data.get('is_retrograde')),
        'combust': combust_orb is not None and combust_orb <= COMBUST_ORB,
        'combust_orb': combust_orb if (combust_orb is not None and combust_orb <= COMBUST_ORB) else None,
    }


def _house_label_ru(house_num: Optional[int]) -> str:
    """Короткая метка дома для сырого лога тестимоний (не для карточки —
    там используется _house_phrase_ru)."""
    if not house_num:
        return ""
    nickname = HOUSE_NICKNAME_RU.get(house_num)
    return f"дом {house_num}" + (f" («{nickname}»)" if nickname else "")


def _house_phrase_ru(house_num: Optional[int], lord_house: int, planet_ru: str,
                      own_side: str) -> Tuple[str, str]:
    """(описание, эффект) для показания «сила дома» значителя. Формулировки
    по образцу пользователя: succedent (кроме 8-го) — нейтрально «без
    бонуса»; кадентный — слабый минус; 8-й — «смерть», минус без усиления
    словом «сильно»; угловой — «сильно за», с пометкой «свой же!», если дом
    совпадает с номером значителя (Lord1 в 1-м / Lord7 в 7-м)."""
    if not house_num:
        return (f"{planet_ru}: дом неизвестен", "Нейтрально")
    if house_num == EIGHTH_HOUSE:
        return (f"{planet_ru}: Дом 8 («смерть»)", f"Против {own_side}")
    if house_num in CADENT_HOUSES:
        return (f"{planet_ru}: обычный кадентный (не «смерть»)", f"Слабо против {own_side}")
    if house_num in ANGULAR_HOUSES:
        own_house_suffix = " — свой же!" if house_num == lord_house else ""
        return (f"{planet_ru}: угловой {house_num}-й дом{own_house_suffix}",
                f"Сильно за {own_side}")
    return (f"{planet_ru}: succedent, без бонуса", "Нейтрально")


def _dignity_phrase_ru(dignity: str, planet_ru: str, own_side: str) -> Tuple[str, str]:
    """(описание, эффект) для показания «достоинство» значителя."""
    if dignity == 'fall':
        return (f"{planet_ru} в Падении", f"Против {own_side}")
    if dignity == 'detriment':
        return (f"{planet_ru} в Изгнании", f"Против {own_side}")
    if dignity == 'domicile':
        return (f"{planet_ru} в собственной обители", f"За {own_side}")
    if dignity == 'exaltation':
        return (f"{planet_ru} в Экзальтации", f"За {own_side}")
    return (f"{planet_ru}: перегрин", "Нейтрально")


def _mixed_method_testimonies(chart: 'EventChart', add) -> Dict[int, Dict[str, Any]]:
    """Гибридный слой (НЕ из книги гл.2 — сознательная эмпирика пользователя,
    см. plans/daily-forecast-hybrid-method.md). Классическая хорарная
    (гл.1-стиль) оценка Lord 1/7: эссенциальное достоинство, сила их
    СОБСТВЕННОГО дома (angular/succedent/cadent+8-й — HOUSE_STRENGTH),
    ретроградность. Книга прямо запрещает это для карты события («FORGET
    ESSENTIAL DIGNITY... DON'T MIX THE METHODS»), но по месяцу эмпирических
    тестов гибрид даёт точнее прогнозы. Тестимонии помечены source='mixed' и
    намеренно НЕ ищутся в книге (RAG) — см. daily_forecast_analysis, где
    book-only фильтр отсекает их перед поиском."""
    profiles: Dict[int, Dict[str, Any]] = {}
    for lord_house in (1, 7):
        profile = _lord_profile(chart, lord_house)
        if not profile:
            continue
        side = chart.lord_side(lord_house)
        own_side = 'Фаворита' if side > 0 else 'Аутсайдера'
        own_side_dative = 'Фавориту' if side > 0 else 'Аутсайдеру'  # «минус» требует дательного
        planet_ru = PLANET_RU.get(profile['planet'], profile['planet'])
        label = f"{profile['planet']} [L{lord_house}]"
        showings: List[Dict[str, Any]] = []

        # Порядок показаний в карточке: дом ПЕРЕД достоинством (так во всех
        # эталонных примерах пользователя — «succedent, без бонуса» идёт
        # первой строкой, «в Падении/в обители» второй).
        house_num = profile['house']
        w = HOUSE_STRENGTH.get(house_num, 0.0) if house_num else 0.0
        if w:
            add(label, 'house_strength', _house_label_ru(house_num),
                side * w, is_point=False, source='mixed')
        desc, effect = _house_phrase_ru(house_num, lord_house, planet_ru, own_side)
        showings.append({
            'kind': 'house_strength', 'label_ru': desc,
            'warn': HOUSE_WARN.get(house_num, ''), 'star': HOUSE_STAR.get(house_num, ''),
            'effect': effect,  # всегда показываем, даже «Нейтрально» при succedent (w=0)
            'weight': round(w, 2),
        })

        dign = profile['dignity']
        w = W_MIXED_DIGNITY.get(dign, 0.0)
        if w:
            add(label, 'essential_dignity', dign, side * w, is_point=False, source='mixed')
        desc, effect = _dignity_phrase_ru(dign, planet_ru, own_side)
        showings.append({
            'kind': 'dignity', 'label_ru': desc,
            'warn': DIGNITY_WARN.get(dign, ''), 'star': DIGNITY_STAR.get(dign, ''),
            'effect': effect if w else None,
            'weight': round(w, 2),
        })

        # Комбустия: УЖЕ добавлена в testimonies отдельно, книжным способом
        # (секция E judge_event_chart, source='book') — здесь НЕ вызываем
        # add() повторно (иначе задвоим вес в base_score), только строим
        # показание для карточки с тем же весом, что и там.
        combust_w = 0.0
        if profile.get('combust'):
            combust_w = -W_COMBUSTION * _closeness(profile['combust_orb'], COMBUST_ORB)
        showings.append({
            'kind': 'combustion', 'label_ru': f"{planet_ru}: сгорание ({(profile.get('combust_orb') or 0):.2f}°!)",
            'warn': '⚠️' if profile.get('combust') else '', 'star': '',
            'effect': f"Сильно против {own_side}" if profile.get('combust') else None,
            'weight': round(combust_w, 2),
        })

        retro_w = W_MIXED_RETROGRADE if profile['retrograde'] else 0.0
        if profile['retrograde']:
            add(label, 'retrograde', 'Rx', side * retro_w, is_point=False, source='mixed')
        showings.append({
            'kind': 'retrograde', 'label_ru': f"{planet_ru}: ретрограден",
            'warn': '⚠️' if profile['retrograde'] else '', 'star': '',
            'effect': f"Ещё минус {own_side_dative}" if profile['retrograde'] else None,
            'weight': round(retro_w, 2),
            'value': profile['retrograde'],
        })

        profile['showings'] = showings
        profile['own_side'] = own_side
        profiles[lord_house] = profile
    return profiles


def _describe_testimony_ru(t: Dict[str, Any]) -> str:
    """Читаемое описание книжной (гл.2) тестимонии для показаний в карточке."""
    aspect, natal = t['aspect'], t['natal']
    house_natal = natal.replace('house ', 'дом ') if isinstance(natal, str) else natal
    if aspect == 'on_cusp':
        return f"на куспиде {house_natal} — контролирует дом"
    if aspect == 'inside_enemy_house':
        return f"внутри {house_natal} — в плену"
    if aspect == 'inside_own_house':
        return f"в своём {house_natal} — усилен"
    if aspect == 'moon_final_aspect':
        return f"финальный аспект: {natal}"
    if aspect == 'moon_early_aspect':
        return f"ранний аспект к {natal}"
    if aspect == 'fortuna_antiscion_cusp':
        return f"антисция Фортуны у {house_natal}"
    if aspect == 'fortuna_aspect':
        return f"{natal} (Фортуна)"
    if aspect in ('fortuna_dispositor', 'fortuna_dispositor_inside'):
        return f"диспозитор Фортуны: {natal}"
    if aspect == 'node_conjunction':
        return f"на {natal}"
    if aspect == 'combustion':
        return f"сожжение (орб {t['orb']}°)"
    if aspect in ('pluto_on_cusp', 'pluto_fortuna'):
        return f"Плутон: {natal}"
    if aspect in ('uranus_to_mc', 'uranus_fortuna'):
        return "Уран применяется"
    if aspect == 'saturn_afflicts':
        return "поражён Сатурном"
    return f"{aspect} → {natal}"


def _mixed_effect_label(weight: float, own_side: str) -> str:
    """Обобщённая (не bespoke) формулировка эффекта — для книжных (гл.2)
    показаний значителя (on_cusp/moon_final_aspect/узлы/внешние планеты и
    т.п.), для которых нет отдельного шаблона фразы, в отличие от
    dignity/house_strength (см. _dignity_phrase_ru/_house_phrase_ru)."""
    if weight >= 1.5:
        return f"Сильно за {own_side}"
    if weight > 0:
        return f"За {own_side}"
    if weight <= -1.5:
        return f"Сильно против {own_side}"
    if weight < 0:
        return f"Против {own_side}"
    return "Нейтрально"


def _merged_showings(profile: Dict[str, Any], testimonies: List[Dict[str, Any]],
                      side: int, own_side: str) -> List[Dict[str, Any]]:
    """Показания для карточки: собственные (dignity/house_strength/retrograde,
    уже в profile['showings']) + релевантные книжные (гл.2) тестимонии этого
    же значителя (куспиды, комбустия, узлы, внешние планеты и т.п.)."""
    showings = list(profile.get('showings') or [])
    prefix = f"{profile['planet']} [L{profile['lord_house']}"
    for t in testimonies:
        # 'mixed' (dignity/house_strength/retrograde) уже в profile['showings'].
        # 'combustion' (книжная, source='book') — тоже уже там: гибридный слой
        # строит собственное показание сгорания с тем же весом (см.
        # _mixed_method_testimonies), чтобы не дублировать при merge.
        if t.get('source') == 'mixed' or t['aspect'] == 'combustion' or not t['transit'].startswith(prefix):
            continue
        own_weight = t['weight'] * side  # разворачиваем к «за/против своей стороны»
        showings.append({
            'kind': t['aspect'], 'label_ru': _describe_testimony_ru(t),
            'warn': '⚠️' if own_weight < 0 else '', 'star': '⭐' if own_weight > 0 else '',
            'effect': _mixed_effect_label(own_weight, own_side),
            'weight': round(own_weight, 2),
        })
    showings.sort(key=lambda s: abs(s['weight']), reverse=True)
    return showings


def _all_planets_report(chart: 'EventChart') -> List[Dict[str, Any]]:
    """Позиции всех 7 традиционных планет — блок «Планеты» карточки.
    Информационно (не влияет на score вне Lord 1/7)."""
    sun_lon = chart.planet_lon('Sun')
    report: List[Dict[str, Any]] = []
    for planet in ('Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn'):
        data = chart.planets.get(planet)
        if not data:
            continue
        lon = _lon(data)
        if lon is None:
            continue
        sign = data.get('sign') or chart._sign_name(lon)
        house_num = data.get('transit_house')
        dignity = essential_dignity(planet, sign)
        house_strength = HOUSE_STRENGTH.get(house_num, 0.0) if house_num else 0.0
        retro = bool(data.get('is_retrograde'))
        combust_orb = _angle_diff(lon, sun_lon) if (planet != 'Sun' and sun_lon is not None) else None
        combust = combust_orb is not None and combust_orb <= COMBUST_ORB
        warnings = sum([retro, combust, dignity in ('fall', 'detriment'), house_strength < 0])
        report.append({
            'planet': planet, 'planet_ru': PLANET_RU.get(planet, planet),
            'symbol': PLANET_SYMBOLS.get(planet, ''),
            'sign': sign, 'sign_ru': SIGN_RU.get(sign, sign),
            'sign_symbol': SIGN_SYMBOLS.get(sign, ''),
            'degree': round(lon % 30, 2),
            'house': house_num, 'house_nickname': HOUSE_NICKNAME_RU.get(house_num),
            'retrograde': retro,
            'combust': combust, 'combust_orb': round(combust_orb, 2) if combust else None,
            'dignity': dignity, 'dignity_ru': DIGNITY_RU.get(dignity, dignity),
            'warnings': warnings,
        })
    return report


def _build_significator_card(chart: 'EventChart', mixed_profiles: Dict[int, Dict[str, Any]],
                              testimonies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Детерминированная карточка (без LLM): Сигнификаторы + Планеты +
    Показания, формат по образцу пользователя."""
    if chart.asc is None or chart.cusps.get(7) is None:
        return None

    def _point(lon: float) -> Dict[str, Any]:
        sign = chart._sign_name(lon)
        return {
            'sign': sign, 'sign_ru': SIGN_RU.get(sign, sign),
            'symbol': SIGN_SYMBOLS.get(sign, ''), 'degree': round(lon % 30, 2),
        }

    def _side_card(lord_house: int) -> Optional[Dict[str, Any]]:
        profile = mixed_profiles.get(lord_house)
        if not profile:
            return None
        planet = profile['planet']
        side = chart.lord_side(lord_house)
        own_side = profile.get('own_side') or ('Фаворита' if side > 0 else 'Аутсайдера')
        house_num = profile['house']
        dignity = profile['dignity']
        return {
            'lord_house': lord_house,
            'planet': planet, 'planet_ru': PLANET_RU.get(planet, planet),
            'symbol': PLANET_SYMBOLS.get(planet, ''),
            'sign': profile['sign'], 'sign_ru': SIGN_RU.get(profile['sign'], profile['sign']),
            'sign_symbol': SIGN_SYMBOLS.get(profile['sign'], ''),
            'degree': profile['degree_in_sign'],
            'house': house_num, 'house_nickname': profile.get('house_nickname'),
            'house_strength': profile['house_strength'],
            # house_mark: единичный ⭐/⚠️ у «Дом N» в блоке «Планеты» (угловой/кадентный+8-й).
            'house_mark': HOUSE_STAR.get(house_num, '') or HOUSE_WARN.get(house_num, ''),
            'dignity': dignity,
            'dignity_ru': DIGNITY_RU.get(dignity, dignity),
            # dignity_mark: ⭐⭐/⭐/⚠️/⚠️⚠️ у названия достоинства (пусто при peregrine).
            'dignity_mark': DIGNITY_STAR.get(dignity, '') or DIGNITY_WARN.get(dignity, ''),
            'retrograde': profile['retrograde'],
            'combust': profile.get('combust', False),
            'showings': _merged_showings(profile, testimonies, side, own_side),
        }

    favourite = _side_card(1)
    underdog = _side_card(7)
    fav_weight = sum(s['weight'] for s in (favourite or {}).get('showings', []))
    ud_weight = sum(s['weight'] for s in (underdog or {}).get('showings', []))
    diff = fav_weight - ud_weight
    if favourite is None or underdog is None or abs(diff) < 0.3:
        mixed_winner = 'draw'
    elif diff > 0:
        mixed_winner = 'favourite'
    else:
        mixed_winner = 'underdog'

    return {
        'asc': _point(chart.asc),
        'desc': _point(chart.cusps[7]),
        'favourite': favourite,
        'underdog': underdog,
        'planets': _all_planets_report(chart),
        'mixed_winner': mixed_winner,
    }


def judge_event_chart(
    transit_houses: Dict[Any, Any],
    transit_planets: Dict[str, Any],
    moon_range_degrees: float = MOON_RANGE_DEFAULT,
    extra_time_possible: bool = False,
) -> Dict[str, Any]:
    """Суждение карты события по чек-листу гл. 2. Возвращает base_score (1-10),
    testimonies (формат key_aspects фронтенда: transit/aspect/natal/orb/weight/is_point,
    weight>0 = за фаворита, <0 = за соперника) и лист суждения."""
    chart = EventChart(transit_houses, transit_planets,
                       moon_range=moon_range_degrees + (1.0 if extra_time_possible else 0.0))

    testimonies: List[Dict[str, Any]] = []

    def add(transit: str, aspect: str, natal: str, weight: float, orb: float = 0.0,
            is_point: bool = True, source: str = 'book'):
        if abs(weight) < 0.01:
            return
        testimonies.append({
            'transit': transit, 'aspect': aspect, 'natal': natal,
            'orb': round(orb, 2), 'weight': round(weight, 2), 'is_point': is_point,
            'source': source,  # 'book' = гл.2 Frawley; 'mixed' = гибридный слой (см. плейс ниже)
        })

    # ===== A. Положения значителей (и их антисций) у куспидов 1/10/7/4 =====
    # «A PLANET ON A CUSP CONTROLS THAT HOUSE;
    #  A PLANET INSIDE A CUSP IS CONTROLLED BY THAT HOUSE»
    for lord_house in RELEVANT_HOUSES:
        lord = chart.lords.get(lord_house)
        if not lord:
            continue
        lord_lon = chart.planet_lon(lord)
        if lord_lon is None:
            continue
        lord_data = chart.planets.get(lord) or {}
        is_retro = (lord_data.get('speed', 0) or 0) < 0
        side = chart.lord_side(lord_house)
        base_w = W_MAIN_LORD_PLACEMENT if lord_house in (1, 7) else W_SUCCESS_LORD_PLACEMENT

        for body_lon, antisc in ((lord_lon, False), (antiscion(lord_lon), True)):
            for target_house in RELEVANT_HOUSES:
                cusp = chart.cusps.get(target_house)
                if cusp is None:
                    continue
                rel = _cusp_relation(body_lon, cusp, _sign_of(cusp))
                if not rel:
                    continue
                kind, orb = rel
                own_house = (chart.lord_side(target_house) == side)
                factor = _closeness(orb, CUSP_ORB) * (ANTISCION_FACTOR if antisc else 1.0)
                label = f"L{lord_house}{'(ant)' if antisc else ''}"
                if kind == 'on':
                    # Контроль дома -> всегда ЗА сторону лорда; над домом врага —
                    # «нога на горле врага», в своём — просто усиление (слабее).
                    w = base_w if not own_house else min(base_w, W_OWN_HOUSE_BONUS + 0.5)
                    if is_retro and not antisc:
                        w *= RETRO_ON_CUSP_FACTOR  # «still positive, but less strong»
                    add(f"{lord} [{label}]", 'on_cusp', f"house {target_house}",
                        side * w * factor, orb)
                else:  # inside
                    if own_house:
                        # В своём доме сразу за куспидом = усилен (слабое свидетельство).
                        add(f"{lord} [{label}]", 'inside_own_house', f"house {target_house}",
                            side * W_OWN_HOUSE_BONUS * factor, orb)
                    else:
                        # В плену дома врага: «like a man in prison» — ретроградность
                        # не спасает («bang as much as he wants, he is still in prison»).
                        add(f"{lord} [{label}]", 'inside_enemy_house', f"house {target_house}",
                            -side * base_w * factor, orb)

    # ===== B. Луна — «поток событий» =====
    moon = transit_planets.get('Moon')
    moon_report: Dict[str, Any] = {'range': chart.moon_range}
    if moon:
        moon_lon = moon['full_degree']
        # Ход Луны ограничен и границей знака: «THE END OF THE SIGN IS THE LIMIT».
        deg_left_in_sign = 30.0 - (moon_lon % 30.0)
        effective_range = min(chart.moon_range, deg_left_in_sign)
        moon_report['effective_range'] = round(effective_range, 2)

        # Луна у куспидов 1/10/7/4 (применяется к куспиду или сразу внутри) + антисция.
        for body_lon, antisc in ((moon_lon, False), (antiscion(moon_lon), True)):
            for target_house in RELEVANT_HOUSES:
                cusp = chart.cusps.get(target_house)
                if cusp is None:
                    continue
                rel = _cusp_relation(body_lon, cusp, _sign_of(cusp))
                if not rel:
                    continue
                kind, orb = rel
                side = chart.lord_side(target_house)  # Луна в доме = поток К этой стороне
                factor = _closeness(orb, CUSP_ORB) * (ANTISCION_FACTOR if antisc else 1.0)
                add(f"Moon{'(ant)' if antisc else ''}", f"moon_{kind}_cusp",
                    f"house {target_house}", side * W_MOON_PLACEMENT * factor, orb)

        # Секвенсор аспектов Луны: применяющиеся, в пределах effective_range.
        events = _moon_aspect_events(chart, moon, effective_range)
        moon_report['events'] = [
            {'travel': round(e['travel'], 2), 'aspect': e['aspect'], 'target': e['target'],
             'kind': e['kind']} for e in events
        ]
        final_event = None
        early_events: List[Dict[str, Any]] = []
        for e in events:  # отсортированы по пути Луны
            if e['kind'] == 'fortuna':
                final_event = e  # «ASPECTS TO FORTUNA OR ITS ANTISCION ARE FINAL»
                break
            if e['kind'] == 'lord_body' and e['aspect'] == 'conjunction':
                final_event = e  # «BODILY CONJUNCTIONS ARE USUALLY FINAL»
                break
            early_events.append(e)
        if final_event is None and early_events:
            final_event = early_events.pop()  # последний аспект в диапазоне

        for e in early_events:
            # Ранний аспект = ранний перевес («early advantage, often on the scoreboard»)
            side = e['side']
            add('Moon', 'moon_early_aspect', e['target'], side * W_MOON_EARLY_ASPECT,
                e['travel'], is_point=False)
        if final_event:
            side = final_event['side']
            w = W_MOON_FINAL_ASPECT * (ANTISCION_FACTOR if final_event.get('antiscion') else 1.0)
            add('Moon', 'moon_final_aspect',
                f"{final_event['aspect']} {final_event['target']}",
                side * w, final_event['travel'], is_point=False)
            moon_report['final'] = f"{final_event['aspect']} {final_event['target']}"

    # ===== C. Фортуна =====
    if chart.fortuna is not None:
        # C1. Положение АНТИСЦИИ Фортуны у куспидов («ANTISCION, NOT BODILY PLACEMENT»).
        for target_house in RELEVANT_HOUSES:
            cusp = chart.cusps.get(target_house)
            if cusp is None:
                continue
            orb = _angle_diff(chart.fortuna_antiscion, cusp)
            if orb <= CUSP_ORB:
                side = chart.lord_side(target_house)
                w = W_FORTUNA_ANTISCION_PLACEMENT if target_house in (1, 7) else W_SUCCESS_LORD_PLACEMENT
                add('Fortuna(ant)', 'fortuna_antiscion_cusp', f"house {target_house}",
                    side * w * _closeness(orb, CUSP_ORB), orb)

        # C2. Аспекты Lords 1/7 к Фортуне и её антисции (перфектирующие, ~5°).
        for lord_house in (1, 7):
            lord = chart.lords.get(lord_house)
            if not lord or lord == 'Moon':
                continue
            _fortuna_aspect_testimonies(chart, lord, lord_house, add)

        # C3. Диспозитор Фортуны.
        disp = chart.fortuna_dispositor
        main_roles = {chart.lords.get(1), chart.lords.get(7), 'Moon'}
        if disp and disp not in main_roles:
            # если диспозитор = Lord 10/4 — приоритет роли диспозитора (книга)
            disp_lon = chart.planet_lon(disp)
            disp_data = chart.planets.get(disp) or {}
            if disp_lon is not None:
                for point, angle, verdict in (
                    (chart.fortuna, 0, 1), (chart.fortuna, 180, -1),
                ):
                    orb = abs(_angle_diff(disp_lon, point) - angle)
                    if orb <= FORTUNA_ASPECT_ORB and _is_applying_to_point(disp_data, point, angle):
                        add(disp, 'fortuna_dispositor',
                            'conj Fortuna' if angle == 0 else 'opp Fortuna',
                            verdict * W_FORTUNA_DISPOSITOR * _closeness(orb, FORTUNA_ASPECT_ORB), orb)
                # Диспозитор в плену дома 1/7 (пример Ювентус: Солнце-диспозитор в 7-м)
                for target_house in (1, 7):
                    cusp = chart.cusps.get(target_house)
                    if cusp is None:
                        continue
                    rel = _cusp_relation(disp_lon, cusp, _sign_of(cusp))
                    if rel and rel[0] == 'inside':
                        side = chart.lord_side(target_house)
                        add(disp, 'fortuna_dispositor_inside', f"house {target_house}",
                            side * 1.0 * _closeness(rel[1], CUSP_ORB), rel[1])

        # C4. Фортуна на узлах: «Fortuna belongs to the favourite».
        for node, verdict in (('NorthNode', 1), ('SouthNode', -1)):
            node_lon = chart.planet_lon(node)
            if node_lon is not None:
                orb = _angle_diff(chart.fortuna, node_lon)
                if orb <= NODE_ORB:
                    add('Fortuna', 'node_conjunction', node,
                        verdict * W_NODE * _closeness(orb, NODE_ORB), orb)

        # C5. Фортуна комбуст: «good news for the underdogs».
        sun = transit_planets.get('Sun')
        if sun and _angle_diff(chart.fortuna, sun['full_degree']) <= COMBUST_ORB:
            add('Fortuna', 'combustion', 'Sun', -W_COMBUSTION,
                _angle_diff(chart.fortuna, sun['full_degree']))

    # ===== D. Узлы: значитель conj узел (<=2°) =====
    for lord_house in RELEVANT_HOUSES:
        lord = chart.lords.get(lord_house)
        lord_lon = chart.planet_lon(lord)
        if lord_lon is None or lord == 'Moon':  # Луна на узле — ничего
            continue
        side = chart.lord_side(lord_house)
        for node, good in (('NorthNode', True), ('SouthNode', False)):
            node_lon = chart.planet_lon(node)
            if node_lon is None:
                continue
            orb = _angle_diff(lord_lon, node_lon)
            if orb <= NODE_ORB:
                verdict = side if good else -side
                add(f"{lord} [L{lord_house}]", 'node_conjunction', node,
                    verdict * W_NODE * _closeness(orb, NODE_ORB), orb)

    # ===== E. Комбустия 2° (кажими в картах события НЕ существует) =====
    sun = transit_planets.get('Sun')
    if sun:
        seen_combust = set()
        for lord_house in RELEVANT_HOUSES:
            lord = chart.lords.get(lord_house)
            if not lord or lord in ('Sun', 'Moon') or lord in seen_combust:
                continue
            lord_lon = chart.planet_lon(lord)
            if lord_lon is None:
                continue
            orb = _angle_diff(lord_lon, sun['full_degree'])
            if orb <= COMBUST_ORB:
                seen_combust.add(lord)
                side = chart.lord_side(lord_house)
                add(f"{lord} [L{lord_house}]", 'combustion', 'Sun',
                    -side * W_COMBUSTION * _closeness(orb, COMBUST_ORB), orb)

    # ===== F. Внешние планеты =====
    _outer_planet_testimonies(chart, add)

    # ===== G. ГИБРИД: эссенциальное+акцидентальное достоинство Lord 1/7 =====
    # НЕ из книги гл.2 — сознательная эмпирика пользователя (см.
    # plans/daily-forecast-hybrid-method.md). Тестимонии помечены
    # source='mixed' и не участвуют в RAG-поиске по книге.
    mixed_profiles = _mixed_method_testimonies(chart, add)
    significator_card = _build_significator_card(chart, mixed_profiles, testimonies)

    # ===== Итог =====
    testimonies.sort(key=lambda t: abs(t['weight']), reverse=True)
    fav_total = round(sum(t['weight'] for t in testimonies if t['weight'] > 0), 2)
    ud_total = round(-sum(t['weight'] for t in testimonies if t['weight'] < 0), 2)
    score = max(1.0, min(10.0, 5.5 + fav_total - ud_total))

    diff = fav_total - ud_total
    if not testimonies or abs(diff) < 0.5:
        # «Gridlocked» карта: свидетельств нет/баланс -> вероятна ничья
        match_type = 'draw_likely'
    elif diff >= 2.0:
        match_type = 'comfortable_win'
    elif diff >= 0.5:
        match_type = 'advantage'
    elif diff <= -2.0:
        match_type = 'underdog_win_likely'
    else:
        match_type = 'underdog_edge'

    return {
        'base_score': round(score, 1),
        'lords': {f"lord{h}": chart.lords.get(h) for h in RELEVANT_HOUSES},
        'lord1': chart.lords.get(1), 'lord7': chart.lords.get(7),
        'lord10': chart.lords.get(10), 'lord4': chart.lords.get(4),
        'moon_substituted_for': chart.moon_substituted_for,
        'fortuna': round(chart.fortuna, 2) if chart.fortuna is not None else None,
        'fortuna_antiscion': round(chart.fortuna_antiscion, 2) if chart.fortuna_antiscion is not None else None,
        'fortuna_dispositor': chart.fortuna_dispositor,
        'moon_report': moon_report,
        'testimonies': testimonies,
        'favourite_points': fav_total,
        'underdog_points': ud_total,
        'match_type': match_type,
        'engine_notes': chart.notes,
        'mixed_profiles': mixed_profiles,
        'significator_card': significator_card,
    }


def _is_applying_to_point(planet: Dict[str, Any], point_lon: float, aspect_angle: float) -> bool:
    """Планета применяется к аспекту с НЕПОДВИЖНОЙ точкой (Фортуна): орб сокращается."""
    speed = planet.get('speed', 0) or 0
    lon = planet.get('full_degree')
    if lon is None:
        return False
    now = abs(_angle_diff(lon, point_lon) - aspect_angle)
    future = abs(_angle_diff((lon + speed * 0.5) % 360, point_lon) - aspect_angle)
    return future < now


def _moon_aspect_events(chart: EventChart, moon: Dict[str, Any], travel_limit: float) -> List[Dict[str, Any]]:
    """Все применяющиеся события Луны в пределах её хода, по порядку пути:
    аспекты к значителям (тела и антисции) и к Фортуне/её антисции.
    Путь считается в градусах хода Луны с поправкой на скорость цели."""
    moon_lon = moon['full_degree']
    moon_speed = abs(moon.get('speed', 0) or 13.2) or 13.2
    events: List[Dict[str, Any]] = []

    def scan(target_lon: float, target_speed: float, label: str, kind: str,
             side: int, antisc: bool):
        for aspect, angle in ASPECT_ANGLES.items():
            # Луна догоняет аспект: сколько градусов ей идти до точности.
            # Точки аспекта: target_lon ± angle. Луна движется вперёд.
            for direction in (1, -1) if angle not in (0, 180) else (1,):
                point = (target_lon + direction * angle) % 360
                gap = (point - moon_lon) % 360  # путь Луны вперёд до точки
                # Поправка на движение цели (планеты уходят вперёд/назад):
                rel = moon_speed - target_speed
                if rel <= 0.1:
                    continue
                travel = gap * moon_speed / rel
                if 0.01 <= travel <= travel_limit:
                    events.append({
                        'travel': travel, 'aspect': aspect, 'target': label,
                        'kind': kind, 'side': side, 'antiscion': antisc,
                    })

    # Значители (тела + антисции)
    for lord_house in RELEVANT_HOUSES:
        lord = chart.lords.get(lord_house)
        if not lord or lord == 'Moon':
            continue
        lord_lon = chart.planet_lon(lord)
        if lord_lon is None:
            continue
        lord_speed = (chart.planets.get(lord) or {}).get('speed', 0) or 0
        side = chart.lord_side(lord_house)
        scan(lord_lon, lord_speed, f"{lord} [L{lord_house}]", 'lord_body', side, False)
        # Антисции лордов: соединения на коротком ходе НЕ финальны, вес ниже.
        scan(antiscion(lord_lon), -lord_speed, f"{lord} [L{lord_house}](ant)",
             'lord_antiscion', side, True)

    # Фортуна и её антисция: аспект к ним ФИНАЛЕН; знак решает тип аспекта.
    if chart.fortuna is not None:
        for point, label in ((chart.fortuna, 'Fortuna'), (chart.fortuna_antiscion, 'Fortuna(ant)')):
            for aspect, angle in ASPECT_ANGLES.items():
                for direction in (1, -1) if angle not in (0, 180) else (1,):
                    p = (point + direction * angle) % 360
                    gap = (p - moon_lon) % 360
                    travel = gap  # Фортуна неподвижна
                    if 0.01 <= travel <= travel_limit:
                        side = 1 if aspect in HARMONIOUS_ASPECTS else -1
                        events.append({
                            'travel': travel, 'aspect': aspect, 'target': label,
                            'kind': 'fortuna', 'side': side,
                            'antiscion': label.endswith('(ant)'),
                        })

    # Дедуп (одно и то же событие через два direction) и сортировка по пути.
    seen = set()
    unique = []
    for e in sorted(events, key=lambda x: x['travel']):
        key = (e['aspect'], e['target'], round(e['travel'], 1))
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return unique


def _fortuna_aspect_testimonies(chart: EventChart, lord: str, lord_house: int, add) -> None:
    """Аспекты Lord 1/7 к Фортуне/антисции (гл. 2):
    L1 conj Фортуна/антисция -> фаворит; L1 opp -> соперник;
    L7 conj -> соперник; L7 opp антисции -> фаворит;
    АНОМАЛИЯ книги: L7 телесная оппозиция Фортуне -> СОПЕРНИК.
    Trine/sextile/square Lords 1/7 к Фортуне ненадёжны — игнор.
    «MAKE SURE THE ASPECT ACTUALLY HAPPENS» — перехват другой планетой отменяет."""
    lord_lon = chart.planet_lon(lord)
    lord_data = chart.planets.get(lord) or {}
    if lord_lon is None or chart.fortuna is None:
        return

    def prohibited(travel_orb: float) -> bool:
        """Лорд перфектирует аспект к другой планете раньше, чем дойдёт до Фортуны."""
        speed = abs(lord_data.get('speed', 0) or 0)
        if speed < 1e-6:
            return True  # стоит на месте — не дойдёт
        for other, odata in chart.planets.items():
            if other == lord or other not in TRADITIONAL_PLANETS or other == 'Moon':
                continue
            olon = _lon(odata)
            if olon is None:
                continue
            for angle in ASPECT_ANGLES.values():
                orb_now = abs(_angle_diff(lord_lon, olon) - angle)
                rel = abs(speed - abs(odata.get('speed', 0) or 0))
                if rel < 1e-6:
                    continue
                if orb_now < travel_orb and _is_applying_to_point(
                        lord_data, (olon + angle) % 360, 0):
                    return True
        return False

    checks = []
    if lord_house == 1:
        checks = [
            (chart.fortuna, 0, +1, 'conj Fortuna'),
            (chart.fortuna_antiscion, 0, +1, 'conj Fortuna(ant)'),
            (chart.fortuna, 180, -1, 'opp Fortuna'),
            (chart.fortuna_antiscion, 180, -1, 'opp Fortuna(ant)'),
        ]
    else:  # Lord 7
        checks = [
            (chart.fortuna, 0, -1, 'conj Fortuna'),
            (chart.fortuna_antiscion, 0, -1, 'conj Fortuna(ant)'),
            (chart.fortuna_antiscion, 180, +1, 'opp Fortuna(ant)'),
            (chart.fortuna, 180, -1, 'opp Fortuna'),  # аномалия книги
        ]
    for point, angle, verdict, label in checks:
        if point is None:
            continue
        orb = abs(_angle_diff(lord_lon, point) - angle)
        if orb <= FORTUNA_ASPECT_ORB and _is_applying_to_point(lord_data, point, angle):
            if prohibited(orb):
                continue
            add(f"{lord} [L{lord_house}]", 'fortuna_aspect', label,
                verdict * W_FORTUNA_ASPECT * _closeness(orb, FORTUNA_ASPECT_ORB), orb)


def _outer_planet_testimonies(chart: EventChart, add) -> None:
    """Плутон/Уран/Сатурн по гл. 2. Нептун — игнор («inconsistent»)."""
    # Плутон: «powerful destructive effect on a relevant cusp... holds a grudge
    # against favourites»; на 2-м куспиде — вредит фавориту.
    pluto_lon = chart.planet_lon('Pluto')
    if pluto_lon is not None:
        for house, side in ((1, 1), (10, 1), (2, 1), (7, -1), (4, -1)):
            cusp = chart.cusps.get(house)
            if cusp is None:
                continue
            orb = _angle_diff(pluto_lon, cusp)
            if orb <= OUTER_ORB:
                w = W_PLUTO if side > 0 else W_PLUTO * 0.5  # к андердогу он снисходительнее
                add('Pluto', 'pluto_on_cusp', f"house {house}",
                    -side * w * _closeness(orb, OUTER_ORB), orb)
        for point, label in ((chart.fortuna, 'Fortuna'),
                             (chart.fortuna_antiscion, 'Fortuna(ant)'),
                             (chart.planet_lon(chart.fortuna_dispositor), 'Fortuna dispositor')):
            if point is None:
                continue
            for angle in (0, 180):
                orb = abs(_angle_diff(pluto_lon, point) - angle)
                if orb <= OUTER_ORB:
                    add('Pluto', 'pluto_fortuna', label,
                        -W_PLUTO * 0.8 * _closeness(orb, OUTER_ORB), orb)

    # Уран: немедленно применяется к MC или conj Фортуна -> фаворит; opp Фортуна -> соперник.
    uranus = chart.planets.get('Uranus')
    uranus_lon = _lon(uranus) if uranus else None
    if uranus_lon is not None:
        if chart.mc is not None:
            orb = _angle_diff(uranus_lon, chart.mc)
            if orb <= OUTER_ORB and _is_applying_to_point(uranus, chart.mc, 0):
                add('Uranus', 'uranus_to_mc', 'MC', W_URANUS * _closeness(orb, OUTER_ORB), orb)
        if chart.fortuna is not None:
            orb_c = _angle_diff(uranus_lon, chart.fortuna)
            orb_o = abs(_angle_diff(uranus_lon, chart.fortuna) - 180)
            if orb_c <= OUTER_ORB:
                add('Uranus', 'uranus_fortuna', 'conj Fortuna', W_URANUS * _closeness(orb_c, OUTER_ORB), orb_c)
            elif orb_o <= OUTER_ORB:
                add('Uranus', 'uranus_fortuna', 'opp Fortuna', -W_URANUS * _closeness(orb_o, OUTER_ORB), orb_o)
            # opp антисции Фортуны — пример Super Bowl 2002 (за андердога)
            orb_a = abs(_angle_diff(uranus_lon, chart.fortuna_antiscion) - 180)
            if orb_a <= OUTER_ORB:
                add('Uranus', 'uranus_fortuna', 'opp Fortuna(ant)', -W_URANUS * _closeness(orb_a, OUTER_ORB), orb_a)

    # Сатурн-малефик (если не Lord 1/7): «afflicting whatever it touches».
    if 'Saturn' not in (chart.lords.get(1), chart.lords.get(7)):
        saturn_lon = chart.planet_lon('Saturn')
        if saturn_lon is not None:
            for lord_house in (1, 7):
                lord = chart.lords.get(lord_house)
                lord_lon = chart.planet_lon(lord)
                if lord_lon is None:
                    continue
                orb = _angle_diff(saturn_lon, lord_lon)
                if orb <= SATURN_ORB:
                    side = chart.lord_side(lord_house)
                    add('Saturn', 'saturn_afflicts', f"{lord} [L{lord_house}]",
                        -side * W_SATURN_MALEFIC * _closeness(orb, SATURN_ORB), orb)
            for house in (1, 7):
                cusp = chart.cusps.get(house)
                if cusp is None:
                    continue
                orb = _angle_diff(saturn_lon, cusp)
                if orb <= SATURN_ORB:
                    side = chart.lord_side(house)
                    add('Saturn', 'saturn_afflicts', f"house {house} cusp",
                        -side * W_SATURN_MALEFIC * _closeness(orb, SATURN_ORB), orb)


# ---------- натальная сноска (не скоринг) ----------

def natal_personalization_note(natal_chart: Dict[str, Any], lord1: Optional[str],
                               language: str) -> Optional[str]:
    """Контекст: значитель фаворита совпадает с управителем натального ASC атлета.
    Только упоминание для LLM, в скоринге не участвует."""
    if not lord1:
        return None
    houses = natal_chart.get('houses') or {}
    asc_entry = houses.get(1) or houses.get('1')
    natal_asc_sign = (asc_entry or {}).get('sign') if isinstance(asc_entry, dict) else None
    if not natal_asc_sign or classical_ruler(natal_asc_sign) != lord1:
        return None
    if language == 'ru':
        return (f"Значитель фаворита в карте матча ({lord1}) совпадает с управителем "
                f"натального Асцендента атлета — усиленная личная значимость дня.")
    return (f"The favourite's significator ({lord1}) is also the athlete's natal "
            f"Ascendant ruler — heightened personal significance of this day.")


def _chunk_text(chunk: Any) -> str:
    if isinstance(chunk, dict):
        return str(chunk.get('content') or chunk.get('text') or chunk.get('chunk_text') or '')
    return str(chunk)


def _testimony_query(t: Dict[str, Any]) -> str:
    """RAG-запрос по терминам главы 2 (event chart), не хорарным."""
    aspect = t['aspect']
    if aspect == 'on_cusp':
        return "planet on cusp controls that house event chart favourite underdog"
    if aspect == 'inside_enemy_house':
        return "planet inside cusp controlled by house prison event chart"
    if aspect == 'inside_own_house':
        return "lord on or in its own house strengthened event chart"
    if aspect == 'moon_final_aspect':
        return "moon final aspect wins flow of events favourite underdog"
    if aspect == 'moon_early_aspect':
        return "moon immediate aspect early advantage scoreboard"
    if aspect.startswith('moon_') and 'cusp' in aspect:
        return "moon applying close inside first tenth seventh fourth cusp victory"
    if aspect == 'fortuna_antiscion_cusp':
        return "antiscion of fortuna close to cusp favourite wins most powerful testimony"
    if aspect == 'fortuna_aspect':
        return "lord conjunct oppose part of fortune antiscion favourite underdog"
    if aspect in ('fortuna_dispositor', 'fortuna_dispositor_inside'):
        return "dispositor of the part of fortune conjunct oppose fortuna"
    if aspect == 'node_conjunction':
        return "significator conjunct north node south node strengthened weakened"
    if aspect == 'combustion':
        return "combustion significator within two degrees of the sun event chart"
    if aspect == 'pluto_on_cusp' or aspect == 'pluto_fortuna':
        return "pluto destructive relevant cusp grudge against favourites"
    if aspect == 'uranus_to_mc' or aspect == 'uranus_fortuna':
        return "uranus applying midheaven conjunct fortuna favours favourites"
    if aspect == 'saturn_afflicts':
        return "saturn malefic afflicting whatever it touches event chart"
    return f"{t['transit']} {aspect} {t['natal']} event chart"


def _split_sides(testimonies: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    fav = [t for t in testimonies if t['weight'] > 0]
    ud = [t for t in testimonies if t['weight'] < 0]
    return fav, ud


# ---------- детерминированный рендер карточки (без LLM) ----------
# LLM неоднократно искажал факты листа суждения (путал дом значителя, спорил
# с гибридными показаниями цитатами книги) — поэтому score/Показания/Вывод
# строятся напрямую из значений расчёта. См. plans/daily-forecast-hybrid-method.md.

def _side_showings_list(side: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Только 4 гибридных показания значителя (дом/достоинство/сгорание/
    ретро), в этом порядке, без книжных (гл.2) тестимоний — единый источник
    для карточки (_showing_pairs_ru) и для короткой прозы (_side_narrative_ru),
    чтобы они не расходились между собой."""
    by_kind = {s['kind']: s for s in side['showings']
               if s['kind'] in ('house_strength', 'dignity', 'combustion', 'retrograde')}
    ordered: List[Dict[str, Any]] = []
    house_showing = by_kind.get('house_strength')
    if house_showing and house_showing.get('effect') is not None:
        ordered.append(house_showing)
    dignity_showing = by_kind.get('dignity')
    if dignity_showing and side['dignity'] != 'peregrine' and dignity_showing.get('effect') is not None:
        ordered.append(dignity_showing)
    combust_showing = by_kind.get('combustion')
    if combust_showing and combust_showing.get('effect') is not None:
        ordered.append(combust_showing)
    retro_showing = by_kind.get('retrograde')
    if retro_showing and retro_showing.get('effect') is not None:
        ordered.append(retro_showing)
    return ordered


def _side_narrative_ru(side: Optional[Dict[str, Any]], own_label: str) -> str:
    if not side:
        return f"У {own_label.lower()} нет определённого значителя дома в этой карте."
    nickname = f" («{side['house_nickname']}»)" if side.get('house_nickname') else ""
    retro = ", ретрограден" if side['retrograde'] else ""
    text = (f"{side['planet_ru']} ({own_label}), управитель дома {side['lord_house']}, находится в "
            f"{side['sign_ru']} {side['degree']}°, дом {side['house']}{nickname}{retro}. "
            f"Достоинство: {side['dignity_ru']}.")
    items = _side_showings_list(side)
    if items:
        text += " Показания: " + "; ".join(
            f"{s['label_ru']} — {s['effect']}" for s in items
        ) + "."
    else:
        text += " Значимых показаний нет — позиция нейтральна."
    return text


def _verdict_narrative_ru(card: Optional[Dict[str, Any]]) -> str:
    """Короткий вердикт для поля verdict — та же карточно-скоуп-логика
    (_card_verdict), что и в детальной карточке, не общий judgement['match_type']."""
    decisive, winner, _diff = _card_verdict(card)
    if winner is None:
        headline = "Карта сбалансирована — вероятна ничья или непредсказуемый исход."
    elif decisive:
        headline = f"{_NOMINATIVE_RU[winner]} побеждает."
    else:
        headline = f"Небольшой перевес {_GENITIVE_RU[winner]}."
    return headline + " " + _verdict_paragraph_ru(card)


# ---------- детальная карточка (формат «Сигнификаторы/Планеты/Показания/Вывод») ----------
# Точный формат по образцу пользователя (event-chart карточки). Только
# форматирование уже посчитанных данных (significator_card/judgement) —
# расчёт/скоринг здесь не участвует и не меняется. Хедер — только generic-
# вариант («Event Chart · место · дата · время · Роли: Фаворит / Аутсайдер»):
# имена игроков/спред/коэффициенты не входят в текущую схему запроса.

_NOMINATIVE_RU = {'favourite': 'Фаворит', 'underdog': 'Аутсайдер'}
_GENITIVE_RU = {'favourite': 'Фаворита', 'underdog': 'Аутсайдера'}

# Пороги ИМЕННО для вывода карточки — НЕ те же, что у общего match_type
# (judgement['match_type'], который считается по всему листу гл.2+гибрид).
# Подобраны и проверены на 4 эталонных примерах пользователя (Båstad,
# Arlington, Umag, Юпитер/Меркурий): |diff| >= 1.5 -> решительный исход,
# 0.3 <= |diff| < 1.5 -> лёгкий перевес, < 0.3 -> ничья/неочевидно.
CARD_DECISIVE_THRESHOLD = 1.5
CARD_EDGE_THRESHOLD = 0.3


def _card_verdict(card: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str], float]:
    """Вывод карточки считается ТОЛЬКО по 4 факторам, видимым в «Показания»
    (дом/достоинство/сгорание/ретро Lord1 и Lord7) — НЕ по общему base_score/
    match_type, куда подмешиваются куспиды/Луна/Фортуна/узлы/внешние планеты
    (те влияют на общий расчёт, но не показаны в этой карточке и не должны
    определять её собственный вывод — иначе вывод карточки перестаёт
    соответствовать тому, что в ней реально показано).
    Возвращает (decisive, winner['favourite'|'underdog'|None], diff)."""
    if not card or not card.get('favourite') or not card.get('underdog'):
        return False, None, 0.0

    def _net(side: Dict[str, Any]) -> float:
        return sum(
            s['weight'] for s in side['showings']
            if s['kind'] in ('house_strength', 'dignity', 'combustion', 'retrograde')
        )

    diff = _net(card['favourite']) - _net(card['underdog'])
    if abs(diff) < CARD_EDGE_THRESHOLD:
        return False, None, diff
    winner = 'favourite' if diff > 0 else 'underdog'
    decisive = abs(diff) >= CARD_DECISIVE_THRESHOLD
    return decisive, winner, diff


def _card_match_type(card: Optional[Dict[str, Any]]) -> str:
    """match_type СТРОГО из карточного вердикта (_card_verdict) — тем же
    словарём значений, что и раньше (comfortable_win/advantage/draw_likely/
    underdog_edge/underdog_win_likely), чтобы существующие потребители поля
    не ломались. Раньше это поле бралось из judgement['match_type'] (полный
    расчёт гл.2+гибрид) — оно могло противоречить тексту карточки/verdict,
    т.к. считалось по другому набору тестимоний. Теперь только один источник
    правды: 4 фактора, реально показанные в карточке."""
    decisive, winner, _diff = _card_verdict(card)
    if winner is None:
        return 'draw_likely'
    if winner == 'favourite':
        return 'comfortable_win' if decisive else 'advantage'
    return 'underdog_win_likely' if decisive else 'underdog_edge'


def _render_header_ru(transits: Dict[str, Any]) -> str:
    location = (transits.get('transit_summary') or {}).get('location') or {}
    place = location.get('place_name') or '—'
    date_part, time_part = '—', '—'
    target_date_str = transits.get('target_date')
    if target_date_str:
        try:
            dt = datetime.fromisoformat(target_date_str)
            date_part = dt.strftime('%d.%m.%Y')
            time_part = dt.strftime('%H:%M')
            offset = dt.strftime('%z')  # напр. +0200
            if offset:
                time_part += f" UTC{offset[:3]}:{offset[3:]}"
        except ValueError:
            pass
    line1 = f"Event Chart · {place} · {date_part} · {time_part}"
    line2 = "Плацидус · Kick-off · Роли: Фаворит / Аутсайдер"
    return line1 + "\n" + line2


def _planet_line_lord_ru(side: Dict[str, Any], role_ru: str) -> List[str]:
    header = f"{side['symbol']} {side['planet_ru']} ({role_ru})"
    retro_mark = " ℞" if side['retrograde'] else ""
    dignity_part = f" · {side['dignity_ru']}" if side['dignity'] != 'peregrine' else ""
    dignity_mark = f" {side['dignity_mark']}" if side.get('dignity_mark') else ""
    house_mark = f" {side['house_mark']}" if side.get('house_mark') else ""
    detail = (f"{side['sign_symbol']} {side['degree']:.2f}°{retro_mark} · "
              f"Дом {side['house']}{house_mark}{dignity_part}{dignity_mark}")
    return [header, detail]


def _planet_line_plain_ru(p: Dict[str, Any]) -> List[str]:
    header = f"{p['symbol']} {p['planet_ru']}"
    retro_mark = " ℞" if p['retrograde'] else ""
    detail = f"{p['sign_symbol']} {p['degree']:.2f}°{retro_mark} · Дом {p['house']}"
    return [header, detail]


def _showing_pairs_ru(side: Dict[str, Any]) -> List[str]:
    """Пары строк (описание, эффект) для блока «Показания» одного значителя:
    дом → достоинство (если не peregrine) → сгорание (если есть) → ретро
    (если есть) — каждое отдельной строкой, а не сводкой. Только гибридные
    показания значителя (house_strength/dignity/combustion/retrograde) —
    остальные книжные (гл.2) тестимонии сюда НЕ входят, они относятся к
    отдельному «расчётному листу», не к этой карточке. Порядок фиксирован
    по kind явно (не по весу — side['showings'] может быть пересортирован,
    см. _merged_showings)."""
    by_kind = {s['kind']: s for s in side['showings']
               if s['kind'] in ('house_strength', 'dignity', 'combustion', 'retrograde')}
    lines: List[str] = []
    house_showing = by_kind.get('house_strength')
    if house_showing and house_showing.get('effect') is not None:
        lines += [house_showing['label_ru'], house_showing['effect']]
    dignity_showing = by_kind.get('dignity')
    if dignity_showing and side['dignity'] != 'peregrine' and dignity_showing.get('effect') is not None:
        lines += [dignity_showing['label_ru'], dignity_showing['effect']]
    combust_showing = by_kind.get('combustion')
    if combust_showing and combust_showing.get('effect') is not None:
        lines += [combust_showing['label_ru'], combust_showing['effect']]
    retro_showing = by_kind.get('retrograde')
    if retro_showing and retro_showing.get('effect') is not None:
        lines += [retro_showing['label_ru'], retro_showing['effect']]
    return lines


def _retro_combust_summary_ru(fav: Optional[Dict[str, Any]],
                               ud: Optional[Dict[str, Any]]) -> List[str]:
    """Fallback-строка «Ретро/сгорание: Нет ни у кого» — только если НИ У
    ОДНОГО значителя нет ни ретро, ни сожжения (иначе они уже показаны
    отдельными строками в _showing_pairs_ru для каждого значителя)."""
    for side in (fav, ud):
        if side and (side['retrograde'] or side.get('combust')):
            return []
    return ["Ретро/сгорание", "Нет ни у кого"]


def _verdict_paragraph_ru(card: Optional[Dict[str, Any]]) -> str:
    """Самодостаточное объяснение вывода из ЭТОЙ карты (без сравнений с
    другими, неизвестными системе картами). Берёт готовые читаемые формулировки
    (label_ru/effect) из показаний карточки — НЕ сырые коды тестимоний, чтобы
    не утекали внутренние имена вроде «essential_dignity»."""
    if not card or not card.get('favourite') or not card.get('underdog'):
        return "Свидетельств в карте немного, перевес не выражен явно."
    fav, ud = card['favourite'], card['underdog']
    ranked: List[Dict[str, Any]] = []
    for side in (fav, ud):
        for s in side['showings']:
            if s['kind'] not in ('house_strength', 'dignity', 'combustion', 'retrograde'):
                continue
            if s.get('effect') is None:
                continue
            if s['kind'] == 'dignity' and side['dignity'] == 'peregrine':
                continue
            ranked.append(s)
    ranked.sort(key=lambda s: abs(s['weight']), reverse=True)
    top = ranked[:2]
    if not top:
        return "Свидетельств в карте немного, перевес не выражен явно."
    text = "Решающие показания: " + "; ".join(
        f"{s['label_ru']} — {s['effect']}" for s in top
    ) + "."
    fh, uh = fav['house'], ud['house']
    if fh and fh == uh:
        nickname = fav.get('house_nickname')
        label = f" («{nickname}»)" if nickname else ""
        text += (f" Оба значителя делят дом {fh}{label} — этот фактор частично "
                f"взаимно гасится, решают остальные повреждения и усиления.")
    return text


def _render_card_text_ru(transits: Dict[str, Any], judgement: Dict[str, Any],
                          card: Optional[Dict[str, Any]]) -> str:
    """Полная текстовая карточка (Сигнификаторы/Планеты/Показания/Вывод) —
    формат по образцу пользователя. Fallback на короткий нарратив, если
    карта не построена (нет ASC/7-го куспида)."""
    if not card:
        return _verdict_narrative_ru(card)

    fav, ud = card.get('favourite'), card.get('underdog')
    asc, desc = card.get('asc'), card.get('desc')

    lines: List[str] = [_render_header_ru(transits), "Сигнификаторы"]
    if asc:
        lines += ["АСЦ (1-й дом, Фаворит)", f"{asc['symbol']} {asc['sign_ru']} {asc['degree']:.2f}°"]
    if desc:
        lines += ["7-й дом (Аутсайдер)", f"{desc['symbol']} {desc['sign_ru']} {desc['degree']:.2f}°"]
    if fav:
        lines += ["Lord 1 = Фаворит", f"{fav['symbol']} {fav['planet_ru']}"]
    if ud:
        lines += ["Lord 7 = Аутсайдер", f"{ud['symbol']} {ud['planet_ru']}"]

    lines.append("Планеты")
    if fav:
        lines += _planet_line_lord_ru(fav, 'Фаворит')
    if ud:
        lines += _planet_line_lord_ru(ud, 'Аутсайдер')
    lord_planets = {p for p in (fav and fav['planet'], ud and ud['planet']) if p}
    for p in (card.get('planets') or []):
        if p['planet'] in lord_planets:
            continue
        lines += _planet_line_plain_ru(p)

    lines.append("Показания")
    if fav:
        lines += _showing_pairs_ru(fav)
    if ud:
        lines += _showing_pairs_ru(ud)
    lines += _retro_combust_summary_ru(fav, ud)

    decisive, winner, _diff = _card_verdict(card)
    emoji = '🏆' if decisive else '⚖️'
    headline = f"{_NOMINATIVE_RU[winner]} побеждает" if (decisive and winner) else "случай пограничный"
    lines.append(f"{emoji} Вывод: {headline}")
    lines.append(_verdict_paragraph_ru(card))
    if decisive and winner:
        lines.append(f"Прогноз: {_NOMINATIVE_RU[winner]} выигрывает, случай однозначный")
    elif winner:
        lines.append(f"Лёгкий перевес {_GENITIVE_RU[winner]}, случай неочевидный")
    else:
        lines.append("Ничья вероятна, случай неочевидный")
    return "\n".join(lines)


async def daily_forecast_analysis(
    natal_chart: Dict[str, Any],
    transits: Dict[str, Any],
    language: str = 'ru',
    provider: Optional[str] = None,
    model: Optional[str] = None,
    moon_range_degrees: float = MOON_RANGE_DEFAULT,
    extra_time_possible: bool = False,
) -> Dict[str, Any]:
    """Полный пайплайн прогноза дня матча (метод карты события).
    transits — результат calculate_transits (должен содержать transit_houses)."""
    t_planets = transits.get('transit_planets', {}) or {}
    transit_houses = transits.get('transit_houses') or {}

    if not transit_houses:
        judgement = {
            'base_score': 5.5, 'lord1': None, 'lord7': None, 'lord10': None, 'lord4': None,
            'testimonies': [], 'favourite_points': 0, 'underdog_points': 0,
            'match_type': 'draw_likely', 'engine_notes': ['нет transit_houses — нейтральная оценка'],
            'mixed_profiles': {}, 'significator_card': None,
        }
    else:
        judgement = judge_event_chart(
            transit_houses, t_planets,
            moon_range_degrees=moon_range_degrees,
            extra_time_possible=extra_time_possible,
        )

    base = judgement['base_score']  # внутренний расчёт (влияет на match_type), наружу не отдаётся
    key_aspects = judgement['testimonies']
    fav_list, ud_list = _split_sides(key_aspects)

    houses_activated = sorted({
        int(p.get('natal_house')) for p in t_planets.values()
        if isinstance(p, dict) and p.get('natal_house')
    })

    personal_note = natal_personalization_note(natal_chart, judgement.get('lord1'), language)

    # RAG по свидетельствам карты события
    async def search_testimony(t: Dict[str, Any]):
        query = _testimony_query(t)
        chunks = await search_chunks_priority_book(
            query, DAILY_FORECAST_PRIORITY_BOOK_ID, top_k_priority=5, top_k_others=0
        )
        return query, chunks

    # Гибридные тестимонии (source='mixed': эссенциальное достоинство/угловатость/
    # ретроградность Lord 1/7) намеренно НЕ ищутся в книге: книга гл.2 прямо
    # запрещает эти понятия для карты события, RAG вернул бы противоречащие
    # цитаты. См. plans/daily-forecast-hybrid-method.md.
    book_testimonies = [t for t in key_aspects if t.get('source', 'book') != 'mixed']
    rag_results = await asyncio.gather(
        *[search_testimony(t) for t in book_testimonies], return_exceptions=True
    )
    # Дедуп чанков + бюджет символов: один фрагмент книги кладём в промпт один раз.
    CHUNK_CHARS = 1500
    RAG_CHARS_BUDGET = 40000
    rag_blocks: List[str] = []
    rag_sources: List[Dict[str, Any]] = []
    seen_global = set()
    used_chars = 0
    for res in rag_results:
        if isinstance(res, Exception):
            continue
        query, chunks = res
        for c in (chunks or []):
            t = _chunk_text(c)
            if not t:
                continue
            ck = (c.get('id') if isinstance(c, dict) else None) or t[:120]
            if ck in seen_global:
                continue
            if used_chars >= RAG_CHARS_BUDGET:
                break
            seen_global.add(ck)
            snippet = t[:CHUNK_CHARS]
            used_chars += len(snippet)
            rag_blocks.append(f"[{query}]\n{snippet}")
            rag_sources.append({
                'query': query,
                'book_id': c.get('book_id') if isinstance(c, dict) else None,
                'book_title': c.get('book_title') if isinstance(c, dict) else None,
                'chunk_id': c.get('id') if isinstance(c, dict) else None,
                'page': c.get('page') if isinstance(c, dict) else None,
                'text': t[:500],
                'text_full': snippet,
                'full_chars': len(t),
            })

    card = judgement.get('significator_card')

    print(f"[daily_forecast] testimonies={len(key_aspects)} (fav={len(fav_list)}/ud={len(ud_list)}) "
          f"rag_blocks={len(rag_blocks)} lord1={judgement.get('lord1')} lord7={judgement.get('lord7')} "
          f"lord10={judgement.get('lord10')} lord4={judgement.get('lord4')} "
          f"match_type={judgement.get('match_type')} base_score={judgement.get('base_score')} "
          f"fortuna={judgement.get('fortuna')} fortuna_antiscion={judgement.get('fortuna_antiscion')}")
    for t in key_aspects:
        print(f"[daily_forecast]   testimony: {t['transit']} [{t['aspect']}] -> {t['natal']} "
              f"orb={t['orb']} weight={t['weight']:+} source={t.get('source', 'book')}")
    for note in (judgement.get('engine_notes') or []):
        print(f"[daily_forecast]   engine_note: {note}")

    # Детерминированный рендер (без LLM): score/Показания/Вывод строятся
    # напрямую из расчётного листа. LLM ранее свободным текстом искажал факты
    # (путал дом значителя, спорил с гибридными показаниями цитатами книги) —
    # см. plans/daily-forecast-hybrid-method.md.
    # card_text — основной, подробный вывод (формат Сигнификаторы/Планеты/
    # Показания/Вывод). favorite/opponent/verdict — те же данные короткой
    # прозой, для фронтов, которые ещё читают эти отдельные поля.
    card_text = _render_card_text_ru(transits, judgement, card)
    favorite_text = _side_narrative_ru(card.get('favourite') if card else None, 'Фаворит')
    opponent_text = _side_narrative_ru(card.get('underdog') if card else None, 'Аутсайдер')
    verdict_text = _verdict_narrative_ru(card)
    summary_text = card_text
    if personal_note:
        summary_text += f"\n\n{personal_note}"
    # По требованию продукта score/category (числовая оценка 1-10) НЕ
    # выводятся в ответе — только качественный вердикт (match_type) и
    # текстовое описание. base_score остаётся внутренним расчётным
    # значением (влияет на match_type), но наружу не отдаётся.
    parsed = {
        'favorite': favorite_text, 'opponent': opponent_text, 'verdict': verdict_text,
        'summary': summary_text, 'card_text': card_text,
    }
    llm_error: Optional[str] = None  # генерация детерминированная, LLM не вызывается

    return {
        **parsed,
        'key_aspects': key_aspects,
        'significator_card': judgement.get('significator_card'),
        'houses_activated': houses_activated,
        'fortune': judgement.get('fortuna'),
        'fortune_antiscion': judgement.get('fortuna_antiscion'),
        'lunar_phase': transits.get('lunar_phase'),
        'llm_error': llm_error,
        'llm_provider': provider,  # эхо для фронта; генерация детерминированная, не используется
        'llm_model': model,
        'generation_mode': 'deterministic',
        'rag_sources': rag_sources,
        'personal_note': personal_note,
        # strength_breakdown: сохраняем ключи lord1/lord7 для фронта,
        # total_strength = суммарные очки стороны по листу суждения.
        'strength_breakdown': {
            'lord1': {
                'planet': judgement.get('lord1'),
                'success_lord': judgement.get('lord10'),
                'total_strength': judgement.get('favourite_points'),
                'testimonies': fav_list,
            },
            'lord7': {
                'planet': judgement.get('lord7'),
                'success_lord': judgement.get('lord4'),
                'total_strength': judgement.get('underdog_points'),
                'testimonies': ud_list,
            },
        },
        # match_type — из карточного вердикта (_card_verdict), НЕ из полного
        # judgement['match_type'] (гл.2+гибрид): иначе это поле могло
        # противоречить тексту verdict/card_text, посчитанному по другому
        # набору тестимоний. full_chart_match_type — старое значение, для
        # отладки/сравнения, не для отображения пользователю.
        'match_type': _card_match_type(card),
        'full_chart_match_type': judgement.get('match_type'),
        'moon_report': judgement.get('moon_report'),
        'engine_notes': judgement.get('engine_notes'),
    }
