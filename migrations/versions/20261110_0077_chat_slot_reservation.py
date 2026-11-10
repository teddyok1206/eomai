"""Reserve an existing worker identity for chat without rewriting historical turns.

Revision ID: 20261110_0077
Revises: 20261109_0076
Create Date: 2026-11-10 UTC
"""

from alembic import op
from sqlalchemy import text

revision = "20261110_0077"
down_revision = "20261109_0076"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""ALTER TABLE general_chat_capacity
      ADD COLUMN worker_slot_id VARCHAR(2),
      ADD CONSTRAINT fk_chat_reserved_worker_slot FOREIGN KEY (worker_slot_id)
        REFERENCES worker_slots(slot_id) ON DELETE RESTRICT,
      ADD CONSTRAINT ck_chat_reserved_worker_slot
        CHECK (worker_slot_id IS NULL OR worker_slot_id='06')
    """)
    op.execute("""ALTER TABLE general_chat_turns
      ADD COLUMN worker_slot_id VARCHAR(2),
      ADD COLUMN auth_binding_id VARCHAR(44),
      ADD COLUMN auth_assignment_revision_id VARCHAR(46),
      ADD CONSTRAINT fk_chat_turn_worker_slot FOREIGN KEY (worker_slot_id)
        REFERENCES worker_slots(slot_id) ON DELETE RESTRICT,
      ADD CONSTRAINT fk_chat_turn_auth_binding FOREIGN KEY (auth_binding_id)
        REFERENCES codex_auth_bindings(binding_id) ON DELETE RESTRICT,
      ADD CONSTRAINT fk_chat_turn_auth_assignment
        FOREIGN KEY (auth_assignment_revision_id, auth_binding_id)
        REFERENCES codex_auth_assignment_revisions(assignment_revision_id, binding_id)
        ON DELETE RESTRICT,
      ADD CONSTRAINT ck_chat_turn_auth_pin CHECK (
        (worker_slot_id IS NULL AND auth_binding_id IS NULL AND auth_assignment_revision_id IS NULL)
        OR (worker_slot_id='06' AND auth_binding_id IS NOT NULL
            AND auth_assignment_revision_id IS NOT NULL AND claim_id IS NOT NULL))
    """)
    op.execute("""CREATE FUNCTION preserve_chat_turn_auth_pin()
      RETURNS trigger LANGUAGE plpgsql AS $$
      BEGIN
        IF OLD.worker_slot_id IS NOT NULL AND
          (OLD.worker_slot_id, OLD.auth_binding_id, OLD.auth_assignment_revision_id)
          IS DISTINCT FROM
          (NEW.worker_slot_id, NEW.auth_binding_id, NEW.auth_assignment_revision_id) THEN
          RAISE EXCEPTION 'chat execution identity is immutable';
        END IF;
        RETURN NEW;
      END $$""")
    op.execute("""CREATE TRIGGER general_chat_turn_auth_pin_immutable BEFORE UPDATE
      ON general_chat_turns FOR EACH ROW EXECUTE FUNCTION preserve_chat_turn_auth_pin()""")


def downgrade() -> None:
    if op.get_bind().scalar(
        text(
            "SELECT EXISTS(SELECT 1 FROM general_chat_capacity WHERE worker_slot_id IS NOT NULL) "
            "OR EXISTS(SELECT 1 FROM general_chat_turns WHERE worker_slot_id IS NOT NULL)"
        )
    ):
        raise RuntimeError("reserved chat execution evidence must be preserved before downgrade")
    op.execute("DROP TRIGGER general_chat_turn_auth_pin_immutable ON general_chat_turns")
    op.execute("DROP FUNCTION preserve_chat_turn_auth_pin()")
    for constraint in (
        "ck_chat_turn_auth_pin",
        "fk_chat_turn_auth_assignment",
        "fk_chat_turn_auth_binding",
        "fk_chat_turn_worker_slot",
    ):
        op.drop_constraint(constraint, "general_chat_turns")
    for column in ("auth_assignment_revision_id", "auth_binding_id", "worker_slot_id"):
        op.drop_column("general_chat_turns", column)
    op.drop_constraint("ck_chat_reserved_worker_slot", "general_chat_capacity")
    op.drop_constraint("fk_chat_reserved_worker_slot", "general_chat_capacity")
    op.drop_column("general_chat_capacity", "worker_slot_id")
