"""M5 — canonical record hashing and tamper-evident anchoring on Polygon Amoy.

The record payload stays off-chain; only its SHA-256 is anchored. Hashing is
deterministic: the same payload serializes to the same canonical JSON and
therefore the same hash on every run, so a record read back from the chain can
be re-derived from the payload and compared byte for byte.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from src.types import FaceEncoding, MatchResult, OnChainRecord

_ABI_PATH = Path(__file__).resolve().parent.parent / "contracts" / "FaceAnchor.abi.json"
_EXPLORER_TX = "https://amoy.polygonscan.com/tx/{}"


def _canonical_hash(payload: dict) -> str:
    """0x-prefixed SHA-256 over the UTF-8 bytes of the payload's canonical JSON."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_record(query: FaceEncoding, match: MatchResult) -> tuple[str, dict]:
    """Build the canonical record payload and its hash for a verified match.

    The payload carries query_image_sha256, embedding_sha256, source_url,
    image_url, matched_image_sha256, similarity (6 decimal places) and
    timestamp_utc. It is serialized as canonical JSON via
    json.dumps(payload, sort_keys=True, separators=(",", ":")) so that the same
    payload always produces the same hash. Returns the "0x"-prefixed SHA-256 of
    that canonical form together with the payload dict.
    """
    embedding_json = json.dumps(query.embedding, separators=(",", ":"))
    payload = {
        "query_image_sha256": query.image_sha256,
        "embedding_sha256": hashlib.sha256(embedding_json.encode("utf-8")).hexdigest(),
        "source_url": match.candidate.source_url,
        "image_url": match.candidate.image_url,
        "matched_image_sha256": match.matched_image_sha256,
        "similarity": round(match.similarity, 6),
        "timestamp_utc": datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z"),
    }
    return _canonical_hash(payload), payload


def _load_abi() -> list:
    with open(_ABI_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _connect():
    """Return a Web3 client for the Amoy RPC, with the POA middleware installed."""
    from web3 import Web3

    from src.config import AMOY_RPC_URL

    web3 = Web3(Web3.HTTPProvider(AMOY_RPC_URL, request_kwargs={"timeout": 60}))
    try:
        from web3.middleware import ExtraDataToPOAMiddleware

        web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
    except ImportError:  # middleware name drift across web3 versions
        pass
    if not web3.is_connected():
        raise RuntimeError(f"Cannot reach Amoy RPC at {AMOY_RPC_URL}")
    return web3


def _contract(web3):
    from src.config import CONTRACT_ADDRESS

    return web3.eth.contract(
        address=web3.to_checksum_address(CONTRACT_ADDRESS), abi=_load_abi()
    )


def _record_bytes32(record_hash: str) -> bytes:
    from web3 import Web3

    raw = Web3.to_bytes(hexstr=record_hash)
    if len(raw) != 32:
        raise ValueError(f"record_hash must be 32 bytes, got {len(raw)}")
    return raw


def anchor_record(record_hash: str, uri: str) -> str:
    """Anchor a record hash on the FaceAnchor contract and return the tx hash.

    The transaction is built and signed locally with the key from config and
    submitted as a raw transaction; the private key is never logged. Reverts
    (including a duplicate record hash) propagate.
    """
    from src.config import PRIVATE_KEY

    web3 = _connect()
    contract = _contract(web3)
    account = web3.eth.account.from_key(PRIVATE_KEY)  # never logged

    priority_fee = web3.eth.max_priority_fee
    base_fee = web3.eth.get_block("latest")["baseFeePerGas"]
    tx = contract.functions.anchor(_record_bytes32(record_hash), uri).build_transaction(
        {
            "from": account.address,
            "nonce": web3.eth.get_transaction_count(account.address),
            "chainId": web3.eth.chain_id,
            "maxPriorityFeePerGas": priority_fee,
            "maxFeePerGas": base_fee * 2 + priority_fee,
        }
    )
    signed = account.sign_transaction(tx)
    tx_hash = web3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = web3.eth.wait_for_transaction_receipt(tx_hash, timeout=240)
    if receipt.status != 1:
        raise RuntimeError(f"anchor transaction reverted: {web3.to_hex(tx_hash)}")
    return web3.to_hex(tx_hash)


def verify_record(record_hash: str) -> OnChainRecord:
    """Read a record hash back from the contract and return what is stored on-chain."""
    web3 = _connect()
    contract = _contract(web3)
    exists, timestamp, uri, submitter = contract.functions.verify(
        _record_bytes32(record_hash)
    ).call()
    return OnChainRecord(
        exists=bool(exists),
        timestamp=int(timestamp),
        uri=uri,
        submitter=submitter,
    )


def recompute_and_compare(payload: dict, record_hash: str) -> bool:
    """Recompute the canonical hash of a payload and report whether it still matches."""
    return _canonical_hash(payload).lower() == record_hash.lower()


def _selftest_offline() -> None:
    """Determinism and tamper detection, no network. Determinism is the point."""
    from src.types import SearchCandidate

    query = FaceEncoding([0.1, -0.2, 0.3], (0, 0, 10, 10), 0.9, "a" * 64, "q.jpg")
    candidate = SearchCandidate(
        "https://example.test/page", "https://example.test/i.jpg", "t", "example.test", False
    )
    match = MatchResult(candidate, 0.53774212, "b" * 64, True)

    record_hash, payload = build_record(query, match)
    assert _canonical_hash(payload) == record_hash
    assert recompute_and_compare(payload, record_hash), "hash not reproducible from payload"

    tampered = dict(payload)
    tampered["similarity"] = round(payload["similarity"] - 0.01, 6)
    assert not recompute_and_compare(tampered, record_hash), "tamper not detected"
    print("[M5] offline selftest OK — deterministic hash, tamper detected")


if __name__ == "__main__":
    from src.config import missing_keys
    from src.face_embed import detect_and_encode
    from src.image_search import search_by_image
    from src.matcher import match_candidates

    SAMPLE = "samples/query.jpg"

    _selftest_offline()

    print(f"\n[M5] M2 encode {SAMPLE}")
    query_encoding = detect_and_encode(SAMPLE)
    if query_encoding is None:
        raise SystemExit("[M5] no face detected in query image")

    print("[M5] M3 reverse image search")
    found = search_by_image(SAMPLE)

    print(f"[M5] M4 match {len(found)} candidates")
    matches = match_candidates(query_encoding, found)
    passing = [m for m in matches if m.passed]
    if not passing:
        raise SystemExit("[M5] no passing match to anchor")
    top = passing[0]
    print(f"[M5] top match: {top.candidate.domain} at similarity {top.similarity:.4f}")

    record_hash, payload = build_record(query_encoding, top)
    print(f"\n[M5] record hash : {record_hash}")
    print("[M5] payload     :")
    print(json.dumps(payload, indent=2, sort_keys=True))

    absent = missing_keys()
    if absent:
        raise SystemExit(
            f"\n[M5] chain keys missing: {', '.join(absent)}. "
            "Deploy contracts/FaceAnchor.sol to Polygon Amoy via Remix, put "
            "PRIVATE_KEY and CONTRACT_ADDRESS in .env, then rerun."
        )

    uri = payload["source_url"]
    already = verify_record(record_hash)
    if already.exists:
        print(f"\n[M5] hash already anchored (ts {already.timestamp}); reusing it")
        tx_hash = "(previously anchored)"
    else:
        print("\n[M5] anchoring on Amoy ...")
        tx_hash = anchor_record(record_hash, uri)
    print(f"[M5] tx hash     : {tx_hash}")
    if tx_hash.startswith("0x"):
        print(f"[M5] explorer    : {_EXPLORER_TX.format(tx_hash)}")

    record = verify_record(record_hash)
    verified = record.exists and recompute_and_compare(payload, record_hash)
    print(f"[M5] on-chain    : exists={record.exists} submitter={record.submitter}")
    print("VERIFIED" if verified else "NOT VERIFIED")

    tampered_payload = dict(payload)
    tampered_payload["similarity"] = round(payload["similarity"] - 0.01, 6)
    still_matches = recompute_and_compare(tampered_payload, record_hash)
    print("TAMPERED" if not still_matches else "TAMPER NOT DETECTED")
