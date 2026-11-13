"""Native metadata follows the existing bounded stream and real-actor boundary."""

from __future__ import annotations

import json
import stat
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from eom_catalog_contracts.material_learning_intake import MaterialLearningAcceptance
from eom_catalog_service import material_native_preparation_runtime as runtime
from eom_catalog_service.material_learning_dispatch import dispatch_material_learning
from eom_catalog_service.material_learning_source import MaterialLearningSourceError
from eom_catalog_service.material_learning_store import material_submission_identity
from eom_catalog_service.settings import CatalogSettings
from eom_identifiers import content_sha256

from tests.unit.test_material_native_preparation import _case


@pytest.mark.parametrize("case", ["success", "truncated", "exceeded", "hash", "denied", "disabled"])
def test_native_upload_framing_authorizes_before_read_and_never_publishes_invalid_input(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    _, path, command, *_ = _case(tmp_path, monkeypatch)
    raw = path.read_bytes()
    request = command.model_dump(mode="json")
    identity = material_submission_identity(command.actor_id, command.idempotency_key)
    accepted = MaterialLearningAcceptance(
        material_id=identity.material_id,
        material_revision_id=identity.material_revision_id,
        run_id=identity.first_run_id,
        request_sha256=content_sha256(request),
        replayed=False,
    )
    order = []

    def authorize(value):
        order.append("authorize")
        assert value == command
        if case == "denied":
            raise MaterialLearningSourceError("MATERIAL_LEARNING_PERMISSION_DENIED")

    def prepare(staged, value):
        order.append("prepare")
        assert staged.name == "metadata.xlsx" and staged != path
        assert stat.S_IMODE(staged.stat().st_mode) == 0o600
        assert staged.read_bytes() == raw
        return accepted

    service = SimpleNamespace(
        settings=CatalogSettings(staging_root=tmp_path),
        authorize_upload=Mock(side_effect=authorize),
        prepare_and_create=Mock(side_effect=prepare),
    )
    body = raw
    if case == "truncated":
        body = raw[:-1]
    elif case == "exceeded":
        body += b"X"
    elif case == "hash":
        request["workbook_sha256"] = "sha256:" + "0" * 64

    output = BytesIO()
    dispatch_material_learning(
        request,
        BytesIO(body),
        output,
        sources=None,
        intake=None,
        reads=None,
        native_preparation=None if case == "disabled" else service,
    )
    reply = json.loads(output.getvalue())
    if case == "success":
        assert reply == accepted.model_dump(mode="json")
        assert order == ["authorize", "prepare"]
    else:
        assert reply["status"] == "ERROR"
        service.prepare_and_create.assert_not_called()
    assert not list(tmp_path.glob("material-native-upload.*"))


def test_native_runtime_is_optional_but_partial_or_relative_config_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = Mock(return_value=object())
    monkeypatch.setattr(runtime, "MaterialNativePreparationService", factory)
    settings = CatalogSettings()
    engine = object()
    assert runtime.build_material_native_preparation(engine, settings, environment={}) is None
    env = dict(
        EOM_MATERIAL_NATIVE_TOOL_PYTHON="/opt/eom/native-exam/runtime/bin/python",
        EOM_MATERIAL_NATIVE_CONVERTER_SOURCE_COMMIT="62d95b980a4e3a6766877dd3fb6f7f45f4afcf3d",
        EOM_MATERIAL_NATIVE_CONVERTER_BUNDLE_SHA256="sha256:" + "f" * 64,
    )
    result = runtime.build_material_native_preparation(engine, settings, environment=env)
    assert result is factory.return_value
    assert factory.call_args.kwargs["python"] == Path(env["EOM_MATERIAL_NATIVE_TOOL_PYTHON"])
    assert isinstance(factory.call_args.kwargs["tool"], runtime.SystemdNativeExamFilePreparer)
    for invalid in (
        {"EOM_MATERIAL_NATIVE_TOOL_PYTHON": env["EOM_MATERIAL_NATIVE_TOOL_PYTHON"]},
        {**env, "EOM_MATERIAL_NATIVE_TOOL_PYTHON": "python"},
        {**env, "EOM_MATERIAL_NATIVE_TOOL_PYTHON": ""},
        {**env, "EOM_MATERIAL_NATIVE_CONVERTER_BUNDLE_SHA256": "invalid"},
    ):
        with pytest.raises(ValueError):
            runtime.build_material_native_preparation(engine, settings, environment=invalid)
