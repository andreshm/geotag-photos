"""photo_manager.py — folder scanning, ExifTool I/O, RAW+JPEG pairing."""

from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import exiftool
import rawpy
from PIL import Image as PilImage
from PySide6.QtGui import QPixmap, QImage

from .photo_item import (
    PhotoItem,
    PendingChanges,
    RAW_EXTENSIONS,
    JPEG_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
)

log = logging.getLogger(__name__)

THUMB_SIZE   = (200, 200)               # px — grid cell thumbnail cap
EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"    # ExifTool standard EXIF date format


# ──────────────────────────────────────────────────────────────────────────────
# ExifTool detection
# ──────────────────────────────────────────────────────────────────────────────

def find_exiftool() -> Optional[str]:
    """Return the path to the ExifTool binary, or None if not found."""
    candidates = [
        Path(__file__).parent.parent / "exiftool.exe",   # bundled alongside main.py
        Path(__file__).parent.parent / "exiftool",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("exiftool") or shutil.which("exiftool.exe")


EXIFTOOL_PATH: Optional[str] = find_exiftool()


def _et_reader() -> exiftool.ExifToolHelper:
    """ExifToolHelper configured for fast reading only."""
    kw: dict = {"common_args": ["-fast2", "-n"]}  # -n = numeric GPS output
    if EXIFTOOL_PATH:
        kw["executable"] = EXIFTOOL_PATH
    return exiftool.ExifToolHelper(**kw)


def _et_writer() -> exiftool.ExifToolHelper:
    """ExifToolHelper configured for writing (no -fast2 — that's read-only)."""
    kw: dict = {"common_args": ["-overwrite_original"]}
    if EXIFTOOL_PATH:
        kw["executable"] = EXIFTOOL_PATH
    return exiftool.ExifToolHelper(**kw)


# ──────────────────────────────────────────────────────────────────────────────
# Folder scanning & RAW+JPEG pairing
# ──────────────────────────────────────────────────────────────────────────────

def scan_folder(folder: Path) -> list[PhotoItem]:
    """Recursively scan *folder* and return logical PhotoItems.

    RAW+JPEG pairs sharing the same stem in the same directory are merged into
    one item.  The JPEG becomes the display file; the RAW is updated silently.
    """
    if not folder.is_dir():
        raise NotADirectoryError(folder)

    # Collect all supported files — case-insensitive on Windows FS
    seen:      set[Path] = set()
    all_files: list[Path] = []
    for ext in SUPPORTED_EXTENSIONS:
        for p in folder.rglob(f"*{ext}"):
            lo = p.resolve()
            if lo not in seen:
                seen.add(lo)
                all_files.append(p)
        for p in folder.rglob(f"*{ext.upper()}"):
            lo = p.resolve()
            if lo not in seen:
                seen.add(lo)
                all_files.append(p)

    all_files.sort(key=lambda p: (str(p.parent), p.stem.lower(), p.suffix.lower()))

    # Group by (parent_dir, lowercase_stem) to find pairs
    groups: dict[tuple[Path, str], list[Path]] = {}
    for f in all_files:
        groups.setdefault((f.parent, f.stem.lower()), []).append(f)

    items: list[PhotoItem] = []
    for (parent, stem), paths in groups.items():
        raw_files  = [p for p in paths if p.suffix.lower() in RAW_EXTENSIONS]
        jpeg_files = [p for p in paths if p.suffix.lower() in JPEG_EXTENSIONS]
        other      = [p for p in paths
                      if p.suffix.lower() not in RAW_EXTENSIONS
                      and p.suffix.lower() not in JPEG_EXTENSIONS]

        if jpeg_files and raw_files:
            items.append(PhotoItem(
                display_path=jpeg_files[0],
                jpeg_path=jpeg_files[0],
                raw_path=raw_files[0],
            ))
        elif jpeg_files:
            for j in jpeg_files:
                items.append(PhotoItem(display_path=j, jpeg_path=j))
        elif raw_files:
            for r in raw_files:
                items.append(PhotoItem(display_path=r, raw_path=r))
        for o in other:
            items.append(PhotoItem(display_path=o))

    items.sort(key=lambda i: (str(i.folder), i.display_path.name.lower()))
    log.info("Scanned %s → %d items (%d total files)",
             folder, len(items), sum(len(i.all_paths) for i in items))
    return items


# ──────────────────────────────────────────────────────────────────────────────
# Metadata reading
# ──────────────────────────────────────────────────────────────────────────────

def _parse_exif_date(raw) -> Optional[datetime]:
    """Parse any common EXIF date string into a naive datetime."""
    if not raw:
        return None
    s = str(raw).strip()
    # Normalise: ISO 'T' separator → space; drop sub-seconds and timezone
    s = s.replace("T", " ")
    s = s[:19]   # "YYYY:MM:DD HH:MM:SS" or "YYYY-MM-DD HH:MM:SS"
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    log.debug("Could not parse date string: %r", raw)
    return None


def _parse_gps_coord(value, ref: Optional[str]) -> Optional[float]:
    """Convert ExifTool numeric GPS value + compass ref to a signed float."""
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if ref and ref.upper() in ("S", "W"):
        v = -abs(v)
    return v


def load_metadata(items: list[PhotoItem]) -> None:
    """Read EXIF date + GPS for all items in one batch ExifTool call."""
    if not items:
        return

    paths = [str(i.display_path) for i in items]
    tags  = [
        "EXIF:DateTimeOriginal",
        "EXIF:CreateDate",
        "EXIF:ModifyDate",
        "GPS:GPSLatitude",
        "GPS:GPSLatitudeRef",
        "GPS:GPSLongitude",
        "GPS:GPSLongitudeRef",
    ]

    try:
        with _et_reader() as et:
            results = et.get_tags(paths, tags)
    except Exception as exc:
        log.error("ExifTool metadata read failed: %s", exc)
        return

    for item, meta in zip(items, results):
        raw_date = (
            meta.get("EXIF:DateTimeOriginal")
            or meta.get("EXIF:CreateDate")
            or meta.get("EXIF:ModifyDate")
        )
        item.date_taken = _parse_exif_date(raw_date)

        # -n flag in _et_reader() makes GPS values come back as plain floats
        item.gps_lat = _parse_gps_coord(
            meta.get("GPS:GPSLatitude"), meta.get("GPS:GPSLatitudeRef"))
        item.gps_lon = _parse_gps_coord(
            meta.get("GPS:GPSLongitude"), meta.get("GPS:GPSLongitudeRef"))
        item._metadata_loaded = True


# ──────────────────────────────────────────────────────────────────────────────
# Thumbnail generation
# ──────────────────────────────────────────────────────────────────────────────

def _pil_to_qpixmap(img: PilImage.Image) -> QPixmap:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qimg = QImage(data, img.width, img.height, img.width * 3,
                  QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qimg)


def generate_thumbnail(item: PhotoItem) -> Optional[QPixmap]:
    """Generate a THUMB_SIZE QPixmap for *item*.  Returns None on failure."""
    path = item.display_path
    suffix = path.suffix.lower()

    # ── Standard raster formats → Pillow ────────────────────────────────────
    if suffix in JPEG_EXTENSIONS | {".tif", ".tiff", ".png", ".bmp", ".webp"}:
        try:
            with PilImage.open(path) as img:
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("Pillow thumb failed (%s): %s", path.name, exc)

    # ── RAW → rawpy → Pillow ─────────────────────────────────────────────────
    if suffix in RAW_EXTENSIONS:
        try:
            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True,
                    half_size=True,
                    no_auto_bright=False,
                    output_bps=8,
                )
            img = PilImage.fromarray(rgb)
            img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
            return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("rawpy thumb failed (%s): %s", path.name, exc)

        # Fallback: ask ExifTool to extract the embedded preview JPEG
        try:
            cmd = [EXIFTOOL_PATH or "exiftool",
                   "-b", "-PreviewImage", "-LargeThumbnailImage",
                   str(path)]
            result = subprocess.run(cmd, capture_output=True, timeout=15)
            if result.returncode == 0 and result.stdout:
                img = PilImage.open(io.BytesIO(result.stdout))
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("ExifTool preview fallback failed (%s): %s", path.name, exc)

    # ── HEIC / HEIF → ExifTool ───────────────────────────────────────────────
    if suffix in {".heic", ".heif"}:
        try:
            cmd = [EXIFTOOL_PATH or "exiftool", "-b", "-ThumbnailImage", str(path)]
            result = subprocess.run(cmd, capture_output=True, timeout=15)
            if result.returncode == 0 and result.stdout:
                img = PilImage.open(io.BytesIO(result.stdout))
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("HEIC thumb failed (%s): %s", path.name, exc)

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Writing changes
# ──────────────────────────────────────────────────────────────────────────────

def _gps_tags(lat: float, lon: float) -> dict:
    return {
        "GPS:GPSLatitude":     abs(lat),
        "GPS:GPSLatitudeRef":  "N" if lat >= 0 else "S",
        "GPS:GPSLongitude":    abs(lon),
        "GPS:GPSLongitudeRef": "E" if lon >= 0 else "W",
    }


def apply_changes(
    item: PhotoItem,
    normalize_dates: bool = False,
    do_rename: bool = False,
    append_original: bool = False,
) -> list[str]:
    """Write pending GPS, optionally normalise dates, optionally rename.

    Returns a list of warning strings (empty list = success).
    Uses ExifTool only for EXIF/GPS tags; os.utime for filesystem timestamps.
    """
    warnings: list[str] = []
    all_paths_str = [str(p) for p in item.all_paths]
    gps = item.pending.gps

    # ── EXIF tags (ExifTool) ─────────────────────────────────────────────────
    exif_tags: dict = {}

    if gps:
        exif_tags.update(_gps_tags(*gps))

    if normalize_dates and item.date_taken:
        date_str = item.date_taken.strftime(EXIF_DATE_FMT)
        # "AllDates" is an ExifTool shortcut that sets
        # DateTimeOriginal, CreateDate and ModifyDate in one pass
        exif_tags["AllDates"] = date_str

    if exif_tags:
        try:
            with _et_writer() as et:
                et.set_tags(all_paths_str, exif_tags)
        except Exception as exc:
            msg = f"ExifTool write error on '{item.display_name}': {exc}"
            log.error(msg)
            warnings.append(msg)
            return warnings   # Don't proceed with rename if write failed

    # ── Filesystem modification time (os.utime — more reliable than ExifTool) ─
    if normalize_dates and item.date_taken:
        ts = item.date_taken.timestamp()
        for p in item.all_paths:
            try:
                os.utime(str(p), (ts, ts))
            except OSError as exc:
                log.warning("utime failed for '%s': %s", p.name, exc)

    # ── Update in-memory state ────────────────────────────────────────────────
    if gps:
        item.gps_lat, item.gps_lon = gps
        item.pending.gps = None

    # ── Rename ───────────────────────────────────────────────────────────────
    if do_rename and item.date_taken:
        for path in list(item.all_paths):   # list() — all_paths may change
            stem = item.date_taken.strftime("%Y%m%d %H%M%S")
            if append_original:
                stem = stem + " " + path.stem
            new_path = path.parent / (stem + path.suffix)

            if new_path == path:
                continue

            # Avoid collisions
            counter = 1
            while new_path.exists():
                new_path = path.parent / (f"{stem} ({counter}){path.suffix}")
                counter += 1

            try:
                path.rename(new_path)
                if path == item.display_path:
                    item.display_path = new_path
                if path == item.jpeg_path:
                    item.jpeg_path = new_path
                if path == item.raw_path:
                    item.raw_path = new_path
            except OSError as exc:
                msg = f"Rename failed '{path.name}' → '{new_path.name}': {exc}"
                log.error(msg)
                warnings.append(msg)

    return warnings


def apply_changes_batch(
    items: list[PhotoItem],
    normalize_dates: bool = False,
    do_rename: bool = False,
    append_original: bool = False,
    progress_callback=None,
) -> list[str]:
    """Apply pending changes to a batch of items, calling progress_callback(n, total)."""
    all_warnings: list[str] = []
    total = len(items)
    for n, item in enumerate(items, 1):
        if progress_callback:
            progress_callback(n, total)
        all_warnings.extend(
            apply_changes(item, normalize_dates, do_rename, append_original)
        )
    return all_warnings
