"""Run a local annotation workflow from versioned project input files.

This script is intended for local development and backend smoke testing. It
loads a project codebook, annotation items, and task configuration from the
workspace directory, constructs the configured LLM client, and runs the
ProjectWorkflow asynchronously.

The current file-based inputs are a temporary development interface. In the
frontend-integrated version, these inputs may be replaced by API-provided
payloads or database records.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from dotenv import load_dotenv

from annotation_demo.core.llm import make_llm
from annotation_demo.utils.storage import load_json, load_yaml
from annotation_demo.workflows.workflow import ProjectWorkflow


load_dotenv()


ROOT_DIR = Path(__file__).resolve().parents[1]


async def amain() -> None:
    project_id = "project_0"

    input_dir = ROOT_DIR / "workspace" / project_id / "inputs"

    codebook = load_json(input_dir / "codebook.v001.json")
    items = load_json(input_dir / "items.v001.json")
    task_config = load_yaml(input_dir / "task_config.v001.yaml")

    llm = make_llm(
        provider=task_config.get("provider", "openai"),
        model=task_config.get("model"),
        temperature=task_config.get("temperature", 0.0),
        max_tokens=task_config.get("max_tokens", 1024),
    )

    workflow = ProjectWorkflow(
        project_id=project_id,
        llm=llm,
        workspace_dir=ROOT_DIR / "workspace",
    )

    result = await workflow.run(
        codebook=codebook,
        items=items,
        task_config=task_config,
    )

    print("\nWorkflow finished.")
    print(json.dumps(result.__dict__, indent=2, ensure_ascii=False))


def main() -> None:
    asyncio.run(amain())


if __name__ == "__main__":
    main()
