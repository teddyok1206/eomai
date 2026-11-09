"""Local mixed publication using the existing native and content-team renderers."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from eom_hwpx_contracts import (
    serialize_content_team_markdown,
    validate_content_team_image_bindings,
)
from eom_hwpx_contracts.curated_document import CuratedHwpxFailure
from eom_hwpx_contracts.curated_mixed import (
    CuratedCanonicalSegment,
    CuratedEditorialSegment,
    CuratedMixedRenderResult,
    CuratedNativeSegment,
)
from eom_hwpx_contracts.curated_occurrences import (
    MAX_OCCURRENCES,
    CuratedOccurrenceRenderRequest,
    CuratedOccurrenceRenderResult,
    CuratedRenderRequest,
    CuratedRenderResult,
    NativeItemRenderRequestV2,
    parse_native_item_render,
)
from eom_hwpx_contracts.native_item import NativeItemImage
from eom_hwpx_contracts.validation import parse_json_object

from eom_hwpx_builder.archive import read_package
from eom_hwpx_builder.content_team_images import inject_content_team_images
from eom_hwpx_builder.content_team_renderer import (
    load_content_team_draft,
    prepare_content_team_runtime,
    render_content_team_document,
)
from eom_hwpx_builder.curated_editorial_layout import reflow_curated_editorial_document
from eom_hwpx_builder.curated_package_merge import (
    OCCURRENCE_OUTPUT_LIMITS,
    OUTPUT_LIMITS,
    merge_native_hwpx,
    parse_native_document,
)
from eom_hwpx_builder.curated_resources import NativeMergeProfile
from eom_hwpx_builder.handoff import prepare_private_handoff_file, write_private_json
from eom_hwpx_builder.native_hwp_converter import NativeHwpConverter
from eom_hwpx_builder.native_item_renderer import (
    prepare_native_item_template,
    render_native_item_document,
)
from eom_hwpx_builder.util import canonical_json_bytes, read_stable_local_file, sha256_bytes
from eom_hwpx_builder.xmlsafe import local_name


@dataclass(frozen=True)
class MixedRenderedOutput:
    result: CuratedRenderResult
    handoff_files: tuple[str, ...]


class _InputError(ValueError):
    def __init__(self, code: CuratedHwpxFailure) -> None:
        self.code = code
        super().__init__(code)


class _Inputs:
    """O(1) unique-file accounting; bytes exist only at each render boundary."""

    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace
        self.files: dict[str, tuple[str, int]] = {}
        self.total = 0

    def read(self, name: str, sha256: str, size: int | None, maximum: int) -> bytes:
        try:
            path = self.workspace / name
            if path.resolve(strict=True) != path.absolute():
                raise ValueError("mixed input must not traverse a symbolic link")
            data = read_stable_local_file(path, max_bytes=maximum)
        except (OSError, ValueError) as exc:
            raise _InputError("HWPX_CURATED_INPUT_INVALID") from exc
        identity = (sha256, len(data))
        if (
            (size is not None and len(data) != size)
            or sha256_bytes(data) != sha256
            or (name in self.files and self.files[name] != identity)
        ):
            raise _InputError("HWPX_CURATED_INPUT_CHANGED")
        if name not in self.files:
            self.total += len(data)
            self.files[name] = identity
        if self.total > 256 * 1024 * 1024:
            raise _InputError("HWPX_CURATED_INPUT_INVALID")
        return data


def render_mixed_curated_document(
    workspace: Path,
    request: CuratedRenderRequest,
) -> MixedRenderedOutput:
    """Produce local candidates only. The Manager owns authorization and Artifact commit."""
    output = workspace / "output/assembled.hwpx"
    output.parent.mkdir(mode=0o700)
    common: dict[str, Any] = {
        "build_id": request.build_id,
        "assembly_revision_id": request.assembly_revision_id,
        "assembly_manifest_sha256": request.assembly_manifest_sha256,
        "input_plan_sha256": request.input_plan_sha256,
        "request_sha256": sha256_bytes(canonical_json_bytes(request.model_dump(mode="json"))),
    }
    failure: CuratedHwpxFailure = "HWPX_CURATED_PRESERVATION_FAILED"
    position: int | None = None
    occurrence_profile = isinstance(request, CuratedOccurrenceRenderRequest)
    result_type = CuratedOccurrenceRenderResult if occurrence_profile else CuratedMixedRenderResult
    maximum_sources = MAX_OCCURRENCES if occurrence_profile else 200
    inputs = _Inputs(workspace)
    handoff_files: list[str] = ["assembled.hwpx", "preservation.json"]
    try:
        prepared = (
            prepare_content_team_runtime(workspace, request.handoff)
            if request.handoff is not None
            else None
        )
        native_template = None
        converter = None
        sources = []
        original_hashes = []
        segment_hashes = []
        for segment in request.segments:
            position = segment.position
            candidate = output.parent / f"segment-{position:03d}.hwpx"
            if isinstance(segment, CuratedNativeSegment):
                inputs.read(
                    segment.local_file, segment.sha256, segment.size_bytes, 50 * 1024 * 1024
                )
                source = workspace / segment.local_file
                original_hashes.append(segment.sha256)
                if segment.source_format == "HWP":
                    if converter is None:
                        failure = "HWPX_CURATED_FORMAT_UNSUPPORTED"
                        assert request.converter is not None
                        converter = NativeHwpConverter(request.converter)
                    failure = "HWPX_CURATED_PRESERVATION_FAILED"
                    conversion = converter.convert(source, candidate, source_sha256=segment.sha256)
                    segment_hashes.append(conversion.output_sha256)
                    sources.append(candidate)
                    handoff_files.append(candidate.name)
                else:
                    segment_hashes.append(segment.sha256)
                    sources.append(source)
                continue
            assert prepared is not None
            if isinstance(segment, CuratedCanonicalSegment):
                raw = inputs.read(
                    segment.blueprint_file,
                    segment.blueprint_sha256,
                    segment.blueprint_size_bytes,
                    2 * 1024 * 1024,
                )
                value = parse_json_object(raw)
                item = parse_native_item_render(value)
                if isinstance(item, NativeItemRenderRequestV2) != occurrence_profile:
                    raise _InputError("HWPX_CURATED_INPUT_CHANGED")
                if (
                    item.build_id != request.build_id
                    or item.item_number != position
                    or item.item_revision_id != segment.item_revision_id
                    or item.source_sha256 != segment.source_sha256
                    or item.effective_content_sha256 != segment.effective_content_sha256
                ):
                    raise _InputError("HWPX_CURATED_INPUT_CHANGED")
                if native_template is None:
                    native_template = prepare_native_item_template(
                        prepared.template, item.template_sha256
                    )
                for image in (block for block in item.body if isinstance(block, NativeItemImage)):
                    inputs.read(image.local_file, image.sha256, None, 20 * 1024 * 1024)
                render_native_item_document(
                    workspace, item, candidate, prepared_template=native_template
                )
            else:
                assert isinstance(segment, CuratedEditorialSegment)
                raw = inputs.read(
                    segment.json_file,
                    segment.source_sha256,
                    segment.json_size_bytes,
                    2 * 1024 * 1024,
                )
                markdown = inputs.read(
                    segment.markdown_file,
                    segment.markdown_sha256,
                    segment.markdown_size_bytes,
                    1024 * 1024,
                )
                draft = load_content_team_draft(raw, source_schema_ref=segment.source_schema_ref)
                if serialize_content_team_markdown(draft) != markdown:
                    raise _InputError("HWPX_CURATED_INPUT_CHANGED")
                bindings = tuple(image.binding for image in segment.images)
                validate_content_team_image_bindings(draft, bindings)
                payloads = tuple(
                    (
                        image.binding,
                        inputs.read(
                            image.local_file,
                            image.binding.sha256,
                            image.size_bytes,
                            2 * 1024 * 1024,
                        ),
                    )
                    for image in segment.images
                )
                render_content_team_document(
                    prepared.runtime,
                    prepared.template,
                    markdown,
                    candidate,
                    draft,
                    item_number_override=position,
                    maximum_item_number=maximum_sources,
                )
                inject_content_team_images(candidate, payloads)
                reflow_curated_editorial_document(candidate, item_number=position)
            prepare_private_handoff_file(candidate)
            original_hashes.append(segment.source_sha256)
            segment_hashes.append(
                sha256_bytes(read_stable_local_file(candidate, max_bytes=64 * 1024 * 1024))
            )
            handoff_files.append(candidate.name)
            sources.append(candidate)
        position = None
        failure = "HWPX_CURATED_PRESERVATION_FAILED"
        report = merge_native_hwpx(
            tuple(sources),
            output,
            profile=NativeMergeProfile.EDITABLE_V2,
            maximum_sources=maximum_sources,
        )
        if report.source_sha256 != tuple(segment_hashes):
            raise _InputError("HWPX_CURATED_INPUT_CHANGED")
        limits = OCCURRENCE_OUTPUT_LIMITS if occurrence_profile else OUTPUT_LIMITS
        document = parse_native_document(read_package(output, limits), limits)
        counts = {"equation": 0, "tbl": 0}
        for _name, section in document.sections:
            for node in section.iter():
                if isinstance(node.tag, str) and (name := local_name(node.tag)) in counts:
                    counts[name] += 1
        result = result_type(
            **common,
            status="SUCCEEDED",
            source_sha256=tuple(original_hashes),
            segment_sha256=tuple(segment_hashes),
            section_source_positions=report.section_source_positions,
            binary_count=report.binary_count,
            native_equation_count=counts["equation"],
            native_table_count=counts["tbl"],
            output_sha256=report.output_sha256,
            output_size_bytes=output.stat().st_size,
            warnings=report.warnings + (("HWP_CONVERTED_NATIVE",) if converter else ()),
            converter_bundle_sha256=request.converter.bundle_sha256 if request.converter else None,
            failure_code=None,
            failure_position=None,
        )
        write_private_json(output.parent / "preservation.json", result.model_dump(mode="json"))
        return MixedRenderedOutput(result, tuple(handoff_files))
    except Exception as exc:
        # Only this fresh invocation's final output is removed. Original inputs
        # and private intermediate diagnostics remain available for investigation.
        output.unlink(missing_ok=True)
        result = result_type(
            **common,
            status="FAILED",
            source_sha256=(),
            segment_sha256=(),
            section_source_positions=(),
            binary_count=0,
            native_equation_count=0,
            native_table_count=0,
            output_sha256=None,
            output_size_bytes=None,
            warnings=(),
            converter_bundle_sha256=None,
            failure_code=exc.code if isinstance(exc, _InputError) else failure,
            failure_position=position,
        )
        return MixedRenderedOutput(result, ())
