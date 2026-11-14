"""Synthetic descriptor proofs only: no image decoding, NAS, DB or model calls."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_files import MaterialNativeFileBinding
from eom_catalog_contracts.material_native_visual_selection import (
    build_material_native_question_visual_scope,
    material_native_visual_guidance,
    validate_material_native_visual_bindings,
)
from eom_catalog_contracts.office_item_learning import OfficeVisualBinding, OfficeVisualBindings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_image_contracts.office_picture_uses import (
    OfficeObjectLocator,
    OfficePictureUseCatalog,
    office_object_id,
)
from pydantic import ValidationError

SOURCE = "sha256:" + "a" * 64
FRAGMENT = "sha256:" + "b" * 64
FIGURE = ("BinData/original.bmp", "figure", "figure-view")
NATIVE_FIGURE = ("BinData/image9.jpg", "figure", "figure-view")
LOGO = ("BinData/title.png", "logo", "logo-view")


def _pointer(path: str, *, schema: str, media: str, sha: str) -> MaterialArtifactMember:
    return MaterialArtifactMember(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        member_path=path,
        schema_ref=schema,
        media_type=media,
        sha256=sha,
        bytes=128,
    )


def _file() -> MaterialNativeFileBinding:
    return MaterialNativeFileBinding(
        source_role="MAIN",
        original_source_sha256=SOURCE,
        native_source_sha256="sha256:" + "c" * 64,
        document=_pointer(
            "native/009.hwpx",
            schema="eom://schemas/material-learning/native-item-document/1.0",
            media="application/vnd.hancom.hwpx",
            sha=FRAGMENT,
        ),
        split_evidence=_pointer(
            "native/009.json",
            schema="eom://schemas/hwpx/native-item-split/1.0",
            media="application/json",
            sha="sha256:" + "d" * 64,
        ),
        split_plan_sha256="sha256:" + "e" * 64,
        ranges=(
            {
                "section_member": "Contents/section0.xml",
                "start_paragraph": 10,
                "end_paragraph": 15,
                "subtree_sha256": "sha256:" + "f" * 64,
            },
        ),
    )


def _catalog(
    source_sha: str,
    specs: tuple[tuple[str, str, str], ...],
    *,
    native: bool = False,
    dimensions: tuple[int, int] = (20, 10),
    view_dimensions: tuple[int, int] = (20, 10),
    unsupported: tuple[str, ...] = (),
) -> OfficePictureUseCatalog:
    images = {}
    uses, views = [], []
    for ordinal, (member, pixels, view_seed) in enumerate(specs):
        whole_sha = sha256_bytes(("whole-png:" + pixels).encode())
        images[member] = dict(
            source_member=member,
            source_member_sha256=sha256_bytes(("container-bytes:" + member).encode()),
            source_format="JPEG" if native else "BMP",
            pixel_sha256=sha256_bytes(("whole-rgba:" + pixels).encode()),
            member_path="images/" + whole_sha[7:] + ".png",
            sha256=whole_sha,
            width_px=dimensions[0],
            height_px=dimensions[1],
            content_length=128,
        )
        locator = OfficeObjectLocator(
            member_path="Contents/section0.xml" if native else "BodyText/Section0",
            ordinal=ordinal,
        )
        use_id = office_object_id(source_sha, locator)
        uses.append(
            dict(
                use_id=use_id,
                locator=locator.model_dump(mode="json"),
                source_member=member,
                native_sha256=sha256_bytes(f"native-record:{source_sha}:{ordinal}".encode()),
                group_id=None,
                placement=None,
                geometry=dict(
                    original_extent=dimensions,
                    viewport=(0, 0, *view_dimensions),
                    clockwise_quarter_turns=0,
                    flip_horizontal=False,
                    flip_vertical=False,
                ),
                unresolved_reasons=[],
            )
        )
        view_sha = sha256_bytes(("rendered-view:" + view_seed).encode())
        views.append(
            dict(
                use_id=use_id,
                member_path="uses/" + view_sha[7:] + ".png",
                sha256=view_sha,
                width_px=view_dimensions[0],
                height_px=view_dimensions[1],
                content_length=128,
            )
        )
    embedded = dict(
        schema_version="office-embedded-image-set/1.0",
        source_sha256=source_sha,
        source_format="HWPX" if native else "HWP5",
        extractor_profile="WHOLE_EMBEDDED_RASTER_V1",
        images=[images[key] for key in sorted(images)],
        unsupported_members=sorted(unsupported),
    )
    value = dict(
        schema_version="office-picture-use-catalog/1.0",
        extractor_profile="HANCOM_NATIVE_PICTURE_USES_V1",
        embedded_images={**embedded, "manifest_sha256": content_sha256(embedded)},
        picture_uses=uses,
        rendered_uses=views,
        native_objects=[],
    )
    return OfficePictureUseCatalog.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )


def _sha(catalog: OfficePictureUseCatalog) -> str:
    return sha256_bytes(canonical_json_bytes(catalog.model_dump(mode="json")))


def _scope(
    source: OfficePictureUseCatalog | None = None,
    question: OfficePictureUseCatalog | None = None,
):
    source = source if source is not None else _catalog(SOURCE, (FIGURE, LOGO))
    question = (
        question if question is not None else _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True)
    )
    return build_material_native_question_visual_scope(
        _file(),
        item_number=9,
        source_catalog=source,
        source_catalog_sha256=_sha(source),
        question_catalog=question,
    )


def _selection(scope, ids: tuple[str, ...]) -> OfficeVisualBindings:
    return OfficeVisualBindings(
        office_catalog_sha256=scope.source_catalog_sha256,
        bindings=tuple(
            OfficeVisualBinding(
                block_id=f"block_figure_{index}",
                picture_use_id=identifier,
                source_region_id="extregion_" + "1" * 32,
                selection_reason="실제 본문 사용 개체 대조",
            )
            for index, identifier in enumerate(ids)
        ),
    )


def test_cross_container_whole_pixels_and_exact_view_select_question_not_logo():
    source = _catalog(SOURCE, (FIGURE, LOGO))
    question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True)
    before = canonical_json_bytes(source.model_dump(mode="json"))
    scope = _scope(source, question)
    assert scope.allowed_picture_use_ids == (source.picture_uses[0].use_id,)
    assert scope.allowed_picture_use_ids != (question.picture_uses[0].use_id,)
    assert scope.question_document == _file().document
    assert scope.split_evidence == _file().split_evidence
    assert scope.source_catalog_sha256 == _sha(source)
    assert source.embedded_images.images[0].source_member_sha256 != (
        question.embedded_images.images[0].source_member_sha256
    )
    assert canonical_json_bytes(source.model_dump(mode="json")) == before
    assert canonical_json_bytes(scope.model_dump(mode="json")) == canonical_json_bytes(
        _scope(source, question).model_dump(mode="json")
    )
    with pytest.raises(ValidationError, match="frozen_instance"):
        scope.item_number = 10


@pytest.mark.parametrize("field", ["source", "canonical-sha", "fragment", "fragment-format"])
def test_exact_source_catalog_and_fragment_pins_are_required(field):
    source = _catalog(SOURCE, (FIGURE,))
    question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True)
    expected_sha = _sha(source)
    code = "MATERIAL_NATIVE_VISUAL_SOURCE_CATALOG_MISMATCH"
    if field == "source":
        source = _catalog("sha256:" + "0" * 64, (FIGURE,))
        expected_sha = _sha(source)
    elif field == "canonical-sha":
        expected_sha = source.manifest_sha256  # Inner manifest is not the Artifact byte SHA.
    elif field == "fragment":
        question = _catalog("sha256:" + "0" * 64, (NATIVE_FIGURE,), native=True)
        code = "MATERIAL_NATIVE_VISUAL_QUESTION_CATALOG_MISMATCH"
    else:
        question = _catalog(FRAGMENT, (NATIVE_FIGURE,))
        code = "MATERIAL_NATIVE_VISUAL_QUESTION_CATALOG_MISMATCH"
    with pytest.raises(ValueError, match=code):
        build_material_native_question_visual_scope(
            _file(),
            item_number=9,
            source_catalog=source,
            source_catalog_sha256=expected_sha,
            question_catalog=question,
        )


def test_solution_file_is_not_a_question_scope():
    source = _catalog(SOURCE, (FIGURE,))
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_QUESTION_FILE_REQUIRED"):
        build_material_native_question_visual_scope(
            _file().model_copy(update={"source_role": "SOLUTIONS"}),
            item_number=9,
            source_catalog=source,
            source_catalog_sha256=_sha(source),
            question_catalog=_catalog(FRAGMENT, (NATIVE_FIGURE,), native=True),
        )


@pytest.mark.parametrize("target", ["source", "question"])
def test_duplicate_view_descriptors_are_rejected_even_after_typed_copy(target):
    source = _catalog(SOURCE, (FIGURE,))
    question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True)
    if target == "source":
        source = source.model_copy(update={"rendered_uses": source.rendered_uses * 2})
    else:
        question = question.model_copy(update={"rendered_uses": question.rendered_uses * 2})
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_CATALOG_INVALID"):
        _scope(source, question)


def test_catalog_inner_manifest_is_revalidated_not_just_outer_byte_hash():
    source = _catalog(SOURCE, (FIGURE,)).model_copy(
        update={"manifest_sha256": "sha256:" + "0" * 64}
    )
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_CATALOG_INVALID"):
        _scope(source)


@pytest.mark.parametrize("field", ["view", "geometry", "reason", "image"])
def test_any_unresolved_actual_body_picture_fails_without_an_allow_all_fallback(field):
    question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True)
    if field == "view":
        question = question.model_copy(update={"rendered_uses": ()})
    elif field in {"geometry", "reason"}:
        use = question.picture_uses[0].model_copy(
            update={"geometry": None}
            if field == "geometry"
            else {"unresolved_reasons": ("UNSUPPORTED_IMAGE",)}
        )
        question = question.model_copy(update={"picture_uses": (use,)})
    else:
        embedded = question.embedded_images.model_copy(update={"images": ()})
        question = question.model_copy(update={"embedded_images": embedded})
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_QUESTION_USE_UNRESOLVED"):
        _scope(question=question)


@pytest.mark.parametrize("field", ["whole-pixels", "whole-size", "view-sha", "view-size"])
def test_whole_rgba_and_exact_rendered_view_both_must_match(field):
    source = _catalog(SOURCE, (FIGURE,), dimensions=(21, 11))
    question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True, dimensions=(21, 11))
    if field == "whole-pixels":
        question = _catalog(
            FRAGMENT,
            (("BinData/image9.jpg", "other-pixels", "figure-view"),),
            native=True,
            dimensions=(21, 11),
        )
    elif field == "whole-size":
        question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True, dimensions=(22, 11))
    elif field == "view-sha":
        question = _catalog(
            FRAGMENT,
            (("BinData/image9.jpg", "figure", "flipped-view"),),
            native=True,
            dimensions=(21, 11),
        )
    else:
        question = _catalog(
            FRAGMENT,
            (NATIVE_FIGURE,),
            native=True,
            dimensions=(21, 11),
            view_dimensions=(19, 10),
        )
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SOURCE_USE_NOT_FOUND"):
        _scope(source, question)


@pytest.mark.parametrize("same_member", [True, False])
def test_identical_source_uses_are_ambiguous_not_all_allowed(same_member):
    second = FIGURE if same_member else ("BinData/duplicate.png", "figure", "figure-view")
    source = _catalog(SOURCE, (FIGURE, second))
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SOURCE_USE_AMBIGUOUS"):
        _scope(source)


def test_same_whole_member_with_distinct_rendered_view_can_match_one_use():
    source = _catalog(SOURCE, (FIGURE, (FIGURE[0], "figure", "other-viewport")))
    assert _scope(source).allowed_picture_use_ids == (source.picture_uses[0].use_id,)


def test_unresolved_source_use_is_never_a_matching_candidate():
    source = _catalog(SOURCE, (FIGURE,))
    value = source.model_dump(mode="json", exclude={"manifest_sha256"})
    value["picture_uses"][0].update(geometry=None, unresolved_reasons=["GEOMETRY_UNRESOLVED"])
    value["rendered_uses"] = []
    source = OfficePictureUseCatalog.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SOURCE_USE_NOT_FOUND"):
        _scope(source)


def test_empty_body_does_not_allow_retained_embedded_raster_or_unreferenced_emf():
    question = _catalog(FRAGMENT, (), native=True, unsupported=("BinData/retained.emf",))
    value = question.model_dump(mode="json", exclude={"manifest_sha256"})
    embedded = value["embedded_images"]
    embedded["images"] = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True).model_dump(mode="json")[
        "embedded_images"
    ]["images"]
    embedded["manifest_sha256"] = content_sha256(
        {key: entry for key, entry in embedded.items() if key != "manifest_sha256"}
    )
    question = OfficePictureUseCatalog.model_validate(
        {**value, "manifest_sha256": content_sha256(value)}
    )
    scope = _scope(question=question)
    assert scope.allowed_picture_use_ids == ()
    validate_material_native_visual_bindings(_selection(scope, ()), scope=scope)
    assert "(없음)" in material_native_visual_guidance(scope)


def test_scope_and_guidance_order_are_canonical_not_fragment_or_member_order():
    source = _catalog(SOURCE, (FIGURE, LOGO))
    native_logo = ("BinData/image1.png", "logo", "logo-view")
    first = _scope(source, _catalog(FRAGMENT, (NATIVE_FIGURE, native_logo), native=True))
    second = _scope(source, _catalog(FRAGMENT, (native_logo, NATIVE_FIGURE), native=True))
    assert first == second
    assert first.allowed_picture_use_ids == tuple(sorted(use.use_id for use in source.picture_uses))
    assert material_native_visual_guidance(first) == material_native_visual_guidance(second)


@pytest.mark.parametrize("count", [64, 65])
def test_scope_has_existing_64_use_bound_without_truncation(count):
    source_specs = tuple(
        (f"BinData/source{number}.bmp", f"pixels{number}", f"view{number}")
        for number in range(count)
    )
    question_specs = tuple(
        (f"BinData/image{number}.png", pixels, view)
        for number, (_, pixels, view) in enumerate(source_specs)
    )
    source = _catalog(SOURCE, source_specs)
    question = _catalog(FRAGMENT, question_specs, native=True)
    if count == 64:
        scope = _scope(source, question)
        assert len(scope.allowed_picture_use_ids) == count
        assert len(material_native_visual_guidance(scope).encode("utf-8")) <= 8000
    else:
        with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_QUESTION_USE_LIMIT"):
            _scope(source, question)


def test_guard_rejects_global_logo_and_wrong_catalog_but_allows_a_proper_subset():
    source = _catalog(SOURCE, (FIGURE, LOGO))
    scope = _scope(source)
    validate_material_native_visual_bindings(
        _selection(scope, scope.allowed_picture_use_ids), scope=scope
    )
    validate_material_native_visual_bindings(_selection(scope, ()), scope=scope)
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SELECTION_OUT_OF_SCOPE"):
        validate_material_native_visual_bindings(
            _selection(scope, (source.picture_uses[1].use_id,)), scope=scope
        )
    wrong = _selection(scope, ()).model_copy(update={"office_catalog_sha256": "sha256:" + "0" * 64})
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SELECTION_CATALOG_MISMATCH"):
        validate_material_native_visual_bindings(wrong, scope=scope)


def test_locality_guard_does_not_replace_existing_full_block_closure():
    from eom_catalog_contracts.office_item_learning import validate_office_visual_bindings

    from tests.unit.test_office_item_learning import office_case

    work, result, catalog, selection = office_case()
    # Both global uses are identical, so a trusted scope must still select only one.
    scope = _scope().model_copy(
        update={
            "source_catalog_sha256": work.office_artifact.sha256,
            "allowed_picture_use_ids": (catalog.picture_uses[0].use_id,),
        }
    )
    empty = selection.model_copy(update={"bindings": ()})
    validate_material_native_visual_bindings(empty, scope=scope)
    with pytest.raises(ValueError, match="OFFICE_VISUAL_BINDING_BLOCK_SET_MISMATCH"):
        validate_office_visual_bindings(empty, result=result, work=work, catalog=catalog)


def test_guidance_is_bounded_including_64_allowed_uses_and_contains_only_pinned_hints():
    scope = _scope().model_copy(
        update={
            "allowed_picture_use_ids": tuple(f"officeobj_{number:032x}" for number in range(64))
        }
    )
    guidance = material_native_visual_guidance(scope)
    assert len(guidance.encode("utf-8")) <= 8000
    assert scope.source_catalog_sha256 in guidance
    assert scope.question_document.sha256 in guidance
    assert scope.split_evidence.sha256 in guidance
    assert all(identifier in guidance for identifier in scope.allowed_picture_use_ids)
    assert "모두 포함하라는 뜻은 아닙니다" in guidance
    assert "권한이나 검증 완료를 뜻하지 않습니다" in guidance
    assert guidance == material_native_visual_guidance(scope)


def test_contract_helper_has_no_infrastructure_import_or_io_calls():
    path = (
        Path(__file__).resolve().parents[2]
        / "packages/catalog_contracts/eom_catalog_contracts/material_native_visual_selection.py"
    )
    tree = ast.parse(path.read_text())
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    } | {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not any(
        name.startswith(("eom_catalog_service", "eom_orchestrator", "sqlalchemy", "pathlib"))
        or name in {"os", "subprocess", "socket"}
        for name in imports
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"open", "exec", "eval", "compile", "__import__"}
        for node in ast.walk(tree)
    )
