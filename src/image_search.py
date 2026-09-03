"""M3 — reverse image search against Google Lens through SerpApi."""

import base64
import sys
from urllib.parse import urlparse

import requests

from src.config import IMGBB_KEY, SERPAPI_KEY
from src.types import SearchCandidate

IMGBB_UPLOAD_URL = "https://api.imgbb.com/1/upload"
SERPAPI_SEARCH_URL = "https://serpapi.com/search"

# Temporary uploads self-delete after 24 hours; the query image only needs to be
# reachable for the duration of the Lens call.
UPLOAD_EXPIRATION_SECONDS = 24 * 60 * 60
REQUEST_TIMEOUT_SECONDS = 60

SOCIAL_DOMAINS = frozenset(
    {
        "instagram.com",
        "x.com",
        "twitter.com",
        "linkedin.com",
        "facebook.com",
        "reddit.com",
        "tiktok.com",
        "youtube.com",
        "github.com",
    }
)

# Public suffixes that occupy two labels, so that a host such as
# www.instagram.co.uk resolves to instagram.co.uk rather than co.uk. This is a
# pragmatic subset, not the full Public Suffix List; every domain in
# SOCIAL_DOMAINS uses a single-label suffix, so the social check is unaffected.
_TWO_LABEL_SUFFIXES = frozenset(
    {"co.uk", "co.in", "co.jp", "co.kr", "com.au", "com.br", "com.mx", "co.za"}
)


class ImageUploadError(RuntimeError):
    """Raised when the query image could not be hosted for the Lens call."""


class ImageSearchError(RuntimeError):
    """Raised when the reverse image search did not produce usable results."""


def _registrable_domain(url: str) -> str:
    """Reduce a URL to its registrable domain, lowercased and without www."""
    host = (urlparse(url).hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    if ".".join(labels[-2:]) in _TWO_LABEL_SUFFIXES:
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def upload_temp_image(image_path: str) -> str:
    """Upload a local image to imgbb and return its public URL.

    Google Lens needs a publicly reachable image URL, so the query image is
    hosted temporarily before the search call is made. The upload is created
    with a 24 hour expiration and deletes itself afterwards.
    """
    with open(image_path, "rb") as handle:
        payload = base64.b64encode(handle.read())

    response = requests.post(
        IMGBB_UPLOAD_URL,
        params={"key": IMGBB_KEY, "expiration": UPLOAD_EXPIRATION_SECONDS},
        data={"image": payload},
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ImageUploadError(
            f"imgbb upload failed with HTTP {response.status_code}: {response.text[:300]}"
        )

    body = response.json()
    if not body.get("success"):
        reason = body.get("error", {}).get("message", "no error message returned")
        raise ImageUploadError(f"imgbb upload rejected: {reason}")

    data = body.get("data", {})
    url = data.get("display_url") or data.get("url")
    if not url:
        raise ImageUploadError(
            "imgbb response contained neither display_url nor url"
        )

    print(f"[M3] uploaded query image -> {url}", file=sys.stderr)
    return url


def _parse_visual_match(match: dict) -> SearchCandidate | None:
    """Turn one SerpApi google_lens visual match into a SearchCandidate.

    Every field name this module depends on is read here and nowhere else, so a
    schema change is a single-function fix. Matches with no page link or no
    direct image URL are unusable downstream and are dropped.
    """
    source_url = match.get("link") or ""
    thumbnail_url = match.get("thumbnail") or ""
    image_url = match.get("image") or thumbnail_url
    if not source_url or not image_url:
        return None

    domain = _registrable_domain(source_url)
    return SearchCandidate(
        source_url=source_url,
        image_url=image_url,
        title=match.get("title") or "",
        domain=domain,
        is_social=domain in SOCIAL_DOMAINS,
        thumbnail_url=thumbnail_url,
    )


def search_by_image(image_path: str, max_results: int = 20) -> list[SearchCandidate]:
    """Reverse image search the given image and return the candidate pages found.

    Makes a genuine live SerpApi call; results are never hardcoded or cached.
    Candidates from instagram, x, twitter, linkedin, facebook, reddit, tiktok,
    youtube and github are flagged with is_social=True and are returned first,
    followed by the remaining candidates. API errors are raised, never swallowed
    into an empty list.
    """
    image_url = upload_temp_image(image_path)

    response = requests.get(
        SERPAPI_SEARCH_URL,
        params={
            "engine": "google_lens",
            "url": image_url,
            # Pinned so the result set does not shift if the engine default
            # changes; "all" is what visual_matches is parsed against.
            "type": "all",
            "api_key": SERPAPI_KEY,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    if response.status_code != 200:
        raise ImageSearchError(
            f"SerpApi returned HTTP {response.status_code}: {response.text[:300]}"
        )

    body = response.json()
    if body.get("error"):
        raise ImageSearchError(f"SerpApi reported an error: {body['error']}")

    matches = body.get("visual_matches") or []
    if not matches:
        raise ImageSearchError(
            f"Google Lens returned no visual matches for {image_url}"
        )

    social: list[SearchCandidate] = []
    other: list[SearchCandidate] = []
    for match in matches:
        candidate = _parse_visual_match(match)
        if candidate is None:
            continue
        print(
            f"[M3] candidate {candidate.domain}"
            f"{' (social)' if candidate.is_social else ''}",
            file=sys.stderr,
        )
        (social if candidate.is_social else other).append(candidate)

    ordered = (social + other)[:max_results]
    if not ordered:
        raise ImageSearchError(
            f"Google Lens returned {len(matches)} matches but none carried both a "
            f"page link and an image URL"
        )
    return ordered


if __name__ == "__main__":
    SAMPLE = "samples/query.jpg"

    print(f"[M3] reverse image search on {SAMPLE}")
    results = search_by_image(SAMPLE)
    for index, result in enumerate(results, start=1):
        print(f"{index:>3}. {result.domain:<28} social={result.is_social!s:<5} {result.source_url}")

    social_hits = sum(1 for r in results if r.is_social)
    print(f"\n[M3] {len(results)} candidates, {social_hits} social")
