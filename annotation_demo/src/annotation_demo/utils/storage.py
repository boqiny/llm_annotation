"""
Filesystem storage utilities.

This module provides lightweight project-local storage helpers for the demo
backend. It manages JSON, YAML, text, JSONL, version IDs, run IDs, and project
workspace directories.

Responsibilities:
- Create project workspace directories.
- Save and load JSON/YAML/text files.
- Append run summaries to JSONL logs.
- Generate prompt/input versions and run IDs.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


DEFAULT_WORKSPACE_DIR = Path("workspace")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_dir(path: str | Path) -> Path:
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_project_dir(
    project_id: str,
    workspace_dir: str | Path = DEFAULT_WORKSPACE_DIR,
) -> Path:
    return Path(workspace_dir) / project_id


def ensure_project_dirs(
    project_id: str,
    workspace_dir: str | Path = DEFAULT_WORKSPACE_DIR,
) -> Path:
    project_dir = get_project_dir(project_id, workspace_dir)

    for subdir in [
        "inputs",
        "prompts",
        "runs",
        "logs",
        "memory",
    ]:
        ensure_dir(project_dir / subdir)

    return project_dir


def save_json(path: str | Path, obj: Any, indent: int = 2) -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    path.write_text(
        json.dumps(obj, indent=indent, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def load_json(path: str | Path) -> Any:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def save_yaml(path: str | Path, obj: Any) -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    path.write_text(
        yaml.safe_dump(obj, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    return path


def load_yaml(path: str | Path) -> Any:
    path = Path(path)
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def save_text(path: str | Path, text: str) -> Path:
    path = Path(path)
    ensure_dir(path.parent)
    path.write_text(text, encoding="utf-8")
    return path


def load_text(path: str | Path) -> str:
    path = Path(path)
    return path.read_text(encoding="utf-8")


def append_jsonl(path: str | Path, obj: dict[str, Any]) -> Path:
    path = Path(path)
    ensure_dir(path.parent)

    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    return path


def list_versions(
    directory: str | Path,
    suffix: str | None = None,
    prefix: str = "v",
) -> list[str]:
    directory = Path(directory)

    if not directory.exists():
        return []

    versions: list[str] = []
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)(?:\..+)?$")

    for path in directory.iterdir():
        if not path.is_file():
            continue

        if suffix is not None and path.suffix != suffix:
            continue

        match = pattern.match(path.name)
        if match:
            versions.append(f"{prefix}{int(match.group(1)):03d}")

    return sorted(set(versions))


def next_version(
    directory: str | Path,
    suffix: str | None = None,
    prefix: str = "v",
) -> str:
    versions = list_versions(directory, suffix=suffix, prefix=prefix)

    if not versions:
        return f"{prefix}001"

    last_num = max(int(v.replace(prefix, "")) for v in versions)
    return f"{prefix}{last_num + 1:03d}"


def list_runs(runs_dir: str | Path) -> list[str]:
    runs_dir = Path(runs_dir)

    if not runs_dir.exists():
        return []

    run_ids: list[str] = []
    pattern = re.compile(r"^run_(\d+)$")

    for path in runs_dir.iterdir():
        if not path.is_dir():
            continue

        match = pattern.match(path.name)
        if match:
            run_ids.append(f"run_{int(match.group(1)):03d}")

    return sorted(run_ids)


def next_run_id(runs_dir: str | Path) -> str:
    run_ids = list_runs(runs_dir)

    if not run_ids:
        return "run_001"

    last_num = max(int(run_id.replace("run_", "")) for run_id in run_ids)
    return f"run_{last_num + 1:03d}"


def create_run_dir(project_dir: str | Path) -> tuple[str, Path]:
    project_dir = Path(project_dir)
    runs_dir = project_dir / "runs"

    run_id = next_run_id(runs_dir)
    run_dir = runs_dir / run_id
    ensure_dir(run_dir)

    return run_id, run_dir


def project_paths(
    project_id: str,
    workspace_dir: str | Path = DEFAULT_WORKSPACE_DIR,
) -> dict[str, Path]:
    project_dir = ensure_project_dirs(project_id, workspace_dir)

    return {
        "project": project_dir,
        "inputs": project_dir / "inputs",
        "prompts": project_dir / "prompts",
        "runs": project_dir / "runs",
        "logs": project_dir / "logs",
        "memory": project_dir / "memory",
        "runs_log": project_dir / "logs" / "runs.jsonl",
    }
