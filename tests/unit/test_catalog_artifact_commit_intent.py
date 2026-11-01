"""The commit seal carries hashes, not Artifact bytes or recovery authority."""

import json
from copy import deepcopy
from importlib.resources import files
from pathlib import Path

import pytest
from eom_identifiers import content_sha256
from eom_protocol.artifact_commit_intent import CatalogFileSetCommitIntent
from jsonschema import Draft202012Validator
from pydantic import ValidationError


def intent_body():
    body = dict(
        schema_version="catalog-file-set-commit-intent/1.0",
        job_id="job_" + "1" * 32,
        artifact_id="artifact_" + "2" * 32,
        artifact_revision_id="rev_" + "3" * 32,
        request_sha256="sha256:" + "4" * 64,
        result_sha256="sha256:" + "5" * 64,
        manifest_sha256="sha256:" + "6" * 64,
        manifest_created_at="2026-11-01T02:01:43.386155Z",
        recovery_basis=None,
    )
    return body | {"intent_sha256": content_sha256(body)}


def test_packaged_commit_schema_matches_canonical_schema():
    schema = files("eom_protocol").joinpath("schemas/catalog-file-set-commit-intent-v1.schema.json")
    canonical = (
        Path(__file__).parents[2]
        / "schemas/orchestrator/catalog-file-set-commit-intent-v1.schema.json"
    )
    assert json.loads(schema.read_text()) == json.loads(canonical.read_text())
    Draft202012Validator.check_schema(json.loads(schema.read_text()))


@pytest.mark.parametrize("with_basis", [False, True])
def test_intent_round_trip_is_frozen_and_canonical(with_basis):
    body = intent_body()
    if with_basis:
        body["recovery_basis"] = dict(
            kind="PINNED_KNOWLEDGE_ACCEPTANCE",
            actor_id="operator_" + "7" * 32,
            source_basis_sha256="sha256:" + "8" * 64,
        )
        body["intent_sha256"] = content_sha256(
            {k: v for k, v in body.items() if k != "intent_sha256"}
        )
    intent = CatalogFileSetCommitIntent.model_validate(body)
    assert CatalogFileSetCommitIntent.model_validate(intent.model_dump(mode="json")) == intent
    assert CatalogFileSetCommitIntent.model_validate(intent) == intent
    with pytest.raises(ValidationError):
        intent.job_id = "job_" + "9" * 32


@pytest.mark.parametrize(
    "fault", ["extra", "hash", "missing", "family", "offset", "actor", "basis_extra", "oversized"]
)
def test_invalid_commit_intent_is_rejected_without_payload_leak(fault):
    body = intent_body()
    private_value = "DO_NOT_DISCLOSE_THIS_UNTRUSTED_PAYLOAD"
    if fault == "extra":
        body["payload"] = private_value
    elif fault == "hash":
        body["manifest_sha256"] = "sha256:" + "9" * 64
    elif fault == "missing":
        del body["job_id"]
    elif fault == "family":
        body["schema_version"] = private_value
    elif fault == "offset":
        body["manifest_created_at"] = "2026-11-01T11:01:43+09:00"
    elif fault in {"actor", "basis_extra"}:
        body["recovery_basis"] = dict(
            kind="PINNED_KNOWLEDGE_ACCEPTANCE",
            actor_id="operator_" + "7" * 32,
            source_basis_sha256="sha256:" + "8" * 64,
        )
        if fault == "actor":
            body["recovery_basis"]["actor_id"] = private_value
        else:
            body["recovery_basis"]["permission"] = private_value
    else:
        body["payload"] = private_value * 3000
    with pytest.raises(ValidationError) as caught:
        CatalogFileSetCommitIntent.model_validate(body)
    assert private_value not in str(caught.value)


@pytest.mark.parametrize("fault", ["extra", "hash", "nested_extra"])
def test_model_copy_does_not_bypass_schema(fault):
    body = deepcopy(intent_body())
    if fault == "nested_extra":
        body["recovery_basis"] = dict(
            kind="PINNED_KNOWLEDGE_ACCEPTANCE",
            actor_id="operator_" + "7" * 32,
            source_basis_sha256="sha256:" + "8" * 64,
        )
        body["intent_sha256"] = content_sha256(
            {k: v for k, v in body.items() if k != "intent_sha256"}
        )
    intent = CatalogFileSetCommitIntent.model_validate(body)
    if fault == "extra":
        intent = intent.model_copy(update={"payload": "forged"})
    elif fault == "hash":
        intent = intent.model_copy(update={"result_sha256": "sha256:" + "0" * 64})
    else:
        intent = intent.model_copy(
            update={
                "recovery_basis": intent.recovery_basis.model_copy(update={"permission": "forged"})
            }
        )
    with pytest.raises(ValidationError):
        CatalogFileSetCommitIntent.model_validate(intent)
