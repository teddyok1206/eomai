from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

from eom_api.app import create_app
from eom_api.openapi import export_openapi

from tests.api.helpers import disconnected_services

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "api" / "openapi" / "eom-api-v1.openapi.json"
HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
AUTH_MUTATIONS = {
    "auth_login",
    "auth_refresh",
    "auth_logout",
    "auth_logout_all",
    "auth_change_password",
    # A device challenge is deliberately non-replayable secret material. A
    # lost response must not be reconstructed by an idempotency replay.
    "codex_auth_challenge_reveal",
}


def _operations(schema: dict[str, object]):
    paths = schema["paths"]
    assert isinstance(paths, dict)
    for path, path_item in paths.items():
        assert isinstance(path_item, dict)
        for method, operation in path_item.items():
            if method in HTTP_METHODS:
                assert isinstance(operation, dict)
                yield path, method, operation


def test_openapi_31_security_errors_idempotency_and_stable_ids() -> None:
    services = disconnected_services()
    try:
        schema = create_app(services).openapi()
    finally:
        services.engine.dispose()
    assert schema["openapi"].startswith("3.1.")
    scheme = schema["components"]["securitySchemes"]["OpaqueBearer"]
    assert scheme["scheme"] == "bearer"
    assert scheme["bearerFormat"] == "opaque"
    assert "jwt" not in json.dumps(schema).lower()
    operation_ids = [operation["operationId"] for _, _, operation in _operations(schema)]
    assert len(operation_ids) == len(set(operation_ids))
    for _, method, operation in _operations(schema):
        operation_id = operation["operationId"]
        if method in {"post", "put", "patch", "delete"} and operation_id not in AUTH_MUTATIONS:
            parameters = operation.get("parameters", [])
            assert any(
                parameter.get("in") == "header" and parameter.get("name") == "Idempotency-Key"
                for parameter in parameters
            ), operation_id
        for status, response in operation["responses"].items():
            if str(status).isdigit() and int(status) >= 400:
                assert "application/problem+json" in response["content"]


def test_openapi_export_is_deterministic(tmp_path: Path) -> None:
    services = disconnected_services()
    try:
        app = create_app(services)
        first = tmp_path / "first.openapi.json"
        second = tmp_path / "second.openapi.json"
        first_hash = export_openapi(app, first)
        app.openapi_schema = None
        second_hash = export_openapi(app, second)
    finally:
        services.engine.dispose()
    assert first.read_bytes() == second.read_bytes()
    assert first_hash == second_hash == hashlib.sha256(first.read_bytes()).hexdigest()


def test_committed_openapi_hash_matches() -> None:
    payload = CONTRACT.read_bytes()
    recorded = (CONTRACT.parent / "eom-api-v1.sha256").read_text(encoding="ascii").split()[0]
    assert hashlib.sha256(payload).hexdigest() == recorded


def test_breaking_change_detector() -> None:
    module_path = ROOT / "scripts" / "api" / "check_openapi_breaking.py"
    spec = importlib.util.spec_from_file_location("check_openapi_breaking", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    old = json.loads(CONTRACT.read_text(encoding="utf-8"))
    compatible = copy.deepcopy(old)
    compatible["paths"]["/api/v1/new-optional"] = {}
    assert module.breaking_changes(old, compatible) == []
    removed = copy.deepcopy(old)
    removed["paths"].pop("/api/v1/items")
    findings = module.breaking_changes(old, removed)
    assert any("endpoint deleted" in finding for finding in findings)
