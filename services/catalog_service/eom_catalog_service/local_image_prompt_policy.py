"""Derived, bounded prompt policy for the fixed local image model."""

from __future__ import annotations

from typing import Final

LOCAL_GPU_PROMPT_POLICY_REVISION: Final = "local-gpu-image-prompt-policy/1.1"

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

# Ordered sentences keep the highest-value subject-independent constraints inside both 77-token
# CLIP encoders. The renderer style leads, followed immediately by exact subject-specific content.
LOCAL_GPU_RASTER_REQUIREMENTS: Final = (
    "Monochrome KICE exam line art on blank pure white canvas, isolated subjects, crisp black "
    "outlines, flat gray or hatching inside objects only, single composition.",
    "Exact count, position, direction, scale, ratio, geometry, scientific relation.",
    "Necessary objects, wide blank margins.",
)
LOCAL_GPU_BACKGROUND_REQUIREMENTS: Final = (
    "Non-authoritative background layer only.",
    *LOCAL_GPU_RASTER_REQUIREMENTS,
)

# Ordered terms combine the two sources' always-on prohibitions.  Authoritative labels, graphs,
# equations, arrows, scales, and exact geometry remain in the deterministic SVG overlay.
LOCAL_GPU_NEGATIVE_REQUIREMENTS: Final = (
    "color",
    "colored background",
    "gray background",
    "background fill",
    "border",
    "frame",
    "gradient",
    "shadow",
    "gloss",
    "photo texture",
    "photo",
    "3d",
    "perspective",
    "tilted view",
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
    "graphs",
    "scales",
    "watermark",
)


def compose_local_gpu_prompts(
    *,
    subject: str,
    background_only: bool,
    worker_negative: str | None,
) -> tuple[str, str]:
    """Arrange mandatory renderer style and exact worker content without truncation."""

    requirements = (
        LOCAL_GPU_BACKGROUND_REQUIREMENTS if background_only else LOCAL_GPU_RASTER_REQUIREMENTS
    )
    leading_count = 2 if background_only else 1
    leading = " ".join(requirements[:leading_count])
    trailing = " ".join(requirements[leading_count:])
    positive = f"{leading} Subject: {subject}. {trailing}"
    negative_parts = (
        (*LOCAL_GPU_NEGATIVE_REQUIREMENTS, worker_negative)
        if worker_negative is not None
        else LOCAL_GPU_NEGATIVE_REQUIREMENTS
    )
    return positive, ", ".join(negative_parts)
