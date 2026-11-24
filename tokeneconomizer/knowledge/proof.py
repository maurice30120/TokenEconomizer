"""File contracts over bytes captured by a complete, trustworthy observation."""
import hashlib
from pathlib import Path


def file_proof(root, path, observed, *, complete):
    """Build a proof only from a complete observation; never hash a later file read."""
    if not complete or not isinstance(observed, bytes):
        return None
    root = Path(root).resolve()
    target = (root / path).resolve()
    try:
        relative = target.relative_to(root)
    except ValueError:
        return None
    return {"path": str(relative), "sha256": hashlib.sha256(observed).hexdigest()}


def verify_file(root, proof):
    """Revalidate the stored observation, failing closed on unreadable files."""
    try:
        root = Path(root).resolve()
        target = (root / proof["path"]).resolve()
        target.relative_to(root)
        return hashlib.sha256(target.read_bytes()).hexdigest() == proof["sha256"]
    except (OSError, ValueError, KeyError, TypeError):
        return False
