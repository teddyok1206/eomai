"""CPU composition/source-unit tests; not installation, model-forward or owner acceptance."""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, cast

import pytest
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_catalog_service import embedding_native_cpu as cpu
from eom_catalog_service import embedding_native_factory as factory
from eom_catalog_service import embedding_native_installation_admission as installed
from eom_catalog_service.embedding_execution_ports import NativeEmbeddingBackend

ROOT = Path(__file__).resolve().parents[2]
PINS = (
    "embeddingnativeconfig_" + "a" * 32,
    "embeddingnativeconfigrev_" + "b" * 32,
    "sha256:" + "c" * 64,
    "sha256:" + "d" * 64,
    "sha256:" + "e" * 64,
)


@pytest.mark.parametrize("purpose", ("INDEX", "QUERY"))
def test_fixed_purpose_preserves_each_independent_owner_pin(purpose: str) -> None:
    selected, pins = cpu._owner_arguments((purpose, *PINS))
    assert selected == purpose
    assert (
        pins.configuration_id,
        pins.configuration_revision_id,
        pins.configuration_sha256,
        pins.configuration_raw_sha256,
        pins.receipt_raw_sha256,
    ) == PINS


@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("invalid", ("", "latest", "../config", "sha256:" + "A" * 64, "x" * 4096))
def test_invalid_arguments_have_no_default_or_runtime_fallback(index: int, invalid: str) -> None:
    arguments = ["INDEX", *PINS]
    arguments[index] = invalid
    with pytest.raises(ValueError):
        cpu._owner_arguments(tuple(arguments))


@pytest.mark.parametrize("arguments", ((), ("INDEX", *PINS[:-1]), ("INDEX", *PINS, "extra")))
def test_argument_count_is_exact(arguments: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="OWNER_PINS_INVALID"):
        cpu._owner_arguments(arguments)


@pytest.mark.parametrize("purpose", ("INDEX", "QUERY"))
@pytest.mark.parametrize(
    "failure", (None, "capture", "entry", "factory", "backend", "body", "cleanup")
)
def test_descriptor_entrypoint_owns_identity_and_input_before_captured_backend_lifetime(
    monkeypatch: pytest.MonkeyPatch, purpose: str, failure: str | None
) -> None:
    events: list[str] = []
    backend = cast(NativeEmbeddingBackend, object())

    class Admission:
        def __init__(
            self,
            configuration: RootLocalNativeConfigurationPin,
            *,
            expected_receipt_raw_sha256: str,
        ) -> None:
            events.append("capture")
            assert configuration.configuration_id == PINS[0]
            assert configuration.configuration_revision_id == PINS[1]
            assert configuration.configuration_sha256 == PINS[2]
            assert configuration.configuration_raw_sha256 == PINS[3]
            assert expected_receipt_raw_sha256 == PINS[4]
            if failure == "capture":
                raise ValueError("synthetic capture failure")

        def __enter__(self) -> Admission:
            events.append("admission-enter")
            if failure == "entry":
                raise ValueError("synthetic admission entry failure")
            return self

        def __exit__(self, *_args: object) -> None:
            events.append("admission-close")
            if failure == "cleanup":
                raise ValueError("synthetic cleanup uncertainty")

    @contextmanager
    def scope() -> Iterator[NativeEmbeddingBackend]:
        events.append("backend-enter")
        if failure == "backend":
            raise ValueError("synthetic backend failure")
        try:
            yield backend
        finally:
            events.append("backend-close")

    def bind(**kwargs: Any) -> Any:
        events.append("factory")
        assert kwargs == {
            "profile": "CPU_INDEX_FP32",
            "configuration_id": PINS[0],
            "configuration_revision_id": PINS[1],
            "configuration_raw_sha256": PINS[3],
            "admission": kwargs["admission"],
        }
        assert isinstance(kwargs["admission"], Admission)
        if failure == "factory":
            raise ValueError("synthetic factory failure")
        return scope

    def run(**kwargs: Any) -> None:
        assert kwargs["profile"] == "CPU_INDEX_FP32"
        events.append("identity-and-request")
        with kwargs["backend_scope"]() as actual:
            assert actual is backend
            events.append("body")
            if failure == "body":
                raise ValueError("synthetic encode failure")

    def forbidden(**_kwargs: Any) -> None:
        pytest.fail("the other purpose must not run")

    monkeypatch.setattr(sys, "argv", ["fixed-installed-module", purpose, *PINS])
    monkeypatch.setattr(installed, "ProtectedNativeEmbeddingInstallationAdmission", Admission)
    monkeypatch.setattr(factory, "native_embedding_backend_scope", bind)
    monkeypatch.setattr(cpu, "run_native_embedding_index", run if purpose == "INDEX" else forbidden)
    monkeypatch.setattr(
        cpu, "run_native_embedding_reference_query", run if purpose == "QUERY" else forbidden
    )
    assert cpu.main() == (0 if failure is None else 1)
    expected = [
        "identity-and-request",
        "capture",
        "admission-enter",
        "factory",
        "backend-enter",
        "body",
    ]
    cutoff = {"capture": 2, "entry": 3, "factory": 4, "backend": 5}.get(
        failure or "", len(expected)
    )
    expected = expected[:cutoff]
    if failure not in {"capture", "entry", "factory", "backend"}:
        expected.append("backend-close")
    if failure not in {"capture", "entry"}:
        expected.append("admission-close")
    assert events == expected


def test_bad_owner_pin_never_reaches_identity_or_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["fixed-installed-module", "INDEX", *PINS[:-1]])
    monkeypatch.setattr(cpu, "run_native_embedding_index", lambda **_: pytest.fail("no dispatch"))
    assert cpu.main() == 1


def test_fresh_import_is_stdlib_only_and_bad_cli_is_quiet() -> None:
    command = (
        "import sys; import eom_catalog_service.embedding_native_cpu; "
        "assert not any(n in sys.modules for n in "
        "('pydantic','torch','transformers','eom_gpu_lease','eom_orchestrator','sqlalchemy'))"
    )
    completed = subprocess.run(
        [sys.executable, "-B", "-c", command], capture_output=True, check=False, timeout=30
    )
    assert completed.returncode == 0 and not completed.stdout and not completed.stderr
    completed = subprocess.run(
        [sys.executable, "-B", "-m", "eom_catalog_service.embedding_native_cpu", "INDEX"],
        capture_output=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 1 and not completed.stdout and not completed.stderr


def test_composition_adds_no_io_launch_authority_or_alternative_encoder() -> None:
    tree = ast.parse(inspect.getsource(cpu))
    imports = {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)} | {
        name.name for node in ast.walk(tree) if isinstance(node, ast.Import) for name in node.names
    }
    assert not any(
        name.startswith(
            (
                "eom_orchestrator",
                "eom_workflow_runner",
                "eom_api",
                "sqlalchemy",
                "torch",
                "transformers",
            )
        )
        or name in {"os", "pathlib", "subprocess", "socket", "json"}
        for name in imports
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"open", "eval", "exec"}
        for node in ast.walk(tree)
    )


def test_fixed_unit_templates_share_isolation_but_keep_purpose_and_descriptors_separate() -> None:
    sources = []
    for purpose in ("index", "query"):
        path = ROOT / f"infra/systemd/eom-embedding-native-cpu-{purpose}@.service"
        source = path.read_text()
        values: dict[str, list[str]] = {}
        for line in source.splitlines():
            if not line or line.startswith(("[", "#")):
                continue
            key, value = line.split("=", 1)
            values.setdefault(key, []).append(value)
        for key, value in {
            "User": "eom-embedding-index-cpu",
            "Group": "eom-embedding-index-cpu",
            "EnvironmentFile": "/etc/eom/embedding-native-cpu.env",
            "PrivateNetwork": "yes",
            "PrivateDevices": "yes",
            "ProtectSystem": "strict",
            "NoNewPrivileges": "yes",
            "Restart": "no",
            "KillMode": "control-group",
            "MemoryMax": "6G",
            "CPUQuota": "400%",
            "TasksMax": "64",
            "TimeoutStartSec": "180",
            "LimitFSIZE": "64M",
            "CapabilityBoundingSet": "",
            "AmbientCapabilities": "",
            "WorkingDirectory": "/",
            "StandardInput": f"file:/run/eom-embedding-native-{purpose}/%i/input.json",
            "StandardOutput": f"file:/run/eom-embedding-native-{purpose}/%i/result.json",
            "StandardError": f"file:/run/eom-embedding-native-{purpose}/%i/vectors.f32",
        }.items():
            assert values[key] == [value]
        command = values["ExecStart"][0]
        assert command.startswith(
            "/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python3.12 -I -B -m "
            f"eom_catalog_service.embedding_native_cpu {purpose.upper()} "
        )
        assert command.count("${EOM_EMBEDDING_") == 5
        denied = set(" ".join(values["InaccessiblePaths"]).split())
        assert {
            "/mnt/nas",
            "/etc/eom",
            "/home/eom/EOM",
            "/home/eom/EOMIS",
            "/srv/eom/worker-homes",
            "/var/lib/eom-workflow-runner",
            "/run/eom-embedding-native-index",
            "/run/eom-embedding-native-query",
        } <= denied
        assert (
            not {"ReadWritePaths", "SupplementaryGroups", "WantedBy", "ExecStartPre"}
            & values.keys()
        )
        sources.append(
            source.replace(purpose.upper(), "PURPOSE").replace(
                f"native-{purpose}/%i/", "native-PURPOSE/%i/"
            )
        )
    assert sources[0] == sources[1]
