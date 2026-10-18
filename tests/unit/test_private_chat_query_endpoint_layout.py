"""Production endpoint selection only; no actual account/OS deployment authorization."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts.private_chat_query_prepare import PRIVATE_CHAT_PREPARE_SOCKET
from eom_catalog_contracts.reference_query_prepare import REFERENCE_QUERY_PREPARE_SOCKET
from eom_orchestrator import private_chat_query_prepare_client as module
from eom_orchestrator.general_chat_socket import ChatTransportError


def test_private_prepare_default_has_a_distinct_group_parent():
    private = Path(PRIVATE_CHAT_PREPARE_SOCKET)
    reference = Path(REFERENCE_QUERY_PREPARE_SOCKET)
    assert private == Path("/run/eom-private-chat-query-owner/prepare.sock")
    assert private.parent != reference.parent


def test_installed_client_uses_fixed_owner_and_chat_group_without_group_membership(monkeypatch):
    owners, groups = [], []

    def owner(name):
        owners.append(name)
        return SimpleNamespace(pw_uid=1234)

    def group(name):
        groups.append(name)
        return SimpleNamespace(gr_gid=5678)

    monkeypatch.setattr(module.pwd, "getpwnam", owner)
    monkeypatch.setattr(module.grp, "getgrnam", group)
    client = module.PrivateChatQueryPrepareClient.for_installed_owner()
    assert owners == ["eom-workflow-runner"] and groups == ["eom-general-chat"]
    assert client.endpoint.path == Path(PRIVATE_CHAT_PREPARE_SOCKET)
    assert client.endpoint.owner_uid == 1234 and client.endpoint.group_gid == 5678
    assert client.endpoint.parent_mode == 0o2750


def test_private_tmpfiles_selection_matches_the_client_and_does_not_change_api_layout():
    root = Path(__file__).resolve().parents[2]
    private = root / "infra/tmpfiles/eom-private-chat-query-owner.conf"
    assert private.read_text().splitlines() == [
        "# Optional private QUERY parent; install only with compatible private owner activation.",
        "d /run/eom-private-chat-query-owner 2750 eom-workflow-runner eom-general-chat - -",
    ]
    reference = (root / "infra/tmpfiles/eom-reference-query-owner.conf").read_text()
    assert "d /run/eom-reference-query-owner 2750 eom-workflow-runner eom-api - -" in reference


@pytest.mark.parametrize("fault", ("owner_missing", "group_missing", "root_owner", "root_group"))
def test_installed_client_rejects_missing_or_root_identity_without_exchange(monkeypatch, fault):
    def owner(_name):
        if fault == "owner_missing":
            raise KeyError("not a configured account")
        return SimpleNamespace(pw_uid=0 if fault == "root_owner" else 1234)

    def group(_name):
        if fault == "group_missing":
            raise KeyError("not a configured group")
        return SimpleNamespace(gr_gid=0 if fault == "root_group" else 5678)

    monkeypatch.setattr(module.pwd, "getpwnam", owner)
    monkeypatch.setattr(module.grp, "getgrnam", group)
    with pytest.raises(ChatTransportError) as caught:
        module.PrivateChatQueryPrepareClient.for_installed_owner()
    assert caught.value.kind == ("UNAVAILABLE" if fault.endswith("missing") else "INVALID")
