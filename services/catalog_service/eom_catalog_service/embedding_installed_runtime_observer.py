"""Concrete source numerical observer; protected installation/sandbox acceptance stays separate."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType

from eom_catalog_contracts.embedding_installed_runtime_proof import (
    MAX_INSTALLED_RUNTIME_PROOF_BYTES,
    EmbeddingInstalledRuntimeProofPointer,
    parse_installed_runtime_proof,
    validate_installed_runtime_proof_pointer,
)
from jsonschema.exceptions import ValidationError as JsonSchemaError

from eom_catalog_service.embedding_execution_ports import (
    CudaEmbeddingOwnership,
    InstalledEmbeddingRuntimeObservation,
)
from eom_catalog_service.embedding_runtime_distribution import verify_installed_numeric_distribution
from eom_catalog_service.embedding_runtime_files import (
    InstalledRuntimeProofError,
    NumericalRuntimeFileSnapshots,
)
from eom_catalog_service.embedding_runtime_files import (
    require_runtime_proof as _require,
)
from eom_catalog_service.embedding_runtime_os_identity import (
    observe_runtime_device,
    require_native_runtime_interpreter,
)

_PROFILE_PREFIXES = MappingProxyType(
    {
        "CPU_INDEX_FP32": Path("/opt/eom/conda/envs/eom-embedding-index-cpu"),
        "CUDA_INDEX_FP32": Path("/opt/eom/conda/envs/eom-embedding-cuda"),
    }
)
_PROOF_ROOT = Path("/opt/eom/embedding-runtime-proofs")
_ARCHIVE_ROOT = Path("/opt/eom/embedding-runtime-archives")
_PROC_ROOT = Path("/proc")
_OWNER_UID = 0


@dataclass(frozen=True, slots=True)
class ConfiguredInstalledRuntimeProof:
    """Trusted owner admission pointer, never constructed from a worker request."""

    pointer: EmbeddingInstalledRuntimeProofPointer


class ProtectedInstalledEmbeddingRuntimeObserver:
    def __init__(
        self,
        configured: ConfiguredInstalledRuntimeProof,
        *,
        cuda_ownership: CudaEmbeddingOwnership | None = None,
    ) -> None:
        self._ownership = cuda_ownership
        try:
            self._pointer = EmbeddingInstalledRuntimeProofPointer.model_validate(
                configured.pointer.model_dump(mode="json")
            )
            self._cuda = self._pointer.profile == "CUDA_INDEX_FP32"
            _require(self._cuda or cuda_ownership is None, "CPU_OWNERSHIP_FORBIDDEN")
            self._require_owned()
            self._prefix = _PROFILE_PREFIXES[self._pointer.profile]
            self._files = NumericalRuntimeFileSnapshots(_OWNER_UID)
            path = (
                _PROOF_ROOT
                / self._pointer.proof_id
                / self._pointer.proof_revision_id
                / "proof.json"
            )
            raw = self._files.read(
                path,
                sha256=self._pointer.proof_raw_sha256,
                maximum=MAX_INSTALLED_RUNTIME_PROOF_BYTES,
            )
            self._proof = parse_installed_runtime_proof(json.loads(raw))
            validate_installed_runtime_proof_pointer(self._proof, self._pointer, raw)
            self._python = require_native_runtime_interpreter(self._prefix)
            self._files.observe_protected_interpreter(self._prefix / "bin/python3.12")
            verified = tuple(
                verify_installed_numeric_distribution(
                    library, prefix=self._prefix, archive_root=_ARCHIVE_ROOT, files=self._files
                )
                for library in self._proof.numeric_libraries
            )
            roots = {root for distribution in verified for root in distribution.namespace_roots}
            members = {
                member for distribution in verified for member in distribution.installed_members
            }
            self._files.require_closed_namespaces(roots, members)
            builds = [value.torch_version for value in verified if value.pin.name == "torch"]
            torch_pin = next(
                library for library in self._proof.numeric_libraries if library.name == "torch"
            )
            _require(
                builds == [(torch_pin.version, self._proof.torch_build_cuda_version)],
                "TORCH_BUILD_MISMATCH",
            )
            self._libraries = tuple(distribution.pin for distribution in verified)
            self.observe()
        except InstalledRuntimeProofError:
            raise
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            UnicodeError,
            JsonSchemaError,
        ) as exc:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_PROOF_INVALID") from exc

    def _require_owned(self) -> None:
        if self._cuda:
            _require(self._ownership is not None, "CUDA_OWNERSHIP_REQUIRED")
            assert self._ownership is not None
            try:
                self._ownership.assert_owned()
            except Exception as exc:
                raise InstalledRuntimeProofError(
                    "INSTALLED_RUNTIME_CUDA_OWNERSHIP_INVALID"
                ) from exc

    def observe(self) -> InstalledEmbeddingRuntimeObservation:
        """Recheck immutable epochs and actual live interpreter/OS; never accept expected DTO."""
        try:
            self._require_owned()
            self._files.assert_unchanged()
            python = require_native_runtime_interpreter(self._prefix)
            _require(python == self._python, "INTERPRETER_CHANGED")
            device = observe_runtime_device(
                self._proof.device_capture, proc_root=_PROC_ROOT, owner_uid=_OWNER_UID
            )
            self._files.assert_unchanged()
            self._require_owned()
            return InstalledEmbeddingRuntimeObservation(
                python, self._libraries, device, self._proof.torch_build_cuda_version
            )
        except InstalledRuntimeProofError:
            raise
        except (OSError, ValueError, TypeError, KeyError, AttributeError, UnicodeError) as exc:
            raise InstalledRuntimeProofError("INSTALLED_RUNTIME_OBSERVATION_INVALID") from exc
