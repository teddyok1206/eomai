"""Real disposable SQL closure; synthetic materialization, no model/NAS/production."""

from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.public_solution_indexing_policy import PublicSolutionIndexingAccessPolicy
from eom_catalog_service.local_indexing_source_ports import LocalIndexingSourceReadIntent
from eom_catalog_service.pinned_artifact_resolution import PinnedArtifactReadContext
from eom_catalog_service.public_solution_capture_ports import CapturedPublicSolutionSources
from eom_catalog_service.public_solution_index_read_set import (
    capture_public_solution_index_population,
)
from eom_catalog_service.public_solution_population_dependencies import (
    observe_public_solution_population_dependencies,
)
from eom_catalog_service.settings import CatalogSettings
from sqlalchemy import text

from tests.integration.test_inference_transfer_candidate_admission import (
    item_source_relation_database as item_source_relation_database,
)
from tests.integration.test_inference_transfer_candidate_admission import occurrence_scope
from tests.integration.test_inference_transfer_candidate_admission import (
    pool_database as pool_database,
)
from tests.integration.test_inference_transfer_candidate_admission import (
    population_observation_database as population_observation_database,
)
from tests.unit.test_public_solution_indexing_policy import public_policy_document

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture
def captured(population_observation_database, tmp_path):
    session = population_observation_database
    scope = occurrence_scope(maximum=1024)
    policy = PublicSolutionIndexingAccessPolicy.model_validate(public_policy_document())
    intent = LocalIndexingSourceReadIntent(
        corpus_id=policy.corpus_id,
        graph_snapshot=scope.graph_snapshot,
        access_policy_revision_id=scope.access_policy_revision_id,
        access_policy_sha256=scope.access_policy_sha256,
        service_policy_revision_id=policy.access_policy_revision_id,
        service_policy_sha256=policy.content_sha256,
        source_classes=scope.source_classes,
        namespace=policy.namespaces[0],
        space=policy.space,
        recipe=policy.recipe,
        native_execution_policy_sha256=policy.native_execution_policy_sha256,
        resource_profile_sha256=policy.resource_profile_sha256,
    )
    reader = PinnedArtifactReadContext.for_session(
        session, CatalogSettings(nas_artifact_root=tmp_path / "not-read")
    )
    value = CapturedPublicSolutionSources((), (), (), intent, None)
    build = Mock(return_value=value)
    reauthorize = Mock(return_value=intent)

    def run():
        return capture_public_solution_index_population(
            session,
            intent,
            reader=reader,
            maximum_sources=16384,
            capture=build,
            reauthorize=reauthorize,
        )

    return NS(**locals())


def test_index_and_human_use_the_same_source_observation(captured):
    case = captured
    assert observe_public_solution_population_dependencies(case.session, case.intent, 16384) == (
        observe_public_solution_population_dependencies(case.session, case.scope, 16384)
    )
    for _ in range(4):
        assert case.run() is case.value
    assert case.build.call_count == 1 and case.reauthorize.call_count == 4


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE pg_temp.items SET lifecycle_state='RETIRED' "
        "WHERE item_id='item_'||lpad('545',32,'0')",
        "UPDATE pg_temp.item_components SET required=false "
        "WHERE item_revision_id='itemrev_'||lpad('545',32,'0')",
        "UPDATE pg_temp.artifacts SET approved=false "
        "WHERE logical_artifact_id='artifact_'||lpad('545',32,'0')",
        "UPDATE pg_temp.artifact_revisions SET content_hash='sha256:'||repeat('b',64) "
        "WHERE revision_id='rev_'||lpad('545',32,'0')",
        "UPDATE pg_temp.jobs SET status='FAILED' WHERE job_id='job_'||lpad('545',32,'0')",
        "UPDATE pg_temp.knowledge_analysis_runs SET canonical_request="
        "canonical_request||jsonb_build_object('changed',true) "
        "WHERE analysis_run_id='analysisrun_'||lpad('545',32,'0')",
        "UPDATE pg_temp.legacy_item_extraction_acceptances SET state='REJECTED' "
        "WHERE acceptance_id='itemacceptance_'||lpad('545',32,'0')",
    ],
)
def test_current_dependency_change_rejects_reuse_without_rematerialization(captured, statement):
    case = captured
    case.run()
    case.session.execute(text(statement))
    with pytest.raises(ValueError, match="POPULATION_CHANGED"):
        case.run()
    assert case.build.call_count == 1


def test_change_during_first_strict_capture_does_not_publish_a_read_set(captured):
    case = captured

    def build():
        case.session.execute(
            text(
                "UPDATE pg_temp.items SET lifecycle_state='RETIRED' "
                "WHERE item_id='item_'||lpad('545',32,'0')"
            )
        )
        return case.value

    case.build.side_effect = build
    with pytest.raises(ValueError, match="POPULATION_CHANGED"):
        case.run()


def test_real_registration_savepoint_commit_and_rollback_are_not_cache_rejections(captured):
    case = captured
    case.run()
    with case.session.begin_nested():
        case.run()
        case.run()
    assert case.build.call_count == 3
    case.run()
    assert case.build.call_count == 4
    nested = case.session.begin_nested()
    case.run()
    case.session.execute(
        text(
            "UPDATE pg_temp.items SET lifecycle_state='RETIRED' "
            "WHERE item_id='item_'||lpad('545',32,'0')"
        )
    )
    # SQL observation is deliberately not used in Registry's savepoint. The
    # original strict materializer remains responsible for source validation.
    case.run()
    nested.rollback()
    case.run()
    assert case.build.call_count == 7


@pytest.mark.parametrize(
    "table,mutation",
    [
        ("workflow_instances", "state='FAILED'"),
        ("workflow_step_runs", "state='FAILED'"),
        ("resolved_execution_plans", "canonical_document=jsonb_build_object('changed',true)"),
    ],
)
def test_creative_producer_closure_is_checked_even_without_ranking(captured, table, mutation):
    case = captured
    for name in ("workflow_instances", "workflow_step_runs", "resolved_execution_plans"):
        case.session.execute(
            text(f"CREATE TEMP TABLE {name} AS SELECT * FROM app.{name} WITH NO DATA")
        )
    for statement in (
        "INSERT INTO pg_temp.workflow_instances(workflow_id,state,initial_request,request_payload) "
        "VALUES ('workflow_creative','COMPLETED','{}','{}')",
        "INSERT INTO pg_temp.workflow_step_runs(step_run_id,workflow_id,platform_job_id,state) "
        "VALUES ('step_creative','workflow_creative','job_'||lpad('545',32,'0'),'SUCCEEDED')",
        "INSERT INTO pg_temp.resolved_execution_plans(plan_id,workflow_id,canonical_document) "
        "VALUES ('plan_creative','workflow_creative','{}')",
    ):
        case.session.execute(text(statement))
    case.run()
    case.session.execute(text(f"UPDATE pg_temp.{table} SET {mutation}"))
    with pytest.raises(ValueError, match="POPULATION_CHANGED"):
        case.run()
    assert case.build.call_count == 1
