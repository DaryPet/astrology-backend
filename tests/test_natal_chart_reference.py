"""Reference-chart test for calculate_planet_positions (app/utils/astrology_v2.py).

Fixed input: 22.04.1978, 04:40, Tallinn, Estonia. Expected values are an
independently calculated reference chart for this exact birth data.

Tolerances: planet/cusp degrees are compared with a small margin rather than
exact equality, and North Node uses a wider margin because this codebase
computes the TRUE node (swe.TRUE_NODE) while some reference charts are
generated with the MEAN node convention — both are standard, valid
definitions of the same point.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.astrology_v2 import calculate_planet_positions

BIRTH_DT = datetime(1978, 4, 22, 4, 40, tzinfo=ZoneInfo('Europe/Tallinn'))
LAT, LON = 59.4370, 24.7536

PLANET_TOLERANCE_DEG = 0.05
NODE_TOLERANCE_DEG = 1.5
CUSP_TOLERANCE_DEG = 0.75

REFERENCE_PLANETS = {
    'Sun':       ('Taurus', 1 + 34 / 60, 1),
    'Moon':      ('Libra', 17 + 17 / 60, 7),
    'Mercury':   ('Aries', 15 + 17 / 60, 1),
    'Venus':     ('Taurus', 23 + 34 / 60, 2),
    'Mars':      ('Leo', 4 + 14 / 60, 6),
    'Jupiter':   ('Cancer', 1 + 32 / 60, 4),
    'Saturn':    ('Leo', 23 + 39 / 60, 7),
    'Uranus':    ('Scorpio', 14 + 56 / 60, 8),
    'Neptune':   ('Sagittarius', 18 + 2 / 60, 9),
    'Pluto':     ('Libra', 14 + 51 / 60, 7),
    'NorthNode': ('Libra', 4 + 40 / 60, 7),
    'Lilith':    ('Cancer', 10 + 34 / 60, 5),
    'Chiron':    ('Taurus', 5 + 5 / 60, 1),
}

REFERENCE_ASC = ('Aquarius', 21 + 28 / 60)
REFERENCE_MC = ('Sagittarius', 20 + 21 / 60)

REFERENCE_HOUSES = {
    1: ('Aquarius', 21 + 28 / 60),
    2: ('Taurus', 9 + 23 / 60),
    3: ('Gemini', 5 + 5 / 60),
    4: ('Gemini', 20 + 21 / 60),
    5: ('Cancer', 3 + 30 / 60),
    6: ('Cancer', 18 + 59 / 60),
    7: ('Leo', 21 + 28 / 60),
    8: ('Scorpio', 9 + 23 / 60),
    9: ('Sagittarius', 5 + 5 / 60),
    10: ('Sagittarius', 20 + 21 / 60),
    11: ('Capricorn', 3 + 30 / 60),
    12: ('Capricorn', 18 + 59 / 60),
}


def _chart():
    return calculate_planet_positions(
        BIRTH_DT, "Tallinn, Estonia", lat=LAT, lon=LON, timezone_str='Europe/Tallinn',
    )


def test_planet_signs_houses_and_degrees_match_reference_chart():
    """Every planet's sign, house and degree match the reference chart."""
    chart = _chart()
    for planet, (sign, degree, house) in REFERENCE_PLANETS.items():
        data = chart['planets'][planet]
        tolerance = NODE_TOLERANCE_DEG if planet == 'NorthNode' else PLANET_TOLERANCE_DEG

        assert data['sign'] == sign, f"{planet}: expected sign {sign}, got {data['sign']}"
        assert data['house'] == house, f"{planet}: expected house {house}, got {data['house']}"
        assert abs(data['degree'] - degree) <= tolerance, (
            f"{planet}: expected {degree:.4f}°, got {data['degree']:.4f}° "
            f"(diff {abs(data['degree'] - degree):.4f}° > tolerance {tolerance}°)"
        )


def test_ascendant_and_mc_match_reference_chart():
    """Ascendant and Midheaven match the reference chart."""
    chart = _chart()
    asc_sign, asc_degree = REFERENCE_ASC
    mc_sign, mc_degree = REFERENCE_MC

    assert chart['ascendant'] == asc_sign
    assert abs(chart['ascendant_degree'] - asc_degree) <= CUSP_TOLERANCE_DEG

    assert chart['mc'] == mc_sign
    assert abs(chart['mc_degree'] - mc_degree) <= CUSP_TOLERANCE_DEG


def test_house_cusps_match_reference_chart():
    """All 12 house cusps match the reference chart."""
    chart = _chart()
    for house_num, (sign, degree) in REFERENCE_HOUSES.items():
        cusp = chart['houses'][house_num]
        assert cusp['sign'] == sign, f"House {house_num}: expected sign {sign}, got {cusp['sign']}"
        assert abs(cusp['degree'] - degree) <= CUSP_TOLERANCE_DEG, (
            f"House {house_num}: expected {degree:.4f}°, got {cusp['degree']:.4f}° "
            f"(diff {abs(cusp['degree'] - degree):.4f}° > tolerance {CUSP_TOLERANCE_DEG}°)"
        )
