"""Concrete original-launch owner composition; no worker sudo, new queue or model retries.

Concrete owner adapter; state/Artifact commit remain Orchestrator responsibilities.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

from eom_catalog_contracts.embedding_device_benchmark import (
    BenchmarkLaunchReceipt,
    BenchmarkOwnerRequest,
    BenchmarkStagedInputs,
    BenchmarkWorkerInvocation,
    benchmark_timeout_seconds,
    embedding_device_benchmark_bytes,
    validate_benchmark_invocation,
)
from eom_identifiers import sha256_bytes
from eom_orchestrator.embedding_device_benchmark_owner import BenchmarkLaunchAuthorization
from eom_orchestrator.inference_transfer_cpu_handoff import fixed_owner_identity
from eom_workflow.embedding_benchmark_launch_control import BenchmarkLaunchPrepared

from eom_catalog_service.embedding_benchmark_gpu_resource_client import (
    OwnerBenchmarkGpuResourceClient,
)
from eom_catalog_service.embedding_benchmark_handoff import capture_benchmark_runtime_installation
from eom_catalog_service.embedding_benchmark_launch import (
    BenchmarkLaunchPins,
    benchmark_launch_environment_bytes,
)
from eom_catalog_service.embedding_benchmark_launch_publication import (
    BenchmarkLaunchArtifactPublisher,
)
from eom_catalog_service.embedding_benchmark_launch_workspace import stage_owner_benchmark_launch
from eom_catalog_service.embedding_benchmark_native_connection import (
    CapturedBenchmarkNativeConnection,
)
from eom_catalog_service.embedding_benchmark_native_observation import (
    observe_benchmark_native_session,
)
from eom_catalog_service.embedding_benchmark_root_connection import (
    connect_benchmark_series_root,
    require_benchmark_series_listener,
)
from eom_catalog_service.embedding_benchmark_unit_policy import benchmark_unit_family
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins
from eom_catalog_service.embedding_runtime_files import (
    NumericalRuntimeFileSnapshots,
    fixed_native_embedding_profile,
)

# The fixed numeric environments intentionally stay immutable. Budgeted benchmark
# entrypoints live in the separately pinned owner release and are added to sys.path
# only by the exact 1200-second unit invocation.
_BUDGET1200_OWNER_RELEASE = "d381e6bc480606a828898ebe2e9942dd8a143677"
_BUDGET1200_OWNER_SITE = (
    Path("/opt/eom/embedding-owner-releases") / _BUDGET1200_OWNER_RELEASE / "site-packages"
)
_BUDGET1200_MODULE_SHA256 = {
    "embedding_benchmark_budget1200_cpu.py": (
        "sha256:600451a58941abd41f49b21effd5de5a244baa0a122ccb912208959b98acddb0"
    ),
    "embedding_benchmark_budget1200_cuda.py": (
        "sha256:04881926b1a09897bd036daedfe77e83b6eda0f79be11f505f7c7bb43d070b87"
    ),
    "embedding_benchmark_budget_entrypoint.py": (
        "sha256:57798ac413fc38fb1de6cc5a437ac9c3b7297d4dcc4dc3161ef055078e2c0cf7"
    ),
    "embedding_benchmark_unit_policy.py": (
        "sha256:d48ef789253e565b786bbc6a0e65a54c3db8be6289703978b9e41b50393a68c4"
    ),
}


class FixedBenchmarkLaunchExecution:
    """Installed caller selects both exact backends and a root-controller release.

    The protected one-shot root controller must already serve the original admitted
    owner stage. This adapter never starts privileged helpers, bypasses an admission
    or substitutes a new execution when a connection/result/commit is uncertain.
    """

    def __init__(
        self,
        request: BenchmarkOwnerRequest,
        *,
        cpu: NativeEmbeddingBackendPins,
        cuda: NativeEmbeddingBackendPins,
        controller_release: str,
        publisher: BenchmarkLaunchArtifactPublisher,
    ) -> None:
        embedding_device_benchmark_bytes(request)
        cpu.__post_init__()
        cuda.__post_init__()
        if (
            type(controller_release) is not str
            or re.fullmatch(r"[0-9a-f]{40}", controller_release, re.ASCII) is None
            or type(publisher) is not BenchmarkLaunchArtifactPublisher
            or publisher.source_commit != controller_release
        ):
            raise ValueError("BENCHMARK_EXECUTION_SELECTION_INVALID")
        self._request, self._cpu, self._cuda = request, cpu, cuda
        self._release, self._publisher = controller_release, publisher
        self._installation: tuple[NumericalRuntimeFileSnapshots, ...] | None = None

    def assert_installed(self, request: BenchmarkOwnerRequest) -> None:
        owner = fixed_owner_identity()
        if (
            os.getresuid() != (owner.owner_uid,) * 3
            or os.getresgid() != (owner.owner_gid,) * 3
            or request != self._request
        ):
            raise ValueError("BENCHMARK_EXECUTION_OWNER_OR_SELECTION_INVALID")
        require_benchmark_series_listener(request)
        if self._installation is None:
            files = NumericalRuntimeFileSnapshots(0)
            module_pins: dict[Path, str] = {}
            for device in ("CPU", "CUDA"):
                family = benchmark_unit_family(device, request.execution_policy)
                for name, digest in (
                    (family.service_template, family.service_sha256),
                    (family.socket_template, family.socket_sha256),
                ):
                    files.read(Path("/etc/systemd/system") / name, sha256=digest, maximum=65536)
            for runtime in (request.cpu, request.cuda):
                prefix = fixed_native_embedding_profile(runtime.profile).prefix
                files.observe_protected_member_identity(
                    prefix
                    / "lib/python3.12/site-packages/eom_catalog_service"
                    / "embedding_benchmark_entrypoint.py"
                )
                family = benchmark_unit_family(
                    runtime.numerical_runtime.device.kind, request.execution_policy
                )
                if family.timeout_seconds in {600, 1200}:
                    package_root = (
                        _BUDGET1200_OWNER_SITE
                        if family.timeout_seconds == 1200
                        else prefix / "lib/python3.12/site-packages"
                    )
                    for member in (
                        family.entrypoint_module.rsplit(".", 1)[-1] + ".py",
                        "embedding_benchmark_budget_entrypoint.py",
                        "embedding_benchmark_unit_policy.py",
                    ):
                        path = package_root / "eom_catalog_service" / member
                        if family.timeout_seconds == 1200:
                            digest = _BUDGET1200_MODULE_SHA256[member]
                            if module_pins.setdefault(path, digest) != digest:
                                raise ValueError("BENCHMARK_EXECUTION_MODULE_PIN_MISMATCH")
                        else:
                            files.observe_protected_member_identity(path)
            # Both devices share one immutable v1.2 package. Hash each exact member
            # once; duplicate references must agree and retained epochs fence reuse.
            for path, digest in module_pins.items():
                files.read(path, sha256=digest, maximum=65536)
            self._installation = (
                files,
                capture_benchmark_runtime_installation(request.cpu, backend=self._cpu),
                capture_benchmark_runtime_installation(request.cuda, backend=self._cuda),
            )
        for captured in self._installation:
            captured.assert_unchanged()

    def run_and_publish(
        self,
        invocation: BenchmarkWorkerInvocation,
        inputs: BenchmarkStagedInputs,
        authorization: BenchmarkLaunchAuthorization,
    ) -> BenchmarkLaunchReceipt:
        owner_started_ns = time.monotonic_ns()
        self.assert_installed(self._request)
        validate_benchmark_invocation(self._request, invocation, inputs)
        authorization.assert_invocation(invocation)
        if invocation.launch_ordinal > 1:
            authorization.require_cpu_reference()
        expires = (
            time.monotonic_ns() + benchmark_timeout_seconds(invocation.execution_policy) * 10**9
        )
        staged = stage_owner_benchmark_launch(
            self._request, invocation, inputs, authorization=authorization, expires_ns=expires
        )
        control, root_peer = connect_benchmark_series_root(
            self._request,
            staged.association,
            authorization=authorization,
            controller_release=self._release,
        )
        transport = None
        try:
            prepared = control.receive_prepared()
            if not isinstance(prepared, BenchmarkLaunchPrepared):
                raise ValueError("BENCHMARK_EXECUTION_ROOT_UNCERTAIN")
            backend = self._cpu if invocation.device == "CPU" else self._cuda
            expected_backend = dict(
                configuration_id=backend.configuration_id,
                configuration_revision_id=backend.configuration_revision_id,
                configuration_sha256=backend.configuration_sha256,
                configuration_raw_sha256=backend.configuration_raw_sha256,
                receipt_raw_sha256=backend.receipt_raw_sha256,
            )
            environment = benchmark_launch_environment_bytes(
                BenchmarkLaunchPins(
                    invocation.execution_id,
                    sha256_bytes(embedding_device_benchmark_bytes(invocation)),
                    staged.association.owner_pid,
                    expires,
                    backend,
                )
            )
            if prepared.backend.model_dump(
                mode="json"
            ) != expected_backend or prepared.environment_raw_sha256 != sha256_bytes(environment):
                raise ValueError("BENCHMARK_EXECUTION_ROOT_SELECTION_CHANGED")
            authorization.assert_invocation(invocation)
            transport = CapturedBenchmarkNativeConnection.connect(
                invocation, authorization=authorization, expires_ns=expires
            )
            if invocation.device == "CPU":
                observed = observe_benchmark_native_session(
                    transport,
                    invocation,
                    inputs,
                    authorization=authorization,
                    expires_ns=expires,
                    owner_started_ns=owner_started_ns,
                )
            else:
                with control.resources() as duplicate:
                    resources = OwnerBenchmarkGpuResourceClient(
                        duplicate,
                        invocation,
                        root_peer=root_peer,
                        authorization=authorization,
                        expires_ns=expires,
                    )
                    observed = observe_benchmark_native_session(
                        transport,
                        invocation,
                        inputs,
                        authorization=authorization,
                        expires_ns=expires,
                        gpu_resources=resources,
                        owner_started_ns=owner_started_ns,
                    )
            completion = control.receive_completed()
            authorization.assert_invocation(invocation)
            return self._publisher.publish(
                invocation, inputs, observed, prepared, completion, authorization=authorization
            )
        finally:
            if transport is not None:
                transport.close()
            control.close()
