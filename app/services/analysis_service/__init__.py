"""
app.services.analysis_service — package re-export shim.

Split from a single 3316-line module into one file per astrological domain
(mirrors the app/services/prompt_templates/ split — see
app/services/INSIGHTS.md, 2026-07-27 Decisions entry, and
plans/analysis-service-split-refactor.md for this split specifically).

This __init__.py re-exports the full original public surface so every
existing `from app.services.analysis_service import X` call site keeps
working unchanged, including the underscore-prefixed helpers that other
modules import directly (_fetch_book_titles, stream_verified_analysis,
stream_chat_reply, search_chunks_priority_book).

get_llm_adapter is re-exported here too even though no code in this package
reads it through this binding anymore (every call site now does its own
local `from app.services.llm_adapter import get_llm_adapter`, same pattern
the original file already used everywhere except 3 call sites — see
app/services/INSIGHTS.md, 2026-08-23 entry). It's kept as an attribute here
purely so `monkeypatch.setattr(app.services.analysis_service, "get_llm_adapter", ...)`
(tests/test_api_llm_routes.py, tests/test_api_functional_flows.py) doesn't
raise AttributeError — patching app.services.llm_adapter.get_llm_adapter
(the origin) is what actually takes effect for every real call site.
"""
from app.services.llm_adapter import get_llm_adapter
from app.services.analysis_service._shared import (
    PLANET_TO_BOOK_ID,
    HOUSE_WORDS,
    _planet_display,
    _lang_key,
    _localized,
    _localized2,
    PROGRESSIONS_PRIORITY_BOOK_ID,
    TRANSITS_PRIORITY_BOOK_ID,
    NATAL_BOOK_IDS,
    TRANSITS_PROGRESSIONS_BOOK_IDS,
    _fetch_book_titles,
    search_chunks_by_book_ids,
    search_chunks_priority_book,
    search_chunks_all_books,
    stream_verified_analysis,
    stream_chat_reply,
    dedup_chunk_sections,
)
from app.services.analysis_service.query import (
    build_analysis_prompt,
    analyze_astrology_query,
    build_planet_analysis_prompt,
    _prepare_planet_analysis,
    analyze_planet,
    analyze_planet_stream,
)
from app.services.analysis_service.natal import (
    _prepare_natal_analysis,
    full_chart_analysis_v2,
    full_chart_analysis_v2_stream,
    get_top_books,
    full_chart_analysis,
)
from app.services.analysis_service.progressions import (
    _prepare_progressions_analysis,
    progressions_analysis,
    progressions_analysis_stream,
)
from app.services.analysis_service.transits import (
    _prepare_transits_analysis,
    transits_analysis,
    transits_analysis_stream,
)
from app.services.analysis_service.progressed_synastry import (
    _collect_progressed_synastry_layers,
    _prepare_progressed_synastry_analysis,
    progressed_synastry_analysis,
    progressed_synastry_analysis_stream,
    _prepare_progressed_synastry_aspect_analysis,
    analyze_progressed_synastry_aspect,
    analyze_progressed_synastry_aspect_stream,
)
from app.services.analysis_service.summary import (
    generate_summary,
)
from app.services.analysis_service.chat import (
    _prepare_chat_with_astrologer,
    chat_with_astrologer,
    chat_with_astrologer_stream,
)
