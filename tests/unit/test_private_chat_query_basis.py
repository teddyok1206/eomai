"""Private query input is one immutable question, not an approved Item or a grant."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from eom_catalog_contracts import (
    PrivateChatQueryBasis,
    build_private_chat_query_basis,
    private_chat_query_text_sha256,
)
from eom_catalog_contracts.validation import CATALOG_SCHEMA_RESOURCES, load_schema
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes
from eom_orchestrator.general_chat_similarity_basis import (
    PreparedPrivateChatQuery,
    read_owned_private_chat_query,
)
from eom_orchestrator.general_chat_state import ChatError
from eom_protocol.artifact_members import ArtifactMemberPointer
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError as SchemaError

CONVERSATION = "chat_" + "1" * 32
TURN = "chatturn_" + "2" * 32
ACTOR = "operator_" + "3" * 32
TEXT = "  2 m/s와 3 m/s는 같지 않다.\n이 조건을 쓰는 문항을 찾아줘.  "


def payload(*, grounded=False, **updates):
    document = {
        "schema_version": "general-chat-message/2.0" if grounded else "general-chat-message/1.0",
        "conversation_id": CONVERSATION,
        "turn_id": TURN,
        "role": "user",
        "text": TEXT,
    }
    if grounded:
        document["selection"] = None
    return canonical_json_bytes(document | updates)


def pointer(raw=None, *, grounded=False):
    return ArtifactMemberPointer(
        artifact_id="artifact_" + "4" * 32,
        artifact_revision_id="rev_" + "5" * 32,
        member_path="chat/evidence.json",
        schema_ref=f"eom://schemas/general-chat/message/{'2.0' if grounded else '1.0'}",
        media_type="application/json",
        sha256=sha256_bytes(payload(grounded=grounded) if raw is None else raw),
    )


def basis():
    return build_private_chat_query_basis(
        conversation_id=CONVERSATION, turn_id=TURN, message=pointer(), text=TEXT
    )


def reseal(document):
    document = {key: value for key, value in document.items() if key != "basis_sha256"}
    return document | {"basis_sha256": content_sha256(document)}


def test_schema_resource_is_independently_pinned_and_mirrored():
    resource = CATALOG_SCHEMA_RESOURCES["system-rag-private-chat-query-basis"]
    root = Path(__file__).resolve().parents[2]
    raw = (root / resource.canonical_path).read_bytes()
    assert (
        raw
        == (
            root / "packages/catalog_contracts/eom_catalog_contracts" / resource.resource_path
        ).read_bytes()
    )
    assert (
        sha256_bytes(raw)
        == resource.sha256
        == ("sha256:589521cd1ed918569c41f149eb224376172c493a97b00b256c39cbfa5367b145")
    )
    Draft202012Validator.check_schema(load_schema("system-rag-private-chat-query-basis"))


def test_basis_roundtrip_has_only_pointers_hashes_and_no_private_text_or_authority():
    value = basis()
    assert PrivateChatQueryBasis.model_validate(value) == value
    assert PrivateChatQueryBasis.model_validate_json(canonical_json_bytes(value)) == value
    assert value.query_text_sha256 == sha256_bytes(TEXT.encode())
    assert TEXT not in canonical_json_bytes(value).decode()
    assert not {"actor_id", "role", "profile", "solution_evidence", "text", "path"} & set(
        value.model_dump()
    )
    assert value == basis()


@pytest.mark.parametrize("text", ["", "   \n", "a\x00b", "x" * 16001, True, 3, None, "\ud800"])
def test_exact_recipe_rejects_invalid_input_without_truncation(text):
    with pytest.raises((ValueError, UnicodeError)):
        private_chat_query_text_sha256(text)


def test_exact_recipe_does_not_erase_spaces_negation_numbers_or_unicode_distinctions():
    texts = (
        TEXT,
        TEXT.strip(),
        TEXT.replace("않다", "맞다"),
        TEXT.replace("2 m/s", "4 m/s"),
        "é",
        "e\u0301",
    )
    assert len({private_chat_query_text_sha256(text) for text in texts}) == len(texts)
    assert private_chat_query_text_sha256("가" * 16000) == sha256_bytes(("가" * 16000).encode())


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", "system-rag-private-chat-query-basis/9.0"),
        ("basis", "APPROVED_REFERENCE_ITEM"),
        ("consumer_purpose", "ITEM_AUTHORING"),
        ("query_recipe", "strip-and-summarize/1.0"),
        ("conversation_id", "chat_latest"),
        ("turn_id", True),
        ("query_text_sha256", 123),
        ("actor_id", ACTOR),
        ("profile", {}),
        ("text", TEXT),
        ("authority", "ADMIN"),
    ],
)
def test_closed_contract_rejects_unoffered_values_even_with_a_new_hash(field, value):
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatQueryBasis.model_validate(
            reseal(basis().model_dump(mode="json") | {field: value})
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("member_path", "../secret"),
        ("media_type", "text/plain"),
        ("schema_ref", "eom://schemas/general-chat/turn-result/1.0"),
        ("artifact_revision_id", "latest"),
        ("sha256", "0" * 64),
    ],
)
def test_nested_pointer_is_strict_before_pydantic_coercion(field, value):
    document = basis().model_dump(mode="json")
    document["message"][field] = value
    with pytest.raises((ValueError, SchemaError)):
        PrivateChatQueryBasis.model_validate(reseal(document))


def test_copied_constructed_missing_extra_and_unhashed_changes_are_rejected():
    value = basis()
    invalid = (
        value.model_copy(update={"authority": "ADMIN"}),
        value.model_copy(update={"turn_id": "chatturn_" + "6" * 32}),
        value.model_copy(update={"message": value.message.model_copy(update={"actor_id": ACTOR})}),
        PrivateChatQueryBasis.model_construct(
            **{k: v for k, v in value.__dict__.items() if k != "basis"}
        ),
    )
    for document in invalid:
        with pytest.raises((ValueError, SchemaError)):
            PrivateChatQueryBasis.model_validate(document)
    with pytest.raises(ValueError):
        PreparedPrivateChatQuery(value, TEXT + "changed")


class Repository:
    """Synthetic authority only; actual DB authorization belongs to opt-in tests."""

    def __init__(self, member):
        self.snapshots = 0
        self.active = True
        self.owner = ACTOR
        self.conversation = CONVERSATION
        self.turn_value = SimpleNamespace(
            conversation_id=CONVERSATION,
            input_artifact_id=member.artifact_id,
            input_revision_id=member.artifact_revision_id,
            input_sha256=member.sha256,
        )

    @contextmanager
    def read_snapshot(self):
        self.snapshots += 1
        yield object()

    def require_actor(self, session, actor_id):
        if not self.active or actor_id != ACTOR:
            raise ChatError("GENERAL_CHAT_FORBIDDEN")

    def owned(self, session, actor_id, conversation_id):
        if actor_id != self.owner or conversation_id != self.conversation:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")

    def turn(self, session, turn_id):
        if turn_id != TURN:
            raise ChatError("GENERAL_CHAT_NOT_FOUND")
        return self.turn_value


class Evidence:
    def __init__(self, member, raw):
        self.member, self.raw = member, raw
        self.reads = []
        self.resolutions = []
        self.after_read = lambda: None

    def resolve_family(self, pointers):
        self.resolutions.append(pointers)
        return (self.member,)

    def read(self, pointers):
        self.reads.append(pointers)
        self.after_read()
        return (self.raw,)


def resolve(repository, evidence, **updates):
    return read_owned_private_chat_query(
        repository,
        evidence,
        **{
            "actor_id": ACTOR,
            "conversation_id": CONVERSATION,
            "turn_id": TURN,
        }
        | updates,
    )


@pytest.mark.parametrize("grounded", [False, True])
def test_owner_reads_only_one_message_then_rechecks_in_a_fresh_snapshot(grounded):
    raw, member = payload(grounded=grounded), pointer(grounded=grounded)
    repository, evidence = Repository(member), Evidence(member, raw)
    first, second = resolve(repository, evidence), resolve(repository, evidence)
    assert first == second and first.text == TEXT
    assert first.basis.message == member and repository.snapshots == 4
    assert evidence.reads == [(member,), (member,)]
    assert len(evidence.resolutions) == 2


@pytest.mark.parametrize("fault", ["inactive", "other_owner", "foreign_turn", "missing_turn"])
def test_denial_happens_before_any_artifact_read(fault):
    repository, evidence = Repository(pointer()), Evidence(pointer(), payload())
    updates = {}
    if fault == "inactive":
        repository.active = False
    elif fault == "other_owner":
        repository.owner = "operator_" + "9" * 32
    elif fault == "foreign_turn":
        repository.turn_value.conversation_id = "chat_" + "9" * 32
    else:
        updates["turn_id"] = "chatturn_" + "9" * 32
    with pytest.raises(ChatError):
        resolve(repository, evidence, **updates)
    assert evidence.reads == evidence.resolutions == []


@pytest.mark.parametrize("fault", ["inactive", "ownership", "pointer"])
def test_revocation_or_pointer_change_after_materialization_cannot_return_a_basis(fault):
    repository, evidence = Repository(pointer()), Evidence(pointer(), payload())

    def change():
        if fault == "inactive":
            repository.active = False
        elif fault == "ownership":
            repository.owner = "operator_" + "9" * 32
        else:
            repository.turn_value.input_sha256 = "sha256:" + "9" * 64

    evidence.after_read = change
    with pytest.raises(ChatError):
        resolve(repository, evidence)
    assert repository.snapshots == 2 and evidence.reads == [(pointer(),)]


@pytest.mark.parametrize(
    "fault",
    ["hash", "role", "conversation", "turn", "noncanonical", "schema", "substitute", "oversize"],
)
def test_untrusted_member_faults_fail_without_returning_private_text(fault):
    member, raw = pointer(), payload()
    if fault == "hash":
        raw = payload(text="changed")
    elif fault in {"role", "conversation", "turn"}:
        updates = (
            {"role": "assistant"}
            if fault == "role"
            else {f"{fault}_id": ("chat_" if fault == "conversation" else "chatturn_") + "9" * 32}
        )
        raw = payload(**updates)
        member = pointer(raw)
    elif fault == "noncanonical":
        raw = payload() + b"\n"
        member = pointer(raw)
    elif fault == "oversize":
        raw = b" " * 256001
        member = pointer(raw)
    repository, evidence = Repository(member), Evidence(member, raw)
    if fault == "schema":
        evidence.member = member.model_copy(
            update={"schema_ref": "eom://schemas/general-chat/message/2.0"}
        )
    elif fault == "substitute":
        evidence.member = member.model_copy(update={"artifact_revision_id": "rev_" + "9" * 32})
    with pytest.raises(ChatError, match=r"^GENERAL_CHAT_POINTER_INVALID$") as failure:
        resolve(repository, evidence)
    assert TEXT not in str(failure.value)
