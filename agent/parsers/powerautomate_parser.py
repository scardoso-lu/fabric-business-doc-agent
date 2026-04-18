"""Parser for Microsoft Power Automate flow files.

Supports two source formats:

- **ZIP archives** exported from the Power Automate portal — the archive must
  contain a ``definition.json`` file at its root.
- **Standalone JSON files** whose contents match the Power Automate flow
  schema (detected by the presence of ``triggers`` + ``actions`` under a
  ``definition`` key at root or under ``properties``).

Detection is intentionally conservative so these files are not confused with
Fabric pipeline JSON (which uses an ``activities`` key) or Dataflow Gen2 JSON
(which uses a ``queries`` key).
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class PowerAutomateTrigger:
    name: str
    type: str
    kind: str = ""
    description: str = ""


@dataclass
class PowerAutomateAction:
    name: str
    type: str
    run_after: list[str] = field(default_factory=list)
    connection: str = ""
    description: str = ""


@dataclass
class ParsedPowerAutomateFlow:
    name: str
    source_path: Path
    display_name: str
    description: str
    triggers: list[PowerAutomateTrigger]
    actions: list[PowerAutomateAction]
    connections: list[str]

    @property
    def all_action_names(self) -> list[str]:
        return [a.name for a in self.actions]

    @property
    def trigger_summary(self) -> str:
        """One-line summary of all triggers."""
        if not self.triggers:
            return ""
        parts = []
        for t in self.triggers:
            kind = f" ({t.kind})" if t.kind else ""
            parts.append(f"{t.name}: {t.type}{kind}")
        return "; ".join(parts)

    @property
    def action_summary(self) -> str:
        """Comma-separated list of top-level action names."""
        return ", ".join(a.name for a in self.actions)


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def find_powerautomate_files(root: Path) -> list[Path]:
    """Recursively find Power Automate flow files under *root*.

    Accepts:
    - ``.zip`` files that are Power Automate portal exports (contain ``definition.json``)
    - ``.json`` files whose top-level structure matches the Power Automate flow schema
    """
    found: list[Path] = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts:
            continue
        suffix = path.suffix.lower()
        if suffix == ".zip":
            if _is_powerautomate_zip(path):
                found.append(path)
        elif suffix == ".json":
            if _is_powerautomate_json(path):
                found.append(path)
    return found


def _is_powerautomate_zip(path: Path) -> bool:
    try:
        with zipfile.ZipFile(path) as zf:
            return "definition.json" in zf.namelist()
    except Exception:
        return False


def _is_powerautomate_json(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return _extract_definition(data) is not None
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_powerautomate_file(path: Path) -> ParsedPowerAutomateFlow | None:
    """Parse a Power Automate flow file.  Returns None if the file is not a valid flow."""
    try:
        if path.suffix.lower() == ".zip":
            return _parse_zip(path)
        return _parse_json_file(path)
    except Exception:
        return None


def _parse_zip(path: Path) -> ParsedPowerAutomateFlow | None:
    with zipfile.ZipFile(path) as zf:
        if "definition.json" not in zf.namelist():
            return None
        data = json.loads(zf.read("definition.json").decode("utf-8"))
    return _parse_data(data, path)


def _parse_json_file(path: Path) -> ParsedPowerAutomateFlow | None:
    data = json.loads(path.read_text(encoding="utf-8"))
    return _parse_data(data, path)


def _parse_data(data: dict, source_path: Path) -> ParsedPowerAutomateFlow | None:
    defn = _extract_definition(data)
    if defn is None:
        return None

    props = data.get("properties", {})
    display_name = (
        props.get("displayName")
        or data.get("displayName")
        or source_path.stem
    )
    description = props.get("description", "") or data.get("description", "") or ""
    name = display_name or source_path.stem

    triggers = _parse_triggers(defn.get("triggers", {}))
    actions = _parse_actions(defn.get("actions", {}))
    connections = _parse_connections(props.get("connectionReferences", {}))

    return ParsedPowerAutomateFlow(
        name=name,
        source_path=source_path,
        display_name=display_name,
        description=description,
        triggers=triggers,
        actions=actions,
        connections=connections,
    )


def _extract_definition(data: dict) -> dict | None:
    """Extract the flow definition dict from various JSON layouts."""
    # Layout 1: properties.definition with triggers + actions
    props = data.get("properties", {})
    defn = props.get("definition", {})
    if isinstance(defn, dict) and "triggers" in defn and "actions" in defn:
        return defn
    # Layout 2: root-level definition with triggers + actions
    defn = data.get("definition", {})
    if isinstance(defn, dict) and "triggers" in defn and "actions" in defn:
        return defn
    # Layout 3: triggers + actions directly at root
    if "triggers" in data and "actions" in data:
        return data
    return None


def _parse_triggers(triggers: dict) -> list[PowerAutomateTrigger]:
    result = []
    for name, t in (triggers or {}).items():
        if not isinstance(t, dict):
            continue
        result.append(PowerAutomateTrigger(
            name=name,
            type=t.get("type", ""),
            kind=t.get("kind", ""),
            description=t.get("description", "") or "",
        ))
    return result


def _parse_actions(actions: dict, _depth: int = 0) -> list[PowerAutomateAction]:
    """Flatten the actions dict into a list, recursing into nested branches.

    Handles the real Power Automate JSON shape:

    - ``Condition`` actions: true branch under ``actions`` key; false branch under
      ``else.actions`` (the ``else`` key wraps its own ``actions`` dict).
    - ``Switch`` actions: each case under ``cases.<name>.actions``; default branch
      under ``default.actions``.
    - ``Scope`` / ``Apply_to_each`` / ``Do_until``: child actions under ``actions``.

    Recursion is capped at three levels to avoid runaway depth on pathological inputs.
    """
    result = []
    for name, a in (actions or {}).items():
        if not isinstance(a, dict):
            continue
        run_after = list((a.get("runAfter") or {}).keys())
        inputs = a.get("inputs") or {}
        host = inputs.get("host") or {}
        conn = (
            host.get("connectionName", "")
            or (host.get("apiId") or "").split("/")[-1]
        )
        result.append(PowerAutomateAction(
            name=name,
            type=a.get("type", ""),
            run_after=run_after,
            connection=conn,
            description=a.get("description", "") or "",
        ))
        if _depth >= 3:
            continue

        # True branch / Scope / loop children
        true_actions = a.get("actions") or {}
        if isinstance(true_actions, dict) and true_actions:
            result.extend(_parse_actions(true_actions, _depth + 1))

        # False branch: else.actions (real PA shape) or else directly (simplified)
        else_branch = a.get("else") or {}
        if isinstance(else_branch, dict) and else_branch:
            else_actions = else_branch.get("actions") or else_branch
            if isinstance(else_actions, dict) and else_actions:
                result.extend(_parse_actions(else_actions, _depth + 1))

        # Switch cases: cases.<name>.actions
        for case_body in (a.get("cases") or {}).values():
            if isinstance(case_body, dict):
                case_actions = case_body.get("actions") or {}
                if isinstance(case_actions, dict) and case_actions:
                    result.extend(_parse_actions(case_actions, _depth + 1))

        # Switch default branch
        default_branch = a.get("default") or {}
        if isinstance(default_branch, dict):
            default_actions = default_branch.get("actions") or {}
            if isinstance(default_actions, dict) and default_actions:
                result.extend(_parse_actions(default_actions, _depth + 1))

    return result


def _parse_connections(refs: dict) -> list[str]:
    """Extract readable connector names from connectionReferences."""
    names: list[str] = []
    for ref in (refs or {}).values():
        if not isinstance(ref, dict):
            continue
        api = ref.get("api") or {}
        api_name = api.get("displayName") or api.get("name", "")
        if api_name:
            names.append(api_name)
    # Deduplicate while preserving order
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]  # type: ignore[func-returns-value]
