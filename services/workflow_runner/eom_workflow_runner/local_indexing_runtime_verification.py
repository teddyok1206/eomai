"""Fixed protected no-forward verifier; never inherit controller credentials."""

from __future__ import annotations

import subprocess
from pathlib import Path

from eom_catalog_service.embedding_runtime_files import NumericalRuntimeFileSnapshots
from eom_workflow.local_indexing_owner_configuration import LocalIndexingRuntimeVerifierPin

_RELEASES = Path("/opt/eom/embedding-owner-releases")
_PYTHON = Path("/opt/eom/conda/envs/eom-embedding-index-cpu/bin/python3.12")
_ENV = {"PATH": "/usr/bin:/bin", "TZ": "UTC", "LANG": "C.UTF-8", "LC_ALL": "C"}


class FixedIndexingRuntimeVerification:
    """Current immutable script/prefix evidence, not service or source authority."""

    def __init__(self, pin: LocalIndexingRuntimeVerifierPin) -> None:
        checked = LocalIndexingRuntimeVerifierPin.model_validate(pin)
        self._files = NumericalRuntimeFileSnapshots()
        self._script = _RELEASES / checked.source_commit / "verify-runtime.py"
        self._files.read(self._script, sha256=checked.script_raw_sha256, maximum=64 * 1024)
        self._files.observe_protected_member_identity(_PYTHON)

    def assert_current(self) -> None:
        try:
            self._files.assert_unchanged()
            result = subprocess.run(
                (str(_PYTHON), "-I", "-B", str(self._script)),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=_ENV,
                check=False,
                timeout=60,
            )
            self._files.assert_unchanged()
            if result.returncode:
                raise ValueError("LOCAL_INDEXING_NUMERICAL_RUNTIME_UNAVAILABLE")
        except Exception:
            raise ValueError("LOCAL_INDEXING_NUMERICAL_RUNTIME_UNAVAILABLE") from None
