"""Isolated local image provider infrastructure adapter."""

from eom_image_provider.provider import (
    GeneratedBackground,
    ImageBackend,
    ProviderError,
    acquire_gpu_lease,
    generate_background,
    generate_composite_handoff,
    reuse_composite_handoff,
    verify_model_revision,
)

__all__ = [
    "GeneratedBackground",
    "ImageBackend",
    "ProviderError",
    "acquire_gpu_lease",
    "generate_background",
    "generate_composite_handoff",
    "reuse_composite_handoff",
    "verify_model_revision",
]
