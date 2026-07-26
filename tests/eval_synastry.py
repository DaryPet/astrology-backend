"""Orchestrator: old (fcca162, pre-batching experiment) vs new (working tree)
variant of full_synastry_analysis_v2, N runs per variant.

The astrological input is shared (tests/eval_synastry_precompute.py) —
comparison is isolated to the RAG/prompt/LLM layer. Each run is a separate
subprocess with cwd in the respective tree, using the same venv interpreter
(requirements.txt hasn't changed between versions).

    python tests/eval_synastry.py --runs 3 --old-worktree <path>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHART_INPUT = ROOT / "tests" / "reports" / "synastry" / "chart_input.json"
RAW_DIR = ROOT / "tests" / "reports" / "synastry" / "raw"
PYTHON = ROOT / "venv" / "bin" / "python"

TOKEN_ESTIMATE_RE = re.compile(r"tokens estimated\)")
TOKEN_ESTIMATE_NUM_RE = re.compile(r"~(\d+) tokens estimated")


def run_variant(variant: str, cwd: Path, run_idx: int) -> dict:
    out_path = RAW_DIR / f"{variant}_{run_idx}.json"
    stdout_path = RAW_DIR / f"{variant}_{run_idx}.stdout.txt"
    cmd = [
        str(PYTHON), str(ROOT / "tests" / "eval_synastry_runner.py"),
        "--input", str(CHART_INPUT.resolve()),
        "--output", str(out_path.resolve()),
        "--label", variant,
    ]
    env = dict(os.environ)
    env["PYTHONPATH"] = str(cwd)
    print(f"[{variant} run {run_idx}] launching in {cwd} ...")
    t0 = time.monotonic()
    proc = subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True, timeout=900)
    wall = time.monotonic() - t0
    stdout_path.write_text(proc.stdout + "\n--- stderr ---\n" + proc.stderr, encoding="utf-8")

    input_tokens_est = None
    m = TOKEN_ESTIMATE_NUM_RE.search(proc.stdout)
    if m:
        input_tokens_est = int(m.group(1))

    print(f"[{variant} run {run_idx}] wall={wall:.1f}s rc={proc.returncode}")
    if proc.returncode != 0:
        print(proc.stdout[-2000:])
        print(proc.stderr[-2000:])

    result = {}
    if out_path.exists():
        result = json.loads(out_path.read_text(encoding="utf-8"))
    result["wall_seconds"] = wall
    result["input_tokens_estimate"] = input_tokens_est
    result["output_tokens_estimate"] = (result.get("analysis_chars") or 0) // 4
    result["returncode"] = proc.returncode
    # Write back into the per-run file — eval_synastry_report.py reads these
    # fields directly from raw/*.json, not from runs_index.json.
    if out_path.exists():
        out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--old-worktree", required=True, help="path to worktree checked out at fcca162")
    parser.add_argument("--only", choices=["old", "new", "both"], default="both")
    args = parser.parse_args()

    if not CHART_INPUT.exists():
        print("chart_input.json missing — run tests/eval_synastry_precompute.py first")
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    old_path = Path(args.old_worktree).resolve()
    variants = []
    if args.only in ("old", "both"):
        variants.append(("old", old_path))
    if args.only in ("new", "both"):
        variants.append(("new", ROOT))

    all_results = []
    for variant, cwd in variants:
        for run_idx in range(1, args.runs + 1):
            res = run_variant(variant, cwd, run_idx)
            all_results.append(res)

    index_path = RAW_DIR.parent / "runs_index.json"
    index_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote {index_path} — {len(all_results)} runs total")


if __name__ == "__main__":
    main()
