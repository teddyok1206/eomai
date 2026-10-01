from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "apps/web_gui/eom_web_gui/static/hwpx-delivery-target.js"
APP = ROOT / "apps/web_gui/eom_web_gui/static/app.js"
HTML = ROOT / "apps/web_gui/eom_web_gui/static/index.html"
DECISION = ROOT / "docs/adr/0166-flow-to-hwpx-pinned-revision-handoff.md"


def _run_module(tmp_path: Path, expression: str) -> object:
    node = shutil.which("node")
    if node is None:
        raise AssertionError("Node is required for the HWPX delivery target gate")
    staged = tmp_path / "hwpx-delivery-target.mjs"
    staged.write_bytes(MODULE.read_bytes())
    script = f"""
      import * as target from {json.dumps(staged.as_uri())};
      const value = (() => {{ {expression} }})();
      console.log(JSON.stringify(value));
    """
    completed = subprocess.run(
        [node, "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def test_completed_workflow_yields_exact_frozen_registration_target(tmp_path: Path) -> None:
    value = _run_module(
        tmp_path,
        """
        const value = target.hwpxTargetFromWorkflow({workflow: {
          state: "COMPLETED",
          workflow_id: "workflow_11111111111111111111111111111111",
          item_registration: {
            item_id: "item_22222222222222222222222222222222",
            item_revision_id: "itemrev_33333333333333333333333333333333",
          },
        }});
        return {value, frozen: Object.isFrozen(value)};
        """,
    )

    assert value == {
        "value": {
            "source": "WORKFLOW",
            "itemRevisionId": "itemrev_33333333333333333333333333333333",
            "itemId": "item_22222222222222222222222222222222",
            "workflowId": "workflow_11111111111111111111111111111111",
        },
        "frozen": True,
    }


def test_nonterminal_or_unregistered_workflow_has_no_delivery_target(tmp_path: Path) -> None:
    value = _run_module(
        tmp_path,
        """
        return [
          target.hwpxTargetFromWorkflow({workflow: {
            state: "RUNNING",
            workflow_id: "workflow_11111111111111111111111111111111",
            item_registration: {
              item_id: "item_22222222222222222222222222222222",
              item_revision_id: "itemrev_33333333333333333333333333333333",
            },
          }}),
          target.hwpxTargetFromWorkflow({workflow: {
            state: "COMPLETED",
            workflow_id: "workflow_11111111111111111111111111111111",
            item_registration: null,
          }}),
        ];
        """,
    )

    assert value == [None, None]


def test_workflow_target_rejects_malformed_revision_identity(tmp_path: Path) -> None:
    value = _run_module(
        tmp_path,
        """
        try {
          target.hwpxTargetFromWorkflow({workflow: {
            state: "COMPLETED",
            workflow_id: "workflow_11111111111111111111111111111111",
            item_registration: {
              item_id: "item_22222222222222222222222222222222",
              item_revision_id: "itemrev_stale",
            },
          }});
          return "accepted";
        } catch (error) {
          return error.message;
        }
        """,
    )

    assert value == "HWPX_DELIVERY_TARGET_INVALID"


def test_preview_and_build_use_the_same_revision_target_shape(tmp_path: Path) -> None:
    value = _run_module(
        tmp_path,
        """
        const preview = target.hwpxTargetFromItemPreview({
          template_delivery_available: true,
          item_id: "item_22222222222222222222222222222222",
          item_revision_id: "itemrev_33333333333333333333333333333333",
          workflow_id: "workflow_11111111111111111111111111111111",
        });
        const unavailable = target.hwpxTargetFromItemPreview({
          template_delivery_available: false,
        });
        const build = target.hwpxTargetFromBuild({
          item_revision_id: "itemrev_33333333333333333333333333333333",
        });
        return {preview, unavailable, build};
        """,
    )

    assert value == {
        "preview": {
            "source": "ITEM_PREVIEW",
            "itemRevisionId": "itemrev_33333333333333333333333333333333",
            "itemId": "item_22222222222222222222222222222222",
            "workflowId": "workflow_11111111111111111111111111111111",
        },
        "unavailable": None,
        "build": {
            "source": "HWPX_BUILD",
            "itemRevisionId": "itemrev_33333333333333333333333333333333",
            "itemId": None,
            "workflowId": None,
        },
    }


def test_flow_handoff_is_explicit_and_does_not_submit_a_build() -> None:
    source = APP.read_text(encoding="utf-8")
    html = HTML.read_text(encoding="utf-8")
    handoff = source.split("function continueWorkflowToHwpx()", maxsplit=1)[1].split(
        "function appendEvidenceChip", maxsplit=1
    )[0]

    assert 'id="workflow-hwpx-continue"' in html
    assert 'id="item-hwpx-continue"' in html
    assert 'aria-describedby="workflow-hwpx-message"' in html
    assert 'id="hwpx-target-title" tabindex="-1"' in html
    assert "selectHwpxDeliveryTarget(state.workflowHwpxTarget);" in handoff
    assert 'showView("hwpx");' in handoff
    assert '$("#hwpx-target-title").focus();' in handoff
    assert "api(" not in handoff
    assert "createHwpxBuild" not in handoff
    assert 'class="technical-details inline-technical-details admin-only"' in html


def test_target_switch_clears_a_mismatched_build_and_bulk_path_stays_separate() -> None:
    source = APP.read_text(encoding="utf-8")
    decision = DECISION.read_text(encoding="utf-8")

    assert "currentBuildRevision !== nextRevision" in source
    assert "clearHwpxBuildSelection();" in source
    assert 'state.hwpxDeliveryTarget?.source === "WORKFLOW"' in source
    assert "Mock-exam production continues" in decision
    assert "does not create 25 individual HWPX builds" in decision
    assert "Assessment Assembly HWPX application" in decision


def test_workflow_handoff_ignores_stale_lookup_stream_and_poll_responses() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "workflowRequestSequence: 0" in source
    assert "const requestSequence = ++state.workflowRequestSequence;" in source
    assert source.count("requestSequence !== state.workflowRequestSequence") >= 5
    assert source.count("value?.workflow?.workflow_id !== workflowId") == 2
    assert 'state.hwpxDeliveryTarget?.source === "WORKFLOW"' in source
    assert 'renderWorkflowHwpxHandoff(null, "LOADING", null);' in source


def test_hwpx_submission_reuses_one_intent_and_blocks_double_clicks() -> None:
    source = APP.read_text(encoding="utf-8")

    assert "hwpxBuildSubmissionPending: false" in source
    assert "hwpxBuildSubmissionIntent: null" in source
    assert "if (state.hwpxBuildSubmissionPending) return;" in source
    assert "state.hwpxBuildSubmissionIntent?.fingerprint !== fingerprint" in source
    assert "idempotency_key: intent.idempotencyKey" in source
    assert "state.hwpxBuildSubmissionIntent = null;" in source
    assert "state.hwpxBuildSubmissionIntent !== intent" in source
    assert "state.hwpxDeliveryTarget?.itemRevisionId !== revision" in source
    assert 'submit.textContent = "HWPX 제작 요청 중";' in source
    assert 'submit.textContent = "문항 HWPX 만들기";' in source
