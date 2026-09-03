"""SQLite persistence for defects and their LLM categorizations.

Two tables: `defects` (raw ADO pull) and `categorizations` (LLM output,
one row per defect id, replaced on re-categorization). SQLite rather than
a CSV-only pipeline because re-runs need to know which defects are already
categorized without re-parsing every export.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from .models import Defect, DefectCategorization

_SCHEMA = """
CREATE TABLE IF NOT EXISTS defects (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    module TEXT,
    severity TEXT,
    state TEXT,
    resolution_notes TEXT,
    root_cause_raw TEXT,
    created_date TEXT,
    closed_date TEXT,
    tags TEXT,
    comments TEXT
);

CREATE TABLE IF NOT EXISTS categorizations (
    defect_id INTEGER PRIMARY KEY REFERENCES defects(id),
    root_cause_category TEXT NOT NULL,
    testing_gap_flag INTEGER NOT NULL,
    summary TEXT NOT NULL,
    confidence REAL NOT NULL
);
"""


class DefectStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def upsert_defects(self, defects: list[Defect]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO defects
                    (id, title, description, module, severity, state,
                     resolution_notes, root_cause_raw, created_date, closed_date,
                     tags, comments)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    module=excluded.module,
                    severity=excluded.severity,
                    state=excluded.state,
                    resolution_notes=excluded.resolution_notes,
                    root_cause_raw=excluded.root_cause_raw,
                    created_date=excluded.created_date,
                    closed_date=excluded.closed_date,
                    tags=excluded.tags,
                    comments=excluded.comments
                """,
                [
                    (
                        d.id,
                        d.title,
                        d.description,
                        d.module,
                        d.severity,
                        d.state,
                        d.resolution_notes,
                        d.root_cause_raw,
                        d.created_date,
                        d.closed_date,
                        d.tags,
                        d.comments,
                    )
                    for d in defects
                ],
            )

    def get_uncategorized_defects(self) -> list[Defect]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.* FROM defects d
                LEFT JOIN categorizations c ON c.defect_id = d.id
                WHERE c.defect_id IS NULL
                """
            ).fetchall()
        return [_row_to_defect(row) for row in rows]

    def save_categorizations(self, categorizations: list[DefectCategorization]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO categorizations
                    (defect_id, root_cause_category, testing_gap_flag, summary, confidence)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(defect_id) DO UPDATE SET
                    root_cause_category=excluded.root_cause_category,
                    testing_gap_flag=excluded.testing_gap_flag,
                    summary=excluded.summary,
                    confidence=excluded.confidence
                """,
                [
                    (c.defect_id, c.root_cause_category, int(c.testing_gap_flag), c.summary, c.confidence)
                    for c in categorizations
                ],
            )

    def get_categorized_defects(self) -> list[dict]:
        """Defects joined with their categorization — the shape the export and aggregate stages need."""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, c.root_cause_category, c.testing_gap_flag, c.summary, c.confidence
                FROM defects d
                JOIN categorizations c ON c.defect_id = d.id
                """
            ).fetchall()
        return [dict(row) for row in rows]


def _row_to_defect(row: sqlite3.Row) -> Defect:
    return Defect(
        id=row["id"],
        title=row["title"],
        description=row["description"] or "",
        module=row["module"] or "",
        severity=row["severity"] or "",
        state=row["state"] or "",
        resolution_notes=row["resolution_notes"] or "",
        root_cause_raw=row["root_cause_raw"] or "",
        created_date=row["created_date"] or "",
        closed_date=row["closed_date"],
        tags=row["tags"] or "",
        comments=row["comments"] or "",
    )
