"""Workflow failures retain technical causes without leaking source or credential text."""

import json
import logging
from io import StringIO

from eom_workflow_runner.logging import (
    WorkflowJsonFormatter,
    log_workflow_event,
    workflow_failure_metadata,
)


def test_private_message_sql_and_filename_never_enter_failure_metadata():
    namespace = {"__name__": "eom_workflow_runner.synthetic_boundary"}
    exec(
        compile(
            "def fail():\n    raise ValueError('PRIVATE_SOURCE_PASSWORD')\n",
            "/private/secret/path.py",
            "exec",
        ),
        namespace,
    )
    try:
        try:
            namespace["fail"]()
        except ValueError as cause:
            raise RuntimeError("PRIVATE_QUERY_TOKEN") from cause
    except RuntimeError as error:
        metadata = workflow_failure_metadata(error)
    assert metadata == dict(
        cause_type="ValueError", cause_site="eom_workflow_runner.synthetic_boundary:2"
    )
    stream = StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(WorkflowJsonFormatter())
    logger = logging.Logger("synthetic.workflow", logging.INFO)
    logger.addHandler(handler)
    log_workflow_event(
        logger,
        logging.ERROR,
        "platform role execution failed",
        event="WORKFLOW_COMMAND_FAILED",
        **metadata,
    )
    value = json.loads(stream.getvalue())
    assert value["cause_type"] == "ValueError" and value["cause_site"].endswith(":2")
    assert "PRIVATE" not in stream.getvalue() and "/private/" not in stream.getvalue()


def test_only_fixed_code_and_sqlstate_shapes_are_reported():
    class TechnicalFailure(RuntimeError):
        code = "CONTROL_SOURCE_UNAVAILABLE"
        sqlstate = "40001"

    error = TechnicalFailure("private")
    assert workflow_failure_metadata(error) == dict(
        cause_type="TechnicalFailure",
        cause_code="CONTROL_SOURCE_UNAVAILABLE",
        cause_sqlstate="40001",
    )
    error.code = "private-token-with-sensitive-content"
    error.sqlstate = "private-sql"
    assert workflow_failure_metadata(error) == dict(cause_type="TechnicalFailure")


def test_cause_cycles_and_excessive_chains_are_bounded():
    first, second = ValueError("private"), RuntimeError("private")
    first.__cause__, second.__cause__ = second, first
    assert workflow_failure_metadata(first)["cause_type"] == "RuntimeError"
    current = LookupError("private")
    for _ in range(10):
        wrapper = RuntimeError("private")
        wrapper.__cause__ = current
        current = wrapper
    assert workflow_failure_metadata(current)["cause_type"] == "RuntimeError"


def test_unavailable_diagnostic_property_does_not_replace_the_original_failure():
    class OriginalFailure(RuntimeError):
        @property
        def code(self):
            raise ValueError("PRIVATE_DATA")

    assert workflow_failure_metadata(OriginalFailure("PRIVATE_DATA")) == dict(
        cause_type="OriginalFailure"
    )
