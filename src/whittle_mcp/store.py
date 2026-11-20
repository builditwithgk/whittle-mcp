"""Where the omitted text lives, so that nothing is ever really lost: every trim stores the full input under a short handle."""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from pathlib import Path


def default_directory() -> Path:
    base = os.environ.get("WHITTLE_DIR")
    if base:
        return Path(base)
    return Path(tempfile.gettempdir()) / "whittle-store"


class Store:
    """In-memory by default; pass a directory to share handles between separate CLI calls. Entries expire after `ttl` seconds."""

    def __init__(self, directory: Path | None = None, ttl: int = 24 * 3600) -> None:
        self.directory = directory
        self.ttl = ttl
        self._memory: dict[str, str] = {}
        if directory:
            directory.mkdir(parents=True, exist_ok=True)
            self._expire()

    def _expire(self) -> None:
        assert self.directory
        cutoff = time.time() - self.ttl
        for path in self.directory.glob("*.txt"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
            except OSError:
                pass

    def put(self, text: str) -> str:
        handle = hashlib.sha1(text.encode("utf-8", "surrogatepass")).hexdigest()[:8]
        self._memory[handle] = text
        if self.directory:
            (self.directory / f"{handle}.txt").write_text(text, encoding="utf-8", errors="surrogatepass")
        return handle

    def get(self, handle: str) -> str | None:
        if handle in self._memory:
            return self._memory[handle]
        if self.directory and handle.isalnum():
            path = self.directory / f"{handle}.txt"
            if path.is_file():
                return path.read_text(encoding="utf-8", errors="surrogatepass")
        return None

    def lines(self, handle: str, start: int, end: int) -> str | None:
        """Lines start..end (1-based, inclusive) of a stored input."""
        text = self.get(handle)
        if text is None:
            return None
        rows = text.splitlines()
        return "\n".join(rows[max(start, 1) - 1:max(end, 0)])
