"""Immutable released-family identities; no current/latest policy resolution."""

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class CreativeLearningProfile:
    definition_version: str
    role_protocol: str
    result_schema: str
    preset_key: str
    plan_schema_version: str
    plan_contract: str
    resolver_version: str


_PROFILES = (
    CreativeLearningProfile(
        "1.0.0",
        "workflow-role/1.33.0",
        "external-item-learning-result@1.0",
        "external-item-learning",
        "resolved-execution-plan/27.0",
        "resolved-execution-plan-v27",
        "27.0.0",
    ),
    CreativeLearningProfile(
        "2.0.0",
        "workflow-role/1.34.0",
        "external-item-learning-result@2.0",
        "creative-source-learning",
        "resolved-execution-plan/28.0",
        "resolved-execution-plan-v28",
        "28.0.0",
    ),
)
_BY_DEFINITION = MappingProxyType({profile.definition_version: profile for profile in _PROFILES})
_BY_PROTOCOL = MappingProxyType({profile.role_protocol: profile for profile in _PROFILES})
CREATIVE_LEARNING_PRESET_KEYS = frozenset(profile.preset_key for profile in _PROFILES)


def creative_learning_profile(definition_version: str) -> CreativeLearningProfile:
    try:
        return _BY_DEFINITION[definition_version]
    except KeyError as error:
        raise ValueError("unsupported creative learning Workflow version") from error


def creative_learning_profile_for_protocol(protocol: str) -> CreativeLearningProfile:
    try:
        return _BY_PROTOCOL[protocol]
    except KeyError as error:
        raise ValueError("unsupported creative learning role protocol") from error
