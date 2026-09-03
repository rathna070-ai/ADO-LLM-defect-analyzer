from ado_defect_analysis.models import Defect


def test_from_work_item_strips_html_and_maps_fields():
    item = {
        "id": 42,
        "fields": {
            "System.Title": "Checkout button does nothing",
            "System.Description": "<div>Clicking <b>Pay</b> does nothing.</div>",
            "System.AreaPath": "App\\Checkout",
            "System.State": "Closed",
            "System.CreatedDate": "2026-01-01T00:00:00Z",
            "Microsoft.VSTS.Common.Severity": "1 - Critical",
            "Microsoft.VSTS.Common.ClosedDate": "2026-01-05T00:00:00Z",
            "Microsoft.VSTS.Common.ResolvedReason": "Fixed event handler binding.",
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
    assert defect.root_cause_raw == "Code defect"
    assert defect.tags == "regression; payments"
    assert defect.comments == "QA repro'd on staging."


def test_from_work_item_falls_back_to_history_when_no_resolved_reason():
    item = {
        "id": 7,
        "fields": {
            "System.Title": "Bug",
            "System.History": "Root cause was a race condition.",
        },
    }

    defect = Defect.from_work_item(item, root_cause_field="Microsoft.VSTS.CMMI.RootCause")

    assert defect.resolution_notes == "Root cause was a race condition."
