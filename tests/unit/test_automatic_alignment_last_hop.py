"""Same bounded shortest-path ranking without materializing irrelevant final leaves."""

from collections import defaultdict, deque

import pytest
from eom_catalog_service.automatic_curriculum_alignment import (
    automatic_item_alignment_policy,
    derive_automatic_item_curriculum_unit_ids,
)
from sqlalchemy import Column, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session


def oracle(edges, seeds, units, policy):
    adjacent = defaultdict(set)
    for left, right in edges:
        adjacent[left].add(right)
        adjacent[right].add(left)
    distances = defaultdict(dict)
    for seed in seeds:
        queue, visited = deque([(seed, 0)]), {seed}
        while queue:
            node, depth = queue.popleft()
            if node in units:
                distances[units[node]][seed] = depth
            if depth == 3:
                continue
            for neighbor in adjacent[node] - visited:
                visited.add(neighbor)
                queue.append((neighbor, depth + 1))
    ranked = sorted(
        distances, key=lambda unit: (-len(distances[unit]), sum(distances[unit].values()), unit)
    )
    if policy.maximum_support_only:
        best = len(distances[ranked[0]])
        ranked = [unit for unit in ranked if len(distances[unit]) == best]
    return tuple(sorted(ranked[: policy.maximum_units]))


@pytest.mark.parametrize("version", ("1.0", "1.1", "1.2"))
@pytest.mark.parametrize("leaves", (0, 17000))
def test_last_hop_pruning_preserves_full_bfs_without_relaxing_policy(version, leaves):
    engine, metadata = create_engine("sqlite+pysqlite:///:memory:"), MetaData()
    nodes = Table(
        "knowledge_nodes",
        metadata,
        Column("graph_snapshot_revision_id", String),
        Column("node_id", String),
    )
    graph_edges = Table(
        "knowledge_edges",
        metadata,
        Column("graph_snapshot_revision_id", String),
        Column("edge_id", String),
        Column("from_node_id", String),
        Column("to_node_id", String),
    )
    curriculum = Table(
        "curriculum_units",
        metadata,
        Column("graph_snapshot_revision_id", String),
        Column("curriculum_unit_id", String),
        Column("node_id", String),
        Column("framework_revision_id", String),
        Column("parent_unit_id", String),
        Column("unit_level", String),
        Column("ordinal", Integer),
    )
    metadata.create_all(engine)
    seeds = ("s_a", "s_b")
    edges = [("s_a", "h1"), ("s_b", "h1"), ("h1", "h2"), ("h2", "unit_late"), ("s_a", "unit_near")]
    edges += [("h2", f"dead{index:05d}") for index in range(leaves)]
    units = {"unit_late": "currunit_" + "a" * 32, "unit_near": "currunit_" + "b" * 32}
    policy = automatic_item_alignment_policy("integrated-science-auto-alignment/" + version)
    with engine.begin() as connection:
        connection.execute(
            nodes.insert(),
            [{"graph_snapshot_revision_id": "pinned", "node_id": node} for node in seeds],
        )
        connection.execute(
            graph_edges.insert(),
            [
                dict(
                    graph_snapshot_revision_id="pinned",
                    edge_id=f"edge{index:05d}",
                    from_node_id=left,
                    to_node_id=right,
                )
                for index, (left, right) in enumerate(edges)
            ],
        )
        connection.execute(
            curriculum.insert(),
            [
                dict(
                    graph_snapshot_revision_id="pinned",
                    curriculum_unit_id=unit,
                    node_id=node,
                    framework_revision_id="framework",
                    parent_unit_id=None,
                    unit_level="MINOR",
                    ordinal=index + 1,
                )
                for index, (node, unit) in enumerate(units.items())
            ],
        )
    with Session(engine) as session:
        assert derive_automatic_item_curriculum_unit_ids(
            session,
            graph_snapshot_revision_id="pinned",
            evidence_node_ids=seeds,
            alignment_policy_version=policy.version,
        ) == oracle(edges, seeds, units, policy)
    engine.dispose()
