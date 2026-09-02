"""M3 — reverse image search against Google Lens through SerpApi."""

from src.types import SearchCandidate


def upload_temp_image(image_path: str) -> str:
    """Upload a local image to imgbb and return its public URL.

    Google Lens needs a publicly reachable image URL, so the query image is
    hosted temporarily before the search call is made.
    """
    raise NotImplementedError


def search_by_image(image_path: str, max_results: int = 20) -> list[SearchCandidate]:
    """Reverse image search the given image and return the candidate pages found.

    Makes a genuine live SerpApi call; results are never hardcoded or cached.
    Candidates from instagram, x, twitter, linkedin, facebook, reddit, tiktok,
    youtube and github are flagged with is_social=True and are returned first,
    followed by the remaining candidates. API errors are raised, never swallowed
    into an empty list.
    """
    raise NotImplementedError
