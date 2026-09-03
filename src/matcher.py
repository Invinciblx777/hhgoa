"""M4 — re-encode each search candidate and cosine-match it against the query face."""

import os
import sys
import tempfile
from urllib.parse import urlparse

import cv2
import numpy as np
import requests

from src.face_embed import cosine_similarity, detect_and_encode, sha256_file
from src.types import FaceEncoding, MatchResult, SearchCandidate

# ArcFace cosine. Calibrated down from 0.50 — see README "Threshold calibration":
# 11 true matches floored at 0.5120, an 11-face negative control ceilinged at
# -0.0257, a 0.5377-wide empty band between them. 0.40 sits inside that band.
DEFAULT_THRESHOLD = 0.40

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


_NON_IMAGE_CONTENT_TYPES = ("text/", "application/json", "application/xml")


class _NotAnImage(RuntimeError):
    """Fetched bytes were not a usable image: wrong content-type or won't decode."""


def _response_is_non_image(response: requests.Response) -> bool:
    """True only when the Content-Type clearly names a non-image body.

    A missing or generic type (some CDNs send application/octet-stream for real
    images) is left for the decode check to judge.
    """
    ctype = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    return ctype.startswith(_NON_IMAGE_CONTENT_TYPES)


def _decodes_as_image(path: str) -> bool:
    buffer = np.fromfile(path, dtype=np.uint8)
    return buffer.size > 0 and cv2.imdecode(buffer, cv2.IMREAD_COLOR) is not None


def _fetch_one(image_url: str) -> str:
    """Fetch a single URL to a temp file. Raises _NotAnImage if the body is not
    a decodable image; propagates requests errors."""
    response = requests.get(
        image_url,
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
        headers={"User-Agent": BROWSER_USER_AGENT},
        stream=True,
    )
    response.raise_for_status()
    non_image_type = _response_is_non_image(response)

    handle = tempfile.NamedTemporaryFile(
        prefix="hhgoa_candidate_", suffix=_suffix_for(image_url), delete=False
    )
    try:
        with handle:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                handle.write(chunk)
        if non_image_type:
            raise _NotAnImage(f"non-image content-type from {image_url}")
        if not _decodes_as_image(handle.name):
            raise _NotAnImage(f"undecodable image bytes from {image_url}")
    except BaseException:
        os.unlink(handle.name)
        raise
    return handle.name


def _download_to_temp(image_url: str, fallback_url: str = "") -> tuple[str, str]:
    """Download an image to a temp file, returning (path, url_that_worked).

    If the primary URL errors, returns a non-image content-type, or yields bytes
    that will not decode, retry once with fallback_url before giving up. This
    recovers Instagram/Facebook candidates whose direct image URL 403s or serves
    an HTML error page while the Lens thumbnail is still fetchable. Caller
    deletes the file.
    """
    urls = [image_url]
    if fallback_url and fallback_url != image_url:
        urls.append(fallback_url)

    last_error: Exception | None = None
    for url in urls:
        try:
            return _fetch_one(url), url
        except (requests.RequestException, _NotAnImage) as exc:
            last_error = exc
    raise last_error if last_error is not None else _NotAnImage(image_url)


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
            temp_path, used_url = _download_to_temp(
                candidate.image_url, candidate.thumbnail_url
            )
            source = "primary image" if used_url == candidate.image_url else "thumbnail"
            print(f"{label}: fetched via {source} URL", file=sys.stderr)
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
        except (requests.RequestException, _NotAnImage) as exc:
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
