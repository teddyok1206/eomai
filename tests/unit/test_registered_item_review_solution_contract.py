"""Synthetic pointer validation only; no stored review, approval or source authorization."""

from __future__ import annotations

import ast
import copy
from pathlib import Path

import pytest
from eom_catalog_contracts.knowledge import ApprovedItemKnowledgeSourceV2
from eom_catalog_contracts.registered_item_review_solution import (
    MAX_REGISTERED_ITEM_REVIEW_SOLUTION_BYTES,
    REGISTERED_ITEM_REVIEW_SOLUTION_REF,
    REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA,
    RegisteredItemReviewRoleReference,
    RegisteredItemReviewSolutionEvidence,
    parse_registered_item_review_solution_evidence,
    registered_item_review_solution_evidence_bytes,
    registered_item_review_solution_evidence_sha256,
)
from eom_catalog_contracts.validation import (
    CATALOG_SCHEMA_RESOURCES,
    load_schema,
    validate_contract,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

ROOT = Path(__file__).resolve().parents[2]
INVALID = (ValueError, TypeError, SchemaError)


def _member(identity: str, member_path: str, schema_ref: str) -> dict:
    return {
        "artifact_id": "artifact_" + identity * 32,
        "artifact_revision_id": "rev_" + identity * 32,
        "member_path": member_path,
        "schema_ref": schema_ref,
        "media_type": "application/json",
        "sha256": "sha256:" + identity * 64,
    }


def evidence_body(version: str = "11.0") -> dict:
    """No persisted item or real report; hashes identify synthetic immutable fixtures."""
    content = _member(
        "1",
        "assessment-item-content.json",
        "eom://schemas/item-registry/assessment-item-content-v3",
    )
    value = {
        "schema_version": "registered-item-review-solution-evidence/1.0",
        "evidence_kind": "REGISTERED_ITEM_REVIEW_SOLUTION",
        "source": {
            "source_kind": "APPROVED_ITEM_REVISION",
            "source_class": "APPROVED_ITEM",
            "item_id": "item_" + "5" * 32,
            "item_revision_id": "itemrev_" + "6" * 32,
            "lifecycle_state": "APPROVED",
            "artifact_member": content
            | {
                "materialized_path": "source/item-content.json",
                "bytes": 128,
                "logical_name": "item-content.json",
            },
        },
        "workflow_id": "workflow_" + "7" * 32,
        "registration_step_run_id": "steprun_" + "8" * 32,
        "registration_manifest": _member(
            "2",
            "item-revision-manifest.json",
            "eom://schemas/item-registry/item-revision-manifest-v2",
        ),
        "item_content": content,
        "authoring": {
            "step_run_id": "steprun_" + "9" * 32,
            "step_key": "authoring",
            "attempt": 2,
            "job_id": "job_" + "a" * 32,
            "artifact": _member("3", "result.json", f"authoring-result@{version}"),
        },
        "review": {
            "step_run_id": "steprun_" + "b" * 32,
            "step_key": "review",
            "attempt": 2,
            "job_id": "job_" + "c" * 32,
            "artifact": _member("4", "result.json", f"review-result@{version}"),
        },
        "authoring_receipt_sha256": "sha256:" + "d" * 64,
        "review_receipt_sha256": "sha256:" + "e" * 64,
    }
    return value | {"evidence_sha256": content_sha256(value)}


def _seal(body: dict) -> dict:
    return body | {"evidence_sha256": registered_item_review_solution_evidence_sha256(body)}


def _replace(body: dict, path: tuple[str, ...], value: object) -> dict:
    changed = copy.deepcopy(body)
    parent = changed
    for name in path[:-1]:
        parent = parent[name]
    parent[path[-1]] = value
    return _seal(changed)


def test_schema_first_mirror_sha_and_draft202012_are_exact():
    resource = CATALOG_SCHEMA_RESOURCES[REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    assert (
        raw
        == (
            ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    schema = load_schema(REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA)
    assert schema["$id"] == REGISTERED_ITEM_REVIEW_SOLUTION_REF
    Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("version", ("11.0", "12.0"))
@pytest.mark.parametrize("manifest_version", ("v1", "v2"))
def test_closed_families_round_trip_and_hash_excludes_only_self(version, manifest_version):
    body = evidence_body(version)
    body["registration_manifest"]["schema_ref"] = (
        "eom://schemas/item-registry/item-revision-manifest-" + manifest_version
    )
    body = _seal(body)
    validate_contract(REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA, body)
    evidence = RegisteredItemReviewSolutionEvidence.model_validate(body)
    assert evidence.source == ApprovedItemKnowledgeSourceV2.model_validate(body["source"])
    assert RegisteredItemReviewSolutionEvidence.model_validate(evidence) == evidence
    assert registered_item_review_solution_evidence_sha256(evidence) == body["evidence_sha256"]
    raw = registered_item_review_solution_evidence_bytes(evidence)
    assert len(raw) < MAX_REGISTERED_ITEM_REVIEW_SOLUTION_BYTES
    assert raw == canonical_json_bytes(body)
    assert parse_registered_item_review_solution_evidence(raw) == evidence
    assert not hasattr(evidence, "assert_authorized")
    assert isinstance(evidence.item_content, ArtifactMemberPointer)


@pytest.mark.parametrize("field", tuple(evidence_body()))
def test_required_fields_are_not_hidden_constructor_defaults(field):
    body = evidence_body()
    del body[field]
    for validate in (
        lambda: validate_contract(REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA, body),
        lambda: RegisteredItemReviewSolutionEvidence.model_validate(body),
    ):
        with pytest.raises(INVALID):
            validate()


@pytest.mark.parametrize(
    "path,value",
    (
        (("schema_version",), "registered-item-review-solution-evidence/2.0"),
        (("evidence_kind",), "KNOWLEDGE_ANALYSIS"),
        (("workflow_id",), "workflow_not-an-id"),
        (("registration_step_run_id",), "job_" + "8" * 32),
        (("source", "source_class"), "PAST_EXAM"),
        (("source", "source_kind"), "CONTENT_INTAKE_FILE"),
        (("source", "lifecycle_state"), "PENDING"),
        (("source", "item_id"), "itemrev_" + "5" * 32),
        (("source", "artifact_member", "schema_ref"), None),
        (("source", "artifact_member", "media_type"), "application/pdf"),
        (("source", "artifact_member", "bytes"), True),
        (("authoring", "step_key"), "review"),
        (("review", "step_key"), "unknown_review"),
        (("authoring", "step_run_id"), "steprun_BAD"),
        (("authoring", "job_id"), "workflow_" + "a" * 32),
        (("authoring", "attempt"), True),
        (("authoring", "attempt"), "2"),
        (("review", "attempt"), 0),
        (("authoring", "artifact", "schema_ref"), "authoring-result@10.0"),
        (("review", "artifact", "schema_ref"), "review-result@12.0"),
        (("review", "artifact", "schema_ref"), "authoring-result@11.0"),
        (("review", "artifact", "member_path"), "other.json"),
        (("review", "artifact", "media_type"), "text/plain"),
        (("item_content", "member_path"), "../result.json"),
        (("item_content", "member_path"), "/result.json"),
        (("item_content", "member_path"), "a//result.json"),
        (("item_content", "member_path"), "a/./result.json"),
        (("item_content", "member_path"), "a\\result.json"),
        (("item_content", "member_path"), "result.json\x00"),
        (("item_content", "sha256"), "f" * 64),
        (("registration_manifest", "member_path"), "manifest.json"),
        (("registration_manifest", "schema_ref"), "eom://schemas/item-registry/unknown-v3"),
        (("registration_manifest", "media_type"), "image/png"),
        (("authoring_receipt_sha256",), "sha256:" + "A" * 64),
    ),
)
def test_structural_schema_and_pydantic_reject_the_same_closed_shapes(path, value):
    body = _replace(evidence_body(), path, value)
    with pytest.raises(INVALID):
        validate_contract(REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA, body)
    with pytest.raises(INVALID):
        RegisteredItemReviewSolutionEvidence.model_validate(body)


@pytest.mark.parametrize("pointer_field", tuple(ArtifactMemberPointer.model_fields))
def test_item_content_must_match_source_identity_not_its_workspace_location(pointer_field):
    body = evidence_body()
    other = _member("f", "other.json", "eom://schemas/item-registry/assessment-item-content-v2")
    if pointer_field == "media_type":
        # Media is already a schema constraint; the other five fields need domain equality.
        other[pointer_field] = "application/pdf"
    body = _replace(body, ("item_content", pointer_field), other[pointer_field])
    with pytest.raises(INVALID):
        RegisteredItemReviewSolutionEvidence.model_validate(body)


def test_materialization_location_is_not_canonical_identity():
    body = _replace(
        evidence_body(), ("source", "artifact_member", "materialized_path"), "source/other.json"
    )
    body = _replace(body, ("source", "artifact_member", "logical_name"), "alternate.json")
    assert RegisteredItemReviewSolutionEvidence.model_validate(body).item_content == (
        RegisteredItemReviewSolutionEvidence.model_validate(evidence_body()).item_content
    )


@pytest.mark.parametrize(
    "target,source",
    (
        (("review", "step_run_id"), ("authoring", "step_run_id")),
        (("registration_step_run_id",), ("authoring", "step_run_id")),
        (("registration_step_run_id",), ("review", "step_run_id")),
        (("review", "job_id"), ("authoring", "job_id")),
        (("review", "artifact", "artifact_id"), ("authoring", "artifact", "artifact_id")),
        (
            ("review", "artifact", "artifact_revision_id"),
            ("authoring", "artifact", "artifact_revision_id"),
        ),
        (("registration_manifest", "artifact_id"), ("authoring", "artifact", "artifact_id")),
        (("review_receipt_sha256",), ("authoring_receipt_sha256",)),
    ),
)
def test_semantic_cross_pointer_aliases_are_rejected_after_structural_validation(target, source):
    body = evidence_body()
    value = body
    for key in source:
        value = value[key]
    body = _replace(body, target, value)
    validate_contract(REGISTERED_ITEM_REVIEW_SOLUTION_SCHEMA, body)
    with pytest.raises(INVALID):
        RegisteredItemReviewSolutionEvidence.model_validate(body)


@pytest.mark.parametrize("field", ("text", "output", "answer", "token", "actor", "permission"))
@pytest.mark.parametrize("target", ("root", "authoring", "artifact", "source"))
def test_no_result_content_or_authority_is_embedded(field, target):
    body = evidence_body()
    parent = {
        "root": body,
        "authoring": body["authoring"],
        "artifact": body["review"]["artifact"],
        "source": body["source"],
    }[target]
    parent[field] = "forbidden"
    with pytest.raises(INVALID):
        RegisteredItemReviewSolutionEvidence.model_validate(_seal(body))


def test_self_hash_is_checked_and_unrelated_report_substitution_changes_it():
    body = evidence_body()
    body["review_receipt_sha256"] = "sha256:" + "f" * 64
    with pytest.raises(INVALID):
        RegisteredItemReviewSolutionEvidence.model_validate(body)
    assert (
        RegisteredItemReviewSolutionEvidence.model_validate(_seal(body)).evidence_sha256
        != (evidence_body()["evidence_sha256"])
    )


@pytest.mark.parametrize("fault", ("source", "pointer", "role", "extra", "missing"))
def test_model_construct_and_copy_cannot_skip_boundary_validation(fault):
    evidence = RegisteredItemReviewSolutionEvidence.model_validate(evidence_body())
    if fault == "source":
        invalid = evidence.model_copy(
            update={"source": evidence.source.model_copy(update={"source_class": "PAST_EXAM"})}
        )
    elif fault == "pointer":
        invalid = evidence.model_copy(
            update={
                "item_content": evidence.item_content.model_copy(update={"member_path": "../x"})
            }
        )
    elif fault == "role":
        invalid = evidence.model_copy(
            update={"review": evidence.review.model_copy(update={"attempt": True})}
        )
    elif fault == "extra":
        invalid = evidence.model_copy(update={"approval": True})
    else:
        invalid = RegisteredItemReviewSolutionEvidence.model_construct(
            schema_version=evidence.schema_version
        )
    with pytest.raises(INVALID):
        RegisteredItemReviewSolutionEvidence.model_validate(invalid)
    with pytest.raises(INVALID):
        registered_item_review_solution_evidence_bytes(invalid)


def test_standalone_role_model_revalidates_constructed_nested_pointer_and_extras():
    role = RegisteredItemReviewRoleReference.model_validate(evidence_body()["review"])
    invalid = role.model_copy(
        update={
            "artifact": role.artifact.model_copy(update={"schema_ref": "authoring-result@11.0"})
        }
    )
    with pytest.raises(INVALID):
        RegisteredItemReviewRoleReference.model_validate(invalid)
    with pytest.raises(INVALID):
        RegisteredItemReviewRoleReference.model_validate(role.model_copy(update={"secret": "x"}))


@pytest.mark.parametrize(
    "fault", ("whitespace", "duplicate", "trailing", "nonjson", "utf8", "oversized", "float")
)
def test_wire_parser_requires_bounded_canonical_json(fault):
    raw = canonical_json_bytes(evidence_body())
    if fault == "whitespace":
        raw = b" " + raw
    elif fault == "duplicate":
        raw = b'{"evidence_sha256":"sha256:' + b"a" * 64 + b'",' + raw[1:]
    elif fault == "trailing":
        raw += b"\n"
    elif fault == "nonjson":
        raw = b"{}{}"
    elif fault == "utf8":
        raw = b"\xff"
    elif fault == "oversized":
        raw = b" " * (MAX_REGISTERED_ITEM_REVIEW_SOLUTION_BYTES + 1)
    else:
        raw = raw.replace(b'"attempt":2', b'"attempt":2.0')
    with pytest.raises(INVALID):
        parse_registered_item_review_solution_evidence(raw)


def test_contract_dependency_direction_has_no_workflow_or_infrastructure_imports():
    source = (
        ROOT / "packages/catalog_contracts/eom_catalog_contracts/registered_item_review_solution.py"
    )
    tree = ast.parse(source.read_text())
    imports = [
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    ]
    assert all(
        not name.startswith(("eom_workflow", "eom_catalog_service", "sqlalchemy", "subprocess"))
        for name in imports
    )
