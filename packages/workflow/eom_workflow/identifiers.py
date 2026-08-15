"""Opaque identifiers owned by the workflow subsystem."""

from uuid import uuid4


def new_definition_id() -> str:
    return f"wfdef_{uuid4().hex}"


def new_workflow_id() -> str:
    return f"workflow_{uuid4().hex}"


def new_step_run_id() -> str:
    return f"steprun_{uuid4().hex}"


def new_command_id() -> str:
    return f"wfcmd_{uuid4().hex}"


def new_approval_request_id() -> str:
    return f"approval_{uuid4().hex}"
