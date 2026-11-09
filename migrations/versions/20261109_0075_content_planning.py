"""Content editions, occurrence placements and user-recorded print snapshots.

Revision ID: 20261109_0075
Revises: 20261105_0074
Create Date: 2026-11-09 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261109_0075"
down_revision = "20261105_0074"
branch_labels = None
depends_on = None

# Frozen PostgreSQL DDL; never import future application models from a migration.
_DDL = (
    """ALTER TABLE deliverable_revisions ADD CONSTRAINT uq_deliverable_revision_owner UNIQUE
(deliverable_revision_id, deliverable_id)""",
    """ALTER TABLE assessment_forms ADD CONSTRAINT uq_assessment_form_owner UNIQUE
(assessment_form_id, deliverable_id)""",
    """ALTER TABLE assessment_form_revisions ADD CONSTRAINT uq_assessment_form_revision_owner
UNIQUE (assessment_form_revision_id, assessment_form_id)""",
    """ALTER TABLE assessment_form_revisions ALTER COLUMN display_label TYPE VARCHAR(200)""",
    """ALTER TABLE curated_document_assembly_revisions ADD COLUMN manifest_schema_version
VARCHAR(64) NOT NULL DEFAULT 'curated-document-assembly-manifest/1.0'""",
    """ALTER TABLE curated_document_assembly_revisions ADD CONSTRAINT uq_curated_revision_profile
UNIQUE (assembly_revision_id, manifest_schema_version), ADD CONSTRAINT
uq_curated_revision_exact_pointer UNIQUE (assembly_id, assembly_revision_id,
manifest_sha256), ADD CONSTRAINT ck_curated_revision_profile CHECK
(manifest_schema_version IN
('curated-document-assembly-manifest/1.0','curated-document-assembly-manifest/2.0') AND
(manifest_schema_version <> 'curated-document-assembly-manifest/2.0' OR
COALESCE(canonical_document->>'schema_version' = manifest_schema_version, false)))""",
    """CREATE SEQUENCE content_product_revision_number_seq""",
    """SELECT setval('content_product_revision_number_seq', GREATEST(COALESCE((SELECT
MAX(revision_number) FROM deliverable_revisions), 0) + 1, 1), false)""",
    """CREATE TABLE content_editions (
	edition_id VARCHAR(40) NOT NULL,
	deliverable_id VARCHAR(44) NOT NULL,
	edition_key VARCHAR(128) NOT NULL,
	current_revision_id VARCHAR(41),
	lock_version INTEGER DEFAULT 1 NOT NULL,
	lifecycle_state VARCHAR(16) NOT NULL,
	created_by VARCHAR(41) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (edition_id),
	CONSTRAINT uq_content_edition_owner UNIQUE (edition_id, deliverable_id),
	CONSTRAINT uq_content_edition_key UNIQUE (deliverable_id, edition_key),
	CONSTRAINT ck_content_edition_lock CHECK (lock_version > 0),
	CONSTRAINT ck_content_edition_state CHECK (lifecycle_state IN ('ACTIVE','ARCHIVED')),
	FOREIGN KEY(deliverable_id) REFERENCES deliverables (deliverable_id) ON DELETE RESTRICT,
	FOREIGN KEY(created_by) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """CREATE INDEX ix_content_edition_product ON content_editions (deliverable_id, edition_id)""",
    """CREATE TABLE content_edition_revisions (
	deliverable_revision_id VARCHAR(41) NOT NULL,
	deliverable_id VARCHAR(44) NOT NULL,
	edition_id VARCHAR(40) NOT NULL,
	revision_number INTEGER NOT NULL,
	previous_revision_id VARCHAR(41),
	academic_year INTEGER,
	composition_sha256 VARCHAR(71) NOT NULL,
	PRIMARY KEY (deliverable_revision_id),
	CONSTRAINT uq_content_edition_revision_number UNIQUE (edition_id, revision_number),
	CONSTRAINT uq_content_edition_revision_owner UNIQUE (edition_id, deliverable_id,
deliverable_revision_id),
	CONSTRAINT uq_content_edition_revision_member UNIQUE (edition_id,
deliverable_revision_id),
	CONSTRAINT fk_content_revision_edition FOREIGN KEY(edition_id, deliverable_id) REFERENCES
content_editions (edition_id, deliverable_id) ON DELETE RESTRICT,
	CONSTRAINT fk_content_revision_product FOREIGN KEY(deliverable_revision_id,
deliverable_id) REFERENCES deliverable_revisions (deliverable_revision_id, deliverable_id)
ON DELETE RESTRICT,
	CONSTRAINT fk_content_revision_predecessor FOREIGN KEY(edition_id, previous_revision_id)
REFERENCES content_edition_revisions (edition_id, deliverable_revision_id) ON DELETE
RESTRICT,
	CONSTRAINT ck_content_revision_chain CHECK (revision_number > 0 AND ((revision_number =
1) = (previous_revision_id IS NULL))),
	CONSTRAINT ck_content_revision_year CHECK (academic_year IS NULL OR academic_year BETWEEN
1900 AND 3000),
	CONSTRAINT ck_content_revision_hash CHECK (composition_sha256 ~ '^sha256:[0-9a-f]{64}$')
)""",
    """CREATE INDEX ix_content_revision_year ON content_edition_revisions (academic_year,
deliverable_revision_id)""",
    """CREATE TABLE content_form_memberships (
	assessment_form_id VARCHAR(37) NOT NULL,
	deliverable_id VARCHAR(44) NOT NULL,
	edition_id VARCHAR(40) NOT NULL,
	assembly_id VARCHAR(41) NOT NULL,
	PRIMARY KEY (assessment_form_id),
	CONSTRAINT uq_content_form_edition UNIQUE (assessment_form_id, edition_id),
	CONSTRAINT uq_content_form_curated_assembly UNIQUE (assembly_id),
	CONSTRAINT uq_content_form_assembly_owner UNIQUE (assessment_form_id, assembly_id),
	CONSTRAINT fk_content_form_product FOREIGN KEY(assessment_form_id, deliverable_id)
REFERENCES assessment_forms (assessment_form_id, deliverable_id) ON DELETE RESTRICT,
	CONSTRAINT fk_content_form_edition FOREIGN KEY(edition_id, deliverable_id) REFERENCES
content_editions (edition_id, deliverable_id) ON DELETE RESTRICT,
	FOREIGN KEY(assembly_id) REFERENCES curated_document_assemblies (assembly_id) ON DELETE
RESTRICT
)""",
    """CREATE INDEX ix_content_form_edition ON content_form_memberships (edition_id,
assessment_form_id)""",
    """CREATE TABLE content_form_revision_compositions (
	assessment_form_revision_id VARCHAR(40) NOT NULL,
	assessment_form_id VARCHAR(37) NOT NULL,
	edition_id VARCHAR(40) NOT NULL,
	section_id VARCHAR(40) NOT NULL,
	assembly_id VARCHAR(41) NOT NULL,
	assembly_revision_id VARCHAR(44) NOT NULL,
	manifest_sha256 VARCHAR(71) NOT NULL,
	placement_count INTEGER NOT NULL,
	PRIMARY KEY (assessment_form_revision_id),
	CONSTRAINT fk_content_form_revision_assembly_owner FOREIGN KEY(assessment_form_id,
assembly_id) REFERENCES content_form_memberships (assessment_form_id, assembly_id) ON
DELETE RESTRICT,
	CONSTRAINT uq_content_form_revision_scope UNIQUE (edition_id, section_id,
assessment_form_revision_id),
	CONSTRAINT fk_content_form_revision_identity FOREIGN KEY(assessment_form_revision_id,
assessment_form_id) REFERENCES assessment_form_revisions (assessment_form_revision_id,
assessment_form_id) ON DELETE RESTRICT,
	CONSTRAINT fk_content_form_revision_edition FOREIGN KEY(assessment_form_id, edition_id)
REFERENCES content_form_memberships (assessment_form_id, edition_id) ON DELETE RESTRICT,
	CONSTRAINT fk_content_form_revision_assembly FOREIGN KEY(assembly_id,
assembly_revision_id, manifest_sha256) REFERENCES curated_document_assembly_revisions
(assembly_id, assembly_revision_id, manifest_sha256) ON DELETE RESTRICT,
	CONSTRAINT ck_content_form_slot_count CHECK (placement_count BETWEEN 0 AND 100000)
)""",
    """CREATE INDEX ix_content_form_revision_assembly ON content_form_revision_compositions
(assembly_revision_id)""",
    """CREATE TABLE content_edition_revision_forms (
	deliverable_revision_id VARCHAR(41) NOT NULL,
	section_id VARCHAR(40) NOT NULL,
	edition_id VARCHAR(40) NOT NULL,
	assessment_form_revision_id VARCHAR(40) NOT NULL,
	leaf_order INTEGER NOT NULL,
	PRIMARY KEY (deliverable_revision_id, section_id),
	CONSTRAINT uq_content_revision_leaf_order UNIQUE (deliverable_revision_id, leaf_order),
	CONSTRAINT uq_content_revision_leaf_form UNIQUE (deliverable_revision_id,
assessment_form_revision_id),
	CONSTRAINT fk_content_leaf_edition_revision FOREIGN KEY(edition_id,
deliverable_revision_id) REFERENCES content_edition_revisions (edition_id,
deliverable_revision_id) ON DELETE RESTRICT,
	CONSTRAINT fk_content_leaf_form_scope FOREIGN KEY(edition_id, section_id,
assessment_form_revision_id) REFERENCES content_form_revision_compositions (edition_id,
section_id, assessment_form_revision_id) ON DELETE RESTRICT,
	CONSTRAINT ck_content_leaf_order CHECK (leaf_order BETWEEN 1 AND 10000)
)""",
    """CREATE INDEX ix_content_leaf_form_revision ON content_edition_revision_forms
(assessment_form_revision_id, deliverable_revision_id)""",
    """CREATE TABLE curated_document_assembly_slots_v2 (
	assembly_revision_id VARCHAR(44) NOT NULL,
	placement_id VARCHAR(42) NOT NULL,
	manifest_schema_version VARCHAR(64) DEFAULT 'curated-document-assembly-manifest/2.0' NOT
NULL,
	position INTEGER NOT NULL,
	placement_kind VARCHAR(40) NOT NULL,
	source_id VARCHAR(40),
	source_revision_id VARCHAR(43),
	item_id VARCHAR(37),
	item_revision_id VARCHAR(40),
	graph_snapshot_revision_id VARCHAR(41),
	canonical_slot JSONB NOT NULL,
	PRIMARY KEY (assembly_revision_id, placement_id),
	CONSTRAINT uq_curated_slot_position UNIQUE (assembly_revision_id, position),
	CONSTRAINT fk_curated_slot_v2_profile FOREIGN KEY(assembly_revision_id,
manifest_schema_version) REFERENCES curated_document_assembly_revisions
(assembly_revision_id, manifest_schema_version) ON DELETE RESTRICT,
	CONSTRAINT ck_curated_slot_v2_profile CHECK (manifest_schema_version =
'curated-document-assembly-manifest/2.0'),
	CONSTRAINT ck_curated_slot_identity CHECK (placement_id ~ '^placement_[0-9a-f]{32}$'),
	CONSTRAINT ck_curated_slot_position CHECK (position BETWEEN 1 AND 100000),
	CONSTRAINT ck_curated_slot_target CHECK ((placement_kind = 'EMPTY' AND source_id IS NULL
AND source_revision_id IS NULL AND item_id IS NULL AND item_revision_id IS NULL AND
graph_snapshot_revision_id IS NULL) OR (placement_kind = 'EXTERNAL_SOURCE_DOCUMENT' AND
source_id IS NOT NULL AND source_revision_id IS NOT NULL AND item_id IS NULL AND
item_revision_id IS NULL AND graph_snapshot_revision_id IS NULL) OR (placement_kind IN
('REGISTERED_ITEM_REVISION','PAST_EXAM_ITEM_REVISION') AND source_id IS NULL AND
source_revision_id IS NULL AND item_id IS NOT NULL AND item_revision_id IS NOT NULL AND
graph_snapshot_revision_id IS NOT NULL)),
	CONSTRAINT ck_curated_slot_small_pointer CHECK (jsonb_typeof(canonical_slot) = 'object'
AND octet_length(canonical_slot::text) <= 16384 AND canonical_slot ?&
ARRAY['placement_id','position','target'] AND canonical_slot->'target' ? 'placement_kind'
AND canonical_slot->>'placement_id' = placement_id AND
(canonical_slot->>'position')::integer = position AND
canonical_slot->'target'->>'placement_kind' = placement_kind AND
(canonical_slot->'target'->>'item_id') IS NOT DISTINCT FROM item_id AND
(canonical_slot->'target'->>'item_revision_id') IS NOT DISTINCT FROM item_revision_id AND
(canonical_slot->'target'->>'source_id') IS NOT DISTINCT FROM source_id AND
(canonical_slot->'target'->>'source_revision_id') IS NOT DISTINCT FROM source_revision_id
AND (canonical_slot->'target'->>'graph_snapshot_revision_id') IS NOT DISTINCT FROM
graph_snapshot_revision_id),
	FOREIGN KEY(source_id) REFERENCES external_item_sources (source_id) ON DELETE RESTRICT,
	FOREIGN KEY(source_revision_id) REFERENCES external_item_source_revisions (revision_id)
ON DELETE RESTRICT,
	FOREIGN KEY(item_id) REFERENCES items (item_id) ON DELETE RESTRICT,
	FOREIGN KEY(item_revision_id) REFERENCES item_revisions (item_revision_id) ON DELETE
RESTRICT,
	FOREIGN KEY(graph_snapshot_revision_id) REFERENCES knowledge_graph_snapshots
(graph_snapshot_revision_id) ON DELETE RESTRICT
)""",
    """CREATE INDEX ix_curated_slot_item ON curated_document_assembly_slots_v2 (item_id,
assembly_revision_id, placement_id) WHERE item_id IS NOT NULL""",
    """CREATE INDEX ix_curated_slot_item_revision ON curated_document_assembly_slots_v2
(item_revision_id, assembly_revision_id) WHERE item_revision_id IS NOT NULL""",
    """CREATE INDEX ix_curated_slot_source ON curated_document_assembly_slots_v2 (source_id,
assembly_revision_id, placement_id) WHERE source_id IS NOT NULL""",
    """CREATE INDEX ix_curated_slot_source_revision ON curated_document_assembly_slots_v2
(source_revision_id, assembly_revision_id) WHERE source_revision_id IS NOT NULL""",
    """CREATE TABLE content_print_records (
	print_record_id VARCHAR(38) NOT NULL,
	edition_id VARCHAR(40) NOT NULL,
	deliverable_revision_id VARCHAR(41) NOT NULL,
	scope_sha256 VARCHAR(71) NOT NULL,
	intent VARCHAR(16) NOT NULL,
	predecessor_print_record_id VARCHAR(38),
	canonical_record JSONB NOT NULL,
	record_sha256 VARCHAR(71) NOT NULL,
	recorded_by VARCHAR(41) NOT NULL,
	recorded_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (print_record_id),
	CONSTRAINT uq_content_print_edition UNIQUE (print_record_id, edition_id),
	CONSTRAINT fk_content_print_revision FOREIGN KEY(edition_id, deliverable_revision_id)
REFERENCES content_edition_revisions (edition_id, deliverable_revision_id) ON DELETE
RESTRICT,
	CONSTRAINT fk_content_print_predecessor FOREIGN KEY(predecessor_print_record_id,
edition_id) REFERENCES content_print_records (print_record_id, edition_id) ON DELETE
RESTRICT,
	CONSTRAINT ck_content_print_intent CHECK ((intent = 'INITIAL' AND
predecessor_print_record_id IS NULL) OR (intent IN ('REPRINT','CORRECTION') AND
predecessor_print_record_id IS NOT NULL AND predecessor_print_record_id <>
print_record_id)),
	CONSTRAINT ck_content_print_hashes CHECK (scope_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
record_sha256 ~ '^sha256:[0-9a-f]{64}$'),
	CONSTRAINT ck_content_print_shape CHECK (jsonb_typeof(canonical_record) = 'object'),
	FOREIGN KEY(recorded_by) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """CREATE INDEX ix_content_print_edition_recent ON content_print_records (edition_id,
recorded_at DESC, print_record_id)""",
    """CREATE INDEX ix_content_print_revision ON content_print_records (deliverable_revision_id)""",
    """CREATE UNIQUE INDEX uq_content_print_initial ON content_print_records (edition_id,
scope_sha256) WHERE intent = 'INITIAL'""",
    """CREATE TABLE content_print_scopes (
	print_record_id VARCHAR(38) NOT NULL,
	assessment_form_revision_id VARCHAR(40) NOT NULL,
	edition_id VARCHAR(40) NOT NULL,
	section_id VARCHAR(40) NOT NULL,
	scope_order INTEGER NOT NULL,
	PRIMARY KEY (print_record_id, assessment_form_revision_id),
	CONSTRAINT uq_content_print_scope_order UNIQUE (print_record_id, scope_order),
	CONSTRAINT uq_content_print_scope_section UNIQUE (print_record_id, section_id),
	CONSTRAINT fk_content_print_scope_owner FOREIGN KEY(print_record_id, edition_id)
REFERENCES content_print_records (print_record_id, edition_id) ON DELETE RESTRICT,
	CONSTRAINT fk_content_print_scope_form FOREIGN KEY(edition_id, section_id,
assessment_form_revision_id) REFERENCES content_form_revision_compositions (edition_id,
section_id, assessment_form_revision_id) ON DELETE RESTRICT,
	CONSTRAINT ck_content_print_scope_order CHECK (scope_order BETWEEN 1 AND 10000)
)""",
    """CREATE INDEX ix_content_print_scope_form ON content_print_scopes
(assessment_form_revision_id, print_record_id)""",
    """CREATE TABLE content_print_events (
	print_record_id VARCHAR(38) NOT NULL,
	sequence INTEGER NOT NULL,
	event_kind VARCHAR(32) NOT NULL,
	replacement_print_record_id VARCHAR(38),
	reason VARCHAR(2000) NOT NULL,
	actor_id VARCHAR(41) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (print_record_id, sequence),
	CONSTRAINT uq_content_print_terminal_event UNIQUE (print_record_id),
	CONSTRAINT ck_content_print_event_sequence CHECK (sequence > 0),
	CONSTRAINT ck_content_print_event_kind CHECK ((event_kind = 'VOID_RECORD' AND
replacement_print_record_id IS NULL) OR (event_kind = 'CORRECT_RECORD' AND
replacement_print_record_id IS NOT NULL AND replacement_print_record_id <>
print_record_id)),
	CONSTRAINT ck_content_print_event_reason CHECK (length(reason) BETWEEN 1 AND 2000),
	FOREIGN KEY(print_record_id) REFERENCES content_print_records (print_record_id) ON DELETE
RESTRICT,
	FOREIGN KEY(replacement_print_record_id) REFERENCES content_print_records
(print_record_id) ON DELETE RESTRICT,
	FOREIGN KEY(actor_id) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """CREATE TABLE content_planning_events (
	edition_id VARCHAR(40) NOT NULL,
	sequence INTEGER NOT NULL,
	command_kind VARCHAR(64) NOT NULL,
	before_revision_id VARCHAR(41),
	after_revision_id VARCHAR(41) NOT NULL,
	change_summary JSONB NOT NULL,
	actor_id VARCHAR(41) NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (edition_id, sequence),
	CONSTRAINT ck_content_event_sequence CHECK (sequence > 0),
	CONSTRAINT fk_content_event_before FOREIGN KEY(edition_id, before_revision_id) REFERENCES
content_edition_revisions (edition_id, deliverable_revision_id) ON DELETE RESTRICT,
	CONSTRAINT fk_content_event_after FOREIGN KEY(edition_id, after_revision_id) REFERENCES
content_edition_revisions (edition_id, deliverable_revision_id) ON DELETE RESTRICT,
	CONSTRAINT ck_content_event_small_metadata CHECK (jsonb_typeof(change_summary) = 'object'
AND octet_length(change_summary::text) <= 1048576),
	FOREIGN KEY(edition_id) REFERENCES content_editions (edition_id) ON DELETE RESTRICT,
	FOREIGN KEY(actor_id) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """CREATE TABLE content_planning_command_receipts (
	actor_id VARCHAR(41) NOT NULL,
	command_kind VARCHAR(64) NOT NULL,
	idempotency_key VARCHAR(128) NOT NULL,
	request_sha256 VARCHAR(71) NOT NULL,
	result_pointer JSONB NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
	PRIMARY KEY (actor_id, command_kind, idempotency_key),
	CONSTRAINT ck_content_command_key CHECK (idempotency_key ~ '^[!-~]{16,128}$'),
	CONSTRAINT ck_content_command_hash CHECK (request_sha256 ~ '^sha256:[0-9a-f]{64}$'),
	CONSTRAINT ck_content_command_small_pointer CHECK (jsonb_typeof(result_pointer) =
'object' AND octet_length(result_pointer::text) <= 16384),
	FOREIGN KEY(actor_id) REFERENCES operators (operator_id) ON DELETE RESTRICT
)""",
    """ALTER TABLE content_editions ADD CONSTRAINT fk_content_edition_current_revision FOREIGN
KEY(edition_id, deliverable_id, current_revision_id) REFERENCES content_edition_revisions
(edition_id, deliverable_id, deliverable_revision_id) ON DELETE RESTRICT""",
)

_GUARDS = (
    """CREATE FUNCTION reject_content_history_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
RAISE EXCEPTION 'CONTENT_PLANNING_HISTORY_IMMUTABLE' USING ERRCODE='23514';
END; $$""",
    """CREATE FUNCTION protect_content_parent_history() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF (TG_TABLE_NAME = 'deliverable_revisions' AND EXISTS (
 SELECT 1 FROM content_edition_revisions r
 WHERE r.deliverable_revision_id = to_jsonb(OLD)->>'deliverable_revision_id'
)) OR (TG_TABLE_NAME = 'assessment_form_revisions' AND EXISTS (
 SELECT 1 FROM content_form_revision_compositions r
 WHERE r.assessment_form_revision_id = to_jsonb(OLD)->>'assessment_form_revision_id'
)) THEN
 RAISE EXCEPTION 'CONTENT_PLANNING_HISTORY_IMMUTABLE' USING ERRCODE='23514';
END IF;
IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
RETURN NEW;
END; $$""",
    """CREATE FUNCTION protect_content_edition_identity() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF TG_OP = 'DELETE' THEN
 RAISE EXCEPTION 'CONTENT_EDITION_HISTORY_EXISTS' USING ERRCODE='23514';
END IF;
IF ROW(NEW.edition_id,NEW.deliverable_id,NEW.edition_key,NEW.created_by,NEW.created_at)
 IS DISTINCT FROM
ROW(OLD.edition_id,OLD.deliverable_id,OLD.edition_key,OLD.created_by,OLD.created_at)
 OR NEW.lock_version <> OLD.lock_version + 1 THEN
 RAISE EXCEPTION 'CONTENT_EDITION_TRANSITION_INVALID' USING ERRCODE='23514';
END IF;
IF NEW.current_revision_id IS DISTINCT FROM OLD.current_revision_id AND NOT EXISTS (
 SELECT 1 FROM content_edition_revisions r
 WHERE r.edition_id=NEW.edition_id AND r.deliverable_revision_id=NEW.current_revision_id
 AND r.previous_revision_id IS NOT DISTINCT FROM OLD.current_revision_id
) THEN
 RAISE EXCEPTION 'CONTENT_EDITION_HEAD_INVALID' USING ERRCODE='23514';
END IF;
RETURN NEW;
END; $$""",
    """CREATE FUNCTION validate_content_revision_membership() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE body jsonb;
BEGIN
SELECT metadata_json INTO STRICT body FROM deliverable_revisions
 WHERE deliverable_revision_id=NEW.deliverable_revision_id;
IF body->>'schema_version' IS DISTINCT FROM 'content-edition-composition/1.0'
 OR body->>'edition_id' IS DISTINCT FROM NEW.edition_id
 OR body->>'deliverable_id' IS DISTINCT FROM NEW.deliverable_id
 OR body->>'deliverable_revision_id' IS DISTINCT FROM NEW.deliverable_revision_id
 OR (body->>'revision_number')::integer IS DISTINCT FROM NEW.revision_number
 OR body->>'previous_revision_id' IS DISTINCT FROM NEW.previous_revision_id
 OR body->>'composition_sha256' IS DISTINCT FROM NEW.composition_sha256
 OR (body->>'academic_year')::integer IS DISTINCT FROM NEW.academic_year THEN
 RAISE EXCEPTION 'CONTENT_REVISION_POINTER_INVALID' USING ERRCODE='23514';
END IF;
IF NEW.previous_revision_id IS NOT NULL AND NOT EXISTS (
 SELECT 1 FROM content_edition_revisions r
 WHERE r.edition_id=NEW.edition_id AND r.deliverable_revision_id=NEW.previous_revision_id
 AND r.revision_number + 1 = NEW.revision_number
) THEN
 RAISE EXCEPTION 'CONTENT_REVISION_CHAIN_INVALID' USING ERRCODE='23514';
END IF;
RETURN NEW;
END; $$""",
    """CREATE FUNCTION validate_content_form_composition() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NOT EXISTS (
 SELECT 1 FROM assessment_form_revisions f
 JOIN content_edition_revisions r ON r.deliverable_revision_id=f.deliverable_revision_id
 WHERE f.assessment_form_revision_id=NEW.assessment_form_revision_id
 AND r.edition_id=NEW.edition_id AND f.assessment_assembly_revision_id IS NULL
) OR NOT EXISTS (
 SELECT 1 FROM curated_document_assembly_revisions a
 WHERE a.assembly_revision_id=NEW.assembly_revision_id
 AND a.manifest_schema_version='curated-document-assembly-manifest/2.0'
 AND jsonb_array_length(a.canonical_document->'placements')=NEW.placement_count
) THEN
 RAISE EXCEPTION 'CONTENT_FORM_COMPOSITION_INVALID' USING ERRCODE='23514';
END IF;
RETURN NEW;
END; $$""",
    """CREATE FUNCTION validate_curated_legacy_placement_profile() RETURNS trigger LANGUAGE
plpgsql AS $$
BEGIN
IF NOT EXISTS (
 SELECT 1 FROM curated_document_assembly_revisions r
 WHERE r.assembly_revision_id=NEW.assembly_revision_id
 AND r.manifest_schema_version='curated-document-assembly-manifest/1.0'
) THEN
 RAISE EXCEPTION 'CURATED_ASSEMBLY_ROW_PROFILE_INVALID' USING ERRCODE='23514';
END IF;
RETURN NEW;
END; $$""",
    """CREATE FUNCTION validate_content_print_scope() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE body jsonb;
BEGIN
SELECT canonical_record->'scope'->'forms'->(NEW.scope_order-1) INTO STRICT body
 FROM content_print_records WHERE print_record_id=NEW.print_record_id;
IF body IS NULL OR body->>'section_id' IS DISTINCT FROM NEW.section_id
 OR body->'form'->>'form_revision_id' IS DISTINCT FROM NEW.assessment_form_revision_id
 OR NOT EXISTS (
 SELECT 1 FROM content_print_records p
 JOIN content_edition_revision_forms f ON
f.deliverable_revision_id=p.deliverable_revision_id
 WHERE p.print_record_id=NEW.print_record_id AND f.section_id=NEW.section_id
 AND f.assessment_form_revision_id=NEW.assessment_form_revision_id
) THEN
 RAISE EXCEPTION 'CONTENT_PRINT_SCOPE_INVALID' USING ERRCODE='23514';
END IF;
RETURN NEW;
END; $$""",
    """CREATE FUNCTION validate_content_print_event() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
IF NEW.event_kind='CORRECT_RECORD' AND NOT EXISTS (
 SELECT 1 FROM content_print_records replacement
 JOIN content_print_records original ON original.print_record_id=NEW.print_record_id
 WHERE replacement.print_record_id=NEW.replacement_print_record_id
 AND replacement.edition_id=original.edition_id
 AND replacement.predecessor_print_record_id=original.print_record_id
 AND replacement.intent='CORRECTION'
) THEN
 RAISE EXCEPTION 'CONTENT_PRINT_CORRECTION_INVALID' USING ERRCODE='23514';
END IF;
RETURN NEW;
END; $$""",
)

_FROZEN_TABLES = (
    "content_edition_revisions",
    "content_form_memberships",
    "content_form_revision_compositions",
    "content_edition_revision_forms",
    "curated_document_assembly_slots_v2",
    "content_print_records",
    "content_print_scopes",
    "content_print_events",
    "content_planning_events",
    "content_planning_command_receipts",
)

_VALIDATORS = (
    ("content_edition_revisions", "validate_content_revision_membership"),
    ("content_form_revision_compositions", "validate_content_form_composition"),
    ("curated_document_assembly_placements", "validate_curated_legacy_placement_profile"),
    ("content_print_scopes", "validate_content_print_scope"),
    ("content_print_events", "validate_content_print_event"),
)


def upgrade() -> None:
    for statement in (*_DDL, *_GUARDS):
        op.execute(statement)
    for table in _FROZEN_TABLES:
        op.execute(
            f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION reject_content_history_mutation()"
        )
    for table, function in _VALIDATORS:
        op.execute(
            f"CREATE TRIGGER {function}_guard BEFORE INSERT ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION {function}()"
        )
    op.execute(
        "CREATE TRIGGER content_edition_identity BEFORE UPDATE OR DELETE ON content_editions "
        "FOR EACH ROW EXECUTE FUNCTION protect_content_edition_identity()"
    )
    for table in ("deliverable_revisions", "assessment_form_revisions"):
        op.execute(
            f"CREATE TRIGGER content_parent_history BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION protect_content_parent_history()"
        )


def downgrade() -> None:
    # A code rollback never authorizes deletion of user-created placement/print history.
    for table in (*_FROZEN_TABLES, "content_editions"):
        if op.get_bind().scalar(text(f"SELECT EXISTS (SELECT 1 FROM {table})")):
            raise RuntimeError("CONTENT_PLANNING_HISTORY_EXISTS")
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS (SELECT 1 FROM curated_document_assembly_revisions "
            "WHERE manifest_schema_version='curated-document-assembly-manifest/2.0') "
            "OR EXISTS (SELECT 1 FROM assessment_form_revisions WHERE length(display_label)>128)"
        )
    ):
        raise RuntimeError("CONTENT_PLANNING_HISTORY_EXISTS")
    for table in ("deliverable_revisions", "assessment_form_revisions"):
        op.execute(f"DROP TRIGGER content_parent_history ON {table}")
    for table, function in _VALIDATORS:
        op.execute(f"DROP TRIGGER {function}_guard ON {table}")
    op.execute("DROP TRIGGER content_edition_identity ON content_editions")
    op.execute("ALTER TABLE content_editions DROP CONSTRAINT fk_content_edition_current_revision")
    for table in reversed(_FROZEN_TABLES):
        op.drop_table(table)
    op.drop_table("content_editions")
    for function in (
        "reject_content_history_mutation",
        "protect_content_parent_history",
        "protect_content_edition_identity",
        "validate_content_revision_membership",
        "validate_content_form_composition",
        "validate_curated_legacy_placement_profile",
        "validate_content_print_scope",
        "validate_content_print_event",
    ):
        op.execute(f"DROP FUNCTION {function}()")
    op.execute("DROP SEQUENCE content_product_revision_number_seq")
    op.execute(
        "ALTER TABLE curated_document_assembly_revisions "
        "DROP CONSTRAINT ck_curated_revision_profile, "
        "DROP CONSTRAINT uq_curated_revision_exact_pointer, "
        "DROP CONSTRAINT uq_curated_revision_profile, DROP COLUMN manifest_schema_version"
    )
    op.execute(
        "ALTER TABLE assessment_form_revisions DROP CONSTRAINT uq_assessment_form_revision_owner"
    )
    op.execute("ALTER TABLE assessment_form_revisions ALTER COLUMN display_label TYPE VARCHAR(128)")
    op.execute("ALTER TABLE assessment_forms DROP CONSTRAINT uq_assessment_form_owner")
    op.execute("ALTER TABLE deliverable_revisions DROP CONSTRAINT uq_deliverable_revision_owner")
