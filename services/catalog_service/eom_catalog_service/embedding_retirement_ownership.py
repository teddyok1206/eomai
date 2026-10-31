"""Registry ownership only: candidate aliases are neither file resolution nor delete authority."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from eom_identifiers import content_sha256

_ITEM = re.compile(r"item_[0-9a-f]{32}\Z")
_ITEM_REVISION = re.compile(r"itemrev_[0-9a-f]{32}\Z")
_ARTIFACT = re.compile(r"artifact_[0-9a-f]{32}\Z")
_ARTIFACT_REVISION = re.compile(r"rev_[0-9a-f]{32}\Z")
_SHA = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PARTITION = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_LEGACY_PROJECTION = "accepted-solution-comparison/1.0"
_PROJECTIONS = frozenset(
    {_LEGACY_PROJECTION, "registered-item-review-comparison/1.0", "public-solution-text/1.0"}
)


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("EMBEDDING_RETIREMENT_OWNERSHIP_INPUT_INVALID")


def _matches(value: object, pattern: re.Pattern[str]) -> bool:
    return type(value) is str and pattern.fullmatch(value) is not None


@dataclass(frozen=True, slots=True, order=True)
class RetirementArtifactRevisionKey:
    """Comparison identity only; an owner resolver still needs full hash/schema/media proof."""

    artifact_id: str
    artifact_revision_id: str

    def __post_init__(self) -> None:
        _require(_matches(self.artifact_id, _ARTIFACT))
        _require(_matches(self.artifact_revision_id, _ARTIFACT_REVISION))


@dataclass(frozen=True, slots=True)
class FrozenPastExamRetirementTarget:
    item_id: str
    item_revision_id: str
    manifest_sha256: str

    def __post_init__(self) -> None:
        _require(_matches(self.item_id, _ITEM))
        _require(_matches(self.item_revision_id, _ITEM_REVISION))
        _require(_matches(self.manifest_sha256, _SHA))


@dataclass(frozen=True, slots=True)
class FrozenPastExamRetirementScope:
    targets: tuple[FrozenPastExamRetirementTarget, ...]
    target_set_sha256: str
    legacy_storage_partition: str

    def __post_init__(self) -> None:
        _require(type(self.targets) is tuple and 1 <= len(self.targets) <= 16384)
        _require(all(type(row) is FrozenPastExamRetirementTarget for row in self.targets))
        revisions = tuple(row.item_revision_id for row in self.targets)
        _require(revisions == tuple(sorted(set(revisions))))
        _require(len({row.item_id for row in self.targets}) == len(self.targets))
        _require(_matches(self.legacy_storage_partition, _PARTITION))
        _require(self.legacy_storage_partition != "public-solution")
        _require(_matches(self.target_set_sha256, _SHA))
        _require(
            self.target_set_sha256
            == content_sha256(
                [
                    dict(
                        item_id=row.item_id,
                        item_revision_id=row.item_revision_id,
                        manifest_sha256=row.manifest_sha256,
                    )
                    for row in self.targets
                ]
            )
        )


@dataclass(frozen=True, slots=True)
class RetirementEncodingOwnership:
    encoding_sha256: str
    storage_partition: str
    shard: RetirementArtifactRevisionKey

    def __post_init__(self) -> None:
        _require(_matches(self.encoding_sha256, _SHA))
        _require(_matches(self.storage_partition, _PARTITION))
        _require(type(self.shard) is RetirementArtifactRevisionKey)


@dataclass(frozen=True, slots=True)
class RetirementBindingOwnership:
    binding_sha256: str
    encoding_sha256: str
    item_revision_id: str
    source_class: Literal["PAST_EXAM", "APPROVED_ITEM"]
    projection_version: str

    def __post_init__(self) -> None:
        _require(_matches(self.binding_sha256, _SHA))
        _require(_matches(self.encoding_sha256, _SHA))
        _require(_matches(self.item_revision_id, _ITEM_REVISION))
        _require(self.source_class in {"PAST_EXAM", "APPROVED_ITEM"})
        _require(self.projection_version in _PROJECTIONS)


@dataclass(frozen=True, slots=True)
class RegistryRetirementOwnership:
    """Sorted registry candidates, subject to separate index/consumer/authority/lifecycle gates."""

    candidate_binding_sha256s: tuple[str, ...]
    registry_exclusive_encoding_sha256s: tuple[str, ...]
    registry_shared_encoding_sha256s: tuple[str, ...]
    registry_exclusive_shards: tuple[RetirementArtifactRevisionKey, ...]
    registry_shared_shards: tuple[RetirementArtifactRevisionKey, ...]


def classify_registry_retirement_ownership(
    scope: FrozenPastExamRetirementScope,
    encodings: Iterable[RetirementEncodingOwnership],
    bindings: Iterable[RetirementBindingOwnership],
) -> RegistryRetirementOwnership:
    """Use complete registry rows, not only a prefiltered target JOIN.

    Read adapters must include non-target/unbound encodings sharing any candidate
    shard and every binding of each encoding. This pure calculation cannot prove
    that an adapter's input inventory is complete or that an Artifact has no other
    consumers. Its result is deliberately not a deletion plan or permission.
    """
    _require(type(scope) is FrozenPastExamRetirementScope)
    targets = {row.item_revision_id for row in scope.targets}
    encoding_map: dict[str, RetirementEncodingOwnership] = {}
    shard_encodings: dict[RetirementArtifactRevisionKey, set[str]] = {}
    revision_owners: dict[str, str] = {}
    for encoding in encodings:
        _require(type(encoding) is RetirementEncodingOwnership)
        _require(encoding.encoding_sha256 not in encoding_map)
        encoding_map[encoding.encoding_sha256] = encoding
        shard = encoding.shard
        previous = revision_owners.setdefault(shard.artifact_revision_id, shard.artifact_id)
        _require(previous == shard.artifact_id)
        shard_encodings.setdefault(shard, set()).add(encoding.encoding_sha256)
    seen_bindings: set[str] = set()
    candidate_bindings: set[str] = set()
    candidate_encodings: set[str] = set()
    outside_encodings: set[str] = set()
    for binding in bindings:
        _require(type(binding) is RetirementBindingOwnership)
        _require(binding.binding_sha256 not in seen_bindings)
        seen_bindings.add(binding.binding_sha256)
        bound_encoding = encoding_map.get(binding.encoding_sha256)
        _require(bound_encoding is not None)
        assert bound_encoding is not None
        candidate = (
            binding.source_class == "PAST_EXAM"
            and binding.item_revision_id in targets
            and binding.projection_version == _LEGACY_PROJECTION
            and bound_encoding.storage_partition == scope.legacy_storage_partition
        )
        if candidate:
            candidate_bindings.add(binding.binding_sha256)
            candidate_encodings.add(binding.encoding_sha256)
        else:
            outside_encodings.add(binding.encoding_sha256)
    exclusive_encodings = candidate_encodings - outside_encodings
    candidate_shards = {encoding_map[key].shard for key in candidate_encodings}
    exclusive_shards = {
        shard for shard in candidate_shards if shard_encodings[shard] <= exclusive_encodings
    }
    return RegistryRetirementOwnership(
        tuple(sorted(candidate_bindings)),
        tuple(sorted(exclusive_encodings)),
        tuple(sorted(candidate_encodings & outside_encodings)),
        tuple(sorted(exclusive_shards)),
        tuple(sorted(candidate_shards - exclusive_shards)),
    )
