"""Bounded page materialization uses the existing immutable pointer checks."""

import os
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.material_learning import MaterialDiscoveryWork
from eom_identifiers import content_sha256, sha256_bytes
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import materialize_material_learning_sources
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord

from tests.unit.test_execution_materializer import FakeSession
from tests.unit.test_material_learning_contracts import work
from tests.unit.test_worker_systemd import _png_header


def fixture(tmp_path):
    body, records, originals = work(), {}, []
    root = (tmp_path / "nas").resolve()
    for page in body["pages"]:
        page["text"] = None
        image = page["image"]
        image.update(
            media_type="image/png", schema_ref="eom://schemas/educational-document/page-image/1.0"
        )
        image["member_path"] = f"analysis/images/page-{page['physical_page']:06d}.png"
        revision_root = root / image["artifact_id"] / image["artifact_revision_id"]
        path = revision_root / image["member_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = _png_header(page["width_pixels"], page["height_pixels"]) + bytes(
            [page["input_index"]]
        )
        path.write_bytes(payload)
        image.update(bytes=len(payload), sha256=sha256_bytes(payload))
        originals.append(path)
        records[(ArtifactRecord, image["artifact_id"])] = SimpleNamespace(approved=True)
        key = (ArtifactRevisionRecord, image["artifact_revision_id"])
        if key not in records:
            records[key] = SimpleNamespace(
                approved=True,
                logical_artifact_id=image["artifact_id"],
                nas_path=str(revision_root),
                manifest={"files": []},
            )
        records[key].manifest["files"].append(
            {
                "file_name": image["member_path"],
                **{
                    field: image[field] for field in ("sha256", "bytes", "media_type", "schema_ref")
                },
            }
        )
    body["input_sha256"] = content_sha256(
        {key: value for key, value in body.items() if key != "input_sha256"}
    )
    return MaterialDiscoveryWork.model_validate(body), root, FakeSession(records), originals


@pytest.mark.parametrize("case", ["success", "missing", "hash", "denied"])
def test_only_selected_verified_images_are_copied(tmp_path, case):
    selected, root, session, originals = fixture(tmp_path)
    workspace = tmp_path / "worker"
    workspace.mkdir(mode=0o2770)
    workspace.chmod(0o2770)
    allowed = frozenset(page.image.artifact_revision_id for page in selected.pages)
    if case == "hash":
        originals[0].write_bytes(originals[0].read_bytes() + b"corrupted")
    elif case == "missing":
        del session.records[(ArtifactRevisionRecord, selected.pages[0].image.artifact_revision_id)]
    elif case == "denied":
        allowed = frozenset()
    arguments = dict(
        work=selected,
        workspace=workspace,
        artifact_root=root,
        worker_group_id=os.getgid(),
        authorized_artifact_revision_ids=allowed,
    )
    if case != "success":
        with pytest.raises(ControlPlaneError):
            materialize_material_learning_sources(session, **arguments)
        return
    byte_count, members = materialize_material_learning_sources(session, **arguments)
    assert members == 2
    assert byte_count == sum(page.image.bytes for page in selected.pages)
    assert not list(workspace.rglob("*.pdf"))
    for page, original in zip(selected.pages, originals, strict=True):
        assert (
            workspace / f"source/material/main/page-{page.physical_page:06d}.png"
        ).read_bytes() == original.read_bytes()
