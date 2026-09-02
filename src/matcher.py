"""M4 — re-encode each search candidate and cosine-match it against the query face."""

import os
import sys
import tempfile
from urllib.parse import urlparse

import requests

from src.face_embed import cosine_similarity, detect_and_encode, sha256_file
from src.types import FaceEncoding, MatchResult, SearchCandidate

DEFAULT_THRESHOLD = 0.50    # ArcFace cosine; calibrate and record the value in README

DOWNLOAD_TIMEOUT_SECONDS = 10

# Several image hosts return 403 to a bare requests user agent.
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_ALLOWED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png", ".webp", ".bmp"})


def _suffix_for(image_url: str) -> str:
    """Pick a temp-file suffix from the URL, defaulting to .jpg."""
    suffix = os.path.splitext(urlparse(image_url).path)[1].lower()
    return suffix if suffix in _ALLOWED_SUFFIXES else ".jpg"


def _download_to_temp(image_url: str) -> str:
    """Download an image to a temp file and return its path. Caller deletes it."""
    response = requests.get(
        image_url,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        headers={"User-Agent": BROWSER_USER_AGENT},
        stream=True,
    )
    response.raise_for_status()

    handle = tempfile.NamedTemporaryFile(
        prefix="hhgoa_candidate_", suffix=_suffix_for(image_url), delete=False
    )
    try:
        with handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                handle.write(chunk)
    except BaseException:
        os.unlink(handle.name)
        raise
    return handle.name


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
    results: list[MatchResult] = []

    for index, candidate in enumerate(candidates, start=1):
        label = f"[M4] {index}/{len(candidates)} {candidate.domain}"
        temp_path: str | None = None
        try:
            temp_path = _download_to_temp(candidate.image_url)
            encoding = detect_and_encode(temp_path)
            if encoding is None:
                print(f"{label}: skipped, no face detected", file=sys.stderr)
                continue

            similarity = cosine_similarity(query.embedding, encoding.embedding)
            results.append(
                MatchResult(
                    candidate=candidate,
                    similarity=similarity,
                    matched_image_sha256=sha256_file(temp_path),
                    passed=similarity >= threshold,
                )
            )
            print(f"{label}: similarity {similarity:.4f}", file=sys.stderr)
        except requests.RequestException as exc:
            print(f"{label}: skipped, download failed: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 - one bad candidate must not end the run
            print(f"{label}: skipped, {type(exc).__name__}: {exc}", file=sys.stderr)
        finally:
            if temp_path is not None:
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    results.sort(key=lambda r: r.similarity, reverse=True)
    return results


if __name__ == "__main__":
    from src.image_search import search_by_image

    SAMPLE = "samples/query.jpg"

    print(f"[M4] encoding query {SAMPLE}")
    query_encoding = detect_and_encode(SAMPLE)
    if query_encoding is None:
        print("[M4] no face detected in query image")
        raise SystemExit(1)

    print("[M4] reverse image search")
    found = search_by_image(SAMPLE)

    print(f"[M4] verifying {len(found)} candidates at threshold {DEFAULT_THRESHOLD}")
    matches = match_candidates(query_encoding, found)

    print(f"\n{'rank':>4}  {'similarity':>10}  {'result':<6}  {'domain':<28}  source")
    print("-" * 110)
    for rank, match in enumerate(matches, start=1):
        verdict = "PASS" if match.passed else "FAIL"
        print(
            f"{rank:>4}  {match.similarity:>10.4f}  {verdict:<6}  "
            f"{match.candidate.domain:<28}  {match.candidate.source_url}"
        )

    passed_count = sum(1 for m in matches if m.passed)
    print(
        f"\n[M4] {len(matches)} encoded of {len(found)} candidates, "
        f"{passed_count} passed at {DEFAULT_THRESHOLD}"
    )
