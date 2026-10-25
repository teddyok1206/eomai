"""Real closed request parsing; synthetic cache, lease and model leaves, no devices."""

import json
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_gpu_lease import SHARED_GPU_LOCK_PATH
from eom_image_provider import cli

from tests.unit.test_local_image_provider import (
    _composite_request,
    _conditioned_request,
    _conditioned_request_v4,
    _conditioned_request_v6,
    _reference_png,
    _rgba_png,
    _store,
)


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize(
    ("operation", "factory", "reuse", "render"),
    [
        (
            "generate-composite",
            _composite_request,
            "reuse_composite_handoff",
            "generate_composite_handoff",
        ),
        (
            "generate-reference-composite",
            _conditioned_request,
            "reuse_reference_conditioned_composite_handoff",
            "generate_reference_conditioned_composite_handoff",
        ),
        (
            "generate-reference-style-composite",
            _conditioned_request_v4,
            "reuse_reference_conditioned_composite_handoff_v4",
            "generate_reference_conditioned_composite_handoff_v4",
        ),
        (
            "generate-reference-base-composite",
            _conditioned_request_v6,
            "reuse_reference_conditioned_composite_handoff_v6",
            "generate_reference_conditioned_composite_handoff_v6",
        ),
    ],
)
def test_generation_uses_original_budget_but_cached_result_never_reclaims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation,
    factory,
    reuse: str,
    render: str,
    cached: bool,
) -> None:
    model_store, manifest = _store(tmp_path)
    request = (
        factory(manifest, _rgba_png())
        if operation == "generate-composite"
        else factory(manifest, _rgba_png(), _reference_png())
    )
    original = request.model_dump(mode="json")
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(original), encoding="utf-8")
    request_path.chmod(0o640)
    receipt = SimpleNamespace(model_dump=lambda **_: {"synthetic_leaf": True})
    reused = Mock(return_value=receipt if cached else None)
    generated = Mock(return_value=receipt)
    monkeypatch.setattr(cli, reuse, reused)
    monkeypatch.setattr(cli, render, generated)
    leases: list[tuple[Path, int]] = []

    @contextmanager
    def lease(path: Path, *, busy_wait_seconds: int):
        leases.append((path, busy_wait_seconds))
        yield

    monkeypatch.setattr(cli, "acquire_gpu_lease", lease)
    arguments = [
        "eom-local-image",
        operation,
        "--request",
        str(request_path),
        "--model-store-root",
        str(model_store),
        "--workspace",
        str(tmp_path),
        "--gpu-lock",
        str(SHARED_GPU_LOCK_PATH),
    ]
    if operation == "generate-reference-style-composite":
        arguments += ["--style-adapter-store-root", str(tmp_path)]
    monkeypatch.setattr(sys, "argv", arguments)
    cli.main()
    budget = (
        request.generation.timeout_seconds
        if operation == "generate-composite"
        else request.composite_request.generation.timeout_seconds
    )
    assert leases == ([] if cached else [(SHARED_GPU_LOCK_PATH, budget)])
    assert generated.call_count == (0 if cached else 1)
    assert json.loads(request_path.read_text(encoding="utf-8")) == original
