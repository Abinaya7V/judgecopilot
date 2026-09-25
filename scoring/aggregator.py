"""
Pool-level aggregation across all submissions in a hackathon.

Raw per-submission scores are produced independently (order shouldn't
matter, but LLM scoring can still drift slightly run to run). This module
adds a second-pass calibration step: rank submissions per dimension and
compute a percentile-adjusted score, so a submission judged early or late
in a batch isn't penalized relative to ones judged when the "scale" in
context had drifted.
"""

from dataclasses import dataclass
from statistics import mean, pstdev
from typing import Dict, Any

from scoring.engine import EvaluationResult, DimensionScore
from scoring.rubrics import DIMENSIONS


@dataclass
class RankedResult:
    result: EvaluationResult
    rank: int
    percentile: float
    calibrated_total: float
    similarity_flags: list[dict] = None



def calibrate_pool(results: list[EvaluationResult], similarity_matches: list['SimilarityMatch'] = None) -> list[RankedResult]:
    """
    Applies z-score normalization per dimension across the whole pool,
    then recomputes each submission's weighted total from the normalized
    per-dimension scores. This flattens out systematic drift (e.g. the
    model scoring everything a point lower after reading 30 mediocre
    READMEs in a row) without hiding genuine differences in quality.
    
    If similarity_matches is provided, cross-submission similarity flags are 
    attached to the ranked results.
    """
    if not results:
        return []

    dim_keys = [d.key for d in DIMENSIONS]
    dim_weights = {d.key: d.weight for d in DIMENSIONS}

    # raw_scores[dim_key] = [score for each submission, in order]
    raw_scores: dict[str, list[float]] = {
        key: [next(ds.score for ds in r.dimension_scores if ds.key == key) for r in results]
        for key in dim_keys
    }

    calibrated_totals = [0.0] * len(results)

    for key in dim_keys:
        values = raw_scores[key]
        mu = mean(values)
        sigma = pstdev(values) or 1.0  # avoid div-by-zero when all scores tie

        for i, raw in enumerate(values):
            z = (raw - mu) / sigma
            # Map z-score back onto a 1-10 scale centered on the pool mean,
            # clipped to stay in range. This is intentionally gentle —
            # it corrects drift, it doesn't override genuine outliers.
            calibrated = min(10.0, max(1.0, mu + z * 1.5))
            calibrated_totals[i] += calibrated * dim_weights[key]

    total_weight = sum(dim_weights.values())
    calibrated_pct = [
        round((t / (10 * total_weight)) * 100, 1) for t in calibrated_totals
    ]

    ranked = sorted(
        zip(results, calibrated_pct),
        key=lambda pair: pair[1],
        reverse=True,
    )

    n = len(ranked)
    output: list[RankedResult] = []
    
    # Pre-compute similarity flags keyed by team_name if matches are provided
    flags_by_team = {r.team_name: [] for r in results}
    if similarity_matches:
        for match in similarity_matches:
            flags_by_team[match.team_a_name].append({
                "matched_team": match.team_b_name,
                "matched_team_id": match.submission_b_id,
                "idea_score": match.idea_score,
                "code_score": match.code_score,
                "matched_fields": match.matched_fields
            })
            flags_by_team[match.team_b_name].append({
                "matched_team": match.team_a_name,
                "matched_team_id": match.submission_a_id,
                "idea_score": match.idea_score,
                "code_score": match.code_score,
                "matched_fields": match.matched_fields
            })

    for idx, (result, cal_total) in enumerate(ranked):
        rank = idx + 1
        percentile = round((1 - (idx / max(n - 1, 1))) * 100, 1) if n > 1 else 100.0
        output.append(RankedResult(
            result=result,
            rank=rank,
            percentile=percentile,
            calibrated_total=cal_total,
            similarity_flags=flags_by_team[result.team_name]
        ))
    return output


def merge_judge_scores(
    submission_id: str, 
    judge_results: Dict[str, EvaluationResult], 
    disagreement_threshold: float = 1.5
) -> Dict[str, Any]:
    """
    Takes the raw results from all judges for a single submission and computes the consensus and variance.
    If only one judge scored it, returns a result mathematically equivalent to their single score.
    """
    if not judge_results:
        return {}

    judges = list(judge_results.keys())
    
    # If single judge, return simple wrapping
    if len(judges) == 1:
        j = judges[0]
        return {
            "per_judge": {j: judge_results[j]},
            "averaged": judge_results[j],
            "disagreement": {},
            "flagged_disagreement": []
        }
        
    first_result = judge_results[judges[0]]
    dim_keys = [d.key for d in DIMENSIONS]
    
    averaged_dimensions = []
    disagreement = {}
    flagged_disagreement = []
    
    for key in dim_keys:
        scores = []
        justifications = []
        strengths = []
        concerns = []
        label = ""
        for j_id, res in judge_results.items():
            for ds in res.dimension_scores:
                if ds.key == key:
                    scores.append(ds.score)
                    label = ds.label
                    justifications.append(f"[{j_id}]: {ds.justification}")
                    if ds.strengths:
                        strengths.extend([f"[{j_id}] {s}" for s in ds.strengths])
                    if ds.concerns:
                        concerns.extend([f"[{j_id}] {c}" for c in ds.concerns])
                    break
                    
        avg_score = round(mean(scores), 1) if scores else 0.0
        stdev = pstdev(scores) if len(scores) > 1 else 0.0
        
        disagreement[key] = stdev
        if stdev > disagreement_threshold:
            flagged_disagreement.append(key)
            
        averaged_dimensions.append(DimensionScore(
            key=key,
            label=label,
            score=avg_score,
            justification="\n\n".join(justifications),
            strengths=strengths,
            concerns=concerns
        ))

    # Recompute weighted total for the averaged result
    dim_weights = {d.key: d.weight for d in DIMENSIONS}
    total_weight = sum(dim_weights.values())
    raw_total = sum(d.score * dim_weights.get(d.key, 1.0) for d in averaged_dimensions)
    weighted_total = round((raw_total / (10 * total_weight)) * 100, 1) if total_weight > 0 else 0.0

    # Combine top strengths/improvements
    all_ts = []
    all_ti = []
    all_flags = []
    for j_id, res in judge_results.items():
        all_ts.extend([f"[{j_id}] {s}" for s in res.top_strengths])
        all_ti.extend([f"[{j_id}] {i}" for i in res.top_improvements])
        all_flags.extend([f"[{j_id}] {f}" for f in res.judge_flags])

    averaged_result = EvaluationResult(
        team_name=first_result.team_name,
        project_title=first_result.project_title,
        dimension_scores=averaged_dimensions,
        weighted_total=weighted_total,
        top_strengths=all_ts,
        top_improvements=all_ti,
        judge_flags=all_flags
    )

    return {
        "per_judge": judge_results,
        "averaged": averaged_result,
        "disagreement": disagreement,
        "flagged_disagreement": flagged_disagreement
    }

