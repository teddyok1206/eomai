"""Derived, bounded prompt policy for the fixed local image model."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

LocalGpuPromptContract = Literal["LEGACY_COMPAT", "ASSESSMENT_LINE_ART_V1"]

LOCAL_GPU_LEGACY_PROMPT_POLICY_REVISION: Final = "local-gpu-image-prompt-policy/1.4"
LOCAL_GPU_PROMPT_POLICY_REVISION: Final = "local-gpu-image-prompt-policy/1.6"
LOCAL_GPU_MAX_LEGACY_SUBJECT_CHARS: Final = 50
LOCAL_GPU_MAX_SUBJECT_CHARS: Final = 180

# These are provenance pins for the three reviewed inputs. They are not runtime paths and the
# Catalog service does not dereference repository files while handling a request.
LOCAL_GPU_PROMPT_SOURCE_PINS: Final = (
    (
        "config/control-plane/standard-item-v5/references/guidance/"
        "content-team-integrated-science-authoring-v05.md",
        "sha256:62f245320a4776a2ee3dcd273fb1180b6f3c431a45d2504d125816102f017435",
    ),
    (
        "config/control-plane/standard-item-v6/references/guidance/"
        "content-team-hwp-question-editor-handoff-v1.md",
        "sha256:6fdfd8f9dbc67abfcac9ef2761059bbe841a8b994640925fef30388d95a00ee5",
    ),
    (
        "content/image-specs/kice-integrated-science-illustration-v1.md",
        "sha256:9acdb63cfbc69583d852b386fddb205dfc6efc493a6b68195375b222139396ed",
    ),
)

# The fixed SSD-1B provider has two 77-token CLIP encoders. The complete reviewed team-lead
# instructions and editor layout contract remain pinned outside the model prompt; the GPU receives
# the worker-authored concise alt text as its semantic subject. Authoritative scientific labels and
# geometry remain in the deterministic overlay, while panel labels remain editable HWPX text.
LOCAL_GPU_RASTER_REQUIREMENTS: Final = ("monochrome:",)
LOCAL_GPU_BACKGROUND_REQUIREMENTS: Final = ("monochrome:",)

# The local SSD-1B checkpoint responded reliably to a concise English subject in the 520-item
# benchmark, while the same subjects in Korean repeatedly collapsed into unrelated portraits.
# Scientific labels and exact geometry still belong to the deterministic SVG overlay.
LOCAL_GPU_ASSESSMENT_STYLE_PREFIX: Final = (
    "black-and-white Korean science exam figure, flat 2D technical line drawing, centered isolated "
    "subject, clean white background, uniform black outlines, sparse light-gray hatching, no text:"
)
_LOCAL_GPU_ENGLISH_SUBJECT: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,.'()/_-]{2,179}$")

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

LOCAL_GPU_ASSESSMENT_NEGATIVE_REQUIREMENTS: Final = (
    "color",
    "gray background",
    "border",
    "frame",
    "gradient",
    "shadow",
    "photograph",
    "photorealistic",
    "anime",
    "manga",
    "comic",
    "cartoon",
    "3d",
    "render",
    "perspective",
    "cinematic lighting",
    "dramatic composition",
    "decoration",
    "extra objects",
    "duplicates",
    "collage",
    "crop",
    "text",
    "letters",
    "labels",
    "numbers",
    "symbols",
    "equations",
    "watermark",
    "logo",
    "person",
    "human",
    "man",
    "woman",
    "child",
    "face",
    "portrait",
    "fashion",
    "clothing",
    "stage",
    "room",
)


@dataclass(frozen=True)
class LocalGpuPromptPlan:
    """One immutable prompt-policy choice included in provider request identity."""

    policy_revision: str
    positive_prompt: str
    negative_prompt: str


def local_gpu_prompt_policy_revision(prompt_contract: LocalGpuPromptContract) -> str:
    """Return the immutable policy revision selected by a pinned Pack contract."""

    if prompt_contract == "ASSESSMENT_LINE_ART_V1":
        return LOCAL_GPU_PROMPT_POLICY_REVISION
    return LOCAL_GPU_LEGACY_PROMPT_POLICY_REVISION


def compose_local_gpu_prompt_plan(
    *,
    subject: str,
    production_route: Literal["LOCAL_GENERATIVE_BACKGROUND", "HYBRID_LOCAL_GENERATIVE"],
    prompt_contract: LocalGpuPromptContract,
) -> LocalGpuPromptPlan:
    """Select a backward-compatible prompt policy without truncating worker content."""

    if prompt_contract == "ASSESSMENT_LINE_ART_V1":
        if (
            production_route != "HYBRID_LOCAL_GENERATIVE"
            or _LOCAL_GPU_ENGLISH_SUBJECT.fullmatch(subject) is None
        ):
            raise ValueError("assessment local GPU subject is not bounded English")
        return LocalGpuPromptPlan(
            policy_revision=LOCAL_GPU_PROMPT_POLICY_REVISION,
            positive_prompt=f"{LOCAL_GPU_ASSESSMENT_STYLE_PREFIX} {subject}",
            negative_prompt=", ".join(LOCAL_GPU_ASSESSMENT_NEGATIVE_REQUIREMENTS),
        )
    if len(subject) > LOCAL_GPU_MAX_LEGACY_SUBJECT_CHARS:
        raise ValueError("legacy local GPU subject exceeds the bounded compatibility limit")

    prefix = (
        LOCAL_GPU_BACKGROUND_REQUIREMENTS
        if production_route == "LOCAL_GENERATIVE_BACKGROUND"
        else LOCAL_GPU_RASTER_REQUIREMENTS
    )[0]
    return LocalGpuPromptPlan(
        policy_revision=LOCAL_GPU_LEGACY_PROMPT_POLICY_REVISION,
        positive_prompt=f"{prefix} {subject}",
        negative_prompt=", ".join(LOCAL_GPU_NEGATIVE_REQUIREMENTS),
    )
