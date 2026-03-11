import json
from pathlib import Path


def test_bundle_contract_schema_matches_expected_enums() -> None:
    schema_path = Path("contracts/repo_bundle.schema.json")
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    assert schema["properties"]["source_type"]["enum"] == ["github", "local"]
    assert schema["$defs"]["DocumentKind"]["enum"] == ["code", "documentation", "commit"]
    assert schema["$defs"]["SourceChunk"]["properties"]["start_line"]["minimum"] == 1
    assert schema["$defs"]["SourceChunk"]["properties"]["end_line"]["minimum"] == 1
