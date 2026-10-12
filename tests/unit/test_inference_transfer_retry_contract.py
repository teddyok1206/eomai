"""Pure successor-command contracts; no runtime, DB, worker or model invocation."""

from __future__ import annotations

import copy
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import inference_transfer_retry as retry
from eom_catalog_contracts.inference_transfer_invocation_v11 import (
    InferenceTransferPairSubmitRequestV11,
    parse_pair_submit_request_v11,
)
from eom_catalog_contracts.inference_transfer_retry import (
    MAX_TRANSFER_RETRY_BYTES,
    InferenceTransferPairRetryRequestV1,
    parse_pair_retry_request_v1,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_workflow.schemas import role_schema_bundle_hash
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_invocation_fixtures import rehash, submit_request

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_NAME = "item-inference-transfer-retry"
RETRY_SCHEMA_SHA = "sha256:1198bbd9071ec67b4e7a0a60f47149b7496ebbaba3686117c4420e58646f7f1b"
# Taken from the pre-retry HEAD's frozen registry using AST literals, never runtime Git.
OLD_RESOURCE_COUNT = 295
OLD_RESOURCE_SNAPSHOT_SHA = (
    "sha256:47815f7633440b84e6bc1893ed31b56dba312722c9a190be89c74b2b7d92447f"
)
FAILED_STEP_ID = "steprun_" + "4" * 32


def _selection() -> InferenceTransferPairSubmitRequestV11:
    body = submit_request().model_dump(mode="json")
    body["schema_version"] = "inference-transfer-pair-submit/1.1"
    return parse_pair_submit_request_v11(rehash(body, "submission_sha256"))


def _body(**updates: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema_version": "inference-transfer-pair-retry/1.0",
        "failed_step_run_id": FAILED_STEP_ID,
        "failed_attempt": 1,
        "selection": _selection().model_dump(mode="json"),
        "reason": "원 실패는 보존하고 동일 비교의 명시적 successor를 실행한다.",
    }
    body.update(updates)
    return rehash(body, "retry_sha256")


def _request() -> InferenceTransferPairRetryRequestV1:
    return parse_pair_retry_request_v1(_body())


def _copied_request(
    value: InferenceTransferPairRetryRequestV1, **updates: Any
) -> InferenceTransferPairRetryRequestV1:
    copied = value.model_copy(update=updates)
    if isinstance(updates.get("failed_attempt"), float):
        # A float has no canonical EOM digest; field validation must reject it before hashing.
        return copied
    body = copied.model_dump(mode="json", exclude={"retry_sha256"}, warnings=False)
    return copied.model_copy(update={"retry_sha256": content_sha256(body)})


def test_new_schema_is_registered_mirrored_hash_bound_2020_12() -> None:
    entry = CATALOG_SCHEMA_RESOURCES[SCHEMA_NAME]
    canonical = (ROOT / entry.canonical_path).read_bytes()
    packaged = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
    ).read_bytes()
    assert canonical == packaged
    assert sha256_bytes(canonical) == entry.sha256 == RETRY_SCHEMA_SHA
    assert entry.schema_version == "1.0"
    schema = load_schema(SCHEMA_NAME)
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"] == "eom://schemas/knowledge/item-inference-transfer-retry/1.0"
    assert schema["additionalProperties"] is False
    assert (
        set(schema["required"])
        == set(schema["properties"])
        == {
            "schema_version",
            "failed_step_run_id",
            "failed_attempt",
            "selection",
            "reason",
            "retry_sha256",
        }
    )
    assert schema["properties"]["selection"]["$ref"] == (
        "eom://schemas/knowledge/item-inference-transfer-invocation/1.1#/$defs/submitRequest"
    )
    Draft202012Validator.check_schema(schema)
    validate_contract(SCHEMA_NAME, _body())


def test_all_preexisting_catalog_resources_retain_metadata_and_exact_bytes() -> None:
    # These successors are not part of the frozen pre-retry resource inventory.
    additions = {SCHEMA_NAME, "item-inference-transfer-embedding"}
    old = {name: entry for name, entry in CATALOG_SCHEMA_RESOURCES.items() if name not in additions}
    assert len(old) == OLD_RESOURCE_COUNT
    # Compare the complete old identity snapshot before dereferencing any path.
    assert content_sha256({name: asdict(entry) for name, entry in old.items()}) == (
        OLD_RESOURCE_SNAPSHOT_SHA
    )
    for entry in old.values():
        canonical = (ROOT / entry.canonical_path).read_bytes()
        packaged = (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
        ).read_bytes()
        assert canonical == packaged
        assert sha256_bytes(canonical) == entry.sha256


def test_released_one_attempt_definition_and_role_bundles_are_unchanged() -> None:
    definition = ROOT / "config/workflows/item-inference-transfer-comparison.v1_1.yaml"
    assert sha256_bytes(definition.read_bytes()) == (
        "sha256:7b2e40cb7c4190905b445ea91646b13833df77d6ac2266a5117922d7f4f10246"
    )
    assert role_schema_bundle_hash("workflow-role/1.29.0") == (
        "sha256:fc65246c255e51d9500797abc976bc68d4a3eb81483301c132e098b74614f8dc"
    )
    assert role_schema_bundle_hash("workflow-role/1.30.0") == (
        "sha256:023510a8bb3071fd89336ee799725ec2a7335a2c2846f966e44353fbfcd2f800"
    )


def test_retry_is_a_small_frozen_value_with_exact_original_selection_not_authority() -> None:
    body = _body()
    before = copy.deepcopy(body)
    value = parse_pair_retry_request_v1(body)
    assert value.failed_step_run_id == FAILED_STEP_ID
    assert type(value.failed_attempt) is int and value.failed_attempt == 1
    assert value.selection == _selection()
    assert value.retry_sha256 == content_sha256(
        value.model_dump(mode="json", exclude={"retry_sha256"})
    )
    assert value.model_dump(mode="json") == before
    assert MAX_TRANSFER_RETRY_BYTES == 40 * 1024
    assert len(canonical_json_bytes(before)) < MAX_TRANSFER_RETRY_BYTES
    assert body == before
    for name in ("actor_id", "permissions", "workflow_id", "preset_id", "left_profile"):
        assert not hasattr(value, name)
    with pytest.raises(ValidationError, match="frozen"):
        value.reason = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        value.selection.expected_header_sha256 = sha("f")


@pytest.mark.parametrize("attempt", [True, False, 1.0, "1", None, 0, -1, 2])
def test_failed_attempt_is_exact_integer_one_without_numeric_coercion(attempt: object) -> None:
    body = _body()
    body["failed_attempt"] = attempt
    if not isinstance(attempt, float):
        body = rehash(body, "retry_sha256")
    with pytest.raises(ValidationError, match="exact integer one"):
        InferenceTransferPairRetryRequestV1.model_validate(body)
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(body)


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "synthetic-operator"),
        ("authority", "ADMIN"),
        ("role", "WORKER"),
        ("permissions", ["ALL"]),
        ("requester_permissions_sha256", sha("f")),
        ("workflow_id", "workflow_" + "f" * 32),
        ("preset_id", "execpreset_" + "f" * 32),
        ("preset_revision_id", "execpresetrev_" + "f" * 32),
        ("execution_preset_key", "customer-support"),
        ("model_candidate", {"model": "synthetic-model"}),
        ("workspace_path", "/synthetic/workspace"),
        ("storage_uri", "nas://synthetic/never-resolved"),
        ("result_path", "/synthetic/result.json"),
        ("left_profile", {"full_profile_bytes": "not admitted"}),
    ],
)
def test_extra_authority_paths_presets_or_profile_bytes_are_not_accepted(
    field: str, value: Any
) -> None:
    body = _body(**{field: value})
    with pytest.raises(SchemaValidationError):
        parse_pair_retry_request_v1(body)
    with pytest.raises(ValidationError):
        InferenceTransferPairRetryRequestV1.model_validate(body)


@pytest.mark.parametrize(
    "version",
    ["inference-transfer-pair-submit/1.0", "inference-transfer-pair-submit/1.2", "latest"],
)
def test_nested_selection_is_only_the_exact_v11_family(version: str) -> None:
    selection = _selection().model_dump(mode="json")
    selection["schema_version"] = version
    body = _body(selection=rehash(selection, "submission_sha256"))
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(body)
    with pytest.raises(ValidationError):
        InferenceTransferPairRetryRequestV1.model_validate(body)


@pytest.mark.parametrize(
    "path,value",
    [
        (("comparison", "left_profile", "profile_revision_id"), "current"),
        (("comparison", "left_profile", "profile_sha256"), sha("f")),
        (("comparison", "request_sha256"), sha("f")),
        (("snapshot_prepare", "access_policy_sha256"), sha("f")),
        (("expected_header_sha256",), sha("f")),
        (("submission_sha256",), sha("f")),
    ],
)
def test_outer_retry_hash_does_not_repair_nested_pointer_or_hash_mutation(
    path: tuple[str, ...], value: str
) -> None:
    selection = _selection().model_dump(mode="json")
    target = selection
    for segment in path[:-1]:
        target = target[segment]
    target[path[-1]] = value
    body = _body(selection=selection)
    before = copy.deepcopy(body)
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(body)
    assert body == before


@pytest.mark.parametrize("digest", [None, "", "not-a-hash", sha("f")])
def test_supplied_wrong_or_missing_self_hash_is_never_repaired(digest: object) -> None:
    body = _body() | {"retry_sha256": digest}
    before = copy.deepcopy(body)
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(body)
    assert body == before
    del body["retry_sha256"]
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(body)
    assert "retry_sha256" not in body


def test_hash_covers_failed_step_reason_and_complete_nested_selection() -> None:
    first = _request()
    changed_reason = parse_pair_retry_request_v1(_body(reason="명시적 이유가 달라졌다."))
    changed_step = parse_pair_retry_request_v1(_body(failed_step_run_id="steprun_" + "5" * 32))
    assert len({first.retry_sha256, changed_reason.retry_sha256, changed_step.retry_sha256}) == 3
    body = _body()
    body["reason"] = "old digest cannot cover changed reason"
    with pytest.raises(ValidationError, match="canonical retry command"):
        parse_pair_retry_request_v1(body)


@pytest.mark.parametrize("reason", ["", " \n\t", "x" * 513])
def test_reason_is_bounded_and_nonblank(reason: str) -> None:
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(_body(reason=reason))


@pytest.mark.parametrize("control", ["\x00", "\x01", "\x08", "\x0b", "\x0c", "\x1f"])
def test_reason_rejects_disallowed_controls_in_schema_and_frozen_model(control: str) -> None:
    body = _body(reason="합성 이유" + control + "보존")
    with pytest.raises(SchemaValidationError):
        validate_contract(SCHEMA_NAME, body)
    with pytest.raises(ValidationError, match="control character"):
        InferenceTransferPairRetryRequestV1.model_validate(body)


@pytest.mark.parametrize("reason", ["이유\t보존", "이유\n다음 줄", "이유\r다음 줄"])
def test_reason_preserves_permitted_tab_and_newline_values(reason: str) -> None:
    body = _body(reason=reason)
    before = copy.deepcopy(body)
    validate_contract(SCHEMA_NAME, body)
    value = InferenceTransferPairRetryRequestV1.model_validate(body)
    assert value.reason == reason
    assert value.model_dump(mode="json") == before
    assert body == before


def test_encoded_retry_byte_budget_checks_inclusive_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _body(reason="한" * 512)
    size = len(canonical_json_bytes(body))
    assert size < MAX_TRANSFER_RETRY_BYTES
    # Exercise the defensive budget guard with valid bounded content, not enlarged profiles.
    monkeypatch.setattr(retry, "MAX_TRANSFER_RETRY_BYTES", size)
    assert (
        len(canonical_json_bytes(parse_pair_retry_request_v1(body).model_dump(mode="json"))) == size
    )
    monkeypatch.setattr(retry, "MAX_TRANSFER_RETRY_BYTES", size - 1)
    with pytest.raises(ValidationError, match="fixed byte budget"):
        parse_pair_retry_request_v1(body)


@pytest.mark.parametrize(
    "updates",
    [
        {"failed_attempt": True},
        {"failed_attempt": 1.0},
        {"failed_attempt": "1"},
        {"failed_attempt": 2},
        {"failed_step_run_id": "current"},
        {"schema_version": "inference-transfer-pair-retry/2.0"},
        {"reason": " "},
    ],
)
def test_copied_or_constructed_instances_must_revalidate_all_fields(
    updates: dict[str, Any],
) -> None:
    copied = _copied_request(_request(), **updates)
    body = copied.model_dump(mode="json", warnings=False)
    constructed = InferenceTransferPairRetryRequestV1.model_construct(**body)
    for value in (copied, constructed):
        with pytest.raises(ValidationError):
            InferenceTransferPairRetryRequestV1.model_validate(value)
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(body)


def test_copied_nested_selection_cannot_bypass_v11_or_canonical_hash_validation() -> None:
    value = _request()
    selected = value.selection.model_copy(
        update={"schema_version": "inference-transfer-pair-submit/1.0"}
    )
    selected_body = selected.model_dump(mode="json", warnings=False)
    selected = selected.model_copy(
        update={
            "submission_sha256": content_sha256(
                {key: member for key, member in selected_body.items() if key != "submission_sha256"}
            )
        }
    )
    copied = _copied_request(value, selection=selected)
    with pytest.raises((SchemaValidationError, ValidationError)):
        InferenceTransferPairRetryRequestV1.model_validate(copied)
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(copied.model_dump(mode="json", warnings=False))


def test_public_retry_shape_does_not_accept_profile_context_or_authority_in_selection() -> None:
    selection = _selection().model_dump(mode="json")
    selection["actor_id"] = "synthetic-admin"
    body = _body(selection=rehash(selection, "submission_sha256"))
    with pytest.raises((SchemaValidationError, ValidationError)):
        parse_pair_retry_request_v1(body)
