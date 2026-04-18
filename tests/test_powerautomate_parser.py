"""Tests for agent/parsers/powerautomate_parser.py"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from agent.parsers.powerautomate_parser import (
    ParsedPowerAutomateFlow,
    _extract_definition,
    _is_powerautomate_json,
    _is_powerautomate_zip,
    _parse_actions,
    _parse_connections,
    _parse_data,
    _parse_triggers,
    find_powerautomate_files,
    parse_powerautomate_file,
)


# ---------------------------------------------------------------------------
# Fixtures — shared JSON payloads
# ---------------------------------------------------------------------------

SIMPLE_FLOW = {
    "properties": {
        "displayName": "My Flow",
        "description": "Sends a daily report",
        "definition": {
            "triggers": {
                "Recurrence": {
                    "type": "Recurrence",
                    "recurrence": {"frequency": "Day", "interval": 1},
                }
            },
            "actions": {
                "Send_an_email": {
                    "type": "OpenApiConnection",
                    "runAfter": {},
                    "inputs": {
                        "host": {"connectionName": "shared_office365", "apiId": "/providers/Microsoft.PowerApps/apis/shared_office365"},
                        "method": "post",
                        "path": "/Mail",
                    },
                    "description": "Send summary email",
                }
            },
        },
        "connectionReferences": {
            "shared_office365": {
                "api": {"name": "shared_office365", "displayName": "Office 365 Outlook"},
            }
        },
    }
}

ROOT_LEVEL_FLOW = {
    "displayName": "Root Level Flow",
    "triggers": {
        "manual": {"type": "Request", "kind": "Button"}
    },
    "actions": {
        "Compose": {"type": "Compose", "runAfter": {}, "inputs": "hello"}
    },
}

DEFINITION_LEVEL_FLOW = {
    "definition": {
        "triggers": {
            "http_trigger": {"type": "Request", "kind": "Http"}
        },
        "actions": {
            "Parse_JSON": {"type": "ParseJson", "runAfter": {}}
        },
    }
}


# ---------------------------------------------------------------------------
# _extract_definition
# ---------------------------------------------------------------------------

class TestExtractDefinition:
    def test_properties_definition_layout(self):
        defn = _extract_definition(SIMPLE_FLOW)
        assert defn is not None
        assert "triggers" in defn
        assert "actions" in defn

    def test_root_definition_layout(self):
        defn = _extract_definition(DEFINITION_LEVEL_FLOW)
        assert defn is not None
        assert "triggers" in defn

    def test_root_level_layout(self):
        defn = _extract_definition(ROOT_LEVEL_FLOW)
        assert defn is not None
        assert "triggers" in defn

    def test_pipeline_json_not_matched(self):
        pipeline = {"properties": {"activities": [{"name": "Copy", "type": "Copy"}]}}
        assert _extract_definition(pipeline) is None

    def test_dataflow_json_not_matched(self):
        dataflow = {"properties": {"definition": {"queries": []}}}
        assert _extract_definition(dataflow) is None

    def test_empty_dict_not_matched(self):
        assert _extract_definition({}) is None

    def test_missing_actions_not_matched(self):
        data = {"definition": {"triggers": {"t": {}}}}
        assert _extract_definition(data) is None

    def test_missing_triggers_not_matched(self):
        data = {"definition": {"actions": {"a": {}}}}
        assert _extract_definition(data) is None


# ---------------------------------------------------------------------------
# _parse_triggers
# ---------------------------------------------------------------------------

class TestParseTriggers:
    def test_basic_trigger(self):
        triggers = {"Recurrence": {"type": "Recurrence", "kind": "Schedule"}}
        result = _parse_triggers(triggers)
        assert len(result) == 1
        assert result[0].name == "Recurrence"
        assert result[0].type == "Recurrence"
        assert result[0].kind == "Schedule"

    def test_empty_triggers(self):
        assert _parse_triggers({}) == []

    def test_trigger_without_kind(self):
        triggers = {"manual": {"type": "Request"}}
        result = _parse_triggers(triggers)
        assert result[0].kind == ""

    def test_multiple_triggers(self):
        triggers = {
            "t1": {"type": "Recurrence"},
            "t2": {"type": "Request"},
        }
        result = _parse_triggers(triggers)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _parse_actions
# ---------------------------------------------------------------------------

class TestParseActions:
    def test_basic_action(self):
        actions = {
            "Send_email": {
                "type": "OpenApiConnection",
                "runAfter": {},
                "inputs": {"host": {"connectionName": "shared_office365"}},
                "description": "Sends email",
            }
        }
        result = _parse_actions(actions)
        assert len(result) == 1
        assert result[0].name == "Send_email"
        assert result[0].type == "OpenApiConnection"
        assert result[0].connection == "shared_office365"
        assert result[0].description == "Sends email"

    def test_run_after_populated(self):
        actions = {
            "Step2": {
                "type": "Compose",
                "runAfter": {"Step1": ["Succeeded"]},
            }
        }
        result = _parse_actions(actions)
        assert result[0].run_after == ["Step1"]

    def test_nested_condition_actions(self):
        actions = {
            "Check": {
                "type": "Condition",
                "runAfter": {},
                "actions": {
                    "If_yes": {"type": "Compose", "runAfter": {}}
                },
                "else": {
                    "actions": {
                        "If_no": {"type": "Terminate", "runAfter": {}}
                    }
                },
            }
        }
        result = _parse_actions(actions)
        names = [a.name for a in result]
        assert "Check" in names
        assert "If_yes" in names
        assert "If_no" in names

    def test_switch_case_actions(self):
        actions = {
            "Route": {
                "type": "Switch",
                "runAfter": {},
                "cases": {
                    "Case_A": {
                        "case": "A",
                        "actions": {"Action_A": {"type": "Compose", "runAfter": {}}}
                    }
                },
                "default": {
                    "actions": {"Default_Action": {"type": "Terminate", "runAfter": {}}}
                },
            }
        }
        result = _parse_actions(actions)
        names = [a.name for a in result]
        assert "Route" in names
        assert "Action_A" in names
        assert "Default_Action" in names

    def test_empty_actions(self):
        assert _parse_actions({}) == []

    def test_connection_from_api_id(self):
        actions = {
            "Act": {
                "type": "OpenApiConnection",
                "runAfter": {},
                "inputs": {"host": {"apiId": "/providers/Microsoft.PowerApps/apis/shared_sharepointonline"}},
            }
        }
        result = _parse_actions(actions)
        assert result[0].connection == "shared_sharepointonline"


# ---------------------------------------------------------------------------
# _parse_connections
# ---------------------------------------------------------------------------

class TestParseConnections:
    def test_extracts_display_names(self):
        refs = {
            "shared_office365": {"api": {"displayName": "Office 365 Outlook", "name": "shared_office365"}},
            "shared_sharepointonline": {"api": {"name": "shared_sharepointonline"}},
        }
        result = _parse_connections(refs)
        assert "Office 365 Outlook" in result
        assert "shared_sharepointonline" in result

    def test_deduplicates(self):
        refs = {
            "ref1": {"api": {"name": "shared_office365"}},
            "ref2": {"api": {"name": "shared_office365"}},
        }
        result = _parse_connections(refs)
        assert result.count("shared_office365") == 1

    def test_empty_refs(self):
        assert _parse_connections({}) == []


# ---------------------------------------------------------------------------
# _parse_data
# ---------------------------------------------------------------------------

class TestParseData:
    def test_simple_flow(self, tmp_path):
        path = tmp_path / "flow.json"
        flow = _parse_data(SIMPLE_FLOW, path)
        assert flow is not None
        assert flow.name == "My Flow"
        assert flow.display_name == "My Flow"
        assert flow.description == "Sends a daily report"
        assert len(flow.triggers) == 1
        assert len(flow.actions) == 1
        assert "Office 365 Outlook" in flow.connections

    def test_name_fallback_to_stem(self, tmp_path):
        data = {"definition": {"triggers": {"t": {}}, "actions": {"a": {}}}}
        path = tmp_path / "MyFallbackFlow.json"
        flow = _parse_data(data, path)
        assert flow is not None
        assert flow.name == "MyFallbackFlow"

    def test_invalid_data_returns_none(self, tmp_path):
        path = tmp_path / "not_a_flow.json"
        flow = _parse_data({"activities": []}, path)
        assert flow is None


# ---------------------------------------------------------------------------
# ParsedPowerAutomateFlow properties
# ---------------------------------------------------------------------------

class TestParsedPowerAutomateFlow:
    def _make_flow(self, tmp_path) -> ParsedPowerAutomateFlow:
        return _parse_data(SIMPLE_FLOW, tmp_path / "f.json")

    def test_trigger_summary(self, tmp_path):
        flow = self._make_flow(tmp_path)
        assert "Recurrence" in flow.trigger_summary

    def test_action_summary(self, tmp_path):
        flow = self._make_flow(tmp_path)
        assert "Send_an_email" in flow.action_summary

    def test_all_action_names(self, tmp_path):
        flow = self._make_flow(tmp_path)
        assert "Send_an_email" in flow.all_action_names


# ---------------------------------------------------------------------------
# File-level detection
# ---------------------------------------------------------------------------

class TestIsJsonDetection:
    def test_valid_flow_detected(self, tmp_path):
        path = tmp_path / "flow.json"
        path.write_text(json.dumps(SIMPLE_FLOW), encoding="utf-8")
        assert _is_powerautomate_json(path) is True

    def test_pipeline_json_not_detected(self, tmp_path):
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps({"properties": {"activities": []}}), encoding="utf-8")
        assert _is_powerautomate_json(path) is False

    def test_invalid_json_not_detected(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        assert _is_powerautomate_json(path) is False


class TestIsZipDetection:
    def test_zip_with_definition_json(self, tmp_path):
        path = tmp_path / "flow.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("definition.json", json.dumps(SIMPLE_FLOW))
        assert _is_powerautomate_zip(path) is True

    def test_zip_without_definition_json(self, tmp_path):
        path = tmp_path / "other.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("readme.txt", "hello")
        assert _is_powerautomate_zip(path) is False

    def test_not_a_zip(self, tmp_path):
        path = tmp_path / "file.zip"
        path.write_bytes(b"not a zip")
        assert _is_powerautomate_zip(path) is False


# ---------------------------------------------------------------------------
# parse_powerautomate_file
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_parse_json_file(self, tmp_path):
        path = tmp_path / "flow.json"
        path.write_text(json.dumps(SIMPLE_FLOW), encoding="utf-8")
        flow = parse_powerautomate_file(path)
        assert flow is not None
        assert flow.name == "My Flow"

    def test_parse_zip_file(self, tmp_path):
        path = tmp_path / "flow.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("definition.json", json.dumps(SIMPLE_FLOW))
        flow = parse_powerautomate_file(path)
        assert flow is not None
        assert flow.name == "My Flow"

    def test_invalid_file_returns_none(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text(json.dumps({"no": "flows"}), encoding="utf-8")
        assert parse_powerautomate_file(path) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert parse_powerautomate_file(tmp_path / "ghost.json") is None


# ---------------------------------------------------------------------------
# find_powerautomate_files
# ---------------------------------------------------------------------------

class TestFindFiles:
    def test_finds_json_flow(self, tmp_path):
        path = tmp_path / "flow.json"
        path.write_text(json.dumps(SIMPLE_FLOW), encoding="utf-8")
        found = find_powerautomate_files(tmp_path)
        assert path in found

    def test_finds_zip_flow(self, tmp_path):
        path = tmp_path / "flow.zip"
        with zipfile.ZipFile(path, "w") as zf:
            zf.writestr("definition.json", json.dumps(SIMPLE_FLOW))
        found = find_powerautomate_files(tmp_path)
        assert path in found

    def test_skips_pipeline_json(self, tmp_path):
        path = tmp_path / "pipeline.json"
        path.write_text(json.dumps({"properties": {"activities": []}}), encoding="utf-8")
        found = find_powerautomate_files(tmp_path)
        assert path not in found

    def test_skips_git_directory(self, tmp_path):
        git_dir = tmp_path / ".git" / "objects"
        git_dir.mkdir(parents=True)
        path = git_dir / "flow.json"
        path.write_text(json.dumps(SIMPLE_FLOW), encoding="utf-8")
        found = find_powerautomate_files(tmp_path)
        assert path not in found

    def test_finds_nested_flow(self, tmp_path):
        subdir = tmp_path / "Workflows"
        subdir.mkdir()
        path = subdir / "daily.json"
        path.write_text(json.dumps(SIMPLE_FLOW), encoding="utf-8")
        found = find_powerautomate_files(tmp_path)
        assert path in found

    def test_empty_directory(self, tmp_path):
        assert find_powerautomate_files(tmp_path) == []
