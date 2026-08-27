from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "apps/web_gui/eom_web_gui/static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
JAVASCRIPT = (STATIC / "app.js").read_text(encoding="utf-8")
DESIGN_NOTE = ROOT / "docs/product/EOM_SCIENTIFIC_WORKBENCH_DESIGN_SYSTEM.md"


def test_scientific_workbench_decision_is_documented_as_presentation_only() -> None:
    text = DESIGN_NOTE.read_text(encoding="utf-8")
    assert "Scientific Workbench" in text
    assert "사용자 작업면 (`human`)" in text
    assert "운영·근거 화면 (`engine`)" in text
    assert "changes presentation, not product truth" in text
    assert "does not add or change an API, workflow, DB schema" in text


def test_surface_mode_is_route_derived_and_not_a_user_theme() -> None:
    expected_modes = {
        'workflow: "engine"',
        'request: "human"',
        'item: "human"',
        'approval: "human"',
        'hwpx: "human"',
        'control: "engine"',
        'explorer: "engine"',
        'dashboard: "human"',
    }
    assert all(entry in JAVASCRIPT for entry in expected_modes)
    assert "document.documentElement.dataset.uiMode = mode;" in JAVASCRIPT
    assert 'id="surface-mode-label"' in HTML
    assert 'id="sidebar-mode-label"' in HTML
    assert "localStorage" not in JAVASCRIPT


def test_workflow_presents_process_and_pinned_evidence_without_unsafe_html() -> None:
    for stage in ("request", "authoring", "review", "approval", "registration", "hwpx"):
        assert f'data-flow-stage="{stage}"' in HTML
    assert 'id="workflow-evidence"' in HTML
    assert "renderWorkflowEvidence(provenance);" in JAVASCRIPT
    assert 'element.setAttribute("aria-current",' in JAVASCRIPT
    assert "innerHTML" not in JAVASCRIPT
    assert "heading.textContent = label;" in JAVASCRIPT
    assert "chip.title = technicalValue;" in JAVASCRIPT


def test_semantic_tokens_and_accessibility_rules_are_part_of_the_css_contract() -> None:
    for token in (
        "--eom-ink",
        "--eom-graphite",
        "--eom-muted-ink",
        "--eom-mist",
        "--eom-porcelain",
        "--eom-line",
        "--eom-action-teal",
        "--eom-info-cobalt",
        "--eom-signal-amber",
        "--eom-critical-vermilion",
    ):
        assert token in CSS
    assert 'html[data-ui-mode="human"]' in CSS
    assert 'html[data-ui-mode="engine"]' in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "border-radius: 16px" not in CSS
    assert "border-radius: 24px" not in CSS


def test_readable_type_scale_keeps_explanatory_text_out_of_micro_sizes() -> None:
    for token in (
        "--eom-type-caption: 12px",
        "--eom-type-label: 13px",
        "--eom-type-body: 14px",
    ):
        assert token in CSS
    assert (
        "body { margin: 0; min-width: 320px; background: var(--eom-background); "
        "font-size: var(--eom-type-body)" in CSS
    )
    assert ".curriculum-helper" in CSS and "font-size: var(--eom-type-label)" in CSS
    assert ".decision-checklist ul" in CSS and "font-size: var(--eom-type-label)" in CSS
    assert 'html[data-ui-mode="human"] .panel-heading .eyebrow { display: none; }' in CSS


def test_technical_details_are_progressively_disclosed_without_hiding_recovery() -> None:
    assert HTML.count('class="technical-details"') >= 2
    assert "<summary>기술 정보</summary>" in HTML
    assert "<summary>고정 버전·출처 정보</summary>" in HTML
    assert 'id="hwpx-existing-build-id"' in HTML
    assert 'id="hwpx-build-load"' in HTML


def test_execution_preset_mutation_is_guided_and_separately_reviewed() -> None:
    assert '<details id="advanced-preset-policy"' in HTML
    assert "고급 실행 정책" in HTML
    assert 'id="preset-base-select"' in HTML
    assert 'id="preset-review-panel"' in HTML
    assert 'id="preset-review-confirm"' in HTML
    assert 'id="preset-release-panel"' in HTML
    assert 'id="preset-release-confirm"' in HTML
    assert 'id="preset-draft-json"' not in HTML
    assert 'JSON.parse($("#preset-draft-json")' not in JAVASCRIPT
    assert 'actionButton("Release 검토"' in JAVASCRIPT
    assert "state.reviewedPresetDraft" in JAVASCRIPT
    assert "state.presetReleaseCandidate" in JAVASCRIPT


def test_static_design_assets_have_no_external_runtime_dependency() -> None:
    for text in (HTML, CSS, JAVASCRIPT):
        assert "https://" not in text
        assert "http://" not in text
