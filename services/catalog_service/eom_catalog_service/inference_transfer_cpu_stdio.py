"""Installed CPU stdin/result-stdout adapter; never resolves corpus access or publishes."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import pwd
import re
import resource
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from eom_catalog_contracts.inference_transfer_experiment import (
    InferenceTransferExperimentRequest,
    InferenceTransferExperimentResult,
    validate_experiment_result,
)
from eom_catalog_contracts.validation import validate_contract
from eom_identifiers import canonical_json_bytes, content_sha256

from eom_catalog_service.inference_transfer_experiment import (
    run_staged_inference_transfer_experiment,
)
from eom_catalog_service.inference_transfer_ports import TokenMeasuredEmbeddingBackend
from eom_catalog_service.local_embedding_adapter import OfflineTransformersEmbeddingBackend

MODEL_STORE = Path("/opt/eom/embedding-models")
WORKER_USER = "eom-embedding-experiment"
MAXIMUM_MEMBER_BYTES = 64 * 1024**2
_ROOT_UID = 0
_EXECUTION = re.compile(r"embeddingexecution_[0-9a-f]{32}\Z", re.ASCII)


def measure_cpu_experiment(
    request: InferenceTransferExperimentRequest,
    backend: TokenMeasuredEmbeddingBackend,
    *,
    execution_id: str,
    created_at: datetime,
    model_load_milliseconds: int,
) -> InferenceTransferExperimentResult:
    """Shared numerical measurement recipe for standalone and installed interfaces."""
    result = run_staged_inference_transfer_experiment(
        request,
        backend,
        execution_id=execution_id,
        created_at=created_at,
        model_load_milliseconds=model_load_milliseconds,
    )
    body = result.model_dump(mode="json", exclude={"result_sha256"})
    body["measurements"]["peak_rss_kib_linux"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = InferenceTransferExperimentResult.model_validate(
        body | {"result_sha256": content_sha256(body)}
    )
    validate_experiment_result(request, result)
    return result


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise ValueError("INFERENCE_CPU_REQUEST_INVALID")
        value[key] = member
    return value


def _epoch(value: os.stat_result) -> tuple[int, int, int, int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def read_stdin_request(descriptor: int) -> InferenceTransferExperimentRequest:
    initial = os.fstat(descriptor)
    if (
        not stat.S_ISREG(initial.st_mode)
        or initial.st_uid != _ROOT_UID
        or initial.st_nlink != 1
        or stat.S_IMODE(initial.st_mode) != 0o600
        or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY
        or not 0 < initial.st_size <= MAXIMUM_MEMBER_BYTES
    ):
        raise ValueError("INFERENCE_CPU_INPUT_INVALID")
    chunks: list[bytes] = []
    total = 0
    while chunk := os.read(descriptor, min(1024**2, initial.st_size + 1 - total)):
        total += len(chunk)
        if total > initial.st_size:
            raise ValueError("INFERENCE_CPU_INPUT_CHANGED")
        chunks.append(chunk)
    if total != initial.st_size or _epoch(initial) != _epoch(os.fstat(descriptor)):
        raise ValueError("INFERENCE_CPU_INPUT_CHANGED")
    payload = b"".join(chunks)
    document = json.loads(payload, object_pairs_hook=_unique_object)
    if not isinstance(document, dict):
        raise ValueError("INFERENCE_CPU_REQUEST_INVALID")
    validate_contract("item-inference-transfer-experiment", document)
    request = InferenceTransferExperimentRequest.model_validate(document)
    if (
        payload != canonical_json_bytes(request.model_dump(mode="json"))
        or total > request.budget.maximum_input_bytes
    ):
        raise ValueError("INFERENCE_CPU_REQUEST_INVALID")
    return request


def write_stdout_result(descriptor: int, result: InferenceTransferExperimentResult) -> None:
    result = InferenceTransferExperimentResult.model_validate(result.model_dump(mode="json"))
    document = result.model_dump(mode="json")
    validate_contract("item-inference-transfer-experiment", document)
    payload = canonical_json_bytes(document)
    value = os.fstat(descriptor)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != _ROOT_UID
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != 0o640
        or value.st_size != 0
        or fcntl.fcntl(descriptor, fcntl.F_GETFL) & os.O_ACCMODE != os.O_WRONLY
        or not 0 < len(payload) <= MAXIMUM_MEMBER_BYTES
        or os.lseek(descriptor, 0, os.SEEK_CUR) != 0
    ):
        raise ValueError("INFERENCE_CPU_OUTPUT_INVALID")
    remaining = memoryview(payload)
    while remaining:
        count = os.write(descriptor, remaining)
        if count <= 0:
            raise ValueError("INFERENCE_CPU_OUTPUT_WRITE_FAILED")
        remaining = remaining[count:]
    os.fsync(descriptor)
    after = os.fstat(descriptor)
    if (value.st_dev, value.st_ino, value.st_uid, value.st_mode, value.st_nlink) != (
        after.st_dev,
        after.st_ino,
        after.st_uid,
        after.st_mode,
        after.st_nlink,
    ) or after.st_size != len(payload):
        raise ValueError("INFERENCE_CPU_OUTPUT_CHANGED")


@contextmanager
def _quiet_model_output() -> Iterator[int]:
    """Only the saved output FD receives JSON; library diagnostics never enter logs/results."""
    saved = os.dup(1)
    sink = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
    try:
        os.dup2(sink, 1)
        yield saved
    finally:
        try:
            sys.stdout.flush()
        finally:
            os.dup2(saved, 1)
            os.close(saved)
            os.close(sink)


def run_stdio(execution_id: str) -> None:
    if _EXECUTION.fullmatch(execution_id) is None:
        raise ValueError("INFERENCE_CPU_EXECUTION_ID_INVALID")
    worker = pwd.getpwnam(WORKER_USER)
    if worker.pw_uid <= 0 or os.geteuid() != worker.pw_uid:
        raise ValueError("INFERENCE_CPU_WORKER_IDENTITY_INVALID")
    request = read_stdin_request(0)
    input_epoch = _epoch(os.fstat(0))
    initial = os.fstat(1)
    if (
        not stat.S_ISREG(initial.st_mode)
        or initial.st_uid != _ROOT_UID
        or initial.st_nlink != 1
        or stat.S_IMODE(initial.st_mode) != 0o640
        or initial.st_size != 0
        or fcntl.fcntl(1, fcntl.F_GETFL) & os.O_ACCMODE != os.O_WRONLY
    ):
        raise ValueError("INFERENCE_CPU_OUTPUT_INVALID")
    with _quiet_model_output() as target:
        started = perf_counter()
        backend = OfflineTransformersEmbeddingBackend(
            MODEL_STORE,
            request.model_spec,
            expected_owner_uid=_ROOT_UID,
            batch_size=request.budget.batch_size,
            threads=request.budget.threads,
        )
        result = measure_cpu_experiment(
            request,
            backend,
            execution_id=execution_id,
            created_at=datetime.now(UTC),
            model_load_milliseconds=round(1000 * (perf_counter() - started)),
        )
        if result.backend_kind != "PINNED_MODEL":
            raise ValueError("INFERENCE_CPU_MODEL_PROVENANCE_INVALID")
        if _epoch(os.fstat(0)) != input_epoch:
            raise ValueError("INFERENCE_CPU_INPUT_CHANGED")
        write_stdout_result(target, result)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execution-id", required=True)
    arguments = parser.parse_args()
    try:
        run_stdio(arguments.execution_id)
    except Exception:
        # Third-party exceptions can contain input values; stderr is additionally
        # null in the fixed unit. An exit code is not a quality/authorization result.
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
