# PROJECT_SPEC.md

**Project:** HH Goa 2026 — Task 3: Face Identification & Blockchain Verification
**Deadline:** Sept 7 2026, 23:59 IST. No resubmissions.
**Platform:** Windows 11 native, Python 3.11, venv at `.venv`

---

## RULES FOR CLAUDE CODE

1. Read this file before every task.
2. **Do not change any public interface in this document unless explicitly instructed.**
3. Build one module at a time. Each module must run standalone via its `__main__` block before the next module is written.
4. No frontend. No web server. No Docker. CLI only.
5. Every module gets a `if __name__ == "__main__":` smoke test that runs on real input.
6. Never commit `.env`. Never print private keys or full API keys to stdout.

---

## SCOPE CONSTRAINT (non-negotiable, goes in README)

The pipeline is demonstrated on **consented input only** — the operator's own face, or a
public figure whose images are already publicly indexed.

Rationale, stated plainly in the README:
- Face-to-identity search against non-consenting subjects is a surveillance capability with
  real misuse potential (stalking, doxxing, deanonymization).
- This build is a demonstration of the *pipeline architecture* — detection, retrieval,
  verification, tamper-evident anchoring — not a general person-lookup tool.
- Reverse image search retrieves *indexed images*, not arbitrary faces. The system cannot
  and does not claim to identify strangers from candid photos.

Do not add batch/bulk input modes. Single image in, single record out.

---

## PIPELINE

```
input image
  → M2  detect + encode face            → FaceEncoding
  → M3  reverse image search            → [SearchCandidate]
  → M4  re-encode each candidate,
        cosine-match vs query           → [MatchResult]
  → M5  canonical hash + anchor on-chain → tx hash
  → M5  read back + recompute + compare  → VERIFIED / TAMPERED
```

**M4 is the differentiator.** Most submissions stop at M3 and call reverse image search
"face identification." It isn't. M4 downloads the candidate image, runs face encoding on it,
and requires a cosine similarity pass before the result is accepted. That closes the loop.

---

## REPO LAYOUT

```
hhgoa/
├── PROJECT_SPEC.md
├── README.md
├── .env                  # gitignored
├── .env.example
├── .gitignore
├── requirements.txt
├── contracts/
│   └── FaceAnchor.sol
├── src/
│   ├── __init__.py
│   ├── config.py         # loads .env, no logic
│   ├── face_embed.py     # M2
│   ├── image_search.py   # M3
│   ├── matcher.py        # M4
│   └── chain.py          # M5
├── pipeline.py           # M6 orchestrator CLI
└── samples/
    └── query.jpg
```

---

## FROZEN INTERFACES

### Shared types (`src/types.py`)

```python
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
```

### M1 — `contracts/FaceAnchor.sol`

Solidity ^0.8.20. Deployed to **Polygon Amoy** via Remix + MetaMask.

```solidity
event Anchored(bytes32 indexed recordHash, address indexed submitter, uint256 timestamp, string uri);

function anchor(bytes32 recordHash, string calldata uri) external;
function verify(bytes32 recordHash) external view
    returns (bool exists, uint256 timestamp, string memory uri, address submitter);
```

- Reject duplicate `recordHash` with a revert. Duplicates would undermine tamper-evidence.
- No owner, no upgradeability, no access control. Keep it under 40 lines.

### M2 — `src/face_embed.py`

InsightFace `buffalo_l`, `onnxruntime` **CPU** provider. Do not use `onnxruntime-gpu`.

```python
def detect_and_encode(image_path: str) -> FaceEncoding | None
    # None if no face detected
    # if multiple faces, take the largest bbox
    # embedding must be L2-normalized before return

def sha256_file(path: str) -> str
```

### M3 — `src/image_search.py`

SerpApi Google Lens. Query image must be publicly reachable → upload to imgbb first.

```python
def upload_temp_image(image_path: str) -> str
    # returns public URL

def search_by_image(image_path: str, max_results: int = 20) -> list[SearchCandidate]
    # genuine live API call — NO hardcoded or cached results, ever
    # sets is_social=True for: instagram, x, twitter, linkedin, facebook,
    #                          reddit, tiktok, youtube, github
    # returns social candidates first, then the rest
```

Fail loudly on API error. Never silently return an empty list.

### M4 — `src/matcher.py`

```python
DEFAULT_THRESHOLD = 0.50    # ArcFace cosine; calibrate and record the value in README

def match_candidates(
    query: FaceEncoding,
    candidates: list[SearchCandidate],
    threshold: float = DEFAULT_THRESHOLD,
) -> list[MatchResult]
    # downloads each candidate image, runs M2 encoding on it
    # skips candidates with no detectable face (log, don't crash)
    # returns ALL results sorted by similarity desc, passed flag set per threshold
```

### M5 — `src/chain.py`

```python
def build_record(query: FaceEncoding, match: MatchResult) -> tuple[str, dict]
    # payload dict:
    #   query_image_sha256, embedding_sha256, source_url, image_url,
    #   matched_image_sha256, similarity (6dp), timestamp_utc
    # canonical JSON: json.dumps(payload, sort_keys=True, separators=(",", ":"))
    # returns ("0x" + sha256(canonical).hexdigest(), payload)

def anchor_record(record_hash: str, uri: str) -> str      # returns tx hash
def verify_record(record_hash: str) -> OnChainRecord
def recompute_and_compare(payload: dict, record_hash: str) -> bool
```

Hashing must be deterministic — same payload, same hash, every run. Canonical JSON is not
optional; key order changes the hash.

### M6 — `pipeline.py`

```
python pipeline.py --image samples/query.jpg
python pipeline.py --verify 0x<record_hash>
python pipeline.py --image samples/query.jpg --tamper-demo
```

Console output must be legible on a screen recording. Clear stage banners, similarity score
printed as a number, tx hash printed in full, Amoy explorer URL printed as a clickable line.

`--tamper-demo`: mutate one field of the payload, recompute, show the hash no longer matches
the on-chain record. Prints `TAMPERED`.

---

## ENV (`.env.example`)

```
SERPAPI_KEY=
IMGBB_KEY=
AMOY_RPC_URL=https://rpc-amoy.polygon.technology
PRIVATE_KEY=
CONTRACT_ADDRESS=
```

---

## README REQUIREMENTS (scored — do not phone in)

1. What it does + the pipeline diagram above
2. Setup + run instructions, verbatim commands
3. Which blockchain and why (Polygon Amoy — public testnet, free, real explorer)
4. **Known limitations:**
   - Retrieves indexed images, not arbitrary faces. Cannot identify strangers.
   - Threshold sensitivity; false positive/negative behavior observed in testing
   - Depends on third-party search index coverage and availability
   - Single-face assumption
5. **Scope and misuse** — the constraint section above, in your own words
6. Deployed contract address + explorer link
7. Screen recording link
