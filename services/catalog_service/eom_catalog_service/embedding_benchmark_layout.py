"""Closed POSIX ACL bytes shared by benchmark preparation and file capture."""

from __future__ import annotations

import re
import struct
from pathlib import Path
from typing import Literal

BENCHMARK_LIFETIME_ROOT = Path("/opt/eom/embedding-benchmark-lifetimes")
BENCHMARK_CUDA_LIFETIME_ROOT = BENCHMARK_LIFETIME_ROOT
BENCHMARK_HANDOFF_ROOT = Path("/run/eom-incremental-embeddings/benchmark")
BENCHMARK_CONTROL_ROOT = Path("/run/eom-incremental-embeddings/benchmark-control")


def benchmark_series_socket_name(benchmark_revision_id: str) -> str:
    """Storage label from the complete declared revision suffix, never a hash prefix."""
    match = (
        re.fullmatch(r"embeddingbenchmarkrev_([0-9a-f]{32})", benchmark_revision_id)
        if type(benchmark_revision_id) is str
        else None
    )
    if match is None:
        raise ValueError("BENCHMARK_SERIES_REVISION_INVALID")
    return "series-" + match[1] + ".sock"


def benchmark_read_acl(native_uid: int, kind: Literal["DIRECTORY", "INPUT"]) -> bytes:
    """Native reader plus owner group; no other named user or default grant."""
    if type(native_uid) is not int or not 0 < native_uid < 2**32 - 1:
        raise ValueError("benchmark native UID must be a positive POSIX identifier")
    if kind not in ("DIRECTORY", "INPUT"):
        raise ValueError("benchmark ACL kind must be DIRECTORY or INPUT")
    directory = kind == "DIRECTORY"
    permission = 5 if directory else 4
    undefined = 2**32 - 1
    return struct.pack("<I", 2) + b"".join(
        struct.pack("<HHI", tag, bits, identity)
        for tag, bits, identity in (
            (1, 7 if directory else 6, undefined),
            (2, permission, native_uid),
            (4, permission, undefined),
            (16, permission, undefined),
            (32, 0, undefined),
        )
    )
