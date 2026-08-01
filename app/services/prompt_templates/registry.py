"""Template lookup: resolves (name, language, mode) to the actual prompt text."""
from app.services.prompt_templates.natal import (
    ANALYSIS_PROMPTS, ANALYSIS_PROMPTS_SIMPLE,
    PLANET_PROMPTS, PLANET_PROMPTS_SIMPLE,
    SYNTHESIS_PROMPTS, SYNTHESIS_PROMPTS_SIMPLE,
)
from app.services.prompt_templates.synastry import (
    SYNASTRY_PROMPTS, SYNASTRY_PROMPTS_SIMPLE,
    SYNASTRY_ASPECT_PROMPTS, SYNASTRY_ASPECT_PROMPTS_SIMPLE,
)
from app.services.prompt_templates.progressions import (
    PROGRESSIONS_PROMPTS, PROGRESSIONS_PROMPTS_SIMPLE,
)
from app.services.prompt_templates.transits import (
    TRANSITS_PROMPTS, TRANSITS_PROMPTS_SIMPLE,
)
from app.services.prompt_templates.progressed_synastry import (
    PROGRESSED_SYNASTRY_PROMPTS, PROGRESSED_SYNASTRY_PROMPTS_SIMPLE,
)


def get_simple_template(name: str, language: str) -> str:
    """Получить простой промпт по имени"""
    templates = {
        'analysis': ANALYSIS_PROMPTS_SIMPLE,
        'planet': PLANET_PROMPTS_SIMPLE,
        'synthesis': SYNTHESIS_PROMPTS_SIMPLE,
        'synastry': SYNASTRY_PROMPTS_SIMPLE,
        'synastry_aspect': SYNASTRY_ASPECT_PROMPTS_SIMPLE,
        'progressions': PROGRESSIONS_PROMPTS_SIMPLE,
        'transits': TRANSITS_PROMPTS_SIMPLE,
        'progressed_synastry': PROGRESSED_SYNASTRY_PROMPTS_SIMPLE,
    }
    prompts = templates.get(name, ANALYSIS_PROMPTS_SIMPLE)
    return prompts.get(language, prompts['en'])


def get_template(name: str, language: str, mode: str = 'advanced') -> str:
    if mode == 'simple':
        return get_simple_template(name, language)
    templates = {
        'analysis': ANALYSIS_PROMPTS,
        'planet': PLANET_PROMPTS,
        'synthesis': SYNTHESIS_PROMPTS,
        'synastry': SYNASTRY_PROMPTS,
        'synastry_aspect': SYNASTRY_ASPECT_PROMPTS,
        'progressions': PROGRESSIONS_PROMPTS,
        'transits': TRANSITS_PROMPTS,
        'progressed_synastry': PROGRESSED_SYNASTRY_PROMPTS,
    }
    prompts = templates.get(name, ANALYSIS_PROMPTS)
    return prompts.get(language, prompts['en'])
