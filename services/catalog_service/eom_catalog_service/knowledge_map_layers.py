"""One ordered provenance classification for Map presentation and SQL selection."""

from dataclasses import dataclass
from typing import Literal

from eom_catalog_contracts.knowledge_map_v2 import MapLayerV2
from sqlalchemy import ColumnElement, SQLColumnExpression, and_, case, true

_INTERNAL_DOMAIN = "INTERNAL_EOM"


@dataclass(frozen=True, slots=True)
class _LayerRule:
    source_class: str
    layer: MapLayerV2
    domain: Literal["ANY", "PRESENT", "INTERNAL"] = "ANY"
    workflow: str | None = None


# Specific material provenance precedes origin; non-null origin precedes the
# exact historical Workflow fallback. Unknown history is never guessed as AI.
_RULES = (
    _LayerRule("APPROVED_ITEM", "EXTERNAL", workflow="material-learning"),
    _LayerRule("APPROVED_ITEM", "AI", domain="INTERNAL"),
    _LayerRule("APPROVED_ITEM", "CREATIVE", domain="PRESENT"),
    _LayerRule("APPROVED_ITEM", "CREATIVE", workflow="external-item-learning"),
    _LayerRule("APPROVED_ITEM", "AI", workflow="generic-item-development"),
    _LayerRule("TEXTBOOK", "TEXTBOOK"),
    _LayerRule("PAST_EXAM", "PAST_EXAM"),
    _LayerRule("CURRICULUM", "CURRICULUM"),
    _LayerRule("INTERNAL_GUIDE", "GUIDE"),
)
PRIMARY_MAP_LAYERS: tuple[MapLayerV2, ...] = ("TEXTBOOK", "PAST_EXAM", "CREATIVE", "EXTERNAL", "AI")


def source_layer(
    source_class: str, source_domain: str | None, workflow_key: str | None = None
) -> MapLayerV2:
    domain_matches = {
        "ANY": True,
        "PRESENT": source_domain is not None,
        "INTERNAL": source_domain == _INTERNAL_DOMAIN,
    }
    for rule in _RULES:
        if (
            rule.source_class == source_class
            and domain_matches[rule.domain]
            and (rule.workflow is None or rule.workflow == workflow_key)
        ):
            return rule.layer
    return "UNKNOWN"


def source_layer_expression(
    source_class: SQLColumnExpression[str],
    source_domain: SQLColumnExpression[str | None],
    workflow_key: SQLColumnExpression[str | None],
) -> ColumnElement[str]:
    """Compile the same immutable rules into the existing metadata join."""
    domains = {
        "ANY": true(),
        "PRESENT": source_domain.is_not(None),
        "INTERNAL": source_domain == _INTERNAL_DOMAIN,
    }
    return case(
        *(
            (
                and_(
                    source_class == rule.source_class,
                    domains[rule.domain],
                    true() if rule.workflow is None else workflow_key == rule.workflow,
                ),
                rule.layer,
            )
            for rule in _RULES
        ),
        else_="UNKNOWN",
    )


def source_classes_for_layer(layer: MapLayerV2) -> tuple[str, ...]:
    return tuple(sorted({rule.source_class for rule in _RULES if rule.layer == layer}))
