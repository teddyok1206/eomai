"""Closed installed controls only; no real operator, storage or execution grant."""

from copy import deepcopy
from pathlib import Path

import pytest
from eom_catalog_contracts.similarity_reader_configuration import (
    parse_similarity_reader_configuration,
    parse_similarity_reader_configuration_v2,
)
from eom_catalog_contracts.similarity_reader_routed_configuration import (
    RoutedSimilarityReaderConfiguration,
    parse_similarity_reader_installed_selection,
    require_same_routed_reader_controls,
    routed_similarity_reader_configuration_bytes,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.test_mixed_similarity_reader_runtime import mixed_document
from tests.unit.test_reference_query_execution_contracts import case
from tests.unit.test_similarity_reader_configuration import document


def routed_document(*, mixed=False):
    cuda = case(device="CUDA")
    return dict(
        schema_version="system-rag-similarity-reader-configuration/3.0",
        cpu_configuration=mixed_document() if mixed else document(),
        cuda_document_space=cuda.policy.spaces.document.model_dump(mode="json"),
        cuda_native_execution_policy=cuda.request.native_execution_policy.model_dump(mode="json"),
        cuda_native_execution_policy_sha256=cuda.policy.policy_sha256,
        cuda_runtime_bundle=cuda.request.runtime_bundle.model_dump(mode="json"),
    )


@pytest.mark.parametrize("mixed", [False, True])
def test_schema_first_wrapper_preserves_closed_predecessors_and_canonical_bytes(mixed):
    root = Path(__file__).resolve().parents[2]
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-similarity-reader-configuration-v3"]
    raw_schema = (root / resource.canonical_path).read_bytes()
    assert (
        raw_schema
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert sha256_bytes(raw_schema) == resource.sha256
    selected = RoutedSimilarityReaderConfiguration.model_validate(routed_document(mixed=mixed))
    raw = routed_similarity_reader_configuration_bytes(selected)
    base, parsed = parse_similarity_reader_installed_selection(raw)
    assert base == selected.cpu_configuration and parsed == selected
    old = canonical_json_bytes(base)
    assert parse_similarity_reader_installed_selection(old) == (base, None)
    for decoder in (
        parse_similarity_reader_configuration,
        parse_similarity_reader_configuration_v2,
    ):
        with pytest.raises((ValueError, SchemaError)):
            decoder(raw)


@pytest.mark.parametrize(
    "fault",
    [
        "extra",
        "nested",
        "same_policy",
        "same_bundle",
        "cpu_as_cuda",
        "wrong_member",
        "unknown_family",
        "newline",
        "duplicate",
        "oversize",
        "roles",
        "bool",
    ],
)
def test_wrong_authority_device_and_ambiguous_bytes_never_select_an_owner(fault):
    body = routed_document()
    if fault == "extra":
        body["actor_id"] = "operator_" + "a" * 32
    elif fault == "nested":
        body["cpu_configuration"]["roles"] = ["ADMIN"]
    elif fault == "same_policy":
        body["cuda_native_execution_policy"] = body["cpu_configuration"]["native_execution_policy"]
    elif fault == "same_bundle":
        body["cuda_runtime_bundle"] = body["cpu_configuration"]["runtime_bundle"]
    elif fault == "cpu_as_cuda":
        body["cuda_document_space"] = body["cpu_configuration"]["document_space"]
    elif fault == "wrong_member":
        body["cuda_native_execution_policy"]["member_path"] = "arbitrary.json"
    elif fault == "unknown_family":
        body["schema_version"] = "system-rag-similarity-reader-configuration/4.0"
    elif fault == "roles":
        body["cuda_runtime_bundle"]["authority"] = "WORKER"
    elif fault == "bool":
        body["cpu_configuration"]["database_owner"]["role_oid"] = True
    raw = canonical_json_bytes(body)
    if fault == "newline":
        raw += b"\n"
    elif fault == "duplicate":
        raw = b'{"schema_version":"hidden",' + raw[1:]
    elif fault == "oversize":
        raw = b" " * 65537
    with pytest.raises((ValueError, SchemaError)):
        parse_similarity_reader_installed_selection(raw)


def test_cohost_requires_same_explicit_cuda_controls_not_one_family_fallback():
    primary = RoutedSimilarityReaderConfiguration.model_validate(routed_document())
    mixed = RoutedSimilarityReaderConfiguration.model_validate(routed_document(mixed=True))
    require_same_routed_reader_controls(primary, mixed)
    require_same_routed_reader_controls(None, None)
    with pytest.raises(ValueError, match="COHOST_MISMATCH"):
        require_same_routed_reader_controls(primary, None)
    body = deepcopy(routed_document(mixed=True))
    body["cuda_native_execution_policy"]["sha256"] = "sha256:" + "f" * 64
    changed = RoutedSimilarityReaderConfiguration.model_validate(body)
    with pytest.raises(ValueError, match="COHOST_MISMATCH"):
        require_same_routed_reader_controls(primary, changed)


def test_cohost_revalidates_model_copy_instead_of_treating_it_as_a_grant():
    primary = RoutedSimilarityReaderConfiguration.model_validate(routed_document())
    mixed = RoutedSimilarityReaderConfiguration.model_validate(routed_document(mixed=True))
    changed = primary.model_copy(update={"authority": "ADMIN"})
    with pytest.raises((ValueError, SchemaError)):
        require_same_routed_reader_controls(changed, mixed)
