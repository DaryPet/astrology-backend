"""Builds summary.md from runs_index.json + *.coverage.json + *.judge.json.

    python tests/eval_synastry_report.py
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tests.judge_synastry import JUDGE_MODEL, SAMPLE_STRIDE  # noqa: E402

RAW_DIR = ROOT / "tests" / "reports" / "synastry" / "raw"
OUT_MD = ROOT / "tests" / "reports" / "synastry" / "summary.md"


def _avg(values: List[float]) -> float:
    values = [v for v in values if v is not None]
    return round(statistics.mean(values), 2) if values else float("nan")


def load_variant(variant: str) -> List[Dict[str, Any]]:
    runs = []
    for path in sorted(RAW_DIR.glob(f"{variant}_*.json")):
        if path.stem.endswith((".coverage", ".judge")):
            continue
        run = json.loads(path.read_text(encoding="utf-8"))
        cov_path = path.with_name(path.stem + ".coverage.json")
        judge_path = path.with_name(path.stem + ".judge.json")
        run["coverage"] = json.loads(cov_path.read_text(encoding="utf-8")) if cov_path.exists() else None
        run["judge"] = json.loads(judge_path.read_text(encoding="utf-8")) if judge_path.exists() else None
        runs.append(run)
    return runs


def summarize(variant: str, runs: List[Dict[str, Any]]) -> Dict[str, Any]:
    errors = [r for r in runs if r.get("error")]
    ok_runs = [r for r in runs if not r.get("error")]
    return {
        "variant": variant,
        "n_runs": len(runs),
        "n_errors": len(errors),
        "avg_wall_seconds": _avg([r.get("wall_seconds") or r.get("elapsed_seconds") for r in ok_runs]),
        "avg_chars": _avg([r.get("analysis_chars") for r in ok_runs]),
        "avg_input_tokens_est": _avg([r.get("input_tokens_estimate") for r in ok_runs]),
        "avg_output_tokens_est": _avg([r.get("output_tokens_estimate") for r in ok_runs]),
        "avg_coverage_pct": _avg([r["coverage"]["coverage_pct"] for r in ok_runs if r.get("coverage")]),
        "avg_covered_or_shallow_pct": _avg(
            [r["coverage"]["covered_or_shallow_pct"] for r in ok_runs if r.get("coverage")]
        ),
        "avg_missing": _avg([r["coverage"]["missing"] for r in ok_runs if r.get("coverage")]),
        "avg_book_fidelity": _avg([r["judge"]["book_fidelity_score"] for r in ok_runs if r.get("judge")]),
        "avg_depth": _avg([r["judge"]["depth_score"] for r in ok_runs if r.get("judge")]),
        "contradicted_count": sum(
            1
            for r in ok_runs
            if r.get("judge")
            for a in r["judge"].get("per_aspect", [])
            if a.get("fidelity") == "contradicted"
        ),
    }


def main() -> None:
    old_runs = load_variant("old")
    new_runs = load_variant("new")
    old_summary = summarize("old (pre-experiment, fcca162)", old_runs)
    new_summary = summarize("new (working tree)", new_runs)

    lines = []
    lines.append("# Synastry: old vs new — comparison\n")
    lines.append(
        "The shared astrological input (natal charts + aspects) is identical for both variants "
        "— the comparison is isolated to the RAG/prompt/LLM layer. "
        f"Pair: `tests/data/synastry_eval_pair.json`. Runs: "
        f"{old_summary['n_runs']} old / {new_summary['n_runs']} new.\n"
    )
    lines.append(
        "**old** = fcca162 (before this branch's changes): top 5 aspects in RAG search, "
        "book chunks truncated to 200/150 chars, `deepseek-v4-flash`, `temperature=1`.\n\n"
        "**new** = working tree: all ~51 aspects in RAG search, full book chunks, "
        "`deepseek-v4-pro`, `temperature=0.3`, cross-check and auto-fix of hallucinated planet positions.\n"
    )

    lines.append("\n## Table\n")
    lines.append(
        "| Metric | old | new |\n"
        "|---|---|---|\n"
        f"| Runs (errors) | {old_summary['n_runs']} ({old_summary['n_errors']}) | "
        f"{new_summary['n_runs']} ({new_summary['n_errors']}) |\n"
        f"| Generation time, sec (avg) | {old_summary['avg_wall_seconds']} | {new_summary['avg_wall_seconds']} |\n"
        f"| Response length, chars (avg) | {old_summary['avg_chars']} | {new_summary['avg_chars']} |\n"
        f"| Input, tokens (estimate, avg) | {old_summary['avg_input_tokens_est']} | {new_summary['avg_input_tokens_est']} |\n"
        f"| Output, tokens (estimate, avg) | {old_summary['avg_output_tokens_est']} | {new_summary['avg_output_tokens_est']} |\n"
        f"| Coverage: % aspects with in-depth analysis | {old_summary['avg_coverage_pct']}% | {new_summary['avg_coverage_pct']}% |\n"
        f"| Coverage: % aspects mentioned+analyzed | {old_summary['avg_covered_or_shallow_pct']}% | {new_summary['avg_covered_or_shallow_pct']}% |\n"
        f"| Coverage: missing aspects (avg) | {old_summary['avg_missing']} | {new_summary['avg_missing']} |\n"
        f"| LLM judge: book fidelity, 1-5 | {old_summary['avg_book_fidelity']} | {new_summary['avg_book_fidelity']} |\n"
        f"| LLM judge: analysis depth, 1-5 | {old_summary['avg_depth']} | {new_summary['avg_depth']} |\n"
        f"| LLM judge: contradictions with book (sum over runs) | {old_summary['contradicted_count']} | {new_summary['contradicted_count']} |\n"
    )

    lines.append(
        "\n## Limitations\n\n"
        f"- The judge (`{JUDGE_MODEL}`) scores a sample — "
        f"every {SAMPLE_STRIDE}th aspect (~{51 // SAMPLE_STRIDE} of them), not the full list — "
        "to save tokens, same principle as in the event-chart evals "
        "(a full-sample run can be added separately if needed).\n"
        "- 3 runs per variant — with `temperature>0` there is run-to-run variance, "
        "statistical significance at this sample size is limited (see plans/event-chart-tests-and-evals.md, "
        "\"Limitations\").\n"
        "- The judge itself can be wrong just like the model being scored — numeric verdicts "
        "don't replace a spot-check human audit, they only narrow down what to look at by hand.\n"
    )

    lines.append("\n## By run\n")
    for variant, runs in (("old", old_runs), ("new", new_runs)):
        lines.append(f"\n### {variant}\n")
        for i, r in enumerate(runs, 1):
            cov = r.get("coverage") or {}
            judge = r.get("judge") or {}
            lines.append(
                f"- run {i}: {r.get('wall_seconds', r.get('elapsed_seconds')):.1f}s, "
                f"{r.get('analysis_chars')} chars, "
                f"coverage={cov.get('coverage_pct', '?')}% "
                f"(missing={cov.get('missing', '?')}), "
                f"fidelity={judge.get('book_fidelity_score', '?')}, "
                f"depth={judge.get('depth_score', '?')}"
                f"{' — ERROR: ' + str(r['error']) if r.get('error') else ''}"
            )
            if judge.get("overall_notes"):
                lines.append(f"  - judge: {judge['overall_notes']}")

    OUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {OUT_MD}")


if __name__ == "__main__":
    main()
