"""LLM judge: book fidelity and analysis depth.

The judge is GPT-4o (OpenAI), deliberately a different model family than the
generator (DeepSeek) — to avoid self-preference bias (a model favoring its
own style). It doesn't check the whole text against all 183 chunks (that's
~130k tokens of raw reference per request, expensive, and mostly duplicates
per the measurement in the synastry-all-aspects-batching.md plan) — it takes
a fixed sample of every 3rd aspect (consistent across runs, so the comparison
is fair) and for each one: the analysis paragraph (if present) + the real
book chunks the production code searched for using that same query.

Doesn't replace manual review — it's a standalone LLM agent with its own
limitations (it can be wrong just like the model being scored). A spot-check
human audit of the judge's verdicts is still needed before fully trusting the
numbers.

    python tests/judge_synastry.py <analysis.json> [analysis2.json ...]
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402
load_dotenv(ROOT / ".env")

from app.services.synastry_service import PLANET_RU, find_paragraph_for_pair  # noqa: E402
from tests.check_aspect_coverage import _paragraphs, _strip_debug_block  # noqa: E402

SAMPLE_STRIDE = 3
JUDGE_MODEL = "gpt-4o"

JUDGE_SYSTEM_PROMPT = """You are an independent auditor of an evolutionary-astrology synastry \
analysis (Jeffrey Wolf Green method: Pluto, karmic nodes, soul evolution).

For each of N synastry aspects you are given:
1. A paragraph from the finished analysis where (if found) this aspect is discussed.
2. Real book fragments the system found for this aspect (RAG).

Score each aspect:
- "fidelity": "grounded" (claims agree with the book fragments or with \
general principles of evolutionary astrology, nothing contradicted or made \
up), "unsupported" (plausible, but the book fragments neither confirm nor \
deny it — evolutionary astrology allows general principles without a \
fragment, this is NOT an error by itself), "contradicted" \
(the text asserts something that directly contradicts the book fragments), \
"missing" (the aspect is not discussed in the text at all).
- "depth": "substantive" (concrete analysis: house, sign, ruler, connection \
to the nodes/Pluto, not generic phrases), "generic" (discussed, but in \
template phrases with no chart specifics), "missing".

Return STRICTLY JSON with no explanation outside the structure:
{
  "per_aspect": [{"aspect": "...", "fidelity": "...", "depth": "...", "note": "brief, only if contradicted or substantive with an interesting detail"}],
  "book_fidelity_score": <1-5, average groundedness across the whole sample>,
  "depth_score": <1-5, average depth across the whole sample>,
  "overall_notes": "1-3 sentences: the main pattern (not a repeat of the per_aspect list)"
}
"""


def _load_reference(reference_path: Path, aspects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    data = json.loads(reference_path.read_text(encoding="utf-8"))
    ref = data["reference"]
    # precompute builds reference in order: aspects, then key planets — same
    # order as aspects (see eval_synastry_precompute.py)
    return ref[: len(aspects)]


def _paragraph_for_aspect(paragraphs: List[str], p1_ru: str, p2_ru: str) -> str:
    # Fallback for cases where the direction-aware search (find_paragraph_for_pair)
    # found nothing — the model doesn't always format the aspect as a bold
    # heading with a "Partner N" label. Not used for identical planets
    # (p1_ru == p2_ru, e.g. Venus-Venus) — that would trivially match on a
    # single mention.
    if p1_ru == p2_ru:
        return ""
    best = ""
    for para in paragraphs:
        if p1_ru in para and p2_ru in para and len(para) > len(best):
            best = para
    return best


def build_sample(analysis_text: str, aspects: List[Dict[str, Any]], reference: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    stripped_text = _strip_debug_block(analysis_text)
    paragraphs = _paragraphs(analysis_text)
    sample = []
    for idx in range(0, len(aspects), SAMPLE_STRIDE):
        asp = aspects[idx]
        ref = reference[idx] if idx < len(reference) else {"chunks": []}
        planet1_en, planet2_en = asp.get("planet1", ""), asp.get("planet2", "")
        p1_ru = PLANET_RU.get(planet1_en, planet1_en)
        p2_ru = PLANET_RU.get(planet2_en, planet2_en)
        label = f"{p1_ru} {asp.get('aspect_ru', asp.get('aspect'))} {p2_ru} (orb {asp.get('orb')}°)"
        paragraph = find_paragraph_for_pair(stripped_text, planet1_en, planet2_en) or _paragraph_for_aspect(paragraphs, p1_ru, p2_ru)
        # Only 1 chunk (not 3) per aspect, in full, without truncating the
        # chunk text itself — otherwise we'd hit the org TPM limit
        # (30k/min on gpt-4o) and would also be substituting exactly what
        # we're testing for: truncation of the book text.
        chunk_texts = [c["text"] for c in ref.get("chunks", [])][:1]
        sample.append({
            "aspect": label,
            "analysis_paragraph": paragraph or "(not found in text)",
            "book_fragments": chunk_texts,
        })
    return sample


def judge_run(analysis_text: str, aspects: List[Dict[str, Any]], reference: List[Dict[str, Any]]) -> Dict[str, Any]:
    from openai import OpenAI

    sample = build_sample(analysis_text, aspects, reference)
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    user_content = json.dumps({"aspects_to_review": sample}, ensure_ascii=False, indent=2)
    response = client.chat.completions.create(
        model=JUDGE_MODEL,
        messages=[
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    verdict = json.loads(response.choices[0].message.content)
    verdict["_sample_size"] = len(sample)
    verdict["_judge_model"] = JUDGE_MODEL
    return verdict


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    chart_input = json.loads((ROOT / "tests/reports/synastry/chart_input.json").read_text(encoding="utf-8"))
    aspects = chart_input["aspects"]
    reference = _load_reference(ROOT / "tests/reports/synastry/rag_reference.json", aspects)

    import time

    for i, path_str in enumerate(sys.argv[1:]):
        if i > 0:
            time.sleep(20)  # org TPM limit (30k/min on gpt-4o) — space out calls
        path = Path(path_str)
        run = json.loads(path.read_text(encoding="utf-8"))
        verdict = judge_run(run.get("analysis_text", ""), aspects, reference)
        out_path = path.with_name(path.stem + ".judge.json")
        out_path.write_text(json.dumps(verdict, ensure_ascii=False, indent=2), encoding="utf-8")
        print(
            f"{path.name}: fidelity={verdict.get('book_fidelity_score')} "
            f"depth={verdict.get('depth_score')} (sample={verdict.get('_sample_size')})"
        )


if __name__ == "__main__":
    main()
