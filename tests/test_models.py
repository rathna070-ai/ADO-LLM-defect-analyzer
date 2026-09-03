import pytest

from ado_defect_analysis.models import Defect, DefectCategorization, strip_html


def test_from_work_item_strips_html_and_maps_fields():
    item = {
        "id": 42,
        "fields": {
            "System.Title": "Checkout button does nothing",
            "System.Description": "<div>Clicking <b>Pay</b> does nothing.</div>",
            "System.AreaPath": "App\\Checkout",
            "System.IterationPath": "App\\Sprint 12",
            "System.State": "Closed",
            "System.CreatedDate": "2026-01-01T00:00:00Z",
            "Microsoft.VSTS.Common.Severity": "1 - Critical",
            "Microsoft.VSTS.Common.ClosedDate": "2026-01-05T00:00:00Z",
            "Microsoft.VSTS.Common.ResolvedReason": "Fixed",
            "Microsoft.VSTS.CMMI.RootCause": "Code defect",
            "System.Tags": "regression; payments",
        },
    }

    defect = Defect.from_work_item(
        item, root_cause_field="Microsoft.VSTS.CMMI.RootCause", comments="QA repro'd on staging."
    )

    assert defect.id == 42
    assert defect.description == "Clicking Pay does nothing."
    assert defect.module == "App\\Checkout"
    assert defect.iteration_path == "App\\Sprint 12"
    assert defect.resolution == "Fixed"
    assert defect.root_cause_raw == "Code defect"
    assert defect.tags == "regression; payments"
    assert defect.comments == "QA repro'd on staging."


def test_from_work_item_resolution_notes_come_from_history():
    item = {
        "id": 7,
        "fields": {
            "System.Title": "Bug",
            "System.History": "Root cause was a race condition.",
            "Microsoft.VSTS.Common.ResolvedReason": "Fixed",
        },
    }

    defect = Defect.from_work_item(item, root_cause_field="Microsoft.VSTS.CMMI.RootCause")

    assert defect.resolution_notes == "Root cause was a race condition."
    assert defect.resolution == "Fixed"


def test_from_work_item_defaults_iteration_and_resolution_when_absent():
    item = {"id": 8, "fields": {"System.Title": "Bug"}}

    defect = Defect.from_work_item(item, root_cause_field="Microsoft.VSTS.CMMI.RootCause")

    assert defect.iteration_path == ""
    assert defect.resolution == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("<p>Payment&nbsp;failed</p>", "Payment failed"),
        ("Search &amp; filter broken", "Search & filter broken"),
        ("<div>a &lt;b&gt; c</div>", "a <b> c"),
        ("", ""),
    ],
)
def test_strip_html_unescapes_entities(raw: str, expected: str):
    """Entities left as-is would reach the LLM prompt as literal markup noise."""
    assert strip_html(raw) == expected


def test_defect_categorization_defaults_sdlc_phase_to_unknown():
    categorization = DefectCategorization(
        defect_id=1,
        root_cause_category="code_defect",
        testing_gap_flag=False,
        summary="stub",
        confidence=0.5,
    )

    assert categorization.sdlc_phase == "unknown"
