from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from eom_image_contracts import ImageEvaluationArtifactMember

from scripts.image_trainer import stage_science_visual_pilot as stage


def _pointer() -> ImageEvaluationArtifactMember:
    return ImageEvaluationArtifactMember(
        artifact_id="artifact_" + "1" * 32,
        artifact_revision_id="rev_" + "2" * 32,
        member_path="manifests/visual-pilot-plan.json",
        schema_ref=(
            "eom://schemas/image-provider/local-image-science-corpus-visual-pilot-plan/1.0"
        ),
        media_type="application/json",
        sha256="sha256:" + "3" * 64,
    )


def test_command_binds_every_staged_pdf_to_the_published_plan() -> None:
    sources = tuple(
        SimpleNamespace(
            document_id="sciencedoc_" + f"{index + 1:032x}",
            pdf=SimpleNamespace(sha256="sha256:" + f"{index + 1:064x}"),
            bytes=2048 + index,
            page_count=index % 3 + 1,
        )
        for index in range(12)
    )
    plan = SimpleNamespace(plan_sha256="sha256:" + "4" * 64, selected_sources=sources)

    command = stage._build_command(  # type: ignore[arg-type]
        plan=plan,
        plan_pointer=_pointer(),
        requested_at=datetime(2026, 9, 25, 20, 0, tzinfo=UTC),
        requested_by="operator_user",
    )

    assert command.plan_sha256 == plan.plan_sha256
    assert len(command.staged_sources) == 12
    assert tuple(value.document_id for value in command.staged_sources) == tuple(
        value.document_id for value in sources
    )
    assert all(
        value.staged_pdf_member == f"input/pdfs/{value.document_id}.pdf"
        for value in command.staged_sources
    )


def test_preflight_validates_population_without_publication_or_workspace(
    monkeypatch,
    capsys,
) -> None:
    source = SimpleNamespace(
        pdf=_pointer(),
        bytes=2048,
        page_count=3,
    )
    monkeypatch.setattr(
        stage,
        "_parser",
        lambda: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(
                corpus_artifact_id="artifact_" + "1" * 32,
                corpus_artifact_revision_id="rev_" + "2" * 32,
                corpus_artifact_sha256="sha256:" + "3" * 64,
                approved_at=datetime(2026, 9, 25, 20, 0, tzinfo=UTC),
                approved_by="owner_explicit_chat",
                created_at=datetime(2026, 9, 25, 20, 5, tzinfo=UTC),
                created_by="operator_user",
                source_commit="a" * 40,
                selection_seed_sha256="sha256:" + "5" * 64,
                source_limit=12,
                page_limit=48,
                candidate_limit=24,
                lora_crop_limit=12,
                preflight_only=True,
            )
        ),
    )
    monkeypatch.setattr(stage, "_require_release", lambda _commit: None)
    monkeypatch.setattr(stage, "build_engine", lambda: object())
    monkeypatch.setattr(
        stage, "_load_corpus", lambda _engine, _pointer: SimpleNamespace(documents=())
    )
    monkeypatch.setattr(
        stage,
        "select_science_visual_pilot_sources",
        lambda *_args, **_kwargs: tuple(source for _index in range(12)),
    )
    monkeypatch.setattr(
        stage,
        "_load_artifact_member",
        lambda *_args, **_kwargs: b"x" * 2048,
    )
    monkeypatch.setattr(stage, "_guidance", lambda _commit: ())
    monkeypatch.setattr(stage, "_tool", lambda *_args: object())
    monkeypatch.setattr(stage, "ScienceVisualToolSet", lambda **_kwargs: object())

    assert stage.main() == 0
    assert '"preflight": "PASS"' in capsys.readouterr().out
