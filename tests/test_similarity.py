from models.submission import SubmissionBundle, CodeFile
from scoring.similarity import compute_similarity_matrix, flag_similar_pairs

class DummyTestBackend:
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # Returns identical vectors if texts are identical, else completely orthogonal
        # Since we just want to test threshold logic, we can return [1.0, 0.0] for 
        # one kind of text and [0.0, 1.0] for another, or just hash it.
        import hashlib
        vectors = []
        for text in texts:
            h = hashlib.sha256(text.encode()).digest()
            vec = [(b / 255.0) for b in h[:4]]
            # normalize
            norm = sum(x*x for x in vec) ** 0.5
            vec = [x/norm if norm else 0 for x in vec]
            vectors.append(vec)
        return vectors

def test_similarity_flags_matched_fields():
    backend = DummyTestBackend()
    
    # Sub 1 and Sub 2 have identical idea but different code
    sub1 = SubmissionBundle(
        team_name="Team 1",
        project_title="Idea A",
        problem_statement="Problem A",
        business_impact_pitch="Pitch A",
        code_files=[CodeFile(path="main.py", content="def a(): pass")]
    )
    
    sub2 = SubmissionBundle(
        team_name="Team 2",
        project_title="Idea A",
        problem_statement="Problem A",
        business_impact_pitch="Pitch A",
        code_files=[CodeFile(path="utils.py", content="def b(): pass")]
    )
    
    # Sub 3 has different idea but same code as Sub 1
    sub3 = SubmissionBundle(
        team_name="Team 3",
        project_title="Idea B",
        problem_statement="Problem B",
        business_impact_pitch="Pitch B",
        code_files=[CodeFile(path="main.py", content="def a(): pass")]
    )
    
    bundles = {
        "s1": sub1,
        "s2": sub2,
        "s3": sub3
    }
    
    matrix = compute_similarity_matrix(bundles, backend)
    matches = flag_similar_pairs(matrix, threshold=0.99)
    
    assert len(matches) == 2
    
    # Check what got matched
    for m in matches:
        if (m.submission_a_id == "s1" and m.submission_b_id == "s2") or (m.submission_a_id == "s2" and m.submission_b_id == "s1"):
            assert m.matched_fields == ["idea"]
            assert m.idea_score > 0.99
            assert m.code_score < 0.99
        elif (m.submission_a_id == "s1" and m.submission_b_id == "s3") or (m.submission_a_id == "s3" and m.submission_b_id == "s1"):
            assert m.matched_fields == ["code_structure"]
            assert m.code_score > 0.99
            assert m.idea_score < 0.99

if __name__ == "__main__":
    test_similarity_flags_matched_fields()
    print("All tests passed.")
