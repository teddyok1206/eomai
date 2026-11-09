"""Catalog-backed authorization/pins; the API never resolves files or renders."""

from typing import Literal

from eom_catalog_contracts.curated_document_delivery_application import (
    CuratedDocumentDeliveryQueryV2,
    CuratedDocumentDeliveryResponseV2,
)
from eom_catalog_contracts.curated_document_slots import CuratedDeliveryManifest
from eom_hwpx_contracts.curated_document import CuratedHwpConverterSnapshot
from eom_hwpx_contracts.curated_occurrences import CuratedBuildInput
from eom_hwpx_contracts.models import ContentTeamHandoffSnapshot
from eom_operator_identity import ActorContext

from eom_api.services.catalog_application_client import CatalogApplicationClient


class CuratedDeliveryGateway:
    def __init__(
        self,
        client: CatalogApplicationClient,
        *,
        handoff: ContentTeamHandoffSnapshot,
        converter: CuratedHwpConverterSnapshot,
    ) -> None:
        self.client, self.handoff, self.converter = client, handoff, converter

    def _resolve(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
        purpose: Literal["AUTHORIZE_READ", "AUTHORIZE_BUILD", "PIN_INPUTS"],
    ) -> CuratedDocumentDeliveryResponseV2:
        if actor.operator_id is None or actor.session_id is None:
            raise ValueError("curated delivery requires an authenticated operator")
        result = self.client.resolve_curated_document_delivery(
            CuratedDocumentDeliveryQueryV2(
                actor_id=actor.operator_id,
                session_id=actor.session_id,
                request_id=actor.request_id,
                authentication_time=actor.authentication_time,
                purpose=purpose,
                assembly_id=assembly_id,
                assembly_revision_id=assembly_revision_id,
                manifest_sha256=manifest_sha256,
                handoff=self.handoff if purpose == "PIN_INPUTS" else None,
                converter=self.converter if purpose == "PIN_INPUTS" else None,
            )
        )
        if not isinstance(result, CuratedDocumentDeliveryResponseV2):
            raise ValueError("Catalog delivery contract version differs")
        return result

    def authorize_delivery_build(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDeliveryManifest:
        result = self._resolve(
            assembly_id,
            assembly_revision_id=assembly_revision_id,
            manifest_sha256=manifest_sha256,
            actor=actor,
            purpose="AUTHORIZE_BUILD",
        )
        assert result.manifest is not None
        return result.manifest

    def read_for_delivery(
        self,
        assembly_id: str,
        *,
        assembly_revision_id: str,
        manifest_sha256: str,
        actor: ActorContext,
    ) -> CuratedDeliveryManifest:
        result = self._resolve(
            assembly_id,
            assembly_revision_id=assembly_revision_id,
            manifest_sha256=manifest_sha256,
            actor=actor,
            purpose="AUTHORIZE_READ",
        )
        assert result.manifest is not None
        return result.manifest

    def pin_inputs(
        self, manifest: CuratedDeliveryManifest, *, actor: ActorContext
    ) -> CuratedBuildInput:
        result = self._resolve(
            manifest.assembly_id,
            assembly_revision_id=manifest.assembly_revision_id,
            manifest_sha256=manifest.manifest_sha256,
            actor=actor,
            purpose="PIN_INPUTS",
        )
        assert result.inputs is not None
        return result.inputs
