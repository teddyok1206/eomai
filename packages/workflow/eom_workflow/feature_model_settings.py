"""Product features and their actual model-editing stages; no execution policy copies."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSettingsStage:
    key: str
    label: str
    preset_key: str


@dataclass(frozen=True)
class ModelSettingsFeature:
    key: str
    label: str
    stages: tuple[ModelSettingsStage, ...]


MODEL_SETTINGS_FEATURES = (
    ModelSettingsFeature(
        "item-authoring",
        "문항 제작",
        (ModelSettingsStage("authoring", "출제·그림·검토", "knowledge-grounded-item"),),
    ),
    ModelSettingsFeature(
        "material-review",
        "자료 검토",
        (ModelSettingsStage("review", "문제지·해설지 검토", "pdf-document-review"),),
    ),
    ModelSettingsFeature(
        "material-learning",
        "자료 학습",
        (
            ModelSettingsStage("reading", "자료 내용·문항 읽기", "material-learning"),
            ModelSettingsStage("knowledge", "설명·개념 분석", "material-knowledge-analysis"),
            ModelSettingsStage("items", "문항 분석", "material-item-analysis"),
            ModelSettingsStage("solutions", "풀이보고서", "material-item-solution"),
            ModelSettingsStage("source-analysis", "기출·교과서 분석", "knowledge-analysis"),
        ),
    ),
    ModelSettingsFeature(
        "item-registration",
        "기존 문항 등록",
        (
            ModelSettingsStage("source", "원문·그림·풀이 읽기", "creative-office-learning-four"),
            ModelSettingsStage(
                "graph", "풀이 근거·Graph 등록", "creative-knowledge-analysis-office-four"
            ),
            ModelSettingsStage("extraction", "기존 문항 추출", "legacy-item-extraction"),
            ModelSettingsStage(
                "editorial", "출력 양식 정리", "legacy-item-editorial-compatibility"
            ),
        ),
    ),
    ModelSettingsFeature(
        "similarity-comparison",
        "유사도 정밀 비교",
        (
            ModelSettingsStage(
                "comparison", "풀이 방식 비교", "item-inference-transfer-comparison-axes"
            ),
        ),
    ),
    ModelSettingsFeature(
        "customer-support",
        "고객지원",
        (ModelSettingsStage("support", "시스템 문의", "customer-support"),),
    ),
    ModelSettingsFeature("chat", "ChatGPT", ()),
)

FEATURE_PRESET_KEYS = frozenset(
    stage.preset_key for feature in MODEL_SETTINGS_FEATURES for stage in feature.stages
)

# Removed from new administrator selection, not an alias for historical execution pins.
OBSOLETE_PRESET_KEYS = frozenset(
    {
        "standard-item",
        "external-item-learning",
        "creative-source-learning",
        "creative-source-learning-parallel",
        "creative-office-learning",
        "creative-knowledge-analysis",
        "creative-knowledge-analysis-parallel",
    }
)
