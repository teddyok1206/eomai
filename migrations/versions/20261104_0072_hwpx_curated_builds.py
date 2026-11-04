"""Durable editable delivery for saved mixed-source assemblies.

Revision ID: 20261104_0072
Revises: 20261103_0071
Create Date: 2026-11-04 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261104_0072"
down_revision = "20261103_0071"
branch_labels = None
depends_on = None

# Frozen DDL, not imports from mutable runtime models.
_DDL = (
    """CREATE TABLE hwpx_curated_builds (
build_id VARCHAR(42) NOT NULL,
assembly_id VARCHAR(41) NOT NULL,
assembly_revision_id VARCHAR(44) NOT NULL,
assembly_manifest_sha256 VARCHAR(71) NOT NULL,
input_plan JSONB NOT NULL,
initiator_context JSONB NOT NULL,
input_plan_sha256 VARCHAR(71) NOT NULL,
request_sha256 VARCHAR(71) NOT NULL,
idempotency_key VARCHAR(128) NOT NULL,
created_by_operator_id VARCHAR(41) NOT NULL,
planned_artifact_id VARCHAR(41) NOT NULL,
planned_artifact_revision_id VARCHAR(36) NOT NULL,
planned_job_id VARCHAR(37) NOT NULL,
state VARCHAR(16) NOT NULL,
validation_state VARCHAR(8) NOT NULL,
placement_count INTEGER NOT NULL,
section_count INTEGER,
binary_count INTEGER,
native_table_count INTEGER,
native_equation_count INTEGER,
platform_job_id VARCHAR(36),
output_artifact_id VARCHAR(41),
output_artifact_revision_id VARCHAR(36),
output_sha256 VARCHAR(71),
output_size_bytes INTEGER,
output_filename VARCHAR(160) NOT NULL,
failure_code VARCHAR(80),
created_at TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL,
started_at TIMESTAMP WITH TIME ZONE,
completed_at TIMESTAMP WITH TIME ZONE,
resource_version INTEGER NOT NULL,
PRIMARY KEY (build_id),
CONSTRAINT fk_hwpx_curated_assembly_revision FOREIGN KEY(assembly_id,
assembly_revision_id) REFERENCES curated_document_assembly_revisions (assembly_id,
assembly_revision_id) ON DELETE RESTRICT,
CONSTRAINT uq_hwpx_curated_operator_key UNIQUE (created_by_operator_id,
idempotency_key),
CONSTRAINT ck_hwpx_curated_state CHECK (state IN
('REQUESTED','RUNNING','VALIDATING','SUCCEEDED','FAILED')),
CONSTRAINT ck_hwpx_curated_validation CHECK (validation_state IN
('PENDING','PASS','FAIL')),
CONSTRAINT ck_hwpx_curated_count CHECK (placement_count BETWEEN 1 AND 200 AND
resource_version > 0),
CONSTRAINT ck_hwpx_curated_input_hashes CHECK (assembly_manifest_sha256 ~
'^sha256:[0-9a-f]{64}$' AND request_sha256 ~ '^sha256:[0-9a-f]{64}$' AND
input_plan_sha256 ~ '^sha256:[0-9a-f]{64}$'),
CONSTRAINT ck_hwpx_curated_metadata_budget CHECK (jsonb_typeof(input_plan) = 'object'
AND octet_length(input_plan::text) <= 524288 AND jsonb_typeof(initiator_context) =
'object' AND octet_length(initiator_context::text) <= 4096),
CONSTRAINT ck_hwpx_curated_terminal_evidence CHECK (((state IN
('REQUESTED','RUNNING','VALIDATING') AND validation_state='PENDING' AND completed_at IS
NULL AND output_artifact_id IS NULL AND output_artifact_revision_id IS NULL AND
output_sha256 IS NULL AND failure_code IS NULL) OR (state='SUCCEEDED' AND
validation_state='PASS' AND completed_at IS NOT NULL AND started_at IS NOT NULL AND
platform_job_id IS NOT NULL AND section_count >= placement_count AND binary_count >= 0
AND native_table_count >= 0 AND native_equation_count >= 0 AND
output_artifact_id=planned_artifact_id AND
output_artifact_revision_id=planned_artifact_revision_id AND output_sha256 ~
'^sha256:[0-9a-f]{64}$' AND output_size_bytes BETWEEN 1 AND 268435456 AND failure_code
IS NULL) OR (state='FAILED' AND validation_state='FAIL' AND completed_at IS NOT NULL AND
failure_code IS NOT NULL AND output_artifact_id IS NULL AND output_artifact_revision_id
IS NULL AND output_sha256 IS NULL)) IS TRUE),
FOREIGN KEY(created_by_operator_id) REFERENCES operators (operator_id) ON DELETE
RESTRICT,
UNIQUE (planned_artifact_id),
UNIQUE (planned_artifact_revision_id),
UNIQUE (planned_job_id),
UNIQUE (platform_job_id),
FOREIGN KEY(platform_job_id) REFERENCES jobs (job_id),
FOREIGN KEY(output_artifact_id) REFERENCES artifacts (logical_artifact_id),
FOREIGN KEY(output_artifact_revision_id) REFERENCES artifact_revisions (revision_id)
)""",
    """CREATE INDEX ix_hwpx_curated_owner_recent ON hwpx_curated_builds
(created_by_operator_id, created_at, build_id)""",
    """CREATE INDEX ix_hwpx_curated_recovery ON hwpx_curated_builds (started_at, build_id)
WHERE state IN ('RUNNING','VALIDATING')""",
    """CREATE INDEX ix_hwpx_curated_requested_fifo ON hwpx_curated_builds (created_at,
build_id) WHERE state = 'REQUESTED'""",
    """CREATE INDEX ix_hwpx_curated_revision_history ON hwpx_curated_builds
(assembly_revision_id, created_at, build_id)""",
    """CREATE FUNCTION protect_hwpx_curated_build_identity() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
IF ROW(NEW.build_id, NEW.assembly_id, NEW.assembly_revision_id,
NEW.assembly_manifest_sha256, NEW.input_plan, NEW.input_plan_sha256,
NEW.initiator_context, NEW.request_sha256, NEW.idempotency_key,
NEW.created_by_operator_id, NEW.planned_artifact_id, NEW.planned_artifact_revision_id,
NEW.planned_job_id, NEW.placement_count, NEW.output_filename, NEW.created_at)
IS DISTINCT FROM ROW(OLD.build_id, OLD.assembly_id, OLD.assembly_revision_id,
OLD.assembly_manifest_sha256, OLD.input_plan, OLD.input_plan_sha256,
OLD.initiator_context, OLD.request_sha256, OLD.idempotency_key,
OLD.created_by_operator_id, OLD.planned_artifact_id, OLD.planned_artifact_revision_id,
OLD.planned_job_id, OLD.placement_count, OLD.output_filename, OLD.created_at) THEN
RAISE EXCEPTION 'HWPX_CURATED_BUILD_IDENTITY_IMMUTABLE' USING ERRCODE='23514';
END IF;
IF OLD.state IN ('SUCCEEDED','FAILED') AND NEW IS DISTINCT FROM OLD THEN
RAISE EXCEPTION 'HWPX_CURATED_BUILD_TERMINAL_IMMUTABLE' USING ERRCODE='23514';
END IF;
RETURN NEW;
END;
$$""",
    """CREATE TRIGGER hwpx_curated_build_identity BEFORE UPDATE ON hwpx_curated_builds FOR EACH
ROW EXECUTE FUNCTION protect_hwpx_curated_build_identity()""",
)


def upgrade() -> None:
    for statement in _DDL:
        op.execute(statement)


def downgrade() -> None:
    if op.get_bind().scalar(text("SELECT EXISTS (SELECT 1 FROM hwpx_curated_builds)")):
        raise RuntimeError("HWPX_CURATED_BUILD_HISTORY_EXISTS")
    op.drop_table("hwpx_curated_builds")
    op.execute("DROP FUNCTION protect_hwpx_curated_build_identity()")
