from __future__ import annotations

import hashlib
import os
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LIBRARY = ROOT / "scripts/api/workflow_runner_deployment_hold.sh"
DEPLOY_SCRIPT = ROOT / "scripts/api/deploy_release.sh"
HOLD_SOURCE = ROOT / "infra/systemd/zzzz-eom-workflow-runner-deployment-hold.conf"
BASE_UNIT_SOURCE = ROOT / "infra/systemd/eom-workflow-runner.service"
HOLD_BYTES = b"[Unit]\nRefuseManualStart=yes\nConditionPathExists=!/\n"
HOLD_SHA256 = "d63c1155611f0305d4bcc99da04be6ab89811b7ec1b0abff93e1af118df056e0"
BASE_UNIT_SHA256 = "1688c77a606ea647d498aacbb3f8f75265f459cf888e1495ae82a8d2887b2878"
JOURNAL_CURSOR = (
    "s=0123456789abcdef0123456789abcdef;i=42;b=fedcba9876543210fedcba9876543210;m=123;t=456;x=789"
)
ROTATED_JOURNAL_CURSOR = (
    "s=1123456789abcdef0123456789abcdef;i=43;b=aedcba9876543210fedcba9876543210;m=124;t=457;x=790"
)


def _snapshot(**changes: str) -> str:
    properties = {
        "ActiveState": "inactive",
        "SubState": "dead",
        "UnitFileState": "enabled",
        "MainPID": "0",
        "LoadState": "loaded",
        "FragmentPath": "/etc/systemd/system/eom-workflow-runner.service",
        "DropInPaths": "",
        "RefuseManualStart": "no",
        "NeedDaemonReload": "no",
        "Job": "",
        "InvocationID": "0123456789abcdef0123456789abcdef",
        "ActiveEnterTimestampMonotonic": "123456",
    }
    properties.update(changes)
    return "".join(f"{key}={value}\n" for key, value in properties.items())


def _systemctl(tmp_path: Path, output: str) -> Path:
    path = tmp_path / "systemctl"
    path.write_text(
        "#!/usr/bin/env bash\n"
        '[[ "$1" == show ]] || exit 91\n'
        '[[ "$2" == eom-workflow-runner.service ]] || exit 92\n'
        f"printf '%b' {output!r}\n",
        encoding="utf-8",
    )
    path.chmod(0o700)
    return path


def _run(function: str, *args: str | Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            "/usr/bin/bash",
            "-c",
            'source "$1"; shift; "$@"',
            "hold-test",
            str(LIBRARY),
            function,
            *(str(arg) for arg in args),
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def _run_release_transition_snapshot(
    tmp_path: Path,
    output: str,
    *,
    disabled_on_disk: bool,
) -> subprocess.CompletedProcess[str]:
    fake = tmp_path / "transition-systemctl"
    snapshot = tmp_path / "transition-systemctl.snapshot"
    snapshot.write_text(output, encoding="utf-8")
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'case "$1" in\n'
        '  show) /usr/bin/cat -- "${0}.snapshot" ;;\n'
        + (
            "  is-enabled) printf '%s\\n' disabled; exit 1 ;;\n"
            if disabled_on_disk
            else "  is-enabled) printf '%s\\n' enabled; exit 0 ;;\n"
        )
        + "  *) exit 91 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake.chmod(0o700)
    harness = (
        "set -euo pipefail\n"
        'source "$1"\n'
        "workflow_runner_require_hold_directory() { :; }\n"
        "workflow_runner_require_hold_file() { :; }\n"
        'workflow_runner_release_transition_activation_identity "$2" '
        '"eom-workflow-runner.service"\n'
    )
    return subprocess.run(
        ("/usr/bin/bash", "-c", harness, "release-transition-test", str(LIBRARY), str(fake)),
        check=False,
        capture_output=True,
        text=True,
    )


def _deploy_function(name: str) -> str:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = source.index(f"{name}() {{")
    end = source.index("\n}\n", start) + len("\n}\n")
    return source[start:end]


def _library_function(name: str) -> str:
    source = LIBRARY.read_text(encoding="utf-8")
    start = source.index(f"{name}() {{")
    end = source.index("\n}\n", start) + len("\n}\n")
    return source[start:end]


def _run_verifier_identity_check(
    function: str,
    *,
    source_file: Path,
    target_root: Path,
) -> subprocess.CompletedProcess[str]:
    functions = "\n".join(
        _deploy_function(name)
        for name in (
            "require_workflow_runner_hold_release_verifier_root",
            "require_workflow_runner_hold_release_verifier_target_identity",
            "require_installed_workflow_runner_hold_release_verifier",
        )
    )
    harness = (
        "set -euo pipefail\n"
        'source "$1"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE="$2"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT="$3"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET="${3}/verifier"\n'
        "fail() { printf 'ERROR: %s\\n' \"$1\" >&2; exit 1; }\n"
        + functions
        + f'\n{function} "$(id -u)" "$(id -g)"\n'
    )
    return subprocess.run(
        (
            "/usr/bin/bash",
            "-c",
            harness,
            "verifier-identity-test",
            str(LIBRARY),
            str(source_file),
            str(target_root),
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def _run_verifier_install(
    *,
    source_file: Path,
    target_root: Path,
    current_sha256: str,
    predecessor_sha256: str,
    events: Path,
) -> subprocess.CompletedProcess[str]:
    functions = "\n".join(
        _deploy_function(name)
        for name in (
            "require_workflow_runner_hold_release_verifier_root",
            "require_workflow_runner_hold_release_verifier_target_identity",
            "require_workflow_runner_hold_release_verifier_staged",
            "require_workflow_runner_hold_release_verifier_empty_incoming",
            "require_workflow_runner_hold_release_verifier_complete_incoming",
            "cleanup_workflow_runner_hold_release_verifier_incoming",
            "materialize_workflow_runner_hold_release_verifier_staged",
            "require_installed_workflow_runner_hold_release_verifier",
            "install_workflow_runner_hold_release_verifier",
        )
    )
    harness = (
        "set -euo pipefail\n"
        'source "$1"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE="$2"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT="$3"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET="${3}/verifier"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_STAGED="${3}/.verifier.staged"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256="$4"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_PREDECESSOR_SHA256="$5"\n'
        'events="$6"\n'
        "fail() { printf 'ERROR: %s\\n' \"$1\" >&2; exit 1; }\n"
        "sudo() {\n"
        '  [[ "$1" == -n ]]; shift\n'
        '  printf \'%s\\n\' "$1" >>"${events}"\n'
        '  command_path="$1"; shift\n'
        "  arguments=()\n"
        "  while (($#)); do\n"
        '    if [[ "$1" == -o || "$1" == -g ]]; then shift 2; continue; fi\n'
        '    arguments+=("$1"); shift\n'
        "  done\n"
        '  "${command_path}" "${arguments[@]}"\n'
        "}\n"
        + functions
        + '\ninstall_workflow_runner_hold_release_verifier "$(id -u)" "$(id -g)"\n'
    )
    return subprocess.run(
        (
            "/usr/bin/bash",
            "-c",
            harness,
            "verifier-install-test",
            str(LIBRARY),
            str(source_file),
            str(target_root),
            current_sha256,
            predecessor_sha256,
            str(events),
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def test_canonical_hold_bytes_and_all_pinned_hashes_are_identical() -> None:
    assert HOLD_SOURCE.read_bytes() == HOLD_BYTES
    assert hashlib.sha256(HOLD_BYTES).hexdigest() == HOLD_SHA256
    assert hashlib.sha256(BASE_UNIT_SOURCE.read_bytes()).hexdigest() == BASE_UNIT_SHA256
    helper = LIBRARY.read_text(encoding="utf-8")
    retirement_contract = (
        ROOT / "services/workflow_runner/eom_workflow_runner/retirement_quiescence.py"
    ).read_text(encoding="utf-8")
    assert f"sha256:{HOLD_SHA256}" in helper
    assert f"sha256:{BASE_UNIT_SHA256}" in helper
    assert f"sha256:{HOLD_SHA256}" in retirement_contract
    assert "/zzzz-eom-deployment-hold.conf" in helper
    assert "/zzzz-eom-deployment-hold.conf" in retirement_contract


def test_hold_helper_accepts_exact_stopped_local_unit_snapshot(tmp_path: Path) -> None:
    stopped = _systemctl(tmp_path, _snapshot())

    result = _run(
        "workflow_runner_require_stopped",
        stopped,
        "eom-workflow-runner.service",
    )

    assert result.returncode == 0
    assert result.stdout == ""


def test_hold_acquisition_recovery_accepts_target_present_pending_reload(
    tmp_path: Path,
) -> None:
    stopped = _systemctl(
        tmp_path,
        _snapshot(
            DropInPaths=(
                "/etc/systemd/system/eom-workflow-runner.service.d/zzzz-eom-deployment-hold.conf"
            ),
            RefuseManualStart="yes",
            NeedDaemonReload="yes",
            InvocationID="",
            ActiveEnterTimestampMonotonic="0",
        ),
    )

    result = _run(
        "workflow_runner_stopped_activation_identity",
        stopped,
        "eom-workflow-runner.service",
    )

    assert result.returncode == 0
    assert result.stdout == ":0\n"
    activation = _deploy_function("activate_workflow_runner_deployment_hold")
    assert activation.index("workflow_runner_stopped_activation_identity") < activation.index(
        'systemctl disable --no-reload "${WORKFLOW_RUNNER_SERVICE}"'
    )


@pytest.mark.parametrize(
    ("need_daemon_reload", "disabled_on_disk", "expected_returncode"),
    (("yes", True, 0), ("no", True, 1), ("yes", False, 1)),
)
def test_release_transition_requires_pending_reload_and_disabled_on_disk(
    tmp_path: Path,
    need_daemon_reload: str,
    disabled_on_disk: bool,
    expected_returncode: int,
) -> None:
    result = _run_release_transition_snapshot(
        tmp_path,
        _snapshot(
            UnitFileState="enabled",
            DropInPaths=(
                "/etc/systemd/system/eom-workflow-runner.service.d/zzzz-eom-deployment-hold.conf"
            ),
            RefuseManualStart="yes",
            NeedDaemonReload=need_daemon_reload,
            InvocationID="",
            ActiveEnterTimestampMonotonic="0",
        ),
        disabled_on_disk=disabled_on_disk,
    )

    assert result.returncode == expected_returncode
    assert result.stdout == (":0\n" if expected_returncode == 0 else "")


@pytest.mark.parametrize("unit_file_state", ("enabled", "disabled"))
def test_hold_helper_accepts_synchronized_unheld_acquisition_snapshot(
    tmp_path: Path, unit_file_state: str
) -> None:
    stopped = _systemctl(tmp_path, _snapshot(UnitFileState=unit_file_state))

    result = _run(
        "workflow_runner_unheld_synchronized_activation_identity",
        stopped,
        "eom-workflow-runner.service",
    )

    assert result.returncode == 0
    assert result.stdout == "0123456789abcdef0123456789abcdef:123456\n"


@pytest.mark.parametrize(
    "output",
    (
        _snapshot(UnitFileState="static"),
        _snapshot(DropInPaths="/etc/systemd/system/foreign.conf"),
        _snapshot(RefuseManualStart="yes"),
        _snapshot(NeedDaemonReload="yes"),
    ),
)
def test_synchronized_unheld_acquisition_rejects_nonexact_state(
    tmp_path: Path, output: str
) -> None:
    stopped = _systemctl(tmp_path, output)
    result = _run(
        "workflow_runner_unheld_synchronized_activation_identity",
        stopped,
        "eom-workflow-runner.service",
    )
    assert result.returncode != 0
    assert result.stdout == ""


@pytest.mark.parametrize(
    "output",
    (
        _snapshot(ActiveState="active", SubState="running", MainPID="42"),
        _snapshot(ActiveState="activating", SubState="start", MainPID="42"),
        _snapshot(ActiveState="deactivating", SubState="stop-sigterm", MainPID="42"),
        _snapshot(ActiveState="failed", SubState="failed"),
        _snapshot(MainPID="9"),
        _snapshot(LoadState="not-found", FragmentPath=""),
        _snapshot(FragmentPath="/usr/lib/systemd/system/foreign.service"),
        _snapshot(Job="1234"),
        _snapshot(InvocationID="not-an-invocation-id"),
        _snapshot(ActiveEnterTimestampMonotonic="yesterday"),
        _snapshot(DropInPaths="/tmp/foreign.conf"),
        _snapshot() + "ActiveState=inactive\n",
        "ActiveState=inactive\n",
    ),
)
def test_stopped_helper_rejects_live_transitional_failed_foreign_or_malformed_state(
    tmp_path: Path,
    output: str,
) -> None:
    fake = _systemctl(tmp_path, output)

    result = _run(
        "workflow_runner_require_stopped",
        fake,
        "eom-workflow-runner.service",
    )

    assert result.returncode != 0
    assert result.stdout == ""


def test_hold_file_identity_rejects_hash_mode_and_symlink_tamper(tmp_path: Path) -> None:
    hold = tmp_path / "hold.conf"
    content = b"[Unit]\nRefuseManualStart=yes\nConditionPathExists=!/\n"
    hold.write_bytes(content)
    hold.chmod(0o644)
    expected_hash = "sha256:" + hashlib.sha256(content).hexdigest()
    owner = str(os.getuid())
    group = str(os.getgid())

    assert (
        _run(
            "workflow_runner_require_hold_file",
            hold,
            expected_hash,
            owner,
            group,
            "644",
        ).returncode
        == 0
    )
    hold.chmod(0o664)
    assert (
        _run(
            "workflow_runner_require_hold_file",
            hold,
            expected_hash,
            owner,
            group,
            "644",
        ).returncode
        != 0
    )
    hold.chmod(0o644)
    assert (
        _run(
            "workflow_runner_require_hold_file",
            hold,
            "sha256:" + "f" * 64,
            owner,
            group,
            "644",
        ).returncode
        != 0
    )

    hardlink = tmp_path / "hold-hardlink.conf"
    os.link(hold, hardlink)
    assert (
        _run(
            "workflow_runner_require_hold_file",
            hold,
            expected_hash,
            owner,
            group,
            "644",
        ).returncode
        != 0
    )
    hardlink.unlink()

    symlink = tmp_path / "hold-link.conf"
    symlink.symlink_to(hold)
    assert (
        _run(
            "workflow_runner_require_hold_file",
            symlink,
            expected_hash,
            owner,
            group,
            "644",
        ).returncode
        != 0
    )


def test_activation_identity_rejects_any_invocation_or_timestamp_change() -> None:
    original = "0123456789abcdef0123456789abcdef:123456"

    assert (
        _run("workflow_runner_require_same_activation_identity", original, original).returncode == 0
    )
    assert (
        _run(
            "workflow_runner_require_same_activation_identity",
            original,
            "fedcba9876543210fedcba9876543210:123456",
        ).returncode
        != 0
    )
    assert (
        _run(
            "workflow_runner_require_same_activation_identity",
            original,
            "0123456789abcdef0123456789abcdef:123457",
        ).returncode
        != 0
    )


def test_disable_no_reload_preserves_nonempty_stopped_invocation_identity(tmp_path: Path) -> None:
    fake = tmp_path / "systemctl"
    state = tmp_path / "systemctl.state"
    invocation_id = "0123456789abcdef0123456789abcdef"
    state.write_text(f"enabled:{invocation_id}\n", encoding="ascii")
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'state="${0}.state"\n'
        'IFS=: read -r unit_file_state invocation_id <"${state}"\n'
        'case "$1" in\n'
        "  show)\n"
        '    [[ "$2" == eom-workflow-runner.service ]]\n'
        "    printf '%s\\n' "
        "'ActiveState=inactive' 'SubState=dead' "
        '"UnitFileState=${unit_file_state}" '
        "'MainPID=0' 'LoadState=loaded' "
        "'FragmentPath=/etc/systemd/system/eom-workflow-runner.service' "
        "'DropInPaths=' 'RefuseManualStart=no' 'NeedDaemonReload=no' 'Job=' "
        '"InvocationID=${invocation_id}" '
        "'ActiveEnterTimestampMonotonic=123456'\n"
        "    ;;\n"
        "  disable)\n"
        "    no_reload=false\n"
        '    for argument in "$@"; do [[ "${argument}" == --no-reload ]] && no_reload=true; done\n'
        '    [[ "${no_reload}" == true ]] || invocation_id=""\n'
        '    printf "disabled:%s\\n" "${invocation_id}" >"${state}"\n'
        "    ;;\n"
        "  is-enabled)\n"
        '    if [[ "${unit_file_state}" == disabled ]]; then printf "disabled\\n"; exit 1; fi\n'
        '    printf "enabled\\n"\n'
        "    ;;\n"
        "  *) exit 91 ;;\n"
        "esac\n",
        encoding="ascii",
    )
    fake.chmod(0o700)

    before = _run(
        "workflow_runner_stopped_activation_identity", fake, "eom-workflow-runner.service"
    )
    assert before.returncode == 0
    assert before.stdout == f"{invocation_id}:123456\n"
    assert (
        _run(
            "workflow_runner_unit_disabled_on_disk", fake, "eom-workflow-runner.service"
        ).returncode
        != 0
    )

    implicit_reload = subprocess.run((fake, "disable", "eom-workflow-runner.service"), check=False)
    assert implicit_reload.returncode == 0
    after_gc = _run(
        "workflow_runner_stopped_activation_identity", fake, "eom-workflow-runner.service"
    )
    assert after_gc.returncode == 0
    assert after_gc.stdout == ":123456\n"
    assert (
        _run(
            "workflow_runner_require_same_activation_identity",
            before.stdout.strip(),
            after_gc.stdout.strip(),
        ).returncode
        != 0
    )

    state.write_text(f"enabled:{invocation_id}\n", encoding="ascii")
    no_reload = subprocess.run(
        (fake, "disable", "--no-reload", "eom-workflow-runner.service"), check=False
    )
    assert no_reload.returncode == 0
    assert (
        _run(
            "workflow_runner_unit_disabled_on_disk", fake, "eom-workflow-runner.service"
        ).returncode
        == 0
    )
    after_no_reload = _run(
        "workflow_runner_stopped_activation_identity", fake, "eom-workflow-runner.service"
    )
    assert after_no_reload.stdout == before.stdout
    assert (
        _run(
            "workflow_runner_require_same_activation_identity",
            before.stdout.strip(),
            after_no_reload.stdout.strip(),
        ).returncode
        == 0
    )


def test_hold_acquisition_defers_single_reload_until_hold_is_on_disk_and_enabled() -> None:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    start = source.index("activate_workflow_runner_deployment_hold() {")
    end = source.index("\n\nverify_workflow_runner_deployment_hold()", start)
    activation = source[start:end]
    core = activation[: activation.index("# Commit 6691567")]

    disable = core.index('systemctl disable --no-reload "${WORKFLOW_RUNNER_SERVICE}"')
    materialize = core.index('"${staged_hold}" "${WORKFLOW_RUNNER_HOLD_TARGET}"')
    enable = core.index('systemctl enable --no-reload "${WORKFLOW_RUNNER_SERVICE}"')
    reload = core.index("systemctl daemon-reload")
    held = core.index("workflow_runner_deployment_hold_activation_identity", reload)

    assert disable < materialize < enable < reload < held
    assert core.count("systemctl daemon-reload") == 1
    assert core.count("workflow_runner_require_same_activation_identity") == 3
    assert "workflow_runner_unheld_synchronized_activation_identity" in core


def test_release_journal_fence_is_retry_stable_and_fails_closed(tmp_path: Path) -> None:
    journalctl = tmp_path / "journalctl"
    state = tmp_path / "journalctl.state"
    state.write_text("clean\n", encoding="ascii")
    journalctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'state="$(cat -- "${0}.state")"\n'
        'case " $* " in\n'
        "  *' --until='*)\n"
        '    [[ "${state}" != cursor-failure && "${state}" != permission-failure ]] || exit 1\n'
        '    [[ "${state}" != malformed ]] || { printf "%s\\n" malformed; exit 0; }\n'
        "    observed=1770000000000000\n"
        '    [[ "${state}" != future-cursor ]] || observed=1790000000000000\n'
        f'    printf \'{{"__CURSOR":"{JOURNAL_CURSOR}",\''
        '\'"__REALTIME_TIMESTAMP":"%s"}\\n\' "${observed}"\n'
        f"    printf '%s\\n' '-- cursor: {JOURNAL_CURSOR}'\n"
        "    ;;\n"
        "  *' --cursor='*)\n"
        '    [[ "${state}" != permission-failure ]] || exit 1\n'
        f'    retained="{JOURNAL_CURSOR}"\n'
        f'    [[ "${{state}}" != rotated ]] || retained="{ROTATED_JOURNAL_CURSOR}"\n'
        '    printf \'{"__CURSOR":"%s"}\\n\' "${retained}"\n'
        "    ;;\n"
        "  *' --after-cursor='*)\n"
        '    [[ "${state}" != permission-failure ]] || exit 1\n'
        f'    [[ "${{state}}" != activity ]] || printf \'{{"__CURSOR":"{JOURNAL_CURSOR}"}}\\n\'\n'
        "    ;;\n"
        "  *) exit 91 ;;\n"
        "esac\n",
        encoding="ascii",
    )
    journalctl.chmod(0o700)
    retired_at = "2026-09-08T12:00:00Z"
    retired_at_unix_us = "1780000000000000"

    cursor = _run(
        "workflow_runner_journal_cursor_at_or_before",
        journalctl,
        "--system",
        retired_at,
        retired_at_unix_us,
    )
    assert cursor.returncode == 0
    assert cursor.stdout == f"{JOURNAL_CURSOR}\n"
    before = "0123456789abcdef0123456789abcdef:123456"
    assert (
        _run(
            "workflow_runner_require_release_identity_with_journal_fence",
            before,
            ":0",
            journalctl,
            "--system",
            "eom-workflow-runner.service",
            JOURNAL_CURSOR,
        ).returncode
        == 0
    )

    state.write_text("activity\n", encoding="ascii")
    retry_cursor = _run(
        "workflow_runner_journal_cursor_at_or_before",
        journalctl,
        "--system",
        retired_at,
        retired_at_unix_us,
    )
    assert retry_cursor.returncode == 0
    assert retry_cursor.stdout == cursor.stdout
    assert (
        _run(
            "workflow_runner_require_release_identity_with_journal_fence",
            before,
            ":0",
            journalctl,
            "--system",
            "eom-workflow-runner.service",
            JOURNAL_CURSOR,
        ).returncode
        != 0
    )
    for unavailable_state in ("rotated", "permission-failure"):
        state.write_text(f"{unavailable_state}\n", encoding="ascii")
        assert (
            _run(
                "workflow_runner_require_release_identity_with_journal_fence",
                before,
                ":0",
                journalctl,
                "--system",
                "eom-workflow-runner.service",
                JOURNAL_CURSOR,
            ).returncode
            != 0
        )
    state.write_text("future-cursor\n", encoding="ascii")
    assert (
        _run(
            "workflow_runner_journal_cursor_at_or_before",
            journalctl,
            "--system",
            retired_at,
            retired_at_unix_us,
        ).returncode
        != 0
    )
    for unavailable_state in ("cursor-failure", "permission-failure", "malformed"):
        state.write_text(f"{unavailable_state}\n", encoding="ascii")
        assert (
            _run(
                "workflow_runner_journal_cursor_at_or_before",
                journalctl,
                "--system",
                retired_at,
                retired_at_unix_us,
            ).returncode
            != 0
        )
    state.write_text("clean\n", encoding="ascii")
    assert (
        _run(
            "workflow_runner_require_release_identity_with_journal_fence",
            before,
            "fedcba9876543210fedcba9876543210:123457",
            journalctl,
            "--system",
            "eom-workflow-runner.service",
            JOURNAL_CURSOR,
        ).returncode
        != 0
    )


def test_runtime_mask_cleanup_identity_accepts_only_exact_dev_null_symlink(
    tmp_path: Path,
) -> None:
    owner = str(os.getuid())
    group = str(os.getgid())
    residue = tmp_path / "eom-workflow-runner.service"

    assert (
        _run(
            "workflow_runner_ineffective_runtime_mask_state",
            residue,
            owner,
            group,
        ).stdout
        == "ABSENT\n"
    )
    residue.symlink_to("/dev/null")
    exact = _run(
        "workflow_runner_ineffective_runtime_mask_state",
        residue,
        owner,
        group,
    )
    assert exact.returncode == 0
    assert exact.stdout == "EXACT\n"

    residue.unlink()
    residue.symlink_to("/tmp/foreign")
    foreign = _run(
        "workflow_runner_ineffective_runtime_mask_state",
        residue,
        owner,
        group,
    )
    assert foreign.returncode != 0
    assert foreign.stdout == ""


def test_release_receipt_verifier_is_installed_unprivileged_and_precedes_mutation() -> None:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    operations = (ROOT / "docs/operations/API_PRIVILEGED_DEPLOYMENT.md").read_text(encoding="utf-8")
    gate_start = source.index("release_workflow_runner_deployment_hold_after_verified_receipt() {")
    gate_end = source.index("\n\nverify_mock_exam_deployment_admission()", gate_start)
    gate = source[gate_start:gate_end]

    assert source.startswith("#!/usr/bin/env bash\nset -euo pipefail\n")
    assert 'if (($# > 0)) && [[ "$1" == "--release-workflow-runner-hold" ]]' in source
    assert "(($# == 10))" in source
    assert "install -o root -g root -m 0755" in source
    assert "sudo -n -u eom-api /usr/bin/env -i \\\n" in source
    assert "PYTHONSAFEPATH=1 \\\n" in source
    assert '"${API_PYTHON}" -I "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}"' in source
    verifier = gate.index(
        "verify_workflow_runner_hold_release_receipt --hold-lock-until-release-signal"
    )
    mutation = gate.index("if ! release_workflow_runner_deployment_hold \\")
    assert verifier < mutation
    assert "workflow_runner_hold_release_receipt=VERIFIED_LOCKED" in gate
    assert "release_retired_at_unix_us" in gate
    assert "printf '%s\\n' \"RELEASE_COMPLETE\"" in gate
    assert "workflow_runner_hold_release_receipt=RELEASE_CONFIRMED" in gate
    assert "sudo -n systemd-run --quiet --wait --pipe --collect" in operations
    assert "--expand-environment=no" in operations
    assert "--uid=eom-api --gid=eom-api" in operations
    assert "/var/lib/eom-api/mock-exam-retirement-receipts" in operations
    assert "data.receipt_sha256" in operations
    assert '/usr/bin/ln -T -- "${staged}" "${receipt_file}"' in operations
    assert "sudo -n -u eom-api /usr/bin/install -d -m 0700" in source
    assert "sudo -n -u eom-api /usr/bin/stat --format='%F:%u:%g:%a'" in source
    assert '"directory:${expected_uid}:${expected_gid}:700"' in source
    assert (
        "install -d -o eom-api -g eom-api -m 0700 \\\n"
        '      "${WORKFLOW_RUNNER_RETIREMENT_RECEIPT_ROOT}"' not in source
    )
    for pointer in (
        "RECEIPT_FILE",
        "EXECUTION_ID",
        "EXECUTION_REVISION_ID",
        "CHECKPOINT_SHA256",
        "PRODUCTION_REQUEST_ID",
        "PRODUCTION_PLAN_ID",
        "PRODUCTION_PLAN_SHA256",
        "OPERATOR_ID",
        "RECEIPT_SHA256",
    ):
        assert f'"${{{pointer}}}"' in operations


def test_hold_release_verifier_identity_rejects_owner_mode_link_and_hash_tamper(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.py"
    source_file.write_bytes(b"trusted verifier\n")
    target_root = tmp_path / "libexec"
    target_root.mkdir(mode=0o755)
    target = target_root / "verifier"
    target.write_bytes(source_file.read_bytes())
    target.chmod(0o755)

    exact = _run_verifier_identity_check(
        "require_installed_workflow_runner_hold_release_verifier",
        source_file=source_file,
        target_root=target_root,
    )
    assert exact.returncode == 0, exact.stderr

    target.chmod(0o775)
    wrong_mode = _run_verifier_identity_check(
        "require_installed_workflow_runner_hold_release_verifier",
        source_file=source_file,
        target_root=target_root,
    )
    assert wrong_mode.returncode != 0
    target.chmod(0o755)

    target.write_bytes(b"different verifier\n")
    wrong_hash = _run_verifier_identity_check(
        "require_installed_workflow_runner_hold_release_verifier",
        source_file=source_file,
        target_root=target_root,
    )
    assert wrong_hash.returncode != 0
    target.unlink()
    target.symlink_to(source_file)
    symlink = _run_verifier_identity_check(
        "require_installed_workflow_runner_hold_release_verifier",
        source_file=source_file,
        target_root=target_root,
    )
    assert symlink.returncode != 0

    target.unlink()
    target.write_bytes(source_file.read_bytes())
    target.chmod(0o755)
    hardlink = target_root / "verifier-hardlink"
    os.link(target, hardlink)
    linked = _run_verifier_identity_check(
        "require_installed_workflow_runner_hold_release_verifier",
        source_file=source_file,
        target_root=target_root,
    )
    assert linked.returncode != 0
    hardlink.unlink()

    wrong_owner = subprocess.run(
        (
            "/usr/bin/bash",
            "-c",
            (
                "set -euo pipefail\n"
                'source "$1"\n'
                'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE="$2"\n'
                'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_ROOT="$3"\n'
                'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET="${3}/verifier"\n'
                "fail() { exit 1; }\n"
                + _deploy_function("require_workflow_runner_hold_release_verifier_root")
                + '\nrequire_workflow_runner_hold_release_verifier_root "$(( $(id -u) + 1 ))" '
                '"$(id -g)"\n'
            ),
            "verifier-owner-test",
            str(LIBRARY),
            str(source_file),
            str(target_root),
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert wrong_owner.returncode != 0

    target_root.chmod(0o775)
    wrong_root_mode = _run_verifier_identity_check(
        "require_installed_workflow_runner_hold_release_verifier",
        source_file=source_file,
        target_root=target_root,
    )
    assert wrong_root_mode.returncode != 0


def test_pre_admission_release_boundary_survives_later_admission_failure(
    tmp_path: Path,
) -> None:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    prepare = _deploy_function("prepare_workflow_runner_hold_release_boundary_before_admission")
    install_case = source[
        source.index("  install)\n") : source.index(
            "    ;;\n  release-workflow-runner-hold)", source.index("  install)\n")
        )
    ]
    events = tmp_path / "events"
    harness = (
        "set -euo pipefail\n"
        'events="$1"\n'
        "PRESERVE_WORKFLOW_RUNNER_INACTIVE=true\n"
        "verify_workflow_runner_deployment_hold() { printf '%s\\n' hold >>\"${events}\"; }\n"
        "install_workflow_runner_hold_release_boundary() { "
        "printf '%s\\n' boundary >>\"${events}\"; }\n"
        "verify_mock_exam_deployment_admission() { "
        "printf '%s\\n' admission >>\"${events}\"; return 23; }\n"
        + prepare
        + "\nprepare_workflow_runner_hold_release_boundary_before_admission\n"
        + "set +e\nverify_mock_exam_deployment_admission\nstatus=$?\nset -e\n"
        + "((status == 23))\n"
        + '[[ "$(cat -- "${events}")" == $\'hold\\nboundary\\nhold\\nadmission\' ]]\n'
    )

    completed = subprocess.run(
        ("/usr/bin/bash", "-c", harness, "pre-admission-boundary", str(events)),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert (
        install_case.index("activate_workflow_runner_deployment_hold")
        < install_case.index("prepare_workflow_runner_hold_release_boundary_before_admission")
        < install_case.index("verify_mock_exam_deployment_admission")
    )
    install_service = source[
        source.index("install_service() {") : source.index(
            "\n}\n", source.index("install_service() {")
        )
    ]
    assert "install_workflow_runner_hold_release_boundary" in install_service
    assert (
        '"${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SOURCE}" \\\n'
        '    "${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_TARGET}"' not in install_service
    )


def test_hold_release_boundary_rechecks_source_and_protected_paths_around_install() -> None:
    install = _deploy_function("install_workflow_runner_hold_release_verifier")

    source_before = install.index("source_sha256_before=")
    current_source = install.index('"${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256}"')
    predecessor = install.index('"${WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_PREDECESSOR_SHA256}"')
    materialize = install.index("materialize_workflow_runner_hold_release_verifier_staged")
    source_after = install.index("source_sha256_after=")
    stable_source = install.index('[[ "${source_sha256_after}" == "${source_sha256_before}" &&')
    staged_exact = install.index("require_workflow_runner_hold_release_verifier_staged")
    publish = install.index("/usr/bin/mv -T")
    exact_verifier = install.index(
        "require_installed_workflow_runner_hold_release_verifier", publish
    )

    assert (
        source_before
        < current_source
        < predecessor
        < materialize
        < source_after
        < stable_source
        < publish
        < exact_verifier
    )
    assert staged_exact < publish
    assert "require_workflow_runner_hold_release_verifier_root" in install
    assert "require_workflow_runner_hold_release_verifier_target_identity" in install
    assert "current workflow runner hold-release verifier conflicts with a staged file" in install
    staging = _deploy_function("materialize_workflow_runner_hold_release_verifier_staged")
    unique = staging.index("/usr/bin/mktemp")
    empty = staging.index("require_workflow_runner_hold_release_verifier_empty_incoming")
    copy = staging.index("/usr/bin/install -o root -g root -m 0755 -T")
    complete = staging.index("require_workflow_runner_hold_release_verifier_complete_incoming")
    source_recheck = staging.index("source_sha256_after=")
    staged_publish = staging.index("/usr/bin/mv -T")
    deterministic = staging.index("require_workflow_runner_hold_release_verifier_staged")
    assert unique < empty < copy < complete < source_recheck < staged_publish < deterministic
    assert "cleanup_workflow_runner_hold_release_verifier_incoming" in staging
    assert ".verify-workflow-runner-hold-release.incoming.XXXXXXXXXXXX" in staging
    boundary = _deploy_function("install_workflow_runner_hold_release_boundary")
    assert "install_workflow_runner_hold_release_verifier" in boundary
    assert "sudo -n -u eom-api /usr/bin/install -d -m 0700" in boundary
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    assert (
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_SHA256="sha256:'
        '6c1fc516e8353d9a16201e8828080dcdf81dd6c57bda50523cbb74baeb1ee41c"' in source
    )
    assert (
        'WORKFLOW_RUNNER_HOLD_RELEASE_VERIFIER_PREDECESSOR_SHA256="sha256:'
        '2eef5744d9d33d1ddb6edc766737d930d50eaa5a44c44dbd3431e2228e0b1f89"' in source
    )


def test_verifier_staged_publish_recovers_command_boundary_cuts_and_then_is_noop(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.py"
    source_file.write_bytes(b"current verifier\n")
    current_sha256 = "sha256:" + hashlib.sha256(source_file.read_bytes()).hexdigest()
    predecessor = b"predecessor verifier\n"
    predecessor_sha256 = "sha256:" + hashlib.sha256(predecessor).hexdigest()
    target_root = tmp_path / "libexec"
    target_root.mkdir(mode=0o755)
    target = target_root / "verifier"
    staged = target_root / ".verifier.staged"
    target.write_bytes(predecessor)
    target.chmod(0o755)
    staged.write_bytes(source_file.read_bytes())
    staged.chmod(0o755)
    events = tmp_path / "events"

    resume_after_stage = _run_verifier_install(
        source_file=source_file,
        target_root=target_root,
        current_sha256=current_sha256,
        predecessor_sha256=predecessor_sha256,
        events=events,
    )
    assert resume_after_stage.returncode == 0, resume_after_stage.stderr
    assert target.read_bytes() == source_file.read_bytes()
    assert not staged.exists()
    assert events.read_text(encoding="ascii") == "/usr/bin/mv\n"

    events.unlink()
    replay_after_publish = _run_verifier_install(
        source_file=source_file,
        target_root=target_root,
        current_sha256=current_sha256,
        predecessor_sha256=predecessor_sha256,
        events=events,
    )
    assert replay_after_publish.returncode == 0, replay_after_publish.stderr
    assert target.read_bytes() == source_file.read_bytes()
    assert not staged.exists()
    assert not events.exists()


def test_verifier_publish_rejects_foreign_stage_and_source_drift_without_touching_target(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.py"
    source_file.write_bytes(b"current verifier\n")
    current_sha256 = "sha256:" + hashlib.sha256(source_file.read_bytes()).hexdigest()
    predecessor = b"predecessor verifier\n"
    predecessor_sha256 = "sha256:" + hashlib.sha256(predecessor).hexdigest()
    target_root = tmp_path / "libexec"
    target_root.mkdir(mode=0o755)
    target = target_root / "verifier"
    target.write_bytes(predecessor)
    target.chmod(0o755)
    staged = target_root / ".verifier.staged"
    staged.write_bytes(b"foreign staged bytes\n")
    staged.chmod(0o755)
    events = tmp_path / "events"

    foreign_stage = _run_verifier_install(
        source_file=source_file,
        target_root=target_root,
        current_sha256=current_sha256,
        predecessor_sha256=predecessor_sha256,
        events=events,
    )
    assert foreign_stage.returncode != 0
    assert target.read_bytes() == predecessor
    assert not events.exists()

    staged.unlink()
    source_file.write_bytes(b"source drift\n")
    source_drift = _run_verifier_install(
        source_file=source_file,
        target_root=target_root,
        current_sha256=current_sha256,
        predecessor_sha256=predecessor_sha256,
        events=events,
    )
    assert source_drift.returncode != 0
    assert target.read_bytes() == predecessor
    assert not events.exists()


def test_partial_unique_incoming_is_ignored_and_never_removed_or_trusted(
    tmp_path: Path,
) -> None:
    source_file = tmp_path / "source.py"
    source_file.write_bytes(b"current verifier\n")
    current_sha256 = "sha256:" + hashlib.sha256(source_file.read_bytes()).hexdigest()
    predecessor = b"predecessor verifier\n"
    predecessor_sha256 = "sha256:" + hashlib.sha256(predecessor).hexdigest()
    target_root = tmp_path / "libexec"
    target_root.mkdir(mode=0o755)
    target = target_root / "verifier"
    target.write_bytes(predecessor)
    target.chmod(0o755)
    orphan = target_root / ".verify-workflow-runner-hold-release.incoming.ABCDEF123456"
    orphan.write_bytes(b"partial orphan\n")
    orphan.chmod(0o755)
    events = tmp_path / "events"

    result = _run_verifier_install(
        source_file=source_file,
        target_root=target_root,
        current_sha256=current_sha256,
        predecessor_sha256=predecessor_sha256,
        events=events,
    )

    assert result.returncode == 0, result.stderr
    assert target.read_bytes() == source_file.read_bytes()
    assert orphan.read_bytes() == b"partial orphan\n"
    assert events.read_text(encoding="ascii").splitlines() == [
        "/usr/bin/mktemp",
        "/usr/bin/install",
        "/usr/bin/mv",
        "/usr/bin/mv",
    ]


@pytest.mark.parametrize(
    ("unit_file_state", "need_daemon_reload", "expected_candidates"),
    (
        (
            "enabled",
            "yes",
            (
                "deployment-hold-candidate",
                "reboot-fenced-candidate",
                "transition-candidate",
                "disable-no-reload",
                "transition-candidate",
            ),
        ),
        (
            "disabled",
            "no",
            (
                "deployment-hold-candidate",
                "reboot-fenced-candidate",
                "disable-no-reload",
                "transition-candidate",
                "reboot-fenced-candidate",
            ),
        ),
    ),
)
def test_hold_release_retries_target_present_exact_state_before_move(
    tmp_path: Path,
    unit_file_state: str,
    need_daemon_reload: str,
    expected_candidates: tuple[str, ...],
) -> None:
    hold = tmp_path / "zzzz-eom-deployment-hold.conf"
    backup = tmp_path / ".zzzz-eom-deployment-hold.released"
    fragment = tmp_path / "eom-workflow-runner.service"
    events = tmp_path / "events"
    fake_systemctl = tmp_path / "systemctl"
    snapshot = tmp_path / "systemctl.snapshot"
    hold.write_bytes(HOLD_BYTES)
    fragment.write_text("[Service]\nExecStart=/bin/true\n", encoding="ascii")
    snapshot.write_text(
        _snapshot(
            UnitFileState=unit_file_state,
            FragmentPath=str(fragment),
            DropInPaths=str(hold),
            RefuseManualStart="yes",
            NeedDaemonReload=need_daemon_reload,
            InvocationID="",
            ActiveEnterTimestampMonotonic="0",
        ),
        encoding="utf-8",
    )
    fake_systemctl.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'case "$1" in\n'
        '  show) /usr/bin/cat -- "${0}.snapshot" ;;\n'
        "  is-enabled) printf '%s\\n' disabled; exit 1 ;;\n"
        "  *) exit 91 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_systemctl.chmod(0o700)

    transition = _library_function(
        "workflow_runner_release_transition_activation_identity"
    ).replace(
        "workflow_runner_release_transition_activation_identity()",
        "workflow_runner_release_transition_activation_identity_exact()",
        1,
    )
    release_fenced = _library_function(
        "workflow_runner_release_fenced_activation_identity"
    ).replace(
        "workflow_runner_release_fenced_activation_identity()",
        "workflow_runner_release_fenced_activation_identity_exact()",
        1,
    )
    harness = (
        "set -euo pipefail\n"
        'WORKFLOW_RUNNER_HOLD_TARGET="$1"\n'
        'WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP="$2"\n'
        'WORKFLOW_RUNNER_FRAGMENT="$3"\n'
        'fake_systemctl="$4"\n'
        'events="$5"\n'
        'WORKFLOW_RUNNER_HOLD_DIRECTORY="$(dirname -- "${WORKFLOW_RUNNER_HOLD_TARGET}")"\n'
        'WORKFLOW_RUNNER_HOLD_SOURCE="${WORKFLOW_RUNNER_HOLD_TARGET}"\n'
        f'WORKFLOW_RUNNER_HOLD_SHA256="sha256:{HOLD_SHA256}"\n'
        'WORKFLOW_RUNNER_INEFFECTIVE_RUNTIME_MASK="${WORKFLOW_RUNNER_HOLD_DIRECTORY}/mask"\n'
        'WORKFLOW_RUNNER_SERVICE="eom-workflow-runner.service"\n'
        "fail() { printf 'ERROR: %s\\n' \"$1\" >&2; exit 1; }\n"
        "workflow_runner_require_hold_directory() { :; }\n"
        "workflow_runner_require_hold_file() { :; }\n"
        "workflow_runner_require_source_hold_file() { :; }\n"
        "workflow_runner_require_no_ineffective_runtime_mask() { :; }\n"
        "workflow_runner_require_base_unit_file() { :; }\n"
        "workflow_runner_file_sha256() { printf '%s\\n' sha256:base; }\n"
        "workflow_runner_journal_cursor_at_or_before() { printf '%s\\n' cursor; }\n"
        "workflow_runner_deployment_hold_activation_identity() { "
        "printf '%s\\n' deployment-hold-candidate >>\"${events}\"; return 1; }\n"
        + _library_function("workflow_runner_unit_snapshot")
        + _library_function("workflow_runner_unit_disabled_on_disk")
        + release_fenced
        + transition
        + _library_function("workflow_runner_require_same_activation_identity")
        + "\nworkflow_runner_release_fenced_activation_identity() {\n"
        "  printf '%s\\n' reboot-fenced-candidate >>\"${events}\"\n"
        "  workflow_runner_release_fenced_activation_identity_exact "
        '"${fake_systemctl}" "$2"\n'
        "}\n" + "\nworkflow_runner_release_transition_activation_identity() {\n"
        "  printf '%s\\n' transition-candidate >>\"${events}\"\n"
        "  workflow_runner_release_transition_activation_identity_exact "
        '"${fake_systemctl}" "$2"\n'
        "}\n"
        "workflow_runner_released_activation_identity() { printf '%s\\n' :0; }\n"
        "workflow_runner_require_release_identity_with_journal_fence() { :; }\n"
        "sudo() {\n"
        '  [[ "$1" == -n ]]; shift\n'
        '  if [[ "$1" == /usr/bin/systemctl && "$2" == disable ]]; then\n'
        '    [[ "$3" == --no-reload && "$4" == "${WORKFLOW_RUNNER_SERVICE}" ]]\n'
        "    printf '%s\\n' disable-no-reload >>\"${events}\"\n"
        '  elif [[ "$1" == /usr/bin/systemctl && "$2" == daemon-reload ]]; then\n'
        "    printf '%s\\n' daemon-reload >>\"${events}\"\n"
        '  elif [[ "$1" == /usr/bin/mv ]]; then\n'
        "    printf '%s\\n' move-hold >>\"${events}\"\n"
        '    command "$@"\n'
        '  elif [[ "$1" == /usr/bin/rm ]]; then\n'
        "    printf '%s\\n' remove-backup >>\"${events}\"\n"
        '    command "$@"\n'
        "  else\n"
        "    return 91\n"
        "  fi\n"
        "}\n"
        + _deploy_function("release_workflow_runner_deployment_hold")
        + "\nrelease_workflow_runner_deployment_hold "
        "2026-09-08T23:28:08Z 1788910088000000"
    )

    result = subprocess.run(
        (
            "/usr/bin/bash",
            "-c",
            harness,
            "release-target-present-retry-test",
            str(hold),
            str(backup),
            str(fragment),
            str(fake_systemctl),
            str(events),
        ),
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("workflow_runner_deployment_hold=RELEASED_INACTIVE_DISABLED\n")
    assert not hold.exists()
    assert not backup.exists()
    assert events.read_text(encoding="ascii").splitlines() == [
        *expected_candidates,
        "move-hold",
        "daemon-reload",
        "remove-backup",
    ]


def test_hold_release_is_reboot_fenced_retryable_and_checks_every_mutation() -> None:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    release_start = source.index("release_workflow_runner_deployment_hold() {")
    release_end = source.index(
        "\n\nrelease_workflow_runner_deployment_hold_after_verified_receipt()", release_start
    )
    release = source[release_start:release_end]

    disable = release.index('systemctl disable --no-reload "${WORKFLOW_RUNNER_SERVICE}"')
    move = release.index(
        '"${WORKFLOW_RUNNER_HOLD_TARGET}" "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}"'
    )
    reload = release.index("systemctl daemon-reload")
    replay = release.index("REPLAYED_RELEASED_INACTIVE_DISABLED")
    cursor = release.index("workflow_runner_journal_cursor_at_or_before")
    first_journal_fence = release.index(
        "workflow_runner_require_release_identity_with_journal_fence"
    )
    cleanup = release.index('rm -- "${WORKFLOW_RUNNER_HOLD_RELEASED_BACKUP}"')
    second_journal_fence = release.index(
        "workflow_runner_require_release_identity_with_journal_fence",
        first_journal_fence + 1,
    )
    assert replay < cursor < disable < move < reload < first_journal_fence
    assert first_journal_fence < second_journal_fence < cleanup
    assert release.count("workflow_runner_require_release_identity_with_journal_fence") == 2
    assert "workflow_runner_cached_release_fenced_activation_identity" in release
    transition_pre_state = release.index(
        "workflow_runner_release_transition_activation_identity",
        release.index("workflow_runner_release_fenced_activation_identity") + 1,
    )
    transition_post_disable = release.index(
        "workflow_runner_release_transition_activation_identity",
        transition_pre_state + 1,
    )
    assert transition_pre_state < disable < transition_post_disable < move
    assert "REPLAYED_RELEASED_INACTIVE_DISABLED" in release
    assert "RELEASED_INACTIVE_DISABLED" in release
    assert "could not be disabled before hold release" in release
    assert "could not be moved to its release backup" in release
    assert "could not reload the workflow runner hold release" in release
    assert "release backup could not be removed" in release
    assert "release backup remains after removal" in release


def test_failed_receipt_gate_cannot_reach_hold_or_systemd_mutation(tmp_path: Path) -> None:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    gate_start = source.index("release_workflow_runner_deployment_hold_after_verified_receipt() {")
    gate_end = source.index("\n\nverify_mock_exam_deployment_admission()", gate_start)
    gate = source[gate_start:gate_end]
    events = tmp_path / "events"
    mutation = tmp_path / "hold-was-mutated"
    harness = (
        "set -euo pipefail\n"
        'events="$1"\n'
        'mutation_path="$2"\n'
        "verify_workflow_runner_hold_release_receipt() { "
        "printf '%s\\n' verifier >>\"${events}\"; "
        "printf '%s\\n' workflow_runner_hold_release_receipt=INVALID; "
        "read -r _ || true; return 23; }\n"
        "release_workflow_runner_deployment_hold() { "
        'printf \'%s\\n\' mutation >>"${events}"; : >"${mutation_path}"; }\n'
        + gate
        + "\n"
        + "set +e\n"
        + "release_workflow_runner_deployment_hold_after_verified_receipt\n"
        + "status=$?\n"
        + "set -e\n"
        + "((status != 0))\n"
        + '[[ "$(cat -- "${events}")" == verifier ]]\n'
        + '[[ ! -e "${mutation_path}" ]]\n'
    )

    completed = subprocess.run(
        ("/usr/bin/bash", "-c", harness, "receipt-gate", str(events), str(mutation)),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert events.read_text(encoding="ascii") == "verifier\n"
    assert not mutation.exists()


def test_successful_receipt_gate_holds_handshake_across_release(tmp_path: Path) -> None:
    source = DEPLOY_SCRIPT.read_text(encoding="utf-8")
    gate_start = source.index("release_workflow_runner_deployment_hold_after_verified_receipt() {")
    gate_end = source.index("\n\nverify_mock_exam_deployment_admission()", gate_start)
    gate = source[gate_start:gate_end]
    events = tmp_path / "events"
    harness = (
        "set -euo pipefail\n"
        'events="$1"\n'
        "verify_workflow_runner_hold_release_receipt() { "
        "printf '%s\\n' locked >>\"${events}\"; "
        "printf '%s\\n' 'workflow_runner_hold_release_receipt=VERIFIED_LOCKED "
        "retired_at=2026-09-08T12:00:00Z retired_at_unix_us=1788868800000000'; "
        'IFS= read -r signal; [[ "${signal}" == RELEASE_COMPLETE ]]; '
        "printf '%s\\n' confirmed >>\"${events}\"; "
        "printf '%s\\n' workflow_runner_hold_release_receipt=RELEASE_CONFIRMED; }\n"
        "release_workflow_runner_deployment_hold() { "
        '[[ "$1" == 2026-09-08T12:00:00Z && "$2" == 1788868800000000 ]]; '
        "printf '%s\\n' release >>\"${events}\"; return 0; }\n"
        + gate
        + "\n"
        + "release_workflow_runner_deployment_hold_after_verified_receipt\n"
        + '[[ "$(cat -- "${events}")" == $\'locked\\nrelease\\nconfirmed\' ]]\n'
    )

    completed = subprocess.run(
        ("/usr/bin/bash", "-c", harness, "receipt-gate", str(events)),
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert events.read_text(encoding="ascii") == "locked\nrelease\nconfirmed\n"


@pytest.mark.privileged
def test_real_user_systemd_local_unit_hold_blocks_manual_dependency_and_restart_then_releases(
    tmp_path: Path,
) -> None:
    if os.environ.get("EOM_RUN_SYSTEMD_HOLD_TEST") != "1":
        pytest.skip("set EOM_RUN_SYSTEMD_HOLD_TEST=1 for isolated real-systemd behavior")
    manager = subprocess.run(
        ("/usr/bin/systemctl", "--user", "is-system-running"),
        check=False,
        capture_output=True,
        text=True,
    )
    if manager.returncode != 0:
        pytest.skip("a running per-user systemd manager is required")

    suffix = uuid.uuid4().hex
    unit_name = f"eom-deployment-hold-test-{suffix}.service"
    target_name = f"eom-deployment-hold-test-{suffix}.target"
    persistent_root = Path.home() / ".config/systemd/user"
    runtime_root = Path(os.environ["XDG_RUNTIME_DIR"]) / "systemd/user"
    unit = persistent_root / unit_name
    target = persistent_root / target_name
    drop_in_directory = persistent_root / f"{unit_name}.d"
    hold = drop_in_directory / "zzzz-eom-deployment-hold.conf"
    backup = drop_in_directory / ".zzzz-eom-deployment-hold.released"
    runtime_mask = runtime_root / unit_name
    enable_link = persistent_root / "default.target.wants" / unit_name
    invoked = tmp_path / "exec-start-was-invoked"

    def systemctl(*arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ("/usr/bin/systemctl", "--user", *arguments),
            check=False,
            capture_output=True,
            text=True,
        )

    def show(property_name: str) -> str:
        observed = systemctl("show", unit_name, f"--property={property_name}", "--value")
        assert observed.returncode == 0, observed.stderr
        return observed.stdout.rstrip("\n")

    persistent_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    drop_in_directory.mkdir(mode=0o755)
    unit.write_text(
        "[Unit]\nDescription=Disposable local-unit hold behavior test\n"
        "[Service]\nType=oneshot\n"
        f"ExecStart=/usr/bin/touch {invoked}\nRemainAfterExit=yes\n"
        "[Install]\nWantedBy=default.target\n",
        encoding="ascii",
    )
    runtime_mask.symlink_to("/dev/null")
    try:
        reloaded = systemctl("daemon-reload")
        assert reloaded.returncode == 0, reloaded.stderr
        enabled = systemctl("enable", unit_name)
        assert enabled.returncode == 0, enabled.stderr
        # Reproduces the original bug: a lower-priority runtime mask does not hide a local unit.
        assert show("FragmentPath") == str(unit)
        assert show("LoadState") == "loaded"
        runtime_mask.unlink()

        started = systemctl("start", unit_name)
        assert started.returncode == 0, started.stderr
        stopped = systemctl("stop", unit_name)
        assert stopped.returncode == 0, stopped.stderr
        assert invoked.is_file()
        invoked.unlink()
        invocation_before = show("InvocationID")
        entered_before = show("ActiveEnterTimestampMonotonic")
        assert invocation_before

        disabled_for_hold = systemctl("disable", "--no-reload", unit_name)
        assert disabled_for_hold.returncode == 0, disabled_for_hold.stderr
        assert not enable_link.exists()
        assert show("InvocationID") == invocation_before
        assert show("ActiveEnterTimestampMonotonic") == entered_before

        hold.write_bytes(b"[Unit]\nRefuseManualStart=yes\nConditionPathExists=!/\n")
        hold.chmod(0o644)
        enabled_under_hold = systemctl("enable", "--no-reload", unit_name)
        assert enabled_under_hold.returncode == 0, enabled_under_hold.stderr
        assert enable_link.is_symlink()
        assert show("InvocationID") == invocation_before
        assert show("ActiveEnterTimestampMonotonic") == entered_before
        reloaded = systemctl("daemon-reload")
        assert reloaded.returncode == 0, reloaded.stderr
        assert show("DropInPaths") == str(hold)
        assert show("RefuseManualStart") == "yes"
        assert show("NeedDaemonReload") == "no"
        assert show("ActiveState") == "inactive"
        assert show("SubState") == "dead"
        assert show("MainPID") == "0"
        assert show("Job") == ""
        assert show("InvocationID") == invocation_before
        assert show("ActiveEnterTimestampMonotonic") == entered_before

        target.write_text(f"[Unit]\nWants={unit_name}\nAfter={unit_name}\n", encoding="ascii")
        dependency_reloaded = systemctl("daemon-reload")
        assert dependency_reloaded.returncode == 0, dependency_reloaded.stderr
        assert show("InvocationID") == invocation_before
        manual = systemctl("start", unit_name)
        assert manual.returncode != 0
        assert not invoked.exists()
        indirect = systemctl("start", target_name)
        assert indirect.returncode == 0, indirect.stderr
        assert show("ActiveState") == "inactive"
        assert not invoked.exists()
        restarted = systemctl("restart", unit_name)
        assert restarted.returncode != 0
        assert not invoked.exists()
        assert show("InvocationID") == invocation_before
        assert show("ActiveEnterTimestampMonotonic") == entered_before
        assert show("Job") == ""

        target.unlink()
        reloaded_without_test_dependency = systemctl("daemon-reload")
        assert reloaded_without_test_dependency.returncode == 0
        assert show("InvocationID") == invocation_before
        retired_at_value = datetime.now(UTC)
        retired_at = retired_at_value.isoformat().replace("+00:00", "Z")
        retired_delta = retired_at_value - datetime(1970, 1, 1, tzinfo=UTC)
        retired_at_unix_us = str(
            (retired_delta.days * 86_400 + retired_delta.seconds) * 1_000_000
            + retired_delta.microseconds
        )
        journal_cursor = _run(
            "workflow_runner_journal_cursor_at_or_before",
            "/usr/bin/journalctl",
            "--user",
            retired_at,
            retired_at_unix_us,
        )
        assert journal_cursor.returncode == 0, journal_cursor.stderr
        assert (
            _run(
                "workflow_runner_require_journal_cursor_retained",
                "/usr/bin/journalctl",
                "--user",
                JOURNAL_CURSOR,
            ).returncode
            != 0
        )

        disabled = systemctl("disable", "--no-reload", unit_name)
        assert disabled.returncode == 0, disabled.stderr
        assert not enable_link.exists()
        assert show("InvocationID") == invocation_before
        assert show("ActiveEnterTimestampMonotonic") == entered_before
        hold.replace(backup)
        # A process interruption after the atomic rename but before daemon-reload remains held by
        # the manager's loaded configuration and is resumable from the exact backup.
        interrupted_release_start = systemctl("start", unit_name)
        assert interrupted_release_start.returncode != 0
        assert not invoked.exists()
        reloaded = systemctl("daemon-reload")
        assert reloaded.returncode == 0, reloaded.stderr
        assert show("DropInPaths") == ""
        assert show("RefuseManualStart") == "no"
        assert show("ActiveState") == "inactive"
        assert show("Job") == ""
        released_identity = f"{show('InvocationID')}:{show('ActiveEnterTimestampMonotonic')}"
        assert released_identity == ":0"
        assert (
            _run(
                "workflow_runner_require_release_identity_with_journal_fence",
                f"{invocation_before}:{entered_before}",
                released_identity,
                "/usr/bin/journalctl",
                "--user",
                unit_name,
                journal_cursor.stdout.strip(),
            ).returncode
            == 0
        )
        backup.unlink()
        assert show("NeedDaemonReload") == "no"
        assert (
            _run(
                "workflow_runner_require_release_identity_with_journal_fence",
                released_identity,
                f"{show('InvocationID')}:{show('ActiveEnterTimestampMonotonic')}",
                "/usr/bin/journalctl",
                "--user",
                unit_name,
                journal_cursor.stdout.strip(),
            ).returncode
            == 0
        )

        released_start = systemctl("enable", "--now", unit_name)
        assert released_start.returncode == 0, released_start.stderr
        assert invoked.is_file()
    finally:
        systemctl("stop", target_name, unit_name)
        systemctl("disable", unit_name)
        systemctl("reset-failed", target_name, unit_name)
        for path in (runtime_mask, hold, backup, target, unit):
            if path.is_symlink() or path.exists():
                path.unlink()
        if drop_in_directory.exists():
            drop_in_directory.rmdir()
        systemctl("daemon-reload")
