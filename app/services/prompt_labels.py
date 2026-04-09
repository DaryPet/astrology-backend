"""Языковые метки для построения промптов"""

PROMPT_LABELS = {
    'ru': {
        'query': '=== ЗАПРОС ПОЛЬЗОВАТЕЛЯ ===',
        'natal_chart': '=== НАТАЛЬНАЯ КАРТА ===',
        'planet_data': '=== ДАННЫЕ ПЛАНЕТЫ ===',
        'found_fragments': '=== НАЙДЕННЫЕ ФРАГМЕНТЫ ИЗ КНИГ ===',
        'analysis': '=== АНАЛИЗ ===',
        
        'planets_in_houses': 'Планеты в домах:',
        'house_cusps': 'Куспиды домов:',
        'planet': 'Планета',
        'sign': 'Знак',
        'degree': 'Градус',
        'house': 'Дом',
        'house_sign': 'Знак на куспиде дома',
        'motion': 'Движение',
        'retrograde': 'Ретроградная (Rx)',
        'direct': 'Директная (D)',
        'planet_aspects': 'Аспекты планеты:',
        'fragment': 'Фрагмент',
        'please_analyze': 'Пожалуйста, дайте подробный анализ.',
        'please_analyze_planet': 'Пожалуйста, дайте подробный анализ этой планеты.',
        'natal_chart_label': 'НАТАЛЬНАЯ КАРТА',
        'planets': 'ПЛАНЕТЫ',
        'houses': 'ДОМА',
        'house_num': 'Дом',
        'pars_fortuna': 'Pars Fortuna',
    },
    
    'en': {
        'query': '=== USER QUERY ===',
        'natal_chart': '=== NATAL CHART ===',
        'planet_data': '=== PLANET DATA ===',
        'found_fragments': '=== FOUND BOOK FRAGMENTS ===',
        'analysis': '=== ANALYSIS ===',
        
        'planets_in_houses': 'Planets in houses:',
        'house_cusps': 'House cusps:',
        'planet': 'Planet',
        'sign': 'Sign',
        'degree': 'Degree',
        'house': 'House',
        'house_sign': 'House sign',
        'motion': 'Motion',
        'retrograde': 'Retrograde (Rx)',
        'direct': 'Direct (D)',
        'planet_aspects': 'Planet aspects:',
        'fragment': 'Fragment',
        'please_analyze': 'Please provide detailed analysis.',
        'please_analyze_planet': 'Please provide detailed analysis of this planet.',
        'natal_chart_label': 'NATAL CHART',
        'planets': 'PLANETS',
        'houses': 'HOUSES',
        'house_num': 'House',
        'pars_fortuna': 'Pars Fortuna',
    },
}


def get_labels(language: str):
    """Получить метки для нужного языка с fallback на английский"""
    return PROMPT_LABELS.get(language, PROMPT_LABELS['en'])
