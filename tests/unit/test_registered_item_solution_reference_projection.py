"""Accepted V1 identity compatibility; synthetic local artifacts, no DB/model/systemd."""

from copy import deepcopy

import pytest
from eom_catalog_contracts import (
    KnowledgeAnalysisProposalReceipt,
    KnowledgeAnalysisRequestV11,
    KnowledgeAnalysisResultV2,
    KnowledgeAnalysisWorkerProposal,
)
from eom_catalog_contracts.knowledge import knowledge_proposal_member_set_sha256
from eom_catalog_service.registered_item_solution_base import (
    RegisteredItemSolutionReferenceError,
    registered_item_solution_reference_index,
    resolve_registered_item_solution_base,
)
from eom_identifiers import canonical_json_bytes, content_sha256, sha256_bytes

from tests.unit.test_registered_item_solution_analysis_candidate_schemas import request_value
from tests.unit.test_registered_item_solution_application import accepted_chain, source_fixture


def proposal_nodes():
    nodes = []
    for kind, count in (
        ("ITEM_ELEMENT", 7),
        ("CONCEPT", 1),
        ("FORMULA", 3),
        ("PROCESS", 2),
        ("ASSESSMENT_PATTERN", 4),
        ("OBSERVABLE_PROPERTY", 2),
    ):
        for index in range(count):
            nodes.append(
                dict(
                    node_id=f"knode_{kind.lower()}_{index}"
                    if kind != "OBSERVABLE_PROPERTY"
                    else f"knode_opaque_property_{index}",
                    node_type=kind,
                    stable_key=f"test.{kind.lower()}.{index}",
                    label=kind,
                    anchor_ids=["anchor_problem"],
                )
            )
    return nodes


def test_accepted_v1_projection_retains_all_anchors_and_original_ids_with_explicit_warning(caplog):
    request, document, source = source_fixture("1.0")
    document["nodes"] = proposal_nodes()
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(document)
    before = proposal.model_dump(mode="json")

    projected = registered_item_solution_reference_index(request, proposal, source)

    assert len(projected.nodes) == 17
    assert {node.node_id for node in projected.nodes} == {
        node.node_id for node in proposal.nodes if node.node_type != "OBSERVABLE_PROPERTY"
    }
    assert projected.anchor_ids == ("anchor_answer", "anchor_problem")
    assert projected.problem_anchor_ids == ("anchor_problem",)
    assert projected.answer_explanation_anchor_ids == ("anchor_answer",)
    assert proposal.model_dump(mode="json") == before
    assert caplog.messages == [
        "REGISTERED_ITEM_SOLUTION_REFERENCE_SUBSET excluded_count=2 "
        "excluded_types=OBSERVABLE_PROPERTY:2"
    ]
    assert all(node.node_id not in caplog.text for node in proposal.nodes)
    again = registered_item_solution_reference_index(request, proposal, source)
    assert again == projected


@pytest.mark.parametrize("suffix_length", (32, 33))
def test_projection_uses_existing_released_schema_id_length_not_only_pydantic_prefix(
    suffix_length, caplog
):
    request, document, source = source_fixture()
    extra = proposal_nodes()[-1] | {"node_id": "knode_observable_property_" + "a" * suffix_length}
    document["nodes"].append(extra)
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(document)

    result = registered_item_solution_reference_index(request, proposal, source)

    assert (extra["node_id"] in {node.node_id for node in result.nodes}) == (suffix_length == 32)
    assert bool(caplog.messages) == (suffix_length == 33)


@pytest.mark.parametrize("missing", ("all", "item", "conceptual"))
def test_projection_rejects_base_without_report_required_roles_before_worker(missing):
    request, document, source = source_fixture()
    document["nodes"] = [
        node
        for node in proposal_nodes()
        if (missing != "all" or node["node_type"] == "OBSERVABLE_PROPERTY")
        and (missing != "item" or node["node_type"] != "ITEM_ELEMENT")
        and (missing != "conceptual" or node["node_type"] not in {"CONCEPT", "PROCESS", "FORMULA"})
    ]
    proposal = KnowledgeAnalysisWorkerProposal.model_validate(document)
    with pytest.raises(
        RegisteredItemSolutionReferenceError,
        match=r"^REGISTERED_ITEM_SOLUTION_REFERENCE_ROLES_UNAVAILABLE$",
    ):
        registered_item_solution_reference_index(request, proposal, source)


@pytest.mark.parametrize("fault", ("hash", "member", "revision", "source"))
def test_compatibility_projection_never_hides_source_or_anchor_failures(fault, caplog):
    request, document, source = source_fixture("1.0")
    document["nodes"] = proposal_nodes()
    if fault == "hash":
        document["anchors"][0]["excerpt_sha256"] = "sha256:" + "0" * 64
    elif fault == "member":
        document["anchors"][0]["member_path"] = "different.json"
    elif fault == "revision":
        document["anchors"][0]["artifact_revision_id"] = "rev_" + "0" * 32
    else:
        source["schema_version"] = "999.0"
    with pytest.raises(ValueError):
        registered_item_solution_reference_index(
            request, KnowledgeAnalysisWorkerProposal.model_validate(document), source
        )
    assert caplog.messages == []


def accepted_chain_with_opaque_nodes(tmp_path):
    """Use a real hashed local receipt/member chain, not model_copy to bypass pins."""
    fixture = accepted_chain(tmp_path, canonical_receipt=True)
    receipt_document = fixture.receipt.model_dump(mode="json")
    node_member = receipt_document["members"]["nodes"]
    nodes_raw = b"".join(canonical_json_bytes(node) + b"\n" for node in proposal_nodes())
    nodes_path = (
        fixture.fixture.root
        / node_member["artifact_id"]
        / node_member["artifact_revision_id"]
        / node_member["member_path"]
    )
    nodes_path.write_bytes(nodes_raw)
    node_member.update(bytes=len(nodes_raw), sha256=sha256_bytes(nodes_raw))
    receipt_document["counts"]["nodes"] = 19
    receipt_document["content_set_sha256"] = knowledge_proposal_member_set_sha256(
        tuple(
            type(fixture.receipt.members.nodes).model_validate(value)
            for value in receipt_document["members"].values()
        )
    )
    fixture.receipt = KnowledgeAnalysisProposalReceipt.model_validate(receipt_document)
    receipt_raw = canonical_json_bytes(fixture.receipt)
    receipt_pointer = fixture.receipt_pointer.model_dump(mode="json")
    receipt_pointer.update(bytes=len(receipt_raw), sha256=sha256_bytes(receipt_raw))
    fixture.receipt_pointer = type(fixture.receipt_pointer).model_validate(receipt_pointer)
    receipt_path = (
        fixture.fixture.root
        / receipt_pointer["artifact_id"]
        / receipt_pointer["artifact_revision_id"]
        / receipt_pointer["member_path"]
    )
    receipt_path.write_bytes(receipt_raw)
    accepted = deepcopy(fixture.revision.result)
    accepted.update(
        counts=receipt_document["counts"],
        proposal_receipt=receipt_pointer,
        proposal_content_set_sha256=fixture.receipt.content_set_sha256,
    )
    accepted["result_sha256"] = content_sha256(
        {k: v for k, v in accepted.items() if k != "result_sha256"}
    )
    accepted = KnowledgeAnalysisResultV2.model_validate(accepted).model_dump(mode="json")
    accepted_raw = canonical_json_bytes(accepted)
    accepted_path = (
        fixture.fixture.root
        / fixture.run.accepted_result_artifact_id
        / fixture.run.accepted_result_artifact_revision_id
        / "evidence/accepted-result.json"
    )
    accepted_path.write_bytes(accepted_raw)
    fixture.revision.result = accepted
    fixture.revision.content_hash = sha256_bytes(accepted_raw)
    fixture.revision.content_bytes = len(accepted_raw)
    fixture.run.accepted_result_sha256 = sha256_bytes(accepted_raw)
    return fixture, nodes_path, nodes_raw


def test_full_registered_base_keeps_all_accepted_members_and_counts_while_projecting_only_17(
    tmp_path,
):
    fixture, nodes_path, nodes_raw = accepted_chain_with_opaque_nodes(tmp_path)
    before_receipt = fixture.receipt.model_dump(mode="json")
    before_revision = deepcopy(fixture.revision.result)

    base = resolve_registered_item_solution_base(
        fixture.fixture.session,
        fixture.reader,
        run=fixture.run,
        request=fixture.request,
        receipt=fixture.receipt,
        receipt_pointer=fixture.receipt_pointer,
    )

    assert len(base.reference_index.nodes) == 17 and base.base_counts.nodes == 19
    assert base.base_members == fixture.receipt.members
    assert nodes_path.read_bytes() == nodes_raw
    assert fixture.receipt.model_dump(mode="json") == before_receipt
    assert fixture.revision.result == before_revision
    value = request_value()
    value.update(
        source=fixture.request.source.model_dump(mode="json"),
        base_analysis=base.model_dump(mode="json"),
    )
    value["request_sha256"] = content_sha256(
        {k: v for k, v in value.items() if k != "request_sha256"}
    )
    assert KnowledgeAnalysisRequestV11.model_validate(value).base_analysis == base
