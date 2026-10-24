"""Pure same-family successor values; no protected files, GPU, DB or admission."""

from __future__ import annotations

import json

import pytest
from eom_catalog_contracts.embedding_cuda_host_extension import CudaHostExtensionSnapshotV11
from eom_catalog_contracts.embedding_native_configuration_revision import (
    derive_native_configuration_revision,
)
from eom_catalog_contracts.embedding_native_installation_evidence import (
    RootLocalNativeConfigurationPin,
)
from eom_catalog_contracts.embedding_native_runtime_config import (
    EmbeddingNativeRuntimeConfigV13,
    installed_embedding_native_runtime_config_bytes,
    parse_installed_embedding_native_runtime_config_bytes,
)
from eom_identifiers import sha256_bytes
from jsonschema.exceptions import ValidationError as SchemaError

from tests.unit.embedding_native_runtime_config_fixtures import native_config_metadata
from tests.unit.embedding_native_runtime_config_v11_fixtures import native_config_metadata_v11
from tests.unit.inference_transfer_embedding_fixtures import seal
from tests.unit.test_embedding_cuda_host_nvml import nvml_body, nvml_pointer
from tests.unit.test_embedding_cuda_installation_input import native


def _case(family="CUDA1.3"):
    if family == "CPU1.0":
        config = native_config_metadata()[0]
    elif family == "CUDA1.0":
        config = native_config_metadata("CUDA_INDEX_FP32")[0]
    elif family == "CPU1.1":
        config = native_config_metadata_v11()[0]
    elif family == "CUDA1.2":
        config = native()[0]
    else:
        body = native()[0].model_dump(mode="json")
        extension = CudaHostExtensionSnapshotV11.model_validate(nvml_body())
        body.update(
            schema_version="embedding-native-runtime-config/1.3",
            cuda_host_extension=nvml_pointer(extension).model_dump(mode="json"),
        )
        config = EmbeddingNativeRuntimeConfigV13.model_validate(seal(body, "config_sha256"))
    raw = installed_embedding_native_runtime_config_bytes(config)
    pin = RootLocalNativeConfigurationPin(
        configuration_id=config.configuration_id,
        configuration_revision_id=config.configuration_revision_id,
        configuration_sha256=config.config_sha256,
        configuration_raw_sha256=sha256_bytes(raw),
    )
    return config, raw, pin


@pytest.mark.parametrize("family", ("CPU1.0", "CUDA1.0", "CPU1.1", "CUDA1.2", "CUDA1.3"))
def test_revision_preserves_exact_family_and_all_numerical_host_resource_pins(family):
    original, raw, pin = _case(family)
    revision = "embeddingnativeconfigrev_" + "f" * 32
    successor, encoded = derive_native_configuration_revision(raw, pin, revision)
    assert type(successor) is type(original)
    assert parse_installed_embedding_native_runtime_config_bytes(encoded) == successor
    assert successor.configuration_id == original.configuration_id
    assert successor.configuration_revision_id == revision
    before, after = original.model_dump(mode="json"), successor.model_dump(mode="json")
    assert {key for key in before if before[key] != after[key]} == {
        "configuration_revision_id",
        "config_sha256",
    }
    assert derive_native_configuration_revision(raw, pin, revision) == (successor, encoded)
    assert installed_embedding_native_runtime_config_bytes(original) == raw


@pytest.mark.parametrize("field", tuple(RootLocalNativeConfigurationPin.model_fields))
def test_independently_wrong_predecessor_is_rejected(field):
    _original, raw, pin = _case()
    value = pin.model_dump(mode="json")
    value[field] = value[field][:-1] + ("0" if value[field][-1] != "0" else "1")
    changed = RootLocalNativeConfigurationPin.model_validate(value)
    with pytest.raises(ValueError):
        derive_native_configuration_revision(raw, changed, "embeddingnativeconfigrev_" + "f" * 32)


@pytest.mark.parametrize(
    "revision", (None, True, 1, "", "rev_" + "f" * 32, "embeddingnativeconfigrev_" + "F" * 32)
)
def test_wrong_raw_revision_or_same_revision_is_rejected(revision):
    original, raw, pin = _case()
    for value in (revision, original.configuration_revision_id):
        with pytest.raises((TypeError, ValueError)):
            derive_native_configuration_revision(raw, pin, value)


@pytest.mark.parametrize(
    "fault", ("noncanonical", "extra", "copied_pin_extra", "changed_resources")
)
def test_raw_or_constructed_fields_cannot_be_hidden(fault):
    _original, raw, pin = _case()
    if fault == "noncanonical":
        raw += b"\n"
        pin = pin.model_copy(update={"configuration_raw_sha256": sha256_bytes(raw)})
    elif fault == "copied_pin_extra":
        pin = pin.model_copy(update={"permission": "ADMIN"})
    else:
        value = json.loads(raw)
        if fault == "extra":
            value["permission"] = "ADMIN"
        else:
            value["resources"]["threads"] = 1
        raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
        pin = pin.model_copy(update={"configuration_raw_sha256": sha256_bytes(raw)})
    with pytest.raises((TypeError, ValueError, SchemaError)):
        derive_native_configuration_revision(raw, pin, "embeddingnativeconfigrev_" + "f" * 32)
