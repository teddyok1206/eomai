"""Supported owner policy publication in the marker-guarded disposable DB only.

No actual machine runtime, source file/model, service/Catalog runtime grant or
activation is claimed. Committed synthetic publication/audit metadata is retained.
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Barrier
from uuid import uuid4

import pytest
from eom_catalog_contracts.local_indexing_mixed_policy import LocalIndexingMixedAccessPolicy
from eom_catalog_contracts.local_indexing_policy import LocalIndexingAccessPolicy
from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalAccessPolicyRevisionRecord,
    KnowledgeCorpusRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)
from eom_catalog_service.local_indexing_policy_publication import (
    LocalIndexingPolicyPublicationError,
    publish_local_indexing_access_policy,
)
from eom_identifiers import content_sha256
from eom_identity_service import (
    activate_local_indexing_service,
    disable_local_indexing_service,
    register_local_indexing_service,
)
from eom_identity_service.models import OperatorRecord
from eom_operator_identity import LocalIndexingServiceIdentity, local_indexing_service_reference
from eom_orchestrator.database import build_native_embedding_controller_engine
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session

from tests.integration.test_local_indexing_service_registry import identity
from tests.integration.test_preset_model_validation_persistence import (
    guarded_engine as guarded_engine,
)
from tests.unit.test_local_indexing_policy_publication import policy_for, source_policy

pytestmark = [pytest.mark.integration, pytest.mark.api_integration]


@pytest.fixture(autouse=True)
def exact_opt_in() -> None:
    if os.environ.get("EOM_RUN_LOCAL_INDEXING_SERVICE_INTEGRATION") != "1":
        pytest.skip("use guarded local-indexing-service-tests; never production")


@dataclass(frozen=True)
class Case:
    engine: Engine
    identity: LocalIndexingServiceIdentity
    policy: LocalIndexingAccessPolicy

    def publish(self):
        with Session(self.engine) as session, session.begin():
            return publish_local_indexing_access_policy(session, self.policy)


@pytest.fixture
def case(guarded_engine: Engine) -> Case:
    native = build_native_embedding_controller_engine()
    assert (native.url.database, native.url.username) == (
        guarded_engine.url.database,
        guarded_engine.url.username,
    )
    item = identity(database_role=guarded_engine.url.username)
    source = source_policy(access_policy_revision_id="accessrev_" + uuid4().hex)
    corpus_id, graph_id = "corpus_" + uuid4().hex, "graph_" + uuid4().hex
    policy = policy_for(
        source,
        access_policy_revision_id="accessrev_" + uuid4().hex,
        service=local_indexing_service_reference(item).model_dump(mode="json"),
        corpus_id=corpus_id,
        graph_id=graph_id,
    )
    with Session(guarded_engine) as session, session.begin():
        register_local_indexing_service(session, item, operation_key="synthetic-pub:" + uuid4().hex)
        activate_local_indexing_service(
            session,
            local_indexing_service_reference(item),
            expected_resource_version=1,
            operation_key="synthetic-pub-active:" + uuid4().hex,
        )
        actor = "operator_" + uuid4().hex
        username = "synthetic-pub-" + uuid4().hex[:12]
        session.add(
            OperatorRecord(
                operator_id=actor,
                username=username,
                normalized_username=username,
                display_name="Synthetic corpus provenance only",
                status="ACTIVE",
                role_version=1,
                must_change_password=False,
                created_by="disposable-fixture",
            )
        )
        session.flush()
        session.add(
            KnowledgeCorpusRecord(
                corpus_id=corpus_id,
                corpus_key="synthetic-pub-" + uuid4().hex,
                display_name="Synthetic metadata only",
                graph_id=graph_id,
                lifecycle_state="ACTIVE",
                lock_version=1,
                created_by_operator_id=actor,
            )
        )
        session.add(
            EducationRetrievalAccessPolicyRevisionRecord(
                access_policy_revision_id=source.access_policy_revision_id,
                schema_version=source.schema_version,
                state="RELEASED",
                content_sha256=source.content_sha256,
                canonical_document=source.model_dump(mode="json"),
                created_by=guarded_engine.url.username,
                created_at=source.created_at,
            )
        )
    try:
        yield Case(native, item, policy)
    finally:
        native.dispose()


def test_actual_owner_publication_replay_and_principal_audit(case: Case) -> None:
    first, second = case.publish(), case.publish()
    assert first.created and not second.created
    assert (
        first.policy_revision_id
        == second.policy_revision_id
        == case.policy.access_policy_revision_id
    )
    assert first.policy_sha256 == second.policy_sha256 == case.policy.content_sha256
    assert first.published_by == second.published_by == case.engine.url.username
    assert first.created_at == case.policy.created_at
    with Session(case.engine) as session:
        row = session.get(EducationRetrievalAccessPolicyRevisionRecord, first.policy_revision_id)
        assert row.canonical_document == case.policy.model_dump(mode="json")


def test_actual_mixed_policy_publication_replay_and_exact_versioned_read(case: Case) -> None:
    """New policy retains real owner/source locks; no runtime or source activation."""
    values = case.policy.model_dump(mode="json", exclude={"content_sha256"})
    values.update(
        schema_version="education-retrieval-access-policy/1.2",
        access_policy_revision_id="accessrev_" + uuid4().hex,
        answer_bearing_use="ACCEPTED_SOLUTION_OR_REGISTERED_REVIEW_PROJECTION_ONLY",
    )
    for namespace in values["namespaces"]:
        namespace["projection_version"] = "mixed-solution-comparison/2.0"
        namespace["population_scope"] = "ALL_ADMITTED_GRAPH_ITEMS"
    policy = LocalIndexingMixedAccessPolicy.model_validate(
        values | {"content_sha256": content_sha256(values)}
    )
    results = []
    for _ in range(2):
        with Session(case.engine) as session, session.begin():
            results.append(publish_local_indexing_access_policy(session, policy))
    assert [result.created for result in results] == [True, False]
    assert {result.policy_sha256 for result in results} == {policy.content_sha256}
    assert {result.published_by for result in results} == {case.engine.url.username}
    with Session(case.engine) as session, session.begin():
        resolved = KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
            session, policy.access_policy_revision_id, sha256=policy.content_sha256
        )
        assert type(resolved) is LocalIndexingMixedAccessPolicy and resolved == policy
        with pytest.raises(KnowledgeRetrievalServiceError) as caught:
            KnowledgeRetrievalApplicationService.resolve_local_indexing_access_policy(
                session, policy.access_policy_revision_id, sha256="sha256:" + "f" * 64
            )
        assert caught.value.code == "KNOWLEDGE_RETRIEVAL_POLICY_STALE"
        row = session.get(
            EducationRetrievalAccessPolicyRevisionRecord, policy.access_policy_revision_id
        )
        assert row.schema_version == policy.schema_version
        assert row.canonical_document == policy.model_dump(mode="json")


def test_actual_conflicting_revision_never_updates_original(case: Case) -> None:
    original = case.publish()
    values = case.policy.model_dump(mode="json", exclude={"content_sha256"})
    values["maximum_sources"] = 100
    changed = LocalIndexingAccessPolicy.model_validate(
        values | {"content_sha256": content_sha256(values)}
    )
    with Session(case.engine) as session, session.begin():
        with pytest.raises(LocalIndexingPolicyPublicationError, match="CONFLICT"):
            publish_local_indexing_access_policy(session, changed)
        # Only the savepoint failed; committing the clean outer root cannot repair/overwrite it.
        assert session.is_active
    assert case.publish().policy_sha256 == original.policy_sha256


@pytest.mark.parametrize("round_id", range(6))
def test_actual_two_independent_roots_insert_once(case: Case, round_id: int) -> None:
    barrier = Barrier(2)
    diagnostics: list[tuple[str | None, str | None]] = []

    def database_error(context) -> None:
        error = context.original_exception
        diagnostics.append(
            (
                getattr(error, "sqlstate", None),
                getattr(getattr(error, "diag", None), "constraint_name", None),
            )
        )

    def publish():
        with Session(case.engine) as session, session.begin():
            barrier.wait(timeout=10)
            return publish_local_indexing_access_policy(session, case.policy)

    event.listen(case.engine, "handle_error", database_error)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            try:
                results = tuple(pool.map(lambda _index: publish(), range(2)))
            except LocalIndexingPolicyPublicationError:
                pytest.fail(f"concurrent publication failed; sanitized diagnostics={diagnostics}")
    finally:
        event.remove(case.engine, "handle_error", database_error)
    assert sorted(result.created for result in results) == [False, True]
    assert {result.policy_sha256 for result in results} == {case.policy.content_sha256}
    assert diagnostics == []


def test_actual_disable_denies_new_and_replayed_publication_without_deleting_history(case) -> None:
    case.publish()
    with Session(case.engine) as session, session.begin():
        disable_local_indexing_service(
            session,
            case.identity.service_id,
            expected_resource_version=2,
            operation_key="synthetic-pub-disable:" + uuid4().hex,
        )
    with pytest.raises(LocalIndexingPolicyPublicationError, match="SCOPE_INVALID"):
        case.publish()
    with Session(case.engine) as session:
        assert (
            session.get(
                EducationRetrievalAccessPolicyRevisionRecord, case.policy.access_policy_revision_id
            )
            is not None
        )


@pytest.mark.parametrize(
    "fault",
    ["missing_source", "wrong_source_hash", "missing_corpus", "wrong_graph", "parent_scope"],
)
def test_actual_scope_denials_create_no_policy(case, fault) -> None:
    values = case.policy.model_dump(mode="json", exclude={"content_sha256"})
    if fault == "missing_source":
        values["source_access_policy_revision_id"] = "accessrev_" + uuid4().hex
    elif fault == "wrong_source_hash":
        values["source_access_policy_sha256"] = "sha256:" + "f" * 64
    elif fault == "missing_corpus":
        values["corpus_id"] = "corpus_" + uuid4().hex
    elif fault == "wrong_graph":
        values["graph_id"] = "graph_" + uuid4().hex
    else:
        values["source_classes"] = ["APPROVED_ITEM", "PAST_EXAM"]
    changed = LocalIndexingAccessPolicy.model_validate(
        values | {"content_sha256": content_sha256(values)}
    )
    with Session(case.engine) as session, session.begin():
        with pytest.raises(LocalIndexingPolicyPublicationError, match="SCOPE_INVALID"):
            publish_local_indexing_access_policy(session, changed)
        assert (
            session.get(
                EducationRetrievalAccessPolicyRevisionRecord, changed.access_policy_revision_id
            )
            is None
        )


def test_actual_smaller_wait_limits_restored_after_success(case) -> None:
    with Session(case.engine) as session, session.begin():
        session.execute(text("SET LOCAL lock_timeout = '90ms'"))
        session.execute(text("SET LOCAL statement_timeout = '2s'"))
        publish_local_indexing_access_policy(session, case.policy)
        assert session.scalar(text("SELECT current_setting('lock_timeout')")) == "90ms"
        assert session.scalar(text("SELECT current_setting('statement_timeout')")) == "2s"


def test_actual_initial_savepoint_is_not_an_owner_root(case) -> None:
    with (
        Session(case.engine) as session,
        session.begin(),
        session.begin_nested(),
        pytest.raises(LocalIndexingPolicyPublicationError, match="CONTEXT_INVALID"),
    ):
        publish_local_indexing_access_policy(session, case.policy)


def test_actual_ordinary_app_public_engine_is_not_native_control_scope(
    case, guarded_engine
) -> None:
    with (
        Session(guarded_engine) as session,
        session.begin(),
        pytest.raises(LocalIndexingPolicyPublicationError, match="CONTEXT_INVALID"),
    ):
        publish_local_indexing_access_policy(session, case.policy)


def test_actual_control_writer_timeout_preserved_then_exact_publication_replays(case) -> None:
    def publish_while_locked():
        with Session(case.engine) as session, session.begin():
            session.execute(text("SET LOCAL lock_timeout = '80ms'"))
            return publish_local_indexing_access_policy(session, case.policy)

    with Session(case.engine) as writer, writer.begin():
        activate_local_indexing_service(
            writer,
            local_indexing_service_reference(case.identity),
            expected_resource_version=2,
            operation_key="synthetic-pub-lock:" + uuid4().hex,
        )
        with (
            ThreadPoolExecutor(max_workers=1) as pool,
            pytest.raises(LocalIndexingPolicyPublicationError, match="PUBLICATION_BUSY") as caught,
        ):
            pool.submit(publish_while_locked).result(timeout=10)
        assert caught.value.__cause__ is None
    first, replay = case.publish(), case.publish()
    assert first.created and not replay.created


def test_actual_non_pk_hash_conflict_is_not_a_successful_replay_or_repair(case) -> None:
    with Session(case.engine) as session, session.begin():
        unrelated_id = "accessrev_" + uuid4().hex
        session.add(
            EducationRetrievalAccessPolicyRevisionRecord(
                access_policy_revision_id=unrelated_id,
                schema_version=case.policy.schema_version,
                state="RELEASED",
                content_sha256=case.policy.content_sha256,
                canonical_document=case.policy.model_dump(mode="json"),
                created_by=case.engine.url.username,
                created_at=case.policy.created_at,
            )
        )
        session.flush()
        with pytest.raises(LocalIndexingPolicyPublicationError, match="CONFLICT"):
            publish_local_indexing_access_policy(session, case.policy)
        assert (
            session.get(
                EducationRetrievalAccessPolicyRevisionRecord, case.policy.access_policy_revision_id
            )
            is None
        )
        assert session.get(EducationRetrievalAccessPolicyRevisionRecord, unrelated_id) is not None
        session.rollback()
