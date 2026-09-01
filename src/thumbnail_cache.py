"""thumbnail_cache.py — Persistent local disk cache for fast thumbnail retrieval with 30-day auto-cleanup."""

from __future__ import annotations

import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Optional

from PIL import Image as PilImage

PilImage.MAX_IMAGE_PIXELS = None
from PySide6.QtGui import QImage

log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache" / "thumbnails"


class ThumbnailCache:
    """Manages pre-rendered thumbnail disk caching for instant loads on large photo/video libraries."""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = cache_dir or DEFAULT_CACHE_DIR
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_filename(self, path: Path) -> str:
        try:
            st = path.stat()
            key = f"{path.resolve()}_{st.st_mtime}_{st.st_size}"
        except OSError:
            key = str(path.resolve())

        digest = hashlib.md5(key.encode("utf-8", errors="ignore")).hexdigest()
        return f"{digest}.jpg"

    def get_cached_image(self, path: Path) -> Optional[QImage]:
        """Return cached QImage if present on disk, otherwise None."""
        cache_file = self.cache_dir / self._cache_filename(path)
        if cache_file.exists() and cache_file.stat().st_size > 0:
            try:
                qimg = QImage(str(cache_file))
                if not qimg.isNull():
                    return qimg
            except Exception as exc:
                log.debug("Cache read error (%s): %s", path.name, exc)
        return None

    def save_cached_image(self, path: Path, img: PilImage.Image, quality: int = 85) -> Optional[Path]:
        """Save PIL image to disk cache for fast future retrieval."""
        cache_file = self.cache_dir / self._cache_filename(path)
        try:
            rgb = img.convert("RGB")
            rgb.save(cache_file, "JPEG", quality=quality, optimize=True)
            return cache_file
        except Exception as exc:
            log.debug("Cache write error (%s): %s", path.name, exc)
            return None

    def cleanup_old_cache(self, max_days: int = 30) -> int:
        """Auto-delete cache files older than max_days. Returns count of deleted files."""
        if not self.cache_dir.exists():
            return 0

        cutoff = time.time() - (max_days * 86400)
        deleted_count = 0

        try:
            for entry in os.scandir(self.cache_dir):
                if entry.is_file() and entry.name.endswith(".jpg"):
                    try:
                        if entry.stat().st_mtime < cutoff:
                            os.remove(entry.path)
                            deleted_count += 1
                    except OSError:
                        pass
        except OSError as exc:
            log.warning("Cache cleanup error: %s", exc)

        if deleted_count > 0:
            log.info("Auto-cleaned %d cache files older than %d days from %s",
                     deleted_count, max_days, self.cache_dir)
        return deleted_count

    def clear_all(self) -> int:
        """Delete all cached thumbnails immediately."""
        if not self.cache_dir.exists():
            return 0
        count = 0
        try:
            for entry in os.scandir(self.cache_dir):
                if entry.is_file():
                    try:
                        os.remove(entry.path)
                        count += 1
                    except OSError:
                        pass
        except OSError as exc:
            log.warning("Clear cache error: %s", exc)
        log.info("Cleared %d cached thumbnails from %s", count, self.cache_dir)
        return count

    def get_stats(self) -> dict:
        """Return cache stats (count, total_bytes, path)."""
        count = 0
        total_bytes = 0
        if self.cache_dir.exists():
            try:
                for entry in os.scandir(self.cache_dir):
                    if entry.is_file():
                        count += 1
                        total_bytes += entry.stat().st_size
            except OSError:
                pass

        return {
            "count": count,
            "total_bytes": total_bytes,
            "formatted_size": f"{total_bytes / (1024 * 1024):.1f} MB" if total_bytes >= 1024*1024 else f"{total_bytes / 1024:.1f} KB",
            "path": str(self.cache_dir.resolve()),
        }


# Global singleton instance
thumbnail_cache = ThumbnailCache()
