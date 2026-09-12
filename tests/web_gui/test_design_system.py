from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
STATIC = ROOT / "apps/web_gui/eom_web_gui/static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
JAVASCRIPT = (STATIC / "app.js").read_text(encoding="utf-8")
DESIGN_NOTE = ROOT / "docs/product/EOM_SCIENTIFIC_WORKBENCH_DESIGN_SYSTEM.md"
LOGIN_HTML = (STATIC / "login.html").read_text(encoding="utf-8")
MARK = STATIC / "eom-mark.svg"


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
        '"item-bank": "human"',
        'approval: "human"',
        'hwpx: "human"',
        'control: "engine"',
        '"admin-settings": "engine"',
        'explorer: "engine"',
        'dashboard: "human"',
    }
    assert all(entry in JAVASCRIPT for entry in expected_modes)
    assert "document.documentElement.dataset.uiMode = mode;" in JAVASCRIPT
    assert 'id="surface-mode-label"' not in HTML
    assert 'id="sidebar-mode-label"' not in HTML
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
    assert "--eom-brand: #4f46e5" in CSS
    assert 'html[data-ui-mode="engine"]' in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "border-radius: 16px" not in CSS
    assert "border-radius: 24px" not in CSS


def test_brand_mark_is_one_color_vector_without_a_literal_letter() -> None:
    root = ElementTree.fromstring(MARK.read_bytes())
    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert root.attrib["viewBox"] == "0 0 64 64"
    assert root.findall("{http://www.w3.org/2000/svg}text") == []
    assert root.findall("{http://www.w3.org/2000/svg}image") == []
    paths = root.findall("{http://www.w3.org/2000/svg}path")
    assert len(paths) == 1
    assert paths[0].attrib["stroke"] == "#4F46E5"
    assert paths[0].attrib["fill"] == "none"
    for document in (HTML, LOGIN_HTML):
        assert (
            '<link rel="icon" href="/studio/assets/eom-mark.svg" type="image/svg+xml">' in document
        )
        assert 'class="brand-seal" src="/studio/assets/eom-mark.svg" alt=""' in document
        assert 'aria-hidden="true">E<' not in document
    assert "background: linear-gradient(145deg" not in CSS


def test_login_surface_uses_the_quiet_solid_workbench_background() -> None:
    login_shell_rule = next(line for line in CSS.splitlines() if line.startswith(".login-shell "))
    assert ".login-page { background: var(--eom-surface-muted); }" in CSS
    assert "background: var(--eom-surface-muted)" in login_shell_rule
    assert "gradient" not in login_shell_rule


def test_readable_type_scale_keeps_explanatory_text_out_of_micro_sizes() -> None:
    for token in (
        "--eom-type-caption: 13px",
        "--eom-type-label: 14px",
        "--eom-type-body: 15px",
    ):
        assert token in CSS
    assert (
        "body { margin: 0; min-width: 320px; background: var(--eom-background); "
        "font-size: var(--eom-type-body)" in CSS
    )
    assert ".decision-checklist ul" in CSS and "font-size: var(--eom-type-label)" in CSS
    assert 'class="eyebrow"' not in HTML
    assert 'class="eyebrow"' not in LOGIN_HTML
    assert 'class="curriculum-helper"' not in HTML
    assert "login-intro" not in LOGIN_HTML
    assert "security-note" not in LOGIN_HTML
    assert "<small" not in LOGIN_HTML


def test_content_first_visual_system_is_consistent_and_restrained() -> None:
    assert '-apple-system, BlinkMacSystemFont, "SF Pro Text"' in CSS
    assert "--eom-radius-control: 10px" in CSS
    assert "--eom-radius-card: 12px" in CSS
    assert ".nav-item { width: 100%; min-height: 44px" in CSS
    assert ".button, .icon-button { min-height: 40px" in CSS
    assert ".login-panel .button { min-height: 44px" in CSS
    assert "background-image:" not in CSS
    assert "linear-gradient(" not in CSS
    assert "sidebar-footer" not in HTML
    assert "안정화 기준 적용" not in HTML


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
    assert 'actionButton("사용 가능 전환 검토"' in JAVASCRIPT
    assert "state.reviewedPresetDraft" in JAVASCRIPT
    assert "state.presetReleaseCandidate" in JAVASCRIPT


def test_execution_settings_have_a_separate_admin_view() -> None:
    control_start = HTML.index('data-view="control"')
    settings_start = HTML.index('data-view="admin-settings"')
    learning_start = HTML.index('data-view="learning"')
    control_view = HTML[control_start:settings_start]
    settings_view = HTML[settings_start:learning_start]

    assert 'data-view-target="admin-settings"' in HTML
    assert 'id="admin-settings-refresh"' in settings_view
    assert 'id="execution-preset-list"' not in control_view
    assert 'id="advanced-preset-policy"' not in control_view
    assert 'id="execution-preset-list"' in settings_view
    assert 'id="advanced-preset-policy"' in settings_view
    assert 'if (name === "admin-settings" && hasAdminRole()) loadAdminSettings();' in JAVASCRIPT


def test_codex_slots_show_live_activity_and_disclose_details_on_demand() -> None:
    assert 'id="codex-slots-summary"' in HTML
    assert 'class="control-list codex-slot-list"' in HTML
    assert 'document.createElement("details")' in JAVASCRIPT
    assert 'card.classList.add("is-active")' in JAVASCRIPT
    assert "Number(account.active_lease_count) > 0" in JAVASCRIPT
    assert "openBindings = new Set" in JAVASCRIPT
    assert "window.setTimeout(loadCodexAccounts, 5000)" in JAVASCRIPT
    assert ".codex-slot-card[open]" in CSS
    assert ".codex-slot-card.is-active" in CSS
    assert ".codex-slot-body" in CSS


def test_static_design_assets_have_no_external_runtime_dependency() -> None:
    for text in (HTML, CSS, JAVASCRIPT):
        assert "https://" not in text
        assert "http://" not in text
