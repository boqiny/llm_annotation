"""Pull ACTUAL billed cost + token usage from the OpenAI organization API.

The chat API never returns cost, only token counts; our in-app dollar figures are
estimates from a hardcoded price table (app/utils/cost_tracker.py). This script
reads the real numbers the dashboard shows, so we can (a) report honest costs and
(b) back out the true effective $/1M rate for the model and correct the table.

Requires an ADMIN key with the `api.usage.read` scope (a project `sk-proj-...`
key returns 403). Put it in the repo-root .env as:
    OPENAI_ADMIN_KEY=sk-admin-...

Run (from annotagent/backend):
    ./.venv/bin/python scripts/fetch_openai_cost.py 2026-06-10 2026-06-26
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]


def load_key() -> str:
    env = REPO / ".env"
    keys = {}
    for line in env.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            keys[k.strip()] = v.strip()
    key = keys.get("OPENAI_ADMIN_KEY") or keys.get("OPENAI_API_KEY", "")
    if not key:
        sys.exit("No OPENAI_ADMIN_KEY / OPENAI_API_KEY in .env")
    return key


def get(url: str, key: str):
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as f:
            return json.loads(f.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:300]
        sys.exit(f"HTTP {e.code}: {body}\n"
                 "(403 with 'Missing scopes: api.usage.read' means the key is a "
                 "project key; create an Admin key instead.)")


def ts(date_str: str) -> int:
    d = dt.datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc)
    return int(d.timestamp())


def main() -> None:
    start = ts(sys.argv[1]) if len(sys.argv) > 1 else None
    end = ts(sys.argv[2]) if len(sys.argv) > 2 else None
    if start is None:
        sys.exit("usage: fetch_openai_cost.py <YYYY-MM-DD start> <YYYY-MM-DD end>")
    key = load_key()
    base = "https://api.openai.com/v1/organization"

    costs = get(f"{base}/costs?start_time={start}"
                + (f"&end_time={end}" if end else "")
                + "&bucket_width=1d&limit=62", key)
    total = 0.0
    print("=== daily cost (USD) ===")
    for b in costs.get("data", []):
        day = dt.datetime.fromtimestamp(b["start_time"], dt.timezone.utc).date()
        amt = sum(r["amount"]["value"] for r in b.get("results", []))
        total += amt
        if amt:
            print(f"  {day}  ${amt:.4f}")
    print(f"TOTAL billed: ${total:.4f}")

    usage = get(f"{base}/usage/completions?start_time={start}"
                + (f"&end_time={end}" if end else "")
                + "&bucket_width=1d&limit=62&group_by=model", key)
    by_model: dict[str, int] = {}
    for b in usage.get("data", []):
        for r in b.get("results", []):
            m = r.get("model", "unknown")
            by_model[m] = by_model.get(m, 0) + r.get("input_tokens", 0) + r.get("output_tokens", 0)
    print("\n=== tokens by model ===")
    for m, t in sorted(by_model.items(), key=lambda kv: -kv[1]):
        print(f"  {m:<24} {t:>14,} tokens")

    tot_tokens = sum(by_model.values())
    if tot_tokens:
        print(f"\nEffective blended rate: ${total / tot_tokens * 1e6:.3f} / 1M tokens "
              f"(over {tot_tokens:,} tokens)")
        print("Set this (split into input/output) in app/utils/cost_tracker.py.")


if __name__ == "__main__":
    main()
