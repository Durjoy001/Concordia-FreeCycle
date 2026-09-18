"""Photo storage behind an interface so local disk can be swapped for GCS."""

from __future__ import annotations

import re
import secrets
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Final

from app.config import settings
from app.services.exceptions import UnprocessableEntity

# Only raster formats Claude vision accepts.
ALLOWED_CONTENT_TYPES: Final[dict[str, str]] = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]*$")
_CHUNK = 64 * 1024


class StorageService(ABC):
    """A content-addressed blob store keyed by storage-relative paths.

    Callers only ever handle keys like ``listings/12/a1b2c3.jpg``; whether that
    resolves to a local file or a GCS object is this class's business.
    """

    @abstractmethod
    def save(self, fileobj: BinaryIO, *, prefix: str, content_type: str) -> str:
        """Persist a stream and return its storage key."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove a key; a missing key is not an error."""

    @abstractmethod
    def local_path(self, key: str) -> Path:
        """A filesystem path the agent layer can read for vision calls."""

    @abstractmethod
    def public_url(self, key: str) -> str:
        """A URL the browser can load."""

    def exists(self, key: str) -> bool:
        raise NotImplementedError

    @staticmethod
    def validate_content_type(content_type: str | None) -> str:
        """Return the file extension for an accepted image type, else raise 422."""
        normalized = (content_type or "").split(";")[0].strip().lower()
        extension = ALLOWED_CONTENT_TYPES.get(normalized)
        if extension is None:
            allowed = ", ".join(sorted(ALLOWED_CONTENT_TYPES))
            raise UnprocessableEntity(f"Unsupported image type {normalized or '(none)'}. Allowed: {allowed}.")
        return extension


class LocalStorageService(StorageService):
    """Stores blobs under ``UPLOAD_DIR``, served by the API's /uploads mount."""

    def __init__(self, root: Path | None = None, base_url: str | None = None,
                 max_bytes: int | None = None) -> None:
        self.root = Path(root or settings.upload_dir).resolve()
        self.base_url = (base_url or settings.public_upload_base_url).rstrip("/")
        self.max_bytes = max_bytes or settings.max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        """Resolve a key inside the root, refusing traversal out of it."""
        if not key or not _SAFE_KEY.match(key) or ".." in PurePosixPath(key).parts:
            raise UnprocessableEntity("Invalid storage key.")
        candidate = (self.root / key).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise UnprocessableEntity("Invalid storage key.")
        return candidate

    def save(self, fileobj: BinaryIO, *, prefix: str, content_type: str) -> str:
        extension = self.validate_content_type(content_type)
        key = f"{prefix.strip('/')}/{secrets.token_hex(16)}{extension}"
        destination = self._resolve(key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        written = 0
        try:
            with destination.open("wb") as out:
                while chunk := fileobj.read(_CHUNK):
                    written += len(chunk)
                    if written > self.max_bytes:
                        raise UnprocessableEntity(
                            f"Image exceeds the {self.max_bytes // (1024 * 1024)}MB limit."
                        )
                    out.write(chunk)
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if written == 0:
            destination.unlink(missing_ok=True)
            raise UnprocessableEntity("Uploaded file is empty.")
        return key

    def delete(self, key: str) -> None:
        self._resolve(key).unlink(missing_ok=True)

    def local_path(self, key: str) -> Path:
        return self._resolve(key)

    def public_url(self, key: str) -> str:
        return f"{self.base_url}/{key}"

    def exists(self, key: str) -> bool:
        return self._resolve(key).is_file()


_storage: StorageService | None = None


def get_storage() -> StorageService:
    """FastAPI dependency / service accessor for the configured storage backend."""
    global _storage
    if _storage is None:
        _storage = LocalStorageService()
    return _storage


def set_storage(service: StorageService | None) -> None:
    """Swap the backend (used by tests, and by a future GCS implementation)."""
    global _storage
    _storage = service
