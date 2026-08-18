from pathlib import Path


def test_workflow_submission_migration_is_additive_and_state_scoped() -> None:
    source = Path("migrations/versions/20260818_0007_workflow_submission_idempotency.py").read_text(
        encoding="utf-8"
    )

    assert 'down_revision: str | Sequence[str] | None = "20260817_0006"' in source
    assert '"ix_workflow_instances_request_hash"' in source
    assert '"uq_workflow_active_request_hash"' in source
    assert "postgresql_where=ACTIVE_WORKFLOW_PREDICATE" in source
    assert "UPDATE workflow_instances" not in source
    assert "DELETE FROM workflow_instances" not in source
    for state in (
        "REQUESTED",
        "RUNNING",
        "AWAITING_HUMAN_APPROVAL",
        "REWORK_REQUESTED",
        "APPROVED",
        "REGISTERING",
    ):
        assert state in source
    for state in ("COMPLETED", "FAILED", "CANCELLED"):
        assert f"'{state}'" not in source.split("def upgrade", maxsplit=1)[0]
