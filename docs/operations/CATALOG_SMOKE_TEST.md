# Catalog Smoke Test

1. Run Intake, Content Pack, and Registry doctors.
2. Verify an accepted placeholder Intake and released development pack.
3. Run a `generic-item-development@1.1.0` placeholder workflow.
4. Confirm the registration creates one Item and approved revision.
5. Replay registration and confirm the same IDs are returned.
6. Run a revise workflow and confirm revision 1 is `SUPERSEDED` and revision 2 current.
7. Create, reserve, and fulfill a Usage Plan.
8. Export Items as JSONL and usage as CSV; verify manifest hashes.
9. Run PostgreSQL immutable-trigger tests and `alembic downgrade/upgrade`.
10. Confirm `eom-observe.service` remains active without restart or permission changes.

No step uses real domain content, modifies EOMIS, or writes binary payloads to PostgreSQL.
