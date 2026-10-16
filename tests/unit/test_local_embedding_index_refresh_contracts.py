"""Synthetic refresh contracts and old-lookup characterization; no model or live DB."""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_service import embedding_registry_application as registry
from eom_catalog_service.embedding_registry_ports import (
    EmbeddingRegistryCaller,
    EmbeddingRegistryLookup,
    EmbeddingRegistryVerificationPort,
)
from eom_identifiers import content_sha256, sha256_bytes
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_index_refresh import (
    INDEX_REFRESH_REQUEST_SCHEMA_SHA256,
    IndexRefreshContractError,
    index_refresh_request_bytes,
    parse_index_refresh_request,
    validate_index_refresh_request_basis,
)
from eom_workflow.local_embedding_request import (
    parse_local_embedding_executable_request,
    parse_local_embedding_service_workflow_request,
)
from eom_workflow.schemas import LocalEmbeddingAdmissionContractError
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session

from tests.unit.embedding_registry_application_fixtures import (
    MemoryRepository,
    MemorySession,
    SyntheticVerifier,
    capture_pair,
)
from tests.unit.inference_transfer_embedding_fixtures import (
    index_manifest,
    index_pointer,
    seal,
    source_binding,
)
from tests.unit.inference_transfer_fixtures import NOW, sha
from tests.unit.local_embedding_service_fixtures import service_fixture

ROOT = Path(__file__).resolve().parents[2]


def refresh_case(*, changed: bool = False):
    fixture = service_fixture()
    original = fixture.request
    bindings = tuple(
        sorted(
            (
                source_binding(entry, view=original.namespace.view, space=original.space)
                for entry in fixture.base.entries
            ),
            key=lambda value: value.source.item_revision_id,
        )
    )
    previous = None
    if changed:
        index = index_manifest(bindings[0], view=original.namespace.view, space=original.space)
        previous = index_pointer(index), index
    basis = {
        "reason": "INDEX_MEMBERSHIP_CHANGED" if changed else "MISSING_NAMESPACE_INDEX",
        "previous_index_manifest": None
        if previous is None
        else previous[0].model_dump(mode="json"),
        "previous_index_sha256": None if previous is None else previous[1].index_sha256,
        "eligible_source_set_sha256": fixture.base.plan.source_set_sha256,
        "eligible_source_count": len(fixture.base.plan.sources),
        "available_binding_set_sha256": content_sha256([b.binding_sha256 for b in bindings]),
        "available_binding_count": len(bindings),
    }
    body = seal(
        original.model_dump(mode="json")
        | {"schema_version": "local-embedding-workflow-request/1.3", "reconciliation_basis": basis},
        "request_sha256",
    )
    return fixture, body, bindings, previous


def test_closed_schema_mirror_and_pin_precede_behavior():
    name = "local-embedding-workflow-request-v1_3.schema.json"
    raw = (ROOT / "schemas/workflow" / name).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow/resources" / name).read_bytes()
    assert sha256_bytes(raw) == INDEX_REFRESH_REQUEST_SCHEMA_SHA256
    Draft202012Validator.check_schema(json.loads(raw))


@pytest.mark.parametrize("changed", [False, True])
def test_contract_roundtrip_preserves_plan_pointer_and_keeps_released_parser_strict(changed):
    fixture, body, bindings, previous = refresh_case(changed=changed)
    request = parse_index_refresh_request(body)
    assert request.source_plan == fixture.request.source_plan
    assert request.source_plan_sha256 == fixture.request.source_plan_sha256
    assert request.request_sha256 != fixture.request.request_sha256
    assert json.loads(index_refresh_request_bytes(request)) == body
    assert parse_index_refresh_request(request) == request
    validate_index_refresh_request_basis(
        request,
        eligible_source_set_sha256=fixture.base.plan.source_set_sha256,
        eligible_source_count=len(fixture.base.plan.sources),
        available_bindings=bindings,
        previous=previous,
    )
    assert parse_local_embedding_executable_request(body) == request
    assert parse_local_embedding_executable_request(request) == request
    # 1.2 bytes/meaning remain closed; parsing1.3 still grants no runtime authority.
    with pytest.raises(LocalEmbeddingAdmissionContractError):
        parse_local_embedding_service_workflow_request(body)


@pytest.mark.parametrize(
    "fault",
    ["missing_basis", "missing_version", "extra", "basis_extra", "copied_extra", "hash"],
)
def test_raw_schema_validation_rejects_missing_extra_copied_or_altered_values(fault):
    _, body, _, _ = refresh_case()
    if fault == "missing_basis":
        del body["reconciliation_basis"]
    elif fault == "missing_version":
        del body["schema_version"]
    elif fault == "extra":
        body["operator_role"] = "ADMIN"
    elif fault == "basis_extra":
        body["reconciliation_basis"]["authorized"] = True
    elif fault == "hash":
        body["request_sha256"] = sha("0")
    else:
        body = parse_index_refresh_request(body).model_copy(update={"operator_role": "ADMIN"})
    with pytest.raises(IndexRefreshContractError):
        parse_index_refresh_request(body)


@pytest.mark.parametrize("field", ["eligible_source_count", "available_binding_count"])
@pytest.mark.parametrize("value", [True, 0, 1025, "2", 2.0, None])
def test_counts_are_closed_strict_positive_bounded_integers(field, value):
    _, body, _, _ = refresh_case()
    body["reconciliation_basis"][field] = value
    with pytest.raises(IndexRefreshContractError):
        # The canonical serializer itself rejects floats. Pass this malformed
        # external value directly so the assertion exercises the actual parser.
        parse_index_refresh_request(body if type(value) is float else seal(body, "request_sha256"))


@pytest.mark.parametrize("fault", ["pair", "reason", "path", "schema", "media", "excess_coverage"])
def test_predecessor_reason_pointer_and_coverage_closure(fault):
    _, body, _, _ = refresh_case(changed=True)
    basis = body["reconciliation_basis"]
    if fault == "pair":
        basis["previous_index_sha256"] = None
    elif fault == "reason":
        basis["reason"] = "MISSING_NAMESPACE_INDEX"
    elif fault in {"path", "schema", "media"}:
        key, value = {
            "path": ("member_path", "latest.json"),
            "schema": ("schema_ref", "eom://schemas/workflow/request/99.0"),
            "media": ("media_type", "text/plain"),
        }[fault]
        basis["previous_index_manifest"][key] = value
    else:
        basis["available_binding_count"] = basis["eligible_source_count"] + 1
    with pytest.raises(IndexRefreshContractError):
        parse_index_refresh_request(seal(body, "request_sha256"))


@pytest.mark.parametrize(
    "fault",
    [
        "source_set",
        "source_count",
        "boolean_count",
        "binding_missing",
        "binding_order",
        "binding_duplicate",
        "previous_missing",
        "previous_hash",
        "previous_pointer",
    ],
)
def test_owner_resolved_scope_mismatch_is_explicit(fault):
    fixture, body, bindings, previous = refresh_case(changed=True)
    actual: dict[str, Any] = {
        "eligible_source_set_sha256": fixture.base.plan.source_set_sha256,
        "eligible_source_count": len(fixture.base.plan.sources),
        "available_bindings": bindings,
        "previous": previous,
    }
    if fault == "source_set":
        actual["eligible_source_set_sha256"] = sha("0")
    elif fault == "source_count":
        actual["eligible_source_count"] += 1
    elif fault == "boolean_count":
        actual["eligible_source_count"] = True
    elif fault == "binding_missing":
        actual["available_bindings"] = bindings[:1]
    elif fault == "binding_order":
        actual["available_bindings"] = bindings[::-1]
    elif fault == "binding_duplicate":
        actual["available_bindings"] = (bindings[0], bindings[0])
    elif fault == "previous_missing":
        actual["previous"] = None
    elif fault == "previous_hash":
        body["reconciliation_basis"]["previous_index_sha256"] = sha("0")
        body = seal(body, "request_sha256")
    else:
        assert previous is not None
        actual["previous"] = (
            ArtifactMemberPointer.model_validate(
                previous[0].model_dump(mode="json") | {"artifact_revision_id": "rev_" + "0" * 32}
            ),
            previous[1],
        )
    with pytest.raises(IndexRefreshContractError):
        validate_index_refresh_request_basis(parse_index_refresh_request(body), **actual)


def test_unchanged_selected_plan_can_have_a_genuinely_new_refresh_identity():
    _, body, _, _ = refresh_case()
    original = parse_index_refresh_request(body)
    changed = copy.deepcopy(body)
    changed["reconciliation_basis"]["eligible_source_set_sha256"] = sha("0")
    successor = parse_index_refresh_request(seal(changed, "request_sha256"))
    assert successor.source_plan == original.source_plan
    assert successor.source_plan_sha256 == original.source_plan_sha256
    assert successor.request_sha256 != original.request_sha256
    assert index_refresh_request_bytes(successor) != index_refresh_request_bytes(original)


def test_current_identical_membership_is_not_a_refresh_even_with_a_new_request_hash():
    fixture, body, bindings, _ = refresh_case(changed=True)
    index = index_manifest(
        *bindings, view=fixture.request.namespace.view, space=fixture.request.space
    )
    previous = index_pointer(index), index
    body["reconciliation_basis"].update(
        previous_index_manifest=previous[0].model_dump(mode="json"),
        previous_index_sha256=index.index_sha256,
    )
    request = parse_index_refresh_request(seal(body, "request_sha256"))
    with pytest.raises(IndexRefreshContractError):
        validate_index_refresh_request_basis(
            request,
            eligible_source_set_sha256=fixture.base.plan.source_set_sha256,
            eligible_source_count=len(fixture.base.plan.sources),
            available_bindings=bindings,
            previous=previous,
        )


def test_existing_bindings_do_not_prove_a_different_namespace_has_an_index(monkeypatch):
    """Real lookup code, synthetic metadata/IAM: reproduces the no-work premise."""
    session = MemorySession()
    command, capture = capture_pair()
    owner = SyntheticVerifier(capture)
    caller = EmbeddingRegistryCaller("operator_" + "1" * 32)
    monkeypatch.setattr(registry, "EmbeddingRegistryRepository", MemoryRepository)
    registry.register_embedding_index(
        cast(Session, session),
        caller,
        command,
        cast(EmbeddingRegistryVerificationPort, owner),
        now=NOW,
    )
    namespace = command.namespace.model_copy(
        update={"population_scope": "OCCURRENCE_BACKED_PAST_EXAM"}
    )
    query = EmbeddingRegistryLookup(
        command.corpus_id,
        namespace,
        command.graph_snapshot,
        command.policy_revision_id,
        command.policy_sha256,
    )
    result = registry.lookup_missing_embedding_bindings(
        cast(Session, session), caller, query, cast(EmbeddingRegistryVerificationPort, owner)
    )
    assert not result.missing and len(result.reusable_rows) == 1
    assert all(
        row.population_scope != namespace.population_scope
        for row in session.state["heads"].values()
    )


def test_refresh_contract_has_no_runtime_infrastructure_imports():
    module = ROOT / "packages/workflow/eom_workflow/local_embedding_index_refresh.py"
    imports = {
        node.module or ""
        for node in ast.walk(ast.parse(module.read_text()))
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        value.startswith(
            ("eom_orchestrator", "eom_catalog_service", "sqlalchemy", "torch", "subprocess")
        )
        for value in imports
    )
