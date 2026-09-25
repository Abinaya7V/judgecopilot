"""
Beyond The Pitch web backend.

This is purely a new interface layer on top of the existing engine —
adapters/, models/, and scoring/ are untouched. The web app:
  1. accepts a submission (zip upload + form metadata),
  2. runs it through FolderAdapter -> SubmissionBundle (unchanged),
  3. runs scoring.engine.evaluate() (unchanged),
  4. stores the result in SQLite (web/data.db, via web/db.py), and
     serves it to the dashboard as JSON, and recomputes the calibrated
     leaderboard via scoring.aggregator.calibrate_pool() (unchanged)
     whenever more than one submission has been scored.

Storage lives in web/db.py — a thin SQLite repository — so submissions
and scores survive a server restart. Delete web/data.db to reset.
"""

import io
import json
import sys
import uuid
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, Form, File, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).parent.parent))  # repo root on path

from adapters.folder_adapter import FolderAdapter
from scoring.engine import evaluate, evaluate_stream, EvaluationResult
from scoring.aggregator import calibrate_pool
from scoring.similarity import compute_similarity_matrix, flag_similar_pairs
from scoring import rubrics
from web import db

app = FastAPI(title="Beyond The Pitch")

class DummyEmbeddingBackend:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        import hashlib
        vectors = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            vec = [(b / 255.0) for b in h[:16]]
            vectors.append(vec)
        return vectors


UPLOAD_ROOT = Path(__file__).parent / "_uploads"
UPLOAD_ROOT.mkdir(exist_ok=True)

db.init_db()

# Persistence now lives in web/db.py (SQLite, web/data.db) instead of an
# in-memory dict — submissions and scores survive a server restart.
# Every place that used to do SUBMISSIONS[sid] now goes through db.*.


def _submission_summary(sid: str, record: dict) -> dict:
    results: Optional[dict] = record.get("result")
    default_result = None
    if results:
        # For backward compatibility, take the 'default' or first judge's result
        default_result = results.get("default") or list(results.values())[0]

    return {
        "id": sid,
        "team_name": record["team_name"],
        "project_title": record["project_title"],
        "status": record["status"],
        "error": record.get("error"),
        "weighted_total": default_result.weighted_total if default_result else None,
        "access_code": record.get("access_code"),
    }


@app.post("/api/submissions")
async def create_submission(
    team_name: str = Form(...),
    project_title: str = Form(...),
    problem_statement: str = Form(""),
    business_impact_pitch: str = Form(""),
    tech_stack: str = Form(""),
    demo_kind: str = Form("none"),
    demo_value: str = Form(""),
    demo_notes: str = Form(""),
    code_zip: Optional[UploadFile] = File(None),
):
    """Create a submission from form fields + an optional zip of the
    team's code folder. Ingests immediately; scoring is a separate call
    so the UI can show 'ingested' before the (slower) LLM pass runs."""
    sid = str(uuid.uuid4())[:8]
    submission_dir = UPLOAD_ROOT / sid

    if code_zip is not None and code_zip.filename:
        submission_dir.mkdir(parents=True, exist_ok=True)
        raw = await code_zip.read()
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                zf.extractall(submission_dir)
        except zipfile.BadZipFile:
            raise HTTPException(400, "Uploaded file is not a valid zip archive.")
        # If the zip contains a single top-level folder, ingest from there
        # so README/code are found at the expected relative paths.
        entries = [p for p in submission_dir.iterdir() if not p.name.startswith("__MACOSX")]
        folder_path = str(entries[0]) if len(entries) == 1 and entries[0].is_dir() else str(submission_dir)
    else:
        submission_dir.mkdir(parents=True, exist_ok=True)
        folder_path = str(submission_dir)

    try:
        bundle = FolderAdapter().ingest(
            folder_path=folder_path,
            team_name=team_name,
            project_title=project_title,
            problem_statement=problem_statement,
            business_impact_pitch=business_impact_pitch,
            tech_stack=tech_stack,
            demo_kind=demo_kind,
            demo_value=demo_value or None,
            demo_notes=demo_notes or None,
        )
    except Exception as e:
        raise HTTPException(400, f"Ingestion failed: {e}")

    access_code = str(uuid.uuid4()).replace("-", "")[:6].upper()

    db.create_submission(
        sid, team_name, project_title, bundle,
        status="ingested",
        code_file_count=len(bundle.code_files),
        has_readme=bool(bundle.readme_text),
        access_code=access_code,
    )
    record = db.get_submission(sid)
    return _submission_summary(sid, record) | {
        "code_file_count": len(bundle.code_files),
        "has_readme": bool(bundle.readme_text),
    }


@app.post("/api/submissions/{sid}/evaluate")
def evaluate_submission(sid: str, judge_id: Optional[str] = None):
    """Run the (unchanged) scoring engine against this submission's
    bundle. Synchronous — fine for hackathon-day submission volumes."""
    record = db.get_submission(sid)
    if not record:
        raise HTTPException(404, "Submission not found.")

    db.set_status(sid, "scoring")
    try:
        result = evaluate(record["bundle"])
        db.save_result(sid, result, judge_id=judge_id or "default")
    except Exception as e:
        db.set_status(sid, "error", str(e))
        raise HTTPException(500, f"Scoring failed: {e}")

    return submission_detail(sid)


@app.post("/api/submissions/{sid}/evaluate/stream")
def evaluate_submission_stream(sid: str):
    """Same scoring pass as /evaluate, but streamed as Server-Sent Events
    so the UI can show live progress ('Scoring Code Quality…', etc.)
    instead of a single blocking spinner. Each dimension call to the LLM
    takes a few seconds; this surfaces that instead of hiding it."""
    record = db.get_submission(sid)
    if not record:
        raise HTTPException(404, "Submission not found.")

    def _sse(event: dict) -> str:
        return f"data: {json.dumps(event)}\n\n"

    def _gen():
        db.set_status(sid, "scoring")
        try:
            for event in evaluate_stream(record["bundle"]):
                if event["stage"] == "dimension":
                    payload = {
                        "stage": "dimension",
                        "status": event["status"],
                        "key": event["key"],
                        "label": event["label"],
                    }
                    if event["status"] == "done":
                        payload["score"] = asdict(event["score"])
                    if event["status"] == "error":
                        payload["error"] = event["error"]
                    yield _sse(payload)
                elif event["stage"] == "summary":
                    payload = {"stage": "summary", "status": event["status"]}
                    if event.get("error"):
                        payload["error"] = event["error"]
                    yield _sse(payload)
                elif event["stage"] == "final":
                    # For streaming, we assume judge_id=default as this is usually single-judge UI
                    db.save_result(sid, event["result"], judge_id="default")
                    yield _sse({
                        "stage": "final",
                        "status": "done",
                        "detail": submission_detail(sid),
                    })
        except Exception as e:
            db.set_status(sid, "error", str(e))
            yield _sse({"stage": "fatal", "status": "error", "error": str(e)})

    return StreamingResponse(
        _gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable proxy buffering (e.g. nginx)
        },
    )


@app.get("/api/submissions")
def list_submissions():
    return [_submission_summary(sid, r) for sid, r in db.list_submissions()]


@app.get("/api/submissions/{sid}")
def submission_detail(sid: str):
    record = db.get_submission(sid)
    if not record:
        raise HTTPException(404, "Submission not found.")

    bundle = record["bundle"]
    results: Optional[dict] = record.get("result")
    default_result = None
    if results:
        default_result = results.get("default") or list(results.values())[0]

    return {
        "id": sid,
        "team_name": record["team_name"],
        "project_title": record["project_title"],
        "status": record["status"],
        "error": record.get("error"),
        "submission": {
            "problem_statement": bundle.problem_statement,
            "business_impact_pitch": bundle.business_impact_pitch,
            "tech_stack": bundle.tech_stack,
            "readme_present": bool(bundle.readme_text),
            "code_file_count": len(bundle.code_files),
            "demo_kind": bundle.demo.kind,
            "demo_value": bundle.demo.value,
        },
        "result": asdict(default_result) if default_result else None,
        "access_code": record.get("access_code"),
    }


@app.get("/api/scorecard/{access_code}")
def get_scorecard(access_code: str):
    import re
    from scoring.aggregator import merge_judge_scores
    
    record = db.get_submission_by_access_code(access_code)
    if not record:
        raise HTTPException(404, "Scorecard not found.")
        
    if record["status"] != "scored" or not record.get("result"):
        return {
            "team_name": record["team_name"],
            "project_title": record["project_title"],
            "status": "not yet evaluated"
        }
        
    sid = None
    all_subs = dict(db.list_submissions())
    for s_id, sub_record in all_subs.items():
        if sub_record.get("access_code") == access_code:
            sid = s_id
            break

    scored = [
        (s_id, r["result"]) for s_id, r in all_subs.items()
        if r.get("result") is not None
    ]
    
    results_for_calibration = []
    merged_by_sid = {}
    for s_id, judge_results in scored:
        merged = merge_judge_scores(s_id, judge_results)
        merged_by_sid[s_id] = merged
        results_for_calibration.append(merged["averaged"])
        
    bundles_dict = {s_id: all_subs[s_id]["bundle"] for s_id, _ in scored if "bundle" in all_subs[s_id]}
    backend = DummyEmbeddingBackend()
    matrix = compute_similarity_matrix(bundles_dict, backend)
    matches = flag_similar_pairs(matrix)
    
    ranked = calibrate_pool(results_for_calibration, matches)
    
    my_rank = next((r for r in ranked if r.result.team_name == record["team_name"]), None)
    
    # Strip judge IDs from justifications
    merged_result = merged_by_sid[sid]["averaged"]
    dimension_scores = []
    for ds in merged_result.dimension_scores:
        stripped_justification = re.sub(r'^\[.*?\]:\s*', '', ds.justification, flags=re.MULTILINE)
        dimension_scores.append({
            "key": ds.key,
            "label": ds.label,
            "score": ds.score,
            "justification": stripped_justification
        })
        
    response = {
        "team_name": record["team_name"],
        "project_title": record["project_title"],
        "status": "scored",
        "overall_score": my_rank.calibrated_total if my_rank else merged_result.weighted_total,
        "dimension_scores": dimension_scores,
    }
    
    if my_rank and my_rank.similarity_flags:
        response["similarity_notice"] = "some overlap was detected with another submission \u2014 this did not affect your score, it's a signal for organizers"
        
    return response


@app.get("/api/leaderboard")
def leaderboard():
    from scoring.aggregator import merge_judge_scores
    scored = [
        (sid, r["result"]) for sid, r in db.list_submissions()
        if r.get("result") is not None
    ]
    if not scored:
        return []

    # Fallback for single judge backward compat: get the averaged score
    results = [merge_judge_scores(sid, r)["averaged"] for sid, r in scored]
    id_by_team = {list(r.values())[0].team_name: sid for sid, r in scored}  # assumes unique team names
    
    # Compute similarity matches
    all_subs = dict(db.list_submissions())
    bundles_dict = {sid: all_subs[sid]["bundle"] for sid, _ in scored if "bundle" in all_subs[sid]}
    backend = DummyEmbeddingBackend()
    matrix = compute_similarity_matrix(bundles_dict, backend)
    matches = flag_similar_pairs(matrix)

    ranked = calibrate_pool(results, matches)

    return [
        {
            "id": id_by_team.get(r.result.team_name),
            "rank": r.rank,
            "percentile": r.percentile,
            "calibrated_total": r.calibrated_total,
            "team_name": r.result.team_name,
            "project_title": r.result.project_title,
            "weighted_total": r.result.weighted_total,
            "judge_flags": r.result.judge_flags,
            "similarity_flags": r.similarity_flags,
        }
        for r in ranked
    ]

@app.get("/api/batch/similarity")
def batch_similarity():
    scored = [
        (sid, r) for sid, r in db.list_submissions()
        if r.get("result") is not None
    ]
    if not scored:
        return []
        
    bundles_dict = {sid: r["bundle"] for sid, r in scored if "bundle" in r}
    backend = DummyEmbeddingBackend()
    matrix = compute_similarity_matrix(bundles_dict, backend)
    matches = flag_similar_pairs(matrix)
    
    return [
        {
            "submission_a_id": m.submission_a_id,
            "submission_b_id": m.submission_b_id,
            "team_a_name": m.team_a_name,
            "team_b_name": m.team_b_name,
            "idea_score": m.idea_score,
            "code_score": m.code_score,
            "matched_fields": m.matched_fields,
        }
        for m in matches
    ]

@app.get("/api/jury/overview")
def jury_overview():
    subs = db.list_submissions()
    ingested = len(subs)
    scored = sum(1 for _, r in subs if r.get("result"))
    unscored = ingested - scored
    return {
        "ingested": ingested,
        "scored": scored,
        "unscored": unscored
    }

@app.get("/api/jury/leaderboard")
def jury_leaderboard():
    from scoring.aggregator import merge_judge_scores
    scored = [
        (sid, r["result"]) for sid, r in db.list_submissions()
        if r.get("result") is not None
    ]
    if not scored:
        return []

    id_by_team = {}
    
    # Pre-merge results to get the 'averaged' result for calibration
    merged_by_sid = {}
    results_for_calibration = []
    
    all_subs = dict(db.list_submissions())
    for sid, judge_results in scored:
        team_name = list(judge_results.values())[0].team_name
        id_by_team[team_name] = sid
        merged = merge_judge_scores(sid, judge_results)
        merged_by_sid[sid] = merged
        results_for_calibration.append(merged["averaged"])
        
    # Compute similarity matches
    bundles_dict = {sid: all_subs[sid]["bundle"] for sid, _ in scored if "bundle" in all_subs[sid]}
    backend = DummyEmbeddingBackend()
    matrix = compute_similarity_matrix(bundles_dict, backend)
    matches = flag_similar_pairs(matrix)

    ranked = calibrate_pool(results_for_calibration, matches)

    output = []
    for r in ranked:
        sid = id_by_team.get(r.result.team_name)
        merged = merged_by_sid[sid]
        
        output.append({
            "id": sid,
            "rank": r.rank,
            "percentile": r.percentile,
            "calibrated_total": r.calibrated_total,
            "team_name": r.result.team_name,
            "project_title": r.result.project_title,
            "weighted_total": r.result.weighted_total,
            "judge_flags": r.result.judge_flags,
            "similarity_flags": r.similarity_flags,
            "judges_scored": len(merged["per_judge"]),
            "disagreement_flags": merged["flagged_disagreement"],
            "averaged_result": asdict(merged["averaged"]),
            "per_judge_results": {j: asdict(res) for j, res in merged["per_judge"].items()}
        })
    return output

@app.get("/api/jury/export")
def jury_export():
    return jury_leaderboard()



@app.delete("/api/submissions/{sid}")
def delete_submission(sid: str):
    if not db.delete_submission(sid):
        raise HTTPException(404, "Submission not found.")
    return {"deleted": sid}


# --- Rubric weight configuration --------------------------------------
#
# Lets judges/organizers reweight dimensions for events where a criterion
# doesn't apply the same way — e.g. an idea-only track with no live demo
# requirement might want Demo Completeness weighted near zero rather than
# penalizing every team equally for something they weren't asked to do.
#
# This reads/writes scoring.rubrics.DIMENSIONS directly (the same list
# scoring/engine.py and scoring/aggregator.py iterate over), so a change
# here takes effect on the next evaluation immediately — no restart.
# Already-scored submissions keep the weighted_total they were scored
# with; re-run "Run evaluation" on them if you want scores reflecting
# the new weights (see the note in scoring/rubrics.py:set_weights).

class WeightsUpdate(BaseModel):
    weights: dict[str, float]


@app.get("/api/config/weights")
def get_rubric_weights():
    return {
        "weights": rubrics.get_weights(),
        "defaults": rubrics.get_default_weights(),
        "dimensions": [
            {"key": d.key, "label": d.label} for d in rubrics.DIMENSIONS
        ],
    }


@app.put("/api/config/weights")
def update_rubric_weights(payload: WeightsUpdate):
    try:
        updated = rubrics.set_weights(payload.weights)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"weights": updated}


@app.post("/api/config/weights/reset")
def reset_rubric_weights():
    return {"weights": rubrics.reset_weights()}


# --- Static frontend -------------------------------------------------

static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
def index():
    return FileResponse(static_dir / "index.html")
