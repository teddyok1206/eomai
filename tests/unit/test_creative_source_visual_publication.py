"""Real synthetic-PDF crops with a fake publisher; never production DB or NAS."""

import shutil
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.creative_source_visuals import (
    CreativeSourceVisualSet,
    validate_creative_source_visual_set,
)
from eom_catalog_contracts.external_item_learning_result_v2 import ExternalItemLearningResultV2
from eom_catalog_contracts.external_item_learning_work import ExternalItemLearningWorkInput
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator import creative_source_visual_publication as owner
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.external_item_learning_page_render import render_creative_source_visuals
from eom_orchestrator.file_set_control_artifacts import PublishedControlFileSet
from eom_protocol.artifact_members import ArtifactMemberPointer
from pydantic import ValidationError

from tests.unit.test_creative_source_visual_render import fixture_source, visual_result
from tests.unit.test_external_item_learning_page_render import _direct_fixture_runner
from tests.unit.test_external_item_learning_work_contract import _work

pytestmark = pytest.mark.skipif(
    shutil.which("pdftoppm") is None or shutil.which("pdfinfo") is None,
    reason="actual synthetic-PDF crop fixture needs Poppler",
)


def _case(monkeypatch, tmp_path, *, repeat=False):
    source, pdf, pages = fixture_source(tmp_path)
    raw = _work()
    raw.update(source=source.model_dump(mode="json"), page_set=pages.model_dump(mode="json"))
    raw["page_artifact"]["sha256"] = sha256_bytes(
        canonical_json_bytes(pages.model_dump(mode="json"))
    )
    raw["request_sha256"] = content_sha256({k: v for k, v in raw.items() if k != "request_sha256"})
    work = ExternalItemLearningWorkInput.model_validate(raw)
    result = visual_result(source, repeat=repeat)
    pointer = ArtifactMemberPointer(
        artifact_id="artifact_" + "c" * 32,
        artifact_revision_id="rev_" + "d" * 32,
        sha256="sha256:" + "e" * 64,
        member_path="result.json",
        schema_ref="external-item-learning-result@2.0",
        media_type="application/json",
    )
    publisher = Mock()
    publisher.find_published.return_value = None
    stored = {}

    def publish(**kwargs):
        stored.update({m.file_name: m.source.read_bytes() for m in kwargs["members"]})
        assert all(sha256_bytes(stored[m.file_name]) == m.sha256 for m in kwargs["members"])
        published = PublishedControlFileSet(
            "job_" + "1" * 32,
            "artifact_" + "2" * 32,
            "rev_" + "3" * 32,
            "visual-set.json",
            sha256_bytes(stored["visual-set.json"]),
            "sha256:" + "4" * 64,
            str(tmp_path / "fake-nas"),
        )
        publisher.read_published_revision.return_value = published
        publisher.find_published.return_value = published
        return published

    publisher.publish_first_observation.side_effect = publish
    page_read = Mock()
    monkeypatch.setattr(owner, "read_external_item_learning_page_artifact", page_read)
    render = Mock(
        side_effect=lambda *args, **kwargs: render_creative_source_visuals(
            *args, **kwargs, run=_direct_fixture_runner
        )
    )
    monkeypatch.setattr(owner, "render_creative_source_visuals", render)

    def read_member(engine, selected, *, maximum_bytes):
        assert engine is publisher.engine
        assert selected.member_path == "visual-set.json" and maximum_bytes == 128 * 1024
        assert sha256_bytes(stored[selected.member_path]) == selected.sha256
        return stored[selected.member_path]

    monkeypatch.setattr(owner, "resolve_control_artifact_member", read_member)
    arguments = dict(
        work=work,
        result=result,
        role_result=pointer,
        pdf_bytes=pdf,
        workspace=tmp_path / "crops",
        source_commit="a" * 40,
        authorize_source=Mock(),
    )
    return publisher, arguments, render, stored, page_read


def test_crops_have_source_derivation_and_replay_reuses_the_exact_artifact(monkeypatch, tmp_path):
    publisher, args, render, stored, page_read = _case(monkeypatch, tmp_path, repeat=True)
    first = owner.publish_creative_source_visuals(publisher, **args)
    assert first is not None and len(first.images) == 2
    assert len(first.receipt.crops) == 1
    a, b = first.images.values()
    assert a.artifact == b.artifact
    assert a.artifact.sha256 == sha256_bytes(stored[a.artifact.artifact_member])
    assert first.receipt.role_result == args["role_result"]
    assert first.receipt.source_revision_id == args["work"].source.source_revision_id
    second = owner.publish_creative_source_visuals(
        publisher, **{**args, "workspace": tmp_path / "unused"}
    )
    assert second == first
    render.assert_called_once()
    publisher.publish_first_observation.assert_called_once()
    assert page_read.call_count == 2
    assert not (tmp_path / "unused").exists()
    with pytest.raises(TypeError):
        first.images["new"] = a


@pytest.mark.parametrize(
    "path",
    [
        "source_revision_id",
        "work_input_sha256",
        "result_sha256",
        "pdf_sha256",
        "role_result.sha256",
        "page_artifact.artifact_revision_id",
        "renderer.pdftoppm_sha256",
        "crops.0.source_page_sha256",
        "crops.0.bounding_box.left",
        "crops.0.pixel_box",
    ],
)
def test_rehashed_receipt_cannot_substitute_source_page_result_or_geometry(
    monkeypatch, tmp_path, path
):
    publisher, args, _, _, _ = _case(monkeypatch, tmp_path)
    receipt = owner.publish_creative_source_visuals(publisher, **args).receipt
    document = receipt.model_dump(mode="json")
    if path == "crops.0.pixel_box":
        document["crops"][0]["pixel_box"][0] += 1
        document["crops"][0]["width_px"] -= 1
    else:
        parts = path.split(".")
        parent = document
        for part in parts[:-1]:
            parent = parent[int(part)] if isinstance(parent, list) else parent[part]
        leaf = parts[-1]
        if leaf == "left":
            parent[leaf] += 1
        elif leaf.endswith("revision_id"):
            prefix = "extitemrev_" if leaf == "source_revision_id" else "rev_"
            parent[leaf] = prefix + "0" * 32
        else:
            parent[leaf] = "sha256:" + "0" * 64
    document["manifest_sha256"] = content_sha256(
        {k: v for k, v in document.items() if k != "manifest_sha256"}
    )
    changed = CreativeSourceVisualSet.model_validate(document)
    with pytest.raises(ValueError, match="MISMATCH"):
        validate_creative_source_visual_set(
            changed, work=args["work"], result=args["result"], role_result=args["role_result"]
        )


def test_schema_mirror_and_tampered_manifest_are_rejected(monkeypatch, tmp_path):
    from hashlib import sha256

    root = Path(__file__).resolve().parents[2]
    relative = "external-item/creative-source-visual-set-v1.schema.json"
    canonical = root / "schemas" / relative
    assert (
        canonical.read_bytes()
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts/resources" / relative
        ).read_bytes()
    )
    assert (
        sha256(canonical.read_bytes()).hexdigest()
        == "76051114c799884a4cf78612dd7561f242971d36465ecfe1b0f5834ff0aa9f32"
    )
    publisher, args, _, _, _ = _case(monkeypatch, tmp_path)
    receipt = owner.publish_creative_source_visuals(publisher, **args).receipt
    document = receipt.model_dump(mode="json")
    document["result_sha256"] = "sha256:" + "0" * 64
    with pytest.raises(ValidationError, match="HASH_MISMATCH"):
        CreativeSourceVisualSet.model_validate(document)


def test_incomplete_commit_replays_same_key_without_rewriting_failed_history(monkeypatch, tmp_path):
    publisher, args, render, _, _ = _case(monkeypatch, tmp_path)
    publish = publisher.publish_first_observation.side_effect
    publisher.publish_first_observation.side_effect = RuntimeError("synthetic interrupted commit")
    with pytest.raises(RuntimeError, match="interrupted"):
        owner.publish_creative_source_visuals(publisher, **args)
    first_key = publisher.publish_first_observation.call_args.kwargs["idempotency_key"]
    publisher.find_published.side_effect = ControlPlaneError(
        "CONTROL_FILE_SET_INCOMPLETE", "synthetic"
    )
    publisher.publish_first_observation.side_effect = publish
    actual = owner.publish_creative_source_visuals(
        publisher, **{**args, "workspace": tmp_path / "retry"}
    )
    assert actual is not None
    assert publisher.publish_first_observation.call_args.kwargs["idempotency_key"] == first_key
    assert render.call_count == 2
    publisher.find_published.side_effect = ControlPlaneError(
        "CONTROL_FILE_SET_CONFLICT", "failed history"
    )
    with pytest.raises(ControlPlaneError, match="failed history"):
        owner.publish_creative_source_visuals(
            publisher, **{**args, "workspace": tmp_path / "forbidden"}
        )
    assert render.call_count == 2
    assert not (tmp_path / "forbidden").exists()


def test_non_visual_source_does_not_publish_a_placeholder(monkeypatch, tmp_path):
    publisher, args, render, _, page = _case(monkeypatch, tmp_path)
    value = deepcopy(args["result"].model_dump(mode="json"))
    value["proposal"]["content"]["body"].pop()
    value["proposal"]["content_region_map"].pop()
    value["result_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "result_sha256"}
    )
    args["result"] = ExternalItemLearningResultV2.model_validate(value)
    assert owner.publish_creative_source_visuals(publisher, **args) is None
    publisher.find_published.assert_not_called()
    publisher.publish_first_observation.assert_not_called()
    render.assert_not_called()
    page.assert_not_called()


def test_source_revoked_after_render_never_publishes_crops(monkeypatch, tmp_path):
    publisher, args, render, _, _ = _case(monkeypatch, tmp_path)
    args["authorize_source"].side_effect = [None, ValueError("source revoked")]
    with pytest.raises(ValueError, match="source revoked"):
        owner.publish_creative_source_visuals(publisher, **args)
    render.assert_called_once()
    publisher.publish_first_observation.assert_not_called()
