from pathlib import Path

import pandas as pd
import pytest
import responses

from ado_defect_analysis.ado_query import AdoQueryUrlError
from ado_defect_analysis.config import AdoConfig, Config, LlmConfig
from ado_defect_analysis.pipeline.fetch import run_fetch_from_excel, run_fetch_from_query
from ado_defect_analysis.storage import DefectStore


def _config(tmp_path: Path) -> Config:
    return Config(
        ado=AdoConfig(),
        llm=LlmConfig(),
        db_path=tmp_path / "d.db",
        output_dir=tmp_path / "out",
    )


def test_excel_import_lands_in_sqlite(tmp_path: Path):
    """The no-credentials path: spreadsheet in, defects table populated."""
    export = tmp_path / "export.xlsx"
    pd.DataFrame(
        [
            {
                "ID": 101,
                "Title": "Checkout fails",
                "Area Path": "App\\Checkout",
                "Iteration Path": "App\\Sprint 12",
                "Resolution": "Fixed",
            }
        ]
    ).to_excel(export, index=False)
    config = _config(tmp_path)

    count = run_fetch_from_excel(config, export)

    assert count == 1
    stored = DefectStore(config.db_path).get_all_defects()
    assert stored[0].id == 101
    assert stored[0].iteration_path == "App\\Sprint 12"
    assert stored[0].resolution == "Fixed"


@responses.activate
def test_query_fetch_uses_org_and_project_from_the_url(tmp_path: Path):
    """The pasted URL decides the target, not .env — so a user can point at
    any project their token reads without editing config."""
    guid = "a1b2c3d4-1111-2222-3333-444455556666"
    base = "https://dev.azure.com/urlorg/UrlProject/_apis"
    responses.add(responses.GET, f"{base}/wit/wiql/{guid}", json={"workItems": [{"id": 3}]})
    responses.add(
        responses.POST,
        f"{base}/wit/workitemsbatch",
        json={"value": [{"id": 3, "fields": {"System.Title": "From URL"}}]},
    )
    config = _config(tmp_path)
    config.ado.organization = "env-org"
    config.ado.project = "EnvProject"

    count = run_fetch_from_query(
        config, f"https://dev.azure.com/urlorg/UrlProject/_queries/query/{guid}", pat="token"
    )

    assert count == 1
    assert DefectStore(config.db_path).get_all_defects()[0].title == "From URL"


def test_query_fetch_rejects_a_bad_url(tmp_path: Path):
    with pytest.raises(AdoQueryUrlError):
        run_fetch_from_query(_config(tmp_path), "https://example.com/nope", pat="token")


def test_excel_import_is_idempotent(tmp_path: Path):
    """Re-running fetch against the same export must not duplicate rows."""
    export = tmp_path / "export.xlsx"
    pd.DataFrame([{"ID": 101, "Title": "Checkout fails"}]).to_excel(export, index=False)
    config = _config(tmp_path)

    run_fetch_from_excel(config, export)
    run_fetch_from_excel(config, export)

    assert len(DefectStore(config.db_path).get_all_defects()) == 1
