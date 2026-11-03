"""One original-image Artifact serves intake, registration and HWPX pointers."""

import io
import struct
import zipfile
import zlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.office_item_learning import (
    OfficeItemLearningWorkInput,
    OfficeVisualBindings,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_image_contracts.office_picture_uses import OfficePictureUseCatalog
from eom_orchestrator import office_picture_use_publication as owner
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.file_set_control_artifacts import PublishedControlFileSet
from eom_orchestrator.office_picture_use_extraction import (
    ExtractedOfficePictureUses,
    unpack_office_picture_use_input,
)

from tests.unit.test_office_item_learning import office_case


def publication_case(tmp_path):
    work, result, catalog, bindings = office_case()

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 19, 13, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress((b"\0" + b"\0\0\0" * 19) * 13))
        + chunk(b"IEND", b"")
    )
    value = catalog.model_dump(mode="json")
    image = value["embedded_images"]["images"][0]
    image.update(
        sha256=sha256_bytes(png),
        member_path="images/" + sha256_bytes(png)[7:] + ".png",
        content_length=len(png),
    )
    value["embedded_images"]["manifest_sha256"] = content_sha256(
        {key: item for key, item in value["embedded_images"].items() if key != "manifest_sha256"}
    )
    for view in value["rendered_uses"]:
        view.update(
            sha256=image["sha256"], member_path=image["member_path"], content_length=len(png)
        )
    value["manifest_sha256"] = content_sha256(
        {key: item for key, item in value.items() if key != "manifest_sha256"}
    )
    catalog = OfficePictureUseCatalog.model_validate(value)
    manifest = canonical_json_bytes(catalog.model_dump(mode="json"))
    raw_work = work.model_dump(mode="json")
    raw_work["office_artifact"]["sha256"] = sha256_bytes(manifest)
    raw_work["request_sha256"] = content_sha256(
        {key: item for key, item in raw_work.items() if key != "request_sha256"}
    )
    work = OfficeItemLearningWorkInput.model_validate(raw_work)
    bindings = OfficeVisualBindings.model_validate(
        {**bindings.model_dump(mode="json"), "office_catalog_sha256": work.office_artifact.sha256}
    )
    workspace = tmp_path / "local"
    (workspace / "images").mkdir(parents=True)
    for path, payload in (
        (workspace / "picture-use-catalog.json", manifest),
        (workspace / image["member_path"], png),
    ):
        path.write_bytes(payload)
        path.chmod(0o600)
    extracted = ExtractedOfficePictureUses(
        catalog, workspace, tuple(sorted(("picture-use-catalog.json", image["member_path"])))
    )
    return work, result, catalog, bindings, extracted


def fixture(monkeypatch, tmp_path):
    work, result, catalog, bindings, extracted = publication_case(tmp_path)
    artifact = work.office_artifact
    publisher = Mock()
    publisher.settings.nas_artifact_root = tmp_path / "nas"
    published = PublishedControlFileSet(
        "job_" + "1" * 32,
        artifact.artifact_id,
        artifact.artifact_revision_id,
        artifact.member_path,
        artifact.sha256,
        artifact.file_set_manifest_sha256,
        str(
            publisher.settings.nas_artifact_root
            / artifact.artifact_id
            / artifact.artifact_revision_id
        ),
    )
    publisher.find_published.return_value = None
    publisher.read_published_revision.return_value = published
    publisher.publish_first_observation.side_effect = lambda **request: (
        setattr(publisher.find_published, "return_value", published) or published
    )
    reader = Mock(return_value=canonical_json_bytes(catalog.model_dump(mode="json")))
    monkeypatch.setattr(owner, "resolve_control_artifact_member", reader)
    authorize = Mock()
    return SimpleNamespace(**locals())


def test_input_publication_is_idempotent_and_registration_reuses_exact_original_members(
    monkeypatch, tmp_path
):
    case = fixture(monkeypatch, tmp_path)
    first = owner.publish_office_picture_catalog(
        case.publisher, case.extracted, source_commit="a" * 40, authorize_source=case.authorize
    )
    second = owner.publish_office_picture_catalog(
        case.publisher, case.extracted, source_commit="b" * 40, authorize_source=case.authorize
    )
    assert first == second == case.work.office_artifact
    assert case.publisher.publish_first_observation.call_count == 1
    members = case.publisher.publish_first_observation.call_args.kwargs["members"]
    assert len(members) == 2  # manifest + one shared full PNG, not one PNG per use
    assert all(
        member.source.read_bytes() and sha256_bytes(member.source.read_bytes()) == member.sha256
        for member in members
    )
    images = owner.resolve_office_source_images(
        case.publisher, work=case.work, result=case.result, selection=case.bindings
    )
    image = next(iter(images.values()))
    assert image.artifact.artifact_id == first.artifact_id
    assert image.artifact.artifact_revision_id == first.artifact_revision_id
    assert image.artifact.artifact_member == case.catalog.rendered_uses[0].member_path
    assert case.publisher.publish_first_observation.call_count == 1
    with pytest.raises(TypeError):
        images["unrelated"] = image


def test_canonical_registration_uses_original_member_without_pdf_crop(monkeypatch, tmp_path):
    from eom_catalog_service.creative_item_registration import CreativeItemRegistrationService
    from eom_workflow.schemas import validate_role_result

    from tests.unit.test_creative_learning_protocol_v2 import role_result

    case = fixture(monkeypatch, tmp_path)
    raw = role_result()
    raw["protocol_version"] = "workflow-role/1.36.0"
    raw["output"] = {
        "learning_result": case.result.model_dump(mode="json"),
        "office_visuals": case.bindings.model_dump(mode="json"),
    }
    role = validate_role_result(raw, "support", "external-item-learning-result@3.0")
    service = object.__new__(CreativeItemRegistrationService)
    service.publisher, service.artifacts = case.publisher, Mock()
    crop = Mock(side_effect=AssertionError("native registration must never crop a PDF"))
    monkeypatch.setattr(
        "eom_catalog_service.creative_item_registration.publish_creative_source_visuals", crop
    )
    content = service._prepare_successor_content(SimpleNamespace(work=case.work, role=role))
    image = content.content.body[-1]
    assert image.artifact.artifact_id == case.work.office_artifact.artifact_id
    assert image.artifact.artifact_member == case.catalog.rendered_uses[0].member_path
    assert (image.width_px, image.height_px) == (19, 13)
    service.artifacts.read_member.assert_not_called()
    crop.assert_not_called()


def test_incomplete_publication_uses_supported_resume_but_terminal_failure_is_not_reinterpreted(
    monkeypatch, tmp_path
):
    case = fixture(monkeypatch, tmp_path)
    case.publisher.find_published.side_effect = ControlPlaneError(
        "CONTROL_FILE_SET_INCOMPLETE", "interrupted"
    )
    owner.publish_office_picture_catalog(
        case.publisher, case.extracted, source_commit="a" * 40, authorize_source=case.authorize
    )
    assert case.publisher.publish_first_observation.call_count == 1
    case.publisher.find_published.side_effect = ControlPlaneError(
        "CONTROL_FILE_SET_FAILED", "preserved"
    )
    with pytest.raises(ControlPlaneError, match="preserved"):
        owner.publish_office_picture_catalog(
            case.publisher, case.extracted, source_commit="a" * 40, authorize_source=case.authorize
        )
    assert case.publisher.publish_first_observation.call_count == 1


@pytest.mark.parametrize(
    "fault", ["extra-member", "duplicate-member", "changed-png", "wrong-source"]
)
def test_sandbox_output_failures_create_no_local_candidate(tmp_path, fault):
    work, _result, catalog, _bindings, extracted = publication_case(tmp_path)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as package:
        for member in extracted.members:
            payload = (extracted.workspace / member).read_bytes()
            if fault == "changed-png" and member.endswith(".png"):
                payload += b"changed"
            package.writestr(member, payload)
        if fault == "extra-member":
            package.writestr("../outside", b"not extracted")
        elif fault == "duplicate-member":
            with pytest.warns(UserWarning):
                package.writestr("picture-use-catalog.json", b"duplicate")
    target = tmp_path / "unpacked"
    with pytest.raises(ValueError):
        unpack_office_picture_use_input(
            output.getvalue(),
            expected_sha256="sha256:" + "0" * 64
            if fault == "wrong-source"
            else work.source.preview_manifest.source_sha256,
            workspace=target,
        )
    assert not target.exists()
