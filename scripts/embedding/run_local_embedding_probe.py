#!/usr/bin/env python3
"""Bounded CPU probe with explanatory toy cases, not real corpus or human labels."""

from __future__ import annotations

import argparse
import importlib
import math
import os
import resource
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from eom_catalog_contracts.item_inference_transfer import LocalEmbeddingModelSpec
from eom_catalog_service.local_embedding_adapter import (
    LocalEmbeddingError,
    OfflineTransformersEmbeddingBackend,
)
from eom_identifiers import canonical_json_bytes, content_sha256

CASES = (
    (
        "parallel_springs",
        "두 용수철을 병렬로 연결하고 힘을 가한다. 탄성 계수 k1, k2인 용수철의 힘을 구한다.",
        "두 용수철의 변형량 x는 같다. F1=k1*x, F2=k2*x이다. "
        "전체 힘 F=F1+F2를 공통 변형량 x와 연결하여 각 힘을 분배한다.",
    ),
    (
        "parallel_resistors",
        "저항 R1, R2를 병렬로 연결한 회로에서 전체 전류가 주어질 때 각 전류를 구한다.",
        "두 저항의 전압 V는 같다. I1=V/R1, I2=V/R2이다. "
        "전체 전류 I=I1+I2를 공통 전압 V와 연결하여 각 전류를 분배한다.",
    ),
    (
        "series_springs",
        "두 용수철을 직렬로 연결하고 힘을 가한다. 탄성 계수 k1, k2인 용수철의 변형량을 구한다.",
        "두 용수철에 걸리는 힘 F는 같다. x1=F/k1, x2=F/k2이다. "
        "전체 변형량 x=x1+x2를 공통 힘 F와 연결하여 각 변형량을 구한다.",
    ),
    (
        "renamed_parallel_springs",
        "용수철 A, B를 병렬로 연결하고 힘을 가한다. 탄성 계수 2k, 3k인 용수철의 힘을 구한다.",
        "두 용수철의 변형량 x는 같다. FA=2k*x, FB=3k*x이다. "
        "전체 힘 F=FA+FB를 공통 변형량 x와 연결하여 각 힘을 분배한다.",
    ),
    (
        "energy_reverse_speed",
        "마찰이 없는 경사면에서 내려온 자동차의 높이를 이용해 속력을 구한다.",
        "계에 비보존력이 한 일이 없다. m*g*h+0.5*m*v^2의 합이 일정하므로 "
        "높이 감소를 운동 에너지 증가와 연결하여 보이지 않는 속력 v를 역으로 구한다.",
    ),
    (
        "momentum_collision",
        "마찰이 없는 수평면에서 두 자동차가 충돌한 뒤 함께 움직일 때 속력을 구한다.",
        "충돌 중 두 자동차를 포함한 계의 외부 충격량이 0이다. 운동량의 합이 일정하므로 "
        "m1*v1+m2*v2=(m1+m2)*v_after를 사용한다. 운동 에너지 보존은 가정하지 않는다.",
    ),
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-store", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not args.output.is_absolute() or args.output.exists() or args.output.is_symlink():
        raise ValueError("an explicit new absolute local output path is required")
    if args.output.parent.resolve() != args.output.parent:
        raise ValueError("output workspace must not contain symlink ancestors")
    workspace = args.output.parent.stat()
    if workspace.st_uid != os.geteuid() or workspace.st_mode & 0o022:
        raise ValueError("output workspace must be owned and nonwritable by others")
    if args.manifest.stat().st_size > 128 * 1024 or args.manifest.is_symlink():
        raise ValueError("bounded nonsymlink model manifest required")
    spec = LocalEmbeddingModelSpec.model_validate_json(args.manifest.read_bytes())
    torch = importlib.import_module("torch")
    torch.set_num_threads(4)
    started = perf_counter()
    backend = OfflineTransformersEmbeddingBackend(
        args.model_store, spec, expected_owner_uid=os.geteuid(), batch_size=4
    )
    load_seconds = perf_counter() - started
    reports = []
    for name, column in (("content_only", 1), ("concrete_inference", 2)):
        texts = tuple(case[column] for case in CASES)
        started = perf_counter()
        vectors = backend.encode(texts, purpose="DOCUMENT")
        encode_seconds = perf_counter() - started
        repeated = backend.encode(texts, purpose="DOCUMENT")
        max_repeat_delta = max(
            abs(a - b)
            for left, right in zip(vectors, repeated, strict=True)
            for a, b in zip(left, right, strict=True)
        )
        ranking: list[dict[str, Any]] = [
            {
                "case_id": CASES[index][0],
                "cosine_millionths": round(
                    1_000_000 * math.fsum(a * b for a, b in zip(vectors[0], vector, strict=True))
                ),
            }
            for index, vector in enumerate(vectors[1:], start=1)
        ]
        ranking.sort(key=lambda row: (-row["cosine_millionths"], row["case_id"]))
        reports.append(
            {
                "view": name,
                "input_set_sha256": content_sha256(texts),
                "documents": len(texts),
                "encode_milliseconds": round(1000 * encode_seconds),
                "repeat_max_abs_delta_billionths": round(1_000_000_000 * max_repeat_delta),
                "ranking": ranking,
            }
        )
    overflow = "NOT_CHECKED"
    try:
        backend.encode(("마찰은 존재하며 외력이 에너지에 영향을 준다. " * 1000,), purpose="QUERY")
    except LocalEmbeddingError as exc:
        if exc.code != "LOCAL_EMBEDDING_INPUT_TOO_LONG":
            raise
        overflow = "REJECTED_BEFORE_INFERENCE"
    if overflow == "NOT_CHECKED":
        raise ValueError("oversized input was silently admitted")
    body = {
        "experiment_kind": "LOCAL_CPU_TOY_PROBE_NOT_CORPUS_ACCEPTANCE",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "model_spec": spec.model_dump(mode="json"),
        "threads": 4,
        "load_milliseconds": round(1000 * load_seconds),
        "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "encoding_commands": 4,
        "encoded_text_count": 24,
        "overflow_commands": 1,
        "overflow_policy": overflow,
        "reports": reports,
        "network_mode": "DEVELOPMENT_PROCESS_OFFLINE_MODEL_FLAGS",
        "production_activation": "NOT_PERFORMED",
        "human_transfer_review": "NOT_EVALUATED",
        "actual_corpus_retrieval": "NOT_PERFORMED",
    }
    document = {**body, "result_sha256": content_sha256(body)}
    descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(canonical_json_bytes(document))
    print(f"CPU_EMBEDDING_TOY_PROBE_RESULT={args.output}")
    print(f"CPU_EMBEDDING_TOY_PROBE_SHA256={document['result_sha256']}")
    print(f"MODEL_LOAD_SECONDS={load_seconds:.3f}")
    print(f"PEAK_RSS_KIB_LINUX={body['peak_rss_kib_linux']}")
    print("HUMAN_TRANSFER_REVIEW=NOT_EVALUATED")
    print("PRODUCTION_ACTIVATION=NOT_PERFORMED")


if __name__ == "__main__":
    main()
