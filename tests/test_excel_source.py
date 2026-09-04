from pathlib import Path

import pandas as pd
import pytest

from ado_defect_analysis.excel_source import ExcelSourceError, parse_excel


def _write_excel(tmp_path: Path, rows: list[dict], filename: str = "export.xlsx") -> Path:
    path = tmp_path / filename
    pd.DataFrame(rows).to_excel(path, index=False)
    return path


def test_parse_excel_with_ado_display_headers(tmp_path: Path):
    path = _write_excel(
        tmp_path,
        [
            {
                "ID": 101,
                "Title": "Checkout button does nothing",
                "Description": "<div>Clicking <b>Pay</b> does nothing.</div>",
                "Area Path": "App\\Checkout",
                "Iteration Path": "App\\Sprint 12",
                "Severity": "1 - Critical",
                "State": "Closed",
                "Resolution": "Fixed",
                "History": "Fixed event binding.",
                "Root Cause": "Code defect",
                "Created Date": "2026-01-01",
                "Closed Date": "2026-01-05",
                "Tags": "regression; payments",
                "Comments": "QA repro'd on staging. Fix verified.",
            }
        ],
    )

    defects = parse_excel(path)

    assert len(defects) == 1
    d = defects[0]
    assert d.id == 101
    assert d.title == "Checkout button does nothing"
    assert d.description == "Clicking Pay does nothing."
    assert d.module == "App\\Checkout"
    assert d.iteration_path == "App\\Sprint 12"
    assert d.resolution == "Fixed"
    assert d.resolution_notes == "Fixed event binding."
    assert d.tags == "regression; payments"
    assert d.comments == "QA repro'd on staging. Fix verified."


def test_parse_excel_with_raw_field_reference_headers(tmp_path: Path):
    path = _write_excel(
        tmp_path,
        [
            {
                "System.Id": 202,
                "System.Title": "Search returns no results",
                "System.AreaPath": "App\\Search",
                "System.State": "Resolved",
                "System.Tags": "search",
            }
        ],
    )

    defects = parse_excel(path)

    assert defects[0].id == 202
    assert defects[0].module == "App\\Search"
    assert defects[0].tags == "search"


def test_parse_excel_reads_prefixed_custom_columns_via_column_map(tmp_path: Path):
    """Customized ADO templates prefix their custom fields. Those names identify
    a deployment, so they are supplied through column_map (EXCEL_COLUMN_MAP in
    practice) rather than shipped in the default synonym table."""
    path = _write_excel(
        tmp_path,
        [
            {
                "ID": 303,
                "Title": "Claim limit not applied",
                "XX_Root Cause": "Coding Error",
                "XX_Disposition": "Working as Designed",
                "SDLC": "Development",
                "Environment": "UAT",
                "XX_Found in Environment": "SIT",
                "XX_Introduced_In_Month": "March",
                "XX_Introduced_In_Year": "2026",
                "User Impact": "High",
                "Parent": "12345",
                "Work Item Type": "Bug",
            }
        ],
    )

    d = parse_excel(
        path,
        column_map={
            "root_cause_raw": ["XX_Root Cause"],
            "resolution": ["XX_Disposition"],
            "found_in_environment": ["XX_Found in Environment"],
            "introduced_in_month": ["XX_Introduced_In_Month"],
            "introduced_in_year": ["XX_Introduced_In_Year"],
        },
    )[0]

    assert d.root_cause_raw == "Coding Error"
    assert d.resolution == "Working as Designed"
    assert d.sdlc_phase_raw == "Development"
    assert d.environment == "UAT"
    assert d.found_in_environment == "SIT"
    assert d.introduced_in_month == "March"
    assert d.introduced_in_year == "2026"
    assert d.user_impact == "High"
    assert d.parent == "12345"
    assert d.work_item_type == "Bug"


def test_parse_excel_supports_custom_column_map(tmp_path: Path):
    path = _write_excel(
        tmp_path,
        [{"WI ID": 5, "Summary": "Bug", "Component": "Billing"}],
    )

    defects = parse_excel(
        path,
        column_map={"id": ["WI ID"], "title": ["Summary"], "module": ["Component"]},
    )

    assert defects[0].id == 5
    assert defects[0].title == "Bug"
    assert defects[0].module == "Billing"


def test_parse_excel_raises_when_required_column_missing(tmp_path: Path):
    path = _write_excel(tmp_path, [{"Title": "Bug with no id column"}])

    with pytest.raises(ExcelSourceError):
        parse_excel(path)


def test_parse_excel_raises_for_missing_file(tmp_path: Path):
    with pytest.raises(ExcelSourceError):
        parse_excel(tmp_path / "does-not-exist.xlsx")


def test_parse_excel_skips_non_numeric_id_rows(tmp_path: Path):
    """Exports often end with a "Total"/footer row — it shouldn't kill the import."""
    path = _write_excel(
        tmp_path,
        [
            {"ID": 1, "Title": "Real defect"},
            {"ID": "Total", "Title": "Footer row from the export"},
            {"ID": 2, "Title": "Another real defect"},
        ],
    )

    defects = parse_excel(path)

    assert [d.id for d in defects] == [1, 2]


def test_parse_excel_skips_blank_id_rows(tmp_path: Path):
    path = _write_excel(
        tmp_path,
        [
            {"ID": 1, "Title": "Real defect"},
            {"ID": "", "Title": "Blank row from export padding"},
        ],
    )

    defects = parse_excel(path)

    assert [d.id for d in defects] == [1]
