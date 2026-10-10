#!/usr/bin/env python3
"""Run one frozen local CPU experiment; does not acquire models or authorize corpus access."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

from eom_catalog_contracts.inference_transfer_experiment import (
    InferenceTransferExperimentRequest,
    InferenceTransferExperimentResult,
    validate_experiment_result,
)
from eom_catalog_contracts.validation import validate_contract
from eom_catalog_service.inference_transfer_cpu_stdio import measure_cpu_experiment
from eom_catalog_service.local_embedding_adapter import OfflineTransformersEmbeddingBackend
from eom_identifiers import canonical_json_bytes
from jsonschema.exceptions import ValidationError as SchemaValidationError

_MAXIMUM_INPUT_BYTES = 64 * 1024**2


def execution_id(value: str) -> str:
    if re.fullmatch(r"embeddingexecution_[0-9a-f]{32}", value) is None:
        raise argparse.ArgumentTypeError("INFERENCE_EXPERIMENT_EXECUTION_ID_INVALID")
    return value


def _workspace(path: Path) -> Path:
    if not path.is_absolute() or ".." in path.parts or Path("/mnt/nas") in (path, *path.parents):
        raise ValueError("INFERENCE_EXPERIMENT_LOCAL_WORKSPACE_REQUIRED")
    for node in (path, *path.parents):
        value = node.lstat()
        sticky_root = value.st_uid == 0 and bool(value.st_mode & stat.S_ISVTX)
        if (
            stat.S_ISLNK(value.st_mode)
            or value.st_uid not in {0, os.geteuid()}
            or (value.st_mode & 0o022 and not sticky_root)
        ):
            raise ValueError("INFERENCE_EXPERIMENT_WORKSPACE_INVALID")
    value = path.stat()
    if not stat.S_ISDIR(value.st_mode) or value.st_uid != os.geteuid() or value.st_mode & 0o022:
        raise ValueError("INFERENCE_EXPERIMENT_WORKSPACE_INVALID")
    return path


def _open_workspace(path: Path) -> int:
    descriptor = os.open(
        _workspace(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    value = os.fstat(descriptor)
    if value.st_uid != os.geteuid() or value.st_mode & 0o022:
        os.close(descriptor)
        raise ValueError("INFERENCE_EXPERIMENT_WORKSPACE_INVALID")
    return descriptor


def _member(workspace: Path, name: str) -> Path:
    if not name or name in {".", ".."} or Path(name).name != name or "\\" in name:
        raise ValueError("INFERENCE_EXPERIMENT_MEMBER_INVALID")
    return workspace / name


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("INFERENCE_EXPERIMENT_DUPLICATE_JSON_MEMBER")
        result[key] = value
    return result


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def read_request(
    workspace: Path, name: str, expected_sha256: str
) -> InferenceTransferExperimentRequest:
    _member(_workspace(workspace), name)
    directory = _open_workspace(workspace)
    try:
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or not 0 < before.st_size <= _MAXIMUM_INPUT_BYTES
        ):
            raise ValueError("INFERENCE_EXPERIMENT_INPUT_INVALID")
        chunks: list[bytes] = []
        observed = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            observed += len(chunk)
            if observed > _MAXIMUM_INPUT_BYTES:
                raise ValueError("INFERENCE_EXPERIMENT_INPUT_TOO_LARGE")
            chunks.append(chunk)
        if observed != before.st_size or _identity(before) != _identity(os.fstat(descriptor)):
            raise ValueError("INFERENCE_EXPERIMENT_INPUT_CHANGED")
    finally:
        os.close(descriptor)
    body = json.loads(b"".join(chunks), object_pairs_hook=_unique_object)
    if not isinstance(body, dict):
        raise ValueError("INFERENCE_EXPERIMENT_INPUT_INVALID")
    validate_contract("item-inference-transfer-experiment", body)
    request = InferenceTransferExperimentRequest.model_validate(body)
    if observed > request.budget.maximum_input_bytes or request.request_sha256 != expected_sha256:
        raise ValueError("INFERENCE_EXPERIMENT_INPUT_PIN_OR_BUDGET_MISMATCH")
    return request


def write_result(workspace: Path, name: str, result: InferenceTransferExperimentResult) -> None:
    result = InferenceTransferExperimentResult.model_validate(result.model_dump(mode="json"))
    body = result.model_dump(mode="json")
    validate_contract("item-inference-transfer-experiment", body)
    payload = canonical_json_bytes(body) + b"\n"
    _member(_workspace(workspace), name)
    directory = _open_workspace(workspace)
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
    finally:
        os.close(directory)
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise ValueError("INFERENCE_EXPERIMENT_OUTPUT_WRITE_FAILED")
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument(
        "--request", default="request.json", help="one filename inside local workspace"
    )
    parser.add_argument(
        "--request-sha256", required=True, help="expected canonical request identity"
    )
    parser.add_argument(
        "--output",
        default="result.json",
        help="new filename; existing outputs are never overwritten",
    )
    parser.add_argument("--model-store", type=Path, required=True)
    parser.add_argument("--model-owner-uid", type=int, default=0)
    parser.add_argument(
        "--execution-id",
        type=execution_id,
        help="owner-pinned identity; omitted standalone invocations retain a new random identity",
    )
    args = parser.parse_args()
    request = read_request(args.workspace, args.request, args.request_sha256)
    _member(_workspace(args.workspace), args.output)
    # Checked before the expensive local forward. O_EXCL remains the final concurrency guard.
    if (args.workspace / args.output).exists() or (args.workspace / args.output).is_symlink():
        raise ValueError("INFERENCE_EXPERIMENT_OUTPUT_ALREADY_EXISTS")
    started = perf_counter()
    backend = OfflineTransformersEmbeddingBackend(
        args.model_store,
        request.model_spec,
        expected_owner_uid=args.model_owner_uid,
        batch_size=request.budget.batch_size,
        threads=request.budget.threads,
    )
    result = measure_cpu_experiment(
        request,
        backend,
        execution_id=args.execution_id or "embeddingexecution_" + uuid4().hex,
        created_at=datetime.now(UTC),
        model_load_milliseconds=round(1000 * (perf_counter() - started)),
    )
    validate_experiment_result(request, result)
    write_result(args.workspace, args.output, result)
    print(f"EXPERIMENT_STATUS={result.status}")
    print(f"DATA_PROVENANCE={result.data_provenance}")
    print(f"RESULT_SHA256={result.result_sha256}")
    print("HUMAN_TRANSFER_REVIEW=NOT_EVALUATED")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, SchemaValidationError):
        # No staged Item text, validation payload, traceback or authority field is emitted.
        print("EXPERIMENT_EXECUTION=FAILED_INPUT_RUNTIME_OR_OUTPUT_BOUNDARY")
        raise SystemExit(1) from None
