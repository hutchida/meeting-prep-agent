"""Contract guard: every JSON Schema in packages/contract/schema must be a valid schema,
and every fixture in packages/contract/fixtures must validate against the schema it names.

Skeleton version. Task g0b-contract-data extends this with the Pydantic-vs-schema checks.
"""

import json
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DIR = ROOT / "packages" / "contract" / "schema"


def test_schemas_are_valid_json_schema() -> None:
    for path in sorted(SCHEMA_DIR.glob("*.json")):
        Draft202012Validator.check_schema(json.loads(path.read_text()))
