"""Fixed native DOCUMENT/QUERY descriptor handoffs; no launch, authority or publication."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from eom_catalog_contracts.embedding_private_chat_query import (
    MAX_PRIVATE_CHAT_QUERY_BYTES,
    EmbeddingPrivateChatQueryInput,
    validate_private_chat_query_result,
)
from eom_catalog_contracts.embedding_reference_query import (
    MAX_REFERENCE_QUERY_BYTES,
    EmbeddingReferenceQueryResult,
)
from eom_catalog_contracts.embedding_reference_query_v11 import (
    EmbeddingReferenceQueryInputV11,
    parse_embedding_reference_query_input_v11,
    validate_reference_query_result_v11,
)
from eom_catalog_contracts.embedding_vector_binary import (
    EmbeddingVectorBinaryError,
    read_unit_vectors,
)
from eom_catalog_contracts.embedding_work_batch import (
    MAX_EMBEDDING_WORK_BATCH_BYTES,
    EmbeddingWorkBatchInput,
    PublicSolutionWorkBatchInput,
    SupportedEmbeddingWorkBatchInput,
    parse_embedding_work_batch_input,
)
from eom_catalog_contracts.embedding_work_batch_result import (
    EmbeddingWorkBatchResult,
    PublicSolutionWorkBatchResult,
    SupportedEmbeddingWorkBatchResult,
    build_embedding_work_batch_result,
    embedding_work_batch_result_bytes,
)
from eom_catalog_contracts.inference_transfer_embedding import (
    MAX_EMBEDDING_INPUT_BYTES,
    EmbeddingVectorShardManifest,
    IncrementalEmbeddingInput,
    parse_incremental_embedding_input,
    validate_incremental_embedding_result,
)
from eom_catalog_contracts.public_solution_query import (
    PublicSolutionQueryInput,
    PublicSolutionQueryResult,
    validate_public_solution_query_result,
)
from eom_identifiers import canonical_json_bytes, sha256_bytes
from jsonschema.exceptions import ValidationError as JsonSchemaError
from pydantic import BaseModel

from eom_catalog_service.embedding_encoder_adapter import (
    IncrementalEmbeddingEncodeError,
    PrivateChatQueryEmbeddingEncodeError,
    ReferenceQueryEmbeddingEncodeError,
    encode_incremental_batch,
    encode_private_chat_query,
    encode_public_solution_query,
    encode_reference_query_batch,
)
from eom_catalog_service.embedding_execution_ports import NativeEmbeddingBackend
from eom_catalog_service.embedding_work_batch_execution import (
    EmbeddingWorkBatchExecutionError,
    EmbeddingWorkBatchExecutionResources,
    EmbeddingWorkBatchFence,
    execute_embedding_work_batch,
)

if TYPE_CHECKING:
    from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuControlChannel

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


def _read_payload(descriptor: int, initial: os.stat_result) -> tuple[bytes, dict[str, Any]]:
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
        return payload, value
    except NativeEmbeddingHandoffError:
        raise
    except (ValueError, TypeError, UnicodeError):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_REQUEST_INVALID") from None


def _read_canonical_request[InputValue: BaseModel](
    descriptor: int,
    initial: os.stat_result,
    parse: Callable[[dict[str, Any]], InputValue],
) -> InputValue:
    return _read_canonical_capture(descriptor, initial, parse)[0]


def _read_canonical_capture[InputValue: BaseModel](
    descriptor: int,
    initial: os.stat_result,
    parse: Callable[[dict[str, Any]], InputValue],
) -> tuple[InputValue, bytes]:
    payload, value = _read_payload(descriptor, initial)
    try:
        request = parse(value)
        if payload != canonical_json_bytes(request.model_dump(mode="json")):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_REQUEST_INVALID")
        return request, payload
    except NativeEmbeddingHandoffError:
        raise
    except (JsonSchemaError, ValueError, TypeError, UnicodeError):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_REQUEST_INVALID") from None


def _read_request(descriptor: int, initial: os.stat_result) -> IncrementalEmbeddingInput:
    return _read_canonical_request(descriptor, initial, parse_incremental_embedding_input)


def _read_reference_query(
    descriptor: int, initial: os.stat_result
) -> EmbeddingReferenceQueryInputV11:
    return _read_canonical_request(descriptor, initial, parse_embedding_reference_query_input_v11)


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
    return _write_contiguous_members(descriptor, initial, (payload,))


def _write_contiguous_members(
    descriptor: int, initial: os.stat_result, payloads: tuple[bytes, ...]
) -> os.stat_result:
    """Stream existing immutable buffers without constructing a concatenated copy."""
    _empty_output(descriptor, initial)
    total = 0
    for payload in payloads:
        remaining = memoryview(payload)
        while remaining:
            count = os.write(descriptor, remaining[:_CHUNK_BYTES])
            if count <= 0 or count > min(len(remaining), _CHUNK_BYTES):
                raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_WRITE_FAILED")
            remaining = remaining[count:]
        total += len(payload)
    os.fsync(descriptor)
    after = os.fstat(descriptor)
    if (
        _identity(initial) != _identity(after)
        or after.st_size != total
        or os.lseek(descriptor, 0, os.SEEK_CUR) != total
        or fcntl.fcntl(descriptor, fcntl.F_GETFL) & (os.O_ACCMODE | os.O_APPEND) != os.O_WRONLY
    ):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_OUTPUT_CHANGED")
    return after


def _prepare_descriptors(
    descriptors: NativeEmbeddingDescriptors, maximum_input_bytes: int
) -> tuple[os.stat_result, os.stat_result, os.stat_result]:
    raw = (descriptors.input, descriptors.result, descriptors.vectors)
    if any(type(value) is not int or value < 0 for value in raw) or len(set(raw)) != 3:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_DESCRIPTOR_INVALID")
    input_initial = _descriptor(descriptors.input, output=False)
    result_initial = _descriptor(descriptors.result, output=True)
    vectors_initial = _descriptor(descriptors.vectors, output=True)
    if input_initial.st_size > maximum_input_bytes:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_DESCRIPTOR_INVALID")
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
    return input_initial, result_initial, vectors_initial


def _ready_outputs(
    descriptors: NativeEmbeddingDescriptors,
    initial: tuple[os.stat_result, os.stat_result, os.stat_result],
) -> None:
    input_initial, result_initial, vectors_initial = initial
    _unchanged_input(descriptors.input, input_initial)
    _empty_output(descriptors.result, result_initial)
    _empty_output(descriptors.vectors, vectors_initial)


def _write_outputs(
    descriptors: NativeEmbeddingDescriptors,
    initial: tuple[os.stat_result, os.stat_result, os.stat_result],
    shard: EmbeddingVectorShardManifest,
    vectors: bytes,
    result_payload: bytes,
    maximum_result_bytes: int,
) -> None:
    input_initial, result_initial, vectors_initial = initial
    read_unit_vectors(
        vectors,
        dimension=shard.dimension,
        row_count=shard.row_count,
        expected_sha256=shard.binary.sha256,
    )
    if (
        len(vectors) != shard.binary.byte_count
        or not 0 < len(result_payload) <= maximum_result_bytes
    ):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
    _ready_outputs(descriptors, initial)
    vectors_final = _write_member(descriptors.vectors, vectors_initial, vectors)
    _unchanged_input(descriptors.input, input_initial)
    result_final = _write_member(descriptors.result, result_initial, result_payload)
    _require_finished_outputs(descriptors, input_initial, vectors_final, result_final)


def _require_finished_outputs(
    descriptors: NativeEmbeddingDescriptors,
    input_initial: os.stat_result,
    vectors_final: os.stat_result,
    result_final: os.stat_result,
) -> None:
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


@dataclass(frozen=True, slots=True)
class _CapturedWorkBatch:
    """One-call temporary FD observations, never an external capability or Artifact."""

    descriptors: NativeEmbeddingDescriptors
    initial: tuple[os.stat_result, os.stat_result, os.stat_result]
    request: SupportedEmbeddingWorkBatchInput
    input_raw_sha256: str
    input_byte_count: int


def _capture_work_batch(
    descriptors: NativeEmbeddingDescriptors,
    maximum_total_output_bytes: int,
    parse: Callable[[object], SupportedEmbeddingWorkBatchInput] = parse_embedding_work_batch_input,
) -> _CapturedWorkBatch:
    if (
        type(maximum_total_output_bytes) is not int
        or not 1 <= maximum_total_output_bytes <= MAX_EMBEDDING_INPUT_BYTES
    ):
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
    initial = _prepare_descriptors(descriptors, MAX_EMBEDDING_WORK_BATCH_BYTES)
    request, raw = _read_canonical_capture(descriptors.input, initial[0], parse)
    _ready_outputs(descriptors, initial)
    return _CapturedWorkBatch(descriptors, initial, request, sha256_bytes(raw), len(raw))


def run_native_embedding_work_batch_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
    *,
    resources: EmbeddingWorkBatchExecutionResources,
    maximum_total_output_bytes: int,
    fence: EmbeddingWorkBatchFence,
) -> EmbeddingWorkBatchResult:
    """Finite batch source-only FD seam; no lease acquisition, launch or Artifact commit.

    A separately admitted native owner must pin these resources/fences and enforce
    the hard process deadline. The input cannot select an interpreter, path or scope.
    Metadata is the last write, after every child and the whole binary are checked.
    """
    try:
        result = _execute_captured_work_batch(
            _capture_work_batch(descriptors, maximum_total_output_bytes),
            backend_scope,
            resources=resources,
            maximum_total_output_bytes=maximum_total_output_bytes,
            fence=fence,
        )
        if not isinstance(result, EmbeddingWorkBatchResult):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
        return result
    except (
        NativeEmbeddingHandoffError,
        EmbeddingWorkBatchExecutionError,
        EmbeddingVectorBinaryError,
    ):
        raise
    except OSError:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_IO_FAILED") from None
    except Exception:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_EXECUTION_FAILED") from None


def run_granted_native_embedding_gpu_batch_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
    *,
    resources: EmbeddingWorkBatchExecutionResources,
    maximum_total_output_bytes: int,
    channel: EmbeddingGpuControlChannel,
) -> EmbeddingWorkBatchResult:
    """Connect an original root grant to one FD batch and wait for actual output ACK.

    Caller separately admits native identity, unit, retained physical lease and backend.
    This adapter neither claims hardware nor authorizes sources nor commits any Artifact.
    A lost final ACK is an uncertain original execution, not permission to repeat/fallback.
    """
    try:
        from eom_catalog_service.embedding_gpu_control_channel import EmbeddingGpuControlChannel

        if type(channel) is not EmbeddingGpuControlChannel:
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_GRANT_INVALID")
        channel.assert_compute_granted()
        captured = _capture_work_batch(descriptors, maximum_total_output_bytes)
        if not isinstance(captured.request, EmbeddingWorkBatchInput):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_GRANT_INVALID")
        channel.bind_batch(
            captured.request,
            input_raw_sha256=captured.input_raw_sha256,
            input_byte_count=captured.input_byte_count,
        )
        result = _execute_captured_work_batch(
            captured,
            backend_scope,
            resources=resources,
            maximum_total_output_bytes=maximum_total_output_bytes,
            fence=channel,
        )
        if not isinstance(result, EmbeddingWorkBatchResult):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
        channel.announce_result(result)
        return result
    except (
        NativeEmbeddingHandoffError,
        EmbeddingWorkBatchExecutionError,
        EmbeddingVectorBinaryError,
    ):
        raise
    except OSError:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_IO_FAILED") from None
    except Exception:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_EXECUTION_FAILED") from None


def _execute_captured_work_batch(
    captured: _CapturedWorkBatch,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
    *,
    resources: EmbeddingWorkBatchExecutionResources,
    maximum_total_output_bytes: int,
    fence: EmbeddingWorkBatchFence,
) -> SupportedEmbeddingWorkBatchResult:
    descriptors, initial, request = captured.descriptors, captured.initial, captured.request
    if request.expected_vector_bytes >= maximum_total_output_bytes:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
    _ready_outputs(descriptors, initial)
    encoded = execute_embedding_work_batch(
        request, resources=resources, backend_scope=backend_scope, fence=fence
    )
    digest = hashlib.sha256()
    for child in encoded.children:
        shard = child.result.shard
        read_unit_vectors(
            child.vectors,
            dimension=shard.dimension,
            row_count=shard.row_count,
            expected_sha256=shard.binary.sha256,
        )
        digest.update(child.vectors)
    result = build_embedding_work_batch_result(
        request,
        tuple(child.result for child in encoded.children),
        "sha256:" + digest.hexdigest(),
    )
    payload = embedding_work_batch_result_bytes(result)
    if len(payload) + result.vectors.byte_count > maximum_total_output_bytes:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
    fence.assert_batch_current(request)
    for child_request in request.children:
        fence.assert_child_current(request, child_request)
    _ready_outputs(descriptors, initial)
    vectors_final = _write_contiguous_members(
        descriptors.vectors, initial[2], tuple(child.vectors for child in encoded.children)
    )
    _unchanged_input(descriptors.input, initial[0])
    result_final = _write_member(descriptors.result, initial[1], payload)
    _require_finished_outputs(descriptors, initial[0], vectors_final, result_final)
    fence.assert_batch_current(request)
    for child_request in request.children:
        fence.assert_child_current(request, child_request)
    return result


def _run_native_embedding_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    initial = _prepare_descriptors(descriptors, MAX_EMBEDDING_INPUT_BYTES)
    request = _read_request(descriptors.input, initial[0])
    _ready_outputs(descriptors, initial)
    # No request/descriptor is passed to construction: the owner pins runtime and ownership.
    with backend_scope() as backend:
        _ready_outputs(descriptors, initial)
        encoded = encode_incremental_batch(request, backend)
        validate_incremental_embedding_result(request, encoded.result)
        _write_outputs(
            descriptors,
            initial,
            encoded.result.shard,
            encoded.vectors,
            canonical_json_bytes(encoded.result.model_dump(mode="json")),
            MAX_EMBEDDING_INPUT_BYTES,
        )


def _run_native_reference_query_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    _run_native_query_descriptors(
        descriptors, backend_scope, parse=parse_embedding_reference_query_input_v11
    )


def _run_native_query_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
    *,
    parse: Callable[[object], EmbeddingReferenceQueryInputV11 | PublicSolutionQueryInput],
) -> None:
    initial = _prepare_descriptors(descriptors, MAX_REFERENCE_QUERY_BYTES)
    request = _read_canonical_request(descriptors.input, initial[0], parse)
    _ready_outputs(descriptors, initial)
    with backend_scope() as backend:
        _ready_outputs(descriptors, initial)
        result: PublicSolutionQueryResult | EmbeddingReferenceQueryResult
        if isinstance(request, PublicSolutionQueryInput):
            public_output = encode_public_solution_query(request, backend)
            validate_public_solution_query_result(request, public_output.result)
            result, vectors = public_output.result, public_output.vectors
        else:
            old_output = encode_reference_query_batch(request, backend)
            validate_reference_query_result_v11(request, old_output.result)
            result, vectors = old_output.result, old_output.vectors
        _write_outputs(
            descriptors,
            initial,
            result.shard,
            vectors,
            canonical_json_bytes(result.model_dump(mode="json")),
            MAX_REFERENCE_QUERY_BYTES,
        )


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


def run_native_reference_query_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    """Fixed QUERY handoff; owner identity/purpose/unit admission is separately mandatory."""
    try:
        _run_native_reference_query_descriptors(descriptors, backend_scope)
    except (
        NativeEmbeddingHandoffError,
        ReferenceQueryEmbeddingEncodeError,
        EmbeddingVectorBinaryError,
    ):
        raise
    except OSError:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_IO_FAILED") from None
    except Exception:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_EXECUTION_FAILED") from None


def run_native_public_solution_query_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    """Explicit QUERY2 seam; not an installed launch, grant or publication capability."""
    try:
        _run_native_query_descriptors(
            descriptors, backend_scope, parse=PublicSolutionQueryInput.model_validate
        )
    except (
        NativeEmbeddingHandoffError,
        ReferenceQueryEmbeddingEncodeError,
        EmbeddingVectorBinaryError,
    ):
        raise
    except OSError:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_IO_FAILED") from None
    except Exception:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_EXECUTION_FAILED") from None


def run_native_public_solution_work_batch_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
    *,
    resources: EmbeddingWorkBatchExecutionResources,
    maximum_total_output_bytes: int,
    fence: EmbeddingWorkBatchFence,
) -> PublicSolutionWorkBatchResult:
    """Use the existing bounded FD writer with explicit QUERY2 batch admission.

    The old batch1 and root GPU grant parsers remain closed. Caller still owns
    current authority, physical lease, completion observation and Artifact commit.
    """
    try:
        result = _execute_captured_work_batch(
            _capture_work_batch(
                descriptors, maximum_total_output_bytes, PublicSolutionWorkBatchInput.model_validate
            ),
            backend_scope,
            resources=resources,
            maximum_total_output_bytes=maximum_total_output_bytes,
            fence=fence,
        )
        if not isinstance(result, PublicSolutionWorkBatchResult):
            raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_RESULT_INVALID")
        return result
    except (
        NativeEmbeddingHandoffError,
        EmbeddingWorkBatchExecutionError,
        EmbeddingVectorBinaryError,
    ):
        raise
    except OSError:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_IO_FAILED") from None
    except Exception:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_EXECUTION_FAILED") from None


def run_native_private_chat_query_descriptors(
    descriptors: NativeEmbeddingDescriptors,
    backend_scope: Callable[[], AbstractContextManager[NativeEmbeddingBackend]],
) -> None:
    """Distinct source-only private handoff; an old reference unit/policy is not a grant."""
    try:
        initial = _prepare_descriptors(descriptors, MAX_PRIVATE_CHAT_QUERY_BYTES)
        request = _read_canonical_request(
            descriptors.input, initial[0], EmbeddingPrivateChatQueryInput.model_validate
        )
        _ready_outputs(descriptors, initial)
        with backend_scope() as backend:
            _ready_outputs(descriptors, initial)
            encoded = encode_private_chat_query(request, backend)
            validate_private_chat_query_result(request, encoded.result)
            _write_outputs(
                descriptors,
                initial,
                encoded.result.shard,
                encoded.vectors,
                canonical_json_bytes(encoded.result),
                MAX_PRIVATE_CHAT_QUERY_BYTES,
            )
    except (
        NativeEmbeddingHandoffError,
        PrivateChatQueryEmbeddingEncodeError,
        EmbeddingVectorBinaryError,
    ):
        raise
    except OSError:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_IO_FAILED") from None
    except Exception:
        raise NativeEmbeddingHandoffError("EMBEDDING_HANDOFF_EXECUTION_FAILED") from None
