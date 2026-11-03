"""Native Hancom picture instances, distinct from their shared binary members.

This catalog is an inventory, not permission or a main-question selection. The
Orchestrator admits a worker's selection against the exact source and catalog.
"""

from typing import Annotated, Literal, Self

from pydantic import Field, model_validator

from eom_image_contracts.models import FrozenModel, Sha256, content_sha256
from eom_image_contracts.office_embedded_images import OfficeEmbeddedImageSet
from eom_image_contracts.validation import validate_contract

OFFICE_PICTURE_USE_CATALOG_REF = "eom://schemas/image-provider/office-picture-use-catalog/1.0"
OfficeObjectId = Annotated[str, Field(pattern=r"^officeobj_[0-9a-f]{32}$")]
NativeUnit = Annotated[int, Field(strict=True, ge=0, le=1_000_000_000)]
PositiveNativeUnit = Annotated[int, Field(strict=True, ge=1, le=1_000_000_000)]

UnresolvedPictureReason = Literal[
    "EXTERNAL_IMAGE",
    "UNSUPPORTED_IMAGE",
    "GEOMETRY_UNRESOLVED",
    "NON_ORTHOGONAL_TRANSFORM",
    "GROUP_COMPOSITION_REQUIRED",
    "IMAGE_EFFECT_UNSUPPORTED",
    "MISSING_IMAGE",
]
OfficeNativeObjectKind = Literal["TABLE", "EQUATION", "DRAWING", "TEXT_BOX", "GROUP"]


class OfficeObjectLocator(FrozenModel):
    member_path: str = Field(
        pattern=r"^(BodyText/Section[0-9]+|Contents/section[0-9]+\.xml)$", max_length=128
    )
    ordinal: int = Field(strict=True, ge=0, le=100000)


def office_object_id(source_sha256: str, locator: OfficeObjectLocator) -> str:
    """Source-pinned record/node identity, never image bytes or a model's label."""
    return (
        "officeobj_"
        + content_sha256(
            {"source_sha256": source_sha256, "locator": locator.model_dump(mode="json")}
        )[7:39]
    )


class OfficePictureGeometry(FrozenModel):
    original_extent: tuple[PositiveNativeUnit, PositiveNativeUnit]
    viewport: tuple[NativeUnit, NativeUnit, NativeUnit, NativeUnit]
    clockwise_quarter_turns: int = Field(strict=True, ge=0, le=3)
    flip_horizontal: bool = Field(strict=True)
    flip_vertical: bool = Field(strict=True)

    @model_validator(mode="after")
    def source_coordinate_bounds(self) -> Self:
        left, top, right, bottom = self.viewport
        width, height = self.original_extent
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            raise ValueError("OFFICE_PICTURE_VIEWPORT_INVALID")
        return self

    def pixel_box(self, *, width: int, height: int) -> tuple[int, int, int, int]:
        """Outward integer rounding keeps boundary labels; no guessed expansion."""
        if not 0 < width <= 10000 or not 0 < height <= 10000:
            raise ValueError("OFFICE_PICTURE_PIXEL_SIZE_INVALID")
        left, top, right, bottom = self.viewport
        native_width, native_height = self.original_extent
        return (
            left * width // native_width,
            top * height // native_height,
            (right * width + native_width - 1) // native_width,
            (bottom * height + native_height - 1) // native_height,
        )


class OfficePictureUse(FrozenModel):
    use_id: OfficeObjectId
    locator: OfficeObjectLocator
    source_member: str | None = Field(pattern=r"^BinData/[^/\\]+$", max_length=256)
    native_sha256: Sha256
    group_id: OfficeObjectId | None
    geometry: OfficePictureGeometry | None
    unresolved_reasons: tuple[UnresolvedPictureReason, ...] = Field(max_length=8)

    @model_validator(mode="after")
    def explicit_unresolved_use(self) -> Self:
        if self.unresolved_reasons != tuple(sorted(set(self.unresolved_reasons))):
            raise ValueError("OFFICE_PICTURE_REASONS_INVALID")
        reasons = set(self.unresolved_reasons)
        if (
            (self.source_member is None and not reasons & {"EXTERNAL_IMAGE", "MISSING_IMAGE"})
            or (
                self.geometry is None
                and not reasons & {"GEOMETRY_UNRESOLVED", "NON_ORTHOGONAL_TRANSFORM"}
            )
            or (self.group_id is not None and "GROUP_COMPOSITION_REQUIRED" not in reasons)
        ):
            raise ValueError("OFFICE_PICTURE_UNRESOLVED_REASON_REQUIRED")
        return self


class OfficeNativeObject(FrozenModel):
    object_id: OfficeObjectId
    locator: OfficeObjectLocator
    kind: OfficeNativeObjectKind
    group_id: OfficeObjectId | None
    native_sha256: Sha256


class OfficePictureView(FrozenModel):
    use_id: OfficeObjectId
    member_path: str = Field(pattern=r"^(images|uses)/[0-9a-f]{64}\.png$")
    sha256: Sha256
    width_px: int = Field(strict=True, ge=1, le=10000)
    height_px: int = Field(strict=True, ge=1, le=10000)
    content_length: int = Field(strict=True, ge=24, le=64 * 1024 * 1024)

    @model_validator(mode="after")
    def hash_named_member(self) -> Self:
        if self.member_path.rsplit("/", 1)[-1] != self.sha256[7:] + ".png":
            raise ValueError("OFFICE_PICTURE_VIEW_IDENTITY_INVALID")
        return self


class OfficePictureUseCatalog(FrozenModel):
    schema_version: Literal["office-picture-use-catalog/1.0"] = "office-picture-use-catalog/1.0"
    extractor_profile: Literal["HANCOM_NATIVE_PICTURE_USES_V1"] = "HANCOM_NATIVE_PICTURE_USES_V1"
    embedded_images: OfficeEmbeddedImageSet
    picture_uses: tuple[OfficePictureUse, ...] = Field(max_length=2048)
    rendered_uses: tuple[OfficePictureView, ...] = Field(max_length=2048)
    native_objects: tuple[OfficeNativeObject, ...] = Field(max_length=4096)
    manifest_sha256: Sha256

    @model_validator(mode="after")
    def closed_native_inventory(self) -> Self:
        value = self.model_dump(mode="json")
        validate_contract("office-picture-use-catalog", value)
        source_sha = self.embedded_images.source_sha256
        images = {image.source_member: image for image in self.embedded_images.images}
        unsupported = set(self.embedded_images.unsupported_members)
        all_objects: tuple[OfficePictureUse | OfficeNativeObject, ...] = (
            *self.picture_uses,
            *self.native_objects,
        )
        ids = [
            obj.use_id if isinstance(obj, OfficePictureUse) else obj.object_id
            for obj in all_objects
        ]
        locators = [(obj.locator.member_path, obj.locator.ordinal) for obj in all_objects]
        if len(set(ids)) != len(ids) or len(set(locators)) != len(locators):
            raise ValueError("OFFICE_PICTURE_DUPLICATE_OBJECT")
        groups = {obj.object_id for obj in self.native_objects if obj.kind == "GROUP"}
        for obj, identifier in zip(all_objects, ids, strict=True):
            if identifier != office_object_id(source_sha, obj.locator):
                raise ValueError("OFFICE_PICTURE_OBJECT_ID_MISMATCH")
            if obj.group_id is not None and (
                obj.group_id not in groups or obj.group_id == identifier
            ):
                raise ValueError("OFFICE_PICTURE_GROUP_MISSING")
        sequences: tuple[tuple[OfficePictureUse | OfficeNativeObject, ...], ...] = (
            self.picture_uses,
            self.native_objects,
        )
        for sequence in sequences:
            keys = [(obj.locator.member_path, obj.locator.ordinal) for obj in sequence]
            if keys != sorted(keys):
                raise ValueError("OFFICE_PICTURE_ORDER_INVALID")
        for use in self.picture_uses:
            if use.source_member is not None and use.source_member not in images:
                required = (
                    "UNSUPPORTED_IMAGE" if use.source_member in unsupported else "MISSING_IMAGE"
                )
                if required not in use.unresolved_reasons:
                    raise ValueError("OFFICE_PICTURE_MEMBER_MISSING")
        expected = {use.use_id: use for use in self.picture_uses if not use.unresolved_reasons}
        views = {view.use_id: view for view in self.rendered_uses}
        if len(views) != len(self.rendered_uses) or tuple(views) != tuple(expected):
            raise ValueError("OFFICE_PICTURE_VIEW_CLOSURE_INVALID")
        for identifier, view in views.items():
            use = expected[identifier]
            if use.geometry is None or use.source_member not in images:
                raise ValueError("OFFICE_PICTURE_VIEW_GEOMETRY_MISSING")
            image = images[use.source_member]
            left, top, right, bottom = use.geometry.pixel_box(
                width=image.width_px, height=image.height_px
            )
            dimensions = (right - left, bottom - top)
            if use.geometry.clockwise_quarter_turns % 2:
                dimensions = dimensions[::-1]
            if (view.width_px, view.height_px) != dimensions:
                raise ValueError("OFFICE_PICTURE_VIEW_DIMENSIONS_INVALID")
        # Imported catalogs are untrusted even though the parsers emit a tree.
        # Color each group once; no repeated ancestor scans for nested groups.
        parents = {
            obj.object_id: obj.group_id for obj in self.native_objects if obj.kind == "GROUP"
        }
        done: set[str] = set()
        for identifier in parents:
            visiting: set[str] = set()
            current: str | None = identifier
            while current is not None and current not in done:
                if current in visiting:
                    raise ValueError("OFFICE_PICTURE_GROUP_CYCLE")
                visiting.add(current)
                current = parents[current]
            done.update(visiting)
        if self.manifest_sha256 != content_sha256(
            {key: entry for key, entry in value.items() if key != "manifest_sha256"}
        ):
            raise ValueError("OFFICE_PICTURE_CATALOG_HASH_MISMATCH")
        return self
