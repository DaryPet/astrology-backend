"""Shared language-resolution helper for prompt templates and labels.

Single point of truth for "unknown language -> fallback" instead of the
`prompts.get(language, prompts['en'])` / `language == 'ru'` checks scattered
across the codebase. See openspec/changes/add-ukrainian-language/plan.md.
"""
from typing import Optional

SUPPORTED_LANGUAGES = ("ru", "en", "uk")
DEFAULT_LANGUAGE = "en"


def normalize_language(language: Optional[str]) -> str:
    return language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
