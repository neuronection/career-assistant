""": the OpenAPI contract is healthy and matches the repo.

The committed `contracts/openapi.json` is the drift gate (CI runs
`scripts/check-openapi.py --check`); these tests keep the schema
itself sane and fail in-suite on drift so local runs catch it too.
"""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
CONTRACT = REPO / "contracts" / "openapi.json"


def _check_openapi_module():
    spec = importlib.util.spec_from_file_location(
        "check_openapi", REPO / "scripts" / "check-openapi.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_openapi_schema_is_healthy():
    schema = _schema()
    assert schema["paths"], "no routes discovered"
    operation_ids = []
    for path, methods in schema["paths"].items():
        assert path.startswith("/"), path
        for method, operation in methods.items():
            assert operation.get("tags"), f"{method.upper()} {path} lacks tags"
            operation_id = operation.get("operationId")
            if operation_id:
                operation_ids.append(operation_id)
    assert len(operation_ids) == len(set(operation_ids)), "duplicate operationId"


def _schema() -> dict:
    from app.main import create_app

    return create_app().openapi()


def test_committed_contract_matches_live_schema():
    committed = json.loads(CONTRACT.read_text(encoding="utf-8"))
    live = _check_openapi_module().normalized_schema()
    assert committed == live, (
        "contracts/openapi.json is stale — run "
        "`backend/venv/bin/python scripts/check-openapi.py --update` "
        "in the same commit as the endpoint change"
    )
