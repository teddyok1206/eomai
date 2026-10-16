"""Entry/import/packaged-unit invariants only; never root execution or real namespace proof."""

import ast
import inspect
from importlib.machinery import ModuleSpec
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

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
    assert names.index("os.setresuid") < names.index("_require_dropped_identity")
    drop_line = next(line for line, name in calls if name == "_require_dropped_identity")
    assert all(
        node.lineno > drop_line
        for node in ast.walk(child)
        if isinstance(node, ast.ImportFrom) and node.module.startswith("eom_")
    )
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
    assert "KillMode=control-group" in template
    assert "EnvironmentFile=/etc/eom/secrets/reference-query-owner.env\n" in template
    assert "EnvironmentFile=/etc/eom/secrets/catalog-manager.env" not in template
    assert "InaccessiblePaths=/etc/eom/secrets/reference-query-owner.env\n" in template
    assert "AmbientCapabilities=CAP_SETUID\n" in template
    assert "AmbientCapabilities=CAP_KILL" not in template
    assert "CapabilityBoundingSet=CAP_SETUID CAP_SETGID CAP_DAC_READ_SEARCH CAP_KILL\n" in template
    assert "CAP_DAC_OVERRIDE" not in template and "CAP_SYS_ADMIN" not in template
    assert "-I -B /opt/eom/embedding-owner-releases/@SOURCE_COMMIT@/" in template
    assert "EOM_REFERENCE_QUERY_CONFIGURATION_SHA256=@CONFIGURATION_SHA256@" in template
    assert "InaccessiblePaths=/home/eom/EOM /home/eom/EOMIS /root/.codex" in template
    assert "/etc/eom/secrets/api.env" not in template
    assert "ReadOnlyPaths=/etc/eom-api" not in template
    assert "ReadOnlyPaths=/srv/eom/conda/envs/eom-api" not in template
    tmpfiles = (root / "infra/tmpfiles/eom-reference-query-owner.conf").read_text()
    assert "d /run/eom-reference-query-owner 2750 eom-workflow-runner eom-api - -" in tmpfiles


def test_parent_forwards_signals_only_to_its_owned_unreaped_child():
    tree = ast.parse(inspect.getsource(module.main))
    kills = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and ast.unparse(node.func) == "os.kill"
    ]
    assert len(kills) == 1
    assert [ast.unparse(argument) for argument in kills[0].args] == ["child", "signum"]
    source = inspect.getsource(module.main)
    assert source.index("child = os.fork()") < source.index("os.kill(child, signum)")
    assert source.index("os.kill(child, signum)") < source.index("os.waitpid(child, 0)")
    assert "suppress(PermissionError)" not in source


def test_signal_capability_is_not_added_to_native_units_or_index_owner():
    root = Path(__file__).resolve().parents[2]
    native = tuple((root / "infra/systemd").glob("eom-embedding-native-*.service"))
    assert len(native) == 5
    index = (
        root
        / "services/workflow_runner/eom_workflow_runner/resources"
        / "eom-embedding-index-owner.service.in"
    )
    assert all("CAP_KILL" not in path.read_text() for path in (*native, index))


@pytest.mark.parametrize(
    "fault",
    (
        "",
        "saved_uid",
        "saved_gid",
        "groups",
        "permitted",
        "effective",
        "ambient",
        "kill_permitted",
        "kill_effective",
        "kill_ambient",
        "nnp",
        "missing",
        "duplicate",
        "oversized",
    ),
)
def test_child_has_no_saved_root_ids_or_retained_capabilities(monkeypatch, fault):
    monkeypatch.setattr(
        module.os, "getresuid", lambda: (990, 990, 0 if fault == "saved_uid" else 990)
    )
    monkeypatch.setattr(
        module.os, "getresgid", lambda: (1000, 1000, 0 if fault == "saved_gid" else 1000)
    )
    monkeypatch.setattr(module.os, "getgroups", lambda: [985] if fault == "groups" else [])
    fields = {
        "CapPrm": "0000000000000000",
        "CapEff": "0000000000000000",
        "CapAmb": "0000000000000000",
        "NoNewPrivs": "1",
    }
    for field, changed in (("CapPrm", "permitted"), ("CapEff", "effective"), ("CapAmb", "ambient")):
        if fault == changed:
            fields[field] = "0000000000000080"
        if fault == "kill_" + changed:
            fields[field] = "0000000000000020"
    if fault == "nnp":
        fields["NoNewPrivs"] = "0"
    if fault == "missing":
        del fields["CapAmb"]
    raw = "\n".join(f"{name}:\t{value}" for name, value in fields.items()).encode()
    if fault == "duplicate":
        raw += b"\nCapPrm:\t0000000000000000"
    elif fault == "oversized":
        raw += b"\n" + b"x" * 8193
    monkeypatch.setattr(module, "Path", lambda _: SimpleNamespace(open=lambda *_: BytesIO(raw)))
    if fault:
        with pytest.raises(ValueError, match="CHILD_PRIVILEGES_RETAINED"):
            module._require_dropped_identity(990, 1000)
    else:
        module._require_dropped_identity(990, 1000)
