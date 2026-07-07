"""Aggregate k=3 (seeds 0,1,2) optimizer results into mean +/- std per dim.

Seed 0 lives in the earlier per-optimizer files (GEPA: gepa_*.json with key
gepa_test_acc; MIPRO/OPRO: opt_<opt>_<slug>.json with key opt_test_acc). Seeds
1,2 are opt_<opt>_<slug>_s{S}.json (key opt_test_acc). Also aggregates zero-shot.
"""
from __future__ import annotations

import json
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
S = BACKEND / "scripts"
DIMS = ["Level of disclosure", "Disclosure as confession",
        "Depth of disclosure", "Intimacy of self-disclosure"]
OPTS = ["gepa", "mipro", "opro"]

# ReflectAgent 3-seed means from exp_result.md Table A (Fiona, +RA).
RA_MEAN = {"Level of disclosure": 70.0, "Disclosure as confession": 82.0,
           "Depth of disclosure": 58.7, "Intimacy of self-disclosure": 75.5}


def _slug(d): return d.replace(" ", "_")


def _seed0_file(opt, dim):
    slug = _slug(dim)
    if opt == "gepa":
        f = S / ("gepa_baseline_result.json" if dim == "Level of disclosure"
                 else f"gepa_{slug}.json")
        return f, "gepa_test_acc"
    return S / f"opt_{opt}_{slug}.json", "opt_test_acc"


def _load(opt, dim):
    """Return (zs_list, opt_list) across available seeds."""
    zs, op = [], []
    # seed 0
    f0, key0 = _seed0_file(opt, dim)
    if f0.exists():
        d = json.load(open(f0))
        zs.append(d["zs_test_acc"] * 100); op.append(d[key0] * 100)
    # seeds 1,2
    for s in (1, 2):
        f = S / f"opt_{opt}_{_slug(dim)}_s{s}.json"
        if f.exists():
            d = json.load(open(f))
            zs.append(d["zs_test_acc"] * 100); op.append(d["opt_test_acc"] * 100)
    return zs, op


def _ms(xs):
    if not xs: return None, None
    m = sum(xs) / len(xs)
    sd = (sum((v - m) ** 2 for v in xs) / len(xs)) ** 0.5
    return m, sd


def main() -> None:
    table = {}
    print(f"{'dim':30} " + " ".join(f"{o:>16}" for o in OPTS) + f"{'RA(3s)':>10}")
    means = {o: [] for o in OPTS}
    for dim in DIMS:
        cells = []
        for opt in OPTS:
            zs, op = _load(opt, dim)
            m, sd = _ms(op)
            table.setdefault(dim, {})[opt] = {"opt_seeds": [round(x, 1) for x in op],
                                              "opt_mean": round(m, 1) if m is not None else None,
                                              "opt_std": round(sd, 1) if sd is not None else None,
                                              "n_seeds": len(op)}
            if m is not None:
                means[opt].append(m)
                cells.append(f"{m:4.1f}+/-{sd:3.1f}(k{len(op)})")
            else:
                cells.append("  --  ")
        print(f"{dim:30} " + " ".join(f"{c:>16}" for c in cells) + f"{RA_MEAN[dim]:>10.1f}")
    print(f"\n{'MEAN':30} " + " ".join(
        f"{(_ms(means[o])[0] or 0):4.1f}          " for o in OPTS)
        + f"{sum(RA_MEAN.values())/4:>10.1f}")
    (S / "k3_aggregate.json").write_text(json.dumps(table, indent=2))
    print(f"\nwrote {S/'k3_aggregate.json'}")


if __name__ == "__main__":
    main()
