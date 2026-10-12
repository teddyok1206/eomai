"""Native indexing descriptor handoff; no launch, source authority or publication."""

from __future__ import annotations

import fcntl
import json
import os
import stat
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
    validate_incremental_embedding_result,
)
from eom_identifiers import canonical_json_bytes
from jsonschema.exceptions import ValidationError as JsonSchemaError

from eom_catalog_service.embedding_encoder_adapter import (
    IncrementalEmbeddingEncodeError,
    encode_incremental_batch,
)
from eom_catalog_service.embedding_execution_ports import NativeEmbeddingBackend

_ROOT_UID = 0
_CHUNK_BYTES = 1024**2


class NativeEmbeddingHandoffError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class NativeEmbeddingDescriptors:
    """Owner-created inherited FDs, not worker paths or an installed execution grant."""

    input: int
    result: int
    vectors: int


def _identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_uid,
        value.st_gid,
        value.st_mode,
        value.st_nlink,
    )


def _epoch(value: os.stat_result) -> tuple[int, ...]:
    return (*_identity(value), value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _descriptor(descriptor: int, *, output: bool) -> os.stat_result:
    if type(descriptor) is not int or descriptor < 0:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_DESCRIPTOR_INVALID")
    value = os.fstat(descriptor)
    flags = fcntl.fcntl(descriptor, fcntl.F_GETFL)
    if (
        not stat.S_ISREG(value.st_mode)
        or value.st_uid != _ROOT_UID
        or value.st_nlink != 1
        or stat.S_IMODE(value.st_mode) != (0o640 if output else 0o600)
        or flags & os.O_ACCMODE != (os.O_WRONLY if output else os.O_RDONLY)
        or flags & os.O_APPEND
        or os.lseek(descriptor, 0, os.SEEK_CUR) != 0
        or (value.st_size != 0 if output else not 0 < value.st_size <= MAX_EMBEDDING_INPUT_BYTES)
    ):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_DESCRIPTOR_INVALID")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, member in pairs:
        if key in value:
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_REQUEST_INVALID")
        value[key] = member
    return value


def _read_request(descriptor: int, initial: os.stat_result) -> IncrementalEmbeddingInput:
    chunks: list[bytes] = []
    total = 0
    while total <= initial.st_size:
        chunk = os.read(descriptor, min(_CHUNK_BYTES, initial.st_size + 1 - total))
        if not chunk:
            break
        total += len(chunk)
        if total > initial.st_size:
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_INPUT_CHANGED")
        chunks.append(chunk)
    if total != initial.st_size or _epoch(initial) != _epoch(os.fstat(descriptor)):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_INPUT_CHANGED")
    payload = b"".join(chunks)
    try:
        value = json.loads(payload, object_pairs_hook=_unique_object)
        if not isinstance(value, dict):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_REQUEST_INVALID")
        request = parse_incremental_embedding_input(value)
        if payload != canonical_json_bytes(request.model_dump(mode="json")):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_REQUEST_INVALID")
        return request
    except NativeEmbeddingHandoffError:
        raise
    except (JsonSchemaError, ValueError, TypeError, UnicodeError):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_REQUEST_INVALID") from None


def _unchanged_input(descriptor: int, initial: os.stat_result) -> None:
    if (
        _epoch(initial) != _epoch(os.fstat(descriptor))
        or os.lseek(descriptor, 0, os.SEEK_CUR) != initial.st_size
    ):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_INPUT_CHANGED")


def _empty_output(descriptor: int, initial: os.stat_result) -> None:
    if _epoch(_descriptor(descriptor, output=True)) != _epoch(initial):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_OUTPUT_CHANGED")


def _write_member(descriptor: int, initial: os.stat_result, payload: bytes) -> os.stat_result:
    _empty_output(descriptor, initial)
    remaining = memoryview(payload)
    while remaining:
        count = os.write(descriptor, remaining[:_CHUNK_BYTES])
        if count <= 0 or count > min(len(remaining), _CHUNK_BYTES):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_WRITE_FAILED")
        remaining = remaining[count:]
    os.fsync(descriptor)
    after = os.fstat(descriptor)
    if (
        _identity(initial) != _identity(after)
        or after.st_size != len(payload)
        or os.lseek(descriptor, 0, os.SEEK_CUR) != len(payload)
        or fcntl.fcntl(descriptor, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_APPEND) != os.O_WRONLY
    ):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_OUTPUT_CHANGED")
    return after


def _run_native_embedding_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    raw = (descriptors.input, descriptors.result, descriptors.vectors)
    if any(type(value) is not int or value < 0 for value in raw) or len(set(raw)) != 3:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_DESCRIPTOR_INVALID")
    input_initial = _descriptor(descriptors.input, output=False)
    result_initial = _descriptor(descriptors.result, output=True)
    vectors_initial = _descriptor(descriptors.vectors, output=True)
    if (
        len(
            {
                (value.st_dev, value.st_ino)
                for value in (input_initial, result_initial, vectors_initial)
            }
        )
        != 3
    ):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_DESCRIPTOR_ALIAS")
    request = _read_request(descriptors.input, input_initial)
    _empty_output(descriptors.result, result_initial)
    _empty_output(descriptors.vectors, vectors_initial)
    # No request/descriptor is passed to construction: the owner pins runtime and ownership.
    with backend_scope() as backend:
        _unchanged_input(descriptors.input, input_initial)
        _empty_output(descriptors.result, result_initial)
        _empty_output(descriptors.vectors, vectors_initial)
        encoded = encode_incremental_batch(request, backend)
        validate_incremental_embedding_result(request, encoded.result)
        shard = encoded.result.shard
        read_unit_vectors(
            encoded.vectors,
            dimension=shard.dimension,
            row_count=shard.row_count,
            expected_sha256=shard.binary.sha256,
        )
        if len(encoded.vectors) != shard.binary.byte_count:
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
        result_payload = canonical_json_bytes(encoded.result.model_dump(mode="json"))
        if not 0 < len(result_payload) <= MAX_EMBEDDING_INPUT_BYTES:
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
        _unchanged_input(descriptors.input, input_initial)
        _empty_output(descriptors.result, result_initial)
        vectors_final = _write_member(descriptors.vectors, vectors_initial, encoded.vectors)
        _unchanged_input(descriptors.input, input_initial)
        result_final = _write_member(descriptors.result, result_initial, result_payload)
        _unchanged_input(descriptors.input, input_initial)
        if (
            _epoch(vectors_final) != _epoch(os.fstat(descriptors.vectors))
            or _epoch(result_final) != _epoch(os.fstat(descriptors.result))
            or os.lseek(descriptors.vectors, 0, os.SEEK_CUR) != vectors_final.st_size
            or os.lseek(descriptors.result, 0, os.SEEK_CUR) != result_final.st_size
            or any(
                fcntl.fcntl(descriptor, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_APPEND) != os.O_WRONLY
                for descriptor in (descriptors.vectors, descriptors.result)
            )
        ):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_OUTPUT_CHANGED")


def run_native_embedding_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    """Write binary then completion JSON once; failures preserve partial local output.

    This source seam has no CLI/production composition. The installed owner must
    additionally verify worker/unit identity, inherited FD origins and cgroup exit.
    """
    try:
        _run_native_embedding_descriptors(descriptors, backend_scope)
    except (
        NativeEmbeddingHandoffError,
        IncrementalEmbeddingEncodeError,
        EmbeddingVectorBinaryError,
    ):
        raise
    except OSError:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_IO_FAILED") from None
    except Exception:
        # Third-party construction/encoding/context errors can contain admitted text.
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_EXECUTION_FAILED") from None
