"""Real local rendering plus adversarial owner acceptance; privileged unit test remains separate."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pymupdf
import pytest
from eom_kakao_archive_contracts import canonical_bytes, sha256
from eom_kakao_archive_contracts.validation import validate_contract
from eom_orchestrator.kakao_pdf_execution import KakaoPdfExecutor
from eom_orchestrator.kakao_pdf_files import KakaoPdfExecutionError, read_pinned
from PIL import Image

from tests.unit.test_kakao_question_render import RELEASE, identity, local_file
from tests.unit.test_kakao_question_render import prepared as prepared


class LocalProcess:
    """Tests same-user subprocess transport, not proof of production Linux isolation."""

    def __init__(self, mutate=None):
        self.calls = 0
        self.mutate = mutate

    def run(self, command, workspace):
        self.calls += 1
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "eom_kakao_archive_worker.cli",
                "--input-root",
                str(workspace / "input"),
                "--output-root",
                str(workspace / "output"),
                "--renderer-release-sha256",
                RELEASE,
            ],
            input=canonical_bytes(command.model_dump(mode="json")),
            capture_output=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode in (0, 1), completed.stderr
        (workspace / "output" / "result.json").write_bytes(completed.stdout)
        (workspace / "output" / "result.json").chmod(0o640)
        if self.mutate:
            self.mutate(command, workspace)


def executor(tmp_path, launcher=None, callback=None):
    root = tmp_path / "workspaces"
    root.mkdir(mode=0o700)
    return KakaoPdfExecutor(
        root,
        os.getuid(),
        os.getgid(),
        launcher or LocalProcess(),
        callback or (lambda command: None),
    )


def _result_edit(workspace, edit):
    path = workspace / "output" / "result.json"
    value = json.loads(path.read_bytes())
    edit(value)
    path.write_bytes(canonical_bytes(value))


def test_actual_process_photo_text_korean_outputs_are_pinned_and_core_staged(prepared, tmp_path):
    source, _, prepare = prepared
    picture = io.BytesIO()
    Image.new("RGB", (400, 300), (90, 120, 160)).save(picture, format="PNG")
    photo = local_file(source, "photo.png", picture.getvalue(), "image/png")

    def change(manifest):
        manifest["questions"][0]["images"].append(
            {
                "attachment_occurrence_id": identity("attachment"),
                "attachment_revision_id": identity("attachmentrev"),
                "member": photo,
                "availability": "AVAILABLE",
                "quality_accepted": True,
            }
        )

    command = prepare(change)
    launcher = LocalProcess()
    checks = []
    execution = executor(tmp_path, launcher, lambda command: checks.append(command.execution.fence))
    accepted = execution.execute(command, source_root=source)
    assert launcher.calls == 1 and checks == [1] * 4
    assert accepted.result.status == "COMPLETED" and accepted.result.page_count == 1
    assert accepted.staging_root is not None
    assert str(accepted.staging_root) not in repr(accepted)
    assert accepted.layout.pages[0].image_blocks[0].crop is None
    for member in accepted.files:
        raw = read_pinned(accepted.staging_root, member, uid=os.getuid(), gid=os.getgid())
        assert sha256(raw) == member.sha256
    with pymupdf.open(accepted.staging_root / "report.pdf") as pdf:
        assert "질문입니다" in pdf[0].get_text() and len(pdf[0].get_image_info()) == 1
    # Dispatch replay never invokes a second worker or replaces accepted bytes.
    with pytest.raises(KakaoPdfExecutionError, match="ATTEMPT_ALREADY_STAGED"):
        execution.execute(command, source_root=source)
    assert launcher.calls == 1


@pytest.mark.parametrize(
    "which", ["export", "command", "manifest", "attempt", "task", "fence", "number"]
)
def test_result_exact_pins_reject_foreign_or_stale_execution(prepared, tmp_path, which):
    source, _, prepare = prepared
    command = prepare()

    def mutate(command, workspace):
        def edit(value):
            if which == "export":
                value["export_id"] = identity("export", 2)
            elif which in {"command", "manifest"}:
                value[which + "_sha256"] = "sha256:" + "0" * 64
            else:
                key = {
                    "attempt": "attempt_id",
                    "task": "task_id",
                    "number": "attempt_number",
                    "fence": "fence",
                }[which]
                value["execution"][key] = identity(which, 2) if which in {"attempt", "task"} else 2

        _result_edit(workspace, edit)

    execution = executor(tmp_path, LocalProcess(mutate))
    with pytest.raises(KakaoPdfExecutionError, match="PINS_MISMATCH"):
        execution.execute(command, source_root=source)
    assert (
        execution.workspace_root / command.execution.attempt_id / "output" / "report.pdf"
    ).exists()
    assert not (execution.workspace_root / command.execution.attempt_id / "accepted").exists()


@pytest.mark.parametrize("at", [1, 2, 3, 4])
def test_current_claim_is_required_before_and_after_local_side_effects(prepared, tmp_path, at):
    source, _, prepare = prepared
    command = prepare()
    count = 0

    def current(command):
        nonlocal count
        count += 1
        if count == at:
            raise KakaoPdfExecutionError("KAKAO_PDF_CLAIM_STALE")

    launcher = LocalProcess()
    execution = executor(tmp_path, launcher, current)
    with pytest.raises(KakaoPdfExecutionError, match="CLAIM_STALE"):
        execution.execute(command, source_root=source)
    assert launcher.calls == (1 if at >= 3 else 0)
    if at >= 3:
        assert (
            execution.workspace_root / command.execution.attempt_id / "output" / "result.json"
        ).exists()


@pytest.mark.parametrize(
    "mutation", ["hash", "missing", "symlink", "hardlink", "extra", "duplicate", "size", "owner"]
)
def test_untrusted_output_descriptors_and_closure_rejected(prepared, tmp_path, mutation):
    source, _, prepare = prepared
    command = prepare()

    def mutate(command, workspace):
        pdf = workspace / "output" / "report.pdf"
        if mutation == "hash":
            raw = pdf.read_bytes()
            pdf.write_bytes(raw[:-1] + b"x")
        elif mutation == "missing":
            pdf.unlink()
        elif mutation == "symlink":
            pdf.unlink()
            pdf.symlink_to(source / "font.otf")
        elif mutation == "hardlink":
            os.link(pdf, workspace / "linked")
        elif mutation == "extra":
            (workspace / "output" / "personal.txt").write_text("not publishable")
        elif mutation == "duplicate":
            _result_edit(
                workspace, lambda result: result["outputs"].__setitem__(1, result["outputs"][0])
            )
        elif mutation == "size":
            pdf.write_bytes(b"%PDF-")

    execution = executor(tmp_path, LocalProcess(mutate))
    if mutation == "owner":
        execution = KakaoPdfExecutor(
            execution.workspace_root,
            os.getuid() + 1,
            os.getgid(),
            execution.launcher,
            execution.assert_current,
        )
    with pytest.raises(KakaoPdfExecutionError):
        execution.execute(command, source_root=source)


@pytest.mark.parametrize(
    "mutation",
    ["source-hash", "source-symlink", "source-hardlink", "source-world-write", "root-symlink"],
)
def test_unsafe_source_never_launches_worker(prepared, tmp_path, mutation):
    source, _, prepare = prepared
    command = prepare()
    font = source / "font.otf"
    if mutation == "source-hash":
        raw = font.read_bytes()
        font.write_bytes(raw[:-1] + b"x")
    elif mutation == "source-symlink":
        font.rename(source / "real.otf")
        font.symlink_to(source / "real.otf")
    elif mutation == "source-hardlink":
        os.link(font, source / "linked.otf")
    elif mutation == "source-world-write":
        font.chmod(0o666)
    else:
        link = tmp_path / "linked-input"
        link.symlink_to(source, target_is_directory=True)
        source = link
    launcher = LocalProcess()
    execution = executor(tmp_path, launcher)
    with pytest.raises(KakaoPdfExecutionError):
        execution.execute(command, source_root=source)
    assert launcher.calls == 0


def test_interrupted_attempt_and_partial_output_are_preserved_not_replayed(prepared, tmp_path):
    source, _, prepare = prepared
    command = prepare()

    class Interrupted:
        calls = 0

        def run(self, command, workspace):
            self.calls += 1
            (workspace / "output" / "partial.pdf").write_bytes(b"%PDF-")
            raise KakaoPdfExecutionError("KAKAO_PDF_EXECUTION_UNCERTAIN")

    launcher = Interrupted()
    execution = executor(tmp_path, launcher)
    with pytest.raises(KakaoPdfExecutionError, match="UNCERTAIN"):
        execution.execute(command, source_root=source)
    with pytest.raises(KakaoPdfExecutionError, match="ALREADY_STAGED"):
        execution.execute(command, source_root=source)
    assert launcher.calls == 1
    assert (
        execution.workspace_root / command.execution.attempt_id / "output" / "partial.pdf"
    ).read_bytes() == b"%PDF-"


def test_layout_refusal_returns_no_publishable_files(prepared, tmp_path):
    source, _, prepare = prepared
    command = prepare(
        lambda manifest: manifest["questions"][0]["text_blocks"].__setitem__(
            0, {"span_id": "too-long", "text": "한글 질문 " * 1500}
        )
    )
    execution = executor(tmp_path)
    result = execution.execute(command, source_root=source)
    assert result.result.status == "NEEDS_LAYOUT_REVIEW"
    assert result.staging_root is None and not result.files


@pytest.mark.parametrize("which", ["text", "image", "font", "page", "bounds"])
def test_hash_correct_layout_receipt_still_must_preserve_source(prepared, tmp_path, which):
    source, _, prepare = prepared
    command = prepare()

    def mutate(command, workspace):
        path = workspace / "output" / "layout.json"
        value = json.loads(path.read_bytes())
        if which == "text":
            value["pages"][0]["text_blocks"][0]["start_codepoint"] = 1
        elif which == "image":
            value["pages"][0]["image_blocks"] = [
                {
                    "attachment_occurrence_id": identity("attachment"),
                    "attachment_revision_id": identity("attachmentrev"),
                    "source_sha256": None,
                    "display_transform": None,
                    "availability": "MISSING",
                    "bounds_pt": [40, 100, 200, 300],
                    "crop": None,
                }
            ]
        elif which == "font":
            value["font_sha256"] = "sha256:" + "0" * 64
        elif which == "page":
            value["pages"][0]["question_revision_id"] = identity("questionrev", 2)
        else:
            value["pages"][0]["text_blocks"][0]["bounds_pt"] = [0, 1, 3, 4]
        raw = canonical_bytes(value)
        path.write_bytes(raw)

        def edit(result):
            for member in result["outputs"]:
                if member["relative_path"] == "layout.json":
                    member.update(size_bytes=len(raw), sha256=sha256(raw))

        _result_edit(workspace, edit)

    with pytest.raises(KakaoPdfExecutionError):
        executor(tmp_path, LocalProcess(mutate)).execute(command, source_root=source)


def test_execution_schema_and_model_reject_boolean_fence(prepared):
    _, _, prepare = prepared
    value = prepare().model_dump(mode="json")
    value["execution"]["fence"] = True
    with pytest.raises(ValueError):
        validate_contract("command", value)
    with pytest.raises(ValueError):
        type(prepare()).model_validate(value)


def test_worker_and_owner_import_boundaries_have_no_publication_or_network():
    import ast

    for root, forbidden in (
        (
            Path("services/kakao_archive_worker"),
            {
                "eom_catalog_service",
                "sqlalchemy",
                "httpx",
                "requests",
                "socket",
                "eom_orchestrator",
            },
        ),
        (
            Path("services/orchestrator/eom_orchestrator"),
            {"eom_kakao_archive_worker", "eom_catalog_service"},
        ),
    ):
        files = root.rglob("*.py") if "worker" in str(root) else root.glob("kakao_pdf_*.py")
        for source in files:
            tree = ast.parse(source.read_text())
            for node in ast.walk(tree):
                names = (
                    [node.module or ""]
                    if isinstance(node, ast.ImportFrom)
                    else [alias.name for alias in node.names]
                    if isinstance(node, ast.Import)
                    else []
                )
                assert not any(name.split(".")[0] in forbidden for name in names), source


def test_finished_recovery_never_rerenders_and_reuses_matching_core_files(prepared, tmp_path):
    source, _, prepare = prepared
    command = prepare()
    launcher = LocalProcess()
    execution = executor(tmp_path, launcher)
    first = execution.execute(command, source_root=source)
    original = first.staging_root / "report.pdf"
    inode = original.stat().st_ino
    stopped = []
    recovered = execution.recover_finished(
        command, assert_stopped=lambda request, path: stopped.append((request.execution, path.name))
    )
    assert stopped == [(command.execution, command.execution.attempt_id)]
    assert recovered == first and launcher.calls == 1
    assert original.stat().st_ino == inode


@pytest.mark.parametrize("partial", [False, True])
def test_finished_recovery_after_owner_interruption_can_complete_partial_copy(
    prepared, tmp_path, partial
):
    source, _, prepare = prepared
    command = prepare()
    launcher = LocalProcess()
    count = 0

    def current(command):
        nonlocal count
        count += 1
        if count == (4 if partial else 3):
            raise KakaoPdfExecutionError("KAKAO_PDF_OWNER_INTERRUPTED")

    execution = executor(tmp_path, launcher, current)
    with pytest.raises(KakaoPdfExecutionError, match="OWNER_INTERRUPTED"):
        execution.execute(command, source_root=source)
    if partial:
        (
            execution.workspace_root / command.execution.attempt_id / "accepted" / "page-0001.png"
        ).unlink()
    resumed = KakaoPdfExecutor(
        execution.workspace_root,
        execution.worker_uid,
        execution.shared_gid,
        launcher,
        lambda command: None,
    )
    accepted = resumed.recover_finished(command, assert_stopped=lambda command, path: None)
    assert accepted.result.status == "COMPLETED" and launcher.calls == 1
    assert len(list(accepted.staging_root.iterdir())) == 3


def test_recovery_requires_owner_stop_observation_and_current_original_fence(prepared, tmp_path):
    source, _, prepare = prepared
    command = prepare()
    launcher = LocalProcess()
    execution = executor(tmp_path, launcher)
    execution.execute(command, source_root=source)

    def running(command, path):
        raise KakaoPdfExecutionError("KAKAO_PDF_ORIGINAL_STILL_RUNNING")

    with pytest.raises(KakaoPdfExecutionError, match="STILL_RUNNING"):
        execution.recover_finished(command, assert_stopped=running)
    changed = command.model_copy(
        update={"execution": command.execution.model_copy(update={"fence": 2})}
    )
    with pytest.raises(KakaoPdfExecutionError, match="RECOVERY_PINS_MISMATCH"):
        execution.recover_finished(changed, assert_stopped=lambda command, path: None)
    assert launcher.calls == 1


@pytest.mark.parametrize("bad", ["accepted-hash", "accepted-link", "extra", "input-hash"])
def test_recovery_does_not_overwrite_or_ignore_changed_previous_files(prepared, tmp_path, bad):
    source, _, prepare = prepared
    command = prepare()
    launcher = LocalProcess()
    execution = executor(tmp_path, launcher)
    first = execution.execute(command, source_root=source)
    workspace = execution.workspace_root / command.execution.attempt_id
    pdf = first.staging_root / "report.pdf"
    if bad == "accepted-hash":
        pdf.write_bytes(b"corrupted-owner-file")
    elif bad == "accepted-link":
        os.link(pdf, tmp_path / "hardlinked.pdf")
    elif bad == "extra":
        (first.staging_root / "extra.txt").write_text("unrecognized")
    else:
        font = workspace / "input" / "font.otf"
        font.write_bytes(b"changed")
    with pytest.raises(KakaoPdfExecutionError):
        execution.recover_finished(command, assert_stopped=lambda command, path: None)
    assert launcher.calls == 1
    if bad == "accepted-hash":
        assert pdf.read_bytes() == b"corrupted-owner-file"
