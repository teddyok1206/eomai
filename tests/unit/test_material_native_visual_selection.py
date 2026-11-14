"""Synthetic descriptor proofs only: no image decoding, NAS, DB or model calls."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import MappingProxyType

import pytest
from eom_catalog_contracts import material_native_visual_selection as selection_owner
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_files import MaterialNativeFileBinding
from eom_catalog_contracts.material_native_visual_selection import (
    NativeSourceVisualIndex,
    build_material_native_question_visual_scope,
    build_material_native_question_visual_scope_from_index,
    build_native_source_visual_index,
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


def test_source_index_is_frozen_and_owns_only_immutable_derived_candidates():
    source = _catalog(SOURCE, (FIGURE, LOGO), native=True)
    index = build_native_source_visual_index(source, source_catalog_sha256=_sha(source))
    assert index.source_sha256 == SOURCE
    assert index.source_catalog_sha256 == _sha(source)
    assert isinstance(index.candidates, MappingProxyType)
    assert isinstance(index.native_candidates, MappingProxyType)
    assert all(isinstance(ids, tuple) for ids in index.candidates.values())
    assert all(isinstance(ids, tuple) for ids in index.native_candidates.values())
    with pytest.raises(FrozenInstanceError):
        index.source_sha256 = "sha256:" + "0" * 64
    with pytest.raises(TypeError):
        index.candidates[next(iter(index.candidates))] = ()
    with pytest.raises(TypeError):
        index.native_candidates[next(iter(index.native_candidates))] = ()
    with pytest.raises(TypeError):
        NativeSourceVisualIndex(source, source_sha256="sha256:" + "0" * 64)


@pytest.mark.parametrize("field", ["source-pin", "catalog-pin", "catalog-lineage"])
def test_index_cannot_be_reused_for_a_different_source_pin_or_catalog_object(field):
    source = _catalog(SOURCE, (FIGURE, LOGO))
    index = build_native_source_visual_index(source, source_catalog_sha256=_sha(source))
    file, catalog_sha = _file(), _sha(source)
    if field == "source-pin":
        file = file.model_copy(update={"original_source_sha256": "sha256:" + "0" * 64})
    elif field == "catalog-pin":
        catalog_sha = "sha256:" + "0" * 64
    else:
        # Equal bytes are not this per-call index's exact parsed-catalog lineage.
        source = OfficePictureUseCatalog.model_validate(source.model_dump(mode="json"))
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SOURCE_CATALOG_MISMATCH"):
        build_material_native_question_visual_scope_from_index(
            file,
            item_number=9,
            source_catalog=source,
            source_catalog_sha256=catalog_sha,
            source_index=index,
            question_catalog=_catalog(FRAGMENT, (NATIVE_FIGURE,), native=True),
        )


@pytest.mark.parametrize("count", [1, 25])
def test_per_book_source_hash_validation_and_index_cost_is_once_with_bitwise_equal_scopes(
    monkeypatch, count
):
    source = _catalog(SOURCE, (FIGURE, LOGO))
    question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True)
    catalog_sha = _sha(source)
    counts = dict(source=0, question=0, hash=0, source_lookup=0)
    require_catalog = selection_owner._require_catalog
    encode = selection_owner.canonical_json_bytes
    identity = selection_owner._view_identity

    def require(catalog, *, question):
        counts["question" if question else "source"] += 1
        return require_catalog(catalog, question=question)

    def canonical(value):
        counts["hash"] += 1
        return encode(value)

    def view_identity(image, view):
        if image.source_member in {FIGURE[0], LOGO[0]}:
            counts["source_lookup"] += 1
        return identity(image, view)

    monkeypatch.setattr(selection_owner, "_require_catalog", require)
    monkeypatch.setattr(selection_owner, "canonical_json_bytes", canonical)
    monkeypatch.setattr(selection_owner, "_view_identity", view_identity)
    ordinary = tuple(
        build_material_native_question_visual_scope(
            _file(),
            item_number=number,
            source_catalog=source,
            source_catalog_sha256=catalog_sha,
            question_catalog=question,
        )
        for number in range(1, count + 1)
    )
    assert counts == dict(source=count, question=count, hash=count, source_lookup=2 * count)
    counts.update(source=0, question=0, hash=0, source_lookup=0)
    index = build_native_source_visual_index(source, source_catalog_sha256=catalog_sha)
    indexed = tuple(
        build_material_native_question_visual_scope_from_index(
            _file(),
            item_number=number,
            source_catalog=source,
            source_catalog_sha256=catalog_sha,
            source_index=index,
            question_catalog=question,
        )
        for number in range(1, count + 1)
    )
    assert counts == dict(source=1, question=count, hash=1, source_lookup=2)
    assert indexed == ordinary
    assert canonical_json_bytes([scope.model_dump(mode="json") for scope in indexed]) == (
        canonical_json_bytes([scope.model_dump(mode="json") for scope in ordinary])
    )
    # A later call/book builds its own index; nothing persists globally.
    assert build_native_source_visual_index(source, source_catalog_sha256=catalog_sha) is not index
    assert counts == dict(source=2, question=count, hash=2, source_lookup=4)


def _case12_catalog(*, question):
    """Exact five descriptor hashes/geometry from approved case12/14 diagnostic.

    This closed metadata subset is synthetic, not the complete canonical source
    catalog or a claim to parse/render source bytes in a contract unit test.
    """
    source_sha = (
        "sha256:4465bab738133d43c428675a0ea7e4bc8ef05e0a742a758d9e88a2726e740f7a"
        if question
        else "sha256:cbeb64a319e4b1f9c9cb5e964b8ff4215865591282e862bfa69c9611196ec01b"
    )
    hashes = (
        "db62ceb8843204b36c3d3cbe64f8f8d767f9f692e132e3286b534d5e6743603d",
        "2df575268e38aba0542f35c8df20561a68fb3f1d6b471dd55e1173f72f7af519",
        "daed771128740d7546909ac365a10de172672b96bce6c112360adef7790b06ba",
        "6616dc47a31669e0d9a20f137d58bbb51bc9ea4e58a8071855d542e41506b21a",
        "54e874703cb47027289fcb8255c4e2f953bb85088b4eea2bc00b26cd7a59a09a",
    )
    views = (
        "3a9454d99f387a37b914eaaca6903c55f222b1da0f7e1b54b9da17945077aeeb",
        "774ca8bed759d2e7e965140b4ec333192dc7c6367b47b5ac7999522ef24c7b3b",
        "b8f8e74d83b87ae4fc7ca1dcb2e052a08d02ef7db31c3a67cbef130b1f1774ba",
    )
    viewports = ((1600, 3556, 19669, 15831), (19923, 3556, 37961, 15831), (0, 19964, 76800, 41940))
    ordinals = (130, 165, 200, 235, 340) if question else (3939, 3974, 4009, 4044, 4149)
    value = _catalog(source_sha, (), native=True).model_dump(mode="json")
    whole = "893df86d233b30f0a808481075457a52147b6f42e348815cba40f38bc3570158"
    value["embedded_images"]["images"] = [
        dict(
            source_member="BinData/image14.png",
            source_member_sha256="sha256:" + whole,
            source_format="PNG",
            pixel_sha256="sha256:dd3f6a35c9593e277b238b78fd822d531ab93690da357b154b83a4a7117daccc",
            member_path="images/" + whole + ".png",
            sha256="sha256:" + whole,
            width_px=1024,
            height_px=559,
            content_length=103695,
        )
    ]
    for index, ordinal in enumerate(ordinals):
        view_index = index % 2 if index < 4 else 2
        locator = OfficeObjectLocator(member_path="Contents/section3.xml", ordinal=ordinal)
        identifier = office_object_id(source_sha, locator)
        value["picture_uses"].append(
            dict(
                use_id=identifier,
                locator=locator.model_dump(mode="json"),
                source_member="BinData/image14.png",
                native_sha256="sha256:" + hashes[index],
                group_id=None,
                geometry=dict(
                    original_extent=(76800, 41940),
                    viewport=viewports[view_index],
                    clockwise_quarter_turns=0,
                    flip_horizontal=False,
                    flip_vertical=False,
                ),
                placement=dict(
                    anchor_ordinal=ordinal - 2,
                    width=(5973, 5963, 23492)[view_index],
                    height=4058 if index < 4 else 6722,
                    horizontal_offset=0,
                    vertical_offset=3825,
                    horizontal_relative="COLUMN",
                    vertical_relative="PARA",
                    z_order=211 + index if index < 4 else 210,
                ),
                unresolved_reasons=[],
            )
        )
        value["rendered_uses"].append(
            dict(
                use_id=identifier,
                member_path="uses/" + views[view_index] + ".png",
                sha256="sha256:" + views[view_index],
                width_px=242 if index < 4 else 1024,
                height_px=165 if index < 4 else 293,
                content_length=(9171, 6567, 41542)[view_index],
            )
        )
    return _rehash_catalog(value)


def _rehash_catalog(value):
    embedded = value["embedded_images"]
    embedded["manifest_sha256"] = content_sha256(
        {key: member for key, member in embedded.items() if key != "manifest_sha256"}
    )
    value["manifest_sha256"] = content_sha256(
        {key: member for key, member in value.items() if key != "manifest_sha256"}
    )
    return OfficePictureUseCatalog.model_validate(value)


def _case12_scope(source, question, *, source_index=None):
    file = _file().model_copy(
        update={
            "original_source_sha256": source.embedded_images.source_sha256,
            "document": _file().document.model_copy(
                update={"sha256": question.embedded_images.source_sha256}
            ),
        }
    )
    arguments = dict(
        item_number=14,
        source_catalog=source,
        source_catalog_sha256=_sha(source),
        question_catalog=question,
    )
    return (
        build_material_native_question_visual_scope(file, **arguments)
        if source_index is None
        else build_material_native_question_visual_scope_from_index(
            file, source_index=source_index, **arguments
        )
    )


def test_case12_actual_five_hashes_resolve_distinct_same_view_native_instances():
    source, question = _case12_catalog(question=False), _case12_catalog(question=True)
    scope = _case12_scope(source, question)
    expected = tuple(sorted(use.use_id for use in source.picture_uses))
    assert scope.allowed_picture_use_ids == expected
    assert set(expected) == {
        "officeobj_84096e23962441fb79249e5693c0dc03",
        "officeobj_22bcc6156beec2afaad2f10d871066ef",
        "officeobj_95b3d9e6551ae86b0c896b8694ac649e",
        "officeobj_07c22f8fc360d4146957bf73ea7baf18",
        "officeobj_6cd1acd0fa1936dac5cfb9ca4351d211",
    }
    # The identical display sizes and rebased anchor ordinals are not selectors.
    assert source.picture_uses[0].placement.width == source.picture_uses[2].placement.width
    assert question.picture_uses[0].placement != source.picture_uses[0].placement
    for index, use in enumerate(question.picture_uses):
        single = question.model_dump(mode="json")
        single["picture_uses"], single["rendered_uses"] = (
            [single["picture_uses"][index]],
            [single["rendered_uses"][index]],
        )
        assert _case12_scope(source, _rehash_catalog(single)).allowed_picture_use_ids == (
            source.picture_uses[index].use_id,
        )
        assert use.native_sha256 == source.picture_uses[index].native_sha256


@pytest.mark.parametrize(
    "fault", ["no-exact", "two-exact", "cross-format", "wrong-view", "other-view-native"]
)
def test_native_secondary_lookup_never_guesses_or_overrides_view_and_format(fault):
    source, question = _case12_catalog(question=False), _case12_catalog(question=True)
    value = source.model_dump(mode="json")
    candidate = question.model_dump(mode="json")
    code = "MATERIAL_NATIVE_VISUAL_SOURCE_USE_AMBIGUOUS"
    if fault == "no-exact":
        candidate["picture_uses"][0]["native_sha256"] = "sha256:" + "f" * 64
    elif fault == "two-exact":
        value["picture_uses"][2]["native_sha256"] = value["picture_uses"][0]["native_sha256"]
    elif fault == "cross-format":
        value["embedded_images"]["source_format"] = "HWP5"
    elif fault == "other-view-native":
        candidate["picture_uses"][0]["native_sha256"] = value["picture_uses"][-1]["native_sha256"]
    else:
        digest = "f" * 64
        candidate["rendered_uses"][0].update(
            sha256="sha256:" + digest, member_path="uses/" + digest + ".png"
        )
        code = "MATERIAL_NATIVE_VISUAL_SOURCE_USE_NOT_FOUND"
    with pytest.raises(ValueError, match=code):
        _case12_scope(_rehash_catalog(value), _rehash_catalog(candidate))


def test_secondary_index_excludes_group_composition_even_when_native_hash_is_exact():
    source = _catalog(SOURCE, (FIGURE, FIGURE, FIGURE), native=True)
    question = _catalog(FRAGMENT, (NATIVE_FIGURE,), native=True)
    value = source.model_dump(mode="json")
    locator = OfficeObjectLocator(member_path="Contents/section0.xml", ordinal=100)
    group = office_object_id(SOURCE, locator)
    value["native_objects"] = [
        dict(
            object_id=group,
            locator=locator.model_dump(mode="json"),
            kind="GROUP",
            group_id=None,
            native_sha256="sha256:" + "f" * 64,
        )
    ]
    value["picture_uses"][0].update(
        group_id=group, unresolved_reasons=["GROUP_COMPOSITION_REQUIRED"]
    )
    value["rendered_uses"] = value["rendered_uses"][1:]
    candidate = question.model_dump(mode="json")
    candidate["picture_uses"][0]["native_sha256"] = value["picture_uses"][0]["native_sha256"]
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SOURCE_USE_AMBIGUOUS"):
        _scope(_rehash_catalog(value), _rehash_catalog(candidate))


def test_unique_view_path_does_not_require_same_native_hash():
    source, question = _case12_catalog(question=False), _case12_catalog(question=True)
    expected = _case12_scope(source, question)
    value = question.model_dump(mode="json")
    value["picture_uses"][-1]["native_sha256"] = "sha256:" + "f" * 64
    assert _case12_scope(source, _rehash_catalog(value)) == expected


@pytest.mark.parametrize("count", [1, 25])
def test_secondary_index_is_built_once_per_book_with_identical_standalone_projection(
    monkeypatch, count
):
    source, question = _case12_catalog(question=False), _case12_catalog(question=True)
    expected = _case12_scope(source, question)
    counts = dict(source=0, question=0, hash=0, source_lookup=0)
    require, encode, identity = (
        selection_owner._require_catalog,
        selection_owner.canonical_json_bytes,
        selection_owner._view_identity,
    )

    def validate(catalog, *, question):
        counts["question" if question else "source"] += 1
        return require(catalog, question=question)

    def canonical(value):
        counts["hash"] += 1
        return encode(value)

    def view_identity(image, view):
        if image is source.embedded_images.images[0]:
            counts["source_lookup"] += 1
        return identity(image, view)

    monkeypatch.setattr(selection_owner, "_require_catalog", validate)
    monkeypatch.setattr(selection_owner, "canonical_json_bytes", canonical)
    monkeypatch.setattr(selection_owner, "_view_identity", view_identity)
    index = build_native_source_visual_index(source, source_catalog_sha256=_sha(source))
    actual = tuple(_case12_scope(source, question, source_index=index) for _ in range(count))
    assert counts == dict(source=1, question=count, hash=1, source_lookup=5)
    assert actual == (expected,) * count
    assert all(
        canonical_json_bytes(scope.model_dump(mode="json"))
        == canonical_json_bytes(expected.model_dump(mode="json"))
        for scope in actual
    )


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
