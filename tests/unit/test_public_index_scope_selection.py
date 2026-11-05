"""Independent device heads must use one exact, published Graph/policy scope."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.public_solution_embedding_index import PublicSolutionIndexNamespace
from eom_catalog_service import embedding_registry_repository as module
from eom_catalog_service.embedding_registry_ports import EmbeddingRegistryError
from sqlalchemy.dialects import postgresql


def case(monkeypatch):
    cpu_ns = PublicSolutionIndexNamespace(
        storage_partition="public-test",
        space_sha256="sha256:" + "1" * 64,
        recipe_sha256="sha256:" + "3" * 64,
    )
    cuda_ns = cpu_ns.model_copy(update={"space_sha256": "sha256:" + "2" * 64})
    common = dict(
        corpus_id="corpus_" + "4" * 32,
        policy_revision_id="accessrev_" + "5" * 32,
        policy_sha256="sha256:" + "6" * 64,
    )
    cpu = NS(
        **common,
        namespace=cpu_ns,
        index_id="embeddingindex_" + "7" * 32,
        index_revision_id="embeddingindexrev_" + "8" * 32,
        graph_snapshot_revision_id="graphrev_" + "9" * 32,
        binding_count=580,
    )
    cuda = NS(
        **common,
        namespace=cuda_ns,
        index_id="embeddingindex_" + "a" * 32,
        index_revision_id="embeddingindexrev_" + "b" * 32,
        graph_snapshot_revision_id="graphrev_" + "c" * 32,
        binding_count=608,
    )
    session = Mock()
    repository = module.EmbeddingRegistryRepository(session)
    repository.current_namespace_revision = Mock(
        side_effect=lambda _corpus, ns: (cpu, 120) if ns == cpu_ns else (cuda, 123)
    )
    monkeypatch.setattr(module, "_registered_index_read", lambda row: row)
    return NS(**locals())


def test_same_scope_heads_keep_independent_partial_coverage_without_sql_history(monkeypatch):
    c = case(monkeypatch)
    c.cuda.graph_snapshot_revision_id = c.cpu.graph_snapshot_revision_id
    assert c.repository.common_public_namespace_revisions(c.cpu.corpus_id, c.cpu_ns, c.cuda_ns) == (
        c.cpu,
        c.cuda,
    )
    c.session.execute.assert_not_called()


def test_lagging_cpu_head_selects_exact_gpu_history_not_newest_gpu_head(monkeypatch):
    c = case(monkeypatch)
    previous = NS(
        **(
            vars(c.cuda)
            | dict(
                graph_snapshot_revision_id=c.cpu.graph_snapshot_revision_id,
                index_revision_id="embeddingindexrev_" + "d" * 32,
                binding_count=604,
            )
        )
    )
    c.session.execute.side_effect = [NS(one_or_none=lambda: None), NS(one_or_none=lambda: previous)]
    assert c.repository.common_public_namespace_revisions(c.cpu.corpus_id, c.cpu_ns, c.cuda_ns) == (
        c.cpu,
        previous,
    )
    assert c.repository.current_namespace_revision.call_count == 2
    compiled = c.session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert c.cpu.graph_snapshot_revision_id in compiled.params.values()
    assert c.cpu.policy_revision_id in compiled.params.values()
    assert c.cpu.policy_sha256 in compiled.params.values()
    assert c.cuda.index_id in compiled.params.values()
    assert 123 in compiled.params.values()
    assert "ORDER BY embedding_index_revisions.revision_number DESC" in str(compiled)
    assert "FOR UPDATE" not in str(compiled)


def test_matching_gpu_head_scope_wins_without_selecting_latest_cpu(monkeypatch):
    c = case(monkeypatch)
    previous = NS(
        **(vars(c.cpu) | dict(graph_snapshot_revision_id=c.cuda.graph_snapshot_revision_id))
    )
    c.session.execute.return_value.one_or_none.return_value = previous
    assert c.repository.common_public_namespace_revisions(c.cpu.corpus_id, c.cpu_ns, c.cuda_ns) == (
        previous,
        c.cuda,
    )
    assert c.session.execute.call_count == 1


def test_distinct_heads_without_common_history_are_explicitly_unavailable(monkeypatch):
    c = case(monkeypatch)
    c.session.execute.return_value.one_or_none.return_value = None
    assert (
        c.repository.common_public_namespace_revisions(c.cpu.corpus_id, c.cpu_ns, c.cuda_ns) is None
    )
    assert c.session.execute.call_count == 3


def test_older_common_scope_uses_bounded_join_and_exact_two_revision_read(monkeypatch):
    c = case(monkeypatch)
    pair = ("embeddingindexrev_" + "d" * 32, "embeddingindexrev_" + "e" * 32)
    c.session.execute.side_effect = [
        NS(one_or_none=lambda: None),
        NS(one_or_none=lambda: None),
        NS(one_or_none=lambda: pair),
    ]
    keys = ((c.cpu.index_id, pair[0]), (c.cuda.index_id, pair[1]))
    c.repository.read_pinned_revisions = Mock(return_value={keys[0]: c.cpu, keys[1]: c.cuda})
    assert c.repository.common_public_namespace_revisions(c.cpu.corpus_id, c.cpu_ns, c.cuda_ns) == (
        c.cpu,
        c.cuda,
    )
    c.repository.read_pinned_revisions.assert_called_once_with(keys)
    sql = c.session.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "JOIN embedding_index_revisions" in str(sql)
    assert "LIMIT" in str(sql) and 120 in sql.params.values() and 123 in sql.params.values()


def test_missing_device_is_not_replaced_by_an_unrelated_namespace(monkeypatch):
    c = case(monkeypatch)
    c.repository.current_namespace_revision.return_value = None
    c.repository.current_namespace_revision.side_effect = None
    assert (
        c.repository.common_public_namespace_revisions(c.cpu.corpus_id, c.cpu_ns, c.cuda_ns) is None
    )
    c.session.execute.assert_not_called()


@pytest.mark.parametrize("fault", ("same_space", "different_partition", "different_recipe"))
def test_device_namespaces_cannot_cross_spaces_partitions_or_recipes(monkeypatch, fault):
    c = case(monkeypatch)
    other = (
        c.cpu_ns
        if fault == "same_space"
        else c.cuda_ns.model_copy(
            update={"storage_partition": "foreign"}
            if fault == "different_partition"
            else {"recipe_sha256": "sha256:" + "f" * 64}
        )
    )
    with pytest.raises(EmbeddingRegistryError, match="REQUEST_INVALID"):
        c.repository.common_public_namespace_revisions(c.cpu.corpus_id, c.cpu_ns, other)
    c.repository.current_namespace_revision.assert_not_called()


def test_exact_scope_read_does_not_use_a_newer_graph_or_policy(monkeypatch):
    c = case(monkeypatch)
    scope = NS(
        corpus_id=c.cpu.corpus_id,
        namespace=c.cuda_ns,
        graph_snapshot=NS(graph_snapshot_revision_id=c.cpu.graph_snapshot_revision_id),
        policy_revision_id=c.cpu.policy_revision_id,
        policy_sha256=c.cpu.policy_sha256,
    )
    c.session.execute.return_value.one_or_none.return_value = None
    assert c.repository.public_revision_for_scope(scope) is None
    assert c.session.execute.call_count == 1


def test_exact_scope_matching_head_does_not_scan_any_history(monkeypatch):
    c = case(monkeypatch)
    scope = NS(
        corpus_id=c.cpu.corpus_id,
        namespace=c.cpu_ns,
        graph_snapshot=NS(graph_snapshot_revision_id=c.cpu.graph_snapshot_revision_id),
        policy_revision_id=c.cpu.policy_revision_id,
        policy_sha256=c.cpu.policy_sha256,
    )
    assert c.repository.public_revision_for_scope(scope) is c.cpu
    c.session.execute.assert_not_called()
