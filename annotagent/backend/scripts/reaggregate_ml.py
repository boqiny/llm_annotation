"""Re-aggregate the rigorous multi-label results from the per-seed JSON files
already on disk (no LLM calls). Use after re-running a single seed so the
SUMMARY reflects all seeds with the >50%-empty validity guard applied.

  ./.venv/bin/python scripts/reaggregate_ml.py [outdir]
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_multilabel_multiseed import aggregate  # noqa: E402

outdir = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND.parent.parent / "exp_result" / "multilabel_rigorous"
runs = defaultdict(list)
for f in sorted(outdir.glob("*_seed*.json")):
    d = json.loads(f.read_text())
    runs[d["config"]["coder"]].append(d)
# aggregate() sorts internally by insertion; keep seeds ordered
for coder in runs:
    runs[coder].sort(key=lambda d: d["config"]["seed"])
aggregate(dict(runs), outdir)
