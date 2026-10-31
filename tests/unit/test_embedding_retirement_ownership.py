"""Pure registry ownership, not permission, source resolution or an actual deletion."""

from collections.abc import Iterator
from dataclasses import FrozenInstanceError, replace

import pytest
from eom_catalog_service.embedding_retirement_ownership import (
    FrozenPastExamRetirementScope,
    FrozenPastExamRetirementTarget,
    RetirementArtifactRevisionKey,
    RetirementBindingOwnership,
    RetirementEncodingOwnership,
    classify_registry_retirement_ownership,
)
from eom_identifiers import content_sha256

LEGACY = "corpus_" + "a" * 32
OLD = "accepted-solution-comparison/1.0"
PUBLIC = "public-solution-text/1.0"


def sha(number: int) -> str:
    return f"sha256:{number:064x}"


def revision(number: int) -> str:
    return f"itemrev_{number:032x}"


def target(number: int) -> FrozenPastExamRetirementTarget:
    return FrozenPastExamRetirementTarget(f"item_{number:032x}", revision(number), sha(number))


def scope(*numbers: int) -> FrozenPastExamRetirementScope:
    targets = tuple(target(number) for number in numbers or (1,))
    digest = content_sha256(
        [
            dict(
                item_id=row.item_id,
                item_revision_id=row.item_revision_id,
                manifest_sha256=row.manifest_sha256,
            )
            for row in targets
        ]
    )
    return FrozenPastExamRetirementScope(targets, digest, LEGACY)


def shard(number: int, *, artifact: int | None = None) -> RetirementArtifactRevisionKey:
    return RetirementArtifactRevisionKey(
        f"artifact_{number if artifact is None else artifact:032x}", f"rev_{number:032x}"
    )


def encoding(number: int, *, file: int | None = None, partition: str = LEGACY):
    return RetirementEncodingOwnership(
        sha(number), partition, shard(number if file is None else file)
    )


def binding(
    number: int,
    *,
    encoded: int | None = None,
    item: int = 1,
    source: str = "PAST_EXAM",
    projection: str = OLD,
):
    return RetirementBindingOwnership(
        sha(number + 1000000),
        sha(number if encoded is None else encoded),
        revision(item),
        source,
        projection,
    )


def test_exact_legacy_targets_only_and_inputs_remain_immutable():
    frozen = scope(1, 2)
    encodings = (encoding(1), encoding(2), encoding(3, partition="public-solution"))
    bindings = (binding(1), binding(2, item=2), binding(3, projection=PUBLIC))
    result = classify_registry_retirement_ownership(frozen, encodings, bindings)
    assert result.candidate_binding_sha256s == (sha(1000001), sha(1000002))
    assert result.registry_exclusive_encoding_sha256s == (sha(1), sha(2))
    assert result.registry_exclusive_shards == (shard(1), shard(2))
    assert result.registry_shared_encoding_sha256s == result.registry_shared_shards == ()
    assert encodings[2].storage_partition == "public-solution"
    with pytest.raises(FrozenInstanceError):
        frozen.target_set_sha256 = sha(0)


def test_same_numeric_encoding_for_two_targets_is_exclusive_without_duplicate_rows():
    result = classify_registry_retirement_ownership(
        scope(1, 2), (encoding(1),), (binding(1), binding(2, encoded=1, item=2))
    )
    assert result.registry_exclusive_encoding_sha256s == (sha(1),)
    assert result.registry_exclusive_shards == (shard(1),)
    assert len(result.candidate_binding_sha256s) == 2


@pytest.mark.parametrize(
    "outside",
    [
        dict(item=2),
        dict(source="APPROVED_ITEM"),
        dict(projection=PUBLIC),
        dict(source="APPROVED_ITEM", projection="registered-item-review-comparison/1.0"),
    ],
)
def test_non_target_or_new_projection_reference_protects_shared_encoding_and_file(outside):
    result = classify_registry_retirement_ownership(
        scope(), (encoding(1),), (binding(1), binding(2, encoded=1, **outside))
    )
    assert result.candidate_binding_sha256s == (sha(1000001),)
    assert result.registry_exclusive_encoding_sha256s == ()
    assert result.registry_shared_encoding_sha256s == (sha(1),)
    assert result.registry_exclusive_shards == ()
    assert result.registry_shared_shards == (shard(1),)


@pytest.mark.parametrize("outside_partition", [LEGACY, "public-solution", "another-partition"])
def test_unbound_encoding_in_same_shard_is_not_discarded(outside_partition):
    result = classify_registry_retirement_ownership(
        scope(), (encoding(1), encoding(2, file=1, partition=outside_partition)), (binding(1),)
    )
    assert result.registry_exclusive_encoding_sha256s == (sha(1),)
    assert result.registry_exclusive_shards == ()
    assert result.registry_shared_shards == (shard(1),)


def test_two_registry_exclusive_rows_can_share_one_registry_exclusive_shard():
    result = classify_registry_retirement_ownership(
        scope(1, 2), (encoding(1), encoding(2, file=1)), (binding(1), binding(2, item=2))
    )
    assert result.registry_exclusive_encoding_sha256s == (sha(1), sha(2))
    assert result.registry_exclusive_shards == (shard(1),)


def test_same_logical_artifact_with_different_revisions_is_not_one_file():
    newer = RetirementEncodingOwnership(sha(2), LEGACY, shard(2, artifact=1))
    result = classify_registry_retirement_ownership(
        scope(), (encoding(1), newer), (binding(1), binding(2, item=2))
    )
    assert result.registry_exclusive_shards == (shard(1),)
    assert result.registry_shared_shards == ()
    assert newer.shard != shard(1)


@pytest.mark.parametrize(
    "partition,projection",
    [
        ("public-solution", PUBLIC),
        ("public-solution", OLD),
        ("other-private-space", OLD),
        (LEGACY, PUBLIC),
    ],
)
def test_partition_or_projection_alone_never_grants_retirement_scope(partition, projection):
    result = classify_registry_retirement_ownership(
        scope(), (encoding(1, partition=partition),), (binding(1, projection=projection),)
    )
    assert result.candidate_binding_sha256s == ()
    assert result.registry_exclusive_encoding_sha256s == ()
    assert result.registry_exclusive_shards == result.registry_shared_shards == ()


def test_duplicate_encoding_identity_is_rejected_instead_of_last_write_wins():
    for duplicated in (encoding(1), encoding(1, file=2)):
        with pytest.raises(ValueError, match="OWNERSHIP_INPUT_INVALID"):
            classify_registry_retirement_ownership(scope(), (encoding(1), duplicated), ())


def test_duplicate_binding_identity_is_rejected_even_with_different_source():
    for duplicated in (binding(1), binding(1, item=2)):
        with pytest.raises(ValueError, match="OWNERSHIP_INPUT_INVALID"):
            classify_registry_retirement_ownership(
                scope(), (encoding(1),), (binding(1), duplicated)
            )


def test_dangling_encoding_reference_is_an_error_even_outside_selected_scope():
    with pytest.raises(ValueError, match="OWNERSHIP_INPUT_INVALID"):
        classify_registry_retirement_ownership(scope(), (encoding(1),), (binding(2, item=2),))


def test_one_artifact_revision_cannot_have_two_logical_owners():
    broken = RetirementEncodingOwnership(sha(2), LEGACY, shard(1, artifact=2))
    with pytest.raises(ValueError, match="OWNERSHIP_INPUT_INVALID"):
        classify_registry_retirement_ownership(scope(), (encoding(1), broken), ())


@pytest.mark.parametrize(
    "changes",
    [
        dict(target_set_sha256=sha(0)),
        dict(legacy_storage_partition="public-solution"),
        dict(legacy_storage_partition="../legacy"),
        dict(targets=()),
        dict(targets=[target(1)]),
        dict(targets=(target(1), target(1))),
        dict(targets=(target(2), target(1))),
        dict(targets=(target(1), replace(target(2), item_id=target(1).item_id))),
    ],
)
def test_frozen_scope_hash_identity_order_and_legacy_partition_are_protected(changes):
    with pytest.raises(ValueError, match="OWNERSHIP_INPUT_INVALID"):
        replace(scope(), **changes)


@pytest.mark.parametrize("value", ["sha256:" + "x" * 64, "sha256:0", True, 1, None])
def test_hash_values_are_not_coerced(value):
    with pytest.raises(ValueError, match="OWNERSHIP_INPUT_INVALID"):
        RetirementEncodingOwnership(value, LEGACY, shard(1))


def test_output_is_deterministic_across_registry_iteration_orders():
    encodings = (encoding(1), encoding(2, file=1), encoding(3), encoding(4, file=3))
    bindings = (binding(1), binding(2), binding(3), binding(4, item=2))
    first = classify_registry_retirement_ownership(scope(), encodings, bindings)
    assert first == classify_registry_retirement_ownership(
        scope(), reversed(encodings), reversed(bindings)
    )


class SinglePass[T]:
    def __init__(self, rows: tuple[T, ...]):
        self.rows = rows
        self.iterations = 0
        self.visits = 0

    def __iter__(self) -> Iterator[T]:
        self.iterations += 1
        assert self.iterations == 1, "registry source was scanned more than once"
        for row in self.rows:
            self.visits += 1
            yield row


def test_large_registry_is_classified_with_one_visit_per_source_row():
    count = 10000
    encodings = SinglePass(tuple(encoding(number) for number in range(1, count + 1)))
    bindings = SinglePass(
        tuple(
            binding(number * 5 + alias, encoded=number)
            for number in range(1, count + 1)
            for alias in range(5)
        )
    )
    result = classify_registry_retirement_ownership(scope(), encodings, bindings)
    assert encodings.visits == count and bindings.visits == count * 5
    assert len(result.registry_exclusive_encoding_sha256s) == count
    assert len(result.candidate_binding_sha256s) == count * 5
    assert len(result.registry_exclusive_shards) == count
    assert not result.registry_shared_shards
