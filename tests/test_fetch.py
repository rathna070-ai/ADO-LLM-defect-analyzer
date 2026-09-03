from pathlib import Path

import pandas as pd

from ado_defect_analysis.config import AdoConfig, Config, LlmConfig
from ado_defect_analysis.pipeline.fetch import run_fetch_from_excel
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


def test_excel_import_is_idempotent(tmp_path: Path):
    """Re-running fetch against the same export must not duplicate rows."""
    export = tmp_path / "export.xlsx"
    pd.DataFrame([{"ID": 101, "Title": "Checkout fails"}]).to_excel(export, index=False)
    config = _config(tmp_path)

    run_fetch_from_excel(config, export)
    run_fetch_from_excel(config, export)

    assert len(DefectStore(config.db_path).get_all_defects()) == 1
