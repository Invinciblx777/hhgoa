"""Shared dataclasses passed between pipeline modules."""

from dataclasses import dataclass


@dataclass
class FaceEncoding:
    embedding: list[float]      # 512-d, L2-normalized
    bbox: tuple[int, int, int, int]
    det_score: float
    image_sha256: str
    source_path: str


@dataclass
class SearchCandidate:
    source_url: str             # page the image was found on
    image_url: str              # direct image URL
    title: str
    domain: str
    is_social: bool
    thumbnail_url: str = ""     # Lens-hosted thumbnail, used as a download fallback


@dataclass
class MatchResult:
    candidate: SearchCandidate
    similarity: float           # cosine, -1.0 to 1.0
    matched_image_sha256: str
    passed: bool


@dataclass
class OnChainRecord:
    exists: bool
    timestamp: int
    uri: str
    submitter: str
