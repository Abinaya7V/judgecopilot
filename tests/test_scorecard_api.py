import pytest
from fastapi.testclient import TestClient

from web.app import app
from web import db

client = TestClient(app)

def test_scorecard_api_flow():
    # Reset DB
    db.reset_db()
    
    # 1. Ingest a submission, ensure access code is returned
    res = client.post("/api/submissions", data={
        "team_name": "Team A",
        "project_title": "Project Alpha",
        "problem_statement": "x",
        "business_impact_pitch": "x",
        "tech_stack": "x",
        "demo_kind": "none",
        "demo_value": "",
        "demo_notes": ""
    })
    assert res.status_code == 200
    data = res.json()
    sid = data["id"]
    access_code = data["access_code"]
    
    assert access_code is not None
    assert len(access_code) == 6
    
    # 2. Scorecard before evaluation
    res = client.get(f"/api/scorecard/{access_code}")
    assert res.status_code == 200
    scorecard = res.json()
    assert scorecard["team_name"] == "Team A"
    assert scorecard["status"] == "not yet evaluated"
    assert "overall_score" not in scorecard
    
    # 3. Evaluate it
    res = client.post(f"/api/submissions/{sid}/evaluate?judge_id=j1")
    assert res.status_code == 200
    
    # 4. Scorecard after evaluation
    res = client.get(f"/api/scorecard/{access_code}")
    assert res.status_code == 200
    scorecard = res.json()
    assert scorecard["status"] == "scored"
    assert "overall_score" in scorecard
    assert len(scorecard["dimension_scores"]) > 0
    # Ensure judge tags are stripped
    for ds in scorecard["dimension_scores"]:
        assert "[j1]:" not in ds["justification"]
        
    # 5. Invalid access code returns 404
    res = client.get("/api/scorecard/INVALID")
    assert res.status_code == 404
