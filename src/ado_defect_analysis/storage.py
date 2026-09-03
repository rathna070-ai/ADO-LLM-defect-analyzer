"""SQLite persistence for defects and their LLM categorizations.

Two tables: `defects` (raw ADO pull) and `categorizations` (LLM output,
one row per defect id, replaced on re-categorization). SQLite rather than
a CSV-only pipeline because re-runs need to know which defects are already
categorized without re-parsing every export.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import Defect, DefectCategorization

#: Label for defects loaded before uploads were tracked by source.
UNKNOWN_SOURCE = "(earlier upload)"

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
    comments TEXT,
    iteration_path TEXT,
    resolution TEXT,
    sdlc_phase_raw TEXT,
    environment TEXT,
    found_in_environment TEXT,
    introduced_in_month TEXT,
    introduced_in_year TEXT,
    user_impact TEXT,
    parent TEXT,
    work_item_type TEXT,
    source_name TEXT,
    source_uploaded_at TEXT
);

CREATE TABLE IF NOT EXISTS categorizations (
    defect_id INTEGER PRIMARY KEY REFERENCES defects(id),
    root_cause_category TEXT NOT NULL,
    testing_gap_flag INTEGER NOT NULL,
    summary TEXT NOT NULL,
    confidence REAL NOT NULL,
    sdlc_phase TEXT,
    evidence TEXT,
    model TEXT,
    prompt_version TEXT,
    categorized_at TEXT,
    input_hash TEXT
);
"""

# Columns added after the initial schema — kept here so an existing defects.db
# upgrades in place instead of erroring on the new column names.
_MIGRATIONS = {
    "defects": [
        ("iteration_path", "TEXT"),
        ("resolution", "TEXT"),
        ("sdlc_phase_raw", "TEXT"),
        ("environment", "TEXT"),
        ("found_in_environment", "TEXT"),
        ("introduced_in_month", "TEXT"),
        ("introduced_in_year", "TEXT"),
        ("user_impact", "TEXT"),
        ("parent", "TEXT"),
        ("work_item_type", "TEXT"),
        ("source_name", "TEXT"),
        ("source_uploaded_at", "TEXT"),
    ],
    "categorizations": [
        ("sdlc_phase", "TEXT"),
        ("evidence", "TEXT"),
        ("model", "TEXT"),
        ("prompt_version", "TEXT"),
        ("categorized_at", "TEXT"),
        ("input_hash", "TEXT"),
    ],
}


class DefectStore:
    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            self._migrate(conn)

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        for table, columns in _MIGRATIONS.items():
            existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            for column, sql_type in columns:
                if column not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type}")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        # Off by default in SQLite, so the categorizations -> defects reference
        # isn't actually enforced without this.
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def upsert_defects(self, defects: list[Defect]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO defects
                    (id, title, description, module, severity, state,
                     resolution_notes, root_cause_raw, created_date, closed_date,
                     tags, comments, iteration_path, resolution,
                     sdlc_phase_raw, environment, found_in_environment,
                     introduced_in_month, introduced_in_year, user_impact, parent,
                     work_item_type, source_name, source_uploaded_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    comments=excluded.comments,
                    iteration_path=excluded.iteration_path,
                    resolution=excluded.resolution,
                    sdlc_phase_raw=excluded.sdlc_phase_raw,
                    environment=excluded.environment,
                    found_in_environment=excluded.found_in_environment,
                    introduced_in_month=excluded.introduced_in_month,
                    introduced_in_year=excluded.introduced_in_year,
                    user_impact=excluded.user_impact,
                    parent=excluded.parent,
                    work_item_type=excluded.work_item_type,
                    source_name=excluded.source_name,
                    source_uploaded_at=excluded.source_uploaded_at
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
                        d.iteration_path,
                        d.resolution,
                        d.sdlc_phase_raw,
                        d.environment,
                        d.found_in_environment,
                        d.introduced_in_month,
                        d.introduced_in_year,
                        d.user_impact,
                        d.parent,
                        d.work_item_type,
                        d.source_name,
                        d.source_uploaded_at,
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

    def get_all_defects(self) -> list[Defect]:
        """All defects regardless of categorization status — used to force a full re-categorize."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM defects").fetchall()
        return [_row_to_defect(row) for row in rows]

    def get_upload_sources(self) -> list[dict]:
        """One row per upload: name, when, and how much of it is analyzed.

        Drives the source picker — the user chooses which upload(s) to run
        rather than every defect ever loaded being swept into one pool.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    COALESCE(NULLIF(d.source_name, ''), ?) AS name,
                    MAX(COALESCE(d.source_uploaded_at, '')) AS uploaded_at,
                    COUNT(*) AS total,
                    SUM(CASE WHEN c.defect_id IS NULL THEN 0 ELSE 1 END) AS categorized
                FROM defects d
                LEFT JOIN categorizations c ON c.defect_id = d.id
                GROUP BY name
                ORDER BY uploaded_at DESC, name
                """,
                (UNKNOWN_SOURCE,),
            ).fetchall()
        return [
            {
                "name": row["name"],
                "uploaded_at": row["uploaded_at"] or "",
                "total": int(row["total"]),
                "categorized": int(row["categorized"] or 0),
                "uncategorized": int(row["total"]) - int(row["categorized"] or 0),
            }
            for row in rows
        ]

    def get_defects_for_sources(self, sources: list[str]) -> list[Defect]:
        """Every defect belonging to the named uploads."""
        if not sources:
            return []
        placeholders = ",".join("?" for _ in sources)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM defects
                WHERE COALESCE(NULLIF(source_name, ''), ?) IN ({placeholders})
                """,
                (UNKNOWN_SOURCE, *sources),
            ).fetchall()
        return [_row_to_defect(row) for row in rows]

    def get_categorization_fingerprints(self) -> dict[int, tuple[str, str, str]]:
        """defect_id -> (input_hash, prompt_version, model) for what's already stored.

        Lets a re-categorize run skip defects where none of the three inputs to
        the judgment have changed, so a backfill only spends tokens on work
        that would actually produce a different answer.
        """
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT defect_id, input_hash, prompt_version, model FROM categorizations"
            ).fetchall()
        return {
            row["defect_id"]: (
                row["input_hash"] or "",
                row["prompt_version"] or "",
                row["model"] or "",
            )
            for row in rows
        }

    def save_categorizations(self, categorizations: list[DefectCategorization]) -> None:
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO categorizations
                    (defect_id, root_cause_category, testing_gap_flag, summary, confidence,
                     sdlc_phase, evidence, model, prompt_version, categorized_at, input_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(defect_id) DO UPDATE SET
                    root_cause_category=excluded.root_cause_category,
                    testing_gap_flag=excluded.testing_gap_flag,
                    summary=excluded.summary,
                    confidence=excluded.confidence,
                    sdlc_phase=excluded.sdlc_phase,
                    evidence=excluded.evidence,
                    model=excluded.model,
                    prompt_version=excluded.prompt_version,
                    categorized_at=excluded.categorized_at,
                    input_hash=excluded.input_hash
                """,
                [
                    (
                        c.defect_id,
                        c.root_cause_category,
                        int(c.testing_gap_flag),
                        c.summary,
                        c.confidence,
                        c.sdlc_phase,
                        c.evidence,
                        c.model,
                        c.prompt_version,
                        c.categorized_at,
                        c.input_hash,
                    )
                    for c in categorizations
                ],
            )

    def get_categorized_defects(self) -> list[dict]:
        """Defects joined with their categorization.

        The shape the export and aggregate stages need.
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT d.*, c.root_cause_category, c.testing_gap_flag, c.summary, c.confidence,
                       c.sdlc_phase, c.evidence, c.model, c.prompt_version, c.categorized_at,
                       c.input_hash
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
        iteration_path=row["iteration_path"] or "",
        resolution=row["resolution"] or "",
        sdlc_phase_raw=row["sdlc_phase_raw"] or "",
        environment=row["environment"] or "",
        found_in_environment=row["found_in_environment"] or "",
        introduced_in_month=row["introduced_in_month"] or "",
        introduced_in_year=row["introduced_in_year"] or "",
        user_impact=row["user_impact"] or "",
        parent=row["parent"] or "",
        work_item_type=row["work_item_type"] or "",
        source_name=row["source_name"] or "",
        source_uploaded_at=row["source_uploaded_at"] or "",
    )
