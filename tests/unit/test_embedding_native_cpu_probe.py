"""Synthetic protocol/transport probes; these are not live installation acceptance."""

from __future__ import annotations

import ast
import errno
import fcntl
import json
import os
import signal
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from eom_catalog_contracts.embedding_native_cpu_probe import (
    CPU_PROBE_SCHEMA,
    MAX_CPU_PROBE_BYTES,
    NativeCpuProbeDenials,
    NativeCpuProbeInput,
    NativeCpuProbeResult,
    parse_native_cpu_probe_input,
    parse_native_cpu_probe_result,
    validate_native_cpu_probe_association,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_catalog_service import embedding_native_cpu_probe as probe
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata

ROOT = Path(__file__).resolve().parents[2]
INVALID = (ValueError, TypeError, SchemaError)


def metadata() -> tuple[NativeCpuProbeInput, bytes, NativeCpuProbeResult]:
    config, bundle, _proof = native_config_metadata()
    request = NativeCpuProbeInput.model_validate(
        {
            "schema_version": "embedding-native-cpu-probe-input/1.0",
            "execution_id": "a" * 32,
            "profile": "CPU_INDEX_FP32",
            "installed_proof": config.installed_proof.model_dump(mode="json"),
            "payload": bundle.payload_pointer.model_dump(mode="json"),
        }
    )
    raw = canonical_json_bytes(request.model_dump(mode="json"))
    result = NativeCpuProbeResult.model_validate(
        {
            "schema_version": "embedding-native-cpu-probe-result/1.0",
            "evidence_state": "OBSERVED_NOT_ADMITTED",
            "recipe": "NATIVE_CPU_FIXED_UNIT_NO_MODEL_NO_FORWARD_NEGATIVES/1.0",
            "execution_id": request.execution_id,
            "input_raw_sha256": sha256_bytes(raw),
            "pid": 123,
            "worker_uid": 1234,
            "worker_gid": 1234,
            "supplementary_gids": [],
            "checked_model_members": len(bundle.payload_model_spec.files) + 1,
            "payload_file_set_sha256": request.payload.file_set_sha256,
            "denials": {name: "DENIED" for name in NativeCpuProbeDenials.model_fields},
            "numerical_runtime": bundle.numerical_runtime.model_dump(mode="json"),
        }
    )
    return request, raw, result


def test_schema_pins_and_roundtrip_do_not_grant_admission() -> None:
    resource = CATALOG_SCHEMA_RESOURCES[CPU_PROBE_SCHEMA]
    raw = (ROOT / resource.canonical_path).read_bytes()
    packaged = ROOT / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
    assert raw == packaged.read_bytes() and sha256_bytes(raw) == resource.sha256
    Draft202012Validator.check_schema(load_schema(CPU_PROBE_SCHEMA))
    request, raw, result = metadata()
    assert parse_native_cpu_probe_input(raw) == request
    assert (
        parse_native_cpu_probe_result(canonical_json_bytes(result.model_dump(mode="json")))
        == result
    )
    validate_native_cpu_probe_association(request, raw, result)
    assert result.evidence_state == "OBSERVED_NOT_ADMITTED"
    assert not hasattr(result, "assert_current")


@pytest.mark.parametrize("scope", ["input", "result"])
@pytest.mark.parametrize("field", ["actor", "command", "path", "approved", "gpu", "artifact_id"])
def test_no_unreviewed_authority_or_paths(scope: str, field: str) -> None:
    request, _, result = metadata()
    body = (request if scope == "input" else result).model_dump(mode="json")
    body[field] = "untrusted"
    parse = parse_native_cpu_probe_input if scope == "input" else parse_native_cpu_probe_result
    with pytest.raises(INVALID):
        parse(canonical_json_bytes(body))


@pytest.mark.parametrize("fault", ["space", "duplicate", "oversize", "depth", "float", "nan"])
def test_external_canonical_input_rejected(fault: str) -> None:
    _, raw, _ = metadata()
    raw = {
        "space": b" " + raw,
        "duplicate": b'{"profile":"CPU_INDEX_FP32",' + raw[1:],
        "oversize": b" " * (MAX_CPU_PROBE_BYTES + 1),
        "depth": b"[" * 1100 + b"0" + b"]" * 1100,
        "float": b'{"x":1.0}',
        "nan": b'{"x":NaN}',
    }[fault]
    with pytest.raises(INVALID):
        parse_native_cpu_probe_input(raw)


@pytest.mark.parametrize("field", ["pid", "worker_uid", "worker_gid", "checked_model_members"])
@pytest.mark.parametrize("value", [True, False, 1.0, "1", -1, None])
def test_raw_numbers_do_not_coerce(field: str, value: object) -> None:
    _, _, result = metadata()
    body = result.model_dump(mode="json")
    body[field] = value
    with pytest.raises(INVALID):
        parse_native_cpu_probe_result(json.dumps(body).encode())
    with pytest.raises(INVALID):
        NativeCpuProbeResult.model_validate(result.model_copy(update={field: value}))


@pytest.mark.parametrize("fault", ["cuda", "profile", "supplementary", "missing_deny", "allow"])
def test_foreign_profile_and_incomplete_negative_evidence_rejected(fault: str) -> None:
    request, _, result = metadata()
    if fault in {"cuda", "profile"}:
        body = request.model_dump(mode="json")
        if fault == "cuda":
            config, _, _ = native_config_metadata("CUDA_INDEX_FP32")
            body["installed_proof"] = config.installed_proof.model_dump(mode="json")
        else:
            body["profile"] = "CUDA_INDEX_FP32"
        with pytest.raises(INVALID):
            parse_native_cpu_probe_input(canonical_json_bytes(body))
    else:
        body = result.model_dump(mode="json")
        if fault == "supplementary":
            body["supplementary_gids"] = [1000]
        elif fault == "missing_deny":
            del body["denials"]["nas"]
        else:
            body["denials"]["nas"] = "ALLOWED"
        with pytest.raises(INVALID):
            parse_native_cpu_probe_result(canonical_json_bytes(body))


@pytest.mark.parametrize("field", ["execution_id", "input_raw_sha256", "payload_file_set_sha256"])
def test_other_execution_or_payload_is_not_replay(field: str) -> None:
    request, raw, result = metadata()
    replacement = "b" * 32 if field == "execution_id" else "sha256:" + "e" * 64
    with pytest.raises(INVALID):
        validate_native_cpu_probe_association(
            request, raw, result.model_copy(update={field: replacement})
        )


def test_write_negative_opens_without_modifying_unexpected_writable_file(tmp_path: Path) -> None:
    target = tmp_path / "immutable"
    target.write_bytes(b"original")
    before = target.stat()
    with pytest.raises(ValueError, match="WRITE_ALLOWED"):
        probe._denied_write(target)
    assert target.read_bytes() == b"original"
    assert target.stat().st_mtime_ns == before.st_mtime_ns


@pytest.mark.parametrize("error", [errno.EACCES, errno.EPERM, errno.EROFS])
def test_write_denials_are_closed(monkeypatch: pytest.MonkeyPatch, error: int) -> None:
    def denied(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(error, "synthetic")

    monkeypatch.setattr(probe.os, "open", denied)
    probe._denied_write(Path("/synthetic"))


@pytest.mark.parametrize("error", [errno.ENOENT, errno.EIO, errno.ETXTBSY, errno.ELOOP])
def test_missing_or_unknown_write_check_is_not_permission_denial(
    monkeypatch: pytest.MonkeyPatch, error: int
) -> None:
    def denied(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(error, "synthetic")

    monkeypatch.setattr(probe.os, "open", denied)
    with pytest.raises(ValueError, match="WRITE_CHECK_INVALID"):
        probe._denied_write(Path("/synthetic"))


@pytest.mark.parametrize("uid", [None, 1000, 65534])
def test_no_owner_or_unprivileged_signal_cannot_finish(
    monkeypatch: pytest.MonkeyPatch, uid: int | None
) -> None:
    response = None if uid is None else SimpleNamespace(si_uid=uid, si_signo=signal.SIGUSR1)
    monkeypatch.setattr(probe.signal, "sigtimedwait", lambda *_: response)
    with pytest.raises(ValueError, match="OWNER_OBSERVATION_MISSING"):
        probe._wait_owner_release()


def test_owner_ack_is_bounded_but_is_not_independent_unit_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    def release(signals: object, timeout: object) -> object:
        calls.append((signals, timeout))
        return SimpleNamespace(si_uid=0, si_signo=signal.SIGUSR1)

    monkeypatch.setattr(probe.signal, "sigtimedwait", release)
    probe._wait_owner_release()
    assert calls == [({signal.SIGUSR1}, 30)]


@pytest.fixture
def transport(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    request, raw, result = metadata()
    source, output = tmp_path / "input.json", tmp_path / "result.json"
    source.write_bytes(raw)
    output.touch(mode=0o600)
    source.chmod(0o600)
    input_fd = os.open(source, os.O_RDONLY)
    result_fd = os.open(output, os.O_WRONLY)
    original_fstat = os.fstat

    def synthetic_root(descriptor: int) -> os.stat_result:
        # Metadata substitution only, never a claim to run a real root-owned unit.
        value = original_fstat(descriptor)
        return SimpleNamespace(
            **{name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
            | {"st_uid": 0}
        )

    monkeypatch.setattr(probe.os, "fstat", synthetic_root)
    monkeypatch.setattr(probe, "require_native_embedding_identity", lambda *_: None)
    monkeypatch.setattr(probe.signal, "pthread_sigmask", lambda *_: None)
    events: list[str] = []

    @contextmanager
    def observations(given: object, given_raw: bytes) -> Any:
        assert given == request and given_raw == raw
        events.append("observe")
        yield result
        events.append("recheck")

    monkeypatch.setattr(probe, "observe_native_cpu_probe", observations)

    def release() -> None:
        assert parse_native_cpu_probe_result(output.read_bytes()) == result
        events.append("owner_ack")

    monkeypatch.setattr(probe, "_wait_owner_release", release)
    try:
        yield request, source, output, input_fd, result_fd, events
    finally:
        os.close(input_fd)
        os.close(result_fd)


def test_report_precedes_owner_ack_and_rechecks_before_return(transport: Any) -> None:
    request, _, output, input_fd, result_fd, events = transport
    probe.run_native_cpu_probe(request.execution_id, input_fd=input_fd, result_fd=result_fd)
    assert events == ["observe", "owner_ack", "recheck"]
    assert (
        parse_native_cpu_probe_result(output.read_bytes()).evidence_state == "OBSERVED_NOT_ADMITTED"
    )
    with pytest.raises(ValueError, match="DESCRIPTORS_INVALID"):
        probe.run_native_cpu_probe(request.execution_id, input_fd=input_fd, result_fd=result_fd)


@pytest.mark.parametrize(
    "fault", ["offset", "output", "append", "mode", "alias", "hardlink", "execution"]
)
def test_bad_handoff_rejected_before_observer(transport: Any, fault: str, tmp_path: Path) -> None:
    request, source, output, input_fd, result_fd, events = transport
    execution = request.execution_id
    if fault == "offset":
        os.lseek(input_fd, 1, os.SEEK_SET)
    elif fault == "output":
        output.write_bytes(b"retained failure")
    elif fault == "append":
        fcntl.fcntl(result_fd, fcntl.F_SETFL, os.O_APPEND)
    elif fault == "mode":
        source.chmod(0o644)
    elif fault == "alias":
        os.dup2(input_fd, result_fd)
    elif fault == "hardlink":
        os.link(source, tmp_path / "alias")
    else:
        execution = "b" * 32
    with pytest.raises(ValueError):
        probe.run_native_cpu_probe(execution, input_fd=input_fd, result_fd=result_fd)
    assert events == []


def test_owner_timeout_keeps_observed_report_not_success(
    transport: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, _, output, input_fd, result_fd, events = transport

    def missing() -> None:
        raise ValueError("NATIVE_CPU_PROBE_OWNER_OBSERVATION_MISSING")

    monkeypatch.setattr(probe, "_wait_owner_release", missing)
    with pytest.raises(ValueError, match="OWNER_OBSERVATION_MISSING"):
        probe.run_native_cpu_probe(request.execution_id, input_fd=input_fd, result_fd=result_fd)
    assert events == ["observe"]
    assert (
        parse_native_cpu_probe_result(output.read_bytes()).evidence_state == "OBSERVED_NOT_ADMITTED"
    )


@pytest.mark.parametrize("fault", ["write", "fsync", "late_input"])
def test_output_or_late_input_failure_never_completes(
    transport: Any, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    request, source, output, input_fd, result_fd, events = transport
    if fault == "write":
        monkeypatch.setattr(probe.os, "write", lambda *_: 0)
    elif fault == "fsync":

        def unavailable(*_args: object) -> None:
            raise OSError("synthetic fsync failure")

        monkeypatch.setattr(probe.os, "fsync", unavailable)
    else:

        def change() -> None:
            source.write_bytes(b"changed after report")

        monkeypatch.setattr(probe, "_wait_owner_release", change)
    with pytest.raises((ValueError, OSError)):
        probe.run_native_cpu_probe(request.execution_id, input_fd=input_fd, result_fd=result_fd)
    assert "owner_ack" not in events
    if fault != "write":
        assert output.stat().st_size > 0  # Partial/completed failure evidence is retained.


def test_no_optional_libraries_or_model_constructors_at_module_import() -> None:
    tree = ast.parse(Path(probe.__file__).read_text())
    imports = [node for node in tree.body if isinstance(node, ast.Import | ast.ImportFrom)]
    names = {
        alias.name if isinstance(node, ast.Import) else node.module or ""
        for node in imports
        for alias in node.names
    }
    assert not any(
        name.startswith(("torch", "transformers", "pydantic", "numpy")) for name in names
    )
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not {"from_pretrained", "forward", "encode", "load_state_dict"} & calls


@pytest.fixture
def observation_ports(monkeypatch: pytest.MonkeyPatch) -> Any:
    from eom_catalog_service import (
        embedding_installed_runtime_observer as proof_module,
    )
    from eom_catalog_service import (
        embedding_offline_backend as backend_module,
    )
    from eom_catalog_service import (
        inference_transfer_cpu_verifier as old_probe,
    )
    from eom_catalog_service import (
        local_embedding_adapter as model_module,
    )

    request, raw, _ = metadata()
    _, bundle, _ = native_config_metadata()
    calls: list[str] = []
    spec = bundle.payload_model_spec
    manifest = SimpleNamespace(
        raw=canonical_json_bytes(spec.model_dump(mode="json")),
        sha256=request.payload.manifest_raw_sha256,
        assert_unchanged=lambda: calls.append("manifest_epoch"),
    )
    payload = SimpleNamespace(
        manifest=manifest, assert_unchanged=lambda: calls.append("payload_epoch")
    )

    class Observer:
        def __init__(self, configured: Any) -> None:
            assert configured.pointer == request.installed_proof
            calls.append("proof")

        def observe(self) -> str:
            calls.append("runtime_metadata")
            return "same actual observation (synthetic fixture)"

    def load_spec(path: Path) -> Any:
        assert path == probe.MODEL_ROOT / spec.model_id / spec.model_revision_id / "manifest.json"
        calls.append("manifest")
        return manifest

    def resolve(root: Path, given: object) -> Any:
        assert root == probe.MODEL_ROOT and given == spec
        calls.append("model_hashes")
        return payload

    def numerics(**kwargs: Any) -> Any:
        assert kwargs["profile"] == "CPU_INDEX_FP32"
        calls.append("model_free_imports")
        return bundle.numerical_runtime

    monkeypatch.setattr(
        probe, "require_native_embedding_identity", lambda *_: calls.append("identity")
    )
    monkeypatch.setattr(proof_module, "ProtectedInstalledEmbeddingRuntimeObserver", Observer)
    monkeypatch.setattr(model_module, "read_protected_embedding_manifest", load_spec)
    monkeypatch.setattr(model_module, "resolve_local_embedding_payload", resolve)
    monkeypatch.setattr(old_probe, "verify_no_network", lambda: calls.append("network"))
    monkeypatch.setattr(old_probe, "denied_file", lambda *_: "DENIED")
    monkeypatch.setattr(old_probe, "denied_socket", lambda *_: "DENIED")
    monkeypatch.setattr(probe, "_denied_write", lambda *_: calls.append("write_denied"))
    monkeypatch.setattr(probe.os, "getgroups", lambda: [os.getegid()])
    monkeypatch.setattr(backend_module, "observe_native_runtime_without_model", numerics)
    return request, raw, manifest, payload, calls, old_probe


def test_observation_uses_existing_ports_and_retains_snapshots(observation_ports: Any) -> None:
    request, raw, _, _, calls, _ = observation_ports
    with probe.observe_native_cpu_probe(request, raw) as result:
        assert result.evidence_state == "OBSERVED_NOT_ADMITTED"
        assert calls[:5] == ["identity", "proof", "runtime_metadata", "manifest", "model_hashes"]
        assert calls[-1] == "model_free_imports"
        calls.append("owner_observed")
    assert calls[-5:] == [
        "owner_observed",
        "identity",
        "manifest_epoch",
        "payload_epoch",
        "runtime_metadata",
    ]


def test_denial_failure_precedes_optional_imports(
    observation_ports: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    request, raw, _, _, calls, old_probe = observation_ports

    def allowed(*_args: object) -> str:
        raise ValueError("forbidden socket was reachable")

    monkeypatch.setattr(old_probe, "denied_socket", allowed)
    with pytest.raises(ValueError, match="reachable"), probe.observe_native_cpu_probe(request, raw):
        pytest.fail("no observation may be emitted")
    assert "model_free_imports" not in calls


def test_payload_manifest_pin_failure_precedes_model_read(observation_ports: Any) -> None:
    request, raw, manifest, _, calls, _ = observation_ports
    manifest.sha256 = "sha256:" + "0" * 64
    with (
        pytest.raises(ValueError, match="PAYLOAD_MISMATCH"),
        probe.observe_native_cpu_probe(request, raw),
    ):
        pytest.fail("no observation may be emitted")
    assert "model_hashes" not in calls and "model_free_imports" not in calls


def test_owner_exception_still_rechecks_retained_payload(observation_ports: Any) -> None:
    request, raw, _, _, calls, _ = observation_ports
    with (
        pytest.raises(ValueError, match="owner observation failed"),
        probe.observe_native_cpu_probe(request, raw),
    ):
        raise ValueError("owner observation failed")
    assert calls[-4:] == ["identity", "manifest_epoch", "payload_epoch", "runtime_metadata"]


def test_fixed_unit_has_no_credentials_worker_authority_or_mutable_storage() -> None:
    text = (ROOT / "infra/systemd/eom-embedding-native-cpu-probe@.service").read_text()
    for required in (
        "User=eom-embedding-index-cpu",
        "Group=eom-embedding-index-cpu",
        "PrivateNetwork=yes",
        "PrivateDevices=yes",
        "NoNewPrivileges=yes",
        "ProtectSystem=strict",
        "ProtectHome=yes",
        "RestrictAddressFamilies=AF_UNIX",
        "CapabilityBoundingSet=\n",
        "AmbientCapabilities=\n",
        "MemoryMax=6G",
        "CPUQuota=400%",
        "TasksMax=64",
        "TimeoutStartSec=180",
        "Restart=no",
        "LimitCORE=0",
        "LimitFSIZE=64K",
        "WorkingDirectory=/",
        "StandardInput=file:/run/eom-embedding-native-probe/%i/input.json",
        "StandardOutput=file:/run/eom-embedding-native-probe/%i/result.json",
        "StandardError=null",
        " -I -B -m eom_catalog_service.embedding_native_cpu_probe %i",
    ):
        assert required in text
    assert "SupplementaryGroups=" not in text and "ReadWritePaths=" not in text
    assert "[Install]" not in text and "EnvironmentFile=" not in text
