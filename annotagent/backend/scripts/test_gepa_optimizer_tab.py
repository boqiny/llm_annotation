"""Integration test: run GEPA through the production optimizer executor
(`app.api.optimizers._execute_run`) the same way the optimizer tab does.

The HTTP route only validates the optimizer name (gepa is in list_optimizers)
and schedules `_execute_run`; this drives that exact executor against a small
real gold dataset in the dev DB, then checks the stored run: status, optimized
prompt, that there are NO rules (GEPA emits a prompt only), and the honest
test scores + leakage audit the executor attaches.

Run from annotagent/backend:
  .venv/bin/python scripts/test_gepa_optimizer_tab.py
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
REPO = BACKEND.parents[1]
sys.path.insert(0, str(BACKEND))

DIM = "Disclosure As Confession"   # binary, well represented in the dev dataset
SRC_DATASET_ID = 1
PROJECT_ID = 1
CAP = 60


def _key() -> str:
    for env in (REPO / ".env", BACKEND.parent / ".env"):
        if env.exists():
            for line in env.read_text().splitlines():
                if line.strip().startswith("EXPERIMENTAL_OPENAI_API_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


async def main() -> None:
    from app.database import async_session
    from sqlalchemy import select
    from app.models.tables import DataItem, Dataset, OptimizerRun
    from app.api.optimizers import _execute_run

    key = _key()
    if not key:
        raise SystemExit("no EXPERIMENTAL_OPENAI_API_KEY")

    # 1) Build a small temp gold dataset from items that carry the chosen dimension.
    async with async_session() as s:
        src = (await s.execute(select(DataItem).where(DataItem.dataset_id == SRC_DATASET_ID))).scalars().all()
        usable = [it for it in src if DIM in (it.gold_labels or {})]
        usable = usable[:CAP]
        print(f"[tab-test] {len(usable)} items carry {DIM!r} (capped {CAP})")
        ds = Dataset(project_id=PROJECT_ID, name="gepa_tab_test", file_type="json",
                     is_gold=True, total_items=len(usable))
        s.add(ds)
        await s.flush()
        for i, it in enumerate(usable):
            s.add(DataItem(dataset_id=ds.id, index=i, content=it.content,
                           context=it.context or "", gold_labels=it.gold_labels))
        run = OptimizerRun(
            project_id=PROJECT_ID, gold_dataset_id=ds.id, optimizer_name="gepa",
            dimension_name=DIM, status="pending", budget=0, train_frac=0.3,
            artifact={"requested_splits": {"train_frac": 0.3, "val_frac": 0.4, "test_frac": 0.3}},
        )
        s.add(run)
        await s.commit()
        await s.refresh(run); await s.refresh(ds)
        run_id, ds_id = run.id, ds.id
    print(f"[tab-test] created dataset {ds_id}, gepa OptimizerRun {run_id}; invoking _execute_run ...")

    # 2) Drive the EXACT executor the tab schedules.
    await _execute_run(run_id=run_id, project_id=PROJECT_ID,
                       provider="openai", model="gpt-5.4-mini", api_key=key)

    # 3) Read back the stored run and check it.
    async with async_session() as s:
        r = await s.get(OptimizerRun, run_id)
        art = r.artifact or {}
        final_prompt = getattr(r, "final_prompt", None) or art.get("optimized_prompt") or ""
        rules = art.get("rule_library") or []
        out = {
            "status": str(r.status),
            "error": r.error,
            "optimizer_name": r.optimizer_name,
            "has_optimized_prompt": bool(final_prompt) or bool(getattr(r, "final_prompt", None)),
            "final_prompt_len": len(final_prompt) if final_prompt else (len(r.final_prompt) if getattr(r, "final_prompt", None) else 0),
            "n_rules": len(rules),
            "trajectory_rounds": len(r.trajectory or []),
            "total_tokens": r.total_tokens,
            "test_scores": art.get("test"),
            "audit_clean": (art.get("audit") or {}).get("clean"),
            "splits": art.get("splits"),
        }
    print("\n===== GEPA via optimizer-tab executor =====")
    print(json.dumps(out, indent=2, default=str))

    ok = out["status"] in ("success", "completed", "done") and out["n_rules"] == 0 and out["test_scores"]
    print("\n[tab-test]", "PASS — GEPA runs through the tab path, prompt-only (no rules)" if ok else "CHECK the output above")

    # 4) Clean up the temp dataset + run so the dev DB stays tidy.
    async with async_session() as s:
        r = await s.get(OptimizerRun, run_id); ds = await s.get(Dataset, ds_id)
        if r: await s.delete(r)
        if ds: await s.delete(ds)
        await s.commit()
    print(f"[tab-test] cleaned up temp dataset {ds_id} + run {run_id}")


if __name__ == "__main__":
    asyncio.run(main())
