"""Shared real validators with synthetic installation ports; no positive OS/GPU claim."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace

import pytest
from eom_catalog_service import embedding_benchmark_cuda_capture as root
from eom_catalog_service import embedding_native_installation_admission as admission
from eom_catalog_service.embedding_native_backend_pins import NativeEmbeddingBackendPins

from tests.unit.test_embedding_cuda_installation_admission import state_for_metadata
from tests.unit.test_embedding_cuda_installation_evidence import DRAFT, metadata
from tests.unit.test_embedding_cuda_nvml_admission import DRAFT as DRAFT_V21
from tests.unit.test_embedding_cuda_nvml_admission import metadata as metadata_v21


@pytest.fixture(params=("2.0", "2.1"))
def state(monkeypatch, request):
    facts, schema = (metadata(), DRAFT) if request.param == "2.0" else (metadata_v21(), DRAFT_V21)
    value = state_for_metadata(monkeypatch, facts, schema)
    value.root = True

    def require_root():
        if not value.root:
            raise ValueError("BENCHMARK_UNIT_ROOT_REQUIRED")

    monkeypatch.setattr(root, "require_root_benchmark_control", require_root)
    # Root must not instantiate native admission or execute its selected interpreter.
    monkeypatch.setattr(
        admission,
        "require_native_runtime_interpreter",
        lambda *_: pytest.fail("root must not enter the native interpreter"),
    )
    return value


def pins(state):
    return NativeEmbeddingBackendPins(
        **state.configuration.model_dump(mode="python"),
        receipt_raw_sha256=state.receipt_pin,
    )


def test_root_capture_reuses_exact_shared_files_and_retains_host_until_scope_exit(state):
    with root.capture_root_benchmark_cuda_runtime(pins(state)) as runtime:
        assert type(runtime) is root.RootBenchmarkCudaRuntime
        runtime.inventory.assert_unchanged()
        runtime.host.assert_current()
        assert state.host_closes == state.resource_closes == 0
        assert len(state.reads) == len(set(state.reads)) == len(state.files)
    assert state.host_closes == state.resource_closes == 1
    assert not hasattr(runtime, "assert_owned")


@pytest.mark.parametrize("changed", ("files", "prefix", "host", "resources", "cwd", "device"))
def test_scope_exit_drift_is_not_a_success_and_still_closes_every_capture(state, changed):
    with (
        pytest.raises(admission.NativeInstallationAdmissionError, match="CHANGED"),
        root.capture_root_benchmark_cuda_runtime(pins(state)),
    ):
        state.broken = changed
    assert state.host_closes == state.resource_closes == 1


@pytest.mark.parametrize("field,value", (("uid", 0), ("groups", [2013]), ("boot", "changed")))
def test_current_account_group_and_boot_are_not_historical_permissions(state, field, value):
    with (
        pytest.raises(admission.NativeInstallationAdmissionError, match="CHANGED"),
        root.capture_root_benchmark_cuda_runtime(pins(state)),
    ):
        setattr(state, field, value)
    assert state.host_closes == state.resource_closes == 1


def test_original_body_failure_is_propagated_after_owned_cleanup(state):
    with (
        pytest.raises(RuntimeError, match="original finite controller failure"),
        root.capture_root_benchmark_cuda_runtime(pins(state)),
    ):
        raise RuntimeError("original finite controller failure")
    assert state.host_closes == state.resource_closes == 1


def test_lost_root_identity_fails_final_fence_and_still_closes_both_scopes(state):
    with (
        pytest.raises(ValueError, match="ROOT_REQUIRED"),
        root.capture_root_benchmark_cuda_runtime(pins(state)),
    ):
        state.root = False
    assert state.host_closes == state.resource_closes == 1


def test_wrong_root_identity_is_denied_before_any_protected_read(state):
    state.root = False
    with (
        pytest.raises(ValueError, match="ROOT_REQUIRED"),
        root.capture_root_benchmark_cuda_runtime(pins(state)),
    ):
        pytest.fail("wrong identity entered capture")
    assert not state.reads and state.host_closes == state.resource_closes == 0


@pytest.mark.parametrize(
    "field", ("configuration_sha256", "configuration_raw_sha256", "receipt_raw_sha256")
)
def test_each_independent_backend_hash_must_match_without_latest_fallback(state, field):
    wrong = replace(pins(state), **{field: "sha256:" + "f" * 64})
    with (
        pytest.raises(admission.NativeInstallationAdmissionError, match="CAPTURE_INVALID"),
        root.capture_root_benchmark_cuda_runtime(wrong),
    ):
        pytest.fail("changed pin entered capture")
    assert state.host_closes == state.resource_closes == 0


@pytest.mark.parametrize("broken", ("mount", "resolve", "prefix", "host_close", "resource_close"))
def test_failed_setup_or_cleanup_does_not_skip_owned_descriptor_retirement(state, broken):
    state.broken = broken
    with (
        pytest.raises(admission.NativeInstallationAdmissionError),
        root.capture_root_benchmark_cuda_runtime(pins(state)),
    ):
        pass
    expected = {
        "mount": (0, 1),
        "resolve": (0, 0),
        "prefix": (1, 1),
        "host_close": (1, 1),
        "resource_close": (1, 1),
    }
    assert (state.host_closes, state.resource_closes) == expected[broken]


def test_installed_series_composition_borrows_capture_for_one_existing_series(state, monkeypatch):
    selection = object.__new__(root.BenchmarkRootSeriesSelection)
    object.__setattr__(selection, "cuda", pins(state))
    checked, served = [], []
    monkeypatch.setattr(
        root.BenchmarkRootSeriesSelection, "__post_init__", lambda value: checked.append(value)
    )

    def serve(value, *, cuda):
        assert value is selection and state.host_closes == state.resource_closes == 0
        cuda.host.assert_current()
        served.append(value)
        return ()  # Selection/order/unit acceptance belongs to the existing series tests.

    monkeypatch.setattr(root, "serve_root_benchmark_series", serve)
    assert root.serve_installed_root_benchmark_series(selection) == ()
    assert checked == served == [selection]
    assert state.host_closes == state.resource_closes == 1


@pytest.mark.parametrize("phase", ("constructor", "enter"))
def test_interruption_before_context_ownership_returns_still_closes_files(
    state, monkeypatch, phase
):
    original = admission.ProtectedCudaInstallationFiles._assert_current
    checks = []

    def interrupted(value):
        checks.append(True)
        if len(checks) == (1 if phase == "constructor" else 2):
            raise KeyboardInterrupt("cancelled protected capture")
        original(value)

    monkeypatch.setattr(admission.ProtectedCudaInstallationFiles, "_assert_current", interrupted)
    with (
        pytest.raises(KeyboardInterrupt, match="cancelled protected capture"),
        root.capture_root_benchmark_cuda_runtime(pins(state)),
    ):
        pytest.fail("interrupted capture entered controller body")
    assert state.host_closes == state.resource_closes == 1


def test_actual_nonroot_is_rejected_without_any_installation_or_model_access():
    if os.geteuid() == 0:
        pytest.skip("genuine nonroot denial requires nonroot process")
    with (
        pytest.raises(ValueError, match="ROOT_REQUIRED"),
        root.capture_root_benchmark_cuda_runtime(None),
    ):
        pytest.fail("actual nonroot entered capture")


def test_root_adapter_import_does_not_import_numerical_or_cuda_resource_modules():
    code = """
import sys
import eom_catalog_service.embedding_benchmark_cuda_capture
for name in ('torch', 'transformers', 'sentence_transformers', 'numpy',
             'eom_catalog_service.embedding_cuda_probe_resource_files'):
    assert name not in sys.modules, name
print('ROOT_CAPTURE_IMPORT_SAFE=PASS')
"""
    completed = subprocess.run(
        [sys.executable, "-B", "-c", code], capture_output=True, text=True, check=True, timeout=15
    )
    assert completed.stdout.strip() == "ROOT_CAPTURE_IMPORT_SAFE=PASS" and not completed.stderr
