"""Run seeds 1 and 2 for gepa/mipro/opro x 4 self-disclosure dims (k=3 total).

Portable per-run timeout via subprocess (macOS has no `timeout`). Resumable:
skips any (optimizer, dim, seed) whose result file already exists.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PY = str(BACKEND / ".venv" / "bin" / "python")
DIMS = ["Level of disclosure", "Disclosure as confession",
        "Depth of disclosure", "Intimacy of self-disclosure"]
OPTS = ["gepa", "mipro", "opro"]
SEEDS = [1, 2]
TIMEOUT = 1200  # seconds per run

def main() -> None:
    total = done = failed = skipped = 0
    for s in SEEDS:
        for opt in OPTS:
            for dim in DIMS:
                total += 1
                slug = dim.replace(" ", "_")
                out = BACKEND / "scripts" / f"opt_{opt}_{slug}_s{s}.json"
                if out.exists():
                    skipped += 1
                    print(f"[skip] {opt} | {dim} | s{s} (exists)", flush=True)
                    continue
                cmd = [PY, "scripts/run_optimizer_baseline.py", "--optimizer", opt,
                       "--dim", dim, "--seed-index", str(s), "--threads", "16",
                       "--out", str(out)]
                print(f"[run ] {opt} | {dim} | s{s} ...", flush=True)
                try:
                    r = subprocess.run(cmd, cwd=str(BACKEND), timeout=TIMEOUT)
                    if r.returncode == 0 and out.exists():
                        done += 1
                        print(f"[ok  ] {opt} | {dim} | s{s}", flush=True)
                    else:
                        failed += 1
                        print(f"[FAIL] {opt} | {dim} | s{s} rc={r.returncode}", flush=True)
                except subprocess.TimeoutExpired:
                    failed += 1
                    print(f"[TIME] {opt} | {dim} | s{s} killed after {TIMEOUT}s", flush=True)
    print(f"\nK3_SWEEP_DONE total={total} done={done} skipped={skipped} failed={failed}", flush=True)

if __name__ == "__main__":
    main()
