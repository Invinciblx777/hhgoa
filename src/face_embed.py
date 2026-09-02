"""M2 — face detection and embedding via InsightFace buffalo_l on the CPU provider."""

import hashlib

import cv2
import numpy as np
from insightface.app import FaceAnalysis

from src.types import FaceEncoding

_CHUNK_SIZE = 1024 * 1024

# The model pack is loaded once at import time; detection and recognition are
# both expensive to initialize and M4 calls into this module in a loop.
# CPUExecutionProvider is pinned explicitly so onnxruntime can never fall back
# to CUDA, and ctx_id=-1 tells InsightFace the same thing.
_app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
_app.prepare(ctx_id=-1, det_size=(640, 640))


def _read_image(image_path: str) -> np.ndarray:
    """Read an image off disk into a BGR array.

    Goes through np.fromfile rather than cv2.imread directly, because cv2.imread
    silently returns None for paths containing non-ASCII characters on Windows.
    """
    buffer = np.fromfile(image_path, dtype=np.uint8)
    if buffer.size == 0:
        raise ValueError(f"Image file is empty or unreadable: {image_path}")
    image = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"Not a decodable image: {image_path}")
    return image


def detect_and_encode(image_path: str) -> FaceEncoding | None:
    """Detect the face in an image and return its 512-d embedding.

    Runs the InsightFace buffalo_l model under the onnxruntime CPU provider.
    Returns None when no face is detected. When several faces are present the
    one with the largest bounding box is used. The embedding is L2-normalized
    before it is returned.
    """
    image = _read_image(image_path)
    faces = _app.get(image)
    if not faces:
        return None

    face = max(
        faces,
        key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]),
    )

    embedding = np.asarray(face.embedding, dtype=np.float64)
    norm = float(np.linalg.norm(embedding))
    if norm == 0.0:
        return None
    embedding = embedding / norm

    x1, y1, x2, y2 = (int(round(v)) for v in face.bbox)
    return FaceEncoding(
        embedding=[float(v) for v in embedding],
        bbox=(x1, y1, x2, y2),
        det_score=float(face.det_score),
        image_sha256=sha256_file(image_path),
        source_path=image_path,
    )


def sha256_file(path: str) -> str:
    """Return the hex-encoded SHA-256 digest of the file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two embeddings, clamped to [-1.0, 1.0].

    Does not assume its inputs are normalized, so it stays correct if it is ever
    handed a raw embedding. Returns 0.0 if either vector has zero magnitude.
    """
    vec_a = np.asarray(a, dtype=np.float64)
    vec_b = np.asarray(b, dtype=np.float64)
    if vec_a.shape != vec_b.shape:
        raise ValueError(
            f"Embedding length mismatch: {vec_a.shape[0]} vs {vec_b.shape[0]}"
        )
    denominator = float(np.linalg.norm(vec_a)) * float(np.linalg.norm(vec_b))
    if denominator == 0.0:
        return 0.0
    return float(np.clip(np.dot(vec_a, vec_b) / denominator, -1.0, 1.0))


if __name__ == "__main__":
    SAMPLE = "samples/query.jpg"

    print(f"[M2] encoding {SAMPLE}")
    encoding = detect_and_encode(SAMPLE)
    if encoding is None:
        print("[M2] no face detected")
        raise SystemExit(1)

    print(f"  bbox            : {encoding.bbox}")
    print(f"  det_score       : {encoding.det_score:.4f}")
    print(f"  embedding length: {len(encoding.embedding)}")
    print(f"  embedding L2    : {np.linalg.norm(encoding.embedding):.6f}")
    print(f"  image_sha256    : {encoding.image_sha256}")
    print(f"  self-similarity : {cosine_similarity(encoding.embedding, encoding.embedding):.6f}")
