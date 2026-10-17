"""Fixed private CPU units over the shared capacity and exact-invocation lifecycle."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from eom_catalog_contracts.embedding_private_chat_query import EmbeddingPrivateChatQueryResult

from eom_orchestrator.inference_transfer_cpu_handoff import (
    claim_native_cpu_dispatch,
    fixed_owner_identity,
    protected_cpu_handoff_directory,
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
from eom_orchestrator.native_private_chat_query_handoff import (
    RUNTIME_ROOT,
    NativePrivateQueryHandoffError,
    PreparedNativePrivateChatQuery,
    materialize_native_private_query_output,
    require_native_private_query_owner_root,
)

PREPARE_TEMPLATE = "eom-embedding-native-private-chat-query-prepare@.service"
QUERY_TEMPLATE = "eom-embedding-native-cpu-private-chat-query@.service"
PREPARE_TEMPLATE_SHA256 = "f3c9d2bad306b0f3f1ac35272d2af8d8957c7f8cfd16866695403da0cd4d7227"
QUERY_TEMPLATE_SHA256 = "cecb3128eaf33b0e897a813aab7ec4559ca26e63291fb7622a5c429826538bde"


class NativePrivateQueryLaunchError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class FixedNativePrivateQueryLauncher:
    """Owner-selected pins, not an authorization grant or worker-selectable backend."""

    cpu_environment_sha256: str
    owner_environment_sha256: str
    assert_runtime_current: Callable[[], None]

    def __post_init__(self) -> None:
        if not callable(self.assert_runtime_current) or any(
            type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None
            for value in (self.cpu_environment_sha256, self.owner_environment_sha256)
        ):
            raise NativePrivateQueryLaunchError("NATIVE_PRIVATE_QUERY_CONFIGURATION_INVALID")

    def assert_current_runtime(self) -> None:
        require_fixed_cpu_unit_template(PREPARE_TEMPLATE, PREPARE_TEMPLATE_SHA256)
        require_fixed_cpu_unit_template(QUERY_TEMPLATE, QUERY_TEMPLATE_SHA256)
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-cpu.env"), self.cpu_environment_sha256
        )
        require_native_cpu_environment_file(
            Path("/etc/eom/embedding-native-private-chat-query-owner.env"),
            self.owner_environment_sha256,
        )
        require_native_cpu_runtime_roots()
        require_native_private_query_owner_root()
        owner = fixed_owner_identity()
        with protected_cpu_handoff_directory(
            RUNTIME_ROOT, owner=owner, uid=0, gid=owner.owner_gid, mode=0o750
        ):
            pass
        self.assert_runtime_current()

    def _observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        prepare, query = native_cpu_unit_names("PRIVATE_CHAT_QUERY", execution_id)
        return inspect_cpu_unit(prepare, template=PREPARE_TEMPLATE), inspect_cpu_unit(
            query, template=QUERY_TEMPLATE
        )

    def observe(self, execution_id: str) -> tuple[CpuUnitObservation, CpuUnitObservation]:
        native_cpu_unit_names("PRIVATE_CHAT_QUERY", execution_id)
        self.assert_current_runtime()
        return self._observe(execution_id)

    def run(self, prepared: PreparedNativePrivateChatQuery) -> EmbeddingPrivateChatQueryResult:
        prepared.__post_init__()
        try:
            return run_fixed_native_cpu(
                purpose="PRIVATE_CHAT_QUERY",
                execution_id=prepared.execution_id,
                assert_runtime=self.assert_current_runtime,
                observe=self._observe,
                materialize=lambda: materialize_native_private_query_output(prepared),
                claim_start=lambda: claim_native_cpu_dispatch(
                    prepared.workspace,
                    prepared.association.association_sha256,
                    owner=fixed_owner_identity(),
                ),
            )
        except NativePrivateQueryHandoffError:
            raise
        except NativeCpuExecutionError as error:
            raise NativePrivateQueryLaunchError(
                error.code.replace("NATIVE_CPU_", "NATIVE_PRIVATE_QUERY_")
            ) from None
        except Exception:
            raise NativePrivateQueryLaunchError("NATIVE_PRIVATE_QUERY_UNCERTAIN") from None
