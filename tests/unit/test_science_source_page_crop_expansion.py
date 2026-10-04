"""Synthetic closed supplemental provenance; not live pixels or model quality acceptance."""

from __future__ import annotations

import ast
import copy
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts import ScienceAssessmentWebCorpusManifestV2
from eom_catalog_service.science_visual_expansion_planning import (
    build_science_visual_expansion_plan,
    validate_science_visual_expansion_plan_sources,
)
from eom_catalog_service.science_visual_pilot import (
    ScienceVisualPilotPlanningError,
    build_science_corpus_training_authorization,
    build_science_visual_pilot_plan_v3,
)
from eom_image_contracts import (
    SCHEMA_SHA256,
    SCIENCE_ORIGINAL_PAGE_SCHEMA_REF,
    SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF,
    SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
    ImageEvaluationArtifactMember,
    LocalImageScienceCorpusVisualPilotPlanV3,
    LocalImageScienceCorpusVisualPilotPlanV4,
    LocalImageScienceCorpusVisualPilotResult,
    LocalImageScienceSourcePageCropReview,
    LocalImageScienceSourcePageCropReviewV2,
    LocalImageScienceSourcePageCropSet,
    LocalImageScienceSourcePageCropSetV2,
    content_json_bytes,
    content_sha256,
    load_schema,
    science_visual_expansion_campaign_id,
    source_page_crop_pointer,
    source_page_crop_protocol,
    source_page_crop_selection_id,
    text_sha256,
    validate_contract,
    validate_source_page_crop_set,
)
from eom_orchestrator import source_page_crop_expansion_inputs as supplemental
from eom_orchestrator import source_page_crop_inputs as admission
from eom_orchestrator import source_page_crop_publication as publication
from eom_orchestrator.file_set_control_artifacts import ControlFileSetPublisher
from eom_orchestrator.source_page_crop_processing import ScienceSourcePageCropPixels
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from tests.unit.test_science_corpus_visual_contracts import _plan_v3_value, _result_value
from tests.unit.test_science_source_page_crops import _fixture_review, _page, _seal_review
from tests.unit.test_science_visual_expansion import _seal
from tests.unit.test_science_visual_pilot_planning import _document


def _sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _pointer(document, index, schema_ref, member):
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + f"{index:032x}",
        artifact_revision_id="rev_" + f"{index:032x}",
        member_path=member,
        schema_ref=schema_ref,
        media_type="application/json",
        sha256=_sha(content_json_bytes(document.model_dump(mode="json"))),
    )


def _result(plan):
    pages = [
        {
            "document_id": source.document_id,
            "physical_page": number,
            "member_path": f"pages/{source.document_id}/page-{number}.png",
            "sha256": content_sha256({"document_id": source.document_id, "page": number}),
            "size_bytes": 1024,
            "width_px": 1200,
            "height_px": 1600,
        }
        for source in plan.selected_sources
        for number in range(1, source.page_count + 1)
    ]
    page = next(
        value
        for value in pages
        if value["document_id"]
        == next(
            source.document_id for source in plan.selected_sources if source.partition == "TRAIN"
        )
    )
    candidate = {
        "document_id": page["document_id"],
        "physical_page": 1,
        "page_image_sha256": page["sha256"],
        "bounding_box": {"left": 1000, "top": 1000, "right": 4000, "bottom": 4000},
        "representation_kind": "UNKNOWN",
        "rendering_mode": "MIXED",
        "visual_features": [],
        "authority_class": "UNKNOWN_REVIEW_REQUIRED",
        "review_state": "PENDING",
        "locator_score_milli": 100,
    }
    candidate["candidate_id"] = "imgsciviscandidate_" + content_sha256(candidate)[7:39]
    candidate["member_path"] = f"crops/{candidate['candidate_id']}.png"
    candidate["sha256"] = content_sha256({"crop": page["document_id"]})
    candidate["size_bytes"] = 1024
    value = {
        "schema_version": "local-image-science-corpus-visual-pilot-result/1.0",
        "pilot_id": plan.pilot_id,
        "plan_sha256": plan.plan_sha256,
        "status": "SUCCEEDED",
        "page_images": sorted(
            pages, key=lambda value: (value["document_id"], value["physical_page"])
        ),
        "visual_candidates": [candidate],
        "omissions": [],
        "runtime": _result_value()["runtime"],
        "error_code": None,
        "started_at": "2026-10-04T06:30:00Z",
        "completed_at": "2026-10-04T07:00:00Z",
    }
    value["result_sha256"] = content_sha256(value)
    return LocalImageScienceCorpusVisualPilotResult.model_validate(value)


@pytest.fixture(scope="module")
def expanded():
    template = LocalImageScienceCorpusVisualPilotPlanV3.model_validate(_plan_v3_value())
    documents = tuple(
        sorted((_document(index) for index in range(600)), key=lambda value: value.sha256)
    )
    identity = {
        "schema_version": "science-assessment-web-corpus-manifest/2.0",
        "plan_id": "sciencecorpusplan_" + "1" * 32,
        "plan_sha256": "sha256:" + "1" * 64,
        "acquisition_sha256": template.acquisition_sha256,
        "resolution_sha256": template.resolution_sha256,
        "resolution_policy_id": template.resolution_policy_id,
        "resolution_policy_sha256": template.resolution_policy_sha256,
    }
    value = {
        **identity,
        "corpus_id": "sciencecorpus_" + content_sha256(identity)[7:39],
        "observed_at": "2026-09-25T15:30:00Z",
        "pdf_validator": {
            "qpdf_path": "/usr/bin/qpdf",
            "qpdf_sha256": "sha256:" + "c" * 64,
            "pdfinfo_path": "/usr/bin/pdfinfo",
            "pdfinfo_sha256": "sha256:" + "d" * 64,
        },
        "documents": [document.model_dump(mode="json") for document in documents],
        "failures": [],
        "intake_shards": [],
        "summary": {
            "unique_document_count": 600,
            "scanned_post_count": 600,
            "candidate_count": 600,
            "acquisition_failure_count": 0,
            "duplicate_observation_count": 0,
            "reused_existing_count": 600,
            "new_intake_count": 0,
            "total_bytes": sum(document.bytes for document in documents),
        },
    }
    value["manifest_sha256"] = content_sha256(value)
    corpus = ScienceAssessmentWebCorpusManifestV2.model_validate(value)
    corpus_pointer = _pointer(
        corpus,
        9000,
        "eom://schemas/legacy-assessment/science-assessment-web-corpus-manifest/2.0",
        "corpus-manifest.json",
    )
    authorization = build_science_corpus_training_authorization(
        corpus=corpus,
        corpus_manifest=corpus_pointer,
        approved_at=datetime(2026, 9, 25, 16, tzinfo=UTC),
        approved_by="fixture.operator",
    )
    authorization_pointer = _pointer(
        authorization,
        9001,
        "eom://schemas/image-provider/local-image-science-corpus-training-authorization/1.0",
        "manifests/science-corpus-training-authorization.json",
    )
    common = {
        "corpus": corpus,
        "corpus_manifest": corpus_pointer,
        "authorization": authorization,
        "authorization_pointer": authorization_pointer,
        "selection_seed_sha256": template.selection_seed_sha256,
        "guidance_authorities": template.guidance_authorities,
        "tools": template.tools,
        "source_commit": "b" * 40,
        "created_by": "fixture.operator",
        "locator_policy": template.locator_policy,
        "campaign_shard_count": 3,
    }
    predecessors = tuple(
        build_science_visual_pilot_plan_v3(
            **common, campaign_shard_index=index, created_at=template.created_at
        )
        for index in range(3)
    )
    predecessor_pointers = tuple(
        _pointer(
            plan,
            9100 + index,
            "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.2",
            "manifests/visual-pilot-plan.json",
        )
        for index, plan in enumerate(predecessors)
    )
    plans = tuple(
        build_science_visual_expansion_plan(
            **common,
            predecessor_plans=predecessors,
            predecessor_plan_pointers=predecessor_pointers,
            campaign_shard_index=index,
            created_at=datetime(2026, 10, 4, 6, tzinfo=UTC),
            source_limit=18,
            page_limit=120,
        )
        for index in range(3)
    )
    results = tuple(_result(plan) for plan in plans)
    pairs = tuple(
        {
            "pilot_plan": _pointer(
                plan,
                9200 + index,
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.3",
                "manifests/visual-pilot-plan.json",
            ).model_dump(mode="json"),
            "pilot_result": _pointer(
                result,
                9300 + index,
                "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-result/1.0",
                "manifests/visual-pilot-result.json",
            ).model_dump(mode="json"),
        }
        for index, (plan, result) in enumerate(zip(plans, results, strict=True))
    )
    basis = SimpleNamespace(
        authorization=authorization,
        crop_set=SimpleNamespace(training_authorization=authorization_pointer),
        plans=predecessors,
        inventory=SimpleNamespace(
            pilot_results=tuple(
                SimpleNamespace(pilot_plan=pointer) for pointer in predecessor_pointers
            )
        ),
    )
    return SimpleNamespace(
        corpus=corpus,
        authorization=authorization,
        authorization_pointer=authorization_pointer,
        predecessors=predecessors,
        predecessor_pointers=predecessor_pointers,
        plans=plans,
        results=results,
        pairs=pairs,
        basis=basis,
    )


def _review(expanded):
    plan, result, pair = expanded.plans[0], expanded.results[0], expanded.pairs[0]
    candidate = result.visual_candidates[0]
    source = next(
        value for value in plan.selected_sources if value.document_id == candidate.document_id
    )
    page = next(
        value
        for value in result.page_images
        if value.document_id == candidate.document_id
        and value.physical_page == candidate.physical_page
    )
    selection = {
        "candidate_id": candidate.candidate_id,
        "parent_candidate_sha256": candidate.sha256,
        "document_id": candidate.document_id,
        "physical_page": candidate.physical_page,
        "source_document": source.pdf.model_dump(mode="json"),
        "source_page": {
            **pair["pilot_result"],
            "member_path": page.member_path,
            "schema_ref": SCIENCE_ORIGINAL_PAGE_SCHEMA_REF,
            "media_type": "image/png",
            "sha256": page.sha256,
        },
        "page_width_px": page.width_px,
        "page_height_px": page.height_px,
        "page_render_dpi": 144,
        "pixel_box": [150, 210, 420, 490],
        "exam_group_sha256": source.exam_group_sha256,
        "partition": source.partition,
        "depiction_key": "SYNTHETIC_OBJECT",
        "caption_en": "A complete synthetic object",
        "caption_sha256": text_sha256("A complete synthetic object"),
        "expression": "CLEAN_CONTOUR",
    }
    selection["selection_id"] = source_page_crop_selection_id(selection)
    value = {
        "schema_version": "local-image-science-source-page-crop-review/1.1",
        "created_at": "2026-10-04T08:00:00Z",
        "created_by": "fixture.operator",
        "source_commit": "b" * 40,
        "basis_crop_set": {
            "artifact_id": "artifact_" + "a" * 32,
            "artifact_revision_id": "rev_" + "a" * 32,
            "member_path": "manifests/science-object-line-art-crop-set.json",
            "schema_ref": "eom://schemas/image-provider/local-image-science-object-line-art-crop-set/1.0",
            "media_type": "application/json",
            "sha256": "sha256:" + "a" * 64,
        },
        "training_authorization": expanded.authorization_pointer.model_dump(mode="json"),
        "supplemental_pilots": list(expanded.pairs),
        "selections": [selection],
        "policy": "REVIEWED_LITERAL_ORIGINAL_PAGE_PIXELS/1.0",
        "pillow_version": "12.3.0",
        "activation_policy": "FORBIDDEN",
    }
    return LocalImageScienceSourcePageCropReviewV2.model_validate(_seal_review(value))


def _reader(monkeypatch, expanded, review):
    records = {
        expanded.authorization.corpus_manifest: content_json_bytes(
            expanded.corpus.model_dump(mode="json")
        )
    }
    for pair, plan, result in zip(
        review.supplemental_pilots, expanded.plans, expanded.results, strict=True
    ):
        records[pair.pilot_plan] = content_json_bytes(plan.model_dump(mode="json"))
        records[pair.pilot_result] = content_json_bytes(result.model_dump(mode="json"))
    calls = []

    def read(engine, requests):
        calls.append(requests)
        assert 5 <= len(requests) <= 9
        assert not any(
            request.pointer.member_path.endswith((".png", ".pdf")) for request in requests
        )
        output = tuple(records[request.pointer] for request in requests)
        assert all(
            _sha(raw) == request.pointer.sha256
            for request, raw in zip(requests, output, strict=True)
        )
        return output

    monkeypatch.setattr(supplemental, "resolve_control_artifact_members", read)
    monkeypatch.setattr(admission, "resolve_sdxl_training_sources", lambda *a, **kw: expanded.basis)
    monkeypatch.setattr(
        admission,
        "resolve_control_artifact_members",
        lambda *a: pytest.fail("premature page pixel read"),
    )
    return records, calls


def test_full_supplemental_metadata_is_admitted_once_before_page_reads(monkeypatch, expanded):
    review = _review(expanded)
    _records, calls = _reader(monkeypatch, expanded, review)
    reads = admission.prepare_source_page_crop_reads(object(), review)
    assert len(calls) == 1 and len(calls[0]) == 7
    assert len(reads) == 1 and reads[0].selections == review.selections
    assert reads[0].pointer == review.selections[0].source_page
    assert reads[0].size_bytes == 1024
    assert source_page_crop_protocol(review).set_model is LocalImageScienceSourcePageCropSetV2
    assert admission.prepare_source_page_crop_reads(object(), review) == reads


def test_discovery_reuses_lineage_admission_without_fabricating_a_crop_review(
    monkeypatch, expanded
):
    review = _review(expanded)
    _records, calls = _reader(monkeypatch, expanded, review)
    lineage = supplemental.resolve_science_visual_expansion_lineage(
        object(),
        supplemental_pilots=review.supplemental_pilots,
        basis=expanded.basis,
        observed_at=review.created_at,
    )
    assert lineage.plans == expanded.plans and lineage.results == expanded.results
    assert len(calls) == 1 and len(calls[0]) == 7


@pytest.mark.parametrize("fault", ["naive_time", "duplicate", "missing"])
def test_discovery_rejects_bad_presentation_input_before_metadata_reads(
    monkeypatch, expanded, fault
):
    review = _review(expanded)
    _reader(monkeypatch, expanded, review)
    monkeypatch.setattr(
        supplemental,
        "resolve_control_artifact_members",
        lambda *a: pytest.fail("metadata read before input admission"),
    )
    arguments = {
        "supplemental_pilots": review.supplemental_pilots,
        "basis": expanded.basis,
        "observed_at": review.created_at,
    }
    if fault == "naive_time":
        arguments["observed_at"] = datetime(2026, 10, 4, 8)
    elif fault == "duplicate":
        arguments["supplemental_pilots"] = (review.supplemental_pilots[0],) * 3
    else:
        arguments["supplemental_pilots"] = review.supplemental_pilots[:1]
    with pytest.raises(ValueError):
        supplemental.resolve_science_visual_expansion_lineage(object(), **arguments)


@pytest.mark.parametrize(
    "fault",
    ["page_hash", "source_hash", "parent_hash", "partition", "frame", "predecessor_candidate"],
)
def test_rehashed_wrong_selections_fail_before_page_read(monkeypatch, expanded, fault):
    review = _review(expanded)
    _reader(monkeypatch, expanded, review)
    value = review.model_dump(mode="json")
    selection = value["selections"][0]
    if fault == "page_hash":
        selection["source_page"]["sha256"] = "sha256:" + "f" * 64
        selection["selection_id"] = source_page_crop_selection_id(selection)
    elif fault == "source_hash":
        selection["source_document"]["sha256"] = "sha256:" + "f" * 64
    elif fault == "parent_hash":
        selection["parent_candidate_sha256"] = "sha256:" + "f" * 64
    elif fault == "partition":
        selection["partition"] = "HOLDOUT"
    elif fault == "frame":
        selection["pixel_box"] = [900, 1200, 1100, 1400]
        selection["selection_id"] = source_page_crop_selection_id(selection)
    else:
        selection["candidate_id"] = "imgsciviscandidate_" + "f" * 32
    wrong = LocalImageScienceSourcePageCropReviewV2.model_validate(_seal_review(value))
    with pytest.raises(ValueError):
        admission.prepare_source_page_crop_reads(object(), wrong)


@pytest.mark.parametrize(
    "fault",
    [
        "plan_bytes",
        "seed",
        "predecessor_order",
        "campaign",
        "wrong_plan_result",
        "late_result",
        "early_result",
        "missing_page",
        "noncanonical",
    ],
)
def test_false_rehashed_lineage_is_rejected_before_page_read(monkeypatch, expanded, fault):
    review = _review(expanded)
    records, _calls = _reader(monkeypatch, expanded, review)
    value = review.model_dump(mode="json")
    pair = value["supplemental_pilots"][0]
    if fault in {"plan_bytes", "seed", "predecessor_order", "campaign"}:
        body = expanded.plans[0].model_dump(mode="json")
        if fault == "plan_bytes":
            body["selected_sources"][0]["bytes"] += 1
        elif fault == "seed":
            body["selection_seed_sha256"] = "sha256:" + "f" * 64
        elif fault == "predecessor_order":
            body["predecessor_plans"].reverse()
        else:
            body["campaign_shard_count"] = 4
        pointers = tuple(
            ImageEvaluationArtifactMember.model_validate(item) for item in body["predecessor_plans"]
        )
        body["campaign_id"] = science_visual_expansion_campaign_id(
            SimpleNamespace(**body), pointers
        )
        changed = LocalImageScienceCorpusVisualPilotPlanV4.model_validate(_seal(body))
        raw = content_json_bytes(changed.model_dump(mode="json"))
        target = "pilot_plan"
    else:
        body = expanded.results[0].model_dump(mode="json")
        if fault == "wrong_plan_result":
            body["plan_sha256"] = "sha256:" + "f" * 64
        elif fault == "late_result":
            body["completed_at"] = "2026-10-04T09:00:00Z"
        elif fault == "early_result":
            body["started_at"] = "2026-10-04T05:00:00Z"
        elif fault == "missing_page":
            body["page_images"].pop()
        body["result_sha256"] = content_sha256(
            {key: item for key, item in body.items() if key != "result_sha256"}
        )
        raw = content_json_bytes(
            LocalImageScienceCorpusVisualPilotResult.model_validate(body).model_dump(mode="json")
        )
        if fault == "noncanonical":
            raw = b" " + raw
        target = "pilot_result"
    pair[target]["sha256"] = _sha(raw)
    changed_review = LocalImageScienceSourcePageCropReviewV2.model_validate(_seal_review(value))
    records[ImageEvaluationArtifactMember.model_validate(pair[target])] = raw
    with pytest.raises(ValueError):
        admission.prepare_source_page_crop_reads(object(), changed_review)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_shard",
        "reordered_shards",
        "duplicate_plan",
        "duplicate_result",
        "legacy_plan",
        "wrong_media",
    ],
)
def test_supplemental_coverage_and_pointer_contracts_are_closed(monkeypatch, expanded, fault):
    review = _review(expanded)
    _reader(monkeypatch, expanded, review)
    value = review.model_dump(mode="json")
    if fault == "missing_shard":
        value["supplemental_pilots"].pop()
    elif fault == "reordered_shards":
        value["supplemental_pilots"].reverse()
    elif fault.startswith("duplicate"):
        key = "pilot_plan" if fault == "duplicate_plan" else "pilot_result"
        value["supplemental_pilots"][1][key] = copy.deepcopy(value["supplemental_pilots"][0][key])
    elif fault == "legacy_plan":
        value["supplemental_pilots"][0]["pilot_plan"] = expanded.predecessor_pointers[0].model_dump(
            mode="json"
        )
    else:
        value["supplemental_pilots"][0]["pilot_result"]["media_type"] = "image/png"
    with pytest.raises((ValueError, ValidationError)):
        wrong = LocalImageScienceSourcePageCropReviewV2.model_validate(_seal_review(value))
        admission.prepare_source_page_crop_reads(object(), wrong)


def test_selection_rule_replay_is_catalog_owned_and_predecessors_are_exact(expanded):
    arguments = {
        "corpus": expanded.corpus,
        "authorization": expanded.authorization,
        "authorization_pointer": expanded.authorization_pointer,
        "predecessor_plans": expanded.predecessors,
        "predecessor_plan_pointers": expanded.predecessor_pointers,
    }
    for plan in expanded.plans:
        validate_science_visual_expansion_plan_sources(plan, **arguments)
    with pytest.raises(ScienceVisualPilotPlanningError):
        validate_science_visual_expansion_plan_sources(
            expanded.plans[0],
            **(
                arguments
                | {"predecessor_plan_pointers": tuple(reversed(expanded.predecessor_pointers))}
            ),
        )


@pytest.mark.parametrize(
    "error", ["CONTROL_ARTIFACT_POINTER_INVALID", "CONTROL_ARTIFACT_HASH_MISMATCH"]
)
def test_missing_or_corrupted_metadata_never_substitutes_latest_or_reads_pixels(
    monkeypatch, expanded, error
):
    from eom_orchestrator.control_artifact_resolution import ControlArtifactResolutionError

    review = _review(expanded)
    _reader(monkeypatch, expanded, review)

    def rejected(engine, requests):
        assert len(requests) == 7
        raise ControlArtifactResolutionError(error)

    monkeypatch.setattr(supplemental, "resolve_control_artifact_members", rejected)
    with pytest.raises(ControlArtifactResolutionError, match=error):
        admission.prepare_source_page_crop_reads(object(), review)


@pytest.mark.parametrize("kind", ["review", "set"])
def test_additive_schemas_are_pinned_202012_and_packaged(expanded, kind):
    name = "science-source-page-crop-" + kind + "-v2"
    Draft202012Validator.check_schema(load_schema(name))
    filename = "local-image-science-source-page-crop-" + kind + "-v2.schema.json"
    root = Path(__file__).resolve().parents[2]
    raw = (root / "schemas/image-provider" / filename).read_bytes()
    assert SCHEMA_SHA256[name] == _sha(raw)
    assert (
        raw
        == (root / "packages/image_contracts/eom_image_contracts/schemas" / filename).read_bytes()
    )
    assert filename in (root / "scripts/image_trainer/build_release.sh").read_text()
    if kind == "review":
        validate_contract(name, _review(expanded).model_dump(mode="json"))


def test_publication_reuses_literal_pipeline_and_selects_exact_wire_version(
    monkeypatch, expanded, tmp_path
):
    review = _review(expanded)
    _reader(monkeypatch, expanded, review)
    calls = []

    class Publisher:
        def __init__(self, engine, settings):
            pass

        def publish(self, **arguments):
            ControlFileSetPublisher._request(object.__new__(ControlFileSetPublisher), **arguments)
            calls.append(arguments)
            members = {member.file_name: member for member in arguments["members"]}
            primary = members[arguments["primary_file"]]
            assert all(
                _sha(member.source.read_bytes()) == member.sha256 for member in members.values()
            )
            return SimpleNamespace(
                artifact_id="artifact_" + "1" * 32,
                artifact_revision_id="rev_" + "2" * 32,
                primary_file=primary.file_name,
                primary_sha256=primary.sha256,
            )

    monkeypatch.setattr(publication, "ControlFileSetPublisher", Publisher)
    monkeypatch.setattr(
        publication,
        "iter_source_page_crop_payloads",
        lambda engine, reads: iter((read, _page(read.selections[0])[1]) for read in reads),
    )

    def process(raw, selections, **kwargs):
        import io

        from PIL import Image

        selection = selections[0]
        with Image.open(io.BytesIO(raw)) as image:
            cropped = image.crop(selection.pixel_box)
            output = io.BytesIO()
            cropped.save(output, format="PNG")
        return (
            ScienceSourcePageCropPixels(
                selection.selection_id, output.getvalue(), cropped.width, cropped.height, "f" * 16
            ),
        )

    first = publication.materialize_and_publish_source_page_crops(
        object(),
        object(),
        review,
        workspace=tmp_path / "first",
        created_at=datetime(2026, 10, 4, 9, tzinfo=UTC),
        process=process,
    )
    second = publication.materialize_and_publish_source_page_crops(
        object(),
        object(),
        review,
        workspace=tmp_path / "replay",
        created_at=datetime(2026, 10, 4, 9, tzinfo=UTC),
        process=process,
    )
    assert isinstance(first.crop_set, LocalImageScienceSourcePageCropSetV2)
    assert first.crop_set == second.crop_set
    assert calls[0]["idempotency_key"] == calls[2]["idempotency_key"]
    assert calls[1]["idempotency_key"] == calls[3]["idempotency_key"]
    assert calls[0]["members"][0].schema_ref == SOURCE_PAGE_CROP_REVIEW_V2_SCHEMA_REF
    assert (
        next(
            member for member in calls[1]["members"] if member.file_name.endswith(".json")
        ).schema_ref
        == SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF
    )
    validate_contract("science-source-page-crop-set-v2", first.crop_set.model_dump(mode="json"))
    validate_source_page_crop_set(review, first.crop_set)
    assert (
        source_page_crop_pointer(
            ImageEvaluationArtifactMember(
                artifact_id=first.publication.artifact_id,
                artifact_revision_id=first.publication.artifact_revision_id,
                member_path=first.publication.primary_file,
                schema_ref=SOURCE_PAGE_CROP_SET_V2_SCHEMA_REF,
                media_type="application/json",
                sha256=first.publication.primary_sha256,
            ),
            first.crop_set.members[0],
        ).media_type
        == "image/png"
    )
    with pytest.raises(ValidationError):
        LocalImageScienceSourcePageCropSet.model_validate(first.crop_set.model_dump(mode="json"))
    with pytest.raises(ValidationError):
        LocalImageScienceSourcePageCropReview.model_validate(review.model_dump(mode="json"))


def test_legacy_and_closed_protocols_remain_distinct(monkeypatch):
    legacy, _basis, _reader = _fixture_review(monkeypatch)
    assert source_page_crop_protocol(legacy).set_model is LocalImageScienceSourcePageCropSet
    assert (
        LocalImageScienceSourcePageCropReview.model_validate_json(legacy.model_dump_json())
        == legacy
    )
    with pytest.raises(ValueError, match="unsupported"):
        source_page_crop_protocol(object())
    root = Path(__file__).resolve().parents[2]
    tree = ast.parse(
        (root / "packages/image_contracts/eom_image_contracts/source_page_crops.py").read_text()
    )
    imported = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
    assert not any(
        module.startswith(("eom_orchestrator", "eom_catalog_service", "sqlalchemy", "subprocess"))
        for module in imported
    )


def test_rehashed_legacy_output_cannot_claim_a_supplemental_review(expanded):
    review = _review(expanded)
    selection = review.selections[0]
    value = {
        "schema_version": "local-image-science-source-page-crop-set/1.0",
        "crop_set_id": "imgsourcecropset_"
        + content_sha256({"selection_ids": (selection.selection_id,)})[7:39],
        "created_at": "2026-10-04T09:00:00Z",
        "review": {
            "artifact_id": "artifact_" + "1" * 32,
            "artifact_revision_id": "rev_" + "2" * 32,
            "member_path": "manifests/science-source-page-crop-review.json",
            "schema_ref": "eom://schemas/image-provider/local-image-science-source-page-crop-review/1.0",
            "media_type": "application/json",
            "sha256": _sha(content_json_bytes(review.model_dump(mode="json"))),
        },
        "pillow_version": review.pillow_version,
        "members": [
            {
                "selection_id": selection.selection_id,
                "member_path": "crops/" + selection.selection_id + ".png",
                "sha256": "sha256:" + "f" * 64,
                "size_bytes": 1024,
                "width_px": 270,
                "height_px": 280,
                "perceptual_hash": "f" * 16,
            }
        ],
        "state": "REVIEWED_SOURCE_DERIVATIVES",
        "activation_policy": "FORBIDDEN",
    }
    value["crop_set_revision_id"] = "imgsourcecropsetrev_" + content_sha256(value)[7:39]
    value["crop_set_sha256"] = content_sha256(value)
    wrong = LocalImageScienceSourcePageCropSet.model_validate(value)
    with pytest.raises(ValueError, match="protocol mismatch"):
        validate_source_page_crop_set(review, wrong)
