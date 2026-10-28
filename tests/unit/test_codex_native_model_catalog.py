from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_identifiers import content_sha256
from eom_orchestrator.control_command_processor import (
    CodexControlCommandProcessor,
    _ObservationTarget,
)
from eom_orchestrator.control_commands import _terminalize_record
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.worker_auth import WorkerAuthObservation
from eom_orchestrator.worker_registry import WorkerSlot
from eom_orchestrator.worker_usage import _validate_observation
from eom_orchestrator.worker_usage_exec import (
    _catalog_snapshot,
    _normalized_model,
    _observation_document,
    _read_model_catalog,
    execute,
)
from eom_workflow import (
    CodexControlCommandResultV3,
    CodexControlCommandResultV4,
    CodexModelCatalogSnapshot,
    CodexUsageObservationV2,
    ModelCandidate,
    validate_control_contract,
)
from pydantic import ValidationError

COMMAND = "codexcmd_" + "1" * 32
BINDING = "authbinding_" + "2" * 32


def _native_model(model: str = "test-model", **updates: object) -> dict[str, object]:
    return {
        "id": model,
        "model": model,
        "displayName": "Test model",
        "hidden": False,
        "isDefault": True,
        "defaultReasoningEffort": "high",
        "supportedReasoningEfforts": [
            {"reasoningEffort": "high", "description": "provider description is discarded"},
            {"reasoningEffort": "ultra", "description": "not an EOM execution effort"},
        ],
        "inputModalities": ["text", "image"],
        "supportsPersonality": True,
        "privateProviderField": "must-not-survive",
    } | updates


def _usage(catalog: CodexModelCatalogSnapshot) -> dict[str, object]:
    return _observation_document(
        command_id=COMMAND,
        binding_id=BINDING,
        slot_id="01",
        account_result={"account": {"type": "chatgpt", "planType": "plus", "email": "private"}},
        usage_result={"rateLimits": {"primary": {"usedPercent": 10}}},
        model_catalog=catalog,
    )


def _responses(monkeypatch: pytest.MonkeyPatch, pages: list[object]) -> list[dict[str, object]]:
    requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        "eom_orchestrator.worker_usage_exec._write_request",
        lambda _process, request: requests.append(request),
    )
    remaining = iter(pages)

    def read(_process: object, ids: frozenset[int], *, deadline: float) -> dict[int, object]:
        assert deadline == 123.0
        return {next(iter(ids)): next(remaining)}

    monkeypatch.setattr("eom_orchestrator.worker_usage_exec._read_responses", read)
    return requests


def test_native_catalog_pagination_is_bounded_sanitized_and_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests = _responses(
        monkeypatch,
        [
            {"data": [_native_model("z-model")], "nextCursor": "page-two"},
            {"data": [_native_model("a-model")], "nextCursor": None},
        ],
    )
    catalog = _read_model_catalog(SimpleNamespace(), cli_version="0.160.0", deadline=123.0)
    assert catalog.state == "OBSERVED"
    assert tuple(model.id for model in catalog.models) == ("a-model", "z-model")
    assert catalog.valid_until - catalog.observed_at == timedelta(hours=1)
    assert requests == [
        {"id": 3, "method": "model/list", "params": {"limit": 20, "includeHidden": False}},
        {
            "id": 4,
            "method": "model/list",
            "params": {"limit": 20, "includeHidden": False, "cursor": "page-two"},
        },
    ]
    payload = catalog.model_dump_json()
    assert "must-not-survive" not in payload
    assert "description" not in payload
    assert "ultra" in catalog.models[0].supported_reasoning_efforts
    for unsupported_effort in ("max", "ultra"):
        with pytest.raises(ValidationError):
            ModelCandidate(model="a-model", reasoning_effort=unsupported_effort)
    document = _usage(catalog)
    validate_control_contract("codex-usage-observation-v2", document)
    observation = _validate_observation(
        document,
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        command_id=COMMAND,
        binding_id=BINDING,
    )
    assert isinstance(observation, CodexUsageObservationV2)


@pytest.mark.parametrize(
    "pages",
    [
        [{"data": [_native_model(), _native_model()], "nextCursor": None}],
        [{"data": [_native_model(hidden="false")], "nextCursor": None}],
        [{"data": [_native_model(displayName="unsafe\nname")], "nextCursor": None}],
        [{"data": [_native_model(defaultReasoningEffort="low")], "nextCursor": None}],
        [{"data": [_native_model(inputModalities=["text", "text"])], "nextCursor": None}],
        [{"data": [], "nextCursor": "again"}, {"data": [], "nextCursor": "again"}],
        [{"data": [], "nextCursor": "x" * 513}],
        [{"data": [_native_model(str(i)) for i in range(21)], "nextCursor": None}],
        [
            {
                "data": [_native_model(f"model-{page}-{i}") for i in range(17)],
                "nextCursor": str(page) if page < 3 else None,
            }
            for page in range(4)
        ],
        [{"data": [], "nextCursor": str(i)} for i in range(4)],
        [{"data": [], "nextCursor": str(i)} for i in range(5)],
    ],
)
def test_native_catalog_invalid_pages_are_explicit_not_partial(
    monkeypatch: pytest.MonkeyPatch, pages: list[object]
) -> None:
    _responses(monkeypatch, pages)
    catalog = _read_model_catalog(SimpleNamespace(), cli_version="0.160.0", deadline=123.0)
    assert catalog.state == "UNAVAILABLE"
    assert catalog.models == ()
    assert catalog.reason_code == "CODEX_MODEL_CATALOG_INVALID"
    assert CodexUsageObservationV2.model_validate(_usage(catalog)).windows[0].used_percent == 10


def test_catalog_serialized_metadata_limit_rejects_large_valid_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    efforts = ["e" * 30 + str(i) for i in range(10)]
    models = [
        _native_model(
            "m" * 120 + str(i),
            displayName="과" * 128,
            defaultReasoningEffort=efforts[0],
            supportedReasoningEfforts=[{"reasoningEffort": effort} for effort in efforts],
            inputModalities=["a" * 30 + str(i) for i in range(8)],
        )
        for i in range(60)
    ]
    pages = [
        {"data": models[page * 20 : (page + 1) * 20], "nextCursor": str(page) if page < 2 else None}
        for page in range(3)
    ]
    _responses(monkeypatch, pages)
    catalog = _read_model_catalog(SimpleNamespace(), cli_version="0.160.0", deadline=123.0)
    assert catalog.state == "UNAVAILABLE"
    assert catalog.models == ()
    assert catalog.reason_code == "CODEX_MODEL_CATALOG_INVALID"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [(TimeoutError, "CODEX_MODEL_CATALOG_TIMEOUT"), (OSError, "CODEX_MODEL_CATALOG_UNAVAILABLE")],
)
def test_native_catalog_failure_does_not_discard_usage(
    monkeypatch: pytest.MonkeyPatch, failure: type[Exception], reason: str
) -> None:
    monkeypatch.setattr("eom_orchestrator.worker_usage_exec._write_request", lambda *args: None)

    def read(*args: Any, **kwargs: Any) -> None:
        raise failure("must-not-survive")

    monkeypatch.setattr("eom_orchestrator.worker_usage_exec._read_responses", read)
    catalog = _read_model_catalog(SimpleNamespace(), cli_version="0.160.0", deadline=123.0)
    assert catalog.reason_code == reason
    assert "must-not-survive" not in catalog.model_dump_json()
    assert CodexUsageObservationV2.model_validate(_usage(catalog)).account_type == "chatgpt"


def test_native_catalog_hash_freshness_and_result_identity_are_validated() -> None:
    catalog = _catalog_snapshot(
        cli_version="0.160.0", models=(_normalized_model(_native_model()),), reason_code=None
    )
    with pytest.raises(ValidationError, match="hash differs"):
        CodexModelCatalogSnapshot.model_validate(
            catalog.model_dump(mode="json") | {"catalog_sha256": "sha256:" + "f" * 64}
        )
    document = _usage(catalog)
    args = {
        "slot": WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        "command_id": COMMAND,
        "binding_id": BINDING,
    }
    with pytest.raises(ControlPlaneError, match="stale"):
        _validate_observation(document, **args, as_of=catalog.valid_until)
    with pytest.raises(ControlPlaneError, match="stale"):
        _validate_observation(document, **args, as_of=catalog.observed_at - timedelta(seconds=6))
    observation = CodexUsageObservationV2.model_validate(document)
    record = SimpleNamespace(
        command_id=COMMAND,
        command_type="OBSERVE",
        binding_id=BINDING,
    )
    _terminalize_record(
        record,
        outcome="SUCCEEDED",
        result_resource_version=2,
        binding_state="READY",
        reason_code=None,
        processed_at=datetime.now(UTC),
        usage_observation=observation,
    )
    validate_control_contract("codex-control-command-result-v3", record.result_document)
    result = CodexControlCommandResultV3.model_validate(record.result_document)
    assert result.usage_observation.model_catalog == catalog
    assert result.result_sha256 == content_sha256(
        {key: value for key, value in record.result_document.items() if key != "result_sha256"}
    )
    with pytest.raises(ValidationError, match="differs from its control command"):
        CodexControlCommandResultV3.model_validate(
            record.result_document | {"binding_id": "authbinding_" + "3" * 32}
        )


def test_degraded_capability_can_report_exhausted_usage_without_claiming_ready() -> None:
    catalog = _catalog_snapshot(
        cli_version="0.160.0", models=(), reason_code="CODEX_MODEL_CATALOG_UNAVAILABLE"
    )
    document = _observation_document(
        command_id=COMMAND,
        binding_id=BINDING,
        slot_id="01",
        account_result={"account": {"type": "chatgpt", "planType": "plus"}},
        usage_result={"rateLimits": {"primary": {"usedPercent": 100}}},
        model_catalog=catalog,
    )
    observation = CodexUsageObservationV2.model_validate(document)
    record = SimpleNamespace(command_id=COMMAND, command_type="OBSERVE", binding_id=BINDING)
    _terminalize_record(
        record,
        outcome="SUCCEEDED",
        result_resource_version=2,
        binding_state="DEGRADED",
        reason_code=None,
        processed_at=datetime.now(UTC),
        usage_observation=observation,
    )
    validate_control_contract("codex-control-command-result-v4", record.result_document)
    result = CodexControlCommandResultV4.model_validate(record.result_document)
    assert result.binding_state == "DEGRADED"
    assert result.usage_observation.windows[0].used_percent == 100
    with pytest.raises(ValidationError):
        CodexControlCommandResultV3.model_validate(record.result_document)


def test_capability_failure_preserves_independent_login_probe_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_at = datetime.now(UTC)
    target = _ObservationTarget(
        binding_id=BINDING,
        expected_resource_version=1,
        slot=WorkerSlot(slot_id="01", linux_user="eom-cdx-01", role="authoring", enabled=True),
        account_label="test-account",
    )

    def auth(**_kwargs: object) -> WorkerAuthObservation:
        return WorkerAuthObservation(
            binding_id=BINDING,
            slot_key="slot01",
            account_label="test-account",
            state="READY",
            reason_code=None,
            codex_cli_version="0.160.0",
            observed_at=observed_at,
            valid_until=observed_at + timedelta(hours=1),
            probe_unit_name="eom-worker-auth-01.service",
        )

    def capability_failure(_path: Path) -> None:
        raise ControlPlaneError("CONTROL_CAPABILITY_POLICY_MISMATCH", "test-only failure")

    monkeypatch.setattr("eom_orchestrator.control_command_processor.observe_worker_auth", auth)
    monkeypatch.setattr(
        "eom_orchestrator.control_command_processor.load_reviewed_capability_policy",
        capability_failure,
    )
    processor = CodexControlCommandProcessor(
        None,  # type: ignore[arg-type] - this direct observation does not open a session
        capability_policy_path=Path("/test/policy.yaml"),
        runner_id="test-observer",
    )
    collected = processor._collect_observation(target=target, observed_at=observed_at)
    assert collected.auth_probe_ready is True
    assert collected.auth.state == "DEGRADED"
    assert collected.auth.reason_code == "CAPABILITY_OBSERVATION_FAILED"


def test_native_observer_executes_only_fixed_read_rpc_methods(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    requests: list[dict[str, object]] = []
    monkeypatch.setattr(
        "eom_orchestrator.worker_usage_exec._validate_identity",
        lambda _slot: (tmp_path, tmp_path / ".codex", tmp_path),
    )
    monkeypatch.setattr("eom_orchestrator.worker_usage_exec._validate_codex_binary", lambda: None)
    monkeypatch.setattr(
        "eom_orchestrator.worker_usage_exec._codex_cli_version", lambda _env: "0.160.0"
    )
    monkeypatch.setattr(
        "eom_orchestrator.worker_usage_exec.subprocess.Popen", lambda *a, **k: object()
    )
    monkeypatch.setattr("eom_orchestrator.worker_usage_exec._terminate", lambda _process: None)
    monkeypatch.setattr(
        "eom_orchestrator.worker_usage_exec._write_request",
        lambda _process, request: requests.append(request),
    )

    def read(_process: object, ids: frozenset[int], *, deadline: float) -> dict[int, object]:
        values = {
            0: {},
            1: {"account": {"type": "chatgpt", "planType": "plus", "email": "private"}},
            2: {"rateLimits": {"primary": {"usedPercent": 10}}},
            3: {"data": [_native_model()], "nextCursor": None},
        }
        return {request_id: values[request_id] for request_id in ids}

    monkeypatch.setattr("eom_orchestrator.worker_usage_exec._read_responses", read)
    assert execute("01", COMMAND, BINDING) == 0
    assert [request["method"] for request in requests] == [
        "initialize",
        "initialized",
        "account/read",
        "account/rateLimits/read",
        "model/list",
    ]
    raw = json.loads((tmp_path / f"{COMMAND}.json").read_bytes())
    assert CodexUsageObservationV2.model_validate(raw).model_catalog.models[0].model == "test-model"
    assert "private" not in json.dumps(raw)
