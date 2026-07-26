"""A single synastry generation for eval_synastry.py.

Launched as a subprocess from eval_synastry.py with a different cwd (current
tree or a worktree at fcca162, the version before the batching experiment) —
this way the real versions of full_synastry_analysis_v2 are compared, not
manually reconstructed ones.

    python tests/eval_synastry_runner.py --input <chart_input.json> \
        --output <result.json> --label old|new
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.getcwd())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()

    chart_input = json.loads(Path(args.input).read_text(encoding="utf-8"))

    from app.services.synastry_service import full_synastry_analysis_v2

    async def run():
        start = time.monotonic()
        error = None
        result = None
        try:
            result = await full_synastry_analysis_v2(
                chart1_data=chart_input["chart1_data"],
                chart2_data=chart_input["chart2_data"],
                aspects=chart_input["aspects"],
                overlays=chart_input.get("overlays"),
                language=chart_input.get("language", "ru"),
                top_k_per_book=chart_input.get("top_k_per_book", 3),
                mode=chart_input.get("mode", "advanced"),
                relationship_context=chart_input.get("relationship_context"),
            )
        except Exception as e:  # noqa: BLE001 - eval harness, want the raw failure
            error = f"{type(e).__name__}: {e}"
        elapsed = time.monotonic() - start
        return result, elapsed, error

    result, elapsed, error = asyncio.run(run())

    analysis_text = (result or {}).get("analysis", "") if result else ""
    out = {
        "label": args.label,
        "cwd": os.getcwd(),
        "elapsed_seconds": elapsed,
        "error": error,
        "analysis_text": analysis_text,
        "analysis_chars": len(analysis_text),
        "summary": (result or {}).get("summary") if result else None,
        "chart1_summary": (result or {}).get("chart1_summary") if result else None,
        "chart2_summary": (result or {}).get("chart2_summary") if result else None,
        "aspects_count": len(chart_input["aspects"]),
    }
    Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[runner:{args.label}] done in {elapsed:.1f}s, {len(analysis_text)} chars, error={error}")


if __name__ == "__main__":
    main()
