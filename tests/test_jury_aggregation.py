from scoring.engine import EvaluationResult, DimensionScore
from scoring.aggregator import merge_judge_scores

def test_merge_single_judge():
    r1 = EvaluationResult(
        team_name="T1",
        project_title="P1",
        weighted_total=85.0,
        dimension_scores=[
            DimensionScore(key="code_quality", label="Code Quality", score=8.5, justification="Good", strengths=["S1"], concerns=[])
        ],
        top_strengths=["Overall good"],
        top_improvements=[],
        judge_flags=[]
    )
    
    merged = merge_judge_scores("sid", {"alice": r1})
    
    assert merged["disagreement"] == {}
    assert merged["flagged_disagreement"] == []
    assert merged["averaged"].weighted_total == 85.0
    assert merged["averaged"].dimension_scores[0].score == 8.5
    assert merged["per_judge"]["alice"] == r1

def test_merge_multiple_judges():
    r1 = EvaluationResult(
        team_name="T1",
        project_title="P1",
        weighted_total=80.0,
        dimension_scores=[
            DimensionScore(key="business_impact", label="Business Impact", score=9.0, justification="Great", strengths=["S1"], concerns=[])
        ],
        top_strengths=["A"], top_improvements=[], judge_flags=[]
    )
    r2 = EvaluationResult(
        team_name="T1",
        project_title="P1",
        weighted_total=40.0,
        dimension_scores=[
            DimensionScore(key="business_impact", label="Business Impact", score=2.0, justification="Terrible", strengths=[], concerns=["C1"])
        ],
        top_strengths=["B"], top_improvements=[], judge_flags=[]
    )
    
    merged = merge_judge_scores("sid", {"alice": r1, "bob": r2}, disagreement_threshold=1.5)
    
    assert "business_impact" in merged["disagreement"]
    # pstdev of [9.0, 2.0] is 3.5
    assert merged["disagreement"]["business_impact"] == 3.5
    assert "business_impact" in merged["flagged_disagreement"]
    
    avg_dim = next(d for d in merged["averaged"].dimension_scores if d.key == "business_impact")
    assert avg_dim.score == 5.5
    assert "[alice]: Great" in avg_dim.justification
    assert "[bob]: Terrible" in avg_dim.justification
    assert "[alice] S1" in avg_dim.strengths
    assert "[bob] C1" in avg_dim.concerns

if __name__ == "__main__":
    test_merge_single_judge()
    test_merge_multiple_judges()
    print("All tests passed.")
