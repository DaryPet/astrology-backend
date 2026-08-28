"""Tests for the anti-fabrication checks in app/services/text_verification.py:
level 1 (planet sign), level 2 (aspect type) and level 3 (aspect coverage)."""
from app.services.text_verification import (
    find_fabricated_positions_layered,
    fix_fabricated_positions_layered,
    find_fabricated_aspect_types_single,
    find_undercovered_aspects_generic,
)


def test_find_fabricated_positions_single_layer_no_marker_needed():
    """A wrong sign is caught even with a single layer and no marker word in the text."""
    layers = {'natal': {'planets': {'Moon': {'sign_ru': 'Рак'}}}}
    text = "Луна в Овне указывает на эмоциональную сдержанность."
    print(f"\n  REAL Moon sign: Cancer (Рак) | LLM TEXT: {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='ru')
    print(f"  FLAGGED as fabricated: {result['fabricated']}")

    assert any('Овне' in item for item in result['fabricated'])
    assert result['layer_confused'] == []


def test_fix_fabricated_positions_single_layer_autocorrects():
    """A wrong sign in a single-layer chart is corrected in place."""
    layers = {'natal': {'planets': {'Moon': {'sign_ru': 'Рак'}}}}
    text = "Луна в Овне указывает на эмоциональную сдержанность."
    print(f"\n  REAL Moon sign: Cancer (Рак) | TEXT BEFORE fix: {text!r}")

    fixed_text, unresolved = fix_fabricated_positions_layered(text, layers, language='ru')
    print(f"  TEXT AFTER fix: {fixed_text!r}")
    print(f"  Unresolved: {unresolved}")

    assert 'Раке' in fixed_text
    assert 'Овне' not in fixed_text
    assert unresolved == []


def test_find_fabricated_positions_four_layers_no_cross_contamination():
    """Four layers each keep their own valid sign for the same planet."""
    layers = {
        'p1_progressed': {'planets': {'Moon': {'sign_ru': 'Телец'}}},
        'p2_progressed': {'planets': {'Moon': {'sign_ru': 'Лев'}}},
        'p1_natal': {'planets': {'Moon': {'sign_ru': 'Дева'}}},
        'p2_natal': {'planets': {'Moon': {'sign_ru': 'Скорпион'}}},
    }
    text = (
        "Прогрессивная Луна в Тельце показывает рост уверенности. "
        "Прогрессивная Луна в Льве добавляет яркости. "
        "Натальная Луна в Деве отвечает за практичность. "
        "Натальная Луна в Скорпионе усиливает интуицию."
    )
    print(f"\n  4 REAL Moon signs: {[ (k, v['planets']['Moon']['sign_ru']) for k, v in layers.items() ]}")
    print(f"  CORRECT text (all 4 signs match): {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='ru')
    print(f"  FLAGGED in correct text (should be empty): {result['fabricated']}")
    assert result['fabricated'] == []

    bad_text = "Натальная Луна в Раке."
    print(f"  BROKEN text (Рак/Cancer is in none of the 4 layers): {bad_text!r}")
    bad_result = find_fabricated_positions_layered(bad_text, layers, language='ru')
    print(f"  FLAGGED in broken text: {bad_result['fabricated']}")
    assert any('Раке' in item for item in bad_result['fabricated'])


def test_find_fabricated_positions_correct_text_no_false_positive():
    """Text that matches the real data is never flagged."""
    layers = {'natal': {'planets': {'Moon': {'sign_ru': 'Рак'}}}}
    text = "Луна в Раке подчеркивает глубокую эмоциональность натальной карты."
    print(f"\n  REAL Moon sign: Cancer (Рак) | LLM TEXT (correct): {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='ru')
    print(f"  RESULT (should be empty — text is correct): {result}")

    assert result == {'fabricated': [], 'layer_confused': []}


def test_find_fabricated_aspect_types_single_detects_wrong_type():
    """A wrong aspect type in a bold heading is detected (detection only, no auto-fix)."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_ru': 'Соединение'}]
    text = "**Солнце в оппозиции с Луной**\nЭтот аспект говорит о внутреннем напряжении."
    print(f"\n  REAL aspect: Sun-Moon = Conjunction (Соединение) | LLM TEXT: {text!r}")

    mismatches = find_fabricated_aspect_types_single(text, aspects, language='ru')
    print(f"  FLAGGED mismatches: {mismatches}")

    assert len(mismatches) == 1
    assert 'Соединение' in mismatches[0]


def test_find_undercovered_aspects_generic_flags_short_paragraph():
    """A paragraph shorter than the coverage threshold counts as undercovered."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_ru': 'Соединение', 'orb': 2.5}]
    full_analysis = "Солнце и Луна в соединении — значимый аспект личности."
    print(f"\n  SHORT paragraph ({len(full_analysis)} chars, threshold 220): {full_analysis!r}")
    assert len(full_analysis) < 220

    missing = find_undercovered_aspects_generic(full_analysis, aspects, language='ru')
    print(f"  FLAGGED as undercovered (should contain this one): {missing}")

    assert len(missing) == 1
    assert 'Соединение' in missing[0]


def test_find_undercovered_aspects_generic_accepts_long_paragraph():
    """A paragraph at/above the threshold with no cop-out phrase is not flagged."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_ru': 'Соединение', 'orb': 2.5}]
    long_paragraph = (
        "Солнце в соединении с Луной формирует один из самых цельных и мощных "
        "аспектов натальной карты: сознательная воля и эмоциональная природа "
        "действуют как единое целое, без внутреннего конфликта между тем, чего "
        "человек хочет, и тем, что он на самом деле чувствует в течение жизни."
    )
    print(f"\n  LONG paragraph ({len(long_paragraph)} chars, threshold 220): {long_paragraph!r}")
    assert len(long_paragraph) >= 220

    missing = find_undercovered_aspects_generic(long_paragraph, aspects, language='ru')
    print(f"  FLAGGED as undercovered (should be empty): {missing}")

    assert missing == []


def test_find_fabricated_positions_single_layer_no_marker_needed_en():
    """EN: a wrong sign is caught even with a single layer and no marker word in the text."""
    layers = {'natal': {'planets': {'Moon': {'sign': 'Cancer'}}}}
    text = "Moon in Aries points to emotional restraint."
    print(f"\n  REAL Moon sign: Cancer | LLM TEXT: {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='en')
    print(f"  FLAGGED as fabricated: {result['fabricated']}")

    assert any('Aries' in item for item in result['fabricated'])
    assert result['layer_confused'] == []


def test_fix_fabricated_positions_single_layer_autocorrects_en():
    """EN: a wrong sign in a single-layer chart is corrected in place."""
    layers = {'natal': {'planets': {'Moon': {'sign': 'Cancer'}}}}
    text = "Moon in Aries points to emotional restraint."
    print(f"\n  REAL Moon sign: Cancer | TEXT BEFORE fix: {text!r}")

    fixed_text, unresolved = fix_fabricated_positions_layered(text, layers, language='en')
    print(f"  TEXT AFTER fix: {fixed_text!r}")
    print(f"  Unresolved: {unresolved}")

    assert 'Cancer' in fixed_text
    assert 'Aries' not in fixed_text
    assert unresolved == []


def test_find_fabricated_positions_four_layers_no_cross_contamination_en():
    """EN: four layers each keep their own valid sign for the same planet."""
    layers = {
        'p1_progressed': {'planets': {'Moon': {'sign': 'Taurus'}}},
        'p2_progressed': {'planets': {'Moon': {'sign': 'Leo'}}},
        'p1_natal': {'planets': {'Moon': {'sign': 'Virgo'}}},
        'p2_natal': {'planets': {'Moon': {'sign': 'Scorpio'}}},
    }
    text = (
        "Progressed Moon in Taurus shows growing confidence. "
        "Progressed Moon in Leo adds vibrance. "
        "Natal Moon in Virgo supports practicality. "
        "Natal Moon in Scorpio deepens intuition."
    )
    print(f"\n  4 REAL Moon signs: {[ (k, v['planets']['Moon']['sign']) for k, v in layers.items() ]}")
    print(f"  CORRECT text (all 4 signs match): {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='en')
    print(f"  FLAGGED in correct text (should be empty): {result['fabricated']}")
    assert result['fabricated'] == []

    bad_text = "Natal Moon in Cancer."
    print(f"  BROKEN text (Cancer is in none of the 4 layers): {bad_text!r}")
    bad_result = find_fabricated_positions_layered(bad_text, layers, language='en')
    print(f"  FLAGGED in broken text: {bad_result['fabricated']}")
    assert any('Cancer' in item for item in bad_result['fabricated'])


def test_find_fabricated_positions_correct_text_no_false_positive_en():
    """EN: text that matches the real data is never flagged."""
    layers = {'natal': {'planets': {'Moon': {'sign': 'Cancer'}}}}
    text = "Moon in Cancer highlights the deep emotionality of the natal chart."
    print(f"\n  REAL Moon sign: Cancer | LLM TEXT (correct): {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='en')
    print(f"  RESULT (should be empty — text is correct): {result}")

    assert result == {'fabricated': [], 'layer_confused': []}


def test_find_fabricated_aspect_types_single_detects_wrong_type_en():
    """EN: a wrong aspect type in a bold heading is detected (detection only, no auto-fix)."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction'}]
    text = "**Sun Opposition Moon**\nThis aspect points to inner tension."
    print(f"\n  REAL aspect: Sun-Moon = Conjunction | LLM TEXT: {text!r}")

    mismatches = find_fabricated_aspect_types_single(text, aspects, language='en')
    print(f"  FLAGGED mismatches: {mismatches}")

    assert len(mismatches) == 1
    assert 'Conjunction' in mismatches[0]


def test_find_undercovered_aspects_generic_flags_short_paragraph_en():
    """EN: a paragraph shorter than the coverage threshold counts as undercovered."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'orb': 2.5}]
    full_analysis = "Sun and Moon in conjunction — a defining aspect of the personality."
    print(f"\n  SHORT paragraph ({len(full_analysis)} chars, threshold 220): {full_analysis!r}")
    assert len(full_analysis) < 220

    missing = find_undercovered_aspects_generic(full_analysis, aspects, language='en')
    print(f"  FLAGGED as undercovered (should contain this one): {missing}")

    assert len(missing) == 1
    assert 'Conjunction' in missing[0]


def test_find_undercovered_aspects_generic_accepts_long_paragraph_en():
    """EN: a paragraph at/above the threshold with no cop-out phrase is not flagged."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'orb': 2.5}]
    long_paragraph = (
        "Sun conjunct Moon forms one of the most unified and powerful aspects "
        "of the natal chart: the conscious will and the emotional nature act "
        "as a single whole, without inner conflict between what a person "
        "wants and what they actually feel throughout their life."
    )
    print(f"\n  LONG paragraph ({len(long_paragraph)} chars, threshold 220): {long_paragraph!r}")
    assert len(long_paragraph) >= 220

    missing = find_undercovered_aspects_generic(long_paragraph, aspects, language='en')
    print(f"  FLAGGED as undercovered (should be empty): {missing}")

    assert missing == []


def test_find_fabricated_positions_single_layer_no_marker_needed_uk():
    """UK: a wrong sign is caught even with a single layer and no marker word in the text."""
    layers = {'natal': {'planets': {'Moon': {'sign_uk': 'Рак'}}}}
    text = "Місяць у Овні вказує на емоційну стриманість."
    print(f"\n  REAL Moon sign: Cancer (Рак) | LLM TEXT: {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='uk')
    print(f"  FLAGGED as fabricated: {result['fabricated']}")

    assert any('Овні' in item for item in result['fabricated'])
    assert result['layer_confused'] == []


def test_fix_fabricated_positions_single_layer_autocorrects_uk():
    """UK: a wrong sign in a single-layer chart is corrected in place."""
    layers = {'natal': {'planets': {'Moon': {'sign_uk': 'Рак'}}}}
    text = "Місяць у Овні вказує на емоційну стриманість."
    print(f"\n  REAL Moon sign: Cancer (Рак) | TEXT BEFORE fix: {text!r}")

    fixed_text, unresolved = fix_fabricated_positions_layered(text, layers, language='uk')
    print(f"  TEXT AFTER fix: {fixed_text!r}")
    print(f"  Unresolved: {unresolved}")

    assert 'Раку' in fixed_text
    assert 'Овні' not in fixed_text
    assert unresolved == []


def test_find_fabricated_positions_four_layers_no_cross_contamination_uk():
    """UK: four layers each keep their own valid sign for the same planet."""
    layers = {
        'p1_progressed': {'planets': {'Moon': {'sign_uk': 'Телець'}}},
        'p2_progressed': {'planets': {'Moon': {'sign_uk': 'Лев'}}},
        'p1_natal': {'planets': {'Moon': {'sign_uk': 'Діва'}}},
        'p2_natal': {'planets': {'Moon': {'sign_uk': 'Скорпіон'}}},
    }
    text = (
        "Прогресивний Місяць у Тельці показує зростання впевненості. "
        "Прогресивний Місяць у Леві додає яскравості. "
        "Натальний Місяць у Діві підтримує практичність. "
        "Натальний Місяць у Скорпіоні поглиблює інтуїцію."
    )
    print(f"\n  4 REAL Moon signs: {[ (k, v['planets']['Moon']['sign_uk']) for k, v in layers.items() ]}")
    print(f"  CORRECT text (all 4 signs match): {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='uk')
    print(f"  FLAGGED in correct text (should be empty): {result['fabricated']}")
    assert result['fabricated'] == []

    bad_text = "Натальний Місяць у Раку."
    print(f"  BROKEN text (Рак/Cancer is in none of the 4 layers): {bad_text!r}")
    bad_result = find_fabricated_positions_layered(bad_text, layers, language='uk')
    print(f"  FLAGGED in broken text: {bad_result['fabricated']}")
    assert any('Раку' in item for item in bad_result['fabricated'])


def test_find_fabricated_positions_correct_text_no_false_positive_uk():
    """UK: text that matches the real data is never flagged."""
    layers = {'natal': {'planets': {'Moon': {'sign_uk': 'Рак'}}}}
    text = "Місяць у Раку підкреслює глибоку емоційність натальної карти."
    print(f"\n  REAL Moon sign: Cancer (Рак) | LLM TEXT (correct): {text!r}")

    result = find_fabricated_positions_layered(text, layers, language='uk')
    print(f"  RESULT (should be empty — text is correct): {result}")

    assert result == {'fabricated': [], 'layer_confused': []}


def test_find_fabricated_aspect_types_single_detects_wrong_type_uk():
    """UK: a wrong aspect type in a bold heading is detected (detection only, no auto-fix)."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_uk': "З'єднання"}]
    text = "**Сонце в опозиції з Місяцем**\nЦей аспект говорить про внутрішнє напруження."
    print(f"\n  REAL aspect: Sun-Moon = Conjunction (З'єднання) | LLM TEXT: {text!r}")

    mismatches = find_fabricated_aspect_types_single(text, aspects, language='uk')
    print(f"  FLAGGED mismatches: {mismatches}")

    assert len(mismatches) == 1
    assert "З'єднання" in mismatches[0]


def test_find_undercovered_aspects_generic_flags_short_paragraph_uk():
    """UK: a paragraph shorter than the coverage threshold counts as undercovered."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_uk': "З'єднання", 'orb': 2.5}]
    full_analysis = "Сонце і Місяць у з'єднанні — значущий аспект особистості."
    print(f"\n  SHORT paragraph ({len(full_analysis)} chars, threshold 220): {full_analysis!r}")
    assert len(full_analysis) < 220

    missing = find_undercovered_aspects_generic(full_analysis, aspects, language='uk')
    print(f"  FLAGGED as undercovered (should contain this one): {missing}")

    assert len(missing) == 1
    assert "З'єднання" in missing[0]


def test_find_undercovered_aspects_generic_accepts_long_paragraph_uk():
    """UK: a paragraph at/above the threshold with no cop-out phrase is not flagged."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_uk': "З'єднання", 'orb': 2.5}]
    long_paragraph = (
        "З'єднання Сонця і Місяця формує один із найцілісніших і найпотужніших "
        "аспектів натальної карти: свідома воля та емоційна природа діють як "
        "єдине ціле, без внутрішнього конфлікту між тим, чого людина хоче, і "
        "тим, що вона насправді відчуває протягом усього життя."
    )
    print(f"\n  LONG paragraph ({len(long_paragraph)} chars, threshold 220): {long_paragraph!r}")
    assert len(long_paragraph) >= 220

    missing = find_undercovered_aspects_generic(long_paragraph, aspects, language='uk')
    print(f"  FLAGGED as undercovered (should be empty): {missing}")

    assert missing == []
