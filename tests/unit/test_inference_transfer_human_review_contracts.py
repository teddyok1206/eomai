"""Pure human-review identity checks; no live user, Artifact read or publication."""

from __future__ import annotations

import ast
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from eom_catalog_contracts import inference_transfer_human_review as contract
from eom_catalog_contracts.inference_transfer_human_review import (
    HUMAN_REVIEW_BUNDLE_SCHEMA_REF,
    HUMAN_REVIEW_RECORD_SCHEMA_REF,
    MAX_HUMAN_COMMAND_BYTES,
    MAX_HUMAN_REVIEW_BYTES,
    InferenceTransferHumanBundleCommand,
    InferenceTransferHumanRecordCommand,
    InferenceTransferHumanReviewBundle,
    InferenceTransferHumanReviewRecord,
    parse_human_bundle,
    parse_human_bundle_command,
    parse_human_record,
    parse_human_record_command,
    validate_human_record_context,
)
from eom_catalog_contracts.item_inference_transfer import HumanTransferEvaluation
from eom_catalog_contracts.models import FrozenModel
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    catalog_schema_registry,
    load_schema,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError

from tests.unit.inference_transfer_fixtures import sha
from tests.unit.inference_transfer_human_review_fixtures import (
    human_bundle,
    human_bundle_command,
    human_record,
    human_record_command,
)
from tests.unit.inference_transfer_invocation_fixtures import rehash
from tests.unit.inference_transfer_snapshot_fixtures import snapshot_v3_record


def _bundle_body() -> dict[str, Any]:
    return human_bundle().model_dump(mode="json")


def _rehash_selection(body: dict[str, Any]) -> dict[str, Any]:
    """Hash test edits bottom-up without treating a valid hash as authorization."""
    selection = body["command"]["selection"]
    selection["comparison"] = rehash(selection["comparison"], "request_sha256")
    selection["snapshot_prepare"] = rehash(selection["snapshot_prepare"], "prepare_sha256")
    body["command"]["selection"] = rehash(selection, "submission_sha256")
    body["command"] = rehash(body["command"], "command_sha256")
    return rehash(body, "bundle_sha256")


def _rebind_pair(body: dict[str, Any]) -> dict[str, Any]:
    """Keep synthetic pair pointers exact after a deliberate source-profile edit."""
    pair = body["command"]["selection"]["comparison"]
    for position, field in enumerate(("left_profile", "right_profile")):
        source = body["sources"][position]
        profile = source["staged_entry"]["profile"]
        source["staged_entry"]["profile"] = rehash(profile, "profile_sha256")
        pointer = dict(source["index_entry"]["profile"])
        pointer["profile_sha256"] = source["staged_entry"]["profile"]["profile_sha256"]
        source["index_entry"]["profile"] = pointer
        pair[field] = pointer
    pair = rehash(pair, "request_sha256")
    body["command"]["selection"]["comparison"] = pair
    comparison = body["comparison"]
    comparison["comparison"] = pair
    result = comparison["result"]
    for field in ("request_id", "request_sha256", "left_profile", "right_profile", "rubric"):
        result[field] = pair[field]
    comparison["result"] = rehash(result, "result_sha256")
    body["comparison"] = rehash(comparison, "result_sha256")
    return _rehash_selection(body)


def test_schema_first_mirror_hash_and_nested_artifact_schema_ids() -> None:
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["item-inference-transfer-human-review"]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw) == resource.sha256
    schema = load_schema("item-inference-transfer-human-review")
    Draft202012Validator.check_schema(schema)
    resolver = catalog_schema_registry().resolver()
    assert resolver.lookup(HUMAN_REVIEW_BUNDLE_SCHEMA_REF).contents == schema["$defs"]["bundle"]
    assert resolver.lookup(HUMAN_REVIEW_RECORD_SCHEMA_REF).contents == schema["$defs"]["record"]


def test_predecessor_human_evaluation_schema_bytes_are_unchanged() -> None:
    resource = CATALOG_SCHEMA_RESOURCES["item-inference-transfer"]
    root = Path(__file__).resolve().parents[2]
    assert sha256_bytes((root / resource.canonical_path).read_bytes()) == (
        "sha256:79e197f598d5fadea0ef757208bd01f05783e83499317680ee804f43600fdff2"
    )
    assert HumanTransferEvaluation.model_fields["schema_version"].default == (
        "item-inference-transfer-human-evaluation/1.0"
    )


@pytest.mark.parametrize(
    "factory,parser,hash_field",
    [
        (human_bundle_command, parse_human_bundle_command, "command_sha256"),
        (human_bundle, parse_human_bundle, "bundle_sha256"),
        (human_record_command, parse_human_record_command, "command_sha256"),
        (human_record, parse_human_record, "record_sha256"),
    ],
)
def test_frozen_roundtrip_exact_canonical_hash(
    factory: Callable[[], FrozenModel],
    parser: Callable[[object], FrozenModel],
    hash_field: str,
) -> None:
    value = factory()
    body = value.model_dump(mode="json")
    assert parser(body) == value
    assert getattr(value, hash_field) == content_sha256(
        {field: child for field, child in body.items() if field != hash_field}
    )
    assert parser(dict(reversed(tuple(body.items())))) == value
    with pytest.raises(ValidationError):
        setattr(value, hash_field, sha("f"))


@pytest.mark.parametrize(
    "parser",
    [
        parse_human_bundle_command,
        parse_human_bundle,
        parse_human_record_command,
        parse_human_record,
    ],
)
@pytest.mark.parametrize("value", [None, [], "not-json", True])
def test_public_parsers_reject_non_objects(
    parser: Callable[[object], FrozenModel], value: object
) -> None:
    with pytest.raises(ValueError, match="JSON object"):
        parser(value)


@pytest.mark.parametrize("field", ["actor_id", "role", "permissions", "token", "source_commit"])
def test_command_does_not_accept_caller_authority_or_runtime_identity(field: str) -> None:
    body = rehash(
        human_bundle_command().model_dump(mode="json") | {field: "forged"}, "command_sha256"
    )
    with pytest.raises(SchemaValidationError):
        parse_human_bundle_command(body)
    with pytest.raises(ValidationError):
        InferenceTransferHumanBundleCommand.model_validate(body)


@pytest.mark.parametrize("field", ["bundle_id", "bundle_revision_id", "workflow_id"])
def test_logical_revision_and_workflow_id_types_do_not_collapse(field: str) -> None:
    body = human_bundle_command().model_dump(mode="json")
    body[field] = "artifact_" + "a" * 32
    with pytest.raises(SchemaValidationError):
        parse_human_bundle_command(rehash(body, "command_sha256"))


@pytest.mark.parametrize("timestamp", ["2026-10-10T18:00:00+09:00", "2026-10-10T18:00:00"])
def test_command_timestamp_must_be_fixed_utc(timestamp: str) -> None:
    body = human_bundle_command().model_dump(mode="json") | {"created_at": timestamp}
    with pytest.raises(SchemaValidationError):
        parse_human_bundle_command(rehash(body, "command_sha256"))
    with pytest.raises(ValidationError):
        InferenceTransferHumanBundleCommand.model_validate(rehash(body, "command_sha256"))


def test_timestamp_age_is_not_a_session_permission_check_in_pure_contract() -> None:
    body = human_bundle_command().model_dump(mode="json") | {"created_at": "2000-01-01T00:00:00Z"}
    value = parse_human_bundle_command(rehash(body, "command_sha256"))
    assert value.created_at.year == 2000
    # Actual future-time and current fresh-session checks belong to the owner.
    body["created_at"] = "2099-01-01T00:00:00Z"
    assert parse_human_bundle_command(rehash(body, "command_sha256")).created_at.year == 2099


def test_utc_schema_accepts_explicit_zero_offset_before_canonicalization() -> None:
    body = human_bundle_command().model_dump(mode="json")
    body["created_at"] = body["created_at"].replace("Z", "+00:00")
    # The wire's semantic content hash is the typed canonical UTC-Z form.
    parsed = parse_human_bundle_command(body)
    assert parsed.model_dump(mode="json")["created_at"].endswith("Z")


@pytest.mark.parametrize("reverse", [False, True])
def test_two_exact_sources_follow_selected_a_to_b_order(reverse: bool) -> None:
    value = human_bundle(reverse=reverse)
    assert parse_human_bundle(value.model_dump(mode="json")) == value
    assert value.sources[0].index_entry.profile == value.command.selection.comparison.left_profile
    assert value.sources[1].index_entry.profile == value.command.selection.comparison.right_profile


def test_reversing_sources_or_repeating_one_source_does_not_renumber_the_pair() -> None:
    body = _bundle_body()
    body["sources"].reverse()
    with pytest.raises(ValidationError, match="A-to-B order"):
        parse_human_bundle(rehash(body, "bundle_sha256"))
    body["sources"] = [body["sources"][0], body["sources"][0]]
    with pytest.raises(ValidationError, match="A-to-B order"):
        parse_human_bundle(rehash(body, "bundle_sha256"))


@pytest.mark.parametrize("count", [0, 1, 3])
def test_bundle_has_exactly_two_sources(count: int) -> None:
    body = _bundle_body()
    body["sources"] = [body["sources"][0]] * count
    with pytest.raises(SchemaValidationError):
        parse_human_bundle(rehash(body, "bundle_sha256"))


def test_bundle_rejects_pointer_only_comparison_without_reading_it_itself() -> None:
    body = _bundle_body()
    body["comparison"]["result_state"] = "POINTER_ONLY"
    body["comparison"]["result"] = None
    body["comparison"] = rehash(body["comparison"], "result_sha256")
    body = rehash(body, "bundle_sha256")
    with pytest.raises(SchemaValidationError):
        parse_human_bundle(body)
    with pytest.raises(ValidationError, match="member-verified"):
        InferenceTransferHumanReviewBundle.model_validate(body)


def test_other_workflow_or_selection_cannot_share_a_human_bundle() -> None:
    body = _bundle_body()
    body["command"]["workflow_id"] = "workflow_" + "f" * 32
    with pytest.raises(ValidationError, match="Workflow selection"):
        parse_human_bundle(_rehash_selection(body))
    body = _bundle_body()
    body["command"]["selection"]["comparison"]["rubric"]["rubric_sha256"] = sha("f")
    with pytest.raises(ValidationError, match="Workflow selection"):
        parse_human_bundle(_rehash_selection(body))


@pytest.mark.parametrize("field", ["access_policy_revision_id", "access_policy_sha256"])
def test_bundle_does_not_reinterpret_snapshot_policy(field: str) -> None:
    body = _bundle_body()
    body["command"]["selection"]["snapshot_prepare"][field] = (
        "accessrev_" + "f" * 32 if field.endswith("revision_id") else sha("f")
    )
    with pytest.raises(ValidationError, match="Graph or policy"):
        parse_human_bundle(_rehash_selection(body))


def test_comparison_graph_and_source_graph_are_both_exact() -> None:
    body = _bundle_body()
    body["comparison"]["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    body["comparison"] = rehash(body["comparison"], "result_sha256")
    with pytest.raises(ValidationError, match="Graph or policy"):
        parse_human_bundle(rehash(body, "bundle_sha256"))
    body = _bundle_body()
    profile = body["sources"][0]["staged_entry"]["profile"]
    profile["source_basis"]["graph_snapshot"]["graph_snapshot_revision_id"] = "graphrev_" + "f" * 32
    with pytest.raises(ValidationError, match="snapshot scope"):
        parse_human_bundle(_rebind_pair(body))


def test_same_hash_recaptured_with_unreleased_projection_version_is_rejected() -> None:
    body = _bundle_body()
    body["sources"][0]["staged_entry"]["profile"]["extraction"]["extractor_version"] = (
        "other-projection/1.0"
    )
    with pytest.raises(ValidationError, match="snapshot scope"):
        parse_human_bundle(_rebind_pair(body))


@pytest.mark.parametrize("content", [None, "", "  \n\t"])
def test_missing_or_blank_canonical_question_text_cannot_be_human_reviewed(
    content: str | None,
) -> None:
    body = _bundle_body()
    entry = body["sources"][0]["staged_entry"]
    if content is None:
        entry["content"] = None
        with pytest.raises(SchemaValidationError):
            parse_human_bundle(rehash(body, "bundle_sha256"))
    else:
        entry["content"]["text"] = content
        entry["content"]["text_sha256"] = content_sha256(content)
    with pytest.raises(ValidationError, match="canonical question text"):
        InferenceTransferHumanReviewBundle.model_validate(rehash(body, "bundle_sha256"))


def test_source_revision_and_full_source_hash_are_not_silently_replaced() -> None:
    body = _bundle_body()
    body["sources"][0]["source"]["artifact_member"]["artifact_revision_id"] = "rev_" + "f" * 32
    with pytest.raises(ValidationError, match="full source"):
        parse_human_bundle(rehash(body, "bundle_sha256"))


def test_full_v3_occurrence_chain_survives_core_v2_profile_materialization() -> None:
    body = _bundle_body()
    body["sources"][0] = snapshot_v3_record().model_dump(mode="json")
    value = parse_human_bundle(_rebind_pair(body))
    source = value.sources[0].source
    assert hasattr(source, "page_inputs")
    assert len(source.page_inputs) == 1
    assert value.sources[0].staged_entry is not None
    assert not hasattr(value.sources[0].staged_entry.profile.source_basis.source, "page_inputs")
    assert value.sources[0].index_entry.source_value_sha256 == content_sha256(
        source.model_dump(mode="json")
    )


def test_member_verified_flag_cannot_hide_mismatched_claim_facets() -> None:
    body = _bundle_body()
    body["comparison"]["result"]["mappings"][0]["left_claim_ids"] = ["transferclaim_decisive"]
    body["comparison"]["result"] = rehash(body["comparison"]["result"], "result_sha256")
    body["comparison"] = rehash(body["comparison"], "result_sha256")
    with pytest.raises(ValidationError, match="transfer facet"):
        parse_human_bundle(rehash(body, "bundle_sha256"))


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_path", "review.json"),
        ("schema_ref", HUMAN_REVIEW_RECORD_SCHEMA_REF),
        ("media_type", "text/plain"),
        ("artifact_revision_id", "latest"),
    ],
)
def test_evaluation_points_only_to_exact_bundle_member(field: str, value: str) -> None:
    body = human_record_command().model_dump(mode="json")
    body["bundle"][field] = value
    with pytest.raises(SchemaValidationError):
        parse_human_record_command(rehash(body, "command_sha256"))
    with pytest.raises(ValidationError):
        InferenceTransferHumanRecordCommand.model_validate(rehash(body, "command_sha256"))


def test_record_is_only_pointer_and_existing_evaluation_and_has_distinct_hashes() -> None:
    value = human_record()
    assert set(value.model_dump(mode="json")) == {
        "schema_version",
        "bundle",
        "evaluation",
        "record_sha256",
    }
    assert len(canonical_json_bytes(value.model_dump(mode="json"))) < MAX_HUMAN_COMMAND_BYTES
    assert value.bundle.sha256 != human_bundle().bundle_sha256
    assert value.record_sha256 != value.evaluation.evaluation_sha256
    validate_human_record_context(human_bundle(), value.evaluation)


@pytest.mark.parametrize("field", ["left_profile", "right_profile", "rubric", "reviewer_id"])
def test_human_evaluation_context_rejects_pair_rubric_or_reviewer_drift(field: str) -> None:
    value = human_record().evaluation
    body = value.model_dump(mode="json")
    if field == "reviewer_id":
        body[field] = "operator_other"
    elif field == "rubric":
        body[field]["rubric_sha256"] = sha("f")
    else:
        body[field]["profile_sha256"] = sha("f")
    changed = HumanTransferEvaluation.model_validate(rehash(body, "evaluation_sha256"))
    with pytest.raises(ValueError, match="pair, rubric or reviewer"):
        validate_human_record_context(human_bundle(), changed)


def test_model_hypothesis_does_not_turn_into_human_label_or_approval() -> None:
    bundle = human_bundle()
    assert bundle.comparison.result is not None
    assert bundle.comparison.result.assessment_kind == "MACHINE_HYPOTHESIS_NOT_HUMAN_VERIFICATION"
    assert not hasattr(bundle, "evaluation") and not hasattr(bundle, "approved")
    body = human_record().evaluation.model_dump(mode="json") | {
        "label": "UNDETERMINED",
        "where_helped": [],
    }
    changed = HumanTransferEvaluation.model_validate(rehash(body, "evaluation_sha256"))
    validate_human_record_context(bundle, changed)
    assert changed.label == "UNDETERMINED"


def test_nested_frozen_hash_and_construct_bypass_is_revalidated() -> None:
    value = human_bundle()
    command = value.command.model_copy(update={"command_sha256": sha("f")})
    body = rehash(
        value.model_dump(mode="json") | {"command": command.model_dump(mode="json")},
        "bundle_sha256",
    )
    with pytest.raises(ValidationError):
        InferenceTransferHumanReviewBundle.model_validate(body | {"command": command})
    evaluation = human_record().evaluation.model_copy(update={"evaluation_sha256": sha("f")})
    record_body = rehash(
        human_record().model_dump(mode="json") | {"evaluation": evaluation.model_dump(mode="json")},
        "record_sha256",
    )
    with pytest.raises(ValidationError):
        InferenceTransferHumanReviewRecord.model_validate(record_body | {"evaluation": evaluation})
    with pytest.raises(ValueError):
        validate_human_record_context(
            value.model_copy(update={"command": command}), human_record().evaluation
        )


def test_copied_snapshot_and_comparison_instances_do_not_skip_nested_validation() -> None:
    value = human_bundle()
    source = value.sources[0]
    assert source.staged_entry is not None
    forged_profile = source.staged_entry.profile.model_copy(update={"profile_sha256": sha("f")})
    forged_entry = source.staged_entry.model_copy(update={"profile": forged_profile})
    forged_source = source.model_copy(update={"staged_entry": forged_entry})
    body = value.model_dump(mode="json")
    body["sources"][0] = forged_source.model_dump(mode="json")
    body = rehash(body, "bundle_sha256")
    with pytest.raises(ValidationError):
        InferenceTransferHumanReviewBundle.model_validate(
            body | {"sources": (forged_source, value.sources[1])}
        )
    comparison = value.comparison.model_copy(update={"result_sha256": sha("f")})
    body = rehash(
        value.model_dump(mode="json") | {"comparison": comparison.model_dump(mode="json")},
        "bundle_sha256",
    )
    with pytest.raises(ValidationError):
        InferenceTransferHumanReviewBundle.model_validate(body | {"comparison": comparison})


def test_actual_two_mebibyte_bundle_bound_rejects_complete_multibyte_claims() -> None:
    body = _bundle_body()
    for source in body["sources"]:
        profile = source["staged_entry"]["profile"]
        template = profile["claims"][0]
        profile["claims"] = [
            *profile["claims"],
            *(
                template | {"claim_id": f"transferclaim_z{index:03d}", "text": "가" * 4000}
                for index in range(126)
            ),
        ]
    body = _rebind_pair(body)
    assert len(canonical_json_bytes(body)) > MAX_HUMAN_REVIEW_BYTES
    with pytest.raises(ValidationError, match="byte budget"):
        InferenceTransferHumanReviewBundle.model_validate(body)


def test_actual_command_byte_bound_is_not_a_unicode_character_count() -> None:
    body = human_record_command().model_dump(mode="json")
    evaluation = body["evaluation"]
    evaluation["where_helped"] = [f"{index:02d}" + "가" * 1998 for index in range(16)]
    body["evaluation"] = rehash(evaluation, "evaluation_sha256")
    body = rehash(body, "command_sha256")
    assert len(canonical_json_bytes(body)) > MAX_HUMAN_COMMAND_BYTES
    with pytest.raises(ValidationError, match="byte budget"):
        parse_human_record_command(body)


@pytest.mark.parametrize(
    "factory,parser,hash_field,bound_name",
    [
        (
            human_bundle_command,
            parse_human_bundle_command,
            "command_sha256",
            "MAX_HUMAN_COMMAND_BYTES",
        ),
        (human_bundle, parse_human_bundle, "bundle_sha256", "MAX_HUMAN_REVIEW_BYTES"),
        (
            human_record_command,
            parse_human_record_command,
            "command_sha256",
            "MAX_HUMAN_COMMAND_BYTES",
        ),
        (human_record, parse_human_record, "record_sha256", "MAX_HUMAN_REVIEW_BYTES"),
    ],
)
def test_actual_utf8_encoded_bound_and_hash_checks(
    monkeypatch: pytest.MonkeyPatch,
    factory: Callable[[], FrozenModel],
    parser: Callable[[object], FrozenModel],
    hash_field: str,
    bound_name: str,
) -> None:
    body = factory().model_dump(mode="json")
    assert len(canonical_json_bytes(body)) <= (
        MAX_HUMAN_COMMAND_BYTES if "COMMAND" in bound_name else MAX_HUMAN_REVIEW_BYTES
    )
    with pytest.raises(ValidationError, match="canonical human-review"):
        parser(body | {hash_field: sha("f")})
    monkeypatch.setattr(contract, bound_name, len(canonical_json_bytes(body)) - 1)
    with pytest.raises(ValidationError, match="byte budget"):
        parser(body)


def test_pure_contract_has_no_runtime_storage_authority_dependency() -> None:
    tree = ast.parse(Path(contract.__file__).read_text(encoding="utf-8"))
    names = {
        alias.name if isinstance(node, ast.Import) else node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in (node.names if isinstance(node, ast.Import) else [ast.alias(name="")])
    }
    forbidden = {
        "sqlalchemy",
        "subprocess",
        "socket",
        "http",
        "eom_orchestrator",
        "eom_catalog_service",
        "eom_api",
    }
    assert not {name.split(".")[0] for name in names}.intersection(forbidden)
