"""Novel-source authority tests, not photographic style or GPU acceptance."""

from __future__ import annotations

import copy
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from eom_image_contracts.models import content_json_bytes, content_sha256, text_sha256
from eom_image_contracts.sdxl_photo_style import (
    LocalImageSdxlPhotoStylePlan,
    parse_photo_style_source,
    photo_style_artifact_pointer,
    validate_photo_style_sources,
)
from eom_image_contracts.sdxl_validation_comparison import parse_sdxl_validation_command
from eom_image_contracts.validation import (
    SCHEMA_FILES,
    SCHEMA_SHA256,
    load_schema,
    validate_contract,
)
from eom_image_contracts.visual_reference import (
    LocalImageVisualReferenceBundle,
    LocalImageVisualReferenceIntent,
    LocalImageVisualReferencePointer,
    NormalizedVisualReferenceMember,
    VisualReferenceIntentArtifactPointer,
    VisualReferenceIntentCandidate,
    VisualReferenceSource,
)
from eom_image_provider.sdxl_comparison_command import load_sdxl_comparison_command
from eom_orchestrator import sdxl_photo_style_inputs as admission
from eom_orchestrator import sdxl_validation_inputs as reserved_admission
from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError
from eom_orchestrator.local_image_training_control_artifacts import (
    LocalImageTrainingControlArtifactPublisher,
)
from jsonschema import ValidationError as SchemaError
from pydantic import ValidationError

from tests.unit.test_local_image_training_control_artifacts import _Publisher
from tests.unit.test_sdxl_native_validation import _native_fixture

NOW = datetime(2026, 10, 5, 18, tzinfo=UTC)


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seal_plan(value):
    value = copy.deepcopy(value)
    value.pop("plan_id", None)
    value.pop("plan_sha256", None)
    value["plan_id"] = "imgsdxlphotoplan_" + content_sha256(value)[7:39]
    value["plan_sha256"] = content_sha256(value)
    return value


def _source(index=1, *, original_hash=None, normalized_bytes=None):
    intent_value = dict(
        schema_version="local-image-visual-reference-intent/1.0",
        intent_id="imgrefintent_" + f"{index:032x}",
        workflow_id="workflow_" + f"{index:032x}",
        image_step_run_id="steprun_" + f"{index:032x}",
        image_job_id="job_" + f"{index:032x}",
        visual_ordinal=0,
        drawing_sha256=_sha(str(index).encode()),
        subject=f"reference photograph {index}",
        query_terms=("reference photograph",),
        candidates=(
            dict(
                rank=1,
                page_id=index,
                file_title=f"File:Photo {index}.jpg",
                canonical_page_url=f"https://commons.wikimedia.org/wiki/File:Photo_{index}.jpg",
                selection_rationale="A morphology photograph for isolated evaluation.",
            ),
        ),
        primary_candidate_page_id=index,
    )
    intent_value["candidates"] = tuple(
        VisualReferenceIntentCandidate.model_validate(v).model_dump(mode="json")
        for v in intent_value["candidates"]
    )
    intent = LocalImageVisualReferenceIntent.model_validate(
        {**intent_value, "intent_sha256": content_sha256(intent_value)}
    )
    intent_raw = content_json_bytes(intent.model_dump(mode="json"))
    bundle_value = dict(
        schema_version="local-image-visual-reference-bundle/1.0",
        bundle_id="imgrefbundle_" + f"{index:032x}",
        bundle_revision_id="imgrefbundlerev_" + f"{index:032x}",
        intent=dict(
            artifact_id="artifact_" + f"{index + 100:032x}",
            artifact_revision_id="rev_" + f"{index + 100:032x}",
            sha256=_sha(intent_raw),
            size_bytes=len(intent_raw),
        ),
        subject=intent.subject,
        observed_at=NOW - timedelta(minutes=2),
        sources=(
            dict(
                reference_id="imgref_" + f"{index:032x}",
                rank=1,
                page_id=index,
                page_revision_id=10,
                file_title=f"File:Photo {index}.jpg",
                canonical_page_url=intent.candidates[0].canonical_page_url,
                original_file_url=f"https://upload.wikimedia.org/wikipedia/commons/a/photo_{index}.jpg",
                original_media_type="image/jpeg",
                original_size_bytes=1000,
                original_sha256=original_hash or _sha(f"original:{index}".encode()),
                original_width_px=1200,
                original_height_px=800,
                license_id="CC0-1.0",
                license_url="https://creativecommons.org/publicdomain/zero/1.0/",
                license_short_name="CC0 1.0",
                disposition="PRIMARY_CONDITIONING",
            ),
        ),
        primary_reference_id="imgref_" + f"{index:032x}",
        normalized_member=dict(
            size_bytes=len(normalized_bytes) if normalized_bytes is not None else 2000,
            sha256=_sha(
                normalized_bytes if normalized_bytes is not None else f"normalized:{index}".encode()
            ),
        ),
    )
    bundle_value.update(
        state="APPROVED",
        provider_api_revision="wikimedia-commons-api/1.0",
        normalization_policy="reference-raster-normalization/1.0",
        observed_at=bundle_value["observed_at"].isoformat().replace("+00:00", "Z"),
        intent=VisualReferenceIntentArtifactPointer.model_validate(
            bundle_value["intent"]
        ).model_dump(mode="json"),
        sources=tuple(
            VisualReferenceSource.model_validate(v).model_dump(mode="json")
            for v in bundle_value["sources"]
        ),
        normalized_member=NormalizedVisualReferenceMember.model_validate(
            bundle_value["normalized_member"]
        ).model_dump(mode="json"),
    )
    bundle = LocalImageVisualReferenceBundle.model_validate(
        {**bundle_value, "bundle_sha256": content_sha256(bundle_value)}
    )
    # Defaults are canonicalized before computing the final immutable semantic hash.
    value = bundle.model_dump(mode="json", exclude={"bundle_sha256"})
    bundle = LocalImageVisualReferenceBundle.model_validate(
        {**value, "bundle_sha256": content_sha256(value)}
    )
    bundle_raw = content_json_bytes(bundle.model_dump(mode="json"))
    reference = LocalImageVisualReferencePointer.model_validate(
        dict(
            bundle_id=bundle.bundle_id,
            bundle_revision_id=bundle.bundle_revision_id,
            bundle_manifest=dict(
                artifact_id="artifact_" + f"{index:032x}",
                artifact_revision_id="rev_" + f"{index:032x}",
                sha256=_sha(bundle_raw),
                size_bytes=len(bundle_raw),
            ),
            primary_reference_id=bundle.primary_reference_id,
            reference_member=dict(
                artifact_id="artifact_" + f"{index:032x}",
                artifact_revision_id="rev_" + f"{index:032x}",
                **bundle.normalized_member.model_dump(
                    mode="json", exclude={"width_px", "height_px", "mode"}
                ),
            ),
        )
    )
    source = parse_photo_style_source(reference, bundle_raw=bundle_raw, intent_raw=intent_raw)
    return source, bundle_raw, intent_raw


def _plan(sources, anchor=None):
    cases = []
    for source in sources:
        prompt, negative = (
            "A restrained black and white exam illustration.",
            "Photographic texture, color, text and excessive detail.",
        )
        value = dict(
            depiction_key="PHOTO_" + str(source.intent.primary_candidate_page_id),
            reference_image=photo_style_artifact_pointer(
                source.reference.reference_member
            ).model_dump(mode="json"),
            reference_width_px=800,
            reference_height_px=504,
            prompt_en=prompt,
            prompt_sha256=text_sha256(prompt),
            negative_prompt_en=negative,
            negative_prompt_sha256=text_sha256(negative),
            seeds=(104729,),
        )
        value["case_id"] = "imgsdxlcase_" + content_sha256(value)[7:39]
        value["staged_member_path"] = "inputs/" + value["case_id"] + ".png"
        cases.append(
            dict(
                visual_reference=source.reference.model_dump(mode="json"),
                case=value,
                source_review=dict(
                    source_kind="PHOTOGRAPH",
                    reviewed_at=NOW - timedelta(minutes=1),
                    reviewed_by="fixture-only",
                    reference_sha256=source.reference.reference_member.sha256,
                    observation="Synthetic review only, not an actual photograph.",
                ),
            )
        )
    if anchor is None:
        anchor = dict(
            artifact_id="artifact_" + "a" * 32,
            artifact_revision_id="rev_" + "b" * 32,
            member_path="manifests/sdxl-canny-reference-command.json",
            schema_ref="eom://schemas/image-provider/local-image-sdxl-canny-reference-command/1.2",
            media_type="application/json",
            sha256="sha256:" + "c" * 64,
        )
    value = dict(
        schema_version="local-image-sdxl-photo-style-plan/1.0",
        source_commit="d" * 40,
        created_at=NOW,
        purpose="EVALUATION_ONLY_PHOTO_TO_EXAM_STYLE",
        dispatch_policy="PREPARATION_ONLY_NOT_A_WORKER_COMMAND",
        activation_policy="FORBIDDEN",
        source_population="LICENSED_MORPHOLOGY_REFERENCES_NOT_CORPUS_HOLDOUT",
        configuration_anchor=anchor,
        cases=sorted(cases, key=lambda c: c["case"]["case_id"]),
        seed=104729,
        initialization=dict(
            policy="FIT_GRAYSCALE_WHITE_RGB_832X512/1.0",
            denoising_strength=0.7,
            scheduler_steps=30,
            effective_denoising_steps=21,
            pillow_version="11.3.0",
        ),
        budget=dict(
            maximum_duration_ms=600000,
            maximum_peak_gpu_memory_bytes=16 * 1024**3,
            maximum_outputs=12,
            maximum_dispatches=1,
            automatic_retry=False,
        ),
    )
    # Hash JSON-shaped timestamp serialization, not datetime repr.
    value["created_at"] = NOW.isoformat().replace("+00:00", "Z")
    for entry in value["cases"]:
        entry["source_review"]["reviewed_at"] = (
            entry["source_review"]["reviewed_at"].isoformat().replace("+00:00", "Z")
        )
    return LocalImageSdxlPhotoStylePlan.model_validate(_seal_plan(value))


def _native_plan(source, command):
    plan = _plan((source,), command.configuration_anchor.model_dump(mode="json"))
    value = plan.model_dump(mode="json")
    value["created_at"] = (
        (command.created_at + timedelta(days=1)).isoformat().replace("+00:00", "Z")
    )
    return LocalImageSdxlPhotoStylePlan.model_validate(_seal_plan(value))


def test_plan_schema_mirror_hash_and_not_dispatch(tmp_path):
    plan = _plan((_source()[0],))
    validate_contract("sdxl-photo-style-plan", plan.model_dump(mode="json"))
    assert load_schema("sdxl-photo-style-plan")["$schema"].endswith("2020-12/schema")
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    member = SCHEMA_FILES["sdxl-photo-style-plan"]
    raw = (root / "schemas/image-provider" / member).read_bytes()
    assert (
        raw == (root / "packages/image_contracts/eom_image_contracts/schemas" / member).read_bytes()
    )
    assert _sha(raw) == SCHEMA_SHA256["sdxl-photo-style-plan"]
    with pytest.raises(ValueError, match="FAMILY_INVALID"):
        parse_sdxl_validation_command(plan.model_dump(mode="json"))
    path = tmp_path / "command.json"
    path.write_bytes(content_json_bytes(plan.model_dump(mode="json")))
    from eom_image_provider.provider import ProviderError

    with pytest.raises(ProviderError, match="SDXL_PROBE_INPUT_INVALID"):
        load_sdxl_comparison_command(tmp_path, path)


@pytest.mark.parametrize(
    "field,value",
    [
        ("dispatch_policy", "DISPATCH"),
        ("activation_policy", "ALLOWED"),
        ("source_population", "HOLDOUT"),
        ("seed", -1),
        ("unexpected", True),
    ],
)
def test_plan_rejects_scope_widening(field, value):
    body = _plan((_source()[0],)).model_dump(mode="json")
    body[field] = value
    with pytest.raises((ValidationError, SchemaError)):
        validate_contract("sdxl-photo-style-plan", _seal_plan(body))


@pytest.mark.parametrize(
    "fault",
    ["hash", "revision", "primary", "size", "member", "review", "time", "seed", "initializer"],
)
def test_semantic_identity_and_review_guards(fault):
    body = _plan((_source()[0],)).model_dump(mode="json")
    if fault == "hash":
        body["plan_sha256"] = "sha256:" + "0" * 64
    elif fault == "revision":
        body["cases"][0]["visual_reference"]["reference_member"]["artifact_revision_id"] = (
            "rev_" + "f" * 32
        )
    elif fault == "primary":
        body["cases"][0]["visual_reference"]["reference_member"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "size":
        body["cases"][0]["case"]["reference_width_px"] = 801
    elif fault == "member":
        body["cases"][0]["case"]["reference_image"]["schema_ref"] = (
            "eom://schemas/image-provider/local-image-science-visual-crop/1.0"
        )
    elif fault == "review":
        body["cases"][0]["source_review"]["reference_sha256"] = "sha256:" + "f" * 64
    elif fault == "time":
        body["cases"][0]["source_review"]["reviewed_at"] = (NOW + timedelta(minutes=1)).isoformat()
    elif fault == "seed":
        body["seed"] += 1
    else:
        body["initialization"]["denoising_strength"] = 0.35
    with pytest.raises(ValidationError):
        LocalImageSdxlPhotoStylePlan.model_validate(body if fault == "hash" else _seal_plan(body))


@pytest.mark.parametrize(
    "fault",
    ["bundle_hash", "intent_hash", "noncanonical", "foreign_intent", "license", "alternate"],
)
def test_source_metadata_fail_closed(fault):
    source, bundle_raw, intent_raw = _source()
    reference = source.reference
    if fault == "bundle_hash":
        bundle_raw += b" "
    elif fault == "intent_hash":
        intent_raw += b" "
    elif fault == "noncanonical":
        bundle_raw += b"\n"
        reference = reference.model_copy(
            update={
                "bundle_manifest": reference.bundle_manifest.model_copy(
                    update={"sha256": _sha(bundle_raw), "size_bytes": len(bundle_raw)}
                )
            }
        )
    else:
        value = source.bundle.model_dump(mode="json")
        if fault == "foreign_intent":
            value["subject"] = "a foreign request"
        elif fault == "license":
            value["sources"][0]["license_id"] = "CC-BY-4.0"
        else:
            value["sources"][0]["file_title"] = "File:A different primary.jpg"
        value["bundle_sha256"] = content_sha256(
            {k: v for k, v in value.items() if k != "bundle_sha256"}
        )
        bundle_raw = content_json_bytes(value)
        reference = reference.model_copy(
            update={
                "bundle_manifest": reference.bundle_manifest.model_copy(
                    update={"sha256": _sha(bundle_raw), "size_bytes": len(bundle_raw)}
                )
            }
        )
    with pytest.raises((ValueError, SchemaError)):
        parse_photo_style_source(reference, bundle_raw=bundle_raw, intent_raw=intent_raw)


def test_duplicate_original_and_training_collision():
    first = _source()[0]
    second = _source(2, original_hash=first.bundle.sources[0].original_sha256)[0]
    plan = _plan((first, second))
    sources = tuple(
        sorted(
            (first, second),
            key=lambda s: next(
                c.case.case_id for c in plan.cases if c.visual_reference == s.reference
            ),
        )
    )
    with pytest.raises(ValueError, match="collision"):
        validate_photo_style_sources(plan, sources, training_image_hashes=frozenset())
    with pytest.raises(ValueError, match="collision"):
        validate_photo_style_sources(
            _plan((first,)),
            (first,),
            training_image_hashes=frozenset({first.reference.reference_member.sha256}),
        )


def test_plan_publication_hash_pin_and_source_mismatch():
    plan = _plan((_source()[0],))
    fake = _Publisher()
    publisher = LocalImageTrainingControlArtifactPublisher(fake, source_commit=plan.source_commit)
    pointer = publisher.commit_sdxl_photo_style_plan(plan)
    assert pointer.member_path == "manifests/sdxl-photo-style-plan.json"
    assert pointer.schema_ref.endswith("sdxl-photo-style-plan/1.0")
    assert pointer.sha256 == _sha(content_json_bytes(plan.model_dump(mode="json")))
    with pytest.raises(ValueError, match="source commit"):
        LocalImageTrainingControlArtifactPublisher(
            fake, source_commit="f" * 40
        ).commit_sdxl_photo_style_plan(plan)


def test_metadata_admission_reuses_complete_native_closure_and_reads_no_binaries(
    tmp_path, monkeypatch
):
    old, reader, _ = _native_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        admission,
        "resolve_sdxl_canny_reference_metadata",
        reserved_admission.resolve_sdxl_canny_reference_metadata,
    )
    source, bundle_raw, intent_raw = _source()
    plan = _native_plan(source, old)
    reader.records[photo_style_artifact_pointer(source.reference.bundle_manifest)] = bundle_raw
    reader.records[photo_style_artifact_pointer(source.bundle.intent)] = intent_raw
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)
    batches = []

    def read_batch(engine, reads):
        batches.append(reads)
        assert all(read.pointer.media_type == "application/json" for read in reads)
        return tuple(
            reader(engine, read.pointer, maximum_bytes=read.maximum_bytes) for read in reads
        )

    monkeypatch.setattr(admission, "resolve_control_artifact_members", read_batch)
    prepared = admission.resolve_sdxl_photo_style_metadata(object(), plan)
    assert len(batches) == 2
    assert prepared.sources == (source,)
    assert len(prepared.configuration.native_admission.sources.regions) == 12
    assert all(
        not member.member_path.endswith((".png", ".safetensors", ".pdf"))
        for member in prepared.files
    )
    assert all(pointer.media_type == "application/json" for pointer in reader.calls)
    assert admission.resolve_sdxl_photo_style_metadata(object(), plan) == prepared


@pytest.mark.parametrize("reason", ["MISSING", "STALE", "PERMISSION", "HASH_MISMATCH"])
def test_resolver_failure_precedes_binary_materialization(tmp_path, monkeypatch, reason):
    old, reader, _ = _native_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        admission,
        "resolve_sdxl_canny_reference_metadata",
        reserved_admission.resolve_sdxl_canny_reference_metadata,
    )
    source, _, _ = _source()
    plan = _native_plan(source, old)
    monkeypatch.setattr(admission, "resolve_control_artifact_member", reader)

    def denied(engine, reads):
        assert all(read.pointer.media_type == "application/json" for read in reads)
        raise ControlArtifactResolutionError("CONTROL_ARTIFACT_" + reason)

    monkeypatch.setattr(admission, "resolve_control_artifact_members", denied)
    with pytest.raises(ControlArtifactResolutionError, match=reason):
        admission.resolve_sdxl_photo_style_metadata(object(), plan)
