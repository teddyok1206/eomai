"""Fixed native INDEX unit adapter; shared CPU capacity and invocation mechanics."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.inference_transfer_embedding import IncrementalEmbeddingResult
from jsonschema.exceptions import ValidationError as SchemaError

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
from eom_orchestrator.native_embedding_index_handoff import (
    PreparedNativeIndex,
    materialize_native_index_output,
    validate_native_index_execution_id,
)

PREPARE_TEMPLATE = "eom-embedding-native-index-prepare@.service"
INDEX_TEMPLATE = "eom-embedding-native-cpu-index@.service"
PREPARE_TEMPLATE_SHA256 = "d07b54290623ffef7997ac4a7bd0d836637da7e081fa0e95a13ac32dc794874c"
INDEX_TEMPLATE_SHA256 = "ad7180dd2c962082a069be79f2255b8d378050d61dc86d442d16ebceb8ee9380"


class NativeIndexLaunchError(ValueError):
    """BUSY and UNCERTAIN preserve ownership; neither permits another model execution."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def native_index_unit_names(execution_id: str) -> tuple[str, str]:
    return native_cpu_unit_names("INDEX", validate_native_index_execution_id(execution_id))


def _require_runtime_roots() -> None:
    try:
        require_native_cpu_runtime_roots()
    except NativeCpuExecutionError as error:
        raise NativeIndexLaunchError(error.code.replace("NATIVE_CPU_", "NATIVE_INDEX_")) from None


@dataclass(frozen=True, slots=True)
class FixedNativeIndexLauncher:
    """Installed-runtime callback comes from composition, never request data."""

    cpu_environment_sha256: str
    owner_environment_sha256: str
    assert_runtime_current: Callable[[], None]

    def __post_init__(self) -> None:
        if not callable(self.assert_runtime_current) or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (self.cpu_environment_sha256, self.owner_environment_sha256)
        ):
            raise NativeIndexLaunchError("NATIVE_INDEX_CONFIGURATION_INVALID")

    def _installed(self) -> None:
        require_fixed_cpu_unit_template(PREPARE_TEMPLATE, PREPARE_TEMPLATE_SHA256)
        require_fixed_cpu_unit_template(INDEX_TEMPLATE, INDEX_TEMPLATE_SHA256)
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-cpu.env"), self.cpu_environment_sha256
        )
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-owner.env"), self.owner_environment_sha256
        )
        _require_runtime_roots()
        self.assert_runtime_current()

    def _observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        prepare, index = native_index_unit_names(execution_id)
        return inspect_cpu_unit(prepare, template=PREPARE_TEMPLATE), inspect_cpu_unit(
            index, template=INDEX_TEMPLATE
        )

    def observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        """Exact-unit read only; no start, source grant or held capacity."""
        validate_native_index_execution_id(execution_id)
        self._installed()
        return self._observe(execution_id)

    def assert_current_runtime(self) -> None:
        self._installed()

    def run(self, prepared: PreparedNativeIndex) -> IncrementalEmbeddingResult:
        prepared = PreparedNativeIndex(
            prepared.execution_id, prepared.association, prepared.request
        )
        try:
            return run_fixed_native_cpu(
                purpose="INDEX",
                execution_id=prepared.execution_id,
                assert_runtime=self._installed,
                observe=self._observe,
                materialize=lambda: materialize_native_index_output(prepared),
            )
        except NativeIndexLaunchError:
            raise
        except NativeCpuExecutionError as error:
            raise NativeIndexLaunchError(
                error.code.replace("NATIVE_CPU_", "NATIVE_INDEX_")
            ) from None
        except (ValueError, SchemaError):
            raise NativeIndexLaunchError("NATIVE_INDEX_UNCERTAIN") from None
