"""
Parse Microsoft Fabric Data Factory pipeline JSON files into structured data.

A Fabric pipeline JSON has the shape:
{
  "name": "...",
  "properties": {
    "description": "...",
    "activities": [ { ... }, ... ],
    "parameters": { "paramName": { "type": "...", "defaultValue": ... } },
    "annotations": []
  }
}

Each activity has at minimum:
  name, type, dependsOn: [{ activity, dependencyConditions }], typeProperties: { ... }
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ActivityDependency:
    activity_name: str
    conditions: list[str]  # e.g. ["Succeeded"]


@dataclass
class PipelineActivity:
    name: str
    activity_type: str          # raw Fabric type string, e.g. "TridentNotebook"
    description: str
    depends_on: list[ActivityDependency]
    type_properties: dict[str, Any]
    raw: dict[str, Any]         # full original JSON block

    # populated for notebook activities after linking
    notebook_path: str | None = None


@dataclass
class PipelineParameter:
    name: str
    param_type: str
    default_value: Any


@dataclass
class ParsedPipeline:
    name: str
    description: str
    source_path: Path
    parameters: list[PipelineParameter]
    activities: list[PipelineActivity]

    def activity_by_name(self, name: str) -> PipelineActivity | None:
        return next((a for a in self.activities if a.name == name), None)

    def root_activities(self) -> list[PipelineActivity]:
        """Activities with no dependencies — the starting points of the pipeline."""
        return [a for a in self.activities if not a.depends_on]

    def ordered_activities(self) -> list[PipelineActivity]:
        """Topological sort: activities in execution order."""
        resolved: list[str] = []
        remaining = list(self.activities)
        max_iter = len(self.activities) + 1
        iterations = 0
        while remaining and iterations < max_iter:
            iterations += 1
            for act in list(remaining):
                dep_names = [d.activity_name for d in act.depends_on]
                if all(d in resolved for d in dep_names):
                    resolved.append(act.name)
                    remaining.remove(act)
        # append anything still unresolved (cycles / bad data)
        resolved.extend(a.name for a in remaining)
        name_index = {n: i for i, n in enumerate(resolved)}
        return sorted(self.activities, key=lambda a: name_index.get(a.name, 999))


def _parse_activity(raw: dict[str, Any]) -> PipelineActivity:
    depends_on = [
        ActivityDependency(
            activity_name=dep["activity"],
            conditions=dep.get("dependencyConditions", ["Succeeded"]),
        )
        for dep in raw.get("dependsOn", [])
    ]
    return PipelineActivity(
        name=raw.get("name", "Unnamed"),
        activity_type=raw.get("type", "Unknown"),
        description=raw.get("description", ""),
        depends_on=depends_on,
        type_properties=raw.get("typeProperties", {}),
        raw=raw,
    )


def parse_pipeline_file(path: Path) -> ParsedPipeline | None:
    """
    Parse a Fabric pipeline JSON file.  Returns None if the file does not
    look like a pipeline (so the caller can silently skip unrelated JSON).
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    # Accept both bare {"activities": [...]} and {"properties": {"activities": [...]}}
    props = data.get("properties", data)
    if "activities" not in props:
        return None

    raw_params = props.get("parameters", {})
    parameters = [
        PipelineParameter(
            name=pname,
            param_type=pval.get("type", "string"),
            default_value=pval.get("defaultValue"),
        )
        for pname, pval in raw_params.items()
    ]

    activities = [_parse_activity(a) for a in props.get("activities", [])]

    pipeline_name = data.get("name") or props.get("name") or path.stem

    return ParsedPipeline(
        name=pipeline_name,
        description=props.get("description", ""),
        source_path=path,
        parameters=parameters,
        activities=activities,
    )


def find_pipeline_files(root: Path) -> list[Path]:
    """
    Recursively find all JSON files under *root* that look like Fabric pipelines.
    Also accepts files with the .pipeline extension.
    """
    candidates: list[Path] = []
    for ext in ("*.json", "*.pipeline"):
        candidates.extend(root.rglob(ext))

    pipelines: list[Path] = []
    for path in sorted(candidates):
        if ".git" in path.parts:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        props = data.get("properties", data)
        if "activities" in props:
            pipelines.append(path)
    return pipelines
