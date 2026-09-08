"""Version-neutral immutable Assembly projection for whole-exam rendering."""

from __future__ import annotations

from dataclasses import dataclass

from eom_catalog_contracts import (
    MockExamAssemblyManifestContract,
    MockExamAssemblyManifestV1,
    MockExamContentPointerV1,
)
from eom_identifiers import content_sha256


@dataclass(frozen=True)
class AssemblyRenderPlacement:
    """Small ordered pointer needed to materialize one Assembly item."""

    position: int
    display_number: str
    points_milli: int
    placement_id: str
    item_id: str
    item_revision_id: str
    item_manifest_sha256: str
    content: MockExamContentPointerV1 | None


@dataclass(frozen=True)
class AssemblyRenderProjection:
    """Catalog-manifest fields consumed by the isolated HWPX boundary."""

    schema_version: str
    assessment_assembly_id: str
    assessment_assembly_revision_id: str
    manifest_sha256: str
    policy_revision_id: str
    policy_sha256: str
    graph_snapshot_revision_id: str
    graph_snapshot_sha256: str
    plan_sha256: str | None
    placements: tuple[AssemblyRenderPlacement, ...]

    def item_set_sha256(self) -> str:
        return content_sha256(
            [
                {
                    "position": row.position,
                    "placement_id": row.placement_id,
                    "item_id": row.item_id,
                    "item_revision_id": row.item_revision_id,
                    "item_manifest_sha256": row.item_manifest_sha256,
                }
                for row in self.placements
            ]
        )

    def request_identity(self) -> dict[str, str | None]:
        value: dict[str, str | None] = {
            "assessment_assembly_revision_id": self.assessment_assembly_revision_id,
            "assembly_manifest_sha256": self.manifest_sha256,
            "policy_revision_id": self.policy_revision_id,
            "policy_sha256": self.policy_sha256,
            "graph_snapshot_revision_id": self.graph_snapshot_revision_id,
            "graph_snapshot_sha256": self.graph_snapshot_sha256,
            "item_set_sha256": self.item_set_sha256(),
        }
        if self.plan_sha256 is not None:
            value["assembly_schema_version"] = self.schema_version
            value["plan_sha256"] = self.plan_sha256
        return value


def project_assembly_for_render(
    manifest: MockExamAssemblyManifestContract,
) -> AssemblyRenderProjection:
    """Normalize V1/V2 manifests without resolving any mutable current pointer."""

    if isinstance(manifest, MockExamAssemblyManifestV1):
        placements = tuple(
            AssemblyRenderPlacement(
                position=row.position,
                display_number=row.display_number,
                points_milli=row.points_milli,
                placement_id=row.placement_id,
                item_id=row.item_id,
                item_revision_id=row.item_revision_id,
                item_manifest_sha256=row.item_manifest_sha256,
                content=None,
            )
            for row in manifest.placements
        )
        return AssemblyRenderProjection(
            schema_version=manifest.schema_version,
            assessment_assembly_id=manifest.assessment_assembly_id,
            assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
            manifest_sha256=manifest.manifest_sha256,
            policy_revision_id=manifest.policy_revision_id,
            policy_sha256=manifest.policy_sha256,
            graph_snapshot_revision_id=manifest.graph_snapshot_revision_id,
            graph_snapshot_sha256=manifest.graph_snapshot_sha256,
            plan_sha256=None,
            placements=placements,
        )

    plan = manifest.plan
    placements = tuple(
        AssemblyRenderPlacement(
            position=row.position,
            display_number=row.display_number,
            points_milli=row.points_milli,
            placement_id=_planned_placement_id(
                manifest.assessment_assembly_revision_id,
                row.slot_id,
                row.item_revision_id,
            ),
            item_id=row.item_id,
            item_revision_id=row.item_revision_id,
            item_manifest_sha256=row.item_manifest_sha256,
            content=row.content,
        )
        for row in plan.placements
    )
    return AssemblyRenderProjection(
        schema_version=manifest.schema_version,
        assessment_assembly_id=manifest.assessment_assembly_id,
        assessment_assembly_revision_id=manifest.assessment_assembly_revision_id,
        manifest_sha256=manifest.manifest_sha256,
        policy_revision_id=plan.policy_revision_id,
        policy_sha256=plan.policy_sha256,
        graph_snapshot_revision_id=plan.graph_snapshot_revision_id,
        graph_snapshot_sha256=plan.graph_snapshot_sha256,
        plan_sha256=plan.plan_sha256,
        placements=placements,
    )


def _planned_placement_id(
    assessment_assembly_revision_id: str,
    slot_id: str,
    item_revision_id: str,
) -> str:
    value = {
        "assessment_assembly_revision_id": assessment_assembly_revision_id,
        "slot_id": slot_id,
        "item_revision_id": item_revision_id,
    }
    return "placement_" + content_sha256(value).removeprefix("sha256:")[:32]
