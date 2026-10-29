"""One existing deterministic role Job key, shared with no-Job recovery checks."""

from eom_identifiers import content_sha256


def role_job_idempotency_key(
    workflow_id: str, step_key: str, attempt: int, definition_hash: str
) -> str:
    digest = content_sha256(
        {
            "workflow_id": workflow_id,
            "step_key": step_key,
            "attempt": attempt,
            "definition_hash": definition_hash,
        }
    ).removeprefix("sha256:")
    return f"wfstep-{digest}"
