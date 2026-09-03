# HH Goa 2026 — Task 3: Face Identification & Blockchain Verification

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
