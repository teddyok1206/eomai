"""Maintenance execution-proof contracts; entirely synthetic, never live Codex calls."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from eom_identifiers import content_sha256, sha256_bytes
from eom_workflow.codex_compatibility import (
    CodexCompatibilityInvocation,
    CodexCompatibilityProbeResult,
    CodexCompatibilityReport,
    CodexCompatibilityRequest,
    compatibility_contract_sha256,
    compatibility_request_sha256,
    load_compatibility_invocation,
    load_compatibility_probe_result,
    load_compatibility_report,
    load_compatibility_request,
)
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES, validate_control_contract
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

HASH = "sha256:" + "a" * 64
NAMES = (
    "codex-compatibility-request",
    "codex-compatibility-report",
    "codex-compatibility-invocation",
    "codex-compatibility-probe-result",
)


def request_document() -> dict[str, Any]:
    return {
        "schema_version": "codex-compatibility-request/1.0",
        "run_id": "codexcompat_" + "1" * 32,
        "source_commit": "f" * 40,
        "created_at": "2026-10-10T00:00:00Z",
        "expires_at": "2026-10-10T02:00:00Z",
        "max_model_calls": 2,
        "cases": [
            {
                "case_id": "compatcase_" + digit * 32,
                "slot_id": slot,
                "binding_id": "authbinding_" + digit * 32,
                "assignment_revision_id": None,
                "expected_resource_version": 7,
                "model": "synthetic-model",
                "reasoning_effort": "medium",
            }
            for digit, slot in (("2", "01"), ("3", "02"))
        ],
    }


def report_document() -> dict[str, Any]:
    request = request_document()
    return {
        "schema_version": "codex-compatibility-report/1.0",
        "request": request,
        "request_sha256": content_sha256(request),
        "scope": "LIVE_EXECUTION_SMOKE",
        "quality_evaluated": False,
        "started_at": "2026-10-10T00:01:00Z",
        "completed_at": "2026-10-10T00:02:00Z",
        "runtime": {
            "cli_version": "0.147.0",
            "cli_launcher_sha256": HASH,
            "cli_binary_sha256": "sha256:" + "b" * 64,
            "worker_exec_sha256": "sha256:" + "c" * 64,
            "contract_sha256": compatibility_contract_sha256(),
        },
        "model_calls": 2,
        "cases": [
            {
                **case,
                "job_id": "job_" + digit * 32,
                "status": "PASS",
                "error_code": None,
                "invocation_sha256": HASH,
                "result_sha256": HASH,
                "elapsed_ms": 100,
            }
            for case, digit in zip(request["cases"], ("4", "5"), strict=True)
        ],
    }


def invocation_document() -> dict[str, Any]:
    request = request_document()
    case = request["cases"][0]
    value = {
        "schema_version": "codex-compatibility-invocation/1.0",
        "run_id": request["run_id"],
        "case_id": case["case_id"],
        "request_sha256": content_sha256(request),
        "job_id": "job_" + "4" * 32,
        "model": case["model"],
        "reasoning_effort": case["reasoning_effort"],
        "image_sha256": HASH,
    }
    return {**value, "invocation_sha256": content_sha256(value)}


def probe_document() -> dict[str, Any]:
    request = request_document()
    return {
        "schema_version": "codex-compatibility-probe-result/1.0",
        "run_id": request["run_id"],
        "case_id": request["cases"][0]["case_id"],
        "request_sha256": content_sha256(request),
        "arithmetic_sum": 43,
        "rectangle_count": 1,
        "outline_circle_count": 1,
        "left_shape": "square",
        "right_shape": "circle",
    }


@pytest.mark.parametrize("name", NAMES)
def test_compatibility_canonical_schemas_match_pinned_installed_resources(name: str) -> None:
    root = Path(__file__).resolve().parents[2]
    entry = CONTROL_SCHEMA_RESOURCES[name]
    canonical = (root / entry.canonical_path).read_bytes()
    packaged = (root / "packages/workflow/eom_workflow" / entry.resource_path).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == entry.sha256
    assert entry.schema_version == "1.0"


def test_exact_contract_pin_covers_all_four_resources() -> None:
    assert compatibility_contract_sha256() == content_sha256(
        {name: CONTROL_SCHEMA_RESOURCES[name].sha256 for name in NAMES}
    )


@pytest.mark.parametrize(
    "name,factory,model,loader",
    [
        (NAMES[0], request_document, CodexCompatibilityRequest, load_compatibility_request),
        (NAMES[1], report_document, CodexCompatibilityReport, load_compatibility_report),
        (
            NAMES[2],
            invocation_document,
            CodexCompatibilityInvocation,
            load_compatibility_invocation,
        ),
        (NAMES[3], probe_document, CodexCompatibilityProbeResult, load_compatibility_probe_result),
    ],
)
def test_schema_first_loaders_preserve_exact_wire_values(name, factory, model, loader) -> None:
    document = factory()
    validate_control_contract(name, document)
    parsed = loader(document)
    assert parsed == model.model_validate(document)
    assert parsed.model_dump(mode="json") == document
    with pytest.raises(ValidationError, match="frozen"):
        parsed.schema_version = "forged"
    with pytest.raises(SchemaValidationError):
        loader({**document, "provider_model_identity": "unverified-provider-claim"})


@pytest.mark.parametrize(
    "change",
    [
        {"run_id": "job_" + "1" * 32},
        {"source_commit": "main"},
        {"created_at": "2026-10-10T00:00:00+00:00"},
        {"created_at": "2026-10-10T09:00:00+09:00"},
        {"created_at": "2026-10-10T00:00:00"},
        {"max_model_calls": 0},
        {"max_model_calls": 65},
        {"max_model_calls": True},
        {"cases": []},
        {"cases": request_document()["cases"] * 33},
    ],
)
def test_request_bounds_reject_in_both_schema_and_model(change) -> None:
    document = {**request_document(), **change}
    with pytest.raises(SchemaValidationError):
        validate_control_contract(NAMES[0], document)
    with pytest.raises(ValidationError):
        CodexCompatibilityRequest.model_validate(document)


@pytest.mark.parametrize(
    "change",
    [
        {"case_id": "compatcase_BAD"},
        {"slot_id": "07"},
        {"binding_id": "codexbind_" + "2" * 32},
        {"expected_resource_version": 0},
        {"expected_resource_version": True},
        {"model": "model;command"},
        {"reasoning_effort": "max"},
        {"reasoning_effort": "ultra"},
        {"worker_authority": "ADMIN"},
    ],
)
def test_case_pins_and_efforts_are_closed(change) -> None:
    document = request_document()
    document["cases"][0].update(change)
    with pytest.raises(SchemaValidationError):
        validate_control_contract(NAMES[0], document)
    with pytest.raises(ValidationError):
        CodexCompatibilityRequest.model_validate(document)


@pytest.mark.parametrize("invalid", ["expired", "too_long", "budget", "id", "pair"])
def test_request_cross_field_invariants(invalid: str) -> None:
    document = request_document()
    if invalid == "expired":
        document["expires_at"] = document["created_at"]
    elif invalid == "too_long":
        document["expires_at"] = "2026-10-10T02:00:01Z"
    elif invalid == "budget":
        document["max_model_calls"] = 1
    elif invalid == "id":
        document["cases"][1]["case_id"] = document["cases"][0]["case_id"]
    else:
        document["cases"][1]["binding_id"] = document["cases"][0]["binding_id"]
    with pytest.raises(ValidationError):
        load_compatibility_request(document)


@pytest.mark.parametrize(
    "change",
    [
        {"scope": "NON_LIVE"},
        {"scope": "LIVE_ONE_SHOT"},
        {"quality_evaluated": True},
        {"quality_evaluated": 0},
        {"model_calls": -1},
        {"model_calls": 65},
        {"model_calls": True},
        {"completed_at": None},
        {"model_catalog": {}},
    ],
)
def test_report_never_confuses_catalog_nonlive_or_quality_with_execution(change) -> None:
    document = {**report_document(), **change}
    with pytest.raises(SchemaValidationError):
        validate_control_contract(NAMES[1], document)
    with pytest.raises(ValidationError):
        CodexCompatibilityReport.model_validate(document)


@pytest.mark.parametrize(
    "change",
    [
        {"invocation_sha256": None},
        {"result_sha256": None},
        {"error_code": "WORKER_EXEC_FAILED"},
        {"error_code": "unsafe arbitrary text"},
        {"elapsed_ms": -1},
        {"elapsed_ms": True},
        {"status": "FAILED"},
    ],
)
def test_passing_case_requires_bounded_exact_execution_evidence(change) -> None:
    document = report_document()
    document["cases"][0].update(change)
    with pytest.raises(SchemaValidationError):
        validate_control_contract(NAMES[1], document)
    with pytest.raises(ValidationError):
        CodexCompatibilityReport.model_validate(document)


def failed_report() -> dict[str, Any]:
    document = report_document()
    document["model_calls"] = 1
    document["cases"][0].update(status="FAIL", error_code="WORKER_EXEC_FAILED", result_sha256=None)
    document["cases"][1].update(
        status="NOT_RUN",
        error_code="PREVIOUS_FAILURE",
        invocation_sha256=None,
        result_sha256=None,
        elapsed_ms=0,
    )
    return document


def test_failed_execution_and_unexecuted_remainder_are_not_passing_or_recounted() -> None:
    parsed = load_compatibility_report(failed_report())
    assert parsed.model_calls == 1
    assert [case.status for case in parsed.cases] == ["FAIL", "NOT_RUN"]


@pytest.mark.parametrize(
    "index,change",
    [
        (0, {"error_code": None}),
        (0, {"error_code": "PREVIOUS_FAILURE"}),
        (0, {"invocation_sha256": None}),
        (1, {"error_code": None}),
        (1, {"error_code": "WORKER_EXEC_FAILED"}),
        (1, {"invocation_sha256": HASH}),
        (1, {"result_sha256": HASH}),
        (1, {"elapsed_ms": 1}),
    ],
)
def test_status_conditionals_are_enforced_without_python_validation(index, change) -> None:
    document = failed_report()
    document["cases"][index].update(change)
    with pytest.raises(SchemaValidationError):
        validate_control_contract(NAMES[1], document)
    with pytest.raises(ValidationError):
        CodexCompatibilityReport.model_validate(document)


@pytest.mark.parametrize(
    "invalid",
    ["request_hash", "order", "missing", "version", "model", "binding", "jobs", "count", "time"],
)
def test_report_rejects_identity_order_hash_and_call_count_mismatch(invalid: str) -> None:
    document = report_document()
    if invalid == "request_hash":
        document["request_sha256"] = HASH
    elif invalid == "order":
        document["cases"].reverse()
    elif invalid == "missing":
        document["cases"].pop()
    elif invalid == "version":
        document["cases"][0]["expected_resource_version"] += 1
    elif invalid == "model":
        document["cases"][0]["model"] = "other-model"
    elif invalid == "binding":
        document["cases"][0]["binding_id"] = "authbinding_" + "e" * 32
    elif invalid == "jobs":
        document["cases"][1]["job_id"] = document["cases"][0]["job_id"]
    elif invalid == "count":
        document["model_calls"] = 1
    else:
        document["completed_at"] = "2026-10-09T23:00:00Z"
    with pytest.raises(ValidationError):
        load_compatibility_report(document)


def test_a_conclusive_failure_cannot_be_followed_by_another_model_call() -> None:
    document = report_document()
    document["cases"][0].update(status="FAIL", error_code="WORKER_EXEC_FAILED")
    with pytest.raises(ValidationError, match="cannot resume"):
        load_compatibility_report(document)


@pytest.mark.parametrize("version", ["latest", "1.2.3-beta", "v1.2.3", "01.2.3"])
def test_report_pins_stable_exact_cli_version(version: str) -> None:
    document = report_document()
    document["runtime"]["cli_version"] = version
    with pytest.raises(SchemaValidationError):
        load_compatibility_report(document)


def test_request_hash_is_canonical_and_input_mutation_cannot_change_frozen_request() -> None:
    document = request_document()
    request = load_compatibility_request(document)
    before = compatibility_request_sha256(request)
    document["cases"][0]["model"] = "other-model"
    assert request.cases[0].model == "synthetic-model"
    assert compatibility_request_sha256(request) == before


@pytest.mark.parametrize("field", ["model", "request_sha256", "image_sha256", "job_id"])
def test_invocation_hash_protects_every_exact_execution_pin(field: str) -> None:
    document = invocation_document()
    document[field] = (
        "other-model"
        if field == "model"
        else ("job_" + "f" * 32 if field == "job_id" else "sha256:" + "f" * 64)
    )
    with pytest.raises(ValidationError, match="content hash differs"):
        load_compatibility_invocation(document)


def test_compatibility_invocation_cannot_impersonate_a_production_plan() -> None:
    document = {**invocation_document(), "plan_id": "execplan_" + "1" * 32}
    with pytest.raises(SchemaValidationError):
        load_compatibility_invocation(document)


@pytest.mark.parametrize(
    "change",
    [
        {"arithmetic_sum": -1},
        {"arithmetic_sum": 1001},
        {"arithmetic_sum": True},
        {"rectangle_count": 6},
        {"outline_circle_count": 6},
        {"left_shape": "hexagon"},
        {"answer_text": "unbounded text"},
    ],
)
def test_probe_result_is_a_closed_bounded_value(change) -> None:
    document = {**probe_document(), **change}
    with pytest.raises(SchemaValidationError):
        validate_control_contract(NAMES[3], document)
    with pytest.raises(ValidationError):
        CodexCompatibilityProbeResult.model_validate(document)


def test_probe_schema_never_forces_correct_arithmetic_or_vision_answers() -> None:
    document = deepcopy(probe_document())
    document.update(
        arithmetic_sum=44, rectangle_count=0, outline_circle_count=2, left_shape="triangle"
    )
    parsed = load_compatibility_probe_result(document)
    assert parsed.arithmetic_sum == 44 and parsed.left_shape == "triangle"
