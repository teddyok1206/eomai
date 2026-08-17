"""Opaque identifiers for manual content intake."""

from uuid import uuid4


def new_intake_batch_id() -> str:
    return f"intake_{uuid4().hex}"


def new_source_file_id() -> str:
    return f"sourcefile_{uuid4().hex}"


def new_analysis_id() -> str:
    return f"analysis_{uuid4().hex}"


def new_decision_id() -> str:
    return f"decision_{uuid4().hex}"
