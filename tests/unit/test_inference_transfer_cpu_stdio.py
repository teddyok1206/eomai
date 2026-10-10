"""Fake stdin/stdout ownership and backend; never an actual privileged/model gate."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.inference_transfer_experiment import InferenceTransferExperimentResult
from eom_catalog_service import inference_transfer_cpu_stdio as stdio
from eom_identifiers import canonical_json_bytes
from jsonschema.exceptions import ValidationError as SchemaValidationError

from tests.unit.inference_transfer_experiment_fixtures import experiment_request
from tests.unit.inference_transfer_fixtures import NOW
from tests.unit.test_inference_transfer_experiment import FakeMeasuredBackend
from tests.unit.test_inference_transfer_experiment_execution import EXECUTION, pinned_result


def input_file(tmp_path: Path, payload: bytes | None = None) -> Path:
    path = tmp_path / "input.json"
    path.write_bytes(
        canonical_json_bytes(experiment_request().model_dump(mode="json"))
        if payload is None
        else payload
    )
    path.chmod(0o600)
    return path


@contextmanager
def stdin_stdout(input_path: Path, output_path: Path) -> Iterator[None]:
    """Temporary process FD redirection; restores pytest streams even after errors."""
    sys.stdout.flush()
    old_input, old_output = os.dup(0), os.dup(1)
    input_fd = os.open(input_path, os.O_RDONLY)
    output_fd = os.open(output_path, os.O_WRONLY)
    try:
        os.dup2(input_fd, 0)
        os.dup2(output_fd, 1)
        yield
    finally:
        sys.stdout.flush()
        os.dup2(old_input, 0)
        os.dup2(old_output, 1)
        for descriptor in (input_fd, output_fd, old_input, old_output):
            os.close(descriptor)


def fake_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    # Root UID is collapsed ONLY for unprivileged FD metadata tests.
    monkeypatch.setattr(stdio, "_ROOT_UID", os.geteuid())
    monkeypatch.setattr(stdio.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.geteuid()))


def test_fd_request_is_exact_canonical_and_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_identity(monkeypatch)
    path = input_file(tmp_path)
    descriptor = os.open(path, os.O_RDONLY)
    try:
        assert stdio.read_stdin_request(descriptor) == experiment_request()
    finally:
        os.close(descriptor)
    descriptor = os.open(path, os.O_RDWR)
    try:
        with pytest.raises(ValueError, match="INPUT_INVALID"):
            stdio.read_stdin_request(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "kind", ["mode", "uid", "hardlink", "cap", "empty", "duplicate", "newline", "budget"]
)
def test_invalid_input_fails_without_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    fake_identity(monkeypatch)
    path = input_file(tmp_path)
    if kind == "mode":
        path.chmod(0o640)
    elif kind == "uid":
        monkeypatch.setattr(stdio, "_ROOT_UID", os.geteuid() + 1)
    elif kind == "hardlink":
        os.link(path, tmp_path / "linked.json")
    elif kind == "cap":
        monkeypatch.setattr(stdio, "MAXIMUM_MEMBER_BYTES", 1)
    elif kind == "empty":
        path.write_bytes(b"")
    elif kind == "duplicate":
        path.write_bytes(b'{"schema_version":"forged",' + path.read_bytes()[1:])
    elif kind == "newline":
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path.write_bytes(
            canonical_json_bytes(
                experiment_request(maximum_input_bytes=1024).model_dump(mode="json")
            )
        )
    descriptor = os.open(path, os.O_RDONLY)
    try:
        with pytest.raises(ValueError):
            stdio.read_stdin_request(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize(
    "kind", ["mode", "uid", "hardlink", "existing", "readwrite", "cap", "forged_hash"]
)
def test_result_writer_requires_empty_root_output_and_validated_typed_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    fake_identity(monkeypatch)
    path = tmp_path / "output.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    result = pinned_result(experiment_request())
    if kind == "mode":
        path.chmod(0o600)
    elif kind == "uid":
        monkeypatch.setattr(stdio, "_ROOT_UID", os.geteuid() + 1)
    elif kind == "hardlink":
        os.link(path, tmp_path / "linked.json")
    elif kind == "existing":
        path.write_bytes(b"historical")
    elif kind == "cap":
        monkeypatch.setattr(stdio, "MAXIMUM_MEMBER_BYTES", 1)
    elif kind == "forged_hash":
        result = result.model_copy(update={"result_sha256": "f" * 64})
    descriptor = os.open(path, os.O_RDWR if kind == "readwrite" else os.O_WRONLY)
    try:
        with pytest.raises(ValueError):
            stdio.write_stdout_result(descriptor, result)
    finally:
        os.close(descriptor)
    assert path.read_bytes() == (b"historical" if kind == "existing" else b"")


def test_writer_emits_one_canonical_bounded_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_identity(monkeypatch)
    path = tmp_path / "output.json"
    path.touch(mode=0o640)
    path.chmod(0o640)
    descriptor = os.open(path, os.O_WRONLY)
    result = pinned_result(experiment_request())
    try:
        stdio.write_stdout_result(descriptor, result)
    finally:
        os.close(descriptor)
    assert path.read_bytes() == canonical_json_bytes(result.model_dump(mode="json"))


def test_library_prints_never_pollute_result_or_raw_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_identity(monkeypatch)
    incoming = input_file(tmp_path)
    outgoing = tmp_path / "output.json"
    outgoing.touch(mode=0o640)
    outgoing.chmod(0o640)
    calls: list[dict[str, Any]] = []

    def backend(*args: Any, **kwargs: Any) -> FakeMeasuredBackend:
        print("sensitive model library diagnostic", flush=True)
        os.write(1, b"native library diagnostic\n")
        calls.append(kwargs)
        return FakeMeasuredBackend()

    def measured(request: Any, _backend: Any, **kwargs: Any) -> InferenceTransferExperimentResult:
        print("buffered library diagnostic without explicit flush")
        assert kwargs["execution_id"] == EXECUTION
        # Explicit fake transport fixture, NOT genuine PINNED_MODEL evidence.
        return pinned_result(request, EXECUTION, created_at=kwargs["created_at"])

    monkeypatch.setattr(stdio, "OfflineTransformersEmbeddingBackend", backend)
    monkeypatch.setattr(stdio, "measure_cpu_experiment", measured)
    with stdin_stdout(incoming, outgoing):
        stdio.run_stdio(EXECUTION)
    result = InferenceTransferExperimentResult.model_validate_json(outgoing.read_bytes())
    assert result.execution_id == EXECUTION
    assert outgoing.read_bytes() == canonical_json_bytes(result.model_dump(mode="json"))
    assert b"library diagnostic" not in outgoing.read_bytes()
    assert calls == [{"expected_owner_uid": os.geteuid(), "batch_size": 4, "threads": 4}]


@pytest.mark.parametrize("kind", ["invalid_identity", "wrong_user", "bad_input", "bad_output"])
def test_prelaunch_transport_failure_does_not_load_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    fake_identity(monkeypatch)
    incoming = input_file(tmp_path)
    outgoing = tmp_path / "output.json"
    outgoing.touch(mode=0o640)
    outgoing.chmod(0o640)
    identity = EXECUTION
    if kind == "invalid_identity":
        identity = "../secret"
    elif kind == "wrong_user":
        monkeypatch.setattr(
            stdio.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.geteuid() + 1)
        )
    elif kind == "bad_input":
        incoming.chmod(0o644)
    else:
        outgoing.write_bytes(b"historical")
    monkeypatch.setattr(
        stdio,
        "OfflineTransformersEmbeddingBackend",
        lambda *_a, **_k: pytest.fail("must not load model"),
    )
    with stdin_stdout(incoming, outgoing), pytest.raises(ValueError):
        stdio.run_stdio(identity)


def test_real_measurement_helper_retains_test_backend_labels() -> None:
    value = stdio.measure_cpu_experiment(
        experiment_request(),
        FakeMeasuredBackend(),
        execution_id=EXECUTION,
        created_at=NOW,
        model_load_milliseconds=2,
    )
    assert value.backend_kind == "TEST_ONLY" and value.actual_model_manifest_sha256 is None
    assert value.data_provenance == "TEST_ONLY_SYNTHETIC"
    assert value.human_transfer_review == "NOT_EVALUATED"
    assert value.measurements.peak_rss_kib_linux is not None


def test_stdio_entry_redacts_schema_and_third_party_error_payload(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def failure(_identity: str) -> None:
        raise SchemaValidationError("sensitive test input must not enter raw journal")

    monkeypatch.setattr(stdio, "run_stdio", failure)
    monkeypatch.setattr(sys, "argv", ["cpu", "--execution-id", EXECUTION])
    with pytest.raises(SystemExit) as observed:
        stdio.main()
    assert observed.value.code == 1
    assert capsys.readouterr() == ("", "")
