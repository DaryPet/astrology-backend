"""Computes both natal charts and synastry aspects once and saves them — so
that the old and new variant of full_synastry_analysis_v2 get an IDENTICAL
astrological input (astrology_v2.py hasn't changed between versions, see git
diff fcca162 -- app/utils/). The comparison stays clean: only the
RAG/prompt/LLM layer differs, not the chart calculation.

Also pulls reference book chunks using the same queries the production code
uses (`f"{p1} {asp_type} {p2} synastry"` and
`f"{planet_name} synastry partner"`) — this is the material for the
"matches the book" LLM judge: the judge checks the analysis text against what
is actually in the database for each aspect, instead of guessing.

    python tests/eval_synastry_precompute.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURE = ROOT / "tests" / "data" / "synastry_eval_pair.json"
OUT_DIR = ROOT / "tests" / "reports" / "synastry"
CHART_INPUT_OUT = OUT_DIR / "chart_input.json"
RAG_REFERENCE_OUT = OUT_DIR / "rag_reference.json"

JEFF_GREEN_BOOK_ID = 26  # app/services/synastry_service.py:13


def _parse_chart_req(chart_cfg: dict):
    from datetime import datetime as dt

    birth_date = dt.fromisoformat(chart_cfg["birth_date"])
    return {
        "birth_date": birth_date,
        "birth_place": chart_cfg["birth_place"],
        "lat": chart_cfg["latitude"],
        "lon": chart_cfg["longitude"],
        "timezone_str": chart_cfg["timezone"],
        "house_system": chart_cfg.get("house_system", "Placidus"),
    }


async def main() -> None:
    from app.utils.astrology_v2 import (
        calculate_planet_positions, calculate_aspects, calculate_synastry,
    )
    from app.services.search_service import search_chunks_by_query

    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def build_chart(chart_cfg: dict) -> dict:
        params = _parse_chart_req(chart_cfg)
        chart = calculate_planet_positions(
            birth_date=params["birth_date"],
            birth_place=params["birth_place"],
            lat=params["lat"],
            lon=params["lon"],
            timezone_str=params["timezone_str"],
            house_system=params["house_system"],
        )
        chart["aspects"] = calculate_aspects(chart["planets"])
        return chart

    chart1_data = build_chart(fixture["chart1"])
    chart2_data = build_chart(fixture["chart2"])
    synastry_aspects = calculate_synastry(chart1_data, chart2_data).get("aspects", [])

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "raw").mkdir(parents=True, exist_ok=True)

    chart_input = {
        "chart1_data": chart1_data,
        "chart2_data": chart2_data,
        "aspects": synastry_aspects,
        "overlays": None,
        "language": fixture.get("language", "ru"),
        "top_k_per_book": fixture.get("top_k_per_book", 3),
        "mode": fixture.get("mode", "advanced"),
        "relationship_context": fixture.get("relationship_context"),
    }
    CHART_INPUT_OUT.write_text(
        json.dumps(chart_input, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(f"Wrote {CHART_INPUT_OUT} — {len(synastry_aspects)} synastry aspects")

    # Reference chunks — the same queries full_synastry_analysis_v2 sends
    top_k = chart_input["top_k_per_book"]
    semaphore = asyncio.Semaphore(12)

    async def fetch_aspect(asp: dict) -> dict:
        p1, p2, asp_type = asp.get("planet1", ""), asp.get("planet2", ""), asp.get("aspect", "")
        query = f"{p1} {asp_type} {p2} synastry"
        async with semaphore:
            chunks = await search_chunks_by_query(query, top_k=top_k, book_id=JEFF_GREEN_BOOK_ID)
        return {
            "aspect_label": f"{p1} {asp_type} {p2}",
            "query": query,
            "chunks": [{"book_title": c.get("book_title"), "text": c.get("text", "")} for c in chunks],
        }

    key_planets = ["Pluto", "NorthNode", "SouthNode", "Saturn", "Sun", "Moon", "Ascendant", "Venus", "Mars", "Jupiter"]

    async def fetch_planet(planet_name: str) -> dict:
        query = f"{planet_name} synastry partner"
        async with semaphore:
            chunks = await search_chunks_by_query(query, top_k=top_k, book_id=JEFF_GREEN_BOOK_ID)
        return {
            "aspect_label": f"Planet {planet_name}",
            "query": query,
            "chunks": [{"book_title": c.get("book_title"), "text": c.get("text", "")} for c in chunks],
        }

    tasks = [fetch_aspect(a) for a in synastry_aspects] + [fetch_planet(p) for p in key_planets]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    reference = [r for r in results if not isinstance(r, Exception)]
    errors = [str(r) for r in results if isinstance(r, Exception)]

    RAG_REFERENCE_OUT.write_text(
        json.dumps({"reference": reference, "errors": errors}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    total_chunks = sum(len(r["chunks"]) for r in reference)
    print(f"Wrote {RAG_REFERENCE_OUT} — {len(reference)} queries, {total_chunks} chunks, {len(errors)} errors")


if __name__ == "__main__":
    asyncio.run(main())
