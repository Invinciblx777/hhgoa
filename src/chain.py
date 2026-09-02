"""M5 — canonical record hashing and tamper-evident anchoring on Polygon Amoy."""

from src.types import FaceEncoding, MatchResult, OnChainRecord


def build_record(query: FaceEncoding, match: MatchResult) -> tuple[str, dict]:
    """Build the canonical record payload and its hash for a verified match.

    The payload carries query_image_sha256, embedding_sha256, source_url,
    image_url, matched_image_sha256, similarity (6 decimal places) and
    timestamp_utc. It is serialized as canonical JSON via
    json.dumps(payload, sort_keys=True, separators=(",", ":")) so that the same
    payload always produces the same hash. Returns the "0x"-prefixed SHA-256 of
    that canonical form together with the payload dict.
    """
    raise NotImplementedError


def anchor_record(record_hash: str, uri: str) -> str:
    """Anchor a record hash on the FaceAnchor contract and return the tx hash."""
    raise NotImplementedError


def verify_record(record_hash: str) -> OnChainRecord:
    """Read a record hash back from the contract and return what is stored on-chain."""
    raise NotImplementedError


def recompute_and_compare(payload: dict, record_hash: str) -> bool:
    """Recompute the canonical hash of a payload and report whether it still matches."""
    raise NotImplementedError
