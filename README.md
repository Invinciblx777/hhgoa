# HH Goa 2026 — Task 3: Face Identification & Blockchain Verification

A single-image face identification pipeline with a tamper-evident on-chain record.
One image goes in; one verified, hash-anchored record comes out.

The pipeline does not stop at reverse image search. Every candidate returned by the
search index is downloaded, re-encoded with the same face model as the query, and must
clear a cosine-similarity threshold before it is accepted as a match. The accepted match
is then serialized to canonical JSON, hashed, and anchored on Polygon Amoy, so the record
can later be re-derived and compared against the chain to prove it was not altered.

## What it does

```
input image
  → M2  detect + encode face             → FaceEncoding
  → M3  reverse image search             → [SearchCandidate]
  → M4  re-encode each candidate,
        cosine-match vs query            → [MatchResult]
  → M5  canonical hash + anchor on-chain → tx hash
  → M5  read back + recompute + compare  → VERIFIED / TAMPERED
```

| Stage | Module | Responsibility |
|-------|--------|----------------|
| M1 | `contracts/FaceAnchor.sol` | Solidity ^0.8.20 anchor contract. Stores `recordHash → (timestamp, uri, submitter)`. Reverts on a duplicate hash. |
| M2 | `src/face_embed.py` | InsightFace `buffalo_l` on `onnxruntime` CPU. Detects the largest face, returns a 512-d L2-normalized embedding plus the image SHA-256. |
| M3 | `src/image_search.py` | Uploads the query to imgbb for a public URL, then runs a live SerpApi Google Lens search. Social-media domains are flagged and returned first. |
| M4 | `src/matcher.py` | Downloads each candidate image, re-runs M2 on it, and computes cosine similarity against the query embedding. Sets `passed` per threshold. |
| M5 | `src/chain.py` | Builds the canonical payload, hashes it, anchors it on Polygon Amoy, then reads the record back and recomputes the hash to confirm it matches. |
| M6 | `pipeline.py` | CLI orchestrator that runs the five stages and prints the result. |

M4 is the part that makes this face identification rather than image lookup. Reverse image
search alone tells you where a picture appears; it does not confirm the face in the result
is the face in the query. M4 closes that loop by re-encoding the retrieved image and
requiring a similarity pass.

## Setup

Python 3.11. Windows 11 native (the pipeline is platform-agnostic; the commands below are
what was used in testing).

```
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

On macOS or Linux, substitute `source .venv/bin/activate` and `cp .env.example .env`.

Fill in `.env`:

| Key | Where it comes from |
|-----|---------------------|
| `SERPAPI_KEY` | serpapi.com — Google Lens engine |
| `IMGBB_KEY` | api.imgbb.com — temporary public hosting for the query image |
| `AMOY_RPC_URL` | Polygon Amoy JSON-RPC endpoint (see RPC endpoint note below) |
| `PRIVATE_KEY` | Funded Amoy testnet account. Get test MATIC from a Polygon Amoy faucet. |
| `CONTRACT_ADDRESS` | Address of your deployed `FaceAnchor` contract, or the deployed one below |

`.env` is gitignored and must stay that way. The first run downloads the InsightFace
`buffalo_l` model pack (~300 MB) into `~/.insightface`.

### RPC endpoint

**`https://rpc-amoy.polygon.technology` was unreachable throughout testing.** It is the
endpoint most Amoy documentation points at, and it fails to connect. Use:

```
AMOY_RPC_URL=https://polygon-amoy-bor-rpc.publicnode.com
```

This is the endpoint every live run in this README was executed against, and it is the
default in `.env.example`. If you clone this repo and the chain stage hangs or errors on
connect, this is why.

### Deploying your own contract

`contracts/FaceAnchor.sol` was deployed via Remix with MetaMask on the Polygon Amoy
network. Compile with Solidity ^0.8.20, deploy, and put the resulting address in
`CONTRACT_ADDRESS`. There is no constructor argument, no owner, and no access control —
anyone can anchor, and no one can modify or delete an anchored record.

## Run

Full pipeline on a query image:

```
python pipeline.py --image samples/query.jpg
```

Verify a previously anchored record hash:

```
python pipeline.py --verify 0x<record_hash>
```

Anchor, then demonstrate tamper detection by mutating one payload field and recomputing:

```
python pipeline.py --image samples/query.jpg --tamper-demo
```

The tamper demo prints `TAMPERED` — the mutated payload hashes to a different value, which
does not exist on-chain, so the record cannot be silently rewritten.

### Live run

Executed against the deployed contract on Polygon Amoy:

- 20/20 search candidates downloaded and successfully encoded
- Strongest match: **1.0000** cosine similarity
- Weakest match: **0.6326**
- All 20 passed the 0.40 threshold
- Anchored, read back, recomputed — **VERIFIED**, the on-chain hash matched the recomputed
  payload hash

## Which blockchain and why

**Polygon Amoy**, the public Polygon PoS testnet.

- **Public and independently verifiable.** Anchored records are readable by anyone through
  a public explorer, without access to this repo or its keys. A private or local chain
  would make the tamper-evidence claim unfalsifiable by a third party.
- **Free.** Gas is paid in testnet MATIC from a faucet, so a demonstration costs nothing
  and does not depend on the operator funding a mainnet wallet.
- **Real explorer.** Amoy PolygonScan renders the transaction, the event log, and the
  contract state, so the anchor can be inspected outside the tool that wrote it.
- **EVM, well-supported tooling.** Solidity, Remix, MetaMask, and `web3.py` work without
  adaptation, and the same contract deploys unchanged to Polygon mainnet if this were ever
  taken past demonstration.

The chain is used purely as a tamper-evident timestamp. No image, embedding, or personal
data is written on-chain — only a SHA-256 hash of the canonical record, plus a URI string.
The hash is not reversible into the underlying data, and the payload must be supplied
off-chain to verify against it.

## Known limitations

**It retrieves indexed images, not arbitrary faces.** This is the fundamental limit, and it
is a property of reverse image search, not a bug in this implementation. Google Lens
returns pages where a visually similar image already appears in the index. If a person's
face has never been published and indexed, there is nothing to retrieve, and the pipeline
returns no candidates. The system cannot identify a stranger from a candid photo, and it
does not claim to. A null result means "not found in the index" — never "this person does
not exist" or "this person is not who they say they are."

**Threshold sensitivity.** The accept/reject decision is a single cosine-similarity cutoff,
currently 0.40 (see Threshold calibration below). Every score is a continuum, and the
threshold draws an arbitrary line across it. Lower it and degraded true matches survive
JPEG recompression, pose, and lighting, at rising risk of false positives. Raise it and
false positives fall while genuine but degraded matches get rejected. The calibration
below found a clean separation gap on the data tested, but that gap was measured on a small
sample from one search — it bounds observed behaviour, not worst-case behaviour. Expect the
classes to overlap on harder input: heavy occlusion, extreme pose, low resolution, age
gap between query and indexed image, or near-identical relatives.

**Dependence on third-party index coverage and availability.** Retrieval quality is
entirely a function of what SerpApi's Google Lens results contain on the day it is queried.
Index coverage varies by person, region, and platform, and it changes without notice. The
pipeline is also subject to SerpApi rate limits, quota exhaustion, and outages, and to
imgbb availability for hosting the query image. When the search stage fails it fails
loudly rather than returning an empty candidate list, because an empty list is
indistinguishable from a genuine no-match and would be a misleading result.

**Single-face assumption.** M2 takes the largest detected bounding box and discards the
rest. For a query image with several faces, "largest" is a proxy for "the subject," and it
is often wrong — a bystander closer to the camera wins over the intended subject. The same
rule applies when re-encoding candidates, so a group photo returned by the search may be
scored on a face that is not the one being matched. Use single-subject images.

**Instagram and Facebook direct image URLs serve HTML login walls.** The `image_url` a
search result gives for a post on those platforms does not return image bytes to an
unauthenticated client. It returns an HTML login page, with a 200 status and a content
type that is not an image. Left unhandled, this either crashes the decoder or silently
scores a non-image as a failed match. `src/matcher.py` detects the non-image response and
falls back to the Lens thumbnail URL, which is served directly and does decode. That
fallback is what made 20/20 candidates encodable in the live run. The cost is that a
thumbnail is lower resolution than the original, which pushes similarity scores down
slightly — one more reason the threshold is not set tight against the true-match floor.

## Threshold calibration

`src/matcher.py` `DEFAULT_THRESHOLD` is **0.40** (ArcFace / InsightFace `buffalo_l`
cosine similarity), lowered from the spec's starting value of 0.50.

Calibration data:

| Set | n | Score range | Bound |
|-----|---|-------------|-------|
| True matches (same person, verified via M4 re-encode) | 11 | 0.5120 – high | **floor 0.5120** |
| Negative control (unrelated faces) | 11 | low – -0.0257 | **ceiling -0.0257** |

- **Separation gap:** 0.5120 − (−0.0257) = **0.5377**. No score from either set landed
  inside that band — the classes are cleanly linearly separable on this data.
- **Why 0.40 over 0.50:** 0.50 sits only 0.0120 below the observed true-match floor
  (0.5120). One genuine match degraded by JPEG recompression, pose, or lighting can
  drop that far and be wrongly rejected. 0.40 sits well inside the empty gap — 0.1120
  of headroom below the true-match floor for degraded positives, and 0.4257 above the
  negative-control ceiling. Because nothing scored between −0.0257 and 0.5120, moving
  the line down to 0.40 buys tolerance for weak positives at no observed cost in false
  positives.

The negative control was run on unrelated faces pulled from a prior Google Lens search,
not a formal benchmark. It bounds behaviour on the data seen in testing; it is not a
statistical guarantee.
## Scope and misuse

This pipeline is demonstrated on consented input only: the operator's own face, or a public
figure whose images are already publicly indexed. Nothing in this repository was run
against a private individual, and it should not be.

Face-to-identity search against non-consenting subjects is a surveillance capability, and
it should be described as one. Pointed at a stranger it becomes an instrument for stalking,
doxxing, and deanonymization — turning a photograph taken in public into a name, an
employer, and a home city. Those harms fall hardest on people who most rely on being
unremarkable in public: domestic-abuse survivors, protesters, journalists' sources, anyone
whose safety depends on not being trivially linkable to a face. The capability does not
become safe because the components are off-the-shelf; if anything, the fact that a working
version can be assembled from a public face model and a search API is the point worth
taking seriously.

What is being demonstrated here is the *pipeline architecture* — detection, retrieval,
verification, tamper-evident anchoring — and specifically the verification step that most
implementations of this idea skip. This is not a person-lookup tool and is not built to be
used as one. There is deliberately no batch mode, no bulk input, no queue, and no stored
result database. Single image in, single record out, one invocation at a time. Those
absences are a design decision, not an unfinished feature, and adding them is out of scope.

The demonstration also rests on a boundary worth stating plainly: it only works at all on
subjects whose images are already publicly indexed. That is a real limit on misuse, but it
is a limit imposed by the search index, not by this code — and it is not a control anyone
should rely on, because index coverage keeps growing.

A production deployment would need controls this demonstration does not have, and would not
be responsible to ship without them:

- **Consent and lawful basis at input.** A recorded, auditable basis for running any
  specific face — subject consent, or a documented legal authority — checked before the
  search stage, not asserted in a README.
- **Authenticated, authorized operators.** No anonymous use. Named accounts, role-based
  authorization, and revocation, so every query is attributable to a person.
- **Immutable query audit log.** Who searched, which face, when, and under what stated
  purpose — retained independently of the operator and reviewable by someone who is not
  the operator. The anchoring mechanism here would be a reasonable basis for that log.
- **Rate limiting and bulk prevention.** Hard per-operator caps, with the single-image
  constraint enforced by the server, so the tool cannot be driven as a scanner.
- **Subject-side rights.** A route for a person to learn they were searched, contest a
  match, and have records deleted.
- **Human review before any consequence.** A similarity score is evidence, not a finding.
  No automated action — no account flag, no denial, no report — on a match alone.
- **Data minimization and retention limits.** Embeddings are biometric data. Delete query
  images and embeddings on a fixed schedule rather than accumulating a face database as a
  side effect.
- **Published accuracy and error characteristics.** Measured false-positive and
  false-negative rates, reported per demographic subgroup, since face recognition error
  rates are known to differ across them. The small calibration set above would not be
  adequate.

Absent those, the honest deployment is the one in this repository: consented input, one
image at a time, a demonstration.

## Deployed contract

| | |
|---|---|
| Network | Polygon Amoy (testnet) |
| Contract | `0x48fE6FEFa15b36F87bdDcb722C4f51D9C886717a` |
| Explorer | https://amoy.polygonscan.com/address/0x48fE6FEFa15b36F87bdDcb722C4f51D9C886717a |
| Submitter | `0x36b4cb8e8c2381653e0935889A931E0fee9128ab` |

Anchor transaction from the live run:

```
0x24b0c95e456146dc1cb5431c446d7c91e4b0fd912782a14a71ef84f83a4be966
```

https://amoy.polygonscan.com/tx/0x24b0c95e456146dc1cb5431c446d7c91e4b0fd912782a14a71ef84f83a4be966

That transaction anchored the record hash; reading it back and recomputing the hash from
the canonical payload returned **VERIFIED**.

## Screen recording

_TODO: link_
