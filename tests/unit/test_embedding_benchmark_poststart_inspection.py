"""Synthetic current-file/root-origin fences; no production identity, DB, model or unit actions."""

import os

import pytest
from eom_catalog_contracts.embedding_benchmark_poststart_failure import (
    benchmark_poststart_failure_bytes,
)
from eom_catalog_service import embedding_benchmark_poststart_inspection as module
from eom_identifiers import sha256_bytes

from tests.unit.embedding_benchmark_poststart_inspection_fixtures import (
    staged_poststart as staged_poststart,
)
from tests.unit.inference_transfer_embedding_fixtures import seal


def mint(case):
    return module.mint_benchmark_poststart_observation(
        case.request, case.invocation, controller=case.controller
    )


def inspector(case, raw_sha256):
    return module.FixedBenchmarkPoststartInspection(case.invocation.execution_id, raw_sha256)


def test_root_create_once_exact_partial_hashes_and_owner_rereads_no_private_retirement(
    staged_poststart, monkeypatch
):
    case = staged_poststart
    before = {p.name: p.read_bytes() for p in (case.execution / "outputs").iterdir()}
    original_open = os.open

    def no_source(path, flags, *args, **kwargs):
        assert not str(path).endswith("benchmark-inputs.json")
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(module.os, "open", no_source)
    result = mint(case)
    assert result.created and result.raw_sha256 == sha256_bytes(case.proof.read_bytes())
    assert case.proof.stat().st_mode & 0o777 == 0o440
    assert case.state["root_reads"] == 1
    assert result.observation.outputs[0].raw_sha256 == sha256_bytes(before["cold-documents.f32"])
    assert {p.name: p.read_bytes() for p in (case.execution / "outputs").iterdir()} == before
    epoch = module._epoch(case.proof.stat())
    replay = mint(case)
    assert not replay.created and replay.observation == result.observation
    assert module._epoch(case.proof.stat()) == epoch and case.state["root_reads"] == 2
    monkeypatch.setattr(
        module,
        "read_root_poststart_retirement",
        lambda *_a: pytest.fail("owner cannot read root700"),
    )
    with inspector(case, result.raw_sha256).capture(case.request, case.invocation) as captured:
        assert captured.observation == result.observation
        captured.assert_current()
    with pytest.raises(ValueError, match="CAPTURE_CLOSED"):
        captured.assert_current()


def test_controller_lifetime_accepts_exact_native_completion_boundaries(staged_poststart):
    case = staged_poststart
    case.state.update(controller_start_us=100, controller_end_us=300)
    result = mint(case)
    with inspector(case, result.raw_sha256).capture(case.request, case.invocation) as captured:
        captured.assert_current()


@pytest.mark.parametrize(
    ("start_us", "end_us"),
    (
        pytest.param(1, 99, id="different-earlier-controller"),
        pytest.param(301, 400, id="different-later-controller"),
        pytest.param(50, 299, id="controller-ends-before-completion"),
        pytest.param(101, 350, id="controller-starts-after-launch"),
    ),
)
def test_controller_must_bracket_launch_before_root_proof_publication(
    staged_poststart, start_us, end_us
):
    case = staged_poststart
    before = {p.name: p.read_bytes() for p in (case.execution / "outputs").iterdir()}
    case.state.update(controller_start_us=start_us, controller_end_us=end_us)
    with pytest.raises(ValueError, match="CONTROLLER_TIME_INVALID"):
        mint(case)
    assert not case.proof.exists()
    assert {p.name: p.read_bytes() for p in (case.execution / "outputs").iterdir()} == before


@pytest.mark.parametrize(
    ("start_us", "end_us"),
    (
        pytest.param(1, 99, id="different-earlier-controller"),
        pytest.param(301, 400, id="different-later-controller"),
        pytest.param(50, 299, id="controller-ends-before-completion"),
        pytest.param(101, 350, id="controller-starts-after-launch"),
    ),
)
def test_fresh_owner_fence_rejects_controller_outside_original_launch(
    staged_poststart, start_us, end_us
):
    case = staged_poststart
    result = mint(case)
    before = case.proof.read_bytes()
    with inspector(case, result.raw_sha256).capture(case.request, case.invocation) as captured:
        case.state.update(controller_start_us=start_us, controller_end_us=end_us)
        with pytest.raises(ValueError, match="CONTROLLER_TIME_INVALID"):
            captured.assert_current()
    assert case.proof.read_bytes() == before


@pytest.mark.parametrize(
    "fault", ("hash", "mode", "acl", "symlink", "hardlink", "json", "snapshot")
)
def test_untrusted_or_stale_proof_is_not_authority(staged_poststart, fault, monkeypatch):
    case = staged_poststart
    result = mint(case)
    expected = result.raw_sha256
    if fault == "hash":
        expected = "sha256:" + "f" * 64
    elif fault == "mode":
        case.proof.chmod(0o640)
    elif fault == "acl":
        original = module.os.listxattr
        inode = case.proof.stat().st_ino

        def attrs(path, *args, **kwargs):
            if isinstance(path, int) and os.fstat(path).st_ino == inode:
                return ["system.posix_acl_access"]
            return original(path, *args, **kwargs)

        monkeypatch.setattr(module.os, "listxattr", attrs)
    elif fault == "symlink":
        original = case.proof.with_suffix(".original")
        case.proof.rename(original)
        case.proof.symlink_to(original)
    elif fault == "hardlink":
        os.link(case.proof, case.proof.with_suffix(".alias"))
    else:
        case.proof.chmod(0o600)
        if fault == "json":
            raw = b"{}"
        else:
            body = result.observation.model_dump(mode="json")
            body["snapshot_sha256"] = "sha256:" + "f" * 64
            raw = benchmark_poststart_failure_bytes(
                module.BenchmarkPoststartObservation.model_validate(
                    seal(body, "observation_sha256")
                )
            )
        case.proof.write_bytes(raw)
        case.proof.chmod(0o440)
        expected = sha256_bytes(raw)
    with (
        pytest.raises((ValueError, OSError)),
        inspector(case, expected).capture(case.request, case.invocation),
    ):
        pytest.fail("untrusted proof")


@pytest.mark.parametrize(
    "fault", ("completion", "association", "output", "extra", "empty", "retirement", "controller")
)
def test_original_control_or_partial_layout_cannot_be_substituted(staged_poststart, fault):
    case = staged_poststart
    if fault == "completion":
        (case.execution / "root-completion.json").unlink()
    elif fault == "association":
        case.association.write_bytes(b"{}")
    elif fault == "output":
        target = case.execution / "outputs/cold-documents.f32"
        target.rename(target.with_suffix(".original"))
        target.symlink_to("cold-documents.original")
    elif fault == "extra":
        (case.execution / "outputs/unexpected").touch()
    elif fault == "empty":
        (case.execution / "outputs/cold-documents.f32").write_bytes(b"")
    elif fault == "retirement":
        case.state["retired"] = 2
    else:
        result = mint(case)
        before = case.proof.read_bytes()
        case.controller = case.controller.model_copy(update={"source_commit": "f" * 40})
        with pytest.raises(ValueError):
            mint(case)
        assert case.proof.read_bytes() == before and sha256_bytes(before) == result.raw_sha256
        return
    with pytest.raises((ValueError, OSError, AssertionError)):
        mint(case)
    assert not case.proof.exists()


@pytest.mark.parametrize(
    "fault",
    (
        "proof",
        "ctime",
        "output",
        "boot",
        "machine",
        "association",
        "completion",
        "invocation",
        "membership",
    ),
)
def test_late_drift_blocks_in_transaction_fence(staged_poststart, fault):
    case = staged_poststart
    result = mint(case)
    with (
        pytest.raises(ValueError),
        inspector(case, result.raw_sha256).capture(case.request, case.invocation) as captured,
    ):
        if fault == "proof":
            case.proof.chmod(0o640)
        elif fault == "ctime":
            target = case.execution / "outputs/cold-documents.f32"
            initial = target.stat()
            target.chmod(0o600)
            target.chmod(0o640)
            os.utime(target, ns=(initial.st_atime_ns, initial.st_mtime_ns))
        elif fault == "output":
            (case.execution / "outputs/cold-documents.f32").write_bytes(b"replacement")
        elif fault == "boot":
            case.state["boot"] = "00000000-0000-0000-0000-000000000002"
        elif fault == "machine":
            case.state["epoch"] += 1
        elif fault == "association":
            case.association.write_bytes(case.association.read_bytes())
        elif fault == "completion":
            target = case.execution / "root-completion.json"
            target.write_bytes(target.read_bytes())
        elif fault == "invocation":
            target = case.execution / "invocation.json"
            target.write_bytes(target.read_bytes())
        else:
            (case.execution / "outputs/new").touch()
        captured.assert_current()


def test_no_post_commit_validation_and_no_stale_remint(staged_poststart):
    case = staged_poststart
    result = mint(case)
    before = case.proof.read_bytes()
    with inspector(case, result.raw_sha256).capture(case.request, case.invocation) as captured:
        captured.assert_current()
        case.state["epoch"] += 1
    with pytest.raises(ValueError, match="PROOF_STALE"):
        mint(case)
    assert case.proof.read_bytes() == before


def test_parsed_observation_cannot_be_inspector_identity_or_mint_authority(
    staged_poststart, monkeypatch
):
    case = staged_poststart
    with pytest.raises(ValueError):
        module.FixedBenchmarkPoststartInspection(case.request, "sha256:" + "0" * 64)
    monkeypatch.setattr(module.os, "getresuid", lambda: (os.getuid() + 50,) * 3)
    with pytest.raises(ValueError, match="ROOT_REQUIRED"):
        mint(case)
    assert not case.proof.exists()


def test_failed_partial_publication_is_preserved_without_rewrite(staged_poststart, monkeypatch):
    case = staged_poststart
    original = module.os.write
    count = 0

    def fail_late(fd, value):
        nonlocal count
        count += 1
        if count == 1:
            return original(fd, value[:3])
        raise OSError("synthetic bounded write failure")

    monkeypatch.setattr(module.os, "write", fail_late)
    with pytest.raises(ValueError):
        mint(case)
    assert case.proof.read_bytes() == b'{"a'
    monkeypatch.setattr(module.os, "write", original)
    with pytest.raises(ValueError):
        mint(case)
    assert case.proof.read_bytes() == b'{"a'
