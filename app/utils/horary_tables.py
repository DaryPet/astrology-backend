# app/utils/horary_tables.py
# Классические (традиционные, 7 планет) таблицы эссенциального достоинства и
# вспомогательные хорарные функции.
# classical_ruler/antiscion — используются в daily_forecast_service для определения
# значителей (Lord 1/4/7/10) в методе карты события (Frawley, гл. 2).
# essential_dignity — используется ТОЛЬКО в гибридном слое daily_forecast_service
# (Lord 1/7), см. plans/daily-forecast-hybrid-method.md: книга гл. 2 прямо
# запрещает это понятие для карты события, но по итогам эмпирических тестов
# на реальных матчах его добавление повышает точность.
# NOTE: house_angularity()/is_retrograde() ниже не используются — сила дома
# считается по полной шкале Лилли (HOUSE_STRENGTH в daily_forecast_service, а
# не по грубому angular/succedent/cadent), ретроградность берётся из готового
# поля 'is_retrograde' в transit_planets (считается в astrology_v2).
from typing import Literal, Optional, Dict, Any

TRADITIONAL_PLANETS = {'Sun', 'Moon', 'Mercury', 'Venus', 'Mars', 'Jupiter', 'Saturn'}

# Домицил (управление): классическое, до открытия Урана/Нептуна/Плутона.
# Каждый знак — список из 1-2 планет (для Sun/Moon — один знак на двоих).
CLASSICAL_RULERS = {
    'Aries': 'Mars', 'Scorpio': 'Mars',
    'Taurus': 'Venus', 'Libra': 'Venus',
    'Gemini': 'Mercury', 'Virgo': 'Mercury',
    'Cancer': 'Moon',
    'Leo': 'Sun',
    'Sagittarius': 'Jupiter', 'Pisces': 'Jupiter',
    'Capricorn': 'Saturn', 'Aquarius': 'Saturn',
}

# Экзальтация: планета → знак экзальтации.
EXALTATION_SIGN = {
    'Sun': 'Aries', 'Moon': 'Taurus', 'Mercury': 'Virgo',
    'Venus': 'Pisces', 'Mars': 'Capricorn', 'Jupiter': 'Cancer', 'Saturn': 'Libra',
}


def _opposite_sign(sign: str) -> str:
    from app.utils.astrology_v2 import ZODIAC_SIGNS
    idx = ZODIAC_SIGNS.index(sign)
    return ZODIAC_SIGNS[(idx + 6) % 12]


FALL_SIGN = {planet: _opposite_sign(sign) for planet, sign in EXALTATION_SIGN.items()}
# Изгнание (detriment) — знак, противоположный домицилу планеты.
DETRIMENT_SIGN = {}
for _sign, _planet in CLASSICAL_RULERS.items():
    DETRIMENT_SIGN.setdefault(_planet, set()).add(_opposite_sign(_sign))

DignityState = Literal['domicile', 'exaltation', 'detriment', 'fall', 'peregrine']


def essential_dignity(planet: str, sign: str) -> DignityState:
    """Эссенциальное достоинство планеты в знаке (только мажорные достоинства:
    домицил/экзальтация/изгнание/падение; term/face не учитываем — v1 упрощение)."""
    if CLASSICAL_RULERS.get(sign) == planet:
        return 'domicile'
    if EXALTATION_SIGN.get(planet) == sign:
        return 'exaltation'
    if FALL_SIGN.get(planet) == sign:
        return 'fall'
    if sign in DETRIMENT_SIGN.get(planet, ()):
        return 'detriment'
    return 'peregrine'


HouseAngularity = Literal['angular', 'succedent', 'cadent']
_ANGULAR = {1, 4, 7, 10}
_SUCCEDENT = {2, 5, 8, 11}
_CADENT = {3, 6, 9, 12}


def house_angularity(house_num: Optional[int]) -> Optional[HouseAngularity]:
    if house_num in _ANGULAR:
        return 'angular'
    if house_num in _SUCCEDENT:
        return 'succedent'
    if house_num in _CADENT:
        return 'cadent'
    return None


def antiscion(longitude: float) -> float:
    """Антисция — зеркало точки относительно оси Рак/Козерог (солнцестояние)."""
    return (180 - longitude) % 360


def classical_ruler(sign: str) -> Optional[str]:
    return CLASSICAL_RULERS.get(sign)


RETROGRADE_PENALTY = -1.5  # Фроули: ретроградный значитель = слабость


def is_retrograde(planet_data: Dict[str, Any]) -> bool:
    """Проверка ретроградности планеты (speed < 0 для большинства планет)."""
    speed = planet_data.get('speed', 0) or 0
    # Sun/Moon/Venus не могут быть ретроградными в традиционной астрологии
    # но Mercury/Mars/Jupiter/Saturn могут
    return speed < -0.001  # небольшой порог для чисел с плавающей точкой
