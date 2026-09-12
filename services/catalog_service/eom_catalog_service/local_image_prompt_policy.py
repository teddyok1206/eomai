"""Derived, bounded prompt policy for the fixed local image model."""

from __future__ import annotations

from typing import Final

LOCAL_GPU_PROMPT_POLICY_REVISION: Final = "local-gpu-image-prompt-policy/1.3"
LOCAL_GPU_MAX_SUBJECT_CHARS: Final = 50

# These are provenance pins for the two reviewed inputs.  They are not runtime paths and the
# Catalog service does not dereference repository files while handling a request.
LOCAL_GPU_PROMPT_SOURCE_PINS: Final = (
    (
        "config/control-plane/standard-item-v5/references/guidance/"
        "content-team-integrated-science-authoring-v05.md",
        "sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435",
    ),
    (
        "content/image-specs/kice-integrated-science-illustration-v1.md",
        "sha256:9acdb63cfbc69583d852b386fddb205dfc6efc493a6b68195375b222139396ed",
    ),
)

# The fixed SSD-1B provider has two 77-token CLIP encoders. The complete reviewed team-lead
# instruction remains pinned in the drawing and its hash; the GPU receives the worker-authored,
# concise alt text as its semantic subject. Authoritative labels and geometry remain in the
# deterministic overlay.
LOCAL_GPU_RASTER_REQUIREMENTS: Final = ("monochrome:",)
LOCAL_GPU_BACKGROUND_REQUIREMENTS: Final = ("monochrome:",)

# Ordered terms combine the two sources' always-on prohibitions.  Authoritative labels, graphs,
# equations, arrows, scales, and exact geometry remain in the deterministic SVG overlay.
LOCAL_GPU_NEGATIVE_REQUIREMENTS: Final = (
    "color",
    "gray background",
    "border",
    "frame",
    "gradient",
    "shadow",
    "photo",
    "3d",
    "perspective",
    "scenery",
    "decoration",
    "extra objects",
    "duplicates",
    "collage",
    "crop",
    "text",
    "labels",
    "numbers",
    "symbols",
    "equations",
)


def compose_local_gpu_prompts(
    *,
    subject: str,
    background_only: bool,
) -> tuple[str, str]:
    """Arrange mandatory renderer style and exact worker content without truncation."""

    prefix = (
        LOCAL_GPU_BACKGROUND_REQUIREMENTS if background_only else LOCAL_GPU_RASTER_REQUIREMENTS
    )[0]
    positive = f"{prefix} {subject}"
    return positive, ", ".join(LOCAL_GPU_NEGATIVE_REQUIREMENTS)
