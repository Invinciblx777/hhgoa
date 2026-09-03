"""M6 - orchestrator CLI for the face identification and verification pipeline.

Sequences the existing modules end to end:

    M2  src.face_embed.detect_and_encode   detect + encode the query face
    M3  src.image_search.search_by_image   reverse image search for candidates
    M4  src.matcher.match_candidates       re-encode + cosine-match each candidate
    M5  src.chain.build_record / anchor_record / verify_record / recompute_and_compare

No pipeline module is modified here. This file only calls their public functions
and formats the output so it stays legible on a screen recording.

    python pipeline.py --image samples/query.jpg
    python pipeline.py --verify 0x<record_hash>
    python pipeline.py --image samples/query.jpg --tamper-demo
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import warnings

# InsightFace prints its model-load table to stdout and onnxruntime / numpy emit
# FutureWarnings at import time. Both are noise on a recording. Silence the
# warnings for the whole run; the import-time chatter is captured in _load_quietly.
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)
os.environ.setdefault("ORT_LOG_SEVERITY_LEVEL", "3")

EXPLORER_TX = "https://amoy.polygonscan.com/tx/{}"
EXPLORER_ADDRESS = "https://amoy.polygonscan.com/address/{}"
BANNER_WIDTH = 64
TOTAL_STAGES = 5


def banner(step: int, title: str) -> None:
    bar = "=" * BANNER_WIDTH
    print(f"\n{bar}\n  [{step}/{TOTAL_STAGES}]  {title}\n{bar}")


def section(title: str) -> None:
    bar = "=" * BANNER_WIDTH
    print(f"\n{bar}\n  {title}\n{bar}")


def verdict_block(word: str, detail: str) -> None:
    """Print the final VERIFIED / TAMPERED result as a hard-to-miss band."""
    bar = "#" * BANNER_WIDTH
    inner = BANNER_WIDTH - 4
    print()
    print(bar)
    print("##" + " " * inner + "##")
    print("##" + f"  {word}".ljust(inner) + "##")
    print("##" + " " * inner + "##")
    print(bar)
    print(f"  {detail}")


def canonical_hash(payload: dict) -> str:
    """0x SHA-256 over the payload's canonical JSON, per PROJECT_SPEC M5.

    Used only to display the hash on screen (genuine and tampered). The verdict
    itself always comes from src.chain.recompute_and_compare, which owns the
    canonical form.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "0x" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pipeline.py",
        description=(
            "Identify a face in an image against publicly indexed images and "
            "anchor the verified result on Polygon Amoy."
        ),
    )
    parser.add_argument(
        "--image",
        help="Path to the query image to run through the pipeline.",
    )
    parser.add_argument(
        "--verify",
        metavar="RECORD_HASH",
        help="Verify an existing 0x-prefixed record hash against the on-chain record.",
    )
    parser.add_argument(
        "--tamper-demo",
        action="store_true",
        help="After anchoring, mutate one payload field to show the hash no longer matches.",
    )
    return parser


@contextlib.contextmanager
def _muffled():
    """Swallow a stage's stderr chatter, replaying it only if the stage raises.

    M3 and M4 narrate every candidate to stderr; that is ~80 lines of noise on a
    screen recording. Kept in a buffer so a genuine stage failure still prints.
    """
    sink = io.StringIO()
    try:
        with contextlib.redirect_stderr(sink):
            yield
    except BaseException:
        sys.stderr.write(sink.getvalue())
        raise


def _load_quietly(chain_only: bool) -> dict:
    """Import the pipeline modules with InsightFace's model-load output captured."""
    sink = io.StringIO()
    try:
        with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(
            sink
        ), warnings.catch_warnings():
            warnings.simplefilter("ignore")
            from src import chain

            bundle = {"chain": chain}
            if not chain_only:
                from src import face_embed, image_search, matcher

                bundle.update(
                    face_embed=face_embed,
                    image_search=image_search,
                    matcher=matcher,
                )
    except BaseException:
        # Surface whatever the import managed to say before it failed.
        sys.stdout.write(sink.getvalue())
        raise
    return bundle


def _missing(keys: tuple[str, ...]) -> list[str]:
    return [key for key in keys if not os.getenv(key)]


def run_verify(record_hash: str) -> None:
    from src import config  # noqa: F401  - importing loads .env

    absent = _missing(("AMOY_RPC_URL", "CONTRACT_ADDRESS"))
    if absent:
        raise SystemExit(
            f"missing .env keys required to read the chain: {', '.join(absent)}"
        )

    rh = record_hash if record_hash.lower().startswith("0x") else "0x" + record_hash
    chain = _load_quietly(chain_only=True)["chain"]

    section("VERIFY ON-CHAIN RECORD")
    print(f"  record hash : {rh}")
    print("  reading FaceAnchor.verify() from Polygon Amoy ...")
    record = chain.verify_record(rh)
    print(f"  exists      : {record.exists}")
    print(f"  timestamp   : {record.timestamp}")
    print(f"  uri         : {record.uri}")
    print(f"  submitter   : {record.submitter}")
    print("  explorer    :")
    print(EXPLORER_ADDRESS.format(os.getenv("CONTRACT_ADDRESS")))

    if record.exists:
        verdict_block(
            "VERIFIED",
            "record hash is anchored on-chain (re-run with --image to re-hash the payload)",
        )
    else:
        verdict_block("NOT FOUND", "no record with this hash exists on-chain")


def run_identify(image_path: str, tamper_demo: bool) -> None:
    from src import config  # noqa: F401  - importing loads .env

    absent = _missing(("SERPAPI_KEY", "IMGBB_KEY"))
    if absent:
        raise SystemExit(
            f"missing .env keys required for reverse image search: {', '.join(absent)}\n"
            "copy .env.example to .env and fill them in."
        )
    if not os.path.isfile(image_path):
        raise SystemExit(f"image not found: {image_path}")

    print("loading InsightFace buffalo_l (CPU) ...", flush=True)
    bundle = _load_quietly(chain_only=False)
    detect_and_encode = bundle["face_embed"].detect_and_encode
    search_by_image = bundle["image_search"].search_by_image
    match_candidates = bundle["matcher"].match_candidates
    threshold = bundle["matcher"].DEFAULT_THRESHOLD
    chain = bundle["chain"]

    # ------------------------------------------------------------------ [1/5]
    banner(1, "FACE DETECTION")
    enc = detect_and_encode(image_path)
    if enc is None:
        raise SystemExit("no face detected in the query image")
    x1, y1, x2, y2 = enc.bbox
    print(f"  image        : {image_path}")
    print(f"  image sha256 : {enc.image_sha256}")
    print(f"  face bbox    : ({x1}, {y1}, {x2}, {y2})   w={x2 - x1} h={y2 - y1}")
    print(f"  det_score    : {enc.det_score:.4f}")
    print(f"  embedding    : {len(enc.embedding)}-d, L2-normalized")

    # ------------------------------------------------------------------ [2/5]
    banner(2, "REVERSE IMAGE SEARCH")
    with _muffled():
        candidates = search_by_image(image_path)
    social = sum(1 for c in candidates if c.is_social)
    print(f"  candidates   : {len(candidates)}")
    print(f"  social       : {social}")
    for index, candidate in enumerate(candidates, start=1):
        tag = "  (social)" if candidate.is_social else ""
        print(f"    {index:>2}. {candidate.domain}{tag}")

    # ------------------------------------------------------------------ [3/5]
    banner(3, "CANDIDATE MATCHING")
    print(f"  threshold    : {threshold:.2f}  (ArcFace cosine)")
    print("  downloading + re-encoding every candidate ...\n")
    with _muffled():
        matches = match_candidates(enc, candidates, threshold)
    print(f"  {'rank':>4}  {'similarity':>10}  {'result':<6}  domain")
    print(f"  {'-' * 4}  {'-' * 10}  {'-' * 6}  {'-' * 30}")
    for rank, match in enumerate(matches, start=1):
        verdict = "PASS" if match.passed else "FAIL"
        print(
            f"  {rank:>4}  {match.similarity:>10.4f}  {verdict:<6}  {match.candidate.domain}"
        )
    passing = [m for m in matches if m.passed]
    print(
        f"\n  {len(matches)} encoded / {len(candidates)} candidates, "
        f"{len(passing)} passed at {threshold:.2f}"
    )
    if not passing:
        raise SystemExit(
            "no candidate cleared the similarity threshold - nothing to anchor"
        )
    top = passing[0]
    print(f"  top match    : {top.candidate.domain}  similarity {top.similarity:.4f}")
    print(f"  source url   : {top.candidate.source_url}")

    # ------------------------------------------------------------------ [4/5]
    banner(4, "ON-CHAIN ANCHOR")
    record_hash, payload = chain.build_record(enc, top)
    print(f"  record hash  : {record_hash}")
    print("  payload      :")
    for row in json.dumps(payload, indent=2, sort_keys=True).splitlines():
        print(f"    {row}")

    absent = _missing(("AMOY_RPC_URL", "PRIVATE_KEY", "CONTRACT_ADDRESS"))
    if absent:
        print(f"\n  ANCHOR SKIPPED - missing .env keys: {', '.join(absent)}")
        print("  Deploy contracts/FaceAnchor.sol to Polygon Amoy (Remix + MetaMask),")
        print("  put PRIVATE_KEY and CONTRACT_ADDRESS in .env, then rerun to anchor.")
        verdict_block(
            "INCOMPLETE",
            "M2-M4 ran; on-chain anchor + verification pending .env keys",
        )
        return

    existing = chain.verify_record(record_hash)
    if existing.exists:
        print(
            f"\n  already anchored (ts {existing.timestamp}) - reusing the on-chain record"
        )
        tx_hash = None
    else:
        print("\n  submitting anchor() to Polygon Amoy ...")
        tx_hash = chain.anchor_record(record_hash, payload["source_url"])
    if tx_hash:
        print(f"  tx hash      : {tx_hash}")
        print("  explorer     :")
        print(EXPLORER_TX.format(tx_hash))

    # ------------------------------------------------------------------ [5/5]
    banner(5, "VERIFICATION")
    record = chain.verify_record(record_hash)
    genuine_match = record.exists and chain.recompute_and_compare(payload, record_hash)
    print(f"  on-chain     : exists={record.exists}  submitter={record.submitter}")
    print(f"  timestamp    : {record.timestamp}")
    print(f"  uri          : {record.uri}")
    print(f"  on-chain hash: {record_hash}")
    print(f"  recomputed   : {canonical_hash(payload)}")
    print(f"  hashes match : {genuine_match}")

    if not tamper_demo:
        if genuine_match:
            verdict_block(
                "VERIFIED", "on-chain record matches the recomputed payload hash"
            )
        else:
            verdict_block(
                "NOT VERIFIED",
                "on-chain record does not match the recomputed payload hash",
            )
        return

    # ---------------------------------------------------------- tamper demo
    section("TAMPER DEMONSTRATION")
    tampered = dict(payload)
    before = tampered["similarity"]
    after = round(before - 0.01, 6)
    tampered["similarity"] = after
    still_matches = chain.recompute_and_compare(tampered, record_hash)
    print(f"  mutated field : similarity  {before}  ->  {after}")
    print(f"  on-chain hash : {record_hash}")
    print(f"  tampered hash : {canonical_hash(tampered)}")
    print(f"  hashes match  : {still_matches}")
    if still_matches:
        verdict_block(
            "TAMPER NOT DETECTED",
            "mutated payload still hashed to the on-chain record",
        )
    else:
        verdict_block(
            "TAMPERED",
            "one changed field breaks the hash - on-chain record no longer matches",
        )


def main() -> None:
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except AttributeError:
        pass

    parser = build_parser()
    args = parser.parse_args()

    if args.image and args.verify:
        parser.error("pass --image or --verify, not both")
    if args.tamper_demo and not args.image:
        parser.error("--tamper-demo requires --image")
    if not args.image and not args.verify:
        parser.error("nothing to do: pass --image PATH or --verify 0xHASH")

    if args.verify:
        run_verify(args.verify)
    else:
        run_identify(args.image, args.tamper_demo)


if __name__ == "__main__":
    main()
