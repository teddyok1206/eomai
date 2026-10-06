"""Synthetic pixel/pin guards; no GPU, NAS, model or scientific-quality claim."""

from __future__ import annotations

import hashlib
import io

import pytest
from eom_image_contracts.photo_object_support import PhotoObjectSupportReview
from eom_image_provider.photo_object_support_pixels import validate_photo_object_support_pixels
from eom_image_provider.provider import ProviderError
from PIL import Image, ImageChops, ImageDraw

from tests.unit.test_photo_object_support_review import _seal, _value


def _encode(image, **options):
    stream = io.BytesIO()
    image.save(stream, format="PNG", **options)
    return stream.getvalue()


def _fixture():
    source = Image.new("RGB", (800, 504), "white")
    prior = Image.new("RGB", (832, 512), "black")
    for point in ((140, 190), (150, 200), (160, 210)):
        prior.putpixel(point, (255, 255, 255))
    mask = Image.new("L", (832, 512), 0)
    ImageDraw.Draw(mask).rectangle((130, 180, 150, 200), fill=255)
    kept = ImageChops.multiply(prior.getchannel("R"), mask)
    candidate = Image.merge("RGB", (kept, kept, kept))
    images = dict(
        source=source, prior_control=prior, support_mask=mask, candidate_control=candidate
    )
    payloads = {name: _encode(image) for name, image in images.items()}
    value = _value()
    value["pixel_observation"].update(
        original_edges=3,
        retained_edges=2,
        deleted_edges=1,
        support_area_pixels=441,
    )
    for name, raw in payloads.items():
        value[name]["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return PhotoObjectSupportReview.model_validate(_seal(value)), payloads, images


def _changed(review, payloads, name, raw):
    payloads = {**payloads, name: raw}
    value = review.model_dump(mode="json")
    value[name]["sha256"] = "sha256:" + hashlib.sha256(raw).hexdigest()
    return PhotoObjectSupportReview.model_validate(_seal(value)), payloads


def test_exact_binary_support_relation_and_counts():
    review, payloads, _ = _fixture()
    before = {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()}
    facts = validate_photo_object_support_pixels(review, **payloads)
    assert facts == review.pixel_observation
    assert (facts.original_edges, facts.retained_edges, facts.deleted_edges) == (3, 2, 1)
    assert facts.added_edges == 0
    assert before == {name: hashlib.sha256(raw).hexdigest() for name, raw in payloads.items()}


@pytest.mark.parametrize("name", ["source", "prior_control", "support_mask", "candidate_control"])
def test_changed_raw_bytes_refused_without_repin(name):
    review, payloads, _ = _fixture()
    payloads[name] += b" "
    with pytest.raises(ProviderError, match="HASH_MISMATCH"):
        validate_photo_object_support_pixels(review, **payloads)


@pytest.mark.parametrize(
    "name,mode,size",
    [
        ("source", "L", (800, 504)),
        ("source", "RGB", (832, 512)),
        ("prior_control", "L", (832, 512)),
        ("prior_control", "RGB", (800, 504)),
        ("support_mask", "RGB", (832, 512)),
        ("support_mask", "L", (800, 504)),
        ("candidate_control", "L", (832, 512)),
        ("candidate_control", "RGB", (800, 504)),
    ],
)
def test_decode_shape_mode_refused_even_with_matching_hash(name, mode, size):
    review, payloads, _ = _fixture()
    review, payloads = _changed(review, payloads, name, _encode(Image.new(mode, size, 127)))
    with pytest.raises(ProviderError, match="PNG_INVALID"):
        validate_photo_object_support_pixels(review, **payloads)


@pytest.mark.parametrize("name", ["prior_control", "candidate_control"])
@pytest.mark.parametrize("pixel", [(127, 127, 127), (255, 0, 0)])
def test_control_gray_or_chroma_refused(name, pixel):
    review, payloads, images = _fixture()
    image = images[name].copy()
    image.putpixel((140, 190), pixel)
    review, payloads = _changed(review, payloads, name, _encode(image))
    with pytest.raises(ProviderError, match="CONTROL_PIXELS_INVALID"):
        validate_photo_object_support_pixels(review, **payloads)


@pytest.mark.parametrize("tone", [0, 127, 255])
def test_mask_uniform_or_nonbinary_refused(tone):
    review, payloads, _ = _fixture()
    mask = Image.new("L", (832, 512), tone)
    review, payloads = _changed(review, payloads, "support_mask", _encode(mask))
    with pytest.raises(ProviderError, match="MASK_PIXELS_INVALID"):
        validate_photo_object_support_pixels(review, **payloads)


@pytest.mark.parametrize("kind", ["add_edge", "delete_kept_edge", "keep_deleted_edge"])
def test_candidate_must_equal_prior_times_mask_not_only_equal_counts(kind):
    review, payloads, images = _fixture()
    candidate = images["candidate_control"].copy()
    if kind == "add_edge":
        candidate.putpixel((145, 190), (255, 255, 255))
    elif kind == "delete_kept_edge":
        candidate.putpixel((140, 190), (0, 0, 0))
    else:
        candidate.putpixel((140, 190), (0, 0, 0))
        candidate.putpixel((160, 210), (255, 255, 255))
    review, payloads = _changed(review, payloads, "candidate_control", _encode(candidate))
    with pytest.raises(ProviderError, match="EDGE_RELATION_INVALID"):
        validate_photo_object_support_pixels(review, **payloads)


def test_valid_metadata_counts_are_recomputed_not_trusted():
    review, payloads, _ = _fixture()
    value = review.model_dump(mode="json")
    value["pixel_observation"]["support_area_pixels"] = 442
    review = PhotoObjectSupportReview.model_validate(_seal(value))
    with pytest.raises(ProviderError, match="PIXEL_OBSERVATION_MISMATCH"):
        validate_photo_object_support_pixels(review, **payloads)


def test_support_cannot_be_a_noop_even_when_png_hashes_differ():
    review, payloads, images = _fixture()
    mask = images["support_mask"].copy()
    ImageDraw.Draw(mask).rectangle((130, 180, 170, 220), fill=255)
    review, payloads = _changed(review, payloads, "support_mask", _encode(mask))
    review, payloads = _changed(
        review, payloads, "candidate_control", _encode(images["prior_control"], compress_level=0)
    )
    with pytest.raises(ProviderError, match="EDGE_COUNTS_INVALID"):
        validate_photo_object_support_pixels(review, **payloads)


@pytest.mark.parametrize("raw", [b"", b"not a PNG", b"x" * (16 * 1024**2 + 1)])
def test_malformed_and_bounded_inputs_refused(raw):
    review, payloads, _ = _fixture()
    review, payloads = _changed(review, payloads, "source", raw)
    expected = "PNG_INVALID" if raw == b"not a PNG" else "BYTE_BOUND_INVALID"
    with pytest.raises(ProviderError, match=expected):
        validate_photo_object_support_pixels(review, **payloads)


def test_multiframe_source_and_non_png_source_refused():
    review, payloads, images = _fixture()
    source = images["source"]
    other = source.copy()
    other.putpixel((10, 10), (0, 0, 0))
    raw = _encode(source, save_all=True, append_images=[other], duration=10, loop=0)
    modified, inputs = _changed(review, payloads, "source", raw)
    with pytest.raises(ProviderError, match="PNG_INVALID"):
        validate_photo_object_support_pixels(modified, **inputs)
    stream = io.BytesIO()
    source.save(stream, format="JPEG")
    modified, inputs = _changed(review, payloads, "source", stream.getvalue())
    with pytest.raises(ProviderError, match="PNG_INVALID"):
        validate_photo_object_support_pixels(modified, **inputs)
