from __future__ import annotations

import io
import json
from contextlib import contextmanager

import pytest
from eom_image_contracts import InformativeLineartExtractionRuntime, content_json_bytes
from eom_image_provider import informative_lineart_extraction as execution
from eom_image_provider import informative_lineart_installation as installation
from eom_image_provider.provider import ProviderError
from PIL import Image, ImageOps

from tests.unit.test_informative_lineart_extraction_contracts import _command, _runtime


def _png(mode="L", size=(832, 512)):
    stream = io.BytesIO()
    Image.new(mode, size, 255).save(stream, format="PNG")
    return stream.getvalue()


class FakeBackend:
    def __init__(self, *, fail=None, malformed=None, peak=100):
        self.opened = 0
        self.calls = 0
        self.runtime = InformativeLineartExtractionRuntime.model_validate(_runtime())
        self.fail, self.malformed, self.peak = fail, malformed, peak

    @contextmanager
    def open(self, material):
        self.opened += 1
        yield self

    def extract(self, fitted):
        self.calls += 1
        with Image.open(io.BytesIO(fitted)) as source:
            assert source.mode == "RGB" and source.size == (832, 512)
        if self.fail == self.calls:
            raise ProviderError("LINEART_EXTRACTION_OOM")
        payload = _png() if self.malformed is None else self.malformed
        return execution.ExtractedLineart(payload, self.peak)


def _workspace(monkeypatch, tmp_path):
    command, baseline, manifest, records = _command()
    workspace = tmp_path / "workspace"
    workspace.mkdir(mode=0o700)
    (workspace / "inputs").mkdir(mode=0o700)
    (workspace / "command.json").write_bytes(content_json_bytes(command.model_dump(mode="json")))
    (workspace / "inputs/baseline-command.json").write_bytes(
        content_json_bytes(baseline.model_dump(mode="json"))
    )
    (workspace / "inputs/extractor-manifest.json").write_bytes(
        content_json_bytes(manifest.model_dump(mode="json"))
    )
    for case in baseline.cases:
        (workspace / case.staged_member_path).write_bytes(records[case.reference_image])
    for path in workspace.rglob("*"):
        if path.is_file():
            path.chmod(0o600)
    monkeypatch.setattr(
        execution, "resolve_informative_lineart_material", lambda *args, **kwargs: object()
    )
    leases = []

    @contextmanager
    def lease(_path):
        leases.append(True)
        yield

    monkeypatch.setattr(execution, "acquire_gpu_lease", lease)
    return command, workspace, leases


def _run(command, workspace, backend):
    return execution.run_informative_lineart_extraction(
        command=command,
        model_store_root=workspace / "unused-store",
        workspace=workspace,
        gpu_lock=workspace / "unused-lock",
        backend=backend,
    )


def test_raw_and_inverted_outputs_keep_original_identity_and_replay_without_gpu(
    monkeypatch, tmp_path
):
    command, workspace, leases = _workspace(monkeypatch, tmp_path)
    backend = FakeBackend()
    result = _run(command, workspace, backend)
    assert result.status == "SUCCEEDED" and len(result.outputs) == len(command.case_ids)
    assert backend.opened == 1 and backend.calls == len(command.case_ids) and len(leases) == 1
    for output in result.outputs:
        with (
            Image.open(workspace / output.lineart_member_path) as raw,
            Image.open(workspace / output.conditioning_member_path) as conditioning,
        ):
            assert raw.mode == "L" and conditioning.mode == "RGB"
            assert conditioning.tobytes() == ImageOps.invert(raw).convert("RGB").tobytes()
    # Replay must not inspect/load the model or acquire the GPU, even if the model is unavailable.
    monkeypatch.setattr(
        execution,
        "resolve_informative_lineart_material",
        lambda *args, **kwargs: pytest.fail("replay resolved model"),
    )
    assert _run(command, workspace, backend) == result
    assert backend.opened == 1 and len(leases) == 1


@pytest.mark.parametrize(
    "fault", ["command", "baseline", "manifest", "input", "link", "hardlink", "partial"]
)
def test_untrusted_or_unreceipted_inputs_fail_before_model_or_gpu(monkeypatch, tmp_path, fault):
    command, workspace, leases = _workspace(monkeypatch, tmp_path)
    target = next((workspace / "inputs").glob("*.png"))
    if fault in {"command", "baseline", "manifest"}:
        name = {
            "command": "command.json",
            "baseline": "inputs/baseline-command.json",
            "manifest": "inputs/extractor-manifest.json",
        }[fault]
        (workspace / name).write_bytes(b"{}")
    elif fault == "input":
        target.write_bytes(b"not PNG")
    elif fault == "link":
        target.unlink()
        target.symlink_to(workspace / "command.json")
    elif fault == "hardlink":
        import os

        os.link(target, workspace / "linked.png")
    else:
        (workspace / "outputs").mkdir(mode=0o700)
    backend = FakeBackend()
    monkeypatch.setattr(
        execution,
        "resolve_informative_lineart_material",
        lambda *args, **kwargs: pytest.fail("invalid input resolved model"),
    )
    with pytest.raises(ProviderError):
        _run(command, workspace, backend)
    assert backend.opened == 0 and not leases


def test_terminal_failure_keeps_only_completed_prefix_and_never_auto_retries(monkeypatch, tmp_path):
    command, workspace, leases = _workspace(monkeypatch, tmp_path)
    backend = FakeBackend(fail=2)
    result = _run(command, workspace, backend)
    assert result.status == "FAILED" and result.error_code == "LINEART_EXTRACTION_OOM"
    assert tuple(output.case_id for output in result.outputs) == command.case_ids[:1]
    assert _run(command, workspace, backend) == result
    assert backend.calls == 2 and len(leases) == 1


@pytest.mark.parametrize(
    "payload", [b"not PNG", _png("RGB"), _png(size=(800, 500))], ids=["invalid", "rgb", "size"]
)
def test_backend_malformed_png_has_no_accepted_output(monkeypatch, tmp_path, payload):
    command, workspace, _ = _workspace(monkeypatch, tmp_path)
    result = _run(command, workspace, FakeBackend(malformed=payload))
    assert result.status == "FAILED" and result.error_code == "LINEART_EXTRACTION_OUTPUT_INVALID"
    assert result.outputs == ()


def test_memory_budget_cannot_publish_over_budget_output(monkeypatch, tmp_path):
    command, workspace, _ = _workspace(monkeypatch, tmp_path)
    result = _run(
        command, workspace, FakeBackend(peak=command.budget.maximum_peak_gpu_memory_bytes + 1)
    )
    assert result.status == "FAILED" and result.error_code == "LINEART_EXTRACTION_BUDGET_EXCEEDED"
    assert (
        result.outputs == ()
        and result.peak_gpu_memory_bytes > command.budget.maximum_peak_gpu_memory_bytes
    )


@pytest.mark.parametrize("fault", ["bytes", "receipt", "missing", "link"])
def test_tampered_replay_is_explicit_error_not_regeneration(monkeypatch, tmp_path, fault):
    command, workspace, leases = _workspace(monkeypatch, tmp_path)
    backend = FakeBackend()
    result = _run(command, workspace, backend)
    member = workspace / result.outputs[0].lineart_member_path
    if fault == "bytes":
        member.write_bytes(b"changed")
    elif fault == "receipt":
        value = json.loads((workspace / "result.json").read_bytes())
        value["outputs"].pop()
        (workspace / "result.json").write_bytes(content_json_bytes(value))
    elif fault == "missing":
        member.unlink()
    else:
        member.unlink()
        member.symlink_to(workspace / "command.json")
    with pytest.raises(ProviderError, match="LINEART_EXTRACTION_OUTPUT_INVALID"):
        _run(command, workspace, backend)
    assert backend.opened == 1 and len(leases) == 1


def test_new_unit_is_offline_same_worker_same_exclusive_gpu_boundary():
    from pathlib import Path

    raw = (
        Path(__file__).parents[2]
        / "infra/systemd/eom-image-informative-lineart-extraction@.service"
    ).read_text()
    for invariant in (
        "User=eom-image",
        "Group=eom-image",
        "PrivateNetwork=true",
        "ProtectHome=true",
        "NoNewPrivileges=true",
        "InaccessiblePaths=/mnt/nas",
        "InaccessiblePaths=/home/eom/EOM",
        "InaccessiblePaths=/home/eom/EOMIS",
        "InaccessiblePaths=/root/.codex",
        "--gpu-lock /var/lib/eom-image/gpu0.lock",
        "Restart=no",
        "TimeoutStartSec=630",
    ):
        assert invariant in raw
    assert "eom-image-trainer/bin/eom-local-image informative-lineart-extraction" in raw


def test_model_install_requires_operator_not_worker(tmp_path):
    command, _, _, _ = _command()
    with pytest.raises(ProviderError, match="REQUIRES_OPERATOR"):
        installation.install_informative_lineart_revision(
            source=tmp_path,
            model_store_root=tmp_path,
            pointer=command.extractor,
            source_owner_uid=0,
            worker_group_gid=0,
        )


@pytest.mark.parametrize(
    "fault", ["pointer", "canonical", "schema", "extra", "license", "config", "link"]
)
def test_bad_install_metadata_fails_before_protected_store_mutation(monkeypatch, tmp_path, fault):
    import os

    from tests.unit.test_informative_lineart_runtime import _manifest, _members, _pointer

    original_uid = os.geteuid()
    members = _members()
    manifest = _manifest(members)
    pointer = _pointer(manifest)
    source = tmp_path / "source"
    source.mkdir(mode=0o700)
    store = tmp_path / "store"
    store.mkdir(mode=0o700)
    raw = content_json_bytes(manifest.model_dump(mode="json"))
    if fault == "pointer":
        pointer = pointer.model_copy(update={"manifest_sha256": "sha256:" + "1" * 64})
    elif fault == "canonical":
        raw += b"\n"
    elif fault == "schema":
        raw = b"{}"
    elif fault == "extra":
        members["unexpected.txt"] = b"unexpected"
    elif fault in {"license", "config"}:
        members["LICENSE" if fault == "license" else "config.json"] = b"wrong"
    for name, payload in {**members, "manifest.json": raw}.items():
        (source / name).write_bytes(payload)
        (source / name).chmod(0o600)
    if fault == "link":
        (source / "manifest.json").unlink()
        (source / "manifest.json").symlink_to(source / "config.json")
    monkeypatch.setattr(installation.os, "geteuid", lambda: 0)
    monkeypatch.setattr(
        installation,
        "_directory",
        lambda *args, **kwargs: pytest.fail("invalid metadata reached protected store"),
    )
    with pytest.raises(ProviderError):
        installation.install_informative_lineart_revision(
            source=source,
            model_store_root=store,
            pointer=pointer,
            source_owner_uid=original_uid,
            worker_group_gid=os.getegid(),
        )
    assert not tuple(store.iterdir())
