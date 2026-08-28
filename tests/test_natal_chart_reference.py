"""Reference-chart test for calculate_planet_positions and calculate_aspects
(app/utils/astrology_v2.py).

Fixed input: 22.04.1978, 04:40, Tallinn, Estonia. Expected planet/house
values are an independently calculated reference chart for this exact birth
data.

Tolerances: planet/cusp degrees are compared with a small margin rather than
exact equality, and North Node uses a wider margin because this codebase
computes the TRUE node (swe.TRUE_NODE) while some reference charts are
generated with the MEAN node convention — both are standard, valid
definitions of the same point.

Aspects (REFERENCE_ASPECTS below): the expected (planet1, planet2, type,
orb) tuples are NOT independently sourced — they are derived by applying the
same aspect-angle list (0/60/90/120/180, a fixed astrological convention) to
the independently-sourced REFERENCE_PLANETS degrees above, computed once and
diffed against the app's live calculate_aspects() output to confirm the two
agree (done in the session that added this test — see engineering-insights
for the full comparison). This test therefore verifies that calculate_aspects
correctly wires real planet positions (full_degree) into the angle/orb
check — it does NOT independently verify the orb-table values themselves
(app/utils/astrology_v2.py's ORBS dict), since those are a convention choice,
not a fact-checkable external reference.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.astrology_v2 import calculate_planet_positions, calculate_aspects

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


# (planet1, planet2, aspect_type, expected_orb_deg) — see module docstring
# for how these were derived. Sorted by orb (tightest/most unambiguous first).
REFERENCE_ASPECTS = [
    ('Sun', 'Jupiter', 'Sextile', 0.033),
    ('Venus', 'Saturn', 'Square', 0.083),
    ('Mercury', 'Pluto', 'Opposition', 0.433),
    ('Mars', 'NorthNode', 'Sextile', 0.433),
    ('Moon', 'Neptune', 'Sextile', 0.750),
    ('Mars', 'Chiron', 'Square', 0.850),
    ('Moon', 'Mercury', 'Opposition', 2.000),
    ('Moon', 'Pluto', 'Conjunction', 2.433),
    ('Sun', 'Mars', 'Square', 2.667),
    ('Mercury', 'Neptune', 'Trine', 2.750),
    ('Jupiter', 'NorthNode', 'Square', 3.133),
    ('Neptune', 'Pluto', 'Sextile', 3.183),
    ('Sun', 'Chiron', 'Conjunction', 3.517),
    ('Jupiter', 'Chiron', 'Sextile', 3.550),
    ('Pluto', 'Lilith', 'Square', 4.283),
    ('Uranus', 'Lilith', 'Trine', 4.367),
    ('Mercury', 'Lilith', 'Square', 4.717),
    ('Lilith', 'Chiron', 'Sextile', 5.483),
    ('Saturn', 'Neptune', 'Trine', 5.617),
    ('NorthNode', 'Lilith', 'Square', 5.900),
    ('Moon', 'Saturn', 'Sextile', 6.367),
    ('Jupiter', 'Saturn', 'Sextile', 7.883),
]

ASPECT_ORB_TOLERANCE_DEG = 0.1
NODE_ASPECT_ORB_TOLERANCE_DEG = 1.5


def _chart():
    return calculate_planet_positions(
        BIRTH_DT, "Tallinn, Estonia", lat=LAT, lon=LON, timezone_str='Europe/Tallinn',
    )


def test_planet_signs_houses_and_degrees_match_reference_chart():
    """Every planet's sign, house and degree match the reference chart."""
    chart = _chart()
    print(f"\n  Input: {BIRTH_DT}, lat={LAT}, lon={LON}")
    print(f"  {'planet':<10} {'expected':<22} {'calculated':<22} {'diff°':<8} OK?")
    for planet, (sign, degree, house) in REFERENCE_PLANETS.items():
        data = chart['planets'][planet]
        tolerance = NODE_TOLERANCE_DEG if planet == 'NorthNode' else PLANET_TOLERANCE_DEG
        diff = abs(data['degree'] - degree)
        expected_str = f"{sign} {degree:.2f}° h{house}"
        got_str = f"{data['sign']} {data['degree']:.2f}° h{data['house']}"
        ok = data['sign'] == sign and data['house'] == house and diff <= tolerance
        print(f"  {planet:<10} {expected_str:<22} {got_str:<22} {diff:<8.4f} {'OK' if ok else 'MISMATCH'}")

        assert data['sign'] == sign, f"{planet}: expected sign {sign}, got {data['sign']}"
        assert data['house'] == house, f"{planet}: expected house {house}, got {data['house']}"
        assert diff <= tolerance, (
            f"{planet}: expected {degree:.4f}°, got {data['degree']:.4f}° "
            f"(diff {diff:.4f}° > tolerance {tolerance}°)"
        )


def test_ascendant_and_mc_match_reference_chart():
    """Ascendant and Midheaven match the reference chart."""
    chart = _chart()
    asc_sign, asc_degree = REFERENCE_ASC
    mc_sign, mc_degree = REFERENCE_MC
    print(f"\n  ASC expected: {asc_sign} {asc_degree:.2f}° | calculated: {chart['ascendant']} {chart['ascendant_degree']:.2f}° "
          f"(diff {abs(chart['ascendant_degree'] - asc_degree):.4f}°)")
    print(f"  MC  expected: {mc_sign} {mc_degree:.2f}° | calculated: {chart['mc']} {chart['mc_degree']:.2f}° "
          f"(diff {abs(chart['mc_degree'] - mc_degree):.4f}°)")

    assert chart['ascendant'] == asc_sign
    assert abs(chart['ascendant_degree'] - asc_degree) <= CUSP_TOLERANCE_DEG

    assert chart['mc'] == mc_sign
    assert abs(chart['mc_degree'] - mc_degree) <= CUSP_TOLERANCE_DEG


def test_house_cusps_match_reference_chart():
    """All 12 house cusps match the reference chart."""
    chart = _chart()
    print(f"\n  {'house':<6} {'expected':<20} {'calculated':<20} {'diff°':<8} OK?")
    for house_num, (sign, degree) in REFERENCE_HOUSES.items():
        cusp = chart['houses'][house_num]
        diff = abs(cusp['degree'] - degree)
        ok = cusp['sign'] == sign and diff <= CUSP_TOLERANCE_DEG
        expected_str = f"{sign} {degree:.2f}°"
        got_str = f"{cusp['sign']} {cusp['degree']:.2f}°"
        print(f"  {house_num:<6} {expected_str:<20} {got_str:<20} {diff:<8.4f} {'OK' if ok else 'MISMATCH'}")

        assert cusp['sign'] == sign, f"House {house_num}: expected sign {sign}, got {cusp['sign']}"
        assert diff <= CUSP_TOLERANCE_DEG, (
            f"House {house_num}: expected {degree:.4f}°, got {cusp['degree']:.4f}° "
            f"(diff {diff:.4f}° > tolerance {CUSP_TOLERANCE_DEG}°)"
        )


def test_aspects_between_planets_match_reference_chart():
    """All 22 real aspects among the 13 reference bodies are found by
    calculate_aspects, with the right type and a matching orb — see the
    module docstring for how REFERENCE_ASPECTS was derived, and no
    unexpected extra aspects appear among those 13 bodies."""
    chart = _chart()
    actual = calculate_aspects(chart['planets'])

    reference_bodies = set(REFERENCE_PLANETS.keys())
    actual_among_reference = {
        (a['planet1'], a['planet2']): a
        for a in actual
        if a['planet1'] in reference_bodies and a['planet2'] in reference_bodies
    }

    print(f"\n  Aspects found among {len(reference_bodies)} bodies: {len(actual_among_reference)} "
          f"(expected {len(REFERENCE_ASPECTS)})")
    print(f"  {'planet1':<10} {'planet2':<10} {'type':<12} {'exp.orb':<10} {'act.orb':<10} OK?")

    for planet1, planet2, aspect_type, expected_orb in REFERENCE_ASPECTS:
        found = actual_among_reference.get((planet1, planet2))
        tolerance = (
            NODE_ASPECT_ORB_TOLERANCE_DEG if 'NorthNode' in (planet1, planet2) else ASPECT_ORB_TOLERANCE_DEG
        )
        if found is None:
            print(f"  {planet1:<10} {planet2:<10} {aspect_type:<12} {expected_orb:<10.3f} {'—':<10} MISSING")
        else:
            diff = abs(found['orb'] - expected_orb)
            ok = found['aspect'] == aspect_type and diff <= tolerance
            print(f"  {planet1:<10} {planet2:<10} {aspect_type:<12} {expected_orb:<10.3f} "
                  f"{found['orb']:<10.3f} {'OK' if ok else 'MISMATCH'}")

        assert found is not None, f"{planet1}-{planet2} {aspect_type}: expected but not found in calculate_aspects output"
        assert found['aspect'] == aspect_type, (
            f"{planet1}-{planet2}: expected {aspect_type}, got {found['aspect']}"
        )
        assert abs(found['orb'] - expected_orb) <= tolerance, (
            f"{planet1}-{planet2} {aspect_type}: expected orb {expected_orb:.3f}°, "
            f"got {found['orb']:.3f}° (diff {abs(found['orb'] - expected_orb):.3f}° > tolerance {tolerance}°)"
        )

    unexpected = set(actual_among_reference.keys()) - {(p1, p2) for p1, p2, _, _ in REFERENCE_ASPECTS}
    print(f"  Unexpected extra aspects among {len(reference_bodies)} bodies: {unexpected or 'none'}")
    assert not unexpected, f"Unexpected extra aspects among reference bodies: {unexpected}"
