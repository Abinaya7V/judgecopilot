"""
Cross-submission novelty & plagiarism detection module.

NOTE: This is a purely semantic similarity signal meant for human judges
to investigate further. It is NOT proof of plagiarism. Similar business
impact pitches are extremely common in hackathons (e.g. many teams build
"AI to solve hospital wait times"), and similar code structure may result
from using the same boilerplate starter templates.
"""

from dataclasses import dataclass
from typing import Protocol
import re
import math
from models.submission import SubmissionBundle

class EmbeddingBackend(Protocol):
    """
    Abstracts the embedding provider (OpenAI, SentenceTransformers, etc.).
    Mirrors the engine.py LLM abstraction.
    """
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...

@dataclass
class SubmissionEmbeddings:
    """Holds the separated embeddings to allow field-level comparison."""
    submission_id: str
    team_name: str
    idea_embedding: list[float]
    code_embedding: list[float]

@dataclass
class SimilarityMatch:
    """Represents a flagged pair exceeding the similarity threshold."""
    submission_a_id: str
    submission_b_id: str
    team_a_name: str
    team_b_name: str
    idea_score: float
    code_score: float
    matched_fields: list[str]   # e.g. ["idea", "code_structure"]


def _get_code_summary(bundle: SubmissionBundle) -> str:
    """
    Extracts structural code fingerprint:
    1. Collects relative file paths.
    2. Excludes boilerplate filenames like README, LICENSE, requirements.txt, 
       package.json, etc.
    3. Extracts top-level class and function definitions.
    """
    ignore_patterns = [
        r"(?i)^readme", r"(?i)^license", r"requirements\.txt$", 
        r"package(-lock)?\.json$", r"yarn\.lock$", r"\.gitignore$", 
        r"docker-compose\.ya?ml$", r"poetry\.lock$", r"Pipfile(\.lock)?$"
    ]
    
    lines = []
    for f in bundle.code_files:
        if any(re.search(pat, f.path) for pat in ignore_patterns):
            continue
            
        lines.append(f"File: {f.path}")
        
        # Simple extraction for Python/JS top-level definitions
        # This isn't a full AST parser, just a quick structural fingerprint
        for line in f.content.splitlines():
            line_stripped = line.strip()
            if line_stripped.startswith("def ") or line_stripped.startswith("class ") or \
               line_stripped.startswith("function ") or line_stripped.startswith("export function ") or \
               line_stripped.startswith("const ") and "=>" in line_stripped:
                lines.append(f"  {line_stripped[:100]}")
                
    return "\n".join(lines)


def embed_submission(submission_id: str, bundle: SubmissionBundle, backend: EmbeddingBackend) -> SubmissionEmbeddings:
    """
    Creates two embeddings per submission to allow for granular matching:
    1. Idea (Title + Problem + Pitch + README)
    2. Code Structure (File paths + structure summary)
    """
    idea_text = f"Title: {bundle.project_title}\nProblem: {bundle.problem_statement}\nPitch: {bundle.business_impact_pitch}\nREADME: {bundle.readme_text}"
    code_text = _get_code_summary(bundle)
    
    # We call the backend once with both texts
    embeddings = backend.embed_texts([idea_text, code_text])
    
    return SubmissionEmbeddings(
        submission_id=submission_id,
        team_name=bundle.team_name,
        idea_embedding=embeddings[0],
        code_embedding=embeddings[1]
    )


def compute_similarity_matrix(bundles_dict: dict[str, SubmissionBundle], backend: EmbeddingBackend) -> list[SubmissionEmbeddings]:
    """
    Batch-level operation. Embeds all submissions.
    Returns the list of SubmissionEmbeddings acting as our "matrix" 
    from which we can compute any pairwise dot product.
    """
    matrix = []
    for sid, bundle in bundles_dict.items():
        matrix.append(embed_submission(sid, bundle, backend))
    return matrix


def _cosine_sim(vec_a: list[float], vec_b: list[float]) -> float:
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def flag_similar_pairs(matrix: list[SubmissionEmbeddings], threshold: float = 0.80) -> list[SimilarityMatch]:
    """
    Computes pairwise cosine similarities across the batch.
    Flags pairs where either the idea_score or code_score > threshold.
    """
    matches = []
    n = len(matrix)
    for i in range(n):
        for j in range(i + 1, n):
            emb_a = matrix[i]
            emb_b = matrix[j]
            
            idea_score = _cosine_sim(emb_a.idea_embedding, emb_b.idea_embedding)
            code_score = _cosine_sim(emb_a.code_embedding, emb_b.code_embedding)
            
            matched_fields = []
            if idea_score > threshold:
                matched_fields.append("idea")
            if code_score > threshold:
                matched_fields.append("code_structure")
                
            if matched_fields:
                matches.append(SimilarityMatch(
                    submission_a_id=emb_a.submission_id,
                    submission_b_id=emb_b.submission_id,
                    team_a_name=emb_a.team_name,
                    team_b_name=emb_b.team_name,
                    idea_score=idea_score,
                    code_score=code_score,
                    matched_fields=matched_fields
                ))
    
    # Sort matches by the highest score between the two pairs
    matches.sort(key=lambda m: max(m.idea_score, m.code_score), reverse=True)
    return matches
