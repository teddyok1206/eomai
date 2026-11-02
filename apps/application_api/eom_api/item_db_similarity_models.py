"""API-owned search intent and immutable-result selectors; no scientific payloads."""

from datetime import datetime
from typing import Any

from eom_orchestrator.models import Base
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ItemDbSimilaritySearchRecord(Base):
    __tablename__ = "item_db_similarity_searches"
    __table_args__ = (
        UniqueConstraint("operator_id", "idempotency_key", name="uq_item_db_search_owner_key"),
        Index(
            "ix_item_db_search_owner_recent", "operator_id", text("created_at DESC"), "search_id"
        ),
        CheckConstraint(
            "jsonb_typeof(input_json)='object' "
            "AND input_json ?& ARRAY['schema_version','selections','top_k'] "
            "AND input_json - ARRAY['schema_version','selections','top_k'] = '{}'::jsonb "
            "AND input_json->>'schema_version'='item-db-similarity-list-input/1.0' "
            "AND octet_length(input_json::text)<=65536 "
            "AND jsonb_typeof(input_json->'selections')='array' "
            "AND jsonb_array_length(input_json->'selections') BETWEEN 1 AND 32 "
            "AND jsonb_typeof(input_json->'top_k')='number' "
            "AND (input_json->>'top_k')::integer BETWEEN 1 AND 64 "
            "AND jsonb_typeof(children_json)='array' "
            "AND jsonb_array_length(children_json)<=32 "
            "AND octet_length(children_json::text)<=32768 "
            "AND (pinned_query IS NULL OR octet_length(pinned_query::text)<=65536)",
            name="ck_item_db_search_metadata_bounds",
        ),
        CheckConstraint(
            "state IN ('PREPARING','PENDING','READY','FAILED','UNAVAILABLE') "
            "AND (device IS NULL OR device IN ('CPU','CUDA')) "
            "AND (state <> 'READY' OR (pinned_query IS NOT NULL "
            "AND jsonb_array_length(children_json)=jsonb_array_length(input_json->'selections')))",
            name="ck_item_db_search_state",
        ),
    )

    search_id: Mapped[str] = mapped_column(String(41), primary_key=True)
    operator_id: Mapped[str] = mapped_column(
        ForeignKey("operators.operator_id", ondelete="RESTRICT"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    intent_sha256: Mapped[str] = mapped_column(String(71), nullable=False)
    input_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    pinned_query: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    children_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    device: Mapped[str | None] = mapped_column(String(4), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
