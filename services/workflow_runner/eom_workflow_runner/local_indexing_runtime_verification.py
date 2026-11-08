"""Fixed protected no-forward verifier; never inherit controller credentials."""

from __future__ import annotations

import subprocess
from enum import StrEnum
from pathlib import Path

from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_workflow.local_indexing_owner_configuration import LocalIndexingRuntimeVerifierPin

_RELEASES = Path("/opt/eom/embedding-owner-releases")
_PYTHON = Path("/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python3.12")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C"}


class IndexingRuntimeFailureReason(StrEnum):
    FILES_CHANGED = "RUNTIME_FILES_CHANGED"
    VERIFIER_TIMEOUT = "RUNTIME_VERIFIER_TIMEOUT"
    VERIFIER_EXECUTION_FAILED = "RUNTIME_VERIFIER_EXECUTION_FAILED"
    VERIFIER_REJECTED = "RUNTIME_VERIFIER_REJECTED"
    CONTROLS_MISMATCH = "RUNTIME_CONTROLS_MISMATCH"
    OS_UNAVAILABLE = "RUNTIME_OS_UNAVAILABLE"
    BOUNDARY_REJECTED = "RUNTIME_BOUNDARY_REJECTED"
    UNEXPECTED_FAILURE = "RUNTIME_UNEXPECTED_FAILURE"


class IndexingRuntimeVerificationError(ValueError):
    """Keep the public error stable; only a closed, nonsecret reason crosses the adapter."""

    def __init__(self, reason: IndexingRuntimeFailureReason) -> None:
        self.reason = IndexingRuntimeFailureReason(reason)
        self.code = self.reason.value
        super().__init__("LOCAL_INDEXING_NUMERICAL_RUNTIME_UNAVAILABLE")


def indexing_runtime_failure_reason(error: ValueError | OSError) -> IndexingRuntimeFailureReason:
    if isinstance(error, IndexingRuntimeVerificationError):
        return error.reason
    if type(error) is ValueError and error.args == ("LOCAL_EMBEDDING_EXECUTOR_CONTROLS_MISMATCH",):
        return IndexingRuntimeFailureReason.CONTROLS_MISMATCH
    if isinstance(error, OSError):
        return IndexingRuntimeFailureReason.OS_UNAVAILABLE
    return IndexingRuntimeFailureReason.BOUNDARY_REJECTED


class FixedIndexingRuntimeVerification:
    """Current immutable script/prefix evidence, not service or source authority."""

    def __init__(self, pin: LocalIndexingRuntimeVerifierPin) -> None:
        checked = LocalIndexingRuntimeVerifierPin.model_validate(pin)
        self._files = NumericalRuntimeFileSnapshots()
        self._script = _RELEASES / checked.source_commit / "verify-runtime.py"
        self._files.read(self._script, sha256=checked.script_raw_sha256, maximum=64 * 1024)
        self._files.observe_protected_member_identity(_PYTHON)

    def _assert_files_current(self) -> None:
        try:
            self._files.assert_unchanged()
        except (ValueError, OSError):
            raise IndexingRuntimeVerificationError(
                IndexingRuntimeFailureReason.FILES_CHANGED
            ) from None

    def assert_current(self) -> None:
        try:
            self._assert_files_current()
            result = subprocess.run(
                (str(_PYTHON), "-I", "-B", str(self._script)),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_ENV,
                check=False,
                timeout=60,
            )
            self._assert_files_current()
            if result.returncode:
                raise IndexingRuntimeVerificationError(
                    IndexingRuntimeFailureReason.VERIFIER_REJECTED
                )
        except IndexingRuntimeVerificationError:
            raise
        except (subprocess.TimeoutExpired, TimeoutError):
            raise IndexingRuntimeVerificationError(
                IndexingRuntimeFailureReason.VERIFIER_TIMEOUT
            ) from None
        except OSError:
            raise IndexingRuntimeVerificationError(
                IndexingRuntimeFailureReason.VERIFIER_EXECUTION_FAILED
            ) from None
        except Exception:
            raise IndexingRuntimeVerificationError(
                IndexingRuntimeFailureReason.UNEXPECTED_FAILURE
            ) from None
