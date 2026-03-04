"""PhotoItem dataclass — one logical photo (may be a RAW+JPEG pair)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtGui import QPixmap


# ---------------------------------------------------------------------------
# File-type sets
# ---------------------------------------------------------------------------
RAW_EXTENSIONS: set[str] = {
    ".3fr", ".arw", ".cr2", ".cr3", ".crw", ".dcr", ".dng", ".erf",
    ".k25", ".kdc", ".mef", ".mrw", ".nef", ".nrw", ".orf", ".pef",
    ".ptx", ".r3d", ".raf", ".raw", ".rw1", ".rw2", ".rwl", ".sr2",
    ".srf", ".srw", ".x3f",
}
JPEG_EXTENSIONS: set[str] = {".jpg", ".jpeg"}
VIDEO_EXTENSIONS: set[str] = {".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts"}

SUPPORTED_EXTENSIONS: set[str] = RAW_EXTENSIONS | JPEG_EXTENSIONS | {
    ".tif", ".tiff", ".heic", ".heif", ".png", ".bmp", ".webp",
}


# ---------------------------------------------------------------------------
# Pending change accumulator
# ---------------------------------------------------------------------------
@dataclass
class PendingChanges:
    """Changes waiting to be written to disk."""
    gps: Optional[tuple[float, float]] = None     # (lat, lon)
    normalize_dates: bool = False                 # set all dates → DateTimeOriginal
    rename: bool = False
    rename_append_original: bool = False


# ---------------------------------------------------------------------------
# Main item
# ---------------------------------------------------------------------------
@dataclass
class PhotoItem:
    """Represents one logical photo shown in the grid.

    When a RAW+JPEG pair shares the same base name in the same folder,
    only the JPEG is shown but both files are updated together.
    """

    # --- identity ---
    display_path: Path          # file shown in grid (JPEG if pair, else raw/other)
    raw_path:     Optional[Path] = None   # companion RAW, if any
    jpeg_path:    Optional[Path] = None   # companion JPEG, if any (= display_path when paired)

    # --- metadata (read from EXIF) ---
    date_taken:  Optional[datetime] = None
    gps_lat:     Optional[float] = None
    gps_lon:     Optional[float] = None

    # --- UI state ---
    thumbnail:   Optional[QPixmap] = field(default=None, repr=False)
    selected:    bool = False

    # --- pending changes (not yet written) ---
    pending:     PendingChanges = field(default_factory=PendingChanges)

    # --- internal ---
    _metadata_loaded: bool = False

    # ------------------------------------------------------------------ helpers

    @property
    def has_gps(self) -> bool:
        return self.gps_lat is not None and self.gps_lon is not None

    @property
    def has_pending_gps(self) -> bool:
        return self.pending.gps is not None

    @property
    def is_pair(self) -> bool:
        return self.raw_path is not None and self.jpeg_path is not None

    @property
    def all_paths(self) -> list[Path]:
        """All physical files belonging to this item (1 or 2)."""
        paths = [self.display_path]
        if self.raw_path and self.raw_path != self.display_path:
            paths.append(self.raw_path)
        if self.jpeg_path and self.jpeg_path != self.display_path:
            paths.append(self.jpeg_path)
        # deduplicate while preserving order
        seen: set[Path] = set()
        result: list[Path] = []
        for p in paths:
            if p not in seen:
                seen.add(p)
                result.append(p)
        return result

    @property
    def display_name(self) -> str:
        return self.display_path.name

    @property
    def folder(self) -> Path:
        return self.display_path.parent

    @property
    def effective_gps(self) -> Optional[tuple[float, float]]:
        """Return pending GPS if set, else existing GPS."""
        if self.pending.gps:
            return self.pending.gps
        if self.has_gps:
            return (self.gps_lat, self.gps_lon)  # type: ignore[return-value]
        return None

    def gps_str(self) -> str:
        g = self.effective_gps
        if g is None:
            return "No GPS"
        lat, lon = g
        return f"{lat:.6f}, {lon:.6f}"

    def date_str(self) -> str:
        if self.date_taken:
            return self.date_taken.strftime("%Y-%m-%d %H:%M:%S")
        return "Unknown date"

    def proposed_filename(self, append_original: bool = False) -> str:
        """Compute the rename target filename (without directory)."""
        if not self.date_taken:
            return self.display_path.name
        stem = self.date_taken.strftime("%Y%m%d %H%M%S")
        if append_original:
            stem = stem + " " + self.display_path.stem
        return stem + self.display_path.suffix
