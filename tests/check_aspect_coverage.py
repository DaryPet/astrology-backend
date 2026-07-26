"""Deterministic coverage check: how many of the synastry aspects are actually
discussed in the finished text, not just mentioned in passing. No LLM.

The primary method is direction-aware: look for a bold heading where planet1
is explicitly attributed to Partner 1 and planet2 to Partner 2
(attribute_header_planets_to_partners in app/services/synastry_service.py).
This matters because the same unordered pair of planets (Saturn-Chiron) can
occur as TWO different real aspects — Saturn(P1)-Chiron(P2) and
Chiron(P1)-Saturn(P2), with different orb and type — a naive "both names in
one paragraph" check confuses them (see
plans/synastry-aspect-type-verification.md, a live example from an eval run).

Falls back to the naive "both names occur near each other in the paragraph"
check — only if the planets are different (Sun != Moon) and the strict
method found nothing: the model doesn't always format an aspect as a bold
heading with a "Partner N" label, and skipping analysis entirely could
undercount coverage. For identical planets (Venus-Venus) the fallback is not
used — there "both names" would trivially match a single mention.

Doesn't check meaning/correctness — only the physical presence of text for a
planet pair. For meaning and book fidelity — see the LLM judge
(judge_synastry.py).

    python tests/check_aspect_coverage.py <analysis.json> [analysis2.json ...]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.services.synastry_service import PLANET_RU, find_paragraph_for_pair  # noqa: E402

SHALLOW_CHAR_THRESHOLD = 220  # below this - "mentioned", not "discussed"

PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n|(?=\*\*[^\n]{0,80}\*\*)")

# The new variant appends a debug block "ИСТОЧНИКИ ПО АСПЕКТАМ" — one line
# per aspect like "Venus Квадрат Pluto (орб: 5.71°): 3 чанков, книги: ?".
# Both planets appear in that one "paragraph line" for EVERY aspect
# regardless of the actual analysis — if the block isn't stripped, the
# coverage check becomes a tautology (always 100% match, because it's a
# list, not an analysis).
# NOTE: this literal marker string is left untranslated on purpose — it must
# match the literal Russian text the production code emits (see
# app/services/synastry_service.py), not prose to translate.
SOURCES_DEBUG_MARKER = "ИСТОЧНИКИ ПО АСПЕКТАМ"


def _strip_debug_block(text: str) -> str:
    idx = text.find(SOURCES_DEBUG_MARKER)
    if idx == -1:
        return text
    # Cut from the start of the line where "===" sits before the marker
    cut = text.rfind("===", 0, idx)
    return text[:cut] if cut != -1 else text[:idx]


def _paragraphs(text: str) -> List[str]:
    text = _strip_debug_block(text)
    parts = [p.strip() for p in PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
    return parts


def check_coverage(analysis_text: str, aspects: List[Dict[str, Any]]) -> Dict[str, Any]:
    stripped_text = _strip_debug_block(analysis_text)
    paragraphs = _paragraphs(analysis_text)
    per_aspect = []

    for asp in aspects:
        planet1_en, planet2_en = asp.get("planet1", ""), asp.get("planet2", "")
        p1_ru = PLANET_RU.get(planet1_en, planet1_en)
        p2_ru = PLANET_RU.get(planet2_en, planet2_en)

        best_paragraph_len = 0
        directed = find_paragraph_for_pair(stripped_text, planet1_en, planet2_en)
        if directed:
            best_paragraph_len = len(directed)
        elif p1_ru != p2_ru:
            # Fallback only for different planets — the model may have
            # discussed the aspect in prose, without a bold heading and
            # partner label.
            for para in paragraphs:
                if p1_ru in para and p2_ru in para:
                    best_paragraph_len = max(best_paragraph_len, len(para))

        if best_paragraph_len == 0:
            status = "missing"
        elif best_paragraph_len < SHALLOW_CHAR_THRESHOLD:
            status = "shallow"
        else:
            status = "covered"

        per_aspect.append({
            "aspect": f"{p1_ru} {asp.get('aspect_ru', asp.get('aspect'))} {p2_ru}",
            "orb": asp.get("orb"),
            "status": status,
            "best_paragraph_chars": best_paragraph_len,
        })

    total = len(per_aspect)
    covered = sum(1 for a in per_aspect if a["status"] == "covered")
    shallow = sum(1 for a in per_aspect if a["status"] == "shallow")
    missing = sum(1 for a in per_aspect if a["status"] == "missing")

    return {
        "total_aspects": total,
        "covered": covered,
        "shallow": shallow,
        "missing": missing,
        "coverage_pct": round(100 * covered / total, 1) if total else 0.0,
        "covered_or_shallow_pct": round(100 * (covered + shallow) / total, 1) if total else 0.0,
        "per_aspect": per_aspect,
    }


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    chart_input = json.loads((ROOT / "tests/reports/synastry/chart_input.json").read_text(encoding="utf-8"))
    aspects = chart_input["aspects"]

    for path_str in sys.argv[1:]:
        path = Path(path_str)
        run = json.loads(path.read_text(encoding="utf-8"))
        report = check_coverage(run.get("analysis_text", ""), aspects)
        out_path = path.with_name(path.stem + ".coverage.json")
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"{path.name}: covered={report['covered']}/{report['total_aspects']} "
            f"({report['coverage_pct']}%) shallow={report['shallow']} missing={report['missing']}"
        )


if __name__ == "__main__":
    main()
