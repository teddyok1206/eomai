from __future__ import annotations

import hashlib
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from eom_image_contracts import (
    INSTITUTIONAL_CROP_SCHEMA_REF,
    ImageEvaluationArtifactMember,
    LocalImageStyleDatasetSplit,
    StyleDatasetMinimumCounts,
    StyleDatasetSample,
    build_style_dataset_split,
    content_json_bytes,
    content_sha256,
    validate_contract,
)
from eom_image_contracts.validation import load_schema
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _pointer(index: int, media: str, schema: str) -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id=f"artifact_{index:032x}",
        artifact_revision_id=f"rev_{index:032x}",
        member_path="p",
        schema_ref=schema,
        media_type=media,
        sha256=_sha(str(index)),
    )


def _sample(
    index: int,
    *,
    document: int | None = None,
    document_hash: str | None = None,
    document_revision: int | None = None,
    exam_group: str | None = None,
    cluster: str | None = None,
    crop: ImageEvaluationArtifactMember | None = None,
) -> StyleDatasetSample:
    source = _pointer(
        10_000 + (index if document is None else document), "application/pdf", "pdf/1.0"
    )
    source_value = source.model_dump(mode="json")
    if document_hash is not None:
        source_value["sha256"] = document_hash
    if document_revision is not None:
        source_value["artifact_revision_id"] = f"rev_{document_revision:032x}"
    value = {
        "crop": (crop or _pointer(index, "image/png", INSTITUTIONAL_CROP_SCHEMA_REF)).model_dump(
            mode="json"
        ),
        "source_document": source_value,
        "exam_group_sha256": exam_group or _sha(f"exam-{index}"),
        "near_duplicate_group_sha256": cluster,
        "depiction_key": f"OBJECT_{index:05d}",
    }
    return StyleDatasetSample.model_validate(
        {**value, "sample_id": "imgstylesample_" + content_sha256(value)[7:39]}
    )


def _split(
    samples: tuple[StyleDatasetSample, ...], *, pinned: tuple[str, ...] = (), full: bool = False
) -> LocalImageStyleDatasetSplit:
    return build_style_dataset_split(
        samples=samples,
        split_id="imgstylesplit_" + "a" * 32,
        split_revision_id="imgstylesplitrev_" + "b" * 32,
        created_at=datetime(2026, 10, 3, tzinfo=UTC),
        style_track="OBJECT_LINE_ART",
        reviewed_inventory=_pointer(50_001, "application/json", "inventory/1.0"),
        authorization=_pointer(50_002, "application/json", "authorization/1.0"),
        seed=37,
        minimum_counts=None
        if full
        else StyleDatasetMinimumCounts(train=1, validation=1, holdout=1),
        pinned_holdout_sample_ids=pinned,
    )


def _rehash(value: dict[str, Any]) -> dict[str, Any]:
    value.pop("split_sha256", None)
    return {**value, "split_sha256": content_sha256(value)}


def test_full_split_schema_model_counts_and_canonical_hash() -> None:
    split = _split(tuple(_sample(index) for index in range(156)), full=True)
    assert split.partition_counts() == {"TRAIN": 100, "VALIDATION": 24, "HOLDOUT": 32}
    assert split.readiness == "READY"
    validate_contract("style-dataset-split", split.model_dump(mode="json"))
    assert LocalImageStyleDatasetSplit.model_validate_json(split.model_dump_json()) == split
    assert split.split_sha256 == content_sha256(
        split.model_dump(mode="json", exclude={"split_sha256"})
    )
    with pytest.raises(ValidationError):
        split.seed = 9


def test_small_dataset_is_insufficient_without_copying_samples() -> None:
    samples = tuple(_sample(index) for index in range(24))
    split = _split(samples, full=True)
    assert split.readiness == "INSUFFICIENT"
    assert len(split.members) == 24
    assert {member.sample for member in split.members} == set(samples)


def test_order_replay_and_concurrent_calls_are_byte_identical() -> None:
    samples = tuple(_sample(index, document=index // 3) for index in range(156))
    expected = content_json_bytes(_split(samples, full=True).model_dump(mode="json"))
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: _split(samples[::-1], full=True), range(4)))
    assert all(content_json_bytes(result.model_dump(mode="json")) == expected for result in results)


@pytest.mark.parametrize(
    "link", ["document", "revision", "pdf_alias", "exam", "cluster", "transitive"]
)
def test_whole_source_and_duplicate_groups_follow_pinned_holdout(link: str) -> None:
    first = _sample(
        1, document=1, cluster=_sha("group") if link in {"cluster", "transitive"} else None
    )
    if link == "document":
        second = _sample(2, document=1)
    elif link == "revision":
        second = _sample(2, document=1, document_revision=90_000, document_hash=_sha("new-pdf"))
    elif link == "pdf_alias":
        second = _sample(2, document_hash=first.source_document.sha256)
    elif link == "exam":
        second = _sample(2, exam_group=first.exam_group_sha256)
    else:
        second = _sample(2, cluster=_sha("group"))
    linked: tuple[StyleDatasetSample, ...] = (first, second)
    if link == "transitive":
        linked += (_sample(3, document=2),)
    split = _split(
        linked + tuple(_sample(index) for index in range(10, 20)), pinned=(first.sample_id,)
    )
    by_id = {member.sample.sample_id: member.partition for member in split.members}
    assert all(by_id[sample.sample_id] == "HOLDOUT" for sample in linked)
    value = split.model_dump(mode="json")
    for member in value["members"]:
        if member["sample"]["sample_id"] == second.sample_id:
            member["partition"] = "TRAIN"
    with pytest.raises(ValidationError, match="leaks"):
        LocalImageStyleDatasetSplit.model_validate(_rehash(value))


def test_small_groups_fill_evaluation_before_large_training_group() -> None:
    samples = tuple(_sample(index, document=0) for index in range(100)) + tuple(
        _sample(index) for index in range(100, 156)
    )
    split = _split(samples, full=True)
    assert split.readiness == "READY"
    assert split.partition_counts() == {"TRAIN": 100, "VALIDATION": 24, "HOLDOUT": 32}


def test_duplicate_sample_and_exact_crop_bytes_are_rejected() -> None:
    first = _sample(1)
    with pytest.raises(ValueError, match="sample ID"):
        _split((first, first))
    with pytest.raises(ValueError, match="exact crop"):
        _split((first, _sample(2, crop=first.crop)))


def test_conflicting_immutable_pointer_is_rejected() -> None:
    with pytest.raises(ValueError, match="conflicting immutable"):
        _split((_sample(1, document=1), _sample(2, document=1, document_hash=_sha("tampered"))))


def test_missing_or_repeated_pinned_holdout_is_rejected() -> None:
    sample = _sample(1)
    with pytest.raises(ValueError, match="missing"):
        _split((sample,), pinned=("imgstylesample_" + "f" * 32,))
    with pytest.raises(ValueError, match="repeats a pinned"):
        _split((sample,), pinned=(sample.sample_id, sample.sample_id))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("created_at", "2026-10-03T00:00:00+09:00"),
        ("created_at", "2026-10-03T00:00:00"),
        ("readiness", "INSUFFICIENT"),
        ("style_track", "SCIENTIFIC_DIAGRAM"),
        ("split_sha256", _sha("forged")),
    ],
)
def test_tampered_split_fields_fail(field: str, replacement: str) -> None:
    value = _split(tuple(_sample(index) for index in range(6))).model_dump(mode="json")
    value[field] = replacement
    if field != "split_sha256":
        value = _rehash(value)
    with pytest.raises(ValidationError):
        LocalImageStyleDatasetSplit.model_validate(value)


def test_sample_identity_and_media_are_validated() -> None:
    value = _sample(1).model_dump(mode="json")
    value["depiction_key"] = "DIFFERENT_OBJECT"
    with pytest.raises(ValidationError, match="identity mismatch"):
        StyleDatasetSample.model_validate(value)
    value["crop"]["media_type"] = "application/pdf"
    with pytest.raises(ValidationError, match="crop contract"):
        StyleDatasetSample.model_validate(value)


@pytest.mark.parametrize("path", ["/p", "../p", "p/../q", "./p", "p/./q", "p//q", "p/", "p\\q"])
def test_schema_and_model_reject_unsafe_pointer_paths(path: str) -> None:
    value = _split(tuple(_sample(index) for index in range(3))).model_dump(mode="json")
    value["authorization"]["member_path"] = path
    value = _rehash(value)
    with pytest.raises(JsonSchemaValidationError):
        validate_contract("style-dataset-split", value)
    with pytest.raises(ValidationError):
        LocalImageStyleDatasetSplit.model_validate(value)


def test_schema_canonical_and_packaged_resources_match() -> None:
    root = Path(__file__).resolve().parents[2]
    name = "local-image-style-dataset-split-v1.schema.json"
    canonical = root / "schemas/image-provider" / name
    packaged = root / "packages/image_contracts/eom_image_contracts/schemas" / name
    assert canonical.read_bytes() == packaged.read_bytes()
    assert load_schema("style-dataset-split")["$id"].endswith(
        "/local-image-style-dataset-split/1.0"
    )
    assert name in (root / "scripts/api/deploy_release.sh").read_text()
    for script in ("image_provider", "image_trainer"):
        assert name in (root / "scripts" / script / "build_release.sh").read_text()


def test_large_grouped_dataset_is_bounded_and_keeps_every_group_whole() -> None:
    samples = tuple(_sample(index, document=index // 4) for index in range(10_000))
    split = _split(samples, full=True)
    assert len(split.members) == 10_000
    assert split.readiness == "READY"
    partition_by_document: dict[str, str] = {}
    for member in split.members:
        document = member.sample.source_document.artifact_id
        assert partition_by_document.setdefault(document, member.partition) == member.partition


def test_unbounded_iterator_stops_at_the_input_limit() -> None:
    sample = _sample(1)
    consumed = 0

    def generate() -> Iterator[StyleDatasetSample]:
        nonlocal consumed
        while True:
            consumed += 1
            yield sample

    with pytest.raises(ValueError, match="1 to 10000"):
        build_style_dataset_split(
            samples=generate(),
            split_id="imgstylesplit_" + "a" * 32,
            split_revision_id="imgstylesplitrev_" + "b" * 32,
            created_at=datetime(2026, 10, 3, tzinfo=UTC),
            style_track="OBJECT_LINE_ART",
            reviewed_inventory=_pointer(50_001, "application/json", "inventory/1.0"),
            authorization=_pointer(50_002, "application/json", "authorization/1.0"),
            seed=37,
        )
    assert consumed == 10_001
