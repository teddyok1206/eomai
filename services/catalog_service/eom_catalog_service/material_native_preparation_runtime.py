"""Optional installed composition for the bounded native intake adapter.

Only deployment configuration selects the isolated Python and qualified converter.
Uploads cannot select executables, converter bundles or source revisions.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from eom_hwpx_contracts.native_conversion_v2 import NativeHwpConverterSnapshotV2
from sqlalchemy import Engine

from eom_catalog_service.material_native_preparation import MaterialNativePreparationService
from eom_catalog_service.native_exam_preparer import SystemdNativeExamFilePreparer
from eom_catalog_service.settings import CatalogSettings

_KEYS = (
    "EOM_MATERIAL_NATIVE_TOOL_PYTHON",
    "EOM_MATERIAL_NATIVE_CONVERTER_SOURCE_COMMIT",
    "EOM_MATERIAL_NATIVE_CONVERTER_BUNDLE_SHA256",
)


def build_material_native_preparation(
    engine: Engine, settings: CatalogSettings, *, environment: Mapping[str, str]
) -> MaterialNativePreparationService | None:
    values = tuple(environment.get(key) for key in _KEYS)
    if all(value is None for value in values):
        return None
    if any(value is None or not value.strip() for value in values):
        raise ValueError("MATERIAL_NATIVE_PREPARATION_RUNTIME_CONFIG_INVALID")
    python, source_commit, bundle_sha256 = values
    assert python is not None and source_commit is not None and bundle_sha256 is not None
    if not Path(python).is_absolute():
        raise ValueError("MATERIAL_NATIVE_PREPARATION_RUNTIME_CONFIG_INVALID")
    converter = NativeHwpConverterSnapshotV2.model_validate(
        {"source_commit": source_commit, "bundle_sha256": bundle_sha256}
    )
    return MaterialNativePreparationService(
        engine,
        settings,
        python=Path(python),
        converter=converter,
        tool=SystemdNativeExamFilePreparer(),
    )
