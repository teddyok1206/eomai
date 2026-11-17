"""Actual source PNGs and crops, not permission grants or live-slot/PDF acceptance."""

import io
from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import eom_catalog_service.kakao_concept_pages as pages_module
import pytest
from eom_catalog_contracts import EducationalDocumentKnowledgeSourceV4
from eom_catalog_contracts.knowledge import KnowledgePageImageObservation
from eom_catalog_contracts.material_knowledge_analysis import EducationalDocumentKnowledgeSourceV5
from eom_catalog_service.kakao_archive_authorization import KakaoArchiveError
from eom_catalog_service.kakao_concept_knowledge import (
    ConceptTextbookMaterial,
    KakaoConceptKnowledgeReader,
    ResolvedConceptTextbookKnowledge,
)
from eom_catalog_service.kakao_concept_pages import (
    CROP_PROFILE,
    ConceptPageSource,
    prepare_kakao_concept_captures,
    prepare_kakao_concept_pages,
)
from eom_kakao_archive_contracts import sha256
from eom_kakao_archive_contracts.concepts import parse_concept_request, validate_concept_result
from PIL import Image

from tests.unit.general_chat_rag_fixtures import scope
from tests.unit.test_chat_rag_resolution import materialized
from tests.unit.test_kakao_concept_contracts import composed, plan, plan_request, result
from tests.unit.test_kakao_concept_knowledge import actor, resolved, snapshot
from tests.unit.test_knowledge_analysis_document_contracts import multimodal_document_source
from tests.unit.test_material_knowledge_contracts import source as uploaded_source


def png(width=11, height=13, *, animated=False, orientation=None):
    image = Image.new("RGB", (width, height), "white")
    for x in range(width):
        for y in range(height):
            image.putpixel((x, y), (x * 10 % 256, y * 10 % 256, 10))
    buffer = io.BytesIO()
    kwargs = {}
    if animated:
        kwargs = dict(save_all=True, append_images=[Image.new("RGB", image.size, "red")])
    if orientation is not None:
        exif = image.getexif()
        exif[274] = orientation
        kwargs["exif"] = exif
    image.save(buffer, format="PNG", **kwargs)
    return buffer.getvalue()


def knowledge(*, family="V5", count=1, raw=None, observed=True):
    raw = png() if raw is None else raw
    if family == "V3":
        base = resolved(materialized())
    else:
        value = uploaded_source() if family == "V5" else multimodal_document_source()
        members = value["materialization_members"]
        for member in members:
            if member["member_kind"] == "PAGE_IMAGE":
                member.update(sha256=sha256(raw), bytes=len(raw), width_pixels=11, height_pixels=13)
        value["materialization_bytes"] = sum(m["bytes"] for m in members)
        source_type = (
            EducationalDocumentKnowledgeSourceV5
            if family == "V5"
            else EducationalDocumentKnowledgeSourceV4
        )
        source = source_type.model_validate(value)
        base = replace(resolved(materialized()), source=source)
        if observed:
            base = replace(
                base,
                page_observations=(
                    KnowledgePageImageObservation(
                        physical_page=1,
                        image_sha256=sha256(raw),
                        observation_state="OBSERVED",
                        anchor_ids=(base.selected_anchors[0].anchor_id,),
                    ),
                ),
            )
    return ResolvedConceptTextbookKnowledge(
        scope(),
        snapshot(),
        tuple(
            ConceptTextbookMaterial(
                "검증 교과서",
                ("knode_concept",),
                replace(base, analysis_run_id=f"analysisrun_{i:032x}"),
            )
            for i in range(1, count + 1)
        ),
    ), raw


def setup(tmp_path, **kwargs):
    value, raw = knowledge(**kwargs)
    staging = tmp_path / "private"
    staging.mkdir(mode=0o700)
    root = staging / "pages"
    root.mkdir(mode=0o700)
    outputs = staging / "result"
    outputs.mkdir(mode=0o700)
    artifacts = Mock()
    artifacts.settings = SimpleNamespace(staging_root=staging, nas_artifact_root=tmp_path / "nas")
    artifacts.read_member.return_value = raw
    authorize = Mock()
    return artifacts, value, root, outputs, authorize


def prepared(tmp_path, **kwargs):
    artifacts, value, root, outputs, authorize = setup(tmp_path, **kwargs)
    staged = prepare_kakao_concept_pages(
        artifacts, knowledge=value, source_root=root, authorize=authorize
    )
    return artifacts, staged, outputs, authorize


def compose(staged, *, captures=1, blocks=1):
    request = parse_concept_request(
        plan_request().model_dump(mode="json")
        | dict(phase="COMPOSE", plan=plan(), context=staged.context.model_dump(mode="json"))
    )
    payload = composed()
    payload["blocks"][0]["citations"] = [dict(evidence_key="E1", passage_key=None, quote=None)]
    payload["blocks"][0]["captures"][0]["page_key"] = staged.context.pages[0].page_key
    payload["blocks"][0]["captures"] *= captures
    payload["blocks"] *= blocks
    return request, validate_concept_result(request, result(request, payload))


@pytest.mark.parametrize("family", ["V4", "V5"])
def test_actual_png_source_identity_and_current_authority_are_preserved(tmp_path, family):
    artifacts, staged, _, authorize = prepared(tmp_path, family=family)
    assert authorize.call_count == 2
    assert len(staged.context.pages) == 1
    source = staged.sources[0]
    page = source.page
    original = source.original
    assert page.page_key == "E1P1"
    assert page.member.sha256 == original.sha256
    assert (staged.source_root / page.member.relative_path).read_bytes() == png()
    assert "인쇄 쪽수 미확인" in staged.context.evidence[0].location
    assert not staged.context.evidence[0].original_passages
    assert not any("아직 열람" in text for text in staged.context.limitations)
    assert artifacts.read_member.call_args.kwargs == dict(
        artifact_id=original.artifact_id,
        revision_id=original.artifact_revision_id,
        member_path=original.member_path,
        sha256=original.sha256,
        media_type="image/png",
        schema_ref=original.schema_ref,
        max_bytes=16 * 1024 * 1024,
    )
    artifacts.commit_file_set.assert_not_called()
    assert stat_mode(staged.source_root / page.member.relative_path) == 0o640


def stat_mode(path):
    return path.stat().st_mode & 0o777


def test_same_canonical_member_across_evidence_is_read_and_written_once(tmp_path):
    artifacts, staged, _, _ = prepared(tmp_path, count=3)
    assert len(staged.context.pages) == 3
    assert len({page.member for page in staged.context.pages}) == 1
    assert len(list(staged.source_root.rglob("*.png"))) == 1
    assert artifacts.read_member.call_count == 1
    assert [page.page_key for page in staged.context.pages] == ["E1P1", "E2P1", "E3P1"]


def test_text_only_source_does_not_invent_pixels_or_original_quotations(tmp_path):
    artifacts, staged, _, _ = prepared(tmp_path, family="V3")
    assert not staged.context.pages and not staged.sources
    assert not staged.context.evidence[0].original_passages
    assert any("PNG가 없는" in text for text in staged.context.limitations)
    artifacts.read_member.assert_not_called()


def test_small_verified_source_range_can_supply_pages_without_parsing_locator(tmp_path):
    artifacts, staged, _, _ = prepared(tmp_path, observed=False)
    assert [page.physical_page for page in staged.context.pages] == [1, 2]
    assert artifacts.read_member.call_count == 2


@pytest.mark.parametrize("field", ["image_sha256", "physical_page"])
def test_mismatched_accepted_page_observation_fails_before_read(tmp_path, field):
    artifacts, value, root, _, authorize = setup(tmp_path)
    analysis = value.materials[0].analysis
    observation = analysis.page_observations[0].model_copy(
        update={field: sha256(b"wrong") if field == "image_sha256" else 3}
    )
    altered = replace(
        value,
        materials=(
            replace(
                value.materials[0], analysis=replace(analysis, page_observations=(observation,))
            ),
        ),
    )
    with pytest.raises(KakaoArchiveError, match="PAGE_OBSERVATION_MISMATCH"):
        prepare_kakao_concept_pages(
            artifacts, knowledge=altered, source_root=root, authorize=authorize
        )
    artifacts.read_member.assert_not_called()


@pytest.mark.parametrize(
    "change", ["hash", "bytes", "dimensions", "animated", "orientation", "corrupt"]
)
def test_original_page_is_checked_by_pointer_and_actual_decoder(tmp_path, change):
    raw = png(animated=change == "animated", orientation=6 if change == "orientation" else None)
    if change == "corrupt":
        raw = b"not-png" * 5
    artifacts, value, root, _, authorize = setup(tmp_path, raw=raw)
    if change == "hash":
        artifacts.read_member.return_value = png(11, 14)
    elif change == "bytes":
        artifacts.read_member.return_value = raw[:-1]
    elif change == "dimensions":
        # A content-correct but falsely dimensioned pointer must also be rejected.
        source = value.materials[0].analysis.source
        altered = source.model_dump(mode="json")
        for member in altered["materialization_members"]:
            if member["member_kind"] == "PAGE_IMAGE":
                member["height_pixels"] = 12
        source = type(source).model_validate(altered)
        value = replace(
            value,
            materials=(
                replace(
                    value.materials[0], analysis=replace(value.materials[0].analysis, source=source)
                ),
            ),
        )
    with pytest.raises(ValueError, match="KAKAO_CONCEPT_PAGE_"):
        prepare_kakao_concept_pages(
            artifacts, knowledge=value, source_root=root, authorize=authorize
        )


@pytest.mark.parametrize("when", [0, 1])
def test_permission_revocation_never_returns_a_usable_context(tmp_path, when):
    artifacts, value, root, _, authorize = setup(tmp_path)
    authorize.side_effect = (
        [KakaoArchiveError("SOURCE_REVOKED")]
        if when == 0
        else [None, KakaoArchiveError("SOURCE_REVOKED")]
    )
    with pytest.raises(KakaoArchiveError, match="SOURCE_REVOKED"):
        prepare_kakao_concept_pages(
            artifacts, knowledge=value, source_root=root, authorize=authorize
        )
    if when == 0:
        artifacts.read_member.assert_not_called()
    artifacts.commit_file_set.assert_not_called()


@pytest.mark.parametrize("kind", ["nas", "outside", "unsafe", "symlink", "not-empty"])
def test_no_nas_unsafe_root_symlink_or_existing_files_are_used(tmp_path, kind):
    artifacts, value, root, _, authorize = setup(tmp_path)
    if kind == "nas":
        artifacts.settings.nas_artifact_root = artifacts.settings.staging_root
    elif kind == "outside":
        root = tmp_path
    elif kind == "unsafe":
        root.chmod(0o755)
    elif kind == "symlink":
        root.rmdir()
        root.symlink_to(tmp_path, target_is_directory=True)
    else:
        (root / "existing").touch()
    with pytest.raises((ValueError, OSError)):
        prepare_kakao_concept_pages(
            artifacts, knowledge=value, source_root=root, authorize=authorize
        )
    artifacts.read_member.assert_not_called()


def test_crop_preserves_original_pixels_and_outward_rounds_without_resizing(tmp_path):
    artifacts, staged, output, authorize = prepared(tmp_path)
    request, result_value = compose(staged)
    authorize.reset_mock()
    captures = prepare_kakao_concept_captures(
        artifacts,
        prepared=staged,
        request=request,
        result=result_value,
        output_root=output,
        authorize=authorize,
    )
    assert authorize.call_count == 2
    assert len(captures) == 1
    capture = captures[0]
    assert capture.original == staged.sources[0].original
    assert capture.profile == CROP_PROFILE
    assert capture.pixel_bounds == (1, 2, 8, 8)
    cropped = (output / capture.member.relative_path).read_bytes()
    assert sha256(cropped) == capture.member.sha256
    with Image.open(io.BytesIO(cropped)) as actual, Image.open(io.BytesIO(png())) as original:
        expected = original.crop(capture.pixel_bounds)
        assert actual.size == (7, 6)
        assert actual.tobytes() == expected.tobytes()
    assert (staged.source_root / staged.context.pages[0].member.relative_path).read_bytes() == png()
    artifacts.commit_file_set.assert_not_called()


def test_identical_captures_reuse_one_derivative_but_preserve_each_block_use(tmp_path):
    artifacts, staged, output, authorize = prepared(tmp_path)
    request, result_value = compose(staged, captures=2, blocks=2)
    captures = prepare_kakao_concept_captures(
        artifacts,
        prepared=staged,
        request=request,
        result=result_value,
        output_root=output,
        authorize=authorize,
    )
    assert [(c.block_index, c.capture_index) for c in captures] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert len({c.member for c in captures}) == 1
    assert len(list(output.rglob("*.png"))) == 1


def test_changed_context_or_result_cannot_be_applied_to_a_different_page(tmp_path):
    artifacts, staged, output, authorize = prepared(tmp_path)
    request, result_value = compose(staged)
    wrong = request.context.model_copy(update={"limitations": ("different",)})
    with pytest.raises(KakaoArchiveError, match="CAPTURE_CONTEXT_MISMATCH"):
        prepare_kakao_concept_captures(
            artifacts,
            prepared=staged,
            request=request.model_copy(update={"context": wrong}),
            result=result_value,
            output_root=output,
            authorize=authorize,
        )
    with pytest.raises(ValueError, match="RESULT_INPUT_MISMATCH"):
        prepare_kakao_concept_captures(
            artifacts,
            prepared=staged,
            request=request,
            result=result_value.model_copy(update={"request_sha256": sha256(b"wrong")}),
            output_root=output,
            authorize=authorize,
        )
    assert not list(output.iterdir())


@pytest.mark.parametrize("mode", ["replace", "symlink"])
def test_changed_staged_page_never_produces_a_crop(tmp_path, mode):
    artifacts, staged, output, authorize = prepared(tmp_path)
    request, result_value = compose(staged)
    page = staged.source_root / staged.context.pages[0].member.relative_path
    if mode == "replace":
        page.write_bytes(png(11, 14))
    else:
        page.unlink()
        page.symlink_to(tmp_path / "missing")
    with pytest.raises((ValueError, OSError)):
        prepare_kakao_concept_captures(
            artifacts,
            prepared=staged,
            request=request,
            result=result_value,
            output_root=output,
            authorize=authorize,
        )
    assert not list(output.iterdir())


def test_current_authority_is_used_by_the_public_reader_for_both_operations(tmp_path):
    artifacts, value, root, output, _ = setup(tmp_path)
    owner = object.__new__(KakaoConceptKnowledgeReader)
    owner.analyses = SimpleNamespace(artifacts=artifacts)
    owner.reauthorize = Mock()
    question = Mock()
    current = actor()
    staged = owner.prepare_pages(
        current, "binding", value, source_root=root, reauthorize_question=question
    )
    request, result_value = compose(staged)
    owner.prepare_captures(
        current,
        "binding",
        staged,
        request=request,
        result=result_value,
        output_root=output,
        reauthorize_question=question,
    )
    assert owner.reauthorize.call_count == 4
    for call in owner.reauthorize.call_args_list:
        assert call.args == (current, "binding", value)
        assert call.kwargs == dict(reauthorize_question=question)


def test_source_and_local_hash_mismatch_is_not_a_capture_source(tmp_path):
    _, staged, _, _ = prepared(tmp_path)
    source = staged.sources[0]
    with pytest.raises(KakaoArchiveError, match="PAGE_POINTER_INVALID"):
        ConceptPageSource(
            source.page, source.original.model_copy(update={"sha256": sha256(b"other")})
        )


def larger_source(value, *, observed):
    analysis = value.materials[0].analysis
    original = analysis.source.model_dump(mode="json")
    index = [m for m in original["materialization_members"] if m["member_kind"] == "INDEX"]
    templates = {
        m["member_kind"]: m for m in original["materialization_members"] if m["physical_page"] == 1
    }
    entries = index[:]
    for kind, suffix, directory in (("PAGE_TEXT", "md", "pages"), ("PAGE_IMAGE", "png", "images")):
        for page in range(1, 7):
            entry = deepcopy(templates[kind])
            entry.update(
                physical_page=page,
                member_path=f"analysis/{directory}/page-{page:06d}.{suffix}",
                materialized_path=f"source/document/{directory}/page-{page:06d}.{suffix}",
                logical_name=f"page-{page:06d}.{suffix}",
            )
            entries.append(entry)
    original.update(
        last_physical_page=6,
        page_image_count=6,
        materialization_members=entries,
        materialization_bytes=sum(m["bytes"] for m in entries),
    )
    source = EducationalDocumentKnowledgeSourceV4.model_validate(original)
    observations = (
        tuple(
            KnowledgePageImageObservation(
                physical_page=page,
                image_sha256=sha256(png()),
                observation_state="OBSERVED",
                anchor_ids=(analysis.selected_anchors[0].anchor_id,),
            )
            for page in range(1, 7)
        )
        if observed
        else ()
    )
    return replace(
        value,
        materials=(
            replace(
                value.materials[0],
                analysis=replace(analysis, source=source, page_observations=observations),
            ),
        ),
    )


@pytest.mark.parametrize("observed", [True, False])
def test_large_source_never_guesses_pages_from_prose_and_marks_partial_coverage(tmp_path, observed):
    artifacts, value, root, _, authorize = setup(tmp_path, family="V4")
    value = larger_source(value, observed=observed)
    staged = prepare_kakao_concept_pages(
        artifacts, knowledge=value, source_root=root, authorize=authorize
    )
    assert [page.physical_page for page in staged.context.pages] == (
        [1, 2, 3, 4] if observed else []
    )
    assert any("미제공" in text for text in staged.context.limitations)
    assert artifacts.read_member.call_count == (4 if observed else 0)


def test_same_pointer_with_conflicting_dimensions_is_rejected_for_every_alias(tmp_path):
    artifacts, value, root, _, authorize = setup(tmp_path, count=2)
    first, second = value.materials
    source = second.analysis.source.model_dump(mode="json")
    for member in source["materialization_members"]:
        if member["member_kind"] == "PAGE_IMAGE":
            member["width_pixels"] = 12
    second = replace(
        second,
        analysis=replace(
            second.analysis, source=EducationalDocumentKnowledgeSourceV5.model_validate(source)
        ),
    )
    value = replace(value, materials=(first, second))
    with pytest.raises(KakaoArchiveError, match="PAGE_DIMENSIONS_INVALID"):
        prepare_kakao_concept_pages(
            artifacts, knowledge=value, source_root=root, authorize=authorize
        )
    assert artifacts.read_member.call_count == 1


def test_total_page_budget_is_checked_before_next_member_is_read(tmp_path, monkeypatch):
    artifacts, value, root, _, authorize = setup(tmp_path, observed=False)
    monkeypatch.setattr(pages_module, "MAX_PAGE_TOTAL_BYTES", len(png()))
    with pytest.raises(KakaoArchiveError, match="PAGES_TOO_LARGE"):
        prepare_kakao_concept_pages(
            artifacts, knowledge=value, source_root=root, authorize=authorize
        )
    assert artifacts.read_member.call_count == 1


def test_empty_knowledge_reports_no_match_without_pixel_or_source_invention(tmp_path):
    artifacts, value, root, _, authorize = setup(tmp_path)
    staged = prepare_kakao_concept_pages(
        artifacts, knowledge=replace(value, materials=()), source_root=root, authorize=authorize
    )
    assert not staged.context.evidence and not staged.context.pages
    assert any("찾지 못했습니다" in text for text in staged.context.limitations)
    artifacts.read_member.assert_not_called()


@pytest.mark.parametrize("when", [0, 1])
def test_crop_permission_revocation_never_returns_a_usable_derivative(tmp_path, when):
    artifacts, staged, output, authorize = prepared(tmp_path)
    request, result_value = compose(staged)
    authorize.side_effect = (
        [KakaoArchiveError("SOURCE_REVOKED")]
        if when == 0
        else [None, KakaoArchiveError("SOURCE_REVOKED")]
    )
    with pytest.raises(KakaoArchiveError, match="SOURCE_REVOKED"):
        prepare_kakao_concept_captures(
            artifacts,
            prepared=staged,
            request=request,
            result=result_value,
            output_root=output,
            authorize=authorize,
        )
    if when == 0:
        assert not list(output.iterdir())
    artifacts.commit_file_set.assert_not_called()
