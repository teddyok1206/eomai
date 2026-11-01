"""A pooled PostgreSQL session must never retain an owner advisory lock."""

from threading import Lock
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from eom_orchestrator.artifact_publication_lock import artifact_publication_lock


@pytest.mark.parametrize("fault", ["acquire", "rollback", "unlock", "lost"])
def test_unconfirmed_release_invalidates_physical_session(fault):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.scalar.return_value = True
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: connection)
    method = {"acquire": "execute", "rollback": "rollback", "unlock": "scalar"}.get(fault)
    if method:
        getattr(connection, method).side_effect = RuntimeError("synthetic SQL failure")
    else:
        connection.scalar.return_value = False
    with (
        pytest.raises(RuntimeError),
        artifact_publication_lock(
            engine,
            namespace="test",
            idempotency_key="same",
            local_lock=Lock(),
        ),
    ):
        pass
    connection.invalidate.assert_called_once()


def test_fallback_lock_is_released_on_error():
    lock = Lock()
    engine = SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))
    with (
        pytest.raises(RuntimeError),
        artifact_publication_lock(
            engine,
            namespace="test",
            idempotency_key="same",
            local_lock=lock,
        ),
    ):
        assert lock.locked()
        raise RuntimeError("synthetic owner exit")
    assert not lock.locked()
