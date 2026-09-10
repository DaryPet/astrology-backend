# app/services/daily_forecast_service.py
# Match-day forecast: a HYBRID method based on the EVENT CHART, following
# John Frawley's book "Sports Astrology" (2007), chapter 2 "The Chart for the
# Event" — priority RAG book id=30.
# Specs: app/services/specs/daily_forecast_event_chart_plan.md,
# plans/daily-forecast-hybrid-method.md (hybrid layer, see below).
#
# Base — the ch. 2 event-chart method (NOT the ch. 1 horary method). Frawley:
# "IT'S NOT THE SAME AS HORARY. DON'T MIX THE METHODS" and "FORGET ESSENTIAL
# DIGNITY. FORGET ACCIDENTAL DIGNITY. FORGET RECEPTIONS" — per the book these
# concepts do not work in an event chart.
#
# HYBRID LAYER (a deliberate departure from the book's explicit ban, see
# plans/daily-forecast-hybrid-method.md): after a month of empirical tests on
# real matches, for Lord 1 and Lord 7 (ONLY the main significators, not
# 10/4) we additionally score essential dignity, the angularity of their
# OWN house and retrogradation — a classical horary (ch. 1-style)
# assessment. Testimonies of this layer are tagged source='mixed'/[HYBRID], are
# not searched in the book via RAG (the book is explicitly against them) and are
# summed into the same base_score on a par with the ch. 2 testimonies. See
# `_mixed_method_testimonies`, `_build_significator_card`.
#
# Chart: time+place of the match START (Placidus). Favourite = 1st house (+10th,
# the house of its success), opponent = 7th (+4th = 10th from the 7th). Ch. 2 testimonies:
#   A. Placements of Lords 1/4/7/10 and their antiscia within 2-3° of cusps 1/4/7/10:
#      ON the cusp = controls the house, JUST INSIDE = imprisoned by the house.
#   B. Moon = "the flow of events": its FINAL applying aspect within its
#      (sport-dependent) range to Lord 1/10 -> favourite, to Lord 7/4 -> opponent.
#      An aspect to Fortune/its antiscion is always final. The sign boundary is the limit.
#   C. Fortune (ALWAYS ASC+Moon-Sun, no night reversal): its antiscion near
#      cusps 1/7 is the strongest single testimony; aspects of Lords 1/7
#      to it; its dispositor; its conjunction with the nodes.
#   D. Nodes: a significator conj the North Node (<=2°) is strengthened, conj the South Node weakened.
#   E. Combustion: a significator within 2° of the Sun is harmed. Cazimi does not exist.
#   F. Outer planets: Pluto on a relevant cusp (against the favourite),
#      Uranus to MC/Fortune (for the favourite), Saturn as malefic. Neptune is ignored.
#   G. HYBRID: essential dignity + angularity + retrogradation
#      of Lord 1/7 (see above).
#
# Reuses: calculate_transits (astrology_v2) -> transit_houses (Placidus cusps
# at the match moment) + transit_planets (including NorthNode/SouthNode,
# Uranus/Neptune/Pluto, each planet's transit_house); RAG
# search_chunks_priority_book; get_llm_adapter.
# The natal chart is only a context note and does not take part in scoring.
import asyncio
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from app.services.analysis_service import search_chunks_priority_book
from app.utils.horary_tables import (
    classical_ruler, antiscion, TRADITIONAL_PLANETS,
    essential_dignity,
)
from app.utils.astrology_v2 import ZODIAC_SIGNS, ZODIAC_SIGNS_RU

# Priority book for the DAILY FORECAST — sport_astrology (id=30).
# Regular transits (/analysis/transits) use their own book (28) — leave it alone.
DAILY_FORECAST_PRIORITY_BOOK_ID = 30

ASPECT_ANGLES = {
    'conjunction': 0, 'sextile': 60, 'square': 90, 'trine': 120, 'opposition': 180,
}
HARMONIOUS_ASPECTS = {'conjunction', 'trine', 'sextile'}  # for all acpects

# Orbs by books (ch. 2): «Small measures of movement and certain narrowly
# prescribed house-placements are all that concern us».
CUSP_ORB = 3.0          # «sitting on the cusp, at most a couple of degrees before it;
                        #  tucked just inside, at most a couple of degrees inside» (2-3°)
FORTUNA_ASPECT_ORB = 5.0  # «keep to a limit of around 5 degrees»
NODE_ORB = 2.0          # «conjunctions only, within a couple of degrees at most»
COMBUST_ORB = 2.0       # «any significator within 2 degrees of the Sun is harmed»
OUTER_ORB = 1.5         # outer planets: «a degree or so away at most»
SATURN_ORB = 2.0        # Saturn as malefic: close contact
MOON_RANGE_DEFAULT = 5.0  # football 80+ minutes; +1° if extra time is possible

RELEVANT_HOUSES = (1, 10, 7, 4)
FAVOURITE_HOUSES = {1, 10}
UNDERDOG_HOUSES = {7, 4}

# Testimony weights (tiers from the spec). Sign: + for the favourite, - for the opponent.
W_MAIN_LORD_PLACEMENT = 2.5   # Lord 1/7 on/in the cusp — «will usually outweigh anything else»
W_SUCCESS_LORD_PLACEMENT = 1.5  # Lords 10/4 near cusps
W_OWN_HOUSE_BONUS = 1.0       # own house: strengthening, but «weaker than dominating the enemy»
W_FORTUNA_ANTISCION_PLACEMENT = 2.5  # «perhaps the most powerful of all»
W_MOON_FINAL_ASPECT = 2.0     # «Moon's final aspect wins»
W_MOON_PLACEMENT = 2.0        # Moon near cusp 1/10/7/4
W_MOON_EARLY_ASPECT = 0.3     # early (non-final) aspect = «early advantage»
W_FORTUNA_ASPECT = 1.5        # conj/opp of Lords 1/7 to Fortune/its antiscion
W_FORTUNA_DISPOSITOR = 1.2
W_NODE = 1.2
W_COMBUSTION = 1.0
W_PLUTO = 1.5
W_URANUS = 1.0
W_SATURN_MALEFIC = 0.7
ANTISCION_FACTOR = 0.7        # antiscia «not quite so compelling as bodily placements»
RETRO_ON_CUSP_FACTOR = 0.6    # retrograde ON the cusp: positive, but weaker than direct

# HYBRID LAYER (NOT from the book — the user's deliberate empirical choice, see
# plans/daily-forecast-hybrid-method.md). The book's ch. 2 explicitly demands
# "FORGET ESSENTIAL DIGNITY. FORGET ACCIDENTAL DIGNITY... DON'T MIX THE
# METHODS", but after a month of real tests a classical (ch. 1-style)
# assessment of Lord 1/7 by dignity/angularity/retrogradation improves forecast
# accuracy. Applied ONLY to Lord 1 and Lord 7 (not to Lord 10/4). The weights are
# not from the book — an empirical choice of the classical horary scale.
W_MIXED_DIGNITY = {
    'domicile': 1.0, 'exaltation': 1.75, 'detriment': -1.75, 'fall': -2.25,
    'peregrine': 0.0,
}
# A simple 3-level house strength scale (angular/succedent/cadent), NOT Lilly's
# full point table: angular = bonus, succedent = neutral ("no
# bonus"), cadent = weak minus. The 8th house is separate — "the house of death",
# singled out from succedent and treated as a strong minus even though it is
# formally succedent. Confirmed by the user on real examples
# (11th succedent = neutral, 9th cadent = weak minus, 8th = strong
# minus), see plans/daily-forecast-hybrid-method.md.
ANGULAR_HOUSES = {1, 4, 7, 10}
CADENT_HOUSES = {3, 6, 9, 12}
EIGHTH_HOUSE = 8
HOUSE_STRENGTH = {h: 1.75 for h in ANGULAR_HOUSES}
HOUSE_STRENGTH.update({h: -1.0 for h in CADENT_HOUSES})
HOUSE_STRENGTH[EIGHTH_HOUSE] = -2.25
HOUSE_STRENGTH.update({h: 0.0 for h in (2, 5, 11)})  # succedent (except the 8th) — neutral
# «Enemy's house» — a caveat to the angular bonus, without which it is wrong: «being in
# an angle is like being in a castle. Unless it is your enemy's castle, in
# which case you're in prison... Lord 1 in the 1st, 4th or 10th is very
# strong, but in the 7th it is very weak» (Frawley, Sports Astrology, ch. 1 —
# the same source the whole hybrid layer comes from). A flat HOUSE_STRENGTH
# gave Lord 1 in the 7th +1.75 instead of a minus and flipped the verdict.
ENEMY_HOUSE = {1: 7, 7: 1}
HOUSE_STRENGTH_ENEMY = -1.75
HOUSE_NICKNAME = {
    'ru': {6: 'болезни, слуги', 8: 'смерть', 12: 'тайные враги, заточение'},
    'en': {6: 'illness, servants', 8: 'death', 12: 'secret enemies, imprisonment'},
}
W_MIXED_RETROGRADE = -1.0

DIGNITY_LABEL = {
    'ru': {
        'domicile': 'Обитель', 'exaltation': 'Экзальтация', 'detriment': 'Изгнание',
        'fall': 'Падение', 'peregrine': 'Перегрин (нейтрально)',
    },
    'en': {
        'domicile': 'Domicile', 'exaltation': 'Exaltation', 'detriment': 'Detriment',
        'fall': 'Fall', 'peregrine': 'Peregrine (neutral)',
    },
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

ROLE_LABEL = {
    'ru': {'favourite': 'Фаворит', 'underdog': 'Аутсайдер'},
    'en': {'favourite': 'Favourite', 'underdog': 'Underdog'},
}


def _side_name(side_key: str, language: str) -> str:
    return ROLE_LABEL.get(language, ROLE_LABEL['en'])[side_key]


# Case form (accusative/genitive — "for/against X"), needed ONLY in
# Russian ("Strongly for the Favourite", "Against the Underdog" take a declined form);
# English has no cases, "for/against the Favourite" uses the same form as the nominative.
_SIDE_OBJECT_FORM_RU = {'favourite': 'Фаворита', 'underdog': 'Аутсайдера'}


def _side_object(side_key: str, language: str) -> str:
    if language == 'ru':
        return _SIDE_OBJECT_FORM_RU[side_key]
    return _side_name(side_key, language)


def _sign_label(sign: str, language: str) -> str:
    """Internal sign values are already English — no translation needed for EN."""
    return SIGN_RU.get(sign, sign) if language == 'ru' else sign


def _planet_label(planet: str, language: str) -> str:
    """Internal planet values are already English — no translation needed for EN."""
    return PLANET_RU.get(planet, planet) if language == 'ru' else planet


def _dignity_label(dignity: str, language: str) -> str:
    return DIGNITY_LABEL.get(language, DIGNITY_LABEL['en']).get(dignity, dignity)


def _house_nickname(house_num: Optional[int], language: str) -> Optional[str]:
    return HOUSE_NICKNAME.get(language, HOUSE_NICKNAME['en']).get(house_num)


# ---------- utilities ----------

def _lon(value: Any) -> Optional[float]:
    """Longitude from a value: a float or a dict with full_degree/longitude/degree/cusp_longitude."""
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
    """Offset of a point relative to a cusp along the zodiac, in (-180, 180].
    Negative = the point is BEFORE the cusp (applying to it),
    positive = the point is PAST the cusp (inside the house)."""
    d = (point - cusp) % 360
    return d - 360 if d > 180 else d


def _sign_of(longitude: float) -> int:
    return int(longitude // 30) % 12


def _closeness(orb: float, max_orb: float) -> float:
    """«The closer the stronger»: 1.0 right up close -> 0.5 at the orb edge."""
    if max_orb <= 0:
        return 1.0
    return max(0.5, 1.0 - (orb / max_orb) * 0.5)


# ---------- event chart engine ----------

class EventChart:
    """Parsing the chart of the match moment: significators, cusps, Fortune."""

    def __init__(self, transit_houses: Dict[Any, Any], transit_planets: Dict[str, Any],
                 moon_range: float = MOON_RANGE_DEFAULT, language: str = 'ru'):
        self.houses = transit_houses
        self.planets = transit_planets
        self.moon_range = moon_range
        self.language = language
        self.notes: List[str] = []  # human-readable notes for the judgement sheet

        self.cusps: Dict[int, Optional[float]] = {
            n: _lon((self._house(n) or {}).get('cusp_longitude')) for n in range(1, 13)
        }
        self.asc = self.cusps.get(1)
        self.mc = self.cusps.get(10)

        # --- significators: Lords 1/10 = favourite, Lords 7/4 = opponent ---
        raw = {n: classical_ruler((self._house(n) or {}).get('sign')) for n in RELEVANT_HOUSES}
        self.lords: Dict[int, Optional[str]] = dict(raw)

        # Moon = «the flow of events». If it rules the 1st/7th, the house is represented by its
        # DISPOSITOR; if the 10th/4th, we do without that lord (the book, ch. 2).
        self.moon_substituted_for: Optional[int] = None
        for h in (1, 7):
            if self.lords.get(h) == 'Moon':
                moon = self.planets.get('Moon') or {}
                dispositor = classical_ruler(moon.get('sign'))
                self.lords[h] = dispositor
                self.moon_substituted_for = h
                if self.language == 'ru':
                    self.notes.append(
                        f"Луна правит {h}-м домом: дом представляет её диспозитор {dispositor}, "
                        f"Луна остаётся «потоком событий»")
                else:
                    self.notes.append(
                        f"Moon rules house {h}: the house is represented by its dispositor "
                        f"{dispositor}, Moon remains the 'flow of events'")
        for h in (10, 4):
            if self.lords.get(h) == 'Moon':
                self.lords[h] = None
                if self.language == 'ru':
                    self.notes.append(f"Луна правит {h}-м домом успеха: обходимся без Lord {h}")
                else:
                    self.notes.append(f"Moon rules the success house {h}: proceeding without Lord {h}")

        # Role conflict: one planet rules houses of both sides, or the success house
        # duplicates the main house -> priority to Lords 1/7, without Lords 10/4
        # (book example: Juventus-Dortmund, Lord10=Lord7 and Lord4=Lord1).
        main = {self.lords.get(1), self.lords.get(7)} - {None}
        for h in (10, 4):
            if self.lords.get(h) in main:
                if self.language == 'ru':
                    self.notes.append(
                        f"Lord {h} ({self.lords[h]}) совпадает с главным значителем — "
                        f"приоритет Lords 1/7, без Lord {h}")
                else:
                    self.notes.append(
                        f"Lord {h} ({self.lords[h]}) coincides with a main significator — "
                        f"Lords 1/7 take priority, proceeding without Lord {h}")
                self.lords[h] = None
        if self.lords.get(1) and self.lords.get(1) == self.lords.get(7):
            # One ruler of both main houses (Cancer/Capricorn ASC after substitution, etc.)
            if self.language == 'ru':
                self.notes.append("Lord 1 и Lord 7 — одна планета: суждение ненадёжно")
            else:
                self.notes.append("Lord 1 and Lord 7 are the same planet: judgement unreliable")

        # --- Fortune: ALWAYS the day formula, «Do I reverse in night charts? NEVER!» ---
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
        """+1 = the favourite's significator, -1 = the opponent's."""
        return 1 if house in FAVOURITE_HOUSES else -1

    def planet_lon(self, name: Optional[str]) -> Optional[float]:
        p = self.planets.get(name) if name else None
        return _lon(p) if p else None


def _cusp_relation(point_lon: float, cusp_lon: float, cusp_sign: int) -> Optional[Tuple[str, float]]:
    """Relation of a point to a cusp per the book:
    ('on', orb) — up to CUSP_ORB° BEFORE the cusp, in the cusp's sign: controls the house;
    ('inside', orb) — up to CUSP_ORB° PAST the cusp, in the cusp's sign: imprisoned by the house.
    A different sign = isolation by the sign boundary («sign boundaries act like insulators»)."""
    off = _signed_offset(point_lon, cusp_lon)
    if -CUSP_ORB <= off < 0 and _sign_of(point_lon) == cusp_sign:
        return 'on', abs(off)
    if 0 <= off <= CUSP_ORB and _sign_of(point_lon) == cusp_sign:
        return 'inside', off
    return None


def _lord_profile(chart: 'EventChart', lord_house: int) -> Optional[Dict[str, Any]]:
    """Significator profile (Lord 1 or Lord 7) for the hybrid layer: own
    house, sign, essential dignity, house strength (angular/succedent/
    cadent+8th, see HOUSE_STRENGTH), retrogradation."""
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
        'house_strength': _house_weight(house_num, lord_house),
        'house_nickname': _house_nickname(house_num, chart.language),
        'dignity': essential_dignity(lord, sign),
        'retrograde': bool(data.get('is_retrograde')),
        'combust': combust_orb is not None and combust_orb <= COMBUST_ORB,
        'combust_orb': combust_orb if (combust_orb is not None and combust_orb <= COMBUST_ORB) else None,
    }


def _house_label(house_num: Optional[int], language: str) -> str:
    """Short house label for the raw testimony log (not for the card —
    the card uses _house_phrase)."""
    if not house_num:
        return ""
    nickname = _house_nickname(house_num, language)
    if language == 'ru':
        return f"дом {house_num}" + (f" («{nickname}»)" if nickname else "")
    return f"house {house_num}" + (f" ('{nickname}')" if nickname else "")


def _house_weight(house_num: Optional[int], lord_house: Optional[int]) -> float:
    """House weight for a significator, with the enemy-house caveat (ENEMY_HOUSE).
    lord_house=1|7 — whose significator this is; None — compute without the caveat (the
    «Planets» block for non-significators, where «own/enemy» does not apply)."""
    if not house_num:
        return 0.0
    if lord_house is not None and house_num == ENEMY_HOUSE.get(lord_house):
        return HOUSE_STRENGTH_ENEMY
    return HOUSE_STRENGTH.get(house_num, 0.0)


def _house_phrase(house_num: Optional[int], lord_house: int, planet_label: str,
                   own_side: str, language: str) -> Tuple[str, str]:
    """(description, effect) for a significator's «house strength» showing. Wording
    follows the user's examples: succedent (except the 8th) — neutral, «no
    bonus»; cadent — weak minus; 8th — «death», a minus without the
    «strongly» intensifier; angular — «strongly for», marked «its own!» if the house
    matches the significator's number (Lord1 in the 1st / Lord7 in the 7th)."""
    if language == 'ru':
        if not house_num:
            return (f"{planet_label}: дом неизвестен", "Нейтрально")
        if house_num == EIGHTH_HOUSE:
            return (f"{planet_label}: Дом 8 («смерть»)", f"Против {own_side}")
        if house_num in CADENT_HOUSES:
            return (f"{planet_label}: обычный кадентный (не «смерть»)", f"Слабо против {own_side}")
        if house_num == ENEMY_HOUSE.get(lord_house):
            return (f"{planet_label}: {house_num}-й дом — дом врага",
                    f"Сильно против {own_side}")
        if house_num in ANGULAR_HOUSES:
            own_house_suffix = " — свой же!" if house_num == lord_house else ""
            return (f"{planet_label}: угловой {house_num}-й дом{own_house_suffix}",
                    f"Сильно за {own_side}")
        return (f"{planet_label}: succedent, без бонуса", "Нейтрально")
    if not house_num:
        return (f"{planet_label}: house unknown", "Neutral")
    if house_num == EIGHTH_HOUSE:
        return (f"{planet_label}: House 8 ('death')", f"Against the {own_side}")
    if house_num in CADENT_HOUSES:
        return (f"{planet_label}: ordinary cadent (not 'death')", f"Slightly against the {own_side}")
    if house_num == ENEMY_HOUSE.get(lord_house):
        return (f"{planet_label}: house {house_num} — the enemy's house",
                f"Strongly against the {own_side}")
    if house_num in ANGULAR_HOUSES:
        own_house_suffix = " — its own!" if house_num == lord_house else ""
        return (f"{planet_label}: angular house {house_num}{own_house_suffix}",
                f"Strongly for the {own_side}")
    return (f"{planet_label}: succedent, no bonus", "Neutral")


def _dignity_phrase(dignity: str, planet_label: str, own_side: str, language: str) -> Tuple[str, str]:
    """(description, effect) for a significator's «dignity» showing."""
    if language == 'ru':
        if dignity == 'fall':
            return (f"{planet_label} в Падении", f"Против {own_side}")
        if dignity == 'detriment':
            return (f"{planet_label} в Изгнании", f"Против {own_side}")
        if dignity == 'domicile':
            return (f"{planet_label} в собственной обители", f"За {own_side}")
        if dignity == 'exaltation':
            return (f"{planet_label} в Экзальтации", f"За {own_side}")
        return (f"{planet_label}: перегрин", "Нейтрально")
    if dignity == 'fall':
        return (f"{planet_label} in Fall", f"Against the {own_side}")
    if dignity == 'detriment':
        return (f"{planet_label} in Detriment", f"Against the {own_side}")
    if dignity == 'domicile':
        return (f"{planet_label} in its own domicile", f"For the {own_side}")
    if dignity == 'exaltation':
        return (f"{planet_label} in Exaltation", f"For the {own_side}")
    return (f"{planet_label}: peregrine", "Neutral")


def _mixed_method_testimonies(chart: 'EventChart', add) -> Dict[int, Dict[str, Any]]:
    """Hybrid layer (NOT from the book's ch. 2 — the user's deliberate empirical choice,
    see plans/daily-forecast-hybrid-method.md). A classical horary
    (ch. 1-style) assessment of Lord 1/7: essential dignity, strength of their
    OWN house (angular/succedent/cadent+8th — HOUSE_STRENGTH),
    retrogradation. The book explicitly forbids this for an event chart («FORGET
    ESSENTIAL DIGNITY... DON'T MIX THE METHODS»), but over a month of empirical
    tests the hybrid gives more accurate forecasts. Testimonies are tagged source='mixed' and
    are deliberately NOT searched in the book (RAG) — see daily_forecast_analysis, where
    the book-only filter drops them before the search."""
    profiles: Dict[int, Dict[str, Any]] = {}
    language = chart.language
    for lord_house in (1, 7):
        profile = _lord_profile(chart, lord_house)
        if not profile:
            continue
        side = chart.lord_side(lord_house)
        side_key = 'favourite' if side > 0 else 'underdog'
        own_side = _side_object(side_key, language)
        planet_label = _planet_label(profile['planet'], language)
        label = f"{profile['planet']} [L{lord_house}]"
        showings: List[Dict[str, Any]] = []

        # Order of showings in the card: house BEFORE dignity (as in all
        # of the user's reference examples — «succedent, no bonus» comes
        # as the first line, «in Fall/in Domicile» as the second).
        house_num = profile['house']
        w = _house_weight(house_num, lord_house)
        if w:
            add(label, 'house_strength', _house_label(house_num, language),
                side * w, is_point=False, source='mixed')
        desc, effect = _house_phrase(house_num, lord_house, planet_label, own_side, language)
        showings.append({
            'kind': 'house_strength', 'label_ru': desc,
            'warn': HOUSE_WARN.get(house_num, ''), 'star': HOUSE_STAR.get(house_num, ''),
            'effect': effect,  # always shown, even «Neutral» for succedent (w=0)
            'weight': round(w, 2),
        })

        dign = profile['dignity']
        w = W_MIXED_DIGNITY.get(dign, 0.0)
        if w:
            add(label, 'essential_dignity', dign, side * w, is_point=False, source='mixed')
        desc, effect = _dignity_phrase(dign, planet_label, own_side, language)
        showings.append({
            'kind': 'dignity', 'label_ru': desc,
            'warn': DIGNITY_WARN.get(dign, ''), 'star': DIGNITY_STAR.get(dign, ''),
            'effect': effect if w else None,
            'weight': round(w, 2),
        })

        # Combustion: ALREADY added to testimonies separately, the book way
        # (section E of judge_event_chart, source='book') — we do NOT call
        # add() again here (otherwise the weight would be doubled in base_score), we only build
        # the showing for the card with the same weight as there.
        combust_w = 0.0
        if profile.get('combust'):
            combust_w = -W_COMBUSTION * _closeness(profile['combust_orb'], COMBUST_ORB)
        combust_orb_val = profile.get('combust_orb') or 0
        if language == 'ru':
            combust_label = f"{planet_label}: сгорание ({combust_orb_val:.2f}°!)"
            combust_effect = f"Сильно против {own_side}" if profile.get('combust') else None
        else:
            combust_label = f"{planet_label}: combustion ({combust_orb_val:.2f}°!)"
            combust_effect = f"Strongly against the {own_side}" if profile.get('combust') else None
        showings.append({
            'kind': 'combustion', 'label_ru': combust_label,
            'warn': '⚠️' if profile.get('combust') else '', 'star': '',
            'effect': combust_effect,
            'weight': round(combust_w, 2),
        })

        retro_w = W_MIXED_RETROGRADE if profile['retrograde'] else 0.0
        if profile['retrograde']:
            add(label, 'retrograde', 'Rx', side * retro_w, is_point=False, source='mixed')
        if language == 'ru':
            own_side_dative = 'Фавориту' if side > 0 else 'Аутсайдеру'  # a «minus» requires the dative case (Russian)
            retro_label = f"{planet_label}: ретрограден"
            retro_effect = f"Ещё минус {own_side_dative}" if profile['retrograde'] else None
        else:
            retro_label = f"{planet_label}: retrograde"
            retro_effect = f"Extra minus for the {own_side}" if profile['retrograde'] else None
        showings.append({
            'kind': 'retrograde', 'label_ru': retro_label,
            'warn': '⚠️' if profile['retrograde'] else '', 'star': '',
            'effect': retro_effect,
            'weight': round(retro_w, 2),
            'value': profile['retrograde'],
        })

        profile['showings'] = showings
        profile['own_side'] = own_side
        profiles[lord_house] = profile
    return profiles


def _describe_testimony(t: Dict[str, Any], language: str) -> str:
    """Readable description of a book (ch. 2) testimony for the card showings."""
    aspect, natal = t['aspect'], t['natal']
    if language != 'ru':
        if aspect == 'on_cusp':
            return f"on the cusp of {natal} — controls the house"
        if aspect == 'inside_enemy_house':
            return f"inside {natal} — held prisoner"
        if aspect == 'inside_own_house':
            return f"in its own {natal} — strengthened"
        if aspect == 'moon_final_aspect':
            return f"final aspect: {natal}"
        if aspect == 'moon_early_aspect':
            return f"early aspect to {natal}"
        if aspect == 'moon_on_cusp':
            return f"Moon on the cusp of {natal} — flow of events toward this side"
        if aspect == 'moon_inside_cusp':
            return f"Moon inside {natal} — flow of events toward this side"
        if aspect == 'fortuna_antiscion_cusp':
            return f"antiscion of Fortuna at {natal}"
        if aspect == 'fortuna_aspect':
            return f"{natal} (Fortuna)"
        if aspect in ('fortuna_dispositor', 'fortuna_dispositor_inside'):
            return f"dispositor of Fortuna: {natal}"
        if aspect == 'node_conjunction':
            return f"on {natal}"
        if aspect == 'combustion':
            return f"combustion (orb {t['orb']}°)"
        if aspect in ('pluto_on_cusp', 'pluto_fortuna'):
            return f"Pluto: {natal}"
        if aspect in ('uranus_to_mc', 'uranus_fortuna'):
            return "Uranus applying"
        if aspect == 'saturn_afflicts':
            return "afflicted by Saturn"
        return f"{aspect} → {natal}"
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
    if aspect == 'moon_on_cusp':
        return f"Луна на куспиде {house_natal} — поток событий к этой стороне"
    if aspect == 'moon_inside_cusp':
        return f"Луна внутри {house_natal} — поток событий к этой стороне"
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


def _mixed_effect_label(weight: float, own_side: str, language: str) -> str:
    """Generic (not bespoke) effect wording — for book (ch. 2)
    significator showings (on_cusp/moon_final_aspect/nodes/outer planets and
    the like), which have no dedicated phrase template, unlike
    dignity/house_strength (see _dignity_phrase/_house_phrase)."""
    if language == 'ru':
        if weight >= 1.5:
            return f"Сильно за {own_side}"
        if weight > 0:
            return f"За {own_side}"
        if weight <= -1.5:
            return f"Сильно против {own_side}"
        if weight < 0:
            return f"Против {own_side}"
        return "Нейтрально"
    if weight >= 1.5:
        return f"Strongly for the {own_side}"
    if weight > 0:
        return f"For the {own_side}"
    if weight <= -1.5:
        return f"Strongly against the {own_side}"
    if weight < 0:
        return f"Against the {own_side}"
    return "Neutral"


def _merged_showings(profile: Dict[str, Any], testimonies: List[Dict[str, Any]],
                      side: int, own_side: str, language: str) -> List[Dict[str, Any]]:
    """Showings for the card: own ones (dignity/house_strength/retrograde,
    already in profile['showings']) + relevant book (ch. 2) testimonies of the
    same significator (cusps, combustion, nodes, outer planets, etc.)."""
    showings = list(profile.get('showings') or [])
    prefix = f"{profile['planet']} [L{profile['lord_house']}"
    for t in testimonies:
        # 'mixed' (dignity/house_strength/retrograde) is already in profile['showings'].
        # 'combustion' (book, source='book') is already there too: the hybrid layer
        # builds its own combustion showing with the same weight (see
        # _mixed_method_testimonies), so it is not duplicated on merge.
        if t.get('source') == 'mixed' or t['aspect'] == 'combustion' or not t['transit'].startswith(prefix):
            continue
        own_weight = t['weight'] * side  # flip to «for/against its own side»
        showings.append({
            'kind': t['aspect'], 'label_ru': _describe_testimony(t, language),
            'warn': '⚠️' if own_weight < 0 else '', 'star': '⭐' if own_weight > 0 else '',
            'effect': _mixed_effect_label(own_weight, own_side, language),
            'weight': round(own_weight, 2),
        })
    showings.sort(key=lambda s: abs(s['weight']), reverse=True)
    return showings


def _all_planets_report(chart: 'EventChart') -> List[Dict[str, Any]]:
    """Positions of all 7 traditional planets — the card's «Planets» block.
    Informational (does not affect the score outside Lord 1/7)."""
    sun_lon = chart.planet_lon('Sun')
    # The enemy-house caveat applies only to Lord 1/7 — for other planets
    # «own/enemy house» is undefined, they are scored by the flat HOUSE_STRENGTH.
    lord_house_of = {p: h for h, p in chart.lords.items() if h in (1, 7) and p}
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
        house_strength = _house_weight(house_num, lord_house_of.get(planet))
        retro = bool(data.get('is_retrograde'))
        combust_orb = _angle_diff(lon, sun_lon) if (planet != 'Sun' and sun_lon is not None) else None
        combust = combust_orb is not None and combust_orb <= COMBUST_ORB
        warnings = sum([retro, combust, dignity in ('fall', 'detriment'), house_strength < 0])
        report.append({
            'planet': planet, 'planet_ru': _planet_label(planet, chart.language),
            'symbol': PLANET_SYMBOLS.get(planet, ''),
            'sign': sign, 'sign_ru': _sign_label(sign, chart.language),
            'sign_symbol': SIGN_SYMBOLS.get(sign, ''),
            'degree': round(lon % 30, 2),
            'house': house_num, 'house_nickname': _house_nickname(house_num, chart.language),
            'retrograde': retro,
            'combust': combust, 'combust_orb': round(combust_orb, 2) if combust else None,
            'dignity': dignity, 'dignity_ru': _dignity_label(dignity, chart.language),
            'warnings': warnings,
        })
    return report


def _build_significator_card(chart: 'EventChart', mixed_profiles: Dict[int, Dict[str, Any]],
                              testimonies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Deterministic card (no LLM): Significators + Planets +
    Showings, format following the user's example."""
    if chart.asc is None or chart.cusps.get(7) is None:
        return None

    def _point(lon: float) -> Dict[str, Any]:
        sign = chart._sign_name(lon)
        return {
            'sign': sign, 'sign_ru': _sign_label(sign, chart.language),
            'symbol': SIGN_SYMBOLS.get(sign, ''), 'degree': round(lon % 30, 2),
        }

    def _side_card(lord_house: int) -> Optional[Dict[str, Any]]:
        profile = mixed_profiles.get(lord_house)
        if not profile:
            return None
        planet = profile['planet']
        side = chart.lord_side(lord_house)
        own_side = profile.get('own_side') or _side_object('favourite' if side > 0 else 'underdog', chart.language)
        house_num = profile['house']
        dignity = profile['dignity']
        return {
            'lord_house': lord_house,
            'planet': planet, 'planet_ru': _planet_label(planet, chart.language),
            'symbol': PLANET_SYMBOLS.get(planet, ''),
            'sign': profile['sign'], 'sign_ru': _sign_label(profile['sign'], chart.language),
            'sign_symbol': SIGN_SYMBOLS.get(profile['sign'], ''),
            'degree': profile['degree_in_sign'],
            'house': house_num, 'house_nickname': profile.get('house_nickname'),
            'house_strength': profile['house_strength'],
            # house_mark: a single ⭐/⚠️ next to «House N» in the «Planets» block (angular/cadent+8th).
            'house_mark': ('⚠️' if house_num == ENEMY_HOUSE.get(lord_house)
                           else HOUSE_STAR.get(house_num, '') or HOUSE_WARN.get(house_num, '')),
            'dignity': dignity,
            'dignity_ru': _dignity_label(dignity, chart.language),
            # dignity_mark: ⭐⭐/⭐/⚠️/⚠️⚠️ next to the dignity name (empty for peregrine).
            'dignity_mark': DIGNITY_STAR.get(dignity, '') or DIGNITY_WARN.get(dignity, ''),
            'retrograde': profile['retrograde'],
            'combust': profile.get('combust', False),
            'showings': _merged_showings(profile, testimonies, side, own_side, chart.language),
        }

    favourite = _side_card(1)
    underdog = _side_card(7)

    card = {
        'asc': _point(chart.asc),
        'desc': _point(chart.cusps[7]),
        'favourite': favourite,
        'underdog': underdog,
        'planets': _all_planets_report(chart),
        # Ch. 2 showings NOT tied to a specific Lord1/Lord7 (the Moon's final
        # aspect as «the flow of events», Fortune's antiscion near a cusp, its
        # dispositor/nodes, outer planets on Fortune/cusps) — already
        # counted in testimonies/base_score, here we only make them visible.
        'chart_wide': _chart_wide_showings(favourite, underdog, testimonies, chart.language),
    }

    # The winner comes ONLY from _card_verdict, the single counter for the whole card.
    # Previously there was a separate count here (sum of side['showings'] with a threshold
    # of 0.3), which ignored chart_wide (Moon/Fortune/Pluto/nodes) and did not know
    # the confidence threshold CARD_DECISIVE_THRESHOLD. Because of that one card
    # could say both «🏆 Favourite wins» (per mixed_winner) and
    # «Draw likely» (per _card_verdict) — see the Ljubljana chart.
    decisive, winner, diff = _card_verdict(card)
    card['mixed_winner'] = winner or 'draw'
    card['decisive'] = decisive
    card['diff'] = round(diff, 2)
    return card


def _global_effect_label(weight: float, language: str) -> str:
    fav = _side_object('favourite', language)
    ud = _side_object('underdog', language)
    if language == 'ru':
        if weight >= 1.5:
            return f"Сильно за {fav}"
        if weight > 0:
            return f"За {fav}"
        if weight <= -1.5:
            return f"Сильно за {ud}"
        if weight < 0:
            return f"За {ud}"
        return "Нейтрально"
    if weight >= 1.5:
        return f"Strongly for the {fav}"
    if weight > 0:
        return f"For the {fav}"
    if weight <= -1.5:
        return f"Strongly for the {ud}"
    if weight < 0:
        return f"For the {ud}"
    return "Neutral"


def _chart_wide_showings(favourite: Optional[Dict[str, Any]], underdog: Optional[Dict[str, Any]],
                          testimonies: List[Dict[str, Any]], language: str) -> List[Dict[str, Any]]:
    """Book (ch. 2) chart showings NOT tied to Lord1/Lord7 directly
    (their 'transit' does not start with either significator's label) — Moon,
    Fortune, nodes on Fortune, outer planets, etc. The weight sign is global:
    + for the Favourite, − for the Underdog (the same convention as in the whole sheet)."""
    prefixes = []
    if favourite:
        prefixes.append(f"{favourite['planet']} [L{favourite['lord_house']}")
    if underdog:
        prefixes.append(f"{underdog['planet']} [L{underdog['lord_house']}")
    out: List[Dict[str, Any]] = []
    for t in testimonies:
        if t.get('source') == 'mixed':
            continue
        if any(t['transit'].startswith(p) for p in prefixes):
            continue
        out.append({
            'label_ru': f"{t['transit']}: {_describe_testimony(t, language)}",
            'effect': _global_effect_label(t['weight'], language),
            'weight': t['weight'],
        })
    out.sort(key=lambda s: abs(s['weight']), reverse=True)
    return out


def judge_event_chart(
    transit_houses: Dict[Any, Any],
    transit_planets: Dict[str, Any],
    moon_range_degrees: float = MOON_RANGE_DEFAULT,
    extra_time_possible: bool = False,
    language: str = 'ru',
) -> Dict[str, Any]:
    """Event chart judgement per the ch. 2 checklist. Returns base_score (1-10),
    testimonies (frontend key_aspects format: transit/aspect/natal/orb/weight/is_point,
    weight>0 = for the favourite, <0 = for the opponent) and the judgement sheet."""
    chart = EventChart(transit_houses, transit_planets,
                       moon_range=moon_range_degrees + (1.0 if extra_time_possible else 0.0),
                       language=language)

    testimonies: List[Dict[str, Any]] = []

    def add(transit: str, aspect: str, natal: str, weight: float, orb: float = 0.0,
            is_point: bool = True, source: str = 'book'):
        if abs(weight) < 0.01:
            return
        testimonies.append({
            'transit': transit, 'aspect': aspect, 'natal': natal,
            'orb': round(orb, 2), 'weight': round(weight, 2), 'is_point': is_point,
            'source': source,  # 'book' = Frawley ch. 2; 'mixed' = hybrid layer (see the section below)
        })

    # ===== A. Placements of significators (and their antiscia) near cusps 1/10/7/4 =====
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
                    # House control -> always FOR the lord's side; over the enemy's house —
                    # «a foot on the enemy's throat», in its own — just strengthening (weaker).
                    w = base_w if not own_house else min(base_w, W_OWN_HOUSE_BONUS + 0.5)
                    if is_retro and not antisc:
                        w *= RETRO_ON_CUSP_FACTOR  # «still positive, but less strong»
                    add(f"{lord} [{label}]", 'on_cusp', f"house {target_house}",
                        side * w * factor, orb)
                else:  # inside
                    if own_house:
                        # In its own house just past the cusp = strengthened (weak testimony).
                        add(f"{lord} [{label}]", 'inside_own_house', f"house {target_house}",
                            side * W_OWN_HOUSE_BONUS * factor, orb)
                    else:
                        # Imprisoned in the enemy's house: «like a man in prison» — retrogradation
                        # does not save it («bang as much as he wants, he is still in prison»).
                        add(f"{lord} [{label}]", 'inside_enemy_house', f"house {target_house}",
                            -side * base_w * factor, orb)

    # ===== B. Moon — «the flow of events» =====
    moon = transit_planets.get('Moon')
    moon_report: Dict[str, Any] = {'range': chart.moon_range}
    if moon:
        moon_lon = moon['full_degree']
        # The Moon's range is also limited by the sign boundary: «THE END OF THE SIGN IS THE LIMIT».
        deg_left_in_sign = 30.0 - (moon_lon % 30.0)
        effective_range = min(chart.moon_range, deg_left_in_sign)
        moon_report['effective_range'] = round(effective_range, 2)

        # Moon near cusps 1/10/7/4 (applying to the cusp or just inside) + antiscion.
        for body_lon, antisc in ((moon_lon, False), (antiscion(moon_lon), True)):
            for target_house in RELEVANT_HOUSES:
                cusp = chart.cusps.get(target_house)
                if cusp is None:
                    continue
                rel = _cusp_relation(body_lon, cusp, _sign_of(cusp))
                if not rel:
                    continue
                kind, orb = rel
                side = chart.lord_side(target_house)  # Moon in a house = flow TOWARDS that side
                factor = _closeness(orb, CUSP_ORB) * (ANTISCION_FACTOR if antisc else 1.0)
                add(f"Moon{'(ant)' if antisc else ''}", f"moon_{kind}_cusp",
                    f"house {target_house}", side * W_MOON_PLACEMENT * factor, orb)

        # Moon aspect sequencer: applying aspects within effective_range.
        events = _moon_aspect_events(chart, moon, effective_range)
        moon_report['events'] = [
            {'travel': round(e['travel'], 2), 'aspect': e['aspect'], 'target': e['target'],
             'kind': e['kind']} for e in events
        ]
        final_event = None
        early_events: List[Dict[str, Any]] = []
        for e in events:  # sorted along the Moon's path
            if e['kind'] == 'fortuna':
                final_event = e  # «ASPECTS TO FORTUNA OR ITS ANTISCION ARE FINAL»
                break
            if e['kind'] == 'lord_body' and e['aspect'] == 'conjunction':
                final_event = e  # «BODILY CONJUNCTIONS ARE USUALLY FINAL»
                break
            early_events.append(e)
        if final_event is None and early_events:
            final_event = early_events.pop()  # the last aspect within range

        for e in early_events:
            # Early aspect = early advantage («early advantage, often on the scoreboard»)
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

    # ===== C. Fortune =====
    if chart.fortuna is not None:
        # C1. Placement of Fortune's ANTISCION near cusps («ANTISCION, NOT BODILY PLACEMENT»).
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

        # C2. Aspects of Lords 1/7 to Fortune and its antiscion (perfecting, ~5°).
        for lord_house in (1, 7):
            lord = chart.lords.get(lord_house)
            if not lord or lord == 'Moon':
                continue
            _fortuna_aspect_testimonies(chart, lord, lord_house, add)

        # C3. Fortune's dispositor.
        disp = chart.fortuna_dispositor
        main_roles = {chart.lords.get(1), chart.lords.get(7), 'Moon'}
        if disp and disp not in main_roles:
            # if the dispositor = Lord 10/4 — the dispositor role takes priority (the book)
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
                # Dispositor imprisoned in house 1/7 (Juventus example: Sun as dispositor in the 7th)
                for target_house in (1, 7):
                    cusp = chart.cusps.get(target_house)
                    if cusp is None:
                        continue
                    rel = _cusp_relation(disp_lon, cusp, _sign_of(cusp))
                    if rel and rel[0] == 'inside':
                        side = chart.lord_side(target_house)
                        add(disp, 'fortuna_dispositor_inside', f"house {target_house}",
                            side * 1.0 * _closeness(rel[1], CUSP_ORB), rel[1])

        # C4. Fortune on the nodes: «Fortuna belongs to the favourite».
        for node, verdict in (('NorthNode', 1), ('SouthNode', -1)):
            node_lon = chart.planet_lon(node)
            if node_lon is not None:
                orb = _angle_diff(chart.fortuna, node_lon)
                if orb <= NODE_ORB:
                    add('Fortuna', 'node_conjunction', node,
                        verdict * W_NODE * _closeness(orb, NODE_ORB), orb)

        # C5. Fortune combust: «good news for the underdogs».
        sun = transit_planets.get('Sun')
        if sun and _angle_diff(chart.fortuna, sun['full_degree']) <= COMBUST_ORB:
            add('Fortuna', 'combustion', 'Sun', -W_COMBUSTION,
                _angle_diff(chart.fortuna, sun['full_degree']))

    # ===== D. Nodes: significator conj a node (<=2°) =====
    for lord_house in RELEVANT_HOUSES:
        lord = chart.lords.get(lord_house)
        lord_lon = chart.planet_lon(lord)
        if lord_lon is None or lord == 'Moon':  # Moon on a node — nothing
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

    # ===== E. Combustion 2° (cazimi does NOT exist in event charts) =====
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

    # ===== F. Outer planets =====
    _outer_planet_testimonies(chart, add)

    # ===== G. HYBRID: essential+accidental dignity of Lord 1/7 =====
    # NOT from the book's ch. 2 — the user's deliberate empirical choice (see
    # plans/daily-forecast-hybrid-method.md). Testimonies are tagged
    # source='mixed' and do not take part in the RAG search over the book.
    mixed_profiles = _mixed_method_testimonies(chart, add)
    significator_card = _build_significator_card(chart, mixed_profiles, testimonies)

    # ===== Result =====
    testimonies.sort(key=lambda t: abs(t['weight']), reverse=True)
    fav_total = round(sum(t['weight'] for t in testimonies if t['weight'] > 0), 2)
    ud_total = round(-sum(t['weight'] for t in testimonies if t['weight'] < 0), 2)
    score = max(1.0, min(10.0, 5.5 + fav_total - ud_total))

    diff = fav_total - ud_total
    if not testimonies or abs(diff) < 0.5:
        # «Gridlocked» chart: no testimonies/balanced -> draw likely
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
    """A planet applying to an aspect with a FIXED point (Fortune): the orb shrinks."""
    speed = planet.get('speed', 0) or 0
    lon = planet.get('full_degree')
    if lon is None:
        return False
    now = abs(_angle_diff(lon, point_lon) - aspect_angle)
    future = abs(_angle_diff((lon + speed * 0.5) % 360, point_lon) - aspect_angle)
    return future < now


def _moon_aspect_events(chart: EventChart, moon: Dict[str, Any], travel_limit: float) -> List[Dict[str, Any]]:
    """All applying Moon events within its range, in path order:
    aspects to significators (bodies and antiscia) and to Fortune/its antiscion.
    The path is measured in degrees of the Moon's travel, corrected for the target's speed."""
    moon_lon = moon['full_degree']
    moon_speed = abs(moon.get('speed', 0) or 13.2) or 13.2
    events: List[Dict[str, Any]] = []

    def scan(target_lon: float, target_speed: float, label: str, kind: str,
             side: int, antisc: bool):
        for aspect, angle in ASPECT_ANGLES.items():
            # The Moon catches up with the aspect: how many degrees it has to go until exact.
            # Aspect points: target_lon ± angle. The Moon moves forward.
            for direction in (1, -1) if angle not in (0, 180) else (1,):
                point = (target_lon + direction * angle) % 360
                gap = (point - moon_lon) % 360  # the Moon's forward path to the point
                # Correction for the target's motion (planets move forward/backward):
                rel = moon_speed - target_speed
                if rel <= 0.1:
                    continue
                travel = gap * moon_speed / rel
                if 0.01 <= travel <= travel_limit:
                    events.append({
                        'travel': travel, 'aspect': aspect, 'target': label,
                        'kind': kind, 'side': side, 'antiscion': antisc,
                    })

    # Significators (bodies + antiscia)
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
        # Lords' antiscia: conjunctions over a short range are NOT final, lower weight.
        scan(antiscion(lord_lon), -lord_speed, f"{lord} [L{lord_house}](ant)",
             'lord_antiscion', side, True)

    # Fortune and its antiscion: an aspect to them is FINAL; the sign decides the aspect type.
    if chart.fortuna is not None:
        for point, label in ((chart.fortuna, 'Fortuna'), (chart.fortuna_antiscion, 'Fortuna(ant)')):
            for aspect, angle in ASPECT_ANGLES.items():
                for direction in (1, -1) if angle not in (0, 180) else (1,):
                    p = (point + direction * angle) % 360
                    gap = (p - moon_lon) % 360
                    travel = gap  # Fortune is stationary
                    if 0.01 <= travel <= travel_limit:
                        side = 1 if aspect in HARMONIOUS_ASPECTS else -1
                        events.append({
                            'travel': travel, 'aspect': aspect, 'target': label,
                            'kind': 'fortuna', 'side': side,
                            'antiscion': label.endswith('(ant)'),
                        })

    # Dedup (the same event via two directions) and sort by path.
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
    """Aspects of Lord 1/7 to Fortune/its antiscion (ch. 2):
    L1 conj Fortune/antiscion -> favourite; L1 opp -> opponent;
    L7 conj -> opponent; L7 opp antiscion -> favourite;
    The book's ANOMALY: L7 bodily opposition to Fortune -> OPPONENT.
    Trine/sextile/square of Lords 1/7 to Fortune are unreliable — ignored.
    «MAKE SURE THE ASPECT ACTUALLY HAPPENS» — interception by another planet cancels it."""
    lord_lon = chart.planet_lon(lord)
    lord_data = chart.planets.get(lord) or {}
    if lord_lon is None or chart.fortuna is None:
        return

    def prohibited(travel_orb: float) -> bool:
        """The lord perfects an aspect to another planet before it reaches Fortune."""
        speed = abs(lord_data.get('speed', 0) or 0)
        if speed < 1e-6:
            return True  # stationary — will not get there
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
                        lord_data, olon, angle):
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
            (chart.fortuna, 180, -1, 'opp Fortuna'),  # the book's anomaly
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
    """Pluto/Uranus/Saturn per ch. 2. Neptune is ignored («inconsistent»)."""
    # Pluto: «powerful destructive effect on a relevant cusp... holds a grudge
    # against favourites»; on the 2nd cusp it harms the favourite.
    pluto_lon = chart.planet_lon('Pluto')
    if pluto_lon is not None:
        for house, side in ((1, 1), (10, 1), (2, 1), (7, -1), (4, -1)):
            cusp = chart.cusps.get(house)
            if cusp is None:
                continue
            orb = _angle_diff(pluto_lon, cusp)
            if orb <= OUTER_ORB:
                w = W_PLUTO if side > 0 else W_PLUTO * 0.5  # it is more lenient to the underdog
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

    # Uranus: immediately applying to MC or conj Fortune -> favourite; opp Fortune -> opponent.
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
            if orb_c <= OUTER_ORB and _is_applying_to_point(uranus, chart.fortuna, 0):
                add('Uranus', 'uranus_fortuna', 'conj Fortuna', W_URANUS * _closeness(orb_c, OUTER_ORB), orb_c)
            elif orb_o <= OUTER_ORB and _is_applying_to_point(uranus, chart.fortuna, 180):
                add('Uranus', 'uranus_fortuna', 'opp Fortuna', -W_URANUS * _closeness(orb_o, OUTER_ORB), orb_o)
            # opp Fortune's antiscion — the Super Bowl 2002 example (for the underdog)
            if chart.fortuna_antiscion is not None:
                orb_a = abs(_angle_diff(uranus_lon, chart.fortuna_antiscion) - 180)
                if orb_a <= OUTER_ORB and _is_applying_to_point(uranus, chart.fortuna_antiscion, 180):
                    add('Uranus', 'uranus_fortuna', 'opp Fortuna(ant)', -W_URANUS * _closeness(orb_a, OUTER_ORB), orb_a)

    # Saturn as malefic (if not Lord 1/7): «afflicting whatever it touches».
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


# ---------- natal note (not scoring) ----------

def natal_personalization_note(natal_chart: Dict[str, Any], lord1: Optional[str],
                               language: str) -> Optional[str]:
    """Context: the favourite's significator matches the ruler of the athlete's natal ASC.
    Only a mention for the LLM, not used in scoring."""
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
    """RAG query using ch. 2 (event chart) terms, not horary ones."""
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


# ---------- deterministic card rendering (no LLM) ----------
# The LLM repeatedly distorted facts from the judgement sheet (confused the significator's house, argued
# with the hybrid showings using book quotes) — so score/Showings/Conclusion
# are built directly from the computed values. See plans/daily-forecast-hybrid-method.md.

def _side_showings_list(side: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Significator showings for the card and the short prose: first the 4 hybrid ones
    (house/dignity/combustion/retro, in this fixed order — as in the
    reference examples), then ANY book (ch. 2) testimonies of the same
    significator (cusps on_cusp/inside_enemy_house, nodes, aspects to Fortune and
    the like — everything already merged into side['showings'] via _merged_showings),
    sorted by weight. Book testimonies used to be dropped here —
    that was my own narrowing based on the user's 4 reference examples, and
    not the user's requirement; an event chart must not lose what is actually in it
    just because it did not occur in the specific examples."""
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

    book_showings = [
        s for s in side['showings']
        if s['kind'] not in ('house_strength', 'dignity', 'combustion', 'retrograde')
        and s.get('effect') is not None
    ]
    book_showings.sort(key=lambda s: abs(s['weight']), reverse=True)
    ordered.extend(book_showings)
    return ordered


def _side_narrative(side: Optional[Dict[str, Any]], role: str, language: str) -> str:
    own_label = _side_name(role, language)
    if not side:
        if language == 'ru':
            return f"У {own_label.lower()} нет определённого значителя дома в этой карте."
        return f"The {own_label.lower()} has no clearly determined house significator in this chart."
    if language == 'ru':
        nickname = f" («{side['house_nickname']}»)" if side.get('house_nickname') else ""
        retro = ", ретрограден" if side['retrograde'] else ""
        text = (f"{side['planet_ru']} ({own_label}), управитель дома {side['lord_house']}, находится в "
                f"{side['sign_ru']} {side['degree']}°, дом {side['house']}{nickname}{retro}. "
                f"Достоинство: {side['dignity_ru']}.")
    else:
        nickname = f" ('{side['house_nickname']}')" if side.get('house_nickname') else ""
        retro = ", retrograde" if side['retrograde'] else ""
        text = (f"{side['planet_ru']} ({own_label}), ruler of house {side['lord_house']}, is in "
                f"{side['sign_ru']} {side['degree']}°, house {side['house']}{nickname}{retro}. "
                f"Dignity: {side['dignity_ru']}.")
    items = _side_showings_list(side)
    if items:
        if language == 'ru':
            text += " Показания: " + "; ".join(
                f"{s['label_ru']} — {s['effect']}" for s in items
            ) + "."
        else:
            text += " Showings: " + "; ".join(
                f"{s['label_ru']} — {s['effect']}" for s in items
            ) + "."
    else:
        text += " Значимых показаний нет — позиция нейтральна." if language == 'ru' \
            else " No significant showings — the position is neutral."
    return text


def _verdict_narrative(card: Optional[Dict[str, Any]], language: str) -> str:
    """Short verdict for the verdict field — the same card-scope logic
    (_card_verdict) as in the detailed card, not the general judgement['match_type']."""
    decisive, winner, _diff = _card_verdict(card)
    if language == 'ru':
        if winner is None:
            headline = "Карта сбалансирована — вероятна ничья или непредсказуемый исход."
        elif decisive:
            headline = f"{_side_name(winner, 'ru')} побеждает."
        else:
            _genitive = {'favourite': 'Фаворита', 'underdog': 'Аутсайдера'}
            headline = f"Небольшой перевес {_genitive[winner]}, случай неочевиден."
    else:
        if winner is None:
            headline = "The chart is balanced — a draw or an unpredictable outcome is likely."
        elif decisive:
            headline = f"The {_side_name(winner, 'en').lower()} wins."
        else:
            headline = f"A slight edge to the {_side_name(winner, 'en').lower()} — not a clear-cut case."
    return headline + " " + _verdict_paragraph(card, language)


# ---------- detailed card (format «Significators/Planets/Showings/Conclusion») ----------
# Exact format following the user's example (event-chart cards). Only
# formatting of already computed data (significator_card/judgement) —
# calculation/scoring is not involved here and does not change. The header is only the generic
# variant («Event Chart · place · date · time · Roles: Favourite / Underdog»):
# player names/spread/odds are not part of the current request schema.

# Thresholds SPECIFICALLY for the card conclusion — NOT the same as the general match_type
# (judgement['match_type'], which is computed over the whole ch. 2+hybrid sheet).
# Tuned and checked on the user's 4 reference examples (Båstad,
# Arlington, Umag, Jupiter/Mercury): |diff| >= 1.5 -> decisive outcome,
# 0.3 <= |diff| < 1.5 -> slight edge, < 0.3 -> draw/unclear.
CARD_DECISIVE_THRESHOLD = 1.5
CARD_EDGE_THRESHOLD = 0.3


def _card_verdict(card: Optional[Dict[str, Any]]) -> Tuple[bool, Optional[str], float]:
    """The card conclusion is computed over ALL showings actually displayed in
    the card: 4 hybrid factors of Lord1/Lord7 (house/dignity/combustion/
    retro) + book (ch. 2) testimonies tied to a specific significator
    (cusps, nodes, aspects to Fortune), + «Other chart showings» (Moon,
    Fortune's antiscion, its dispositor, outer planets — chart_wide). Everything
    shown in the text must be counted here too — otherwise the card conclusion
    may contradict its own showings.
    Returns (decisive, winner['favourite'|'underdog'|None], diff)."""
    if not card or not card.get('favourite') or not card.get('underdog'):
        return False, None, 0.0

    def _net(side: Dict[str, Any]) -> float:
        return sum(s['weight'] for s in _side_showings_list(side))

    chart_wide_total = sum(s['weight'] for s in (card.get('chart_wide') or []))
    diff = _net(card['favourite']) - _net(card['underdog']) + chart_wide_total
    if abs(diff) < CARD_EDGE_THRESHOLD:
        return False, None, diff
    winner = 'favourite' if diff > 0 else 'underdog'
    decisive = abs(diff) >= CARD_DECISIVE_THRESHOLD
    return decisive, winner, diff


def _card_match_type(card: Optional[Dict[str, Any]]) -> str:
    """match_type STRICTLY from the card verdict (_card_verdict) — with the same
    set of values as before (comfortable_win/advantage/draw_likely/
    underdog_edge/underdog_win_likely), so that existing consumers of the field
    don't break. Previously this field was taken from judgement['match_type'] (the full
    ch. 2+hybrid calculation) — it could contradict the card text/verdict,
    since it was computed over a different set of testimonies. Now there is only one source
    of truth: the 4 factors actually shown in the card."""
    decisive, winner, _diff = _card_verdict(card)
    if winner is None:
        return 'draw_likely'
    if winner == 'favourite':
        return 'comfortable_win' if decisive else 'advantage'
    return 'underdog_win_likely' if decisive else 'underdog_edge'


def _render_header(transits: Dict[str, Any], language: str) -> str:
    location = (transits.get('transit_summary') or {}).get('location') or {}
    place = location.get('place_name') or '—'
    date_part, time_part = '—', '—'
    target_date_str = transits.get('target_date')
    if target_date_str:
        try:
            dt = datetime.fromisoformat(target_date_str)
            date_part = dt.strftime('%d.%m.%Y')
            time_part = dt.strftime('%H:%M')
            offset = dt.strftime('%z')  # e.g. +0200
            if offset:
                time_part += f" UTC{offset[:3]}:{offset[3:]}"
        except ValueError:
            pass
    line1 = f"Event Chart · {place} · {date_part} · {time_part}"
    line2 = "Плацидус · Kick-off · Роли: Фаворит / Аутсайдер" if language == 'ru' \
        else "Placidus · Kick-off · Roles: Favourite / Underdog"
    return line1 + "\n" + line2


def _planet_line_lord(side: Dict[str, Any], role: str, language: str) -> List[str]:
    role_label = _side_name(role, language)
    header = f"{side['symbol']} {side['planet_ru']} ({role_label})"
    retro_mark = " ℞" if side['retrograde'] else ""
    dignity_part = f" · {side['dignity_ru']}" if side['dignity'] != 'peregrine' else ""
    dignity_mark = f" {side['dignity_mark']}" if side.get('dignity_mark') else ""
    house_mark = f" {side['house_mark']}" if side.get('house_mark') else ""
    house_word = "Дом" if language == 'ru' else "House"
    detail = (f"{side['sign_symbol']} {side['degree']:.2f}°{retro_mark} · "
              f"{house_word} {side['house']}{house_mark}{dignity_part}{dignity_mark}")
    return [header, detail]


def _planet_line_plain(p: Dict[str, Any], language: str) -> List[str]:
    header = f"{p['symbol']} {p['planet_ru']}"
    retro_mark = " ℞" if p['retrograde'] else ""
    house_word = "Дом" if language == 'ru' else "House"
    detail = f"{p['sign_symbol']} {p['degree']:.2f}°{retro_mark} · {house_word} {p['house']}"
    return [header, detail]


def _showing_pairs(side: Dict[str, Any]) -> List[str]:
    """Line pairs (description, effect) for the «Showings» block of one significator:
    house → dignity (if not peregrine) → combustion (if any) → retro
    (if any), then any relevant book (ch. 2) testimonies of the same
    significator (cusps, nodes, aspects to Fortune, etc.) — see
    _side_showings_list, the single source for both the card and the short
    prose (favorite/opponent). Does not take language — reads the ready-made
    label_ru/effect, computed with the right language when the showings were built."""
    lines: List[str] = []
    for s in _side_showings_list(side):
        lines += [s['label_ru'], s['effect']]
    return lines


def _retro_combust_summary(fav: Optional[Dict[str, Any]],
                            ud: Optional[Dict[str, Any]], language: str) -> List[str]:
    """Fallback line «Retro/combustion: none for anyone» — only if NOT
    A SINGLE significator has either retro or combustion (otherwise they are already shown
    as separate lines in _showing_pairs for each significator)."""
    for side in (fav, ud):
        if side and (side['retrograde'] or side.get('combust')):
            return []
    return ["Ретро/сгорание", "Нет ни у кого"] if language == 'ru' else ["Retro/combustion", "None"]


def _verdict_paragraph(card: Optional[Dict[str, Any]], language: str) -> str:
    """Self-contained explanation of the conclusion from THIS chart (no comparisons with
    other charts unknown to the system). Takes the ready-made readable wording
    (label_ru/effect) from the card showings — NOT raw testimony codes, so that
    internal names like «essential_dignity» do not leak."""
    no_evidence = "Свидетельств в карте немного, перевес не выражен явно." if language == 'ru' \
        else "There is little evidence in the chart — no clear edge either way."
    if not card or not card.get('favourite') or not card.get('underdog'):
        return no_evidence
    fav, ud = card['favourite'], card['underdog']
    ranked: List[Dict[str, Any]] = []
    for side in (fav, ud):
        ranked.extend(_side_showings_list(side))
    ranked.sort(key=lambda s: abs(s['weight']), reverse=True)
    top = ranked[:2]
    if not top:
        return no_evidence
    lead = "Решающие показания: " if language == 'ru' else "Decisive showings: "
    text = lead + "; ".join(
        f"{s['label_ru']} — {s['effect']}" for s in top
    ) + "."
    fh, uh = fav['house'], ud['house']
    if fh and fh == uh:
        nickname = fav.get('house_nickname')
        if language == 'ru':
            label = f" («{nickname}»)" if nickname else ""
            text += (f" Оба значителя делят дом {fh}{label} — этот фактор частично "
                    f"взаимно гасится, решают остальные повреждения и усиления.")
        else:
            label = f" ('{nickname}')" if nickname else ""
            text += (f" Both significators share house {fh}{label} — this factor partly "
                    f"cancels out, the remaining afflictions/strengths decide.")
    return text


def _render_card_text(transits: Dict[str, Any], judgement: Dict[str, Any],
                       card: Optional[Dict[str, Any]], language: str) -> str:
    """Full text card (Significators/Planets/Showings/Conclusion) —
    format following the user's example. Falls back to a short narrative if
    the chart could not be built (no ASC/7th cusp)."""
    if not card:
        return _verdict_narrative(card, language)

    fav, ud = card.get('favourite'), card.get('underdog')
    asc, desc = card.get('asc'), card.get('desc')

    if language == 'ru':
        lines: List[str] = [_render_header(transits, language), "Сигнификаторы"]
        if asc:
            lines += ["АСЦ (1-й дом, Фаворит)", f"{asc['symbol']} {asc['sign_ru']} {asc['degree']:.2f}°"]
        if desc:
            lines += ["7-й дом (Аутсайдер)", f"{desc['symbol']} {desc['sign_ru']} {desc['degree']:.2f}°"]
        if fav:
            lines += ["Lord 1 = Фаворит", f"{fav['symbol']} {fav['planet_ru']}"]
        if ud:
            lines += ["Lord 7 = Аутсайдер", f"{ud['symbol']} {ud['planet_ru']}"]
        lines.append("Планеты")
    else:
        lines = [_render_header(transits, language), "Significators"]
        if asc:
            lines += ["ASC (1st house, Favourite)", f"{asc['symbol']} {asc['sign_ru']} {asc['degree']:.2f}°"]
        if desc:
            lines += ["7th house (Underdog)", f"{desc['symbol']} {desc['sign_ru']} {desc['degree']:.2f}°"]
        if fav:
            lines += ["Lord 1 = Favourite", f"{fav['symbol']} {fav['planet_ru']}"]
        if ud:
            lines += ["Lord 7 = Underdog", f"{ud['symbol']} {ud['planet_ru']}"]
        lines.append("Planets")

    if fav:
        lines += _planet_line_lord(fav, 'favourite', language)
    if ud:
        lines += _planet_line_lord(ud, 'underdog', language)
    lord_planets = {p for p in (fav and fav['planet'], ud and ud['planet']) if p}
    for p in (card.get('planets') or []):
        if p['planet'] in lord_planets:
            continue
        lines += _planet_line_plain(p, language)

    lines.append("Показания" if language == 'ru' else "Showings")
    if fav:
        lines += _showing_pairs(fav)
    if ud:
        lines += _showing_pairs(ud)
    lines += _retro_combust_summary(fav, ud, language)

    chart_wide = card.get('chart_wide') or []
    if chart_wide:
        lines.append("Прочие показания карты (Луна/Фортуна/узлы/внешние)" if language == 'ru'
                      else "Other chart-wide showings (Moon/Fortuna/nodes/outer planets)")
        for s in chart_wide:
            lines += [s['label_ru'], s['effect']]

    decisive, winner, _diff = _card_verdict(card)
    emoji = '🏆' if decisive else '⚖️'
    if language == 'ru':
        headline = f"{_side_name(winner, 'ru')} побеждает" if (decisive and winner) else "случай пограничный"
        lines.append(f"{emoji} Вывод: {headline}")
        lines.append(_verdict_paragraph(card, language))
        if decisive and winner:
            lines.append(f"Прогноз: {_side_name(winner, 'ru')} выигрывает, случай однозначный")
        elif winner:
            _genitive = {'favourite': 'Фаворита', 'underdog': 'Аутсайдера'}
            lines.append(f"Лёгкий перевес {_genitive[winner]}, случай неочевидный")
        else:
            lines.append("Ничья вероятна, случай неочевидный")
    else:
        headline = f"The {_side_name(winner, 'en').lower()} wins" if (decisive and winner) else "borderline case"
        lines.append(f"{emoji} Verdict: {headline}")
        lines.append(_verdict_paragraph(card, language))
        if decisive and winner:
            lines.append(f"Forecast: the {_side_name(winner, 'en').lower()} wins, a clear-cut case")
        elif winner:
            lines.append(f"Slight edge to the {_side_name(winner, 'en').lower()}, not an obvious case")
        else:
            lines.append("A draw is likely, not an obvious case")
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
    """Full pipeline of the match-day forecast (event chart method).
    transits — the result of calculate_transits (must contain transit_houses)."""
    t_planets = transits.get('transit_planets', {}) or {}
    transit_houses = transits.get('transit_houses') or {}

    if not transit_houses:
        no_houses_note = 'нет transit_houses — нейтральная оценка' if language == 'ru' \
            else 'no transit_houses — neutral score'
        judgement = {
            'base_score': 5.5, 'lord1': None, 'lord7': None, 'lord10': None, 'lord4': None,
            'testimonies': [], 'favourite_points': 0, 'underdog_points': 0,
            'match_type': 'draw_likely', 'engine_notes': [no_houses_note],
            'mixed_profiles': {}, 'significator_card': None,
        }
    else:
        judgement = judge_event_chart(
            transit_houses, t_planets,
            moon_range_degrees=moon_range_degrees,
            extra_time_possible=extra_time_possible,
            language=language,
        )

    base = judgement['base_score']  # internal calculation (affects match_type), not returned outside
    key_aspects = judgement['testimonies']
    fav_list, ud_list = _split_sides(key_aspects)

    houses_activated = sorted({
        int(p.get('natal_house')) for p in t_planets.values()
        if isinstance(p, dict) and p.get('natal_house')
    })

    personal_note = natal_personalization_note(natal_chart, judgement.get('lord1'), language)

    # RAG over the event chart testimonies
    async def search_testimony(t: Dict[str, Any]):
        query = _testimony_query(t)
        chunks = await search_chunks_priority_book(
            query, DAILY_FORECAST_PRIORITY_BOOK_ID, top_k_priority=5, top_k_others=0
        )
        return query, chunks

    # Hybrid testimonies (source='mixed': essential dignity/angularity/
    # retrogradation of Lord 1/7) are deliberately NOT searched in the book: the book's ch. 2 explicitly
    # forbids these concepts for an event chart, RAG would return contradicting
    # quotes. See plans/daily-forecast-hybrid-method.md.
    book_testimonies = [t for t in key_aspects if t.get('source', 'book') != 'mixed']
    # Dedup BY QUERY before going to RAG: different testimonies of the same type (e.g. a node
    # touching both Lord 1 and Lord 7) produce an identical _testimony_query — no point searching
    # the book twice for the same thing (previously dedup was only on already fetched chunks).
    unique_by_query: Dict[str, Dict[str, Any]] = {}
    for t in book_testimonies:
        unique_by_query.setdefault(_testimony_query(t), t)
    rag_results = await asyncio.gather(
        *[search_testimony(t) for t in unique_by_query.values()], return_exceptions=True
    )
    # Chunk dedup + character budget: each book fragment goes into the prompt once.
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

    # Deterministic rendering (no LLM): score/Showings/Conclusion are built
    # directly from the computed sheet. The LLM's free text used to distort facts
    # (confused the significator's house, argued with the hybrid showings using book quotes) —
    # see plans/daily-forecast-hybrid-method.md.
    # card_text — the main, detailed output (Significators/Planets/
    # Showings/Conclusion format). favorite/opponent/verdict — the same data as short
    # prose, for frontends that still read these separate fields.
    card_text = _render_card_text(transits, judgement, card, language)
    favorite_text = _side_narrative(card.get('favourite') if card else None, 'favourite', language)
    opponent_text = _side_narrative(card.get('underdog') if card else None, 'underdog', language)
    verdict_text = _verdict_narrative(card, language)
    summary_text = card_text
    if personal_note:
        summary_text += f"\n\n{personal_note}"
    # Per the product requirement, score/category (numeric rating 1-10) are NOT
    # returned in the response — only the qualitative verdict (match_type) and
    # the text description. base_score remains an internal computed
    # value (affects match_type), but is not returned outside.
    parsed = {
        'favorite': favorite_text, 'opponent': opponent_text, 'verdict': verdict_text,
        'summary': summary_text, 'card_text': card_text,
    }
    llm_error: Optional[str] = None  # generation is deterministic, the LLM is not called

    return {
        **parsed,
        'key_aspects': key_aspects,
        'significator_card': judgement.get('significator_card'),
        'houses_activated': houses_activated,
        'fortune': judgement.get('fortuna'),
        'fortune_antiscion': judgement.get('fortuna_antiscion'),
        'lunar_phase': transits.get('lunar_phase'),
        'llm_error': llm_error,
        'llm_provider': provider,  # echo for the frontend; generation is deterministic, not used
        'llm_model': model,
        'generation_mode': 'deterministic',
        'rag_sources': rag_sources,
        'personal_note': personal_note,
        # strength_breakdown: keep the lord1/lord7 keys for the frontend,
        # total_strength = the side's total points on the judgement sheet.
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
        # match_type — from the card verdict (_card_verdict), NOT from the full
        # judgement['match_type'] (ch. 2+hybrid): otherwise this field could
        # contradict the verdict/card_text text computed over a different
        # set of testimonies. full_chart_match_type — the old value, for
        # debugging/comparison, not for display to the user.
        'match_type': _card_match_type(card),
        'full_chart_match_type': judgement.get('match_type'),
        'moon_report': judgement.get('moon_report'),
        'engine_notes': judgement.get('engine_notes'),
    }
