import re
from typing import List, Dict, Any, AsyncGenerator, Callable, Awaitable
from app.services.prompt_templates.languages import normalize_language
from app.services.text_verification import (
    PLANET_RU,
    PLANET_EN,
    PLANET_UK,
)


PLANET_TO_BOOK_ID = {
    "Pluto": 8,
    "Saturn": 20,
    "Neptune": 7,
    "North Node": 6,
    "South Node": 6,
}

# House ordinal words for RAG queries (used in full_chart_analysis_v2 and progressions_analysis)
HOUSE_WORDS = {
    1: "first", 2: "second", 3: "third", 4: "fourth",
    5: "fifth", 6: "sixth", 7: "seventh", 8: "eighth",
    9: "ninth", 10: "tenth", 11: "eleventh", 12: "twelfth"
}

def _planet_display(planet_name: str, language: str) -> str:
    """PLANET_RU/PLANET_UK/PLANET_EN lookup by language, 3-way replacement for
    the old `PLANET_RU.get(x) if is_ru else PLANET_EN.get(x)` binary pattern."""
    lang = normalize_language(language)
    table = {'ru': PLANET_RU, 'uk': PLANET_UK, 'en': PLANET_EN}[lang]
    return table.get(planet_name, planet_name)

def _lang_key(base: str, language: str) -> str:
    """'sign' -> 'sign_ru'/'sign_uk'/'sign' depending on language — 3-way
    replacement for the old `f"{base}_ru" if is_ru else base` binary pattern."""
    lang = normalize_language(language)
    return base if lang == 'en' else f"{base}_{lang}"

def _localized(d: dict, key: str, language: str, default=None):
    """d.get(key_ru/key_uk/key) based on language — 3-way replacement for the
    old `d.get(key_ru if is_ru else key, default)` binary pattern."""
    return d.get(_lang_key(key, language), d.get(key, default))

def _localized2(d1: dict, d2: dict, key: str, language: str, default=None):
    """Same as _localized but tries d1 then d2 at the SAME localized key
    before falling back to default — matches the old cascading pattern
    `d1.get(key_ru if is_ru else key, d2.get(key_ru if is_ru else key, default))`."""
    k = _lang_key(key, language)
    return d1.get(k, d2.get(k, default))



# Priority books for the predictive methods (id from the books table):
# 29 — "Predictive Astrology: The Eagle and the Lark" (Bernadette Brady) — progressions
# 28 — "Planets in Transit: Life Cycles for Living" (Robert Hand) — transits
PROGRESSIONS_PRIORITY_BOOK_ID = 29
TRANSITS_PRIORITY_BOOK_ID = 28

# User decision (2026-08-02): narrow the RAG for the natal chart (all
# languages) from searching the whole library (~8 books, some of which are
# specialized for OTHER methods — 26 synastry, 28/29 transits/progressions)
# down to a fixed list of relevant books. 22 is the main source (highest
# priority), 25 and 23 supplement it.
NATAL_BOOK_IDS = [22, 25, 23]

# Transits and progressions — same principle: a fixed list instead of "one
# priority book + the entire rest of the catalog" (what search_chunks_priority_book
# used to do). Both methods use the same narrow set (28, 29), rather than
# different priority books each.
TRANSITS_PROGRESSIONS_BOOK_IDS = [28, 29]

# Book 28 (Hand, "Planets in Transit") is transit-only; book 29 (Brady,
# "Predictive Astrology") covers BOTH transits and progressions in the same
# book — so filtering by book_id alone can't separate the techniques (a
# progressions search can still surface a purely-transit passage from book
# 29 itself). Real case that exposed this: a progressions request retrieved
# book 28's "Pluto transiting conjunct natal Pluto... does not happen except
# possibly right after birth" — the LLM then fabricated a "progressed Pluto
# return" from it, misapplying transit content to a different technique.
# 2026-08-30.
_TRANSIT_MARKERS = re.compile(r'\btransit(?:ing|s)?\b', re.I)
_PROGRESSION_MARKERS = re.compile(r'\bprogress(?:ed|ion|ions)?\b', re.I)


def _matches_technique(chunk_text: str, technique: str) -> bool:
    """
    Chunk-level filter, not book-level: drops a chunk only when it
    unambiguously discusses the OTHER technique and never mentions this one
    at all. A chunk that mentions both (many predictive-astrology books
    compare the two techniques in the same passage) still passes — this is
    deliberately soft, not a hard require-the-right-keyword filter, to avoid
    dropping genuinely relevant fragments that happen to use both words.
    technique: 'transit' or 'progression'; anything else passes everything.
    """
    has_transit = bool(_TRANSIT_MARKERS.search(chunk_text))
    has_progression = bool(_PROGRESSION_MARKERS.search(chunk_text))
    if technique == 'progression':
        return not (has_transit and not has_progression)
    if technique == 'transit':
        return not (has_progression and not has_transit)
    return True

async def _fetch_book_titles(book_ids: List[int]) -> Dict[int, str]:
    """
    Book titles by id list — one request for the whole analysis (natal/
    transits/progressions), not one per RAG sub-request for each planet/aspect,
    as was the case in search_chunks_all_books/search_chunks_priority_book
    (there the books table was queried again on every call).
    """
    from supabase import create_client
    from app.core.config import settings
    from app.services.supabase_async import run_sync_in_thread

    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        table_call = supabase.table("books").select("id, title").in_("id", book_ids)
        response = await run_sync_in_thread(table_call.execute)
        return {b["id"]: b.get("title", "") for b in (response.data or [])}
    except Exception as e:
        print(f"[_fetch_book_titles] Error: {e}")
        return {}

async def search_chunks_by_book_ids(
    query: str,
    book_ids: List[int],
    book_titles: Dict[int, str],
    top_k_per_book: int = 3,
) -> List[Dict[str, Any]]:
    """
    RAG search restricted to a specific fixed list of books — not the whole
    library (search_chunks_all_books) and not "one priority book + the entire
    rest of the catalog" (search_chunks_priority_book). One parallel
    search_chunks_hybrid call per book in book_ids; book titles are passed in
    already resolved via book_titles (see _fetch_book_titles) — not requeried
    here on every sub-request.
    """
    import asyncio as _asyncio
    from app.services.search_service import search_chunks_hybrid, generate_embedding

    # Same query string goes to every book below — compute the embedding once
    # instead of letting each search_chunks_hybrid recompute it independently.
    query_embedding = generate_embedding(query)
    results = await _asyncio.gather(
        *[
            search_chunks_hybrid(
                query, top_k=top_k_per_book, book_id=bid, query_embedding=query_embedding
            )
            for bid in book_ids
        ],
        return_exceptions=True,
    )
    unique: List[Dict[str, Any]] = []
    seen = set()
    for r in results:
        if isinstance(r, Exception):
            print(f"[search_chunks_by_book_ids] Error: {r}")
            continue
        for chunk in (r or []):
            c_id = chunk.get("id")
            if c_id and c_id in seen:
                continue
            if c_id:
                seen.add(c_id)
            chunk["book_title"] = book_titles.get(chunk.get("book_id"), "")
            unique.append(chunk)
    return unique

async def search_chunks_priority_book(
    query: str,
    priority_book_id: int,
    top_k_priority: int = 4,
    top_k_others: int = 4,
) -> List[Dict[str, Any]]:
    """
    RAG with a priority book: first the chunks from the method's dedicated
    book (book_id filter), then supplemented from the remaining books.
    Priority ones come first.
    """
    import asyncio as _asyncio
    from supabase import create_client
    from app.core.config import settings
    from app.services.search_service import search_chunks_hybrid
    from app.services.supabase_async import run_sync_in_thread

    try:
        priority_task = search_chunks_hybrid(query, top_k=top_k_priority, book_id=priority_book_id)
        others_task = search_chunks_hybrid(query, top_k=top_k_others)
        priority_chunks, other_chunks = await _asyncio.gather(priority_task, others_task)

        # Book titles
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)
        table_call = supabase.table("books").select("id, title")
        books_response = await run_sync_in_thread(table_call.execute)
        book_map = {b["id"]: b.get("title", "") for b in (books_response.data or [])}

        # Priority ones first, then the rest; dedup by chunk id
        unique: List[Dict[str, Any]] = []
        seen = set()
        for chunk in (priority_chunks or []) + (other_chunks or []):
            c_id = chunk.get("id")
            if c_id and c_id in seen:
                continue
            if c_id:
                seen.add(c_id)
            chunk["book_title"] = book_map.get(chunk.get("book_id", ""), "")
            unique.append(chunk)

        n_priority = len(priority_chunks or [])
        print(f"[priority_book_search] book {priority_book_id}: {n_priority} priority + {len(unique) - n_priority} others")
        return unique
    except Exception as e:
        print(f"[priority_book_search] Error: {e}")
        return []

async def search_chunks_all_books(
    query: str,
    top_k_per_book: int = 3
) -> List[Dict[str, Any]]:
    """
    [v2] Hybrid RAG: ONE request across all books at once.
    Eliminates the problem of multiple RPC calls.
    """
    from supabase import create_client
    from app.core.config import settings
    from app.services.search_service import search_chunks_hybrid
    from app.services.supabase_async import run_sync_in_thread

    try:
        supabase = create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)

        # 1. Get the list of books to map titles
        # Wrap the sync call in an async executor so it doesn't block the event loop
        table_call = supabase.table("books").select("id, title")
        books_response = await run_sync_in_thread(table_call.execute)
        if not books_response.data:
            return []

        book_map = {b["id"]: b.get("title", "") for b in books_response.data}
        total_books = len(books_response.data)

        # 2. ONE request with no book_id filter.
        # Request more chunks to cover all the books
        chunks = await search_chunks_hybrid(
            query,
            top_k=top_k_per_book * total_books
        )

        # 3. Add the book titles
        if chunks:
            for chunk in chunks:
                chunk["book_title"] = book_map.get(chunk.get("book_id", ""), "")

        # Remove duplicates
        unique_chunks = []
        seen_ids = set()
        for chunk in chunks:
            c_id = chunk.get("id")
            if c_id and c_id not in seen_ids:
                seen_ids.add(c_id)
                unique_chunks.append(chunk)
        
        print(f"[search_chunks_all_books] Total unique chunks: {len(unique_chunks)} from {total_books} books")
        return unique_chunks

    except Exception as e:
        print(f"[search_chunks_all_books] Error: {e}")
        return []

async def stream_verified_analysis(
    adapter,
    prompt: str,
    language: str,
    fix_fn: Callable[[str], "tuple[str, List[str]]"],
    finalize: Callable[[str, str], Awaitable[Dict[str, Any]]],
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Generic "verified buffer" streaming wrapper
    (plans/streaming-analysis-backend.md, step 2б) — reusable for any analysis
    built on "one generate() call -> fix -> detect checks" (natal, synastry,
    progressions, transits, progressed synastry — see
    plans/streaming-rollout-synastry-progressions-transits.md, step 0). Each
    caller passes its own `fix_fn` (bound to whatever the real fix function
    needs beyond text — layers/chart1_data/chart2_data/language, via a
    closure) and its own `finalize`.

    Reads raw tokens from adapter.generate_stream, buffers them, and only
    releases text once a paragraph boundary ("\\n\\n") closes: the anti-
    fabrication regexes never match across a blank line, so paragraph-by-
    paragraph correction can't diverge from running the same fix over the
    whole text at once. Yields event dicts — {"event": "delta"|"error", "data":
    {...}} — then exactly one {"event": "final", "data": <finalize(...)>}.

    Invariants (do not change without re-reading the plan's "Риски" table):
    - Release only on "\\n\\n" — a sentence-level cut can land inside a
      correction or a layer-marker word.
    - fix_fn reruns over the WHOLE accumulated buffer up to the cut, never
      just the new paragraph — needed so a layer marker from an earlier
      paragraph still attributes a later fabricated position correctly
      (matters for progressions/transits' two-layer fix; harmless no-op for
      natal's single layer).
    - safe_mode: if a corrected prefix ever stops matching what was already
      released (should not happen by construction), stop releasing — nothing
      already shown to the user is ever rewritten. The remainder ships once,
      whole, inside `final`.
    """
    released = ""
    buffer = ""
    last_cut = 0
    safe_mode = False

    async for chunk in adapter.generate_stream(prompt, language):
        if buffer == "" and chunk.startswith("Error: "):
            yield {"event": "error", "data": {"detail": chunk[len("Error: "):]}}
            return

        buffer += chunk
        if safe_mode:
            continue

        cut = buffer.rfind("\n\n")
        if cut <= last_cut:
            continue

        if language in ('ru', 'en', 'uk'):
            corrected, _unresolved = fix_fn(buffer[:cut])
        else:
            # Same gate as every non-stream pipeline: unsupported languages get
            # no fabrication checking there either, so raw deltas are correct
            # here too, not a shortcut.
            corrected = buffer[:cut]

        if not corrected.startswith(released):
            # Rare anomaly — the fix touched already-released text. Stop
            # releasing; the whole corrected text still reaches the user via
            # `final`, just not incrementally.
            safe_mode = True
            continue

        delta = corrected[len(released):]
        released = corrected
        last_cut = cut
        if delta:
            yield {"event": "delta", "data": {"text": delta}}

    result = await finalize(buffer, released)
    yield {"event": "final", "data": result}

async def stream_chat_reply(
    adapter,
    messages: List[Dict[str, str]],
    language: str,
    finalize: Callable[[str], Awaitable[Dict[str, Any]]],
) -> AsyncGenerator[Dict[str, Any], None]:
    """
    Simpler chat-format cousin of stream_verified_analysis (above): chat
    replies (chat_with_astrologer/chat_with_synastry_astrologer) never run
    an anti-fabrication fix pass on their output today — unlike the
    full-analysis endpoints, there's no fix_fn here and therefore no need to
    buffer up to a paragraph boundary before releasing; tokens are relayed
    to the client as soon as they arrive. Yields {"event": "delta", "data":
    {"text": ...}} chunks as raw adapter output, then exactly one
    {"event": "final", "data": <finalize(buffer)>}. An "Error: "-prefixed
    first chunk (same adapter convention stream_verified_analysis relies on)
    is surfaced as {"event": "error"} instead of being streamed as text.
    """
    buffer = ""
    async for chunk in adapter.generate_stream_with_messages(messages, language):
        if buffer == "" and chunk.startswith("Error: "):
            yield {"event": "error", "data": {"detail": chunk[len("Error: "):]}}
            return
        buffer += chunk
        yield {"event": "delta", "data": {"text": chunk}}

    result = await finalize(buffer)
    yield {"event": "final", "data": result}

def dedup_chunk_sections(
    sections: List[tuple]
) -> List[tuple]:
    """Removes chunks whose id already appeared in an earlier section,
    preserving section order and each chunk's position within its section.
    First appearance of a chunk id wins; later sections lose the repeat.

    Dedup is by chunk id only (not text) — two different chunks with
    coincidentally similar text are not collapsed. `dedup_chunk_sections`
    does NOT drop the search itself (every RAG call still runs, every
    section still gets its own targeted query) — it only removes the same
    chunk being pasted into the prompt more than once.
    See app/services/specs/progressed_synastry_rag_prompt_reduction_plan.md
    and app/services/specs/rag_chunk_dedup_plan.md (same design, this is the
    5th consumer).
    """
    seen: set = set()
    result: List[tuple] = []
    for label, chunks in sections:
        unique_chunks = []
        for chunk in chunks:
            c_id = chunk.get("id")
            if c_id and c_id in seen:
                continue
            if c_id:
                seen.add(c_id)
            unique_chunks.append(chunk)
        result.append((label, unique_chunks))
    return result
