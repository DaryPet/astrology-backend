"""System prompts for LLM — package split by astrological domain, all languages per file.

Was a single 905-line prompt_templates.py + 513-line prompt_templates_simple.py.
Rationale for the split (per-domain files, all languages kept together within
each) is in openspec/changes/add-ukrainian-language/plan.md.
"""
from app.services.prompt_templates.registry import get_template, get_simple_template
from app.services.prompt_templates.synastry import get_relationship_context_prompt

__all__ = ["get_template", "get_simple_template", "get_relationship_context_prompt"]
