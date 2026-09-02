"""M4 — re-encode each search candidate and cosine-match it against the query face."""

from src.types import FaceEncoding, MatchResult, SearchCandidate

DEFAULT_THRESHOLD = 0.50    # ArcFace cosine; calibrate and record the value in README


def match_candidates(
    query: FaceEncoding,
    candidates: list[SearchCandidate],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[MatchResult]:
    """Verify each candidate by downloading its image and re-running face encoding.

    Computes the cosine similarity between the query embedding and each
    candidate embedding. Candidates with no detectable face are logged and
    skipped rather than raising. Returns every result sorted by similarity
    descending, with the passed flag set according to the threshold.
    """
    raise NotImplementedError
