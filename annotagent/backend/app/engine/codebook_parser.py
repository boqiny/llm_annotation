"""Parse uploaded codebook JSON into internal structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class LabelDef:
    name: str
    definition: str = ""
    examples: list[str] = field(default_factory=list)


@dataclass
class DimensionDef:
    name: str
    dim_type: str = "single_label"
    labels: list[LabelDef] = field(default_factory=list)
    instructions: str = ""


@dataclass
class CodebookDef:
    name: str
    description: str = ""
    dimensions: list[DimensionDef] = field(default_factory=list)
    decomposition_hints: Optional[dict[str, Any]] = None


def parse_codebook(raw: dict[str, Any]) -> CodebookDef:
    """Parse raw codebook JSON dict into a CodebookDef."""
    dimensions = []
    for dim_raw in raw.get("dimensions", []):
        labels = [
            LabelDef(
                name=lbl.get("name", ""),
                definition=lbl.get("definition", ""),
                examples=lbl.get("examples", []),
            )
            for lbl in dim_raw.get("labels", [])
        ]
        dimensions.append(
            DimensionDef(
                name=dim_raw.get("name", ""),
                dim_type=dim_raw.get("type", "single_label"),
                labels=labels,
                instructions=dim_raw.get("instructions", ""),
            )
        )
    return CodebookDef(
        name=raw.get("name", "Untitled Codebook"),
        description=raw.get("description", ""),
        dimensions=dimensions,
        decomposition_hints=raw.get("decomposition_hints"),
    )


def validate_codebook(raw: dict[str, Any]) -> list[str]:
    """Return a list of validation errors (empty = valid)."""
    errors = []
    if "dimensions" not in raw:
        errors.append("Missing 'dimensions' field")
        return errors
    if not isinstance(raw["dimensions"], list) or len(raw["dimensions"]) == 0:
        errors.append("'dimensions' must be a non-empty list")
        return errors
    for i, dim in enumerate(raw["dimensions"]):
        if not dim.get("name"):
            errors.append(f"Dimension {i}: missing 'name'")
        if not dim.get("labels") or not isinstance(dim.get("labels"), list):
            errors.append(f"Dimension {i} ({dim.get('name', '?')}): missing or empty 'labels'")
        else:
            for j, lbl in enumerate(dim["labels"]):
                if not lbl.get("name"):
                    errors.append(f"Dimension {i}, Label {j}: missing 'name'")
    return errors
