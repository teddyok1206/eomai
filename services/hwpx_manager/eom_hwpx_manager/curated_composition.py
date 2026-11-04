"""Runner-only composition of the existing Catalog and isolated Builder owners."""

from eom_catalog_service.artifacts import CatalogArtifactService
from eom_catalog_service.curated_delivery_inputs import CuratedDeliveryInputs
from eom_catalog_service.curated_document_assembly_service import CuratedDocumentAssemblyService
from eom_catalog_service.external_item_document_media import ExternalItemDocumentMediaService
from eom_catalog_service.registry_service import RegistryService
from eom_catalog_service.settings import CatalogSettings
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from sqlalchemy import Engine

from eom_hwpx_manager.application_adapter import FixedCuratedBuilderAdapter
from eom_hwpx_manager.content_team_service import ContentTeamHwpxService
from eom_hwpx_manager.curated_application_service import CuratedHwpxApplicationService
from eom_hwpx_manager.curated_materialization import CuratedInputMaterializer
from eom_hwpx_manager.curated_service import CuratedHwpxService
from eom_hwpx_manager.settings import HwpxSettings


def build_curated_application(engine: Engine) -> CuratedHwpxApplicationService:
    settings = HwpxSettings.from_environment()
    registry = RegistryService(engine)
    members = ContentTeamHwpxService(engine, settings)
    assemblies = CuratedDocumentAssemblyService(engine, ExternalItemDocumentMediaService(engine))
    adapter = FixedCuratedBuilderAdapter(settings)
    pins = CuratedDeliveryInputs(
        engine,
        assemblies=assemblies,
        handoff=members.snapshot(),
        converter=CuratedHwpConverterSnapshot(
            profile="HWP2HWPX_NATIVE_V1",
            source_commit="62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
            bundle_sha256=settings.native_hwp_converter_bundle_sha256,
        ),
    )
    renderer = CuratedHwpxService(
        engine,
        pins=pins,
        adapter=adapter,
        materializer=CuratedInputMaterializer(members=members, registry=registry, adapter=adapter),
        artifacts=CatalogArtifactService(
            engine,
            CatalogSettings(
                staging_root=settings.staging_root / "curated-artifacts",
                nas_artifact_root=settings.nas_artifact_root,
            ),
        ),
    )
    return CuratedHwpxApplicationService(engine, assemblies=assemblies, renderer=renderer)
