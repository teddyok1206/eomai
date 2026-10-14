"""Concrete fixed QUERY units; INDEX installation alone is not QUERY admission."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from eom_catalog_contracts.embedding_reference_query import EmbeddingReferenceQueryResult
from eom_catalog_contracts.embedding_reference_query_v11 import validate_reference_query_result_v11
from eom_workflow.native_reference_query_coordinator import NativeQueryExecuted
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
    validate_native_query_execution_id,
)

PREPARE_TEMPLATE = "eom-embedding-native-query-prepare@.service"
QUERY_TEMPLATE = "eom-embedding-native-cpu-query@.service"
PREPARE_TEMPLATE_SHA256 = "4194d01ea9cffbc5468aac5f5f174303952e1008f8a8621ad1adea07ef76905f"
QUERY_TEMPLATE_SHA256 = "1bd18e257988df4b3e39eb486e208b999ae7e9e897905ca07f513fc5f3e7893b"


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
        self, prepared: PreparedNativeQuery, result: EmbeddingReferenceQueryResult
    ) -> NativeQueryExecuted:
        """Observe successful original units, not a persisted-result or replay launch grant."""
        prepared.__post_init__()
        validate_reference_query_result_v11(prepared.request, result)
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
            return NativeQueryExecuted.model_validate(
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

    def run(self, prepared: PreparedNativeQuery) -> EmbeddingReferenceQueryResult:
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
