"""All three Item categories use the same actual encoder input, not raw report layout."""

from eom_catalog_contracts.knowledge import KnowledgeAnalysisSolutionReport
from eom_catalog_contracts.public_solution_embedding import PublicSolutionEmbeddingEntry
from eom_catalog_service.public_solution_encoding import prepare_public_solution_encoding
from eom_catalog_service.solution_embedding_projection import project_public_solution_text
from eom_identifiers import canonical_json_bytes, content_sha256

from tests.unit.inference_transfer_embedding_fixtures import embedding_space
from tests.unit.inference_transfer_fixtures import report
from tests.unit.test_public_solution_encoding import public_entry
from tests.unit.test_solution_embedding_projection import source_report


def test_past_creative_and_ai_share_complete_scientific_text_and_cuda_document_encoding():
    past = report("속도는 -36 km/h이다.", "합력은 0 N이 아니다.")
    parts = tuple(value for step in past.solution_steps for value in (step.rationale, step.outcome))
    creative = source_report(("\r\n\t".join(parts),), successor=True)
    ai_value = past.model_dump(mode="json") | {
        "analysis_request_id": "knowledgeanalysis_" + "e" * 32,
        "base_analysis_result_id": "knowledgeanalysisresult_" + "d" * 32,
        "assessment_design_summary": "AI 출제 계보에 별도로 보존되는 설명",
    }
    ai = KnowledgeAnalysisSolutionReport.model_validate(ai_value)
    originals = tuple(canonical_json_bytes(value) for value in (past, creative, ai))
    texts = tuple(project_public_solution_text(value) for value in (past, creative, ai))
    assert texts[0] == texts[1] == texts[2]
    past_entry = public_entry(text=texts[0].text)
    creative_entry = public_entry(creative=True, text=texts[1].text)
    ai_body = past_entry.model_dump(mode="json")
    ai_body["source"]["source_class"] = "APPROVED_ITEM"
    ai_body["source"]["item_id"] = "item_" + "f" * 32
    ai_body["source"]["item_revision_id"] = "itemrev_" + "f" * 32
    ai_body["entry_sha256"] = content_sha256(
        {key: value for key, value in ai_body.items() if key != "entry_sha256"}
    )
    ai_entry = PublicSolutionEmbeddingEntry.model_validate(ai_body)
    cuda = embedding_space(device="CUDA", purpose="DOCUMENT")
    encodings = tuple(
        prepare_public_solution_encoding(entry, space=cuda, storage_partition="public-solution")
        for entry in (past_entry, creative_entry, ai_entry)
    )
    assert encodings[0].input == encodings[1].input == encodings[2].input
    assert len({value.source.entry_sha256 for value in encodings}) == 3
    assert originals == tuple(canonical_json_bytes(value) for value in (past, creative, ai))
    assert "-36 km/h" in encodings[0].input.text
    assert "0 N이 아니다." in encodings[0].input.text
    # This is a deterministic input/provenance test, not a GPU-forward quality claim.
