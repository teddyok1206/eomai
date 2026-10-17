"""Synthetic scoped CUDA composition only; no installed receipt, physical lease or model."""

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_catalog_service import embedding_cuda_probe_resource_files as resources
from eom_catalog_service import embedding_native_cuda_backend as module
from eom_catalog_service import embedding_native_factory as factory
from eom_catalog_service import embedding_native_installation_admission as installed


def configuration():
    return RootLocalNativeConfigurationPin(
        configuration_id="embeddingnativeconfig_" + "a" * 32,
        configuration_revision_id="embeddingnativeconfigrev_" + "b" * 32,
        configuration_sha256="sha256:" + "c" * 64,
        configuration_raw_sha256="sha256:" + "d" * 64,
    )


@pytest.mark.parametrize(
    "fault",
    (
        None,
        "identity",
        "owned-1",
        "receipt",
        "admission-enter",
        "owned-2",
        "factory",
        "backend-enter",
        "owned-3",
        "body",
        "owned-4",
        "backend-close",
        "admission-close",
        "owned-5",
    ),
)
def test_owned_device_outlives_exact_cuda_receipt_backend_and_all_failures(monkeypatch, fault):
    events = []
    pin = configuration()
    backend = object()

    def event(value):
        events.append(value)
        if fault == value:
            raise ValueError("synthetic-" + value)

    def identity(profile):
        assert profile == "CUDA_INDEX_FP32"
        event("identity")

    class Ownership:
        def __init__(self):
            self.calls = 0

        def assert_owned(self):
            self.calls += 1
            event("owned-" + str(self.calls))

        def close(self):
            pytest.fail("borrowed physical ownership was closed by the backend adapter")

    class Admission:
        def __init__(self, observed, *, expected_receipt_raw_sha256):
            assert observed == pin and expected_receipt_raw_sha256 == "sha256:" + "e" * 64
            event("receipt")

        def __enter__(self):
            event("admission-enter")
            return self

        def __exit__(self, *_args):
            event("admission-close")

    owned = Ownership()

    def scope_factory(**arguments):
        event("factory")
        assert arguments == {
            "profile": "CUDA_INDEX_FP32",
            "configuration_id": pin.configuration_id,
            "configuration_revision_id": pin.configuration_revision_id,
            "configuration_raw_sha256": pin.configuration_raw_sha256,
            "admission": arguments["admission"],
            "cuda_ownership": owned,
        }
        assert type(arguments["admission"]) is Admission

        @contextmanager
        def scope():
            event("backend-enter")
            try:
                yield backend
            finally:
                event("backend-close")

        return scope

    monkeypatch.setattr(module, "require_native_embedding_identity", identity)
    monkeypatch.setattr(resources, "OpenedCudaProbeDeviceAccess", Ownership)
    monkeypatch.setattr(installed, "ProtectedNativeCudaEmbeddingInstallationAdmission", Admission)
    monkeypatch.setattr(factory, "native_embedding_backend_scope", scope_factory)

    def execute():
        with module.native_cuda_backend_scope(
            pin, receipt_raw_sha256="sha256:" + "e" * 64, ownership=owned
        ) as observed:
            assert observed is backend
            event("body")

    if fault is None:
        execute()
        assert events == [
            "identity",
            "owned-1",
            "receipt",
            "admission-enter",
            "owned-2",
            "factory",
            "backend-enter",
            "owned-3",
            "body",
            "owned-4",
            "backend-close",
            "admission-close",
            "owned-5",
        ]
    else:
        with pytest.raises(ValueError, match="synthetic"):
            execute()
        assert events[0] == "identity" and fault in events
        if fault in {"identity", "owned-1"}:
            assert "receipt" not in events
        elif fault in {"receipt", "admission-enter", "owned-2"}:
            assert "backend-enter" not in events
        if "backend-enter" in events and fault != "backend-enter":
            assert "backend-close" in events
        if "admission-enter" in events and fault != "admission-enter":
            assert "admission-close" in events


@pytest.mark.parametrize(
    "fault", ("pin_type", "ownership", "receipt_type", "receipt_hash", "changed_pin")
)
def test_untyped_or_changed_pins_and_structural_callback_are_not_physical_ownership(
    monkeypatch, fault
):
    events = []
    monkeypatch.setattr(
        module, "require_native_embedding_identity", lambda _: events.append("identity")
    )
    monkeypatch.setattr(
        installed,
        "ProtectedNativeCudaEmbeddingInstallationAdmission",
        lambda *args, **kwargs: pytest.fail("installation capture before input guard"),
    )
    pin = configuration()
    # Constructing an uninitialized concrete object is deliberately unsafe fixture code;
    # no positive admission is claimed and invalid guards must precede method access.
    ownership = object.__new__(resources.OpenedCudaProbeDeviceAccess)
    receipt = "sha256:" + "e" * 64
    if fault == "pin_type":
        pin = pin.model_dump(mode="python")
    elif fault == "ownership":

        class Callback:
            def assert_owned(self):
                pytest.fail("structural callback is not a captured device scope")

        ownership = Callback()
    elif fault == "receipt_type":
        receipt = True
    elif fault == "receipt_hash":
        receipt = "sha256:" + "E" * 64
    else:
        object.__setattr__(pin, "configuration_id", "latest")
    with (
        pytest.raises(ValueError),
        module.native_cuda_backend_scope(pin, receipt_raw_sha256=receipt, ownership=ownership),
    ):
        pytest.fail("invalid capture entered the model scope")
    assert events == ["identity"]


def test_arguments_have_no_default_reader_receipt_or_ownership():
    with pytest.raises(TypeError):
        module.native_cuda_backend_scope(configuration())


def test_fresh_process_import_and_wrong_identity_never_import_metadata_or_ml():
    source = Path(__file__).resolve().parents[2] / "services/catalog_service"
    code = """
import sys
sys.path.insert(0,sys.argv[1])
from eom_catalog_service.embedding_native_cuda_backend import native_cuda_backend_scope
blocked={'torch','numpy','transformers','tokenizers','pydantic','eom_catalog_contracts'}
assert not blocked.intersection(sys.modules)
try:
    with native_cuda_backend_scope(None,receipt_raw_sha256='not-a-receipt',ownership=None):
        raise AssertionError('wrong identity entered a backend')
except ValueError as error:
    assert str(error)=='NATIVE_EMBEDDING_IDENTITY_INVALID'
assert not blocked.intersection(sys.modules)
"""
    result = subprocess.run(
        (sys.executable, "-I", "-B", "-c", code, str(source)),
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr.decode()
