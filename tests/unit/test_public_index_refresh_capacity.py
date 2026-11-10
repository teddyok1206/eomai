"""Public membership uses its published capacity without widening legacy contracts."""

from collections.abc import Callable
from copy import deepcopy
from functools import lru_cache
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_contract_values import (
    raw_public_solution_contract_value,
    raw_similarity_contract_value,
)
from eom_catalog_contracts.embedding_index_families import parse_supported_embedding_index
from eom_catalog_contracts.inference_transfer_experiment import population_sha256
from eom_catalog_contracts.public_solution_embedding_index import MAX_PUBLIC_SOLUTION_SOURCES
from eom_catalog_service.embedding_incremental_plan import RegisteredEmbeddingRow
from eom_catalog_service.embedding_index_refresh_plan import (
    mixed_index_membership_refresh_reason,
    plan_index_membership_refresh,
    public_index_membership_refresh_reason,
    registered_public_index_membership_refresh_reason,
)
from eom_catalog_service.public_solution_index_assembly import (
    assemble_registered_public_solution_index_revision,
)
from eom_identifiers import content_sha256
from eom_protocol.artifact_members import ArtifactMemberPointer
from eom_workflow.local_embedding_index_refresh import IndexRefreshContractError
from eom_workflow.local_embedding_workflow_receipt_v3 import (
    ResolvedNativeIndexCoverageV3,
    validate_local_embedding_workflow_receipt_v3,
)

from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_native_office_public_embedding import native_plan
from tests.unit.test_public_solution_native_carriers import public_native_fixture
from tests.unit.test_registered_public_solution_index import successor


@lru_cache(maxsize=3)
def _template(version: int) -> Any:
    parent, registered, _pointer, shards = successor()
    if version == 3:
        return parent
    if version == 4:
        return registered
    _previous, plan, _captured = native_plan()
    return assemble_registered_public_solution_index_revision(
        plan,
        available_rows=(
            RegisteredEmbeddingRow(registered.bindings[0].encoding, registered.bindings[0].row_ref),
        ),
        shards=shards,
        index_id=registered.index_id,
        index_revision_id="embeddingindexrev_" + "7" * 32,
        previous_manifest=None,
        created_at=registered.created_at,
    ).index


@lru_cache(maxsize=9)
def _index(version: int, count: int) -> Any:
    return _expand_index(_template(version), count)


def _expand_index(template: Any, count: int) -> Any:
    value = template.model_dump(mode="json")
    originals = value["bindings"]
    bindings = deepcopy(originals)
    # Distinct synthetic sources may legitimately reference one identical numeric row.
    # Validate real schema/hash/layout rules; do not mock models or their raw reader.
    for ordinal in range(count - len(originals)):
        binding = deepcopy(originals[ordinal % len(originals)])
        binding["source"]["item_id"] = f"item_{ordinal:032x}"
        binding["source"]["item_revision_id"] = f"itemrev_{ordinal:032x}"
        logical = content_sha256(
            {
                "item_id": binding["source"]["item_id"],
                "projection_version": binding["projection_version"],
            }
        )
        binding["profile"]["profile_id"] = "inferenceprofile_" + logical[7:39]
        bindings.append(seal(binding, "binding_sha256"))
    value["bindings"] = sorted(bindings, key=lambda binding: binding["source"]["item_revision_id"])
    return type(template).model_validate(seal(value, "index_sha256"))


def _pointer(index: Any) -> ArtifactMemberPointer:
    return ArtifactMemberPointer(
        artifact_id="artifact_" + "e" * 32,
        artifact_revision_id="rev_" + "e" * 32,
        member_path="index.json",
        schema_ref="eom://schemas/knowledge/" + index.schema_version,
        media_type="application/json",
        sha256=content_sha256(index.model_dump(mode="json")),
    )


def _reader(version: int) -> Callable[..., str | None]:
    return cast(
        Callable[..., str | None],
        public_index_membership_refresh_reason
        if version == 3
        else registered_public_index_membership_refresh_reason,
    )


@pytest.mark.parametrize("version", [3, 4, 5])
@pytest.mark.parametrize("count", [1025, 1028])
def test_public_head_over_legacy_capacity_reuses_exact_members_without_refresh(
    version: int, count: int
) -> None:
    index = _index(version, count)
    pointer = _pointer(index)
    assert len(index.bindings) == count
    assert parse_supported_embedding_index(index) == index
    assert (
        _reader(version)(
            eligible_sources=tuple(binding.source for binding in index.bindings),
            available_bindings=index.bindings[::-1],
            previous=(pointer, index),
        )
        is None
    )
    assert _pointer(index) == pointer


@pytest.mark.parametrize("version", [3, 4, 5])
def test_public_head_over_legacy_capacity_detects_only_real_membership_changes(
    version: int,
) -> None:
    index = _index(version, 1028)
    sources = tuple(binding.source for binding in index.bindings)
    reader = _reader(version)
    assert (
        reader(
            eligible_sources=sources,
            available_bindings=index.bindings,
            previous=None,
        )
        == "MISSING_NAMESPACE_INDEX"
    )
    assert (
        reader(
            eligible_sources=sources,
            available_bindings=index.bindings[:-1],
            previous=(_pointer(index), index),
        )
        == "INDEX_MEMBERSHIP_CHANGED"
    )


@pytest.mark.parametrize("version", [3, 4, 5])
@pytest.mark.parametrize(
    "fault",
    [
        "duplicate_source",
        "duplicate_binding",
        "binding_hash",
        "index_hash",
        "extra",
        "pointer_hash",
    ],
)
def test_public_membership_still_rejects_duplicate_hash_and_constructed_model_tampering(
    version: int, fault: str
) -> None:
    index = _index(version, 3)
    sources = tuple(binding.source for binding in index.bindings)
    bindings, pointer = index.bindings, _pointer(index)
    if fault == "duplicate_source":
        sources = (*sources, sources[0])
    elif fault == "duplicate_binding":
        bindings = (*bindings[:-1], bindings[0])
    elif fault == "binding_hash":
        bindings = (
            bindings[0].model_copy(update={"binding_sha256": "sha256:" + "0" * 64}),
            *bindings[1:],
        )
    elif fault == "index_hash":
        index = index.model_copy(update={"index_sha256": "sha256:" + "0" * 64})
    elif fault == "extra":
        index = index.model_copy(update={"unrecognized_authority": True})
    else:
        pointer = pointer.model_copy(update={"sha256": "sha256:" + "0" * 64})
    with pytest.raises(IndexRefreshContractError):
        _reader(version)(
            eligible_sources=sources, available_bindings=bindings, previous=(pointer, index)
        )


@pytest.mark.parametrize("version", [3, 4, 5])
def test_public_membership_keeps_published_upper_bound(version: int) -> None:
    source = _index(version, 3).bindings[0].source
    assert MAX_PUBLIC_SOLUTION_SOURCES == 16384
    with pytest.raises(IndexRefreshContractError):
        _reader(version)(
            eligible_sources=(source,) * (MAX_PUBLIC_SOLUTION_SOURCES + 1),
            available_bindings=(),
            previous=None,
        )
    with pytest.raises(ValueError, match="array bound exceeded"):
        raw_public_solution_contract_value(list(range(MAX_PUBLIC_SOLUTION_SOURCES + 1)))


@pytest.mark.parametrize(
    "reader", [plan_index_membership_refresh, mixed_index_membership_refresh_reason]
)
def test_legacy_membership_limit_remains_1024(reader: Callable[..., object]) -> None:
    sources = tuple(binding.source for binding in _index(4, 1025).bindings)
    assert reader(eligible_sources=sources[:1024], available_bindings=(), previous=None) is None
    with pytest.raises(IndexRefreshContractError):
        reader(eligible_sources=sources, available_bindings=(), previous=None)
    assert len(raw_similarity_contract_value(list(range(1024)))) == 1024
    with pytest.raises(ValueError, match="array bound exceeded"):
        raw_similarity_contract_value(list(range(1025)))


def test_public_receipt3_accepts_large_committed_head_with_small_unchanged_numeric_batch() -> None:
    fixture = public_native_fixture()
    original = fixture["receipt"]
    index = _expand_index(fixture["coverage"].index, 1028)
    sources = tuple(binding.source for binding in index.bindings)
    command = type(original.registration_command).model_validate(
        seal(
            original.registration_command.model_dump(mode="json")
            | {
                "index_manifest": _pointer(index).model_dump(mode="json"),
                "index_sha256": index.index_sha256,
                "source_set_sha256": population_sha256(sources),
                "binding_set_sha256": content_sha256([b.binding_sha256 for b in index.bindings]),
                "eligible_source_count": len(sources),
                "binding_count": len(index.bindings),
            },
            "request_sha256",
        )
    )
    result = type(original.registration_result).model_validate(
        seal(
            original.registration_result.model_dump(mode="json")
            | {
                "request_sha256": command.request_sha256,
                "index_manifest": command.index_manifest.model_dump(mode="json"),
                "index_sha256": command.index_sha256,
            },
            "result_sha256",
        )
    )
    receipt = type(original).model_validate(
        seal(
            original.model_dump(mode="json")
            | {
                "registration_command": command.model_dump(mode="json"),
                "registration_result": result.model_dump(mode="json"),
            },
            "receipt_sha256",
        )
    )
    assert len(fixture["input"].rows) == 1
    assert len(fixture["plan"].sources) == 2
    assert (
        validate_local_embedding_workflow_receipt_v3(
            receipt,
            fixture["request"],
            fixture["plan"],
            fixture["policy"],
            workflow_id=fixture["intent"].workflow_id,
            step_run_id=fixture["intent"].step_run_id,
            receipt_owner_job_id=receipt.receipt_owner_job_id,
            launch_association=fixture["association"],
            owned_input=fixture["input"],
            index_coverage=ResolvedNativeIndexCoverageV3(index, sources),
        )
        == receipt
    )
