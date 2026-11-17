"""Actual private request/image staging through the fixed CLI adapter, without model calls."""

import ast
import io
import json
import os
from copy import deepcopy
from types import SimpleNamespace

import pytest
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_kakao_archive_contracts import canonical_bytes
from eom_kakao_archive_contracts.concepts import parse_concept_request
from eom_orchestrator.control_models import (
    ExecutionBundleRevisionRecord,
    ResolvedExecutionPlanRecord,
)
from eom_orchestrator.control_service import ControlPlaneError
from eom_orchestrator.execution_materializer import (
    authorized_execution_artifact_revisions,
    materialize_execution_step,
    materialize_kakao_concept_sources,
)
from eom_orchestrator.models import ArtifactRecord, ArtifactRevisionRecord
from eom_orchestrator.worker_exec import (
    _encoded_image_dimensions,
    _load_image_inputs,
    codex_command,
)
from eom_workflow.control_schemas import CONTROL_SCHEMA_RESOURCES
from eom_workflow.kakao_concept_images import ConceptCodexImageManifest, concept_image_manifest
from eom_workflow.kakao_concept_request import KakaoConceptWork
from PIL import Image

from tests.unit.test_execution_materializer import FakeSession, _fixture
from tests.unit.test_kakao_concept_contracts import ROOT, compose_request, plan_request
from tests.unit.test_kakao_concept_workflow_contracts import plan_value, rehash, work_value

PLAN_ID = "execplan_" + "1" * 32


def image_bytes(fmt="PNG", *, size=(64, 48), mode="RGB", color="white", **options):
    output = io.BytesIO()
    Image.new(mode, size, color).save(output, format=fmt, **options)
    return output.getvalue()


def inputs(tmp_path, *, fmt="PNG", compose=True, root=None, **options):
    body = (compose_request() if compose else plan_request()).model_dump(mode="json")
    member = body["question"]["student"]["images"][0]["value"]["member"]
    payload = image_bytes(fmt, **options)
    member.update(
        relative_path=f"images/question.{fmt.lower()}",
        sha256=sha256_bytes(payload),
        size_bytes=len(payload),
        media_type={"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt],
    )
    files = {member["relative_path"]: payload}
    if compose:
        page = body["context"]["pages"][0]["member"]
        page_bytes = image_bytes(size=(800, 1000))
        page.update(sha256=sha256_bytes(page_bytes), size_bytes=len(page_bytes))
        files[page["relative_path"]] = page_bytes
        body["context"]["context_sha256"] = content_sha256(
            {key: value for key, value in body["context"].items() if key != "context_sha256"}
        )
    request = parse_concept_request(body)
    raw = canonical_bytes(request.model_dump(mode="json"))
    value = work_value(request)
    for file in value["files"]:
        if file["relative_path"].startswith("images/"):
            file.update(width_pixels=64, height_pixels=48)
    value["question_manifest"].update(
        artifact_id="artifact_" + "f" * 32, artifact_revision_id="rev_" + "f" * 32
    )
    value["request_member"].update(
        artifact_id="artifact_" + "e" * 32, artifact_revision_id="rev_" + "e" * 32
    )
    work = KakaoConceptWork.model_validate(value)
    root = root or (tmp_path / "artifacts").resolve()
    root.mkdir(exist_ok=True)
    records = {}
    for pointer, content in [
        (work.question_manifest, b"question is not worker input"),
        (work.request_member, raw),
        *((file.source, files[file.relative_path]) for file in work.files),
    ]:
        directory = root / pointer.artifact_id / pointer.artifact_revision_id
        path = directory / pointer.member_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        records[ArtifactRecord, pointer.artifact_id] = SimpleNamespace(approved=True)
        records[ArtifactRevisionRecord, pointer.artifact_revision_id] = SimpleNamespace(
            approved=True,
            logical_artifact_id=pointer.artifact_id,
            nas_path=str(directory),
            manifest={
                "files": [
                    dict(
                        file_name=pointer.member_path,
                        sha256=pointer.sha256,
                        bytes=len(content),
                        media_type=pointer.media_type,
                        schema_ref=pointer.schema_ref,
                    )
                ]
            },
        )
    return work, raw, files, root, FakeSession(records)


def stage(tmp_path, *, work, root, session, authorize=lambda _work: None, allowed=None):
    workspace = tmp_path / "worker"
    workspace.mkdir(mode=0o2770)
    workspace.chmod(0o2770)
    if allowed is None:
        allowed = frozenset(
            [
                work.question_manifest.artifact_revision_id,
                work.request_member.artifact_revision_id,
                *(file.source.artifact_revision_id for file in work.files),
            ]
        )
    result = materialize_kakao_concept_sources(
        session,
        work=work,
        workspace=workspace,
        artifact_root=root,
        worker_group_id=os.getgid(),
        authorized_artifact_revision_ids=allowed,
        authorize=authorize,
    )
    return workspace, result


def write_manifest(workspace, document):
    document = deepcopy(document)
    document["manifest_sha256"] = content_sha256(
        {key: value for key, value in document.items() if key != "manifest_sha256"}
    )
    path = workspace / "codex-image-inputs.json"
    path.write_bytes(canonical_json_bytes(document))
    path.chmod(0o640)
    return path


@pytest.mark.parametrize(
    "fmt,options",
    [
        ("PNG", {}),
        ("JPEG", {}),
        ("JPEG", {"progressive": True}),
        ("WEBP", {}),
        ("WEBP", {"lossless": True}),
        ("WEBP", {"mode": "RGBA", "color": (255, 255, 255, 128)}),
    ],
)
def test_original_question_and_textbook_bytes_reach_actual_cli_image_arguments(
    tmp_path, fmt, options
):
    work, raw, files, root, session = inputs(tmp_path, fmt=fmt, **options)
    calls = []
    workspace, result = stage(
        tmp_path, work=work, root=root, session=session, authorize=calls.append
    )
    assert calls == [work, work]
    assert result == (len(raw) + sum(map(len, files.values())), 1 + len(files))
    assert (workspace / "source/concepts/request.json").read_bytes() == raw
    assert not (workspace / "question").exists()
    manifest = concept_image_manifest(PLAN_ID, work)
    paths = _load_image_inputs(
        write_manifest(workspace, manifest.model_dump(mode="json")),
        workspace=workspace,
        group_id=os.getgid(),
        expected_plan_id=PLAN_ID,
    )
    assert len(paths) == 2
    assert [path.read_bytes() for path in paths] == list(files.values())
    command = codex_command(workspace, image_paths=paths)
    index = command.index("--image")
    assert command[index + 1 : index + 3] == tuple(map(str, paths))
    assert command[index + 3] == "--sandbox"
    assert all(path.stat().st_mode & 0o777 == 0o640 for path in paths)
    assert all("physical_page" not in image for image in manifest.model_dump(mode="json")["images"])


def test_schema_and_mirror_are_pinned_and_standalone_worker_has_no_package_imports():
    resource = CONTROL_SCHEMA_RESOURCES["codex-image-input-manifest-v6"]
    raw = (ROOT / resource.canonical_path).read_bytes()
    assert raw == (ROOT / "packages/workflow/eom_workflow" / resource.resource_path).read_bytes()
    assert sha256_bytes(raw) == resource.sha256
    tree = ast.parse((ROOT / "services/orchestrator/eom_orchestrator/worker_exec.py").read_text())
    imports = {
        node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    } | {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    assert not imports & {"PIL", "pydantic", "eom_workflow", "eom_kakao_archive_contracts"}


@pytest.mark.parametrize(
    "case",
    [
        "hash",
        "media",
        "dimensions",
        "frames",
        "orientation",
        "source-denied",
        "late-denied",
        "missing",
        "approval",
        "request-size",
        "request-extra-member",
        "symlink",
    ],
)
def test_core_rejects_bad_sources_before_worker_execution(tmp_path, case):
    options = {}
    if case == "orientation":
        exif = Image.Exif()
        exif[274] = 6
        options["exif"] = exif
    elif case == "frames":
        options.update(
            save_all=True, append_images=[Image.new("RGB", (64, 48), "black")], duration=100, loop=0
        )
    work, _, _, root, session = inputs(tmp_path, **options)
    pointer = work.files[0].source
    source = root / pointer.artifact_id / pointer.artifact_revision_id / pointer.member_path
    value = work.model_dump(mode="json")
    if case == "hash":
        source.write_bytes(source.read_bytes()[:-1] + b"x")
    elif case == "media":
        value["files"][0]["source"]["media_type"] = "image/jpeg"
    elif case == "dimensions":
        value["files"][0]["width_pixels"] = 65
    elif case == "missing":
        del session.records[ArtifactRevisionRecord, pointer.artifact_revision_id]
    elif case == "approval":
        session.records[ArtifactRevisionRecord, pointer.artifact_revision_id].approved = False
    elif case == "request-size":
        value["request_bytes"] += 1
    elif case == "request-extra-member":
        value["files"] = value["files"][:-1]
    elif case == "symlink":
        original = source.with_name("original-copy.png")
        source.rename(original)
        source.symlink_to(original)
    work = KakaoConceptWork.model_validate(value)
    calls = []

    def authorize(value):
        calls.append(value)
        if case == "late-denied" and len(calls) == 2:
            raise PermissionError("revoked after staging")

    with pytest.raises((ControlPlaneError, PermissionError)):
        stage(
            tmp_path,
            work=work,
            root=root,
            session=session,
            authorize=authorize,
            allowed=frozenset() if case == "source-denied" else None,
        )


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("input_index", True),
        ("input_index", 2),
        ("width_pixels", True),
        ("width_pixels", 65),
        ("relative_path", "source/concepts/files/../secret.png"),
        ("relative_path", "source/document/images/page-000001.png"),
        ("media_type", "image/gif"),
        ("media_type", {"unexpected": "object"}),
        ("sha256", "sha256:" + "0" * 64),
    ],
)
def test_fixed_worker_independently_rejects_invalid_manifest_entries(tmp_path, field, replacement):
    work, _, _, root, session = inputs(tmp_path)
    workspace, _ = stage(tmp_path, work=work, root=root, session=session)
    body = concept_image_manifest(PLAN_ID, work).model_dump(mode="json")
    body["images"][0][field] = replacement
    with pytest.raises(ValueError):
        _load_image_inputs(
            write_manifest(workspace, body),
            workspace=workspace,
            group_id=os.getgid(),
            expected_plan_id=PLAN_ID,
        )


@pytest.mark.parametrize(
    "case",
    [
        "duplicated",
        "bad-plan",
        "bad-hash",
        "empty",
        "extra",
        "bytes",
        "mode",
        "hardlink",
        "parent-symlink",
    ],
)
def test_fixed_worker_rejects_identity_file_and_closure_violations(tmp_path, case):
    work, _, _, root, session = inputs(tmp_path)
    workspace, _ = stage(tmp_path, work=work, root=root, session=session)
    body = concept_image_manifest(PLAN_ID, work).model_dump(mode="json")
    image = workspace / body["images"][0]["relative_path"]
    if case == "duplicated":
        body["images"][1] = {**body["images"][0], "input_index": 2}
    elif case == "bad-plan":
        body["plan_id"] = "execplan_" + "f" * 32
    elif case == "empty":
        body["images"] = []
    elif case == "extra":
        body["images"][0]["physical_page"] = 1
    elif case == "bytes":
        image.write_bytes(image.read_bytes() + b"extra")
    elif case == "mode":
        image.chmod(0o660)
    elif case == "hardlink":
        os.link(image, tmp_path / "alias.png")
    elif case == "parent-symlink":
        parent = image.parent
        target = parent.with_name("old-images")
        parent.rename(target)
        parent.symlink_to(target, target_is_directory=True)
    manifest = write_manifest(workspace, body)
    if case == "bad-hash":
        body["manifest_sha256"] = "sha256:" + "0" * 64
        manifest.write_text(json.dumps(body))
    with pytest.raises(ValueError):
        _load_image_inputs(
            manifest, workspace=workspace, group_id=os.getgid(), expected_plan_id=PLAN_ID
        )


def test_text_only_phase_stages_no_images_or_manifest(tmp_path):
    body = plan_request().model_dump(mode="json")
    body["question"]["student"]["images"] = []
    body["question"]["student"]["ordered_blocks"] = body["question"]["student"]["ordered_blocks"][
        :1
    ]
    work = KakaoConceptWork.model_validate(work_value(parse_concept_request(body)))
    assert concept_image_manifest(PLAN_ID, work) is None


@pytest.mark.parametrize("compose", [False, True])
def test_full_execution_materializer_uses_its_existing_instruction_and_invocation_owners(
    tmp_path, monkeypatch, compose
):
    base = _fixture(tmp_path, monkeypatch)
    work, raw, files, root, session = inputs(
        tmp_path, compose=compose, fmt="JPEG", root=base["artifact_root"]
    )
    old_record = base["session"].records[ResolvedExecutionPlanRecord, base["plan_id"]]
    plan = plan_value()
    plan["work_input"] = work.model_dump(mode="json")
    plan["steps"][0]["instruction_bundle"] = old_record.canonical_document["steps"][0][
        "instruction_bundle"
    ]
    instruction = plan["steps"][0]["instruction_bundle"]
    base["session"].records[
        ExecutionBundleRevisionRecord, instruction["bundle_revision_id"]
    ].manifest_artifact_revision_id = instruction["manifest_artifact"]["artifact_revision_id"]
    plan = rehash(plan)
    base["session"].records.update(session.records)
    base["session"].records[ResolvedExecutionPlanRecord, PLAN_ID] = SimpleNamespace(
        canonical_document=plan, plan_sha256=plan["plan_sha256"]
    )
    calls = []
    arguments = dict(plan_id=PLAN_ID, step_key="assist", kakao_concept_authorize=calls.append)
    allowed = authorized_execution_artifact_revisions(base["session"], **arguments)
    assert calls == [work, work]
    assert work.request_member.artifact_revision_id in allowed
    workspace = tmp_path / "worker"
    workspace.mkdir(mode=0o2770)
    workspace.chmod(0o2770)
    execution = materialize_execution_step(
        base["session"],
        **arguments,
        workspace=workspace,
        canonical_artifact_root=root,
        worker_group_id=os.getgid(),
        authorized_artifact_revision_ids=allowed,
    )
    assert execution.source_sha256 == work.request_member.sha256
    assert execution.image_input_manifest_sha256 is not None
    assert (workspace / "source/concepts/request.json").read_bytes() == raw
    assert len(
        _load_image_inputs(
            workspace / "codex-image-inputs.json",
            workspace=workspace,
            group_id=os.getgid(),
            expected_plan_id=PLAN_ID,
        )
    ) == len(files)
    assert work.question_manifest.member_path not in {
        str(path.relative_to(workspace)) for path in workspace.rglob("*")
    }
    assert json.loads(execution.invocation_path.read_bytes())["model"] == plan["steps"][0]["model"]
    with pytest.raises(ControlPlaneError, match="source owner"):
        authorized_execution_artifact_revisions(base["session"], plan_id=PLAN_ID, step_key="assist")


@pytest.mark.parametrize("case", ["hash", "duplicate", "order", "pixels", "bytes"])
def test_typed_image_manifest_rejects_bad_invariants(tmp_path, case):
    work, _, _, _, _ = inputs(tmp_path)
    body = concept_image_manifest(PLAN_ID, work).model_dump(mode="json")
    if case == "hash":
        body["manifest_sha256"] = "sha256:" + "0" * 64
    elif case == "duplicate":
        body["images"][1]["relative_path"] = body["images"][0]["relative_path"]
    elif case == "order":
        body["images"].reverse()
    elif case == "pixels":
        body["images"][0].update(width_pixels=30000, height_pixels=30000)
    else:
        body["images"][0]["bytes"] = 64 * 1024 * 1024 + 1
    with pytest.raises(ValueError):
        ConceptCodexImageManifest.model_validate(body)


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_bounded_header_reader_rejects_wrong_media_and_truncated_headers(fmt):
    payload = image_bytes(fmt)
    media = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}[fmt]
    assert _encoded_image_dimensions(payload, media) == (64, 48)
    for truncated in (b"", payload[:2], payload[:15]):
        with pytest.raises(ValueError):
            _encoded_image_dimensions(truncated, media)
    with pytest.raises(ValueError):
        _encoded_image_dimensions(payload, "image/gif")


@pytest.mark.parametrize(
    "case", ["animation", "riff-length", "chunk-overrun", "frame-duplicate", "canvas-mismatch"]
)
def test_webp_header_cannot_hide_animation_or_different_dimensions(case):
    if case == "animation":
        payload = image_bytes(
            "WEBP",
            save_all=True,
            append_images=[Image.new("RGB", (64, 48), "black")],
            duration=100,
            loop=0,
        )
    else:
        payload = bytearray(image_bytes("WEBP"))
        if case == "riff-length":
            payload[4:8] = (len(payload) + 8).to_bytes(4, "little")
        elif case == "chunk-overrun":
            payload[16:20] = (len(payload) + 8).to_bytes(4, "little")
        elif case == "frame-duplicate":
            payload.extend(payload[12:])
            payload[4:8] = (len(payload) - 8).to_bytes(4, "little")
        else:
            canvas = (
                b"VP8X"
                + (10).to_bytes(4, "little")
                + b"\x00" * 4
                + (65).to_bytes(3, "little")
                + (47).to_bytes(3, "little")
            )
            payload = bytearray(payload[:12] + canvas + payload[12:])
            payload[4:8] = (len(payload) - 8).to_bytes(4, "little")
    with pytest.raises(ValueError):
        _encoded_image_dimensions(bytes(payload), "image/webp")


def test_duplicate_staging_never_authorizes_overwrite(tmp_path):
    work, _, _, root, session = inputs(tmp_path)
    workspace, _ = stage(tmp_path, work=work, root=root, session=session)
    old_bytes = (workspace / "source/concepts/request.json").read_bytes()
    allowed = frozenset(
        [
            work.question_manifest.artifact_revision_id,
            work.request_member.artifact_revision_id,
            *(file.source.artifact_revision_id for file in work.files),
        ]
    )
    with pytest.raises(ControlPlaneError):
        materialize_kakao_concept_sources(
            session,
            work=work,
            workspace=workspace,
            artifact_root=root,
            worker_group_id=os.getgid(),
            authorized_artifact_revision_ids=allowed,
            authorize=lambda _work: None,
        )
    assert (workspace / "source/concepts/request.json").read_bytes() == old_bytes
