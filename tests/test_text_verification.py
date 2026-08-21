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

    result = find_fabricated_positions_layered(text, layers, language='ru')

    assert any('Овне' in item for item in result['fabricated'])
    assert result['layer_confused'] == []


def test_fix_fabricated_positions_single_layer_autocorrects():
    """A wrong sign in a single-layer chart is corrected in place."""
    layers = {'natal': {'planets': {'Moon': {'sign_ru': 'Рак'}}}}
    text = "Луна в Овне указывает на эмоциональную сдержанность."

    fixed_text, unresolved = fix_fabricated_positions_layered(text, layers, language='ru')

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

    result = find_fabricated_positions_layered(text, layers, language='ru')
    assert result['fabricated'] == []

    bad_text = "Натальная Луна в Раке."
    bad_result = find_fabricated_positions_layered(bad_text, layers, language='ru')
    assert any('Раке' in item for item in bad_result['fabricated'])


def test_find_fabricated_positions_correct_text_no_false_positive():
    """Text that matches the real data is never flagged."""
    layers = {'natal': {'planets': {'Moon': {'sign_ru': 'Рак'}}}}
    text = "Луна в Раке подчеркивает глубокую эмоциональность натальной карты."

    result = find_fabricated_positions_layered(text, layers, language='ru')

    assert result == {'fabricated': [], 'layer_confused': []}


def test_find_fabricated_aspect_types_single_detects_wrong_type():
    """A wrong aspect type in a bold heading is detected (detection only, no auto-fix)."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_ru': 'Соединение'}]
    text = "**Солнце в оппозиции с Луной**\nЭтот аспект говорит о внутреннем напряжении."

    mismatches = find_fabricated_aspect_types_single(text, aspects, language='ru')

    assert len(mismatches) == 1
    assert 'Соединение' in mismatches[0]


def test_find_undercovered_aspects_generic_flags_short_paragraph():
    """A paragraph shorter than the coverage threshold counts as undercovered."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_ru': 'Соединение', 'orb': 2.5}]
    full_analysis = "Солнце и Луна в соединении — значимый аспект личности."
    assert len(full_analysis) < 220

    missing = find_undercovered_aspects_generic(full_analysis, aspects, language='ru')

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
    assert len(long_paragraph) >= 220

    missing = find_undercovered_aspects_generic(long_paragraph, aspects, language='ru')

    assert missing == []


def test_find_fabricated_positions_single_layer_no_marker_needed_en():
    """EN: a wrong sign is caught even with a single layer and no marker word in the text."""
    layers = {'natal': {'planets': {'Moon': {'sign': 'Cancer'}}}}
    text = "Moon in Aries points to emotional restraint."

    result = find_fabricated_positions_layered(text, layers, language='en')

    assert any('Aries' in item for item in result['fabricated'])
    assert result['layer_confused'] == []


def test_fix_fabricated_positions_single_layer_autocorrects_en():
    """EN: a wrong sign in a single-layer chart is corrected in place."""
    layers = {'natal': {'planets': {'Moon': {'sign': 'Cancer'}}}}
    text = "Moon in Aries points to emotional restraint."

    fixed_text, unresolved = fix_fabricated_positions_layered(text, layers, language='en')

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

    result = find_fabricated_positions_layered(text, layers, language='en')
    assert result['fabricated'] == []

    bad_text = "Natal Moon in Cancer."
    bad_result = find_fabricated_positions_layered(bad_text, layers, language='en')
    assert any('Cancer' in item for item in bad_result['fabricated'])


def test_find_fabricated_positions_correct_text_no_false_positive_en():
    """EN: text that matches the real data is never flagged."""
    layers = {'natal': {'planets': {'Moon': {'sign': 'Cancer'}}}}
    text = "Moon in Cancer highlights the deep emotionality of the natal chart."

    result = find_fabricated_positions_layered(text, layers, language='en')

    assert result == {'fabricated': [], 'layer_confused': []}


def test_find_fabricated_aspect_types_single_detects_wrong_type_en():
    """EN: a wrong aspect type in a bold heading is detected (detection only, no auto-fix)."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction'}]
    text = "**Sun Opposition Moon**\nThis aspect points to inner tension."

    mismatches = find_fabricated_aspect_types_single(text, aspects, language='en')

    assert len(mismatches) == 1
    assert 'Conjunction' in mismatches[0]


def test_find_undercovered_aspects_generic_flags_short_paragraph_en():
    """EN: a paragraph shorter than the coverage threshold counts as undercovered."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'orb': 2.5}]
    full_analysis = "Sun and Moon in conjunction — a defining aspect of the personality."
    assert len(full_analysis) < 220

    missing = find_undercovered_aspects_generic(full_analysis, aspects, language='en')

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
    assert len(long_paragraph) >= 220

    missing = find_undercovered_aspects_generic(long_paragraph, aspects, language='en')

    assert missing == []


def test_find_fabricated_positions_single_layer_no_marker_needed_uk():
    """UK: a wrong sign is caught even with a single layer and no marker word in the text."""
    layers = {'natal': {'planets': {'Moon': {'sign_uk': 'Рак'}}}}
    text = "Місяць у Овні вказує на емоційну стриманість."

    result = find_fabricated_positions_layered(text, layers, language='uk')

    assert any('Овні' in item for item in result['fabricated'])
    assert result['layer_confused'] == []


def test_fix_fabricated_positions_single_layer_autocorrects_uk():
    """UK: a wrong sign in a single-layer chart is corrected in place."""
    layers = {'natal': {'planets': {'Moon': {'sign_uk': 'Рак'}}}}
    text = "Місяць у Овні вказує на емоційну стриманість."

    fixed_text, unresolved = fix_fabricated_positions_layered(text, layers, language='uk')

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

    result = find_fabricated_positions_layered(text, layers, language='uk')
    assert result['fabricated'] == []

    bad_text = "Натальний Місяць у Раку."
    bad_result = find_fabricated_positions_layered(bad_text, layers, language='uk')
    assert any('Раку' in item for item in bad_result['fabricated'])


def test_find_fabricated_positions_correct_text_no_false_positive_uk():
    """UK: text that matches the real data is never flagged."""
    layers = {'natal': {'planets': {'Moon': {'sign_uk': 'Рак'}}}}
    text = "Місяць у Раку підкреслює глибоку емоційність натальної карти."

    result = find_fabricated_positions_layered(text, layers, language='uk')

    assert result == {'fabricated': [], 'layer_confused': []}


def test_find_fabricated_aspect_types_single_detects_wrong_type_uk():
    """UK: a wrong aspect type in a bold heading is detected (detection only, no auto-fix)."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_uk': "З'єднання"}]
    text = "**Сонце в опозиції з Місяцем**\nЦей аспект говорить про внутрішнє напруження."

    mismatches = find_fabricated_aspect_types_single(text, aspects, language='uk')

    assert len(mismatches) == 1
    assert "З'єднання" in mismatches[0]


def test_find_undercovered_aspects_generic_flags_short_paragraph_uk():
    """UK: a paragraph shorter than the coverage threshold counts as undercovered."""
    aspects = [{'planet1': 'Sun', 'planet2': 'Moon', 'aspect': 'Conjunction', 'aspect_uk': "З'єднання", 'orb': 2.5}]
    full_analysis = "Сонце і Місяць у з'єднанні — значущий аспект особистості."
    assert len(full_analysis) < 220

    missing = find_undercovered_aspects_generic(full_analysis, aspects, language='uk')

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
    assert len(long_paragraph) >= 220

    missing = find_undercovered_aspects_generic(long_paragraph, aspects, language='uk')

    assert missing == []
