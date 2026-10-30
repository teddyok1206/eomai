"""Concrete fixed QUERY units; INDEX installation alone is not QUERY admission."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import ClassVar

from eom_workflow.native_reference_query_coordinator import (
    NativeQueryCheckpointVersion,
    NativeQueryExecutedV11,
)
from eom_workflow.reference_query_execution import (
    SupportedReferenceQueryNativeResult,
    validate_reference_query_native_result,
)
from jsonschema.exceptions import ValidationError as SchemaError

from eom_orchestrator.inference_transfer_cpu_handoff import (
    claim_native_cpu_dispatch,
    fixed_owner_identity,
)
from eom_orchestrator.inference_transfer_cpu_systemd import (
    CpuUnitObservation,
    inspect_cpu_unit,
    require_fixed_cpu_unit_template,
    require_native_cpu_environment_file,
)
from eom_orchestrator.native_embedding_cpu_execution import (
    NativeCpuExecutionError,
    native_cpu_unit_names,
    require_native_cpu_runtime_roots,
    run_fixed_native_cpu,
)
from eom_orchestrator.native_embedding_query_handoff import (
    PreparedNativeQuery,
    materialize_native_query_output,
    require_native_query_owner_root,
    validate_native_query_execution_id,
)

PREPARE_TEMPLATE = "eom-embedding-native-query-prepare@.service"
QUERY_TEMPLATE = "eom-embedding-native-cpu-query@.service"
PREPARE_TEMPLATE_SHA256 = "bbd6ca87732f9a8f0c19e1a6892bdf8d41ed08b1f1473d50918dfde0e7890ec7"
QUERY_TEMPLATE_SHA256 = "2335f5100b7678a202f67c334d2a8c196d04a77b2f2fa73d591a31a3a82533e8"


class NativeQueryLaunchError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def native_query_unit_names(execution_id: str) -> tuple[str, str]:
    return native_cpu_unit_names("QUERY", validate_native_query_execution_id(execution_id))


@dataclass(frozen=True, slots=True)
class FixedNativeQueryLauncher:
    """Explicit owner-selected hashes/callback, not worker/request-controlled settings."""

    cpu_environment_sha256: str
    owner_environment_sha256: str
    assert_runtime_current: Callable[[], None]
    checkpoint_schema_version: ClassVar[NativeQueryCheckpointVersion] = (
        "native-reference-query-coordinator/1.1"
    )

    def __post_init__(self) -> None:
        if not callable(self.assert_runtime_current) or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (self.cpu_environment_sha256, self.owner_environment_sha256)
        ):
            raise NativeQueryLaunchError("NATIVE_QUERY_CONFIGURATION_INVALID")

    def _installed(self) -> None:
        require_fixed_cpu_unit_template(PREPARE_TEMPLATE, PREPARE_TEMPLATE_SHA256)
        require_fixed_cpu_unit_template(QUERY_TEMPLATE, QUERY_TEMPLATE_SHA256)
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-cpu.env"), self.cpu_environment_sha256
        )
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-query-owner.env"), self.owner_environment_sha256
        )
        require_native_cpu_runtime_roots()
        require_native_query_owner_root()
        self.assert_runtime_current()

    def _observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        prepare, query = native_query_unit_names(execution_id)
        return inspect_cpu_unit(prepare, template=PREPARE_TEMPLATE), inspect_cpu_unit(
            query, template=QUERY_TEMPLATE
        )

    def observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        validate_native_query_execution_id(execution_id)
        self._installed()
        return self._observe(execution_id)

    def assert_current_runtime(self) -> None:
        self._installed()

    def completion_observation(
        self, prepared: PreparedNativeQuery, result: SupportedReferenceQueryNativeResult
    ) -> NativeQueryExecutedV11:
        """Observe successful original units, not a persisted-result or replay launch grant."""
        prepared.__post_init__()
        validate_reference_query_native_result(prepared.request, result)
        boot_file = Path("/proc/sys/kernel/random/boot_id")
        boot_id = boot_file.read_text(encoding="ascii").strip()
        prepare, query = self.observe(prepared.execution_id)
        if (
            not prepare.succeeded
            or not query.succeeded
            or boot_file.read_text(encoding="ascii").strip() != boot_id
        ):
            raise NativeQueryLaunchError("NATIVE_QUERY_COMPLETION_UNCERTAIN")
        try:
            return NativeQueryExecutedV11.model_validate(
                {
                    "boot_id": boot_id,
                    "prepare": {
                        "invocation_id": prepare.invocation_id,
                        "started_monotonic": prepare.status.exec_main_started_monotonic,
                        "exited_monotonic": prepare.exited_monotonic,
                    },
                    "query": {
                        "invocation_id": query.invocation_id,
                        "started_monotonic": query.status.exec_main_started_monotonic,
                        "exited_monotonic": query.exited_monotonic,
                    },
                    "prepare_template_sha256": "sha256:" + PREPARE_TEMPLATE_SHA256,
                    "query_template_sha256": "sha256:" + QUERY_TEMPLATE_SHA256,
                    "cpu_environment_sha256": "sha256:" + self.cpu_environment_sha256,
                    "owner_environment_sha256": "sha256:" + self.owner_environment_sha256,
                    "result_sha256": result.result_sha256,
                    "completed_observed_at": datetime.now(UTC),
                }
            )
        except ValueError:
            raise NativeQueryLaunchError("NATIVE_QUERY_COMPLETION_UNCERTAIN") from None

    def run(self, prepared: PreparedNativeQuery) -> SupportedReferenceQueryNativeResult:
        prepared.__post_init__()
        try:
            return run_fixed_native_cpu(
                purpose="QUERY",
                execution_id=prepared.execution_id,
                assert_runtime=self._installed,
                observe=self._observe,
                materialize=lambda: materialize_native_query_output(prepared),
                claim_start=lambda: claim_native_cpu_dispatch(
                    prepared.workspace,
                    prepared.association.association_sha256,
                    owner=fixed_owner_identity(),
                ),
            )
        except NativeQueryLaunchError:
            raise
        except NativeCpuExecutionError as error:
            raise NativeQueryLaunchError(
                error.code.replace("NATIVE_CPU_", "NATIVE_QUERY_")
            ) from None
        except (ValueError, SchemaError):
            raise NativeQueryLaunchError("NATIVE_QUERY_UNCERTAIN") from None
