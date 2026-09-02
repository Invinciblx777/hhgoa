"""M2 — face detection and embedding via InsightFace buffalo_l on the CPU provider."""

from src.types import FaceEncoding


def detect_and_encode(image_path: str) -> FaceEncoding | None:
    """Detect the face in an image and return its 512-d embedding.

    Runs the InsightFace buffalo_l model under the onnxruntime CPU provider.
    Returns None when no face is detected. When several faces are present the
    one with the largest bounding box is used. The embedding is L2-normalized
    before it is returned.
    """
    raise NotImplementedError


def sha256_file(path: str) -> str:
    """Return the hex-encoded SHA-256 digest of the file's bytes."""
    raise NotImplementedError
