"""photo_item.py — PhotoItem dataclass representing one logical photo or video (with RAW+JPEG pairing, format mismatch tracking, and video metadata)."""

from __future__ import annotations

import re
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
VIDEO_EXTENSIONS: set[str] = {
    ".mp4", ".mov", ".m4v", ".3gp", ".qt", ".insv",
    ".avi", ".mkv", ".mts", ".m2ts",
}

SUPPORTED_EXTENSIONS: set[str] = (
    RAW_EXTENSIONS | JPEG_EXTENSIONS | VIDEO_EXTENSIONS | {
        ".tif", ".tiff", ".heic", ".heif", ".png", ".bmp", ".webp",
    }
)

# ---------------------------------------------------------------------------
# Date-in-filename pattern regex
# ---------------------------------------------------------------------------
_DATE_PATTERNS = [
    # YYYYMMDD_HHMMSS or YYYYMMDD HHMMSS or YYYYMMDD-HHMMSS (with optional suffix/prefix)
    re.compile(r"(?:^|[_\s\-\.\(])(19\d\d|20\d\d)[-_.]?(0[1-9]|1[0-2])[-_.]?(0[1-9]|[12]\d|3[01])(?:[_\s\-\.T]+([01]\d|2[0-3])[-_.:]?([0-5]\d)[-_.:]?([0-5]\d)?)?", re.IGNORECASE),
    # PXL_YYYYMMDD or VID_YYYYMMDD or IMG_YYYYMMDD
    re.compile(r"(?:PXL|VID|IMG|WP|WIN)[-_](19\d\d|20\d\d)(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])", re.IGNORECASE),
    # WhatsApp Image YYYY-MM-DD
    re.compile(r"(19\d\d|20\d\d)[-_/.](0[1-9]|1[0-2])[-_/.](0[1-9]|[12]\d|3[01])"),
]


def has_date_in_filename(name: str) -> bool:
    """Return True if filename contains any recognizable date pattern (YYYY-MM-DD, YYYYMMDD, etc.)."""
    stem = name.rsplit(".", 1)[0]
    for pattern in _DATE_PATTERNS:
        match = pattern.search(stem)
        if match:
            groups = match.groups()
            for g in groups:
                if g and len(g) == 4 and g.isdigit():
                    yr = int(g)
                    if 1970 <= yr <= 2099:
                        return True
    return False


# ---------------------------------------------------------------------------
# Pending change accumulator
# ---------------------------------------------------------------------------
@dataclass
class PendingChanges:
    """Changes waiting to be written to disk."""
    gps: Optional[tuple[float, float]] = None     # (lat, lon)
    strip_gps: bool = False                       # completely erase GPS tags from file
    normalize_dates: bool = False                 # set all dates → DateTimeOriginal / CreateDate
    rename: bool = False
    rename_append_original: bool = False
    smart_undated_only: bool = False              # rename only if filename has no date


# ---------------------------------------------------------------------------
# Main item
# ---------------------------------------------------------------------------
@dataclass(eq=False)
class PhotoItem:
    """Represents one logical photo or video shown in the grid.

    When a RAW+JPEG pair shares the same base name in the same folder,
    only the JPEG is shown but both files are updated together.
    """

    # --- identity ---
    display_path: Path          # file shown in grid (JPEG if pair, else raw/video/other)
    raw_path:     Optional[Path] = None   # companion RAW, if any
    jpeg_path:    Optional[Path] = None   # companion JPEG, if any (= display_path when paired)

    # --- metadata (read from EXIF / QuickTime) ---
    date_taken:     Optional[datetime] = None
    gps_lat:        Optional[float] = None
    gps_lon:        Optional[float] = None
    camera_make:    Optional[str] = None
    camera_model:   Optional[str] = None
    lens_model:     Optional[str] = None
    iso:            Optional[int] = None
    f_number:       Optional[float] = None
    exposure_time:  Optional[str] = None
    focal_length:   Optional[str] = None
    image_width:    Optional[int] = None
    image_height:   Optional[int] = None
    file_size:      int = 0
    duration_sec:   Optional[float] = None  # for videos

    # --- format mismatch tracking ---
    format_mismatch: Optional[tuple[str, str]] = None  # (true_binary_ext, filename_ext) e.g. ('.png', '.jpg')

    # --- UI state ---
    thumbnail:      Optional[QPixmap] = field(default=None, repr=False)
    selected:       bool = False

    # --- pending changes (not yet written) ---
    pending:        PendingChanges = field(default_factory=PendingChanges)

    # --- internal ---
    _metadata_loaded: bool = False

    def __hash__(self) -> int:
        return id(self)

    # ------------------------------------------------------------------ helpers

    @property
    def is_video(self) -> bool:
        return self.display_path.suffix.lower() in VIDEO_EXTENSIONS

    @property
    def has_date_in_name(self) -> bool:
        return has_date_in_filename(self.display_name)

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
    def has_format_mismatch(self) -> bool:
        return self.format_mismatch is not None

    @property
    def is_png(self) -> bool:
        """True if this item is a PNG file (by extension or detected format mismatch)."""
        if self.is_video:
            return False
        if self.display_path.suffix.lower() == ".png":
            return True
        if self.format_mismatch and self.format_mismatch[0] == ".png":
            return True
        return False

    @property
    def duration_str(self) -> str:
        """Formatted MM:SS or HH:MM:SS for video duration."""
        if self.duration_sec is None or self.duration_sec <= 0:
            return ""
        total_sec = int(round(self.duration_sec))
        hrs = total_sec // 3600
        mins = (total_sec % 3600) // 60
        secs = total_sec % 60
        if hrs > 0:
            return f"{hrs:02d}:{mins:02d}:{secs:02d}"
        return f"{mins:02d}:{secs:02d}"

    @property
    def video_format_str(self) -> str:
        return self.display_path.suffix.lstrip(".").upper()

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
    def has_pending_gps(self) -> bool:
        """Return True if item has pending GPS update or pending GPS removal."""
        return self.pending.gps is not None or self.pending.strip_gps

    @property
    def effective_gps(self) -> Optional[tuple[float, float]]:
        """Return pending GPS if set, else existing GPS (None if pending strip)."""
        if self.pending.strip_gps:
            return None
        if self.pending.gps is not None:
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

    @property
    def camera_str(self) -> str:
        if self.camera_model:
            if self.camera_make and not self.camera_model.startswith(self.camera_make):
                return f"{self.camera_make} {self.camera_model}"
            return self.camera_model
        return self.camera_make or ("Video File" if self.is_video else "Unknown Camera")

    @property
    def lens_str(self) -> str:
        return self.lens_model or ""

    @property
    def exposure_str(self) -> str:
        if self.is_video:
            parts = []
            if self.duration_str:
                parts.append(f"Duration: {self.duration_str}")
            if self.image_width and self.image_height:
                parts.append(f"{self.image_width}×{self.image_height}")
            return " · ".join(parts) if parts else "Video"

        parts = []
        if self.focal_length:
            parts.append(f"{self.focal_length}")
        if self.f_number:
            parts.append(f"ƒ/{self.f_number}")
        if self.exposure_time:
            parts.append(f"{self.exposure_time}s")
        if self.iso:
            parts.append(f"ISO {self.iso}")
        return " · ".join(parts) if parts else "No exposure data"

    @property
    def dimensions_str(self) -> str:
        if self.image_width and self.image_height:
            return f"{self.image_width} × {self.image_height} px"
        return ""

    @property
    def formatted_size(self) -> str:
        s = self.file_size
        if not s and self.display_path.exists():
            try:
                s = sum(p.stat().st_size for p in self.all_paths if p.exists())
            except Exception:
                s = 0
        if s < 1024:
            return f"{s} B"
        elif s < 1024 * 1024:
            return f"{s / 1024:.1f} KB"
        return f"{s / (1024 * 1024):.1f} MB"

    def proposed_filename(self, append_original: bool = False) -> str:
        """Compute the rename target filename (without directory)."""
        if not self.date_taken:
            return self.display_path.name
        stem = self.date_taken.strftime("%Y%m%d %H%M%S")
        if append_original:
            stem = stem + " " + self.display_path.stem
        return stem + self.display_path.suffix
