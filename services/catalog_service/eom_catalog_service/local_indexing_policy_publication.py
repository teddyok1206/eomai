"""Owner-only immutable Catalog policy publication; never a runtime self-grant."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, cast

from eom_catalog_contracts.local_indexing_mixed_policy import (
    SupportedLocalIndexingAccessPolicy,
    parse_supported_local_indexing_access_policy,
    supported_local_indexing_access_policy_bytes,
)
from eom_catalog_contracts.local_indexing_policy import require_local_indexing_source_policy
from eom_identity_service import lock_current_local_indexing_service_metadata
from eom_operator_identity import (
    LocalIndexingServiceError,
    LocalIndexingServiceErrorCode,
    local_indexing_service_reference,
)
from psycopg.pq import TransactionStatus
from sqlalchemy import Table, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError, IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from eom_catalog_service.knowledge_graph_models import (
    EducationRetrievalAccessPolicyRevisionRecord,
    KnowledgeCorpusRecord,
)
from eom_catalog_service.knowledge_retrieval_service import (
    KnowledgeRetrievalApplicationService,
    KnowledgeRetrievalServiceError,
)

_POLICY = cast(Table, EducationRetrievalAccessPolicyRevisionRecord.__table__)


class LocalIndexingPolicyPublicationError(ValueError):
    def __init__(
        self,
        code: Literal[
            "LOCAL_INDEXING_POLICY_OWNER_REQUIRED",
            "LOCAL_INDEXING_POLICY_CONTEXT_INVALID",
            "LOCAL_INDEXING_POLICY_SCOPE_INVALID",
            "LOCAL_INDEXING_POLICY_PUBLICATION_CONFLICT",
            "LOCAL_INDEXING_POLICY_PUBLICATION_BUSY",
            "LOCAL_INDEXING_POLICY_PUBLICATION_UNAVAILABLE",
        ],
    ) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class LocalIndexingPolicyPublicationResult:
    policy_revision_id: str
    policy_sha256: str
    created: bool
    published_by: str
    created_at: datetime


@contextmanager
def _publication_root(session: Session) -> Iterator[str]:
    root = session.get_transaction()
    if (
        root is None
        or not root.is_active
        or session.get_nested_transaction() is not None
        or session.new
        or session.dirty
        or session.deleted
    ):
        raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_CONTEXT_INVALID")
    connection = session.connection()
    driver = connection.connection.driver_connection
    if (
        connection.dialect.name != "postgresql"
        or connection.dialect.driver != "psycopg"
        or connection.invalidated
        or not connection.in_transaction()
        or connection.in_nested_transaction()
        or getattr(driver, "autocommit", None) is not False
    ):
        raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_CONTEXT_INVALID")
    context = (
        connection.execute(
            text("""
SELECT SESSION_USER AS principal, CURRENT_USER AS role_name,
    pg_catalog.current_setting('transaction_isolation') AS isolation,
    pg_catalog.current_setting('transaction_read_only') AS read_only,
    pg_catalog.current_schemas(false) AS schemas,
    pg_catalog.pg_my_temp_schema() AS temporary_schema,
    (SELECT owner.rolname FROM pg_catalog.pg_namespace namespace
     JOIN pg_catalog.pg_roles owner ON owner.oid=namespace.nspowner
     WHERE namespace.nspname='app') AS schema_owner,
    (SELECT owner.rolname FROM pg_catalog.pg_class object
     JOIN pg_catalog.pg_namespace namespace ON namespace.oid=object.relnamespace
     JOIN pg_catalog.pg_roles owner ON owner.oid=object.relowner
     WHERE namespace.nspname='app' AND object.relname='education_retrieval_access_policy_revisions'
       AND object.relkind='r' AND NOT object.relrowsecurity AND NOT object.relforcerowsecurity)
        AS table_owner
""")
        )
        .mappings()
        .one()
    )
    principal = context["principal"]
    if (
        type(principal) is not str
        or not 1 <= len(principal) <= 63
        or (
            context["role_name"] != principal
            or context["table_owner"] != principal
            or context["schema_owner"] != principal
        )
    ):
        raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_OWNER_REQUIRED")
    if (
        context["isolation"] != "read committed"
        or context["read_only"] != "off"
        or context["schemas"] != ["app", "pg_catalog"]
        or type(context["temporary_schema"]) is not int
        or context["temporary_schema"] != 0
    ):
        raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_CONTEXT_INVALID")
    limits = (
        connection.execute(
            text(
                "SELECT name,setting::pg_catalog.int8 AS milliseconds,"
                "pg_catalog.current_setting(name) AS previous FROM pg_catalog.pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout') AND unit='ms'"
            )
        )
        .mappings()
        .all()
    )
    previous: dict[str, str] = {}
    for row in limits:
        name, actual, prior = row["name"], row["milliseconds"], row["previous"]
        if (
            name not in {"lock_timeout", "statement_timeout"}
            or name in previous
            or type(actual) is not int
            or not 0 <= actual <= 2147483647
            or type(prior) is not str
            or not 0 < len(prior) <= 32
        ):
            raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_CONTEXT_INVALID")
        previous[name] = prior
        cap = 5000 if name == "lock_timeout" else 10000
        connection.execute(
            text("SELECT pg_catalog.set_config(:name,:value,true)"),
            {
                "name": name,
                "value": str(min(actual, cap) if actual else cap) + "ms",
            },
        )
    if set(previous) != {"lock_timeout", "statement_timeout"}:
        raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_CONTEXT_INVALID")
    try:
        yield principal
    finally:
        # Never mask the first PostgreSQL error with SET in an aborted/lost root.
        if (
            session.is_active
            and session.get_transaction() is root
            and root.is_active
            and not connection.invalidated
            and getattr(driver, "closed", True) is False
            and getattr(getattr(driver, "info", None), "transaction_status", None)
            == TransactionStatus.INTRANS
        ):
            for name, value in previous.items():
                connection.execute(
                    text("SELECT pg_catalog.set_config(:name,:value,true)"),
                    {
                        "name": name,
                        "value": value,
                    },
                )


def publish_local_indexing_access_policy(
    session: Session,
    policy: SupportedLocalIndexingAccessPolicy,
) -> LocalIndexingPolicyPublicationResult:
    """Same revision/hash replays; no UPDATE, implicit root, commit, activation or compute."""
    checked = parse_supported_local_indexing_access_policy(policy)
    expected = supported_local_indexing_access_policy_bytes(checked)
    try:
        with _publication_root(session) as principal:
            identity = lock_current_local_indexing_service_metadata(session, checked.service)
            if local_indexing_service_reference(identity) != checked.service:
                raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_SCOPE_INVALID")
            source = KnowledgeRetrievalApplicationService.lock_source_access_policy(
                session,
                checked.source_access_policy_revision_id,
                sha256=checked.source_access_policy_sha256,
            )
            require_local_indexing_source_policy(checked, source)
            corpus = session.scalar(
                select(KnowledgeCorpusRecord)
                .where(
                    KnowledgeCorpusRecord.corpus_id == checked.corpus_id,
                )
                .with_for_update(read=True)
                .execution_options(populate_existing=True)
            )
            if (
                corpus is None
                or corpus.lifecycle_state != "ACTIVE"
                or corpus.graph_id != checked.graph_id
            ):
                raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_SCOPE_INVALID")
            # Identity/source/corpus locks predate this savepoint and survive its rollback.
            with session.begin_nested():
                created = (
                    session.scalar(
                        insert(_POLICY)
                        .values(
                            access_policy_revision_id=checked.access_policy_revision_id,
                            schema_version=checked.schema_version,
                            state=checked.state,
                            content_sha256=checked.content_sha256,
                            canonical_document=checked.model_dump(mode="json"),
                            created_by=principal,
                            created_at=checked.created_at,
                        )
                        # Both revision PK and content SHA are unique. Arbitrate
                        # all unique conflicts, then prove exact PK/bytes below.
                        .on_conflict_do_nothing()
                        .returning(_POLICY.c.access_policy_revision_id)
                        .execution_options(schema_translate_map={None: "app"})
                    )
                    is not None
                )
                record = session.scalar(
                    select(EducationRetrievalAccessPolicyRevisionRecord)
                    .where(
                        EducationRetrievalAccessPolicyRevisionRecord.access_policy_revision_id
                        == checked.access_policy_revision_id,
                    )
                    .with_for_update(read=True)
                    .execution_options(populate_existing=True)
                )
                if record is None or (
                    record.schema_version != checked.schema_version
                    or record.state != "RELEASED"
                    or record.content_sha256 != checked.content_sha256
                    or supported_local_indexing_access_policy_bytes(
                        parse_supported_local_indexing_access_policy(record.canonical_document)
                    )
                    != expected
                    or type(record.created_by) is not str
                    or not 1 <= len(record.created_by) <= 128
                    or record.created_at != checked.created_at
                ):
                    raise LocalIndexingPolicyPublicationError(
                        "LOCAL_INDEXING_POLICY_PUBLICATION_CONFLICT"
                    )
                result = LocalIndexingPolicyPublicationResult(
                    checked.access_policy_revision_id,
                    checked.content_sha256,
                    created,
                    record.created_by,
                    record.created_at.astimezone(UTC),
                )
            return result
    except LocalIndexingPolicyPublicationError:
        raise
    except LocalIndexingServiceError as error:
        if error.code == LocalIndexingServiceErrorCode.BUSY:
            raise LocalIndexingPolicyPublicationError(
                "LOCAL_INDEXING_POLICY_PUBLICATION_BUSY"
            ) from None
        raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_SCOPE_INVALID") from None
    except IntegrityError:
        raise LocalIndexingPolicyPublicationError(
            "LOCAL_INDEXING_POLICY_PUBLICATION_CONFLICT"
        ) from None
    except DBAPIError as error:
        if getattr(error.orig, "sqlstate", None) in {"55P03", "57014", "40P01"}:
            raise LocalIndexingPolicyPublicationError(
                "LOCAL_INDEXING_POLICY_PUBLICATION_BUSY"
            ) from None
        raise LocalIndexingPolicyPublicationError(
            "LOCAL_INDEXING_POLICY_PUBLICATION_UNAVAILABLE"
        ) from None
    except SQLAlchemyError:
        raise LocalIndexingPolicyPublicationError(
            "LOCAL_INDEXING_POLICY_PUBLICATION_UNAVAILABLE"
        ) from None
    except (KnowledgeRetrievalServiceError, ValueError):
        raise LocalIndexingPolicyPublicationError("LOCAL_INDEXING_POLICY_SCOPE_INVALID") from None
