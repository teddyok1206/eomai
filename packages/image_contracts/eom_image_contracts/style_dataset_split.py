"""Pure immutable document/duplicate-group splits for reviewed style samples."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from itertools import islice
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from eom_image_contracts.institutional_style_evaluation import (
    INSTITUTIONAL_CROP_SCHEMA_REF,
    InstitutionalStyleTrack,
)
from eom_image_contracts.models import (
    FrozenModel,
    ImageEvaluationArtifactMember,
    Sha256,
    content_sha256,
)

STYLE_DATASET_SPLIT_SCHEMA_REF = "eom://schemas/image-provider/local-image-style-dataset-split/1.0"
StyleDatasetPartition = Literal["TRAIN", "VALIDATION", "HOLDOUT"]


class StyleDatasetMinimumCounts(FrozenModel):
    train: int = Field(default=100, ge=1, le=10_000)
    validation: int = Field(default=24, ge=1, le=10_000)
    holdout: int = Field(default=32, ge=1, le=10_000)


class StyleDatasetSample(FrozenModel):
    sample_id: str = Field(pattern=r"^imgstylesample_[0-9a-f]{32}$")
    crop: ImageEvaluationArtifactMember
    source_document: ImageEvaluationArtifactMember
    exam_group_sha256: Sha256
    near_duplicate_group_sha256: Sha256 | None
    depiction_key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{2,63}$")

    @model_validator(mode="after")
    def exact_sample(self) -> Self:
        if (
            self.crop.media_type != "image/png"
            or self.crop.schema_ref != INSTITUTIONAL_CROP_SCHEMA_REF
        ):
            raise ValueError("style sample crop contract mismatch")
        if self.source_document.media_type != "application/pdf":
            raise ValueError("style sample source must be a pinned PDF")
        identity = content_sha256(self.model_dump(mode="json", exclude={"sample_id"}))
        if self.sample_id != "imgstylesample_" + identity.removeprefix("sha256:")[:32]:
            raise ValueError("style sample identity mismatch")
        return self


class StyleDatasetSplitMember(FrozenModel):
    sample: StyleDatasetSample
    partition: StyleDatasetPartition


def _group_keys(sample: StyleDatasetSample) -> tuple[str, ...]:
    keys: tuple[str, ...] = (
        "document:" + sample.source_document.artifact_id,
        "pdf:" + sample.source_document.sha256,
        "exam:" + sample.exam_group_sha256,
    )
    if sample.near_duplicate_group_sha256 is not None:
        keys += ("duplicate:" + sample.near_duplicate_group_sha256,)
    return keys


def _require_unique_samples(samples: tuple[StyleDatasetSample, ...]) -> None:
    if not 1 <= len(samples) <= 10_000:
        raise ValueError("style dataset requires 1 to 10000 samples")
    if len({sample.sample_id for sample in samples}) != len(samples):
        raise ValueError("style dataset repeats a sample ID")
    if len({sample.crop.sha256 for sample in samples}) != len(samples):
        raise ValueError("style dataset repeats exact crop bytes")
    pointers: dict[tuple[str, str, str], ImageEvaluationArtifactMember] = {}
    for sample in samples:
        for pointer in (sample.crop, sample.source_document):
            key = (pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path)
            previous = pointers.setdefault(key, pointer)
            if pointer != previous:
                raise ValueError("style dataset has conflicting immutable member pointers")


class LocalImageStyleDatasetSplit(FrozenModel):
    schema_version: Literal["local-image-style-dataset-split/1.0"]
    split_id: str = Field(pattern=r"^imgstylesplit_[0-9a-f]{32}$")
    split_revision_id: str = Field(pattern=r"^imgstylesplitrev_[0-9a-f]{32}$")
    created_at: datetime
    style_track: InstitutionalStyleTrack
    reviewed_inventory: ImageEvaluationArtifactMember
    authorization: ImageEvaluationArtifactMember
    seed: int = Field(ge=0, le=2**32 - 1)
    minimum_counts: StyleDatasetMinimumCounts
    pinned_holdout_sample_ids: tuple[str, ...] = Field(max_length=10_000)
    members: tuple[StyleDatasetSplitMember, ...] = Field(min_length=1, max_length=10_000)
    readiness: Literal["READY", "INSUFFICIENT"]
    split_sha256: Sha256

    @field_validator("created_at")
    @classmethod
    def require_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
            raise ValueError("style dataset timestamp must use UTC")
        return value

    @model_validator(mode="after")
    def exact_split(self) -> Self:
        for pointer in (self.reviewed_inventory, self.authorization):
            if pointer.media_type != "application/json":
                raise ValueError("style dataset metadata pointer must be JSON")
        samples = tuple(member.sample for member in self.members)
        _require_unique_samples(samples)
        sample_ids = tuple(sample.sample_id for sample in samples)
        if sample_ids != tuple(sorted(sample_ids)):
            raise ValueError("style dataset members must be sorted by sample ID")
        pinned = self.pinned_holdout_sample_ids
        if pinned != tuple(sorted(set(pinned))) or not set(pinned) <= set(sample_ids):
            raise ValueError("style dataset holdout IDs must be sorted, unique and present")
        group_partitions: dict[str, StyleDatasetPartition] = {}
        by_id = {member.sample.sample_id: member.partition for member in self.members}
        for member in self.members:
            for key in _group_keys(member.sample):
                if group_partitions.setdefault(key, member.partition) != member.partition:
                    raise ValueError("style dataset leaks a document or duplicate group")
        if any(by_id[sample_id] != "HOLDOUT" for sample_id in pinned):
            raise ValueError("style dataset moved a pinned holdout sample")
        counts = self.partition_counts()
        ready = (
            counts["TRAIN"] >= self.minimum_counts.train
            and counts["VALIDATION"] >= self.minimum_counts.validation
            and counts["HOLDOUT"] >= self.minimum_counts.holdout
        )
        if self.readiness != ("READY" if ready else "INSUFFICIENT"):
            raise ValueError("style dataset readiness differs from partition counts")
        if self.split_sha256 != content_sha256(
            self.model_dump(mode="json", exclude={"split_sha256"})
        ):
            raise ValueError("style dataset split hash mismatch")
        return self

    def partition_counts(self) -> dict[StyleDatasetPartition, int]:
        counts: dict[StyleDatasetPartition, int] = {"TRAIN": 0, "VALIDATION": 0, "HOLDOUT": 0}
        for member in self.members:
            counts[member.partition] += 1
        return counts


class _SourceGroups:
    """Union by size with path compression for transitive provenance links."""

    def __init__(self, count: int) -> None:
        self.parents = list(range(count))
        self.sizes = [1] * count

    def root(self, index: int) -> int:
        while self.parents[index] != index:
            self.parents[index] = self.parents[self.parents[index]]
            index = self.parents[index]
        return index

    def join(self, left: int, right: int) -> None:
        left, right = self.root(left), self.root(right)
        if left == right:
            return
        if self.sizes[left] < self.sizes[right]:
            left, right = right, left
        self.parents[right] = left
        self.sizes[left] += self.sizes[right]


def build_style_dataset_split(
    *,
    samples: Iterable[StyleDatasetSample],
    split_id: str,
    split_revision_id: str,
    created_at: datetime,
    style_track: InstitutionalStyleTrack,
    reviewed_inventory: ImageEvaluationArtifactMember,
    authorization: ImageEvaluationArtifactMember,
    seed: int,
    minimum_counts: StyleDatasetMinimumCounts | None = None,
    pinned_holdout_sample_ids: tuple[str, ...] = (),
) -> LocalImageStyleDatasetSplit:
    """Partition metadata only; callers own pointer resolution and Artifact publication."""
    minimum_counts = minimum_counts or StyleDatasetMinimumCounts()
    bounded_samples = tuple(islice(samples, 10_001))
    _require_unique_samples(bounded_samples)
    ordered = tuple(sorted(bounded_samples, key=lambda sample: sample.sample_id))
    pinned = set(pinned_holdout_sample_ids)
    if len(pinned) != len(pinned_holdout_sample_ids):
        raise ValueError("style dataset repeats a pinned holdout ID")
    if not pinned <= {sample.sample_id for sample in ordered}:
        raise ValueError("style dataset pinned holdout sample is missing")
    groups = _SourceGroups(len(ordered))
    first_by_key: dict[str, int] = {}
    for index, sample in enumerate(ordered):
        for key in _group_keys(sample):
            groups.join(index, first_by_key.setdefault(key, index))
    grouped: dict[int, list[StyleDatasetSample]] = {}
    for index, sample in enumerate(ordered):
        grouped.setdefault(groups.root(index), []).append(sample)
    group_order = sorted(
        grouped.values(),
        key=lambda group: (
            len(group),
            content_sha256({"seed": seed, "samples": [sample.sample_id for sample in group]}),
        ),
    )
    partitions: dict[str, StyleDatasetPartition] = {}
    holdout_count = 0
    remaining: list[list[StyleDatasetSample]] = []
    for group in group_order:
        if any(sample.sample_id in pinned for sample in group):
            partitions.update((sample.sample_id, "HOLDOUT") for sample in group)
            holdout_count += len(group)
        else:
            remaining.append(group)
    validation_count = 0
    for group in remaining:
        if holdout_count < minimum_counts.holdout:
            partition: StyleDatasetPartition = "HOLDOUT"
            holdout_count += len(group)
        elif validation_count < minimum_counts.validation:
            partition = "VALIDATION"
            validation_count += len(group)
        else:
            partition = "TRAIN"
        partitions.update((sample.sample_id, partition) for sample in group)
    train_count = len(ordered) - holdout_count - validation_count
    document = {
        "schema_version": "local-image-style-dataset-split/1.0",
        "split_id": split_id,
        "split_revision_id": split_revision_id,
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "style_track": style_track,
        "reviewed_inventory": reviewed_inventory.model_dump(mode="json"),
        "authorization": authorization.model_dump(mode="json"),
        "seed": seed,
        "minimum_counts": minimum_counts.model_dump(mode="json"),
        "pinned_holdout_sample_ids": sorted(pinned),
        "members": [
            {"sample": sample.model_dump(mode="json"), "partition": partitions[sample.sample_id]}
            for sample in ordered
        ],
        "readiness": (
            "READY"
            if train_count >= minimum_counts.train
            and validation_count >= minimum_counts.validation
            and holdout_count >= minimum_counts.holdout
            else "INSUFFICIENT"
        ),
    }
    document["split_sha256"] = content_sha256(document)
    return LocalImageStyleDatasetSplit.model_validate(document)
