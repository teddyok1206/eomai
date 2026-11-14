"""Nonlive preparation ports: immutable metadata and synthetic PNGs, never NAS/DB/tools."""

from __future__ import annotations

import struct
import zlib
from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialArtifactMember
from eom_catalog_contracts.material_native_intake import (
    MaterialNativeExamBundle,
    MaterialNativeLearningIntakeManifest,
    MaterialNativePreparedArtifact,
)
from eom_catalog_contracts.material_native_visual_preparation import (
    MaterialNativeVisualPreparedArtifact,
)
from eom_catalog_service import material_native_visual_preparation as owner
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
from eom_orchestrator import office_picture_use_publication as publication
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import PublishedControlFileSet
from eom_orchestrator.office_picture_use_extraction import ExtractedOfficePictureUses
from eom_orchestrator.state_machine import JobState
from eom_protocol.artifact_members import ArtifactMemberPointer

from tests.unit.test_material_learning_contracts import rehash
from tests.unit.test_material_learning_preparation import bundle as page_bundle_data
from tests.unit.test_material_native_intake import native_exam_bundle, native_intake
from tests.unit.test_material_native_visual_preparation import base_prepared
from tests.unit.test_material_native_visual_selection import FIGURE, LOGO, NATIVE_FIGURE, _catalog

SOURCE = "1" * 40
TOOL_SOURCE = "2" * 40
PREPARED_TYPE = "control_material_native_visual_prepared"
CATALOG_TYPE = "control_office_picture_use_catalog"


def _png(width, height, rgba):
    def chunk(kind, raw):
        return (
            struct.pack(">I", len(raw))
            + kind
            + raw
            + struct.pack(">I", zlib.crc32(kind + raw) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + rgba * width) * height))
        + chunk(b"IEND", b"")
    )


def _real_catalog(source_sha, *, native=False, empty=False, ambiguous=False):
    specs = () if empty else (NATIVE_FIGURE,) if native else (FIGURE, LOGO)
    if ambiguous:
        specs = (FIGURE, FIGURE, LOGO)
    catalog = _catalog(
        source_sha,
        specs,
        native=native,
        unsupported=("BinData/unreferenced.emf",) if empty else (),
    )
    value = catalog.model_dump(mode="json", exclude={"manifest_sha256"})
    payloads, by_member = {}, {}
    for image in value["embedded_images"]["images"]:
        rgba = bytes.fromhex(image["pixel_sha256"][7:13]) + b"\xff"
        png = _png(image["width_px"], image["height_px"], rgba)
        digest = sha256_bytes(png)
        image.update(
            pixel_sha256=sha256_bytes(
                struct.pack("<II", image["width_px"], image["height_px"])
                + rgba * image["width_px"] * image["height_px"]
            ),
            sha256=digest,
            member_path="images/" + digest[7:] + ".png",
            content_length=len(png),
        )
        payloads[image["member_path"]] = png
        by_member[image["source_member"]] = image
    by_use = {use["use_id"]: use for use in value["picture_uses"]}
    for view in value["rendered_uses"]:
        image = by_member[by_use[view["use_id"]]["source_member"]]
        view.update(
            sha256=image["sha256"],
            member_path=image["member_path"],
            content_length=image["content_length"],
        )
    embedded = value["embedded_images"]
    embedded["manifest_sha256"] = content_sha256(
        {key: data for key, data in embedded.items() if key != "manifest_sha256"}
    )
    catalog = OfficePictureUseCatalog.model_validate(rehash(value, "manifest_sha256"))
    payloads["picture-use-catalog.json"] = canonical_json_bytes(catalog.model_dump(mode="json"))
    return catalog, payloads


def _old_geometry(catalog):
    value = catalog.model_dump(mode="json", exclude={"manifest_sha256"})
    use = value["picture_uses"][0]
    use.update(geometry=None, unresolved_reasons=["GEOMETRY_UNRESOLVED"])
    value["rendered_uses"] = [
        view for view in value["rendered_uses"] if view["use_id"] != use["use_id"]
    ]
    return OfficePictureUseCatalog.model_validate(rehash(value, "manifest_sha256"))


class Artifacts:
    """Exact in-memory canonical read port; writes through Catalog are forbidden."""

    engine = object()

    def __init__(self, events):
        self.events, self.values = events, {}

    def put(self, pointer, raw):
        pointer = pointer.model_copy(update={"sha256": sha256_bytes(raw), "bytes": len(raw)})
        self.values[pointer.artifact_id, pointer.artifact_revision_id, pointer.member_path] = (
            pointer,
            raw,
        )
        return pointer

    def read_member(self, **request):
        key = request["artifact_id"], request["revision_id"], request["member_path"]
        pointer, raw = self.values[key]
        assert request["schema_ref"] == pointer.schema_ref
        assert request["media_type"] == pointer.media_type
        if request["sha256"] != pointer.sha256 or sha256_bytes(raw) != pointer.sha256:
            raise ValueError("TEST_CANONICAL_HASH_MISMATCH")
        if request["max_bytes"] < len(raw):
            raise ValueError("TEST_CANONICAL_SIZE_LIMIT")
        self.events.append(("read", pointer.member_path))
        return raw

    def commit_file_set(self, **_request):
        raise AssertionError("Catalog Job publication is not the control publisher")


class Publisher:
    """Fake existing control protocol, preserving failed immutable keys."""

    def __init__(self, artifacts, root, events):
        self.artifacts, self.events = artifacts, events
        self.engine = object()
        self.settings = SimpleNamespace(nas_artifact_root=root)
        self.completed, self.failed, self.calls = {}, set(), []
        self.fail_type = None

    def find_published(self, *, idempotency_key, artifact_type):
        key = artifact_type, idempotency_key
        self.events.append(("find", *key))
        if key in self.failed:
            raise ControlPlaneError("CONTROL_FILE_SET_INCOMPLETE", "synthetic failed key")
        return self.completed.get(key)

    def find_published_primary_member(self, **request):
        published = self.find_published(**request)
        if published is None:
            return None
        pointer, _ = self.artifacts.values[
            published.artifact_id, published.artifact_revision_id, published.primary_file
        ]
        return ArtifactMemberPointer(**pointer.model_dump(exclude={"bytes"}))

    def publication_state(self, *, idempotency_key, artifact_type):
        assert (artifact_type, idempotency_key) in self.failed
        return JobState.FAILED

    def read_published_revision(self, *, artifact_revision_id, artifact_type):
        return next(
            value
            for (kind, _), value in self.completed.items()
            if kind == artifact_type and value.artifact_revision_id == artifact_revision_id
        )

    def publish_first_observation(self, **request):
        key = request["artifact_type"], request["idempotency_key"]
        assert key not in self.failed and key not in self.completed
        self.calls.append(request)
        self.events.append(("publish", *key))
        if request["artifact_type"] == self.fail_type:
            self.failed.add(key)
            raise ControlPlaneError("CONTROL_FILE_SET_INCOMPLETE", "synthetic failed publication")
        number = len(self.completed) + 256
        artifact_id, revision_id = f"artifact_{number:032x}", f"rev_{number:032x}"
        for member in request["members"]:
            raw = member.source.read_bytes()
            assert len(raw) == member.bytes and sha256_bytes(raw) == member.sha256
            pointer = MaterialArtifactMember(
                artifact_id=artifact_id,
                artifact_revision_id=revision_id,
                member_path=member.file_name,
                sha256=member.sha256,
                bytes=member.bytes,
                schema_ref=member.schema_ref,
                media_type=member.media_type,
            )
            self.artifacts.put(pointer, raw)
        primary = next(
            item for item in request["members"] if item.file_name == request["primary_file"]
        )
        published = PublishedControlFileSet(
            f"job_{number:032x}",
            artifact_id,
            revision_id,
            primary.file_name,
            primary.sha256,
            content_sha256({"test": number}),
            str(self.settings.nas_artifact_root / artifact_id / revision_id),
        )
        self.completed[key] = published
        return published


def _case(monkeypatch, tmp_path, *, fixed=False, empty=False, ambiguous=False, two=False):
    events = []
    artifacts = Artifacts(events)
    settings = CatalogSettings(staging_root=tmp_path / "staging")
    settings.staging_root.mkdir()
    tool_root = tmp_path / "tools" / TOOL_SOURCE / "site-packages"
    files = tool_root / "eom_image_provider"
    files.mkdir(parents=True)
    for name in (
        "office_embedded_images",
        "office_picture_records",
        "office_picture_xml",
        "office_picture_views",
    ):
        (files / (name + ".py")).write_text("# fixed synthetic tool " + name)
    publisher = Publisher(artifacts, tmp_path / "not-live-nas", events)
    monkeypatch.setattr(
        owner,
        "MaterialLearningSourceService",
        lambda *_: SimpleNamespace(
            resolve=lambda receipt, *, operator_id: events.append(
                ("source-auth", operator_id, receipt.original.sha256)
            )
        ),
    )
    service = owner.MaterialNativeVisualPreparationService(
        artifacts=artifacts,
        publisher=publisher,
        settings=settings,
        tool_root=tool_root,
        source_commit=SOURCE,
    )
    base_data, intake_data, bundle_data = (
        base_prepared().model_dump(mode="json"),
        native_intake(),
        native_exam_bundle(),
    )
    for index, role in enumerate(("MAIN", "SOLUTIONS")):
        original = MaterialArtifactMember.model_validate(
            intake_data["sources"][index]["source_upload"]["original"]
        )
        original = artifacts.put(original, ("synthetic original " + role).encode())
        intake_data["sources"][index]["source_upload"]["original"] = original.model_dump(
            mode="json"
        )
        base_data["sources"][index]["original"] = original.model_dump(mode="json")
        bundle_data["main_original" if index == 0 else "solutions_original"] = original.model_dump(
            mode="json"
        )
        bundle_data["items"][0]["question" if index == 0 else "solution"][
            "original_source_sha256"
        ] = original.sha256
    source_catalog, source_payloads = _real_catalog(
        base_data["sources"][0]["original"]["sha256"], ambiguous=ambiguous
    )
    old_catalog = source_catalog if fixed else _old_geometry(source_catalog)
    pointer = MaterialArtifactMember.model_validate(base_data["sources"][0]["office_catalog"])
    pointer = artifacts.put(pointer, canonical_json_bytes(old_catalog.model_dump(mode="json")))
    base_data["sources"][0]["office_catalog"] = pointer.model_dump(mode="json")
    question = bundle_data["items"][0]["question"]
    document = artifacts.put(
        MaterialArtifactMember.model_validate(question["document"]), b"synthetic native question"
    )
    question["document"] = document.model_dump(mode="json")
    evidence = dict(
        source_sha256=question["native_source_sha256"],
        plan_sha256=question["split_plan_sha256"],
        source_role="MAIN",
        item_number=1,
        ranges=question["ranges"],
        paragraph_sha256=["sha256:" + "0" * 64],
        context_sha256=[],
        binary_sha256=[],
        counts=dict(paragraphs=1, tables=0, equations=0, pictures=0 if empty else 1),
        output_sha256=document.sha256,
        output_size_bytes=document.bytes,
    )
    from eom_hwpx_contracts.native_item_split import NativeItemSplitResult

    evidence = NativeItemSplitResult.model_validate(evidence)
    evidence_pointer = artifacts.put(
        MaterialArtifactMember.model_validate(question["split_evidence"]),
        canonical_json_bytes(evidence.model_dump(mode="json")),
    )
    question["split_evidence"] = evidence_pointer.model_dump(mode="json")
    if two:
        second = deepcopy(bundle_data["items"][0])
        second.update(item_number=2, printed_label="02번", row_number=4)
        for name in ("question", "solution"):
            for kind in ("document", "split_evidence"):
                second[name][kind]["member_path"] = second[name][kind]["member_path"].replace(
                    "items/1/", "items/2/"
                )
        second["question"]["document"] = artifacts.put(
            MaterialArtifactMember.model_validate(second["question"]["document"]),
            b"synthetic native question",
        ).model_dump(mode="json")
        second["question"]["split_evidence"] = artifacts.put(
            MaterialArtifactMember.model_validate(second["question"]["split_evidence"]),
            canonical_json_bytes(
                evidence.model_copy(update={"item_number": 2}).model_dump(mode="json")
            ),
        ).model_dump(mode="json")
        bundle_data["items"].append(second)
    bundle = MaterialNativeExamBundle.model_validate(rehash(bundle_data, "bundle_sha256"))
    bundle_pointer = artifacts.put(
        MaterialArtifactMember.model_validate(intake_data["native_bundle"]),
        canonical_json_bytes(bundle.model_dump(mode="json")),
    )
    intake_data["native_bundle"] = base_data["native_bundle"] = bundle_pointer.model_dump(
        mode="json"
    )
    intake = MaterialNativeLearningIntakeManifest.model_validate(intake_data)
    pages = page_bundle_data()
    source = base_data["sources"][0]
    source["page_count"] = pages["page_count"]
    source["pdf"].update(
        media_type="application/pdf",
        schema_ref="eom://schemas/educational-document/pdf-source/1.0",
    )
    for name in (
        "document_id",
        "document_revision_id",
        "source_role",
        "original",
        "pdf",
        "office_catalog",
    ):
        pages[name] = source[name]
    pages["profile"].update(
        source_commit=SOURCE if fixed else "0" * 40,
        office_tool_source_commit=TOOL_SOURCE,
        libreoffice_sha256="sha256:" + "f" * 64,
        h2orestart_sha256="sha256:" + "e" * 64,
    )
    pages["profile"] = rehash(pages["profile"], "profile_sha256")
    pages["conversion"].update(
        conversion_kind="LIBREOFFICE_H2ORESTART_PDF",
        review_pdf_sha256=source["pdf"]["sha256"],
        libreoffice_version="24.2.7",
        libreoffice_sha256="sha256:" + "f" * 64,
        h2orestart_sha256="sha256:" + "e" * 64,
    )
    source["page_bundle"] = artifacts.put(
        MaterialArtifactMember.model_validate(source["page_bundle"]), canonical_json_bytes(pages)
    ).model_dump(mode="json")
    base = MaterialNativePreparedArtifact.model_validate(rehash(base_data, "prepared_sha256"))
    base_pointer = artifacts.put(
        MaterialArtifactMember.model_validate(
            {
                **base_data["intake_manifest"],
                "schema_ref": "eom://schemas/material-learning/prepared/2.0",
                "member_path": "material/prepared.json",
            }
        ),
        canonical_json_bytes(base.model_dump(mode="json")),
    )
    question_catalog, question_payloads = _real_catalog(document.sha256, native=True, empty=empty)
    extractions = []

    def extract(raw, *, expected_sha256, tool_root, workspace):
        assert sha256_bytes(raw) == expected_sha256
        assert tool_root == service.tool_root and not workspace.exists()
        assert (tool_root / "eom_image_provider/office_picture_xml.py").is_file()
        catalog, payloads = (
            (question_catalog, question_payloads)
            if expected_sha256 == document.sha256
            else (source_catalog, source_payloads)
        )
        assert catalog.embedded_images.source_sha256 == expected_sha256
        workspace.mkdir()
        for name, payload in payloads.items():
            path = workspace / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(payload)
        extractions.append((expected_sha256, workspace))
        events.append(("extract", expected_sha256))
        return ExtractedOfficePictureUses(catalog, workspace, tuple(sorted(payloads)))

    monkeypatch.setattr(owner, "extract_office_picture_use_input", extract)

    def read_control(_engine, pointer, *, maximum_bytes):
        assert maximum_bytes == 8 * 1024 * 1024
        return artifacts.read_member(
            **pointer.model_dump(exclude={"artifact_revision_id"}),
            revision_id=pointer.artifact_revision_id,
            max_bytes=maximum_bytes,
        )

    monkeypatch.setattr(publication, "resolve_control_artifact_member", read_control)

    def authorize():
        events.append("auth")

    def enrich():
        return service.enrich(
            base, base_pointer, intake=intake, operator_id=intake.requested_by, authorize=authorize
        )

    return SimpleNamespace(**locals())


def test_old_base_extracts_source_once_and_publishes_only_one_canonical_image_set(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path)
    result = case.enrich()
    assert isinstance(result.prepared, MaterialNativeVisualPreparedArtifact)
    assert result.prepared.sources == case.base.sources
    assert result.prepared.base_prepared == case.base_pointer
    assert result.prepared.question_visual_scopes[0].allowed_picture_use_ids == (
        case.source_catalog.picture_uses[0].use_id,
    )
    assert [request["artifact_type"] for request in case.publisher.calls] == [
        CATALOG_TYPE,
        PREPARED_TYPE,
    ]
    assert len(case.extractions) == 2
    assert [sha for sha, _ in case.extractions].count(case.document.sha256) == 1
    assert all(not path.exists() for _, path in case.extractions)
    prepared_call = case.publisher.calls[-1]
    assert [member.file_name for member in prepared_call["members"]] == ["material/prepared.json"]
    assert prepared_call["manifest_version"] == "material-learning-prepared-artifact/3.0"
    assert case.events[-1] == "auth"
    first = case.events.index(("extract", case.document.sha256))
    assert case.events[first - 1][0] == "read"
    assert "auth" in case.events[:first] and "auth" in case.events[first + 1 :]


def test_fixed_page_bundle_reuses_existing_catalog_without_whole_source_reextraction(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path, fixed=True)
    outcome = case.enrich()
    supplement = outcome.prepared.catalog_supplements[0]
    assert supplement.catalog == supplement.base_catalog == case.base.sources[0].office_catalog
    assert [sha for sha, _ in case.extractions] == [case.document.sha256]
    assert [request["artifact_type"] for request in case.publisher.calls] == [PREPARED_TYPE]


def test_two_questions_share_one_source_publication_and_have_only_temporary_comparison_images(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path, two=True)
    outcome = case.enrich()
    assert tuple(scope.item_number for scope in outcome.prepared.question_visual_scopes) == (1, 2)
    assert [sha for sha, _ in case.extractions].count(case.document.sha256) == 2
    assert len(case.extractions) == 3  # One source plus two native bodies, not two full sources.
    assert [call["artifact_type"] for call in case.publisher.calls] == [CATALOG_TYPE, PREPARED_TYPE]
    assert all(not path.exists() for _, path in case.extractions)
    assert len(case.publisher.calls[-1]["members"]) == 1


def test_exact_control_replay_reads_checkpoint_and_base_without_new_extraction_or_publish(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path)
    first = case.enrich()
    counts = len(case.publisher.calls), len(case.extractions)
    second = case.enrich()
    assert second == first
    assert (len(case.publisher.calls), len(case.extractions)) == counts
    assert ("read", "material/prepared.json") in case.events
    assert case.events[-1] == "auth"


def test_new_exact_base_pointer_uses_a_new_key_without_replacing_the_previous_checkpoint(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path, fixed=True)
    first = case.enrich()
    successor_pointer = case.artifacts.put(
        case.base_pointer.model_copy(update={"artifact_revision_id": "rev_" + "9" * 32}),
        canonical_json_bytes(case.base.model_dump(mode="json")),
    )
    second = case.service.enrich(
        case.base,
        successor_pointer,
        intake=case.intake,
        operator_id=case.intake.requested_by,
        authorize=case.authorize,
    )
    assert first.pointer != second.pointer
    assert first.prepared.base_prepared == case.base_pointer
    assert second.prepared.base_prepared == successor_pointer
    assert len(case.publisher.completed) == 2
    assert len({call["idempotency_key"] for call in case.publisher.calls}) == 2


def test_failed_control_publication_preserves_key_and_is_not_replaced(monkeypatch, tmp_path):
    case = _case(monkeypatch, tmp_path, fixed=True)
    case.publisher.fail_type = PREPARED_TYPE
    for _ in range(2):
        with pytest.raises(ControlPlaneError, match="synthetic failed"):
            case.enrich()
    assert len(case.publisher.calls) == 1
    assert len(case.publisher.failed) == 1
    assert not case.publisher.completed
    assert len(case.extractions) == 1


def test_empty_actual_body_with_retained_emf_creates_empty_scope_and_no_png_publication(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path, fixed=True, empty=True)
    outcome = case.enrich()
    assert outcome.prepared.question_visual_scopes[0].allowed_picture_use_ids == ()
    assert [call["artifact_type"] for call in case.publisher.calls] == [PREPARED_TYPE]
    assert len(case.question_payloads) == 1  # Only temporary catalog metadata, not a fake image.


def test_ambiguous_body_mapping_never_publishes_a_prepared_scope(monkeypatch, tmp_path):
    case = _case(monkeypatch, tmp_path, fixed=True, ambiguous=True)
    with pytest.raises(ValueError, match="SOURCE_USE_AMBIGUOUS"):
        case.enrich()
    assert not case.publisher.calls


def test_wrong_actual_operator_is_rejected_before_any_source_read_or_publication(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path, fixed=True)
    with pytest.raises(ValueError, match="MATERIAL_NATIVE_VISUAL_SOURCE_MISMATCH"):
        case.service.enrich(
            case.base,
            case.base_pointer,
            intake=case.intake,
            operator_id="operator_" + "0" * 32,
            authorize=case.authorize,
        )
    assert not case.events and not case.extractions and not case.publisher.calls


def test_actual_canonical_fragment_bytes_are_hash_checked_before_extraction(monkeypatch, tmp_path):
    case = _case(monkeypatch, tmp_path, fixed=True)
    key = case.document.artifact_id, case.document.artifact_revision_id, case.document.member_path
    pointer, _ = case.artifacts.values[key]
    case.artifacts.values[key] = pointer, b"changed actual fragment bytes"
    with pytest.raises(ValueError, match="TEST_CANONICAL_HASH_MISMATCH"):
        case.enrich()
    assert not case.extractions and not case.publisher.calls


@pytest.mark.parametrize(
    "field", ["output_sha256", "source_sha256", "item_number", "output_size_bytes"]
)
def test_split_receipt_mismatch_is_rejected_before_native_extraction(monkeypatch, tmp_path, field):
    case = _case(monkeypatch, tmp_path, fixed=True)
    body = case.evidence.model_dump(mode="json")
    body[field] = (
        2
        if field == "item_number"
        else 999
        if field == "output_size_bytes"
        else "sha256:" + "0" * 64
    )
    pointer = case.artifacts.put(case.evidence_pointer, canonical_json_bytes(body))
    file = case.bundle.items[0].question.model_copy(update={"split_evidence": pointer})
    with pytest.raises(ValueError, match="SPLIT_EVIDENCE_MISMATCH"):
        case.service.question_scope(
            file,
            item_number=1,
            catalog=case.source_catalog,
            catalog_pointer=case.base.sources[0].office_catalog,
            authorize=case.authorize,
        )
    assert not case.extractions and not case.publisher.calls


def test_current_authority_is_rechecked_after_extract_before_returning_scope(monkeypatch, tmp_path):
    case = _case(monkeypatch, tmp_path, fixed=True)
    count = 0

    def authorize():
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("TEST_SOURCE_REVOKED")

    with pytest.raises(ValueError, match="SOURCE_REVOKED"):
        case.service.question_scope(
            case.bundle.items[0].question,
            item_number=1,
            catalog=case.source_catalog,
            catalog_pointer=case.base.sources[0].office_catalog,
            authorize=authorize,
        )
    assert count == 2 and len(case.extractions) == 1
    assert not case.extractions[0][1].exists() and not case.publisher.calls


@pytest.mark.parametrize("change", ["valid-flip", "image-sha", "old-view"])
def test_catalog_equivalence_rejects_source_or_already_valid_view_changes(change):
    current, _ = _real_catalog("sha256:" + "a" * 64)
    before = _old_geometry(current)
    body = current.model_dump(mode="json", exclude={"manifest_sha256"})
    if change == "valid-flip":
        body["picture_uses"][1]["geometry"]["flip_horizontal"] = True
        code = "CATALOG_GEOMETRY_CHANGED"
    elif change == "image-sha":
        image = body["embedded_images"]["images"][0]
        image.update(sha256="sha256:" + "0" * 64, member_path="images/" + "0" * 64 + ".png")
        body["embedded_images"] = rehash(body["embedded_images"], "manifest_sha256")
        code = "CATALOG_SOURCE_CHANGED"
    else:
        view = body["rendered_uses"][1]
        view.update(sha256="sha256:" + "0" * 64, member_path="uses/" + "0" * 64 + ".png")
        code = "CATALOG_EXISTING_VIEW_CHANGED"
    changed = OfficePictureUseCatalog.model_validate(rehash(body, "manifest_sha256"))
    with pytest.raises(ValueError, match=code):
        owner.require_native_visual_catalog_equivalence(before, changed)


def test_catalog_equivalence_allows_only_missing_geometry_to_be_resolved():
    current, _ = _real_catalog("sha256:" + "a" * 64)
    owner.require_native_visual_catalog_equivalence(_old_geometry(current), current)
    owner.require_native_visual_catalog_equivalence(current, current)


def test_profile_pins_actual_tool_bytes_and_cache_key_changes_with_source_or_tool_profile(
    monkeypatch, tmp_path
):
    case = _case(monkeypatch, tmp_path, fixed=True)
    first = case.enrich()
    parser = case.tool_root / "eom_image_provider/office_picture_xml.py"
    parser.write_text("# different fixed synthetic parser")
    changed = owner.MaterialNativeVisualPreparationService(
        artifacts=case.artifacts,
        publisher=case.publisher,
        settings=case.settings,
        tool_root=case.tool_root,
        source_commit=SOURCE,
    )
    assert (
        changed.profile.parser_implementation_sha256
        != case.service.profile.parser_implementation_sha256
    )
    assert changed.profile.profile_sha256 != first.prepared.visual_profile.profile_sha256
    outcome = changed.enrich(
        case.base,
        case.base_pointer,
        intake=case.intake,
        operator_id=case.intake.requested_by,
        authorize=case.authorize,
    )
    assert outcome.pointer != first.pointer
    keys = [
        call["idempotency_key"]
        for call in case.publisher.calls
        if call["artifact_type"] == PREPARED_TYPE
    ]
    assert len(keys) == len(set(keys)) == 2
