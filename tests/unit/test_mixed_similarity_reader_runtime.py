"""Protected optional read2 selection, synthetic readonly IAM; no real operator grant."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.similarity_read import SimilarityContextReadRequest
from eom_catalog_contracts.similarity_read_v2 import SimilarityContextReadRequestV2
from eom_catalog_contracts.similarity_reader_configuration import (
    SimilarityReaderConfiguration,
    SimilarityReaderConfigurationV2,
    parse_similarity_reader_configuration,
    parse_similarity_reader_configuration_v2,
    require_mixed_similarity_reader_cohost,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_catalog_service import similarity_read_runtime as runtime
from eom_catalog_service import similarity_read_service as service_module
from eom_catalog_service.similarity_context_ports import SimilarityContextReadError
from eom_identifiers import canonical_json_bytes, sha256_bytes
from eom_identity_service import PostgresOperatorAuthorizationFence
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_mixed_similarity_contracts import mixed_context_body
from tests.unit.test_similarity_read_runtime import install_seams
from tests.unit.test_similarity_reader_configuration import document

ROOT = Path(__file__).resolve().parents[2]


def mixed_document():
    body = document()
    body["schema_version"] = "system-rag-similarity-reader-configuration/2.0"
    body["namespace"].update(
        projection_version="mixed-solution-comparison/2.0",
        population_scope="ALL_ADMITTED_GRAPH_ITEMS",
    )
    return body


def test_schema_first_additive_reader2_preserves_old_wire_and_exact_namespace():
    old = SimilarityReaderConfiguration.model_validate(document())
    old_raw = canonical_json_bytes(old)
    assert parse_similarity_reader_configuration(old_raw) == old
    for key in (
        "system-rag-similarity-reader-configuration",
        "system-rag-similarity-reader-configuration-v2",
    ):
        entry = CATALOG_SCHEMA_RESOURCES[key]
        raw = (ROOT / entry.canonical_path).read_bytes()
        assert (
            raw
            == (
                ROOT / "packages/catalog_contracts/eom_catalog_contracts" / entry.resource_path
            ).read_bytes()
        )
        assert sha256_bytes(raw) == entry.sha256
    raw = canonical_json_bytes(mixed_document())
    selected = parse_similarity_reader_configuration_v2(raw)
    assert type(selected) is SimilarityReaderConfigurationV2
    assert not isinstance(selected, SimilarityReaderConfiguration)
    assert require_mixed_similarity_reader_cohost(old, selected) is None
    assert selected.source_classes == old.source_classes
    with pytest.raises((ValueError, SchemaError)):
        parse_similarity_reader_configuration(raw)
    with pytest.raises((ValueError, SchemaError)):
        parse_similarity_reader_configuration_v2(old_raw)


@pytest.mark.parametrize(
    "fault",
    (
        "projection",
        "population",
        "recipe",
        "source",
        "role",
        "bool",
        "cuda",
        "extra",
        "nested",
        "newline",
        "duplicate",
        "budget",
    ),
)
def test_reader2_never_accepts_a_wrong_family_authority_or_ambiguous_bytes(fault):
    body = mixed_document()
    if fault == "projection":
        body["namespace"]["projection_version"] = "accepted-solution-comparison/1.0"
    elif fault == "population":
        body["namespace"]["population_scope"] = "OCCURRENCE_BACKED_PAST_EXAM"
    elif fault == "recipe":
        body["namespace"]["recipe_sha256"] = "sha256:" + "0" * 64
    elif fault == "source":
        body["source_classes"] = ["TEXTBOOK"]
    elif fault == "role":
        body["database_owner"]["role_name"] = "eom_catalog_manager_runtime"
    elif fault == "bool":
        body["database_owner"]["role_oid"] = True
    elif fault == "cuda":
        body["document_space"]["runtime"]["device"] = "CUDA"
    elif fault == "extra":
        body["operator_id"] = "operator_" + "a" * 32
    elif fault == "nested":
        body["namespace"]["permission"] = "ADMIN"
    raw = canonical_json_bytes(body)
    if fault == "newline":
        raw += b"\n"
    elif fault == "duplicate":
        raw = raw[:-1] + b',"schema_version":"system-rag-similarity-reader-configuration/2.0"}'
    elif fault == "budget":
        raw = b" " * 65537
    with pytest.raises((ValueError, SchemaError)):
        parse_similarity_reader_configuration_v2(raw)


@pytest.mark.parametrize(
    "fault",
    ("owner", "corpus", "controls", "bundle", "primary_extra", "mixed_extra", "nested_extra"),
)
def test_cohost_revalidates_same_actual_readonly_deployment_scope(fault):
    primary = SimilarityReaderConfiguration.model_validate(document())
    body = mixed_document()
    if fault == "owner":
        body["database_owner"]["role_oid"] += 1
    elif fault == "corpus":
        body["corpus_id"] = "corpus_" + "f" * 32
    elif fault == "controls":
        body["native_execution_policy"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "bundle":
        body["runtime_bundle"]["bundle_revision_id"] = "embeddingbundlerev_" + "f" * 32
    mixed = SimilarityReaderConfigurationV2.model_validate(body)
    if fault == "primary_extra":
        primary = primary.model_copy(update={"authority": "ADMIN"})
    elif fault == "mixed_extra":
        mixed = mixed.model_copy(update={"authority": "ADMIN"})
    elif fault == "nested_extra":
        mixed = mixed.model_copy(
            update={
                "database_owner": mixed.database_owner.model_copy(update={"authority": "ADMIN"})
            }
        )
    with pytest.raises(ValueError):
        require_mixed_similarity_reader_cohost(primary, mixed)


def configured(monkeypatch):
    c = install_seams(monkeypatch)
    raw = canonical_json_bytes(mixed_document())
    c.mixed_read = Mock(return_value=raw)
    c.mixed_hash = sha256_bytes(raw)
    monkeypatch.setattr(runtime, "read_mixed_similarity_reader_configuration", c.mixed_read)
    return c


def test_optional_factory_independently_inspects_both_catalog_readonly_owners(monkeypatch):
    c = configured(monkeypatch)
    service = runtime.build_catalog_similarity_context_reads(
        c.engine,
        mode="ENABLED",
        configuration_raw_sha256=sha256_bytes(c.raw),
        mixed_configuration_raw_sha256=c.mixed_hash,
    )
    assert service.owner is not service.mixed_owner
    assert (
        service.owner.configuration.registry.namespace.projection_version
        == "accepted-solution-comparison/1.0"
    )
    assert (
        service.mixed_owner.configuration.registry.namespace.projection_version
        == "mixed-solution-comparison/2.0"
    )
    assert (
        type(service.owner.identity)
        is type(service.mixed_owner.identity)
        is PostgresOperatorAuthorizationFence
    )
    assert service.owner.identity is not service.mixed_owner.identity
    assert service.owner.identity.owner == service.mixed_owner.identity.owner
    assert c.inspect.call_count == c.connect.call_count == 2
    c.mixed_read.assert_called_once_with(c.mixed_hash)
    assert not hasattr(service.mixed_owner, "resolve_claim")


@pytest.mark.parametrize("fault", ("owner", "file", "schema", "inspection", "rw_role"))
def test_optional_reader_never_borrows_primary_installation_or_query_write_role(monkeypatch, fault):
    c = configured(monkeypatch)
    if fault == "file":
        c.mixed_read.side_effect = OSError("synthetic private file path")
    elif fault == "schema":
        c.mixed_read.return_value = c.raw
    elif fault == "owner":
        body = mixed_document()
        body["database_owner"]["role_oid"] += 1
        c.mixed_read.return_value = canonical_json_bytes(body)
    elif fault == "inspection":
        c.inspect.side_effect = [None, ValueError("synthetic missing mixed readonly fence")]
    else:
        c.connection.scalar.side_effect = ["eom_catalog_manager_runtime", "eom_app"]
    with pytest.raises(runtime.SimilarityReaderRuntimeError):
        runtime.build_catalog_similarity_context_reads(
            c.engine,
            mode="ENABLED",
            configuration_raw_sha256=sha256_bytes(c.raw),
            mixed_configuration_raw_sha256=c.mixed_hash,
        )


def requests():
    body = mixed_context_body()
    common = {
        "operation": "READ_SIMILARITY_CONTEXT",
        "actor_id": "operator_" + "a" * 32,
        "selection": {
            "workflow_id": "workflow_" + "b" * 32,
            "workflow_request_sha256": "sha256:" + "b" * 64,
            "context_request_sha256": body["request"]["request_sha256"],
        },
    }
    return SimilarityContextReadRequest.model_validate(
        common | {"schema_version": "system-rag-similarity-read-request/1.0"}
    ), SimilarityContextReadRequestV2.model_validate(
        common | {"schema_version": "system-rag-similarity-read-request/2.0"}
    )


def test_exact_read_family_uses_only_its_request_local_owner_without_mutating_primary(monkeypatch):
    c = configured(monkeypatch)
    service = runtime.build_catalog_similarity_context_reads(
        c.engine,
        mode="ENABLED",
        configuration_raw_sha256=sha256_bytes(c.raw),
        mixed_configuration_raw_sha256=c.mixed_hash,
    )
    owners = []

    def select_original(session, owner, caller, selection):
        assert session.get_transaction() is not None
        owners.append(owner)
        raise SimilarityContextReadError("SOURCE_ACCESS_DENIED")

    monkeypatch.setattr(service_module, "select_completed_reference_query_request", select_original)
    original = service.owner
    for request in requests():
        with pytest.raises(SimilarityContextReadError):
            service.read(request)
    assert owners == [original, service.mixed_owner] and service.owner is original


def test_missing_optional_read2_denies_before_database_and_never_falls_back(monkeypatch):
    c = install_seams(monkeypatch)
    service = runtime.build_catalog_similarity_context_reads(
        c.engine, mode="ENABLED", configuration_raw_sha256=sha256_bytes(c.raw)
    )
    service.sessions = Mock()
    service.sessions.begin.side_effect = AssertionError("read2 must not use primary database")
    with pytest.raises(SimilarityContextReadError):
        service.read(requests()[1])
    service.sessions.begin.assert_not_called()
