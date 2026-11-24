import argparse
import importlib.metadata
import json
import re
import sys
import unittest
from pathlib import Path

from behave.parser import parse_file
from jsonschema import Draft202012Validator
from openapi_spec_validator import validate
from referencing import Registry, Resource

SPEC_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SPEC_ROOT.parents[2]


def read_json(file_path):
    return json.loads(file_path.read_text(encoding="utf-8"))


def ensure(condition, message):
    if not condition:
        raise ValueError(message)


def validate_bindings(api_document, binding_document):
    actual = {}
    for route, methods in api_document["paths"].items():
        for method, operation in methods.items():
            identifier = operation["operationId"]
            ensure(identifier not in actual, "duplicate operationId: " + identifier)
            actual[identifier] = (method.upper(), route)
            for parameter_name in re.findall(r"\{([^}]+)\}", route):
                ensure(any(parameter["name"] == parameter_name and parameter["in"] == "path" and parameter.get("required") for parameter in operation.get("parameters", [])), "missing path parameter: " + route)
    bindings = binding_document["bindings"]
    ensure(len(bindings) == len(actual), "binding count mismatch")
    ensure(len({binding["operation_id"] for binding in bindings}) == len(bindings), "duplicate binding")
    for binding in bindings:
        ensure(actual.get(binding["operation_id"]) == (binding["method"], binding["path"]), "binding drift: " + binding["operation_id"])
        operation = api_document["paths"][binding["path"]][binding["method"].lower()]
        ensure(set(binding["responses"]) == set(operation["responses"]), "response status drift")
    return len(actual)


def validate_migration(entities, migration):
    expected = set(entities) - {"Evidence", "RecommendationItem"}
    ensure(set(migration["entities"]) == expected, "entity count drift")
    for entity_name in expected:
        definition = entities[entity_name]
        columns = migration["entities"][entity_name]["columns"]
        ensure(set(columns) == set(definition["properties"]), "column drift: " + entity_name)
        for field_name, field_schema in definition["properties"].items():
            column = columns[field_name]
            ensure(column["column"] == field_name, "column name drift")
            nullable = isinstance(field_schema.get("type"), list) and "null" in field_schema["type"]
            ensure(column["null"] == nullable, "nullability drift")
            for attribute in ("default", "max_length", "choices", "minimum", "maximum", "const"):
                schema_key = {"max_length": "maxLength", "choices": "enum"}.get(attribute, attribute)
                if schema_key in field_schema:
                    ensure(column.get(attribute) == field_schema[schema_key], "field constraint drift: " + entity_name + "." + field_name)


def check_documents():
    contract = read_json(SPEC_ROOT / "verification-contract.json")
    for artifact in contract["required_artifacts"]:
        ensure((SPEC_ROOT / artifact).is_file(), "missing artifact: " + artifact)
    api_document = read_json(SPEC_ROOT / "openapi.yaml")
    validate(api_document)
    resources = []
    for schema_path in SPEC_ROOT.glob("*.schema.json"):
        schema = read_json(schema_path)
        Draft202012Validator.check_schema(schema)
        resources.append((schema_path.as_uri(), Resource.from_contents(schema)))
    registry = Registry().with_resources(resources)
    for schema_path in SPEC_ROOT.glob("*.schema.json"):
        schema = read_json(schema_path)
        if "$ref" in schema:
            registry.resolver(schema_path.as_uri()).lookup(schema["$ref"])
    sections = re.findall(r"^## 第 (\d+) 部分：", (SPEC_ROOT / "spec.md").read_text(encoding="utf-8"), re.MULTILINE)
    ensure(sections == [str(number) for number in range(contract["sections"])], "section structure mismatch")
    document_text = "\n".join((SPEC_ROOT / name).read_text(encoding="utf-8") for name in ("spec.md", "properties.md"))
    feature_tags = []
    for feature_path in (SPEC_ROOT / "features").glob("*.feature"):
        parse_file(str(feature_path))
        feature_tags.extend(re.findall(r"@(TC-M-\d{3})", feature_path.read_text(encoding="utf-8")))
    ensure(len(feature_tags) == len(set(feature_tags)), "duplicate scenario ID")
    ensure(set(feature_tags) == set(contract["scenarios"]), "scenario coverage mismatch")
    for identifier in contract["scenarios"] + contract["properties"] + contract["property_tests"]:
        ensure(identifier in document_text, "missing trace ID: " + identifier)
    for file_name in ("spec.md", "tasks.md", "checklist.md"):
        content = (SPEC_ROOT / file_name).read_text(encoding="utf-8")
        for phrase in contract["forbidden_phrases"]:
            ensure(phrase not in content, "ambiguous phrase: " + file_name + ": " + phrase)
    for document in list(SPEC_ROOT.glob("*.md")) + [PROJECT_ROOT / "AGENTS.md", PROJECT_ROOT / "BACKLOG.md", PROJECT_ROOT / "decisions" / "_INDEX.md"]:
        content = document.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)]+)\)", content):
            if target.startswith(("#", "https://", "http://")):
                continue
            ensure((document.parent / target.split("#", 1)[0]).exists(), "broken link: " + str(document) + ": " + target)
    errors = read_json(SPEC_ROOT / "error-catalog.json")
    ensure(len(errors["errors"]) == 13, "error catalog count mismatch")
    ensure(all(entry["message"] for entry in errors["errors"].values()), "empty error message")
    frontend_contract = read_json(SPEC_ROOT / "frontend-contract.json")
    ensure(len(frontend_contract["pages"]) == contract["frontend_page_count"], "frontend page count mismatch")
    operation_ids = {operation["operationId"] for methods in api_document["paths"].values() for operation in methods.values()}
    for page in frontend_contract["pages"]:
        ensure(page["path"].startswith("/"), "invalid page path")
        ensure(page["component"].startswith("frontend/src/pages/"), "invalid page component")
        ensure(set(page["operations"]).issubset(operation_ids), "frontend operation binding drift")
    operation_count = validate_bindings(api_document, read_json(SPEC_ROOT / "api-bindings.json"))
    ensure(operation_count == contract["operation_count"], "operation count mismatch")
    entities = read_json(SPEC_ROOT / "entities.schema.json")["$defs"]
    validate_migration(entities, read_json(SPEC_ROOT / "migration-plan.json"))
    for schema in (entities["Behavior"], api_document["components"]["schemas"]["BehaviorRequest"]):
        ensure("listened_ms" in schema["required"], "listened_ms missing")
    return {"operations": operation_count, "scenario_groups": len(feature_tags), "properties": len(contract["properties"]), "result": "PASS document gate; no business tests or database access"}


def check_environment():
    ensure(sys.version_info[:2] == (3, 13), "Python major/minor mismatch")
    for entry in (PROJECT_ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if not entry or entry.startswith("#"):
            continue
        package_name, expected = entry.split("==", 1)
        ensure(importlib.metadata.version(package_name) == expected, "Python lock mismatch: " + package_name)
    package = read_json(PROJECT_ROOT / "frontend" / "package.json")
    lock = read_json(PROJECT_ROOT / "frontend" / "package-lock.json")
    for group in ("dependencies", "devDependencies"):
        ensure(package[group] == lock["packages"][""][group], "frontend manifest-lock mismatch")
    print("PASS installed Python versions and frontend manifest-lock consistency")


class GateTests(unittest.TestCase):
    def test_duplicate_operation_rejected(self):
        document = {"paths": {"/a/": {"get": {"operationId": "read"}}, "/b/": {"get": {"operationId": "read"}}}}
        with self.assertRaises(ValueError):
            validate_bindings(document, {"bindings": []})

    def test_unknown_binding_rejected(self):
        document = {"paths": {"/a/": {"get": {"operationId": "read", "responses": {"200": {}}}}}}
        binding = {"bindings": [{"operation_id": "other", "method": "GET", "path": "/a/", "responses": ["200"]}]}
        with self.assertRaises(ValueError):
            validate_bindings(document, binding)

    def test_missing_migration_column_rejected(self):
        with self.assertRaises(ValueError):
            validate_migration({"Song": {"properties": {"id": {"type": "integer"}}}}, {"entities": {"Song": {"columns": {}}}})

    def test_nullability_drift_rejected(self):
        definition = {"Song": {"properties": {"id": {"type": "integer"}}}}
        migration = {"entities": {"Song": {"columns": {"id": {"column": "id", "null": True}}}}}
        with self.assertRaises(ValueError):
            validate_migration(definition, migration)


def main():
    parser = argparse.ArgumentParser(description="Offline specification validation only")
    parser.add_argument("--check-environment", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    options = parser.parse_args()
    if options.self_test:
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GateTests))
        if not result.wasSuccessful():
            return 1
    try:
        print(json.dumps(check_documents(), ensure_ascii=False))
        if options.check_environment:
            check_environment()
    except Exception as error:
        print("FAIL " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
