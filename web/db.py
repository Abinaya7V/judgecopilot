"""
SQLite persistence for Beyond The Pitch's web layer.

This replaces the in-memory SUBMISSIONS dict that used to live in
web/app.py. It's intentionally a thin repository: it stores/loads the
same shapes app.py already worked with (SubmissionBundle, EvaluationResult),
it just backs them with a file instead of a process-lifetime dict.

adapters/, models/, and scoring/ are untouched — same as the README's
"swap in a database" note describes. Only this file and web/app.py change.

The DB file lives at web/data.db by default; delete it to reset all
stored submissions (or call reset_db() from a Python shell).
"""

import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from models.submission import SubmissionBundle, CodeFile, DemoAsset
from scoring.engine import EvaluationResult, DimensionScore

DB_PATH = Path(__file__).parent / "data.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create the submissions table if it doesn't exist yet. Safe to
    call on every app startup."""
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id TEXT PRIMARY KEY,
                team_name TEXT NOT NULL,
                project_title TEXT NOT NULL,
                status TEXT NOT NULL,
                error TEXT,
                bundle_json TEXT NOT NULL,
                result_json TEXT,
                code_file_count INTEGER NOT NULL DEFAULT 0,
                has_readme INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                access_code TEXT UNIQUE
            )
        """)
        try:
            conn.execute("ALTER TABLE submissions ADD COLUMN access_code TEXT UNIQUE")
        except sqlite3.OperationalError:
            pass


def reset_db() -> None:
    """Drop and recreate the table — wipes every stored submission."""
    with _connect() as conn:
        conn.execute("DROP TABLE IF EXISTS submissions")
    init_db()


# --- dataclass <-> JSON helpers -----------------------------------
#
# dataclasses.asdict() handles the serialize direction for free, but
# reconstructing nested dataclasses (CodeFile, DemoAsset, DimensionScore)
# back from plain dicts needs a little help — dataclasses don't do this
# automatically.

def _bundle_to_json(bundle: SubmissionBundle) -> str:
    return json.dumps(asdict(bundle))


def _bundle_from_json(raw: str) -> SubmissionBundle:
    d = json.loads(raw)
    d["code_files"] = [CodeFile(**f) for f in d.get("code_files", [])]
    d["demo"] = DemoAsset(**d["demo"]) if d.get("demo") else DemoAsset(kind="none")
    return SubmissionBundle(**d)


def _result_to_json(results: dict[str, EvaluationResult]) -> str:
    return json.dumps({judge_id: asdict(result) for judge_id, result in results.items()})


def _result_from_json(raw: str) -> dict[str, EvaluationResult]:
    d = json.loads(raw)
    # Handle backward compatibility: if it's a single result (has dimension_scores at top level),
    # wrap it in a default dict.
    if "dimension_scores" in d:
        d["dimension_scores"] = [DimensionScore(**s) for s in d.get("dimension_scores", [])]
        return {"default": EvaluationResult(**d)}
    
    # New format: dictionary of {judge_id: EvaluationResult}
    out = {}
    for judge_id, res_dict in d.items():
        res_dict["dimension_scores"] = [DimensionScore(**s) for s in res_dict.get("dimension_scores", [])]
        out[judge_id] = EvaluationResult(**res_dict)
    return out


def _row_to_record(row: sqlite3.Row) -> dict:
    return {
        "team_name": row["team_name"],
        "project_title": row["project_title"],
        "status": row["status"],
        "error": row["error"],
        "bundle": _bundle_from_json(row["bundle_json"]),
        "result": _result_from_json(row["result_json"]) if row["result_json"] else None,
        "code_file_count": row["code_file_count"],
        "has_readme": bool(row["has_readme"]),
        "access_code": row["access_code"] if "access_code" in row.keys() else None,
    }


# --- public repository API ----------------------------------------

def create_submission(
    sid: str,
    team_name: str,
    project_title: str,
    bundle: SubmissionBundle,
    status: str,
    code_file_count: int,
    has_readme: bool,
    access_code: str,
) -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT INTO submissions
               (id, team_name, project_title, status, error, bundle_json,
                result_json, code_file_count, has_readme, access_code)
               VALUES (?, ?, ?, ?, NULL, ?, NULL, ?, ?, ?)""",
            (sid, team_name, project_title, status, _bundle_to_json(bundle),
             code_file_count, int(has_readme), access_code),
        )


def get_submission(sid: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE id = ?", (sid,)).fetchone()
    return _row_to_record(row) if row else None


def get_submission_by_access_code(access_code: str) -> Optional[dict]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM submissions WHERE access_code = ?", (access_code,)).fetchone()
    return _row_to_record(row) if row else None


def list_submissions() -> list[tuple[str, dict]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM submissions ORDER BY created_at ASC").fetchall()
    return [(row["id"], _row_to_record(row)) for row in rows]


def set_status(sid: str, status: str, error: Optional[str] = None) -> None:
    with _connect() as conn:
        conn.execute(
            "UPDATE submissions SET status = ?, error = ? WHERE id = ?",
            (status, error, sid),
        )


def save_result(sid: str, result: EvaluationResult, judge_id: str = "default") -> None:
    judge_id = judge_id.strip().lower() if judge_id else "default"
    with _connect() as conn:
        row = conn.execute("SELECT result_json FROM submissions WHERE id = ?", (sid,)).fetchone()
        existing = _result_from_json(row["result_json"]) if row and row["result_json"] else {}
        existing[judge_id] = result
        conn.execute(
            "UPDATE submissions SET result_json = ?, status = 'scored', error = NULL WHERE id = ?",
            (_result_to_json(existing), sid),
        )


def delete_submission(sid: str) -> bool:
    with _connect() as conn:
        cur = conn.execute("DELETE FROM submissions WHERE id = ?", (sid,))
        return cur.rowcount > 0
