"""Closed metadata guards; synthetic pointers never establish image/quality PASS."""

from __future__ import annotations

import ast
import copy
import hashlib
import json
from pathlib import Path

import pytest
from eom_image_contracts.models import (
    ImageEvaluationArtifactMember,
    content_json_bytes,
    content_sha256,
)
from eom_image_contracts.photo_object_support import (
    PREFIX,
    REVIEW_SCHEMA,
    PhotoObjectSupportReview,
    parse_photo_object_support_review,
)
from eom_image_contracts.validation import SCHEMA_FILES, SCHEMA_SHA256, validate_contract
from eom_image_contracts.visual_reference import VisualReferencePngArtifactPointer
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError


def _pin(character, schema, member, media="image/png"):
    return dict(
        artifact_id="artifact_" + character * 32,
        artifact_revision_id="rev_" + character * 32,
        member_path=member,
        schema_ref=PREFIX + schema,
        media_type=media,
        sha256="sha256:" + character * 64,
    )


def _seal(value):
    value = copy.deepcopy(value)
    value.pop("review_id", None)
    value.pop("review_sha256", None)
    value["review_id"] = "imgphotosupportreview_" + content_sha256(value)[7:39]
    value["review_sha256"] = content_sha256(value)
    return value


def _value():
    evidence = _pin("5", "unused", "reports/own-review.json", "text/plain")
    evidence["schema_ref"] = "eom://schemas/operations/plain-text-log/1.0"
    source = VisualReferencePngArtifactPointer(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "1" * 32,
        sha256="sha256:" + "1" * 64,
        size_bytes=1,  # Synthetic pointer only; not an existence/size assertion.
    )
    return _seal(
        dict(
            schema_version="local-image-photo-object-support-review/1.0",
            source_commit="a" * 40,
            created_at="2026-10-06T07:20:00Z",
            purpose="EVALUATION_ONLY_OBJECT_SUPPORT",
            activation_policy="FORBIDDEN",
            context_policy="SUBJECT_MORPHOLOGY_ONLY_IRRELEVANT_BACKDROP",
            source_kind="PHOTOGRAPH",
            source_population="LICENSED_MORPHOLOGY_REFERENCES_NOT_CORPUS_HOLDOUT",
            source_coordinate_system="NORMALIZED_PHOTO_PIXELS_800X504",
            mask_coordinate_system="CANNY_CANVAS_PIXELS_832X512",
            source=source.model_dump(mode="json", exclude={"size_bytes"}),
            prior_control=_pin(
                "2",
                "sdxl-canny-conditioning-output/1.0",
                "conditionings/imgsdxlcase_" + "a" * 32 + ".png",
            ),
            support_mask=_pin("3", "photo-object-support-mask/1.0", "masks/foreground.png"),
            candidate_control=_pin(
                "4", "photo-object-support-conditioning/1.0", "conditionings/candidate.png"
            ),
            pixel_observation=dict(
                width_px=832,
                height_px=512,
                mask_mode="L",
                control_mode="RGB",
                mask_tones=[0, 255],
                control_polarity="WHITE_EDGES_ON_BLACK_RGB",
                support_area_pixels=1000,
                original_edges=100,
                retained_edges=60,
                deleted_edges=40,
                added_edges=0,
            ),
            own_review_evidence=evidence,
            reviewed_at="2026-10-06T07:15:00Z",
            reviewed_by="root-own-review",
            decision="OWN_INPUT_ACCEPTED_FOR_BOUNDED_COMPARISON_NOT_PUBLICATION",
            review_independence="OWN_NOT_BLIND",
            preserved_features=["ORIENTATION_POSITION", "VISIBLE_WHEELS", "WHOLE_SILHOUETTE"],
            observation=(
                "Own input view only; synthetic fixture does not establish semantic preservation."
            ),
        )
    )


def _pointer(raw):
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "6" * 32,
        artifact_revision_id="rev_" + "6" * 32,
        member_path="manifests/photo-object-support-review.json",
        schema_ref=REVIEW_SCHEMA,
        media_type="application/json",
        sha256="sha256:" + hashlib.sha256(raw).hexdigest(),
    )


def test_review_schema_canonical_roundtrip_and_frozen():
    value = _value()
    validate_contract("photo-object-support-review", value)
    raw = content_json_bytes(value)
    review = parse_photo_object_support_review(_pointer(raw), raw)
    assert raw == content_json_bytes(review.model_dump(mode="json"))
    assert review.review_independence == "OWN_NOT_BLIND"
    assert review.activation_policy == "FORBIDDEN"
    assert review.pixel_observation.added_edges == 0
    with pytest.raises(ValidationError):
        review.review_id = "imgphotosupportreview_" + "b" * 32


@pytest.mark.parametrize(
    "path,replacement",
    [
        (("source", "schema_ref"), PREFIX + "normalized-visual-reference/2.0"),
        (("source", "schema_ref"), PREFIX + "normalized-visual-reference/1.0"),
        (("source", "member_path"), "references/latest.png"),
        (("source", "media_type"), "image/jpeg"),
        (("support_mask", "schema_ref"), PREFIX + "sdxl-canny-conditioning-output/1.0"),
        (("support_mask", "member_path"), "../foreground.png"),
        (("support_mask", "artifact_revision_id"), "latest"),
        (("support_mask", "media_type"), "application/octet-stream"),
        (("support_mask", "sha256"), "sha256:" + "2" * 64),
        (("prior_control", "member_path"), "conditionings/candidate.png"),
        (("candidate_control", "sha256"), "sha256:" + "2" * 64),
        (("candidate_control", "schema_ref"), PREFIX + "sdxl-canny-conditioning-output/1.0"),
        (("own_review_evidence", "schema_ref"), REVIEW_SCHEMA),
        (("own_review_evidence", "member_path"), "reports/own-review.md"),
        (("pixel_observation", "width_px"), 800),
        (("pixel_observation", "mask_mode"), "RGB"),
        (("pixel_observation", "mask_tones"), [255, 0]),
        (("pixel_observation", "original_edges"), 99),
        (("pixel_observation", "support_area_pixels"), 50),
        (("pixel_observation", "retained_edges"), 0),
        (("pixel_observation", "deleted_edges"), 0),
        (("pixel_observation", "added_edges"), 1),
        (("pixel_observation", "original_edges"), True),
        (("pixel_observation", "original_edges"), 100.0),
        (("context_policy",), "PRESERVE_SCIENTIFIC_SCENE"),
        (("source_kind",), "SCIENTIFIC_DIAGRAM"),
        (("source_population",), "CORPUS_HOLDOUT"),
        (("mask_coordinate_system",), "NORMALIZED_PHOTO_PIXELS_800X504"),
        (("activation_policy",), "ALLOWED"),
        (("decision",), "PUBLICATION_APPROVED"),
        (("review_independence",), "INDEPENDENT_BLIND"),
        (("reviewed_at",), "2026-10-06T07:21:00Z"),
        (("reviewed_at",), "2026-10-06T16:15:00+09:00"),
        (("reviewed_at",), "2026-10-06T07:15:00"),
        (("preserved_features",), ["VISIBLE_WHEELS", "WHOLE_SILHOUETTE"]),
        (
            ("preserved_features",),
            ["ORIENTATION_POSITION", "ORIENTATION_POSITION", "WHOLE_SILHOUETTE"],
        ),
        (("preserved_features",), ["WHOLE_SILHOUETTE", "ORIENTATION_POSITION"]),
        (("preserved_features",), ["ORIENTATION_POSITION", "UNSAFE lower", "WHOLE_SILHOUETTE"]),
        (("extra_blob",), {"pixels": "not permitted"}),
    ],
)
def test_invalid_metadata_refused_even_with_resealed_identity(path, replacement):
    value = _value()
    target = value
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = replacement
    raw = content_json_bytes(_seal(value))
    with pytest.raises((SchemaError, ValidationError)):
        parse_photo_object_support_review(_pointer(raw), raw)


@pytest.mark.parametrize("field", ["review_id", "review_sha256"])
def test_identity_and_semantic_hash_refused(field):
    value = _value()
    value[field] = (
        "imgphotosupportreview_" + "b" * 32 if field == "review_id" else "sha256:" + "b" * 64
    )
    raw = content_json_bytes(value)
    with pytest.raises(ValidationError, match="IDENTITY_HASH"):
        parse_photo_object_support_review(_pointer(raw), raw)


def test_review_pointer_raw_hash_bound_and_canonical_guards():
    raw = content_json_bytes(_value())
    pointer = _pointer(raw)
    with pytest.raises(ValueError, match="BOUND_HASH"):
        parse_photo_object_support_review(pointer, raw + b" ")
    for bad_raw in (b"", b" " * (128 * 1024 + 1)):
        with pytest.raises(ValueError, match="BOUND_HASH"):
            parse_photo_object_support_review(_pointer(bad_raw), bad_raw)
    noncanonical = json.dumps(_value(), indent=2).encode()
    with pytest.raises(ValueError, match="NONCANONICAL"):
        parse_photo_object_support_review(_pointer(noncanonical), noncanonical)
    for field, wrong in (
        ("schema_ref", REVIEW_SCHEMA + "-latest"),
        ("media_type", "text/plain"),
        ("member_path", "review.json"),
    ):
        altered = pointer.model_copy(update={field: wrong})
        with pytest.raises(ValueError, match="POINTER_KIND"):
            parse_photo_object_support_review(altered, raw)


def test_revision_or_source_changes_require_new_review_identity():
    first = _value()
    for name in ("source", "prior_control", "support_mask", "candidate_control"):
        second = copy.deepcopy(first)
        second[name]["artifact_revision_id"] = "rev_" + "b" * 32
        raw = content_json_bytes(second)
        with pytest.raises(ValidationError, match="IDENTITY_HASH"):
            parse_photo_object_support_review(_pointer(raw), raw)
        sealed = _seal(second)
        admitted = parse_photo_object_support_review(
            _pointer(content_json_bytes(sealed)), content_json_bytes(sealed)
        )
        assert admitted.review_id != first["review_id"]
    # No mock lookup above proves target existence/access; that is application work.


@pytest.mark.parametrize("value", [False, True, 0.0, "0"])
def test_direct_model_also_rejects_noninteger_added_edge_claim(value):
    data = _value()
    data["pixel_observation"]["added_edges"] = value
    with pytest.raises(ValidationError, match="ADDED_EDGES_NOT_INTEGER_ZERO"):
        PhotoObjectSupportReview.model_validate(_seal(data))


def test_frozen_schema_resources_match_model_and_no_infrastructure_import():
    root = Path(__file__).resolve().parents[2]
    name = SCHEMA_FILES["photo-object-support-review"]
    raw = (root / "schemas/image-provider" / name).read_bytes()
    assert (
        raw == (root / "packages/image_contracts/eom_image_contracts/schemas" / name).read_bytes()
    )
    assert (
        "sha256:" + hashlib.sha256(raw).hexdigest() == SCHEMA_SHA256["photo-object-support-review"]
    )
    generated = PhotoObjectSupportReview.model_json_schema()
    generated.update(
        {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": REVIEW_SCHEMA}
    )
    assert json.loads(raw) == generated
    module = root / "packages/image_contracts/eom_image_contracts/photo_object_support.py"
    imported = set()
    for node in ast.walk(ast.parse(module.read_text())):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    allowed = {
        "__future__",
        "eom_image_contracts",
        "hashlib",
        "json",
        "re",
        "datetime",
        "dataclasses",
        "typing",
        "pydantic",
    }
    assert all(name.split(".", 1)[0] in allowed for name in imported)
