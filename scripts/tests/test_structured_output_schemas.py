"""Offline regression tests for strict structured-output schema compatibility.

No model call, no network and no real run: these tests only build, validate and
inspect the schemas the supervisor sends to Codex/Claude.

Provenance for ``fixtures/architect-plan-schema-pre-fix.json``: the exact
``report.schema.json`` written by the failed pilot job
``plan-333de1fd7746`` in run ``20261113T104752-32561af8`` (sha256
1404eb3983661625f5f9079e8c3438f364b1d4ba87b872df072d6148b56b9619).
Codex rejected it with HTTP 400 ``invalid_json_schema`` because
``schema.properties.batches.items.required`` did not include
``verification_purpose``.
"""
from __future__ import annotations
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "orchestrator.py"
FIXTURES = HERE / "fixtures"
# Hermetic: never read the developer's live config or state.
os.environ.pop("ABDULLAH_CHECKOUT_REGISTRY", None)
os.environ.pop("ABDULLAH_STATE_DIR", None)
os.environ["ABDULLAH_CONFIG"] = str(SRC.parent / "config.example.json")
spec = importlib.util.spec_from_file_location("abdullah_orchestrator_schema", SRC)
orc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = orc
spec.loader.exec_module(orc)


def node(schema, *path):
    for step in path:
        schema = schema[step]
    return schema


def plan_batch_schema():
    return node(orc.schema("plan"), "properties", "batches", "items")


class GeneratedSchemasAreStrict(unittest.TestCase):
    def test_every_report_schema_passes_preflight(self):
        for kind in orc.STRUCTURED_OUTPUT_KINDS:
            with self.subTest(kind=kind):
                document = orc.schema(kind)
                self.assertIs(
                    orc.validate_structured_output_schema(document), document)

    def test_plan_batch_declares_every_property_required(self):
        batch = plan_batch_schema()
        self.assertEqual(set(batch["required"]), set(batch["properties"]))
        self.assertIn("verification_purpose", batch["required"])

    def test_verification_purpose_is_required_nullable(self):
        purpose = plan_batch_schema()["properties"]["verification_purpose"]
        self.assertEqual(sorted(purpose["type"]), ["null", "string"])
        self.assertIn("description", purpose)

    def test_plan_shape_matches_supervisor_validation(self):
        # Fields validate_report() reads for every batch must be declared and
        # required, so a schema-valid report cannot omit validator inputs.
        batch = plan_batch_schema()
        for field in ("title", "goal", "acceptance", "checks", "risk",
                      "verification_purpose"):
            self.assertIn(field, batch["properties"])
            self.assertIn(field, batch["required"])
        plan = orc.schema("plan")
        self.assertEqual(set(plan["required"]), set(plan["properties"]))

    def test_all_objects_are_closed_and_nested_items_are_checked(self):
        for kind in orc.STRUCTURED_OUTPUT_KINDS:
            document = orc.schema(kind)
            stack = [("root", document)]
            while stack:
                path, current = stack.pop()
                if current.get("type") == "object":
                    self.assertIs(current["additionalProperties"], False, path)
                    self.assertEqual(set(current["required"]),
                                     set(current["properties"]), path)
                    stack.extend((f"{path}.{name}", child)
                                 for name, child in current["properties"].items())
                elif current.get("type") == "array":
                    stack.append((f"{path}[]", current["items"]))


class PreflightRejectsDefects(unittest.TestCase):
    def assert_rejected(self, document, pattern):
        with self.assertRaisesRegex(ValueError, pattern):
            orc.validate_structured_output_schema(document)

    def test_exact_failed_pilot_schema_is_rejected(self):
        failed = json.loads(
            (FIXTURES / "architect-plan-schema-pre-fix.json").read_text(encoding="utf-8"))
        with self.assertRaises(ValueError) as caught:
            orc.validate_structured_output_schema(failed, "report:plan")
        message = str(caught.exception)
        self.assertIn("verification_purpose", message)
        self.assertIn("required", message)

    def test_missing_required_property_is_detected(self):
        document = {
            "type": "object", "additionalProperties": False,
            "properties": {"alpha": {"type": "string"},
                           "beta": {"type": "string"}},
            "required": ["alpha"],
        }
        self.assert_rejected(document, "missing \\['beta'\\]")

    def test_missing_additional_properties_is_detected(self):
        broken = {"type": "object", "additionalProperties": False,
                  "properties": {"outer": {
                      "type": "object", "additionalProperties": False,
                      "properties": {"inner": {"type": "object",
                                               "properties": {"value": {"type": "string"}},
                                               "required": ["value"]}},
                      "required": ["inner"]}},
                  "required": ["outer"]}
        with self.assertRaises(ValueError) as caught:
            orc.validate_structured_output_schema(broken)
        self.assertIn("properties.inner.additionalProperties must be false",
                      str(caught.exception))

    def test_invalid_array_item_object_is_detected(self):
        document = {
            "type": "object", "additionalProperties": False,
            "properties": {"items": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "properties": {"name": {"type": "string"},
                               "note": {"type": "string"}},
                "required": ["name"]}}},
            "required": ["items"],
        }
        self.assert_rejected(document, r"items\.items|missing \['note'\]")

    def test_optional_property_must_be_nullable_or_required(self):
        document = {"type": "object", "additionalProperties": False,
                    "properties": {"required_value": {"type": "string"}},
                    "required": ["required_value"]}
        optional = copy.deepcopy(document)
        optional["properties"]["maybe"] = {"type": "string"}
        self.assert_rejected(optional, r"maybe")

    def test_optional_nullable_field_is_accepted(self):
        document = {"type": "object", "additionalProperties": False,
                    "properties": {"maybe": {"type": ["string", "null"]}},
                    "required": ["maybe"]}
        self.assertIs(orc.validate_structured_output_schema(document), document)

    def test_malformed_plan_schemas_are_detected(self):
        valid = orc.schema("plan")
        broken_required = copy.deepcopy(valid)
        broken_required["required"] = [key for key in valid["required"]
                                       if key != "summary"]
        self.assert_rejected(broken_required, r"summary")

        unknown_property = copy.deepcopy(valid)
        unknown_property["required"].append("not_declared")
        self.assert_rejected(unknown_property, r"not_declared")

        unsupported = copy.deepcopy(valid)
        unsupported["properties"]["status"] = {"type": "string",
                                              "minLength": 1}
        self.assert_rejected(unsupported, r"minLength")

        non_object_root = copy.deepcopy(valid)
        non_object_root["type"] = "array"
        self.assert_rejected(non_object_root, r"root")

        missing_items = copy.deepcopy(valid)
        del missing_items["properties"]["batches"]["items"]
        self.assert_rejected(missing_items, r"items")

        union = copy.deepcopy(valid)
        union["properties"]["status"] = {"anyOf": [{"type": "string"}]}
        self.assert_rejected(union, r"anyOf|type is required")

        bad_enum = copy.deepcopy(valid)
        bad_enum["properties"]["status"] = {"type": "string", "enum": ["ok", 7]}
        self.assert_rejected(bad_enum, r"enum")

        nullable_union = copy.deepcopy(valid)
        nullable_union["properties"]["status"] = {
            "type": ["string", "integer", "null"]}
        self.assert_rejected(nullable_union, r"exactly one type")

    def test_referenced_definitions_are_checked(self):
        document = {
            "type": "object", "additionalProperties": False,
            "$defs": {"open_object": {"type": "object",
                                      "properties": {"x": {"type": "string"}},
                                      "required": ["x"]}},
            "properties": {"value": {"$ref": "#/$defs/open_object"}},
            "required": ["value"],
        }
        self.assert_rejected(document, r"\$defs\.open_object\.additionalProperties")

    def test_schema_generation_fails_closed_before_dispatch(self):
        broken = copy.deepcopy(orc._report_schema("plan"))
        del broken["properties"]["batches"]["items"]["required"][-1]
        with patch.object(orc, "_report_schema", return_value=broken):
            with self.assertRaisesRegex(ValueError, "verification_purpose"):
                orc.schema("plan")

    def test_preflight_status_reports_every_kind(self):
        status = orc.structured_output_schema_status()
        self.assertEqual(set(status), set(orc.STRUCTURED_OUTPUT_KINDS))
        self.assertTrue(all(item["ok"] for item in status.values()), status)


class HostCommandsCarryValidSchemas(unittest.TestCase):
    ROUTE = {"provider": "codex", "model": "gpt-6.1-sol", "effort": "high",
             "billing": "subscription"}

    def test_codex_output_schema_file_is_compatible(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan-abc123"
            path.mkdir()
            argv, _env, fmt = orc.cli_command("codex", "architect", self.ROUTE,
                                              "prompt", path)
            self.assertEqual(fmt, "codex")
            self.assertIn("--output-schema", argv)
            written = json.loads((path / "report.schema.json").read_text(
                encoding="utf-8"))
            self.assertIs(orc.validate_structured_output_schema(written), written)
            self.assertIn("verification_purpose",
                          node(written, "properties", "batches", "items",
                               "required"))

    def test_claude_json_schema_is_compatible(self):
        route = dict(self.ROUTE, provider="claude", model="opus-5.5")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plan-abc123"
            path.mkdir()
            argv, _env, fmt = orc.cli_command("claude", "architect", route,
                                              "prompt", path)
            self.assertEqual(fmt, "claude")
            schema = json.loads(argv[argv.index("--json-schema") + 1])
            self.assertIs(orc.validate_structured_output_schema(schema), schema)


class HighRiskSemanticsPreserved(unittest.TestCase):
    def plan(self, batch):
        return {"contract_version": 2, "status": "complete", "summary": "s",
                "invariants": ["invariant"], "batches": [batch], "blocker": "",
                "required_exploration": {"job_id": "", "scope_satisfied": True}}

    def batch(self, **overrides):
        value = {"title": "t", "goal": "g", "acceptance": ["done"],
                 "checks": [["pytest", "-q"], ["ruff", "check"]],
                 "risk": "ordinary", "verification_purpose": None}
        value.update(overrides)
        return value

    def test_high_risk_still_requires_documented_purpose(self):
        for purpose in (None, "", "   "):
            with self.subTest(purpose=purpose):
                batch = self.batch(risk="high", verification_purpose=purpose)
                with self.assertRaisesRegex(ValueError, "verification_purpose"):
                    orc.validate_report("plan", self.plan(batch))

    def test_high_risk_with_purpose_is_accepted(self):
        batch = self.batch(risk="high",
                           verification_purpose="prove the parser rejects negatives")
        plan = self.plan(batch)
        self.assertIs(orc.validate_report("plan", plan), plan)

    def test_non_high_risk_may_leave_purpose_null(self):
        for purpose in (None, ""):
            with self.subTest(purpose=purpose):
                plan = self.plan(self.batch(verification_purpose=purpose))
                self.assertIs(orc.validate_report("plan", plan), plan)

    def test_trivial_and_duplicate_high_risk_checks_still_rejected(self):
        trivial = self.batch(risk="high", checks=[["true"], ["pytest", "-q"]],
                             verification_purpose="prove it")
        with self.assertRaisesRegex(ValueError, "trivial"):
            orc.validate_report("plan", self.plan(trivial))
        duplicate = self.batch(risk="high", checks=[["pytest", "-q"],
                                                    ["pytest", "-q"]],
                               verification_purpose="prove it")
        with self.assertRaisesRegex(ValueError, "distinct"):
            orc.validate_report("plan", self.plan(duplicate))


if __name__ == "__main__":
    unittest.main()
