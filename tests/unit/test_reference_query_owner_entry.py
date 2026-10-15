"""Entry/import/packaged-unit invariants only; never root execution or real namespace proof."""

import ast
import inspect
from importlib.machinery import ModuleSpec
from pathlib import Path

import pytest
from eom_workflow_runner import reference_query_owner_entry as module


def test_checkout_entry_is_not_an_installed_bootstrap():
    with pytest.raises(ValueError, match="INSTALLATION_UNAVAILABLE"):
        module._installed_site()


def test_selected_owner_imports_reject_ambient_eom_and_numerical_packages(tmp_path, monkeypatch):
    guard = module._InstalledOwnerImports(tmp_path)
    spec = ModuleSpec("eom_sample", loader=None, origin=str(tmp_path / "eom_sample/__init__.py"))
    monkeypatch.setattr(module.importlib.machinery.PathFinder, "find_spec", lambda *_: spec)
    assert guard.find_spec("eom_sample") is spec
    spec.origin = "/home/eom/EOM/not-installed.py"
    with pytest.raises(ModuleNotFoundError):
        guard.find_spec("eom_sample")
    with pytest.raises(ModuleNotFoundError):
        guard.find_spec("eomctl")
    for name in ("torch", "transformers", "sentence_transformers"):
        with pytest.raises(ModuleNotFoundError):
            guard.find_spec(name)
    assert guard.find_spec("decimal") is None


def test_missing_config_pin_fails_before_opening_any_external_file(monkeypatch):
    monkeypatch.delenv("EOM_REFERENCE_QUERY_CONFIGURATION_SHA256", raising=False)
    with pytest.raises(ValueError, match="CONFIGURATION_UNAVAILABLE"):
        module._configuration_bytes()


def test_logs_never_include_exception_text_or_traceback(capsys):
    module._emit("REFERENCE_QUERY_OWNER_STOPPED", error=RuntimeError("synthetic private data"))
    output = capsys.readouterr().out
    assert "RuntimeError" in output and "private data" not in output and "Traceback" not in output


def test_startup_diagnostic_has_only_errno_and_bounded_owned_module_location(capsys):
    namespace = {"__name__": "eom_workflow_runner.synthetic_startup"}
    try:
        exec(
            compile(
                "raise PermissionError(13, 'synthetic private details', '/synthetic/private/file')",
                "/synthetic/private/source.py",
                "exec",
            ),
            namespace,
        )
    except PermissionError as error:
        module._emit("REFERENCE_QUERY_OWNER_STOPPED", error=error)
    output = capsys.readouterr().out
    assert '"errno": "13"' in output
    assert "eom_workflow_runner.synthetic_startup:1" in output
    assert "private" not in output and "Traceback" not in output


def test_uid_drop_and_fork_signal_order_precede_request_handling():
    child = ast.parse(inspect.getsource(module._serve_child))
    calls = sorted(
        (node.lineno, ast.unparse(node.func))
        for node in ast.walk(child)
        if isinstance(node, ast.Call)
    )
    names = [name for _line, name in calls]
    assert names.index("os.setgroups") < names.index("os.setresgid") < names.index("os.setresuid")
    assert names.index("os.setresuid") < names.index("ReferenceQueryOwnerServer")
    parent = inspect.getsource(module.main)
    assert parent.index("signal.SIG_BLOCK") < parent.index("os.fork()")
    assert parent.index("REFERENCE_QUERY_OWNER_PRELOADED_IMPORT_UNAVAILABLE") < parent.index(
        "sys.path.insert"
    )
    assert parent.index("signal.signal(signal.SIGINT, stop_parent)") < parent.index(
        "restore_mask = None"
    )


def test_service_template_isolated_supervisor_without_provider_file_shadowing():
    root = Path(__file__).resolve().parents[2]
    template = (
        root
        / "services/workflow_runner/eom_workflow_runner/resources"
        / "eom-reference-query-owner.service.in"
    ).read_text()
    assert (
        "User=root" in template and "Restart=no" in template and "NoNewPrivileges=yes" in template
    )
    assert "KillMode=control-group" in template and "AmbientCapabilities=\n" in template
    assert "-I -B /opt/eom/embedding-owner-releases/@SOURCE_COMMIT@/" in template
    assert "EOM_REFERENCE_QUERY_CONFIGURATION_SHA256=@CONFIGURATION_SHA256@" in template
    assert "InaccessiblePaths=/home/eom/EOM /home/eom/EOMIS /root/.codex" in template
    assert "/etc/eom/secrets/api.env" not in template
    assert "ReadOnlyPaths=/etc/eom-api" not in template
    assert "ReadOnlyPaths=/srv/eom/conda/envs/eom-api" not in template
    tmpfiles = (root / "infra/tmpfiles/eom-reference-query-owner.conf").read_text()
    assert "d /run/eom-reference-query-owner 2750 eom-workflow-runner eom-api - -" in tmpfiles
