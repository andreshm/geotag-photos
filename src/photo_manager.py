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
    RAW_EXTENSIONS,
    JPEG_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
)

log = logging.getLogger(__name__)

THUMB_SIZE    = (200, 200)
EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"

# Formats that fully support EXIF GPS + AllDates
_EXIF_FORMATS: frozenset[str] = (
    RAW_EXTENSIONS | JPEG_EXTENSIONS | frozenset({".tif", ".tiff", ".heic", ".heif"})
)
# Formats that use XMP (stored in iTXt / metadata chunk).
# PNG: EXIF eXIf chunk triggers compatibility warnings → use XMP instead.
# WebP: EXIF is optional; XMP is better supported across readers.
_XMP_FORMATS: frozenset[str] = frozenset({".png", ".webp"})
# BMP has NO metadata capability — only os.utime() is applied.


# ──────────────────────────────────────────────────────────────────────────────
# ExifTool detection
# ──────────────────────────────────────────────────────────────────────────────

def find_exiftool() -> Optional[str]:
    candidates = [
        Path(__file__).parent.parent / "exiftool.exe",
        Path(__file__).parent.parent / "exiftool",
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return shutil.which("exiftool") or shutil.which("exiftool.exe")


EXIFTOOL_PATH: Optional[str] = find_exiftool()


def _et_reader() -> exiftool.ExifToolHelper:
    """Persistent ExifTool process for fast reading."""
    kw: dict = {"common_args": ["-fast2", "-n"]}
    if EXIFTOOL_PATH:
        kw["executable"] = EXIFTOOL_PATH
    return exiftool.ExifToolHelper(**kw)


def _et_writer() -> exiftool.ExifToolHelper:
    """Persistent ExifTool process for writing (no -fast2 — read-only flag)."""
    kw: dict = {"common_args": ["-overwrite_original"]}
    if EXIFTOOL_PATH:
        kw["executable"] = EXIFTOOL_PATH
    return exiftool.ExifToolHelper(**kw)


# ──────────────────────────────────────────────────────────────────────────────
# Folder scanning & RAW+JPEG pairing
# ──────────────────────────────────────────────────────────────────────────────

def scan_folder(folder: Path) -> list[PhotoItem]:
    """Recursively scan *folder*, pair RAW+JPEG by stem, return PhotoItems."""
    if not folder.is_dir():
        raise NotADirectoryError(folder)

    seen:      set[Path] = set()
    all_files: list[Path] = []

    def _collect(paths):
        for p in paths:
            # Skip files that live inside any directory named "GPSOK"
            try:
                rel_parts = p.relative_to(folder).parts[:-1]
            except ValueError:
                rel_parts = ()
            if any(part.upper() == "GPSOK" for part in rel_parts):
                continue
            lo = p.resolve()
            if lo not in seen:
                seen.add(lo)
                all_files.append(p)

    for ext in SUPPORTED_EXTENSIONS:
        _collect(folder.rglob(f"*{ext}"))
        _collect(folder.rglob(f"*{ext.upper()}"))

    all_files.sort(key=lambda p: (str(p.parent), p.stem.lower(), p.suffix.lower()))

    groups: dict[tuple[Path, str], list[Path]] = {}
    for f in all_files:
        groups.setdefault((f.parent, f.stem.lower()), []).append(f)

    items: list[PhotoItem] = []
    for (parent, stem), paths in groups.items():
        raws  = [p for p in paths if p.suffix.lower() in RAW_EXTENSIONS]
        jpegs = [p for p in paths if p.suffix.lower() in JPEG_EXTENSIONS]
        other = [p for p in paths
                 if p.suffix.lower() not in RAW_EXTENSIONS
                 and p.suffix.lower() not in JPEG_EXTENSIONS]

        if jpegs and raws:
            items.append(PhotoItem(
                display_path=jpegs[0], jpeg_path=jpegs[0], raw_path=raws[0]
            ))
        elif jpegs:
            for j in jpegs:
                items.append(PhotoItem(display_path=j, jpeg_path=j))
        elif raws:
            for r in raws:
                items.append(PhotoItem(display_path=r, raw_path=r))
        for o in other:
            items.append(PhotoItem(display_path=o))

    items.sort(key=lambda i: (str(i.folder), i.display_path.name.lower()))
    log.info("Scanned %s → %d items (%d files)",
             folder, len(items), sum(len(i.all_paths) for i in items))
    return items


# ──────────────────────────────────────────────────────────────────────────────
# Metadata reading
# ──────────────────────────────────────────────────────────────────────────────

def _parse_exif_date(raw) -> Optional[datetime]:
    if not raw:
        return None
    s = str(raw).strip().replace("T", " ")[:19]
    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    log.debug("Unrecognised date string: %r", raw)
    return None


def _parse_gps_coord(value, ref: Optional[str]) -> Optional[float]:
    """Signed decimal degree from ExifTool numeric value + compass ref."""
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
    """Batch-read EXIF date + GPS for all items in one ExifTool call."""
    if not items:
        return
    paths = [str(i.display_path) for i in items]
    tags  = [
        "EXIF:DateTimeOriginal", "EXIF:CreateDate", "EXIF:ModifyDate",
        "GPS:GPSLatitude", "GPS:GPSLatitudeRef",
        "GPS:GPSLongitude", "GPS:GPSLongitudeRef",
    ]
    try:
        with _et_reader() as et:
            results = et.get_tags(paths, tags)
    except Exception as exc:
        log.error("ExifTool read failed: %s", exc)
        return

    for item, meta in zip(items, results):
        raw_date = (
            meta.get("EXIF:DateTimeOriginal")
            or meta.get("EXIF:CreateDate")
            or meta.get("EXIF:ModifyDate")
        )
        item.date_taken = _parse_exif_date(raw_date)
        item.gps_lat    = _parse_gps_coord(meta.get("GPS:GPSLatitude"),
                                            meta.get("GPS:GPSLatitudeRef"))
        item.gps_lon    = _parse_gps_coord(meta.get("GPS:GPSLongitude"),
                                            meta.get("GPS:GPSLongitudeRef"))
        item._metadata_loaded = True


# ──────────────────────────────────────────────────────────────────────────────
# Thumbnail generation
# ──────────────────────────────────────────────────────────────────────────────

def _pil_to_qpixmap(img: PilImage.Image) -> QPixmap:
    img  = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qi   = QImage(data, img.width, img.height, img.width * 3,
                  QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qi)


def generate_thumbnail(item: PhotoItem) -> Optional[QPixmap]:
    """Generate a THUMB_SIZE QPixmap for *item*. Returns None on failure."""
    path   = item.display_path
    suffix = path.suffix.lower()

    # ── Standard raster → Pillow ─────────────────────────────────────────────
    if suffix in JPEG_EXTENSIONS | {".tif", ".tiff", ".png", ".bmp", ".webp"}:
        try:
            with PilImage.open(path) as img:
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("Pillow thumb (%s): %s", path.name, exc)

    # ── RAW → rawpy → Pillow ─────────────────────────────────────────────────
    if suffix in RAW_EXTENSIONS:
        try:
            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True, half_size=True,
                    no_auto_bright=False, output_bps=8,
                )
            img = PilImage.fromarray(rgb)
            img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
            return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("rawpy thumb (%s): %s", path.name, exc)

        # Fallback: ExifTool embedded preview
        try:
            cmd = [EXIFTOOL_PATH or "exiftool",
                   "-b", "-PreviewImage", "-LargeThumbnailImage", str(path)]
            r = subprocess.run(cmd, capture_output=True, timeout=15)
            if r.returncode == 0 and r.stdout:
                img = PilImage.open(io.BytesIO(r.stdout))
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("ExifTool preview fallback (%s): %s", path.name, exc)

    # ── HEIC / HEIF → ExifTool ───────────────────────────────────────────────
    if suffix in {".heic", ".heif"}:
        try:
            cmd = [EXIFTOOL_PATH or "exiftool", "-b", "-ThumbnailImage", str(path)]
            r = subprocess.run(cmd, capture_output=True, timeout=15)
            if r.returncode == 0 and r.stdout:
                img = PilImage.open(io.BytesIO(r.stdout))
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                return _pil_to_qpixmap(img)
        except Exception as exc:
            log.warning("HEIC thumb (%s): %s", path.name, exc)

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Writing changes  —  ONE ExifTool process for the entire batch
# ──────────────────────────────────────────────────────────────────────────────

def _gps_tags(lat: float, lon: float) -> dict:
    """EXIF GPS tags (for JPEG/TIFF/RAW/HEIC)."""
    return {
        "GPS:GPSLatitude":     abs(lat),
        "GPS:GPSLatitudeRef":  "N" if lat >= 0 else "S",
        "GPS:GPSLongitude":    abs(lon),
        "GPS:GPSLongitudeRef": "E" if lon >= 0 else "W",
    }


# Magic-byte signatures (12 bytes is enough for all we need)
_MAGIC: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff",           ".jpg"),   # JPEG
    (b"\x89PNG\r\n\x1a\n",     ".png"),   # PNG
    (b"II\x2a\x00",            ".tiff"),  # TIFF (little-endian)
    (b"MM\x00\x2a",            ".tiff"),  # TIFF (big-endian)
    (b"BM",                    ".bmp"),   # BMP
    # WebP: needs 12-byte check (RIFF????WEBP)
]


def _detect_format_ext(path: Path) -> str:
    """Detect actual file format from magic bytes; fall back to extension.

    File extensions can lie (e.g. a JPEG saved with a .png suffix).
    Reading the first 12 bytes is cheap and definitive for the common cases.
    For RAW/HEIC formats we trust the extension — cameras always write it
    correctly and their magic bytes are complex / model-specific.
    """
    try:
        with open(path, "rb") as fh:
            header = fh.read(12)
    except OSError:
        return path.suffix.lower()

    # WebP: RIFF<4-byte-size>WEBP
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"

    for magic, ext in _MAGIC:
        if header[: len(magic)] == magic:
            return ext

    # Unknown magic → trust the declared extension (handles RAW, HEIC, …)
    return path.suffix.lower()


def _tags_for_path(
    path: Path,
    gps: Optional[tuple[float, float]],
    date_taken: Optional[datetime],
    normalize_dates: bool,
) -> dict:
    """Return the format-appropriate ExifTool tag dict for *path*.

    Actual format is detected from magic bytes, not the extension, so
    misnamed files (e.g. a JPEG saved as .png) are handled correctly.

    Strategy by format
    ──────────────────
    JPEG / TIFF / RAW / HEIC  → EXIF GPS tags  +  AllDates shortcut
    PNG / WebP                 → XMP GPS tags   +  individual XMP date tags
                                 (PNG's EXIF eXIf chunk causes compat warnings;
                                  XMP via iTXt is universally accepted)
    BMP / other                → empty dict  (os.utime() handles timestamps)
    """
    ext = _detect_format_ext(path)

    # Warn once per file when extension and actual format disagree
    declared = path.suffix.lower()
    if ext != declared and declared in SUPPORTED_EXTENSIONS:
        log.warning(
            "'%s' has extension %s but magic bytes say %s — writing as %s",
            path.name, declared, ext, ext,
        )

    tags: dict = {}

    if ext in _EXIF_FORMATS:
        if gps:
            tags.update(_gps_tags(*gps))
        if normalize_dates and date_taken:
            # AllDates = ExifTool shortcut for DateTimeOriginal + CreateDate + ModifyDate
            tags["AllDates"] = date_taken.strftime(EXIF_DATE_FMT)

    elif ext in _XMP_FORMATS:
        if gps:
            lat, lon = gps
            # XMP GPS uses signed decimal degrees; ExifTool stores as "47.6N" / "122.3W"
            tags["XMP:GPSLatitude"]  = lat
            tags["XMP:GPSLongitude"] = lon
        if normalize_dates and date_taken:
            dt_str = date_taken.strftime(EXIF_DATE_FMT)
            tags["XMP:DateTimeOriginal"] = dt_str
            tags["XMP:CreateDate"]       = dt_str
            tags["XMP:ModifyDate"]       = dt_str

    # BMP / anything else → empty tags dict; only os.utime() will run below
    return tags


def _write_exif_for_item(
    item: PhotoItem,
    et: exiftool.ExifToolHelper,
    normalize_dates: bool,
) -> list[str]:
    """Write GPS and date tags for one item using an *already-open* et instance.

    Each physical file is written with format-appropriate tags (EXIF vs XMP).
    Returns warning strings (empty list = full success).
    """
    warnings: list[str] = []
    gps = item.pending.gps

    # Write format-specific metadata to each physical file
    for path in item.all_paths:
        tags = _tags_for_path(path, gps, item.date_taken, normalize_dates)
        if not tags:
            continue   # BMP or unknown format — nothing to write via ExifTool
        try:
            et.set_tags([str(path)], tags)
        except Exception as exc:
            msg = f"ExifTool write error on '{path.name}': {exc}"
            log.warning(msg)
            warnings.append(msg)

    # ── Filesystem modification time — works for ALL formats (incl. BMP) ──────
    if normalize_dates and item.date_taken:
        ts = item.date_taken.timestamp()
        for p in item.all_paths:
            try:
                os.utime(str(p), (ts, ts))
            except OSError as exc:
                log.warning("utime failed '%s': %s", p.name, exc)

    # Commit GPS to in-memory state
    if gps:
        item.gps_lat, item.gps_lon = gps
        item.pending.gps = None

    return warnings


def _rename_item(item: PhotoItem, append_original: bool) -> list[str]:
    """Rename all physical files for *item* to YYYYMMDD HHMMSS[+orig].ext."""
    warnings: list[str] = []
    if not item.date_taken:
        return warnings

    for path in list(item.all_paths):
        stem = item.date_taken.strftime("%Y%m%d %H%M%S")
        if append_original:
            stem = stem + " " + path.stem
        new_path = path.parent / (stem + path.suffix)

        if new_path == path:
            continue

        counter = 1
        while new_path.exists():
            new_path = path.parent / (f"{stem} ({counter}){path.suffix}")
            counter += 1

        try:
            path.rename(new_path)
            if path == item.display_path: item.display_path = new_path
            if path == item.jpeg_path:    item.jpeg_path    = new_path
            if path == item.raw_path:     item.raw_path     = new_path
        except OSError as exc:
            msg = f"Rename failed '{path.name}' → '{new_path.name}': {exc}"
            log.error(msg)
            warnings.append(msg)

    return warnings


def _copy_to_gpsok(item: PhotoItem) -> list[str]:
    """Copy all physical files for *item* into a 'GPSOK' subfolder.

    The item's path attributes are updated to point at the copies so
    subsequent EXIF writes and renames target the copies, leaving the
    original files completely untouched.
    """
    warnings: list[str] = []
    gpsok_dir = item.folder / "GPSOK"
    try:
        gpsok_dir.mkdir(exist_ok=True)
    except OSError as exc:
        return [f"Cannot create GPSOK folder '{gpsok_dir}': {exc}"]

    for path in list(item.all_paths):
        dest = gpsok_dir / path.name
        # Avoid silently overwriting an existing copy
        counter = 1
        while dest.exists():
            dest = gpsok_dir / f"{path.stem} ({counter}){path.suffix}"
            counter += 1
        try:
            shutil.copy2(str(path), str(dest))   # preserves timestamps + metadata
        except OSError as exc:
            warnings.append(f"Copy failed '{path.name}' → GPSOK: {exc}")
            continue
        # Redirect item path references to the new copy
        if path == item.display_path:
            item.display_path = dest
        if path == item.jpeg_path:
            item.jpeg_path = dest
        if path == item.raw_path:
            item.raw_path = dest

    return warnings


def apply_changes_batch(
    items: list[PhotoItem],
    normalize_dates: bool = False,
    do_rename: bool = False,
    append_original: bool = False,
    copy_to_gpsok: bool = False,
    progress_callback=None,
) -> list[str]:
    """Write GPS + dates for all *items* using a SINGLE ExifTool process.

    Opening one process for N photos instead of N processes is roughly
    10–50× faster for large batches (eliminates Perl startup per file).

    If *copy_to_gpsok* is True, files are first copied to a 'GPSOK'
    subfolder (next to each file's parent folder); all writes and renames
    then target the copies — originals are left completely unchanged.

    Renames happen after all ExifTool writes have completed.
    """
    all_warnings: list[str] = []
    total         = len(items)

    # ── Phase 0: Copy to GPSOK (if requested) — before any writes ────────────
    if copy_to_gpsok:
        for item in items:
            all_warnings.extend(_copy_to_gpsok(item))

    # ── Phase 1: EXIF writes (one ExifTool instance for everything) ───────────
    try:
        with _et_writer() as et:
            for n, item in enumerate(items, 1):
                if progress_callback:
                    progress_callback(n, total)
                all_warnings.extend(
                    _write_exif_for_item(item, et, normalize_dates)
                )
    except Exception as exc:
        all_warnings.append(f"Fatal batch write error: {exc}")
        return all_warnings   # Skip rename phase if ExifTool died

    # ── Phase 2: renames (after all writes succeed) ────────────────────────────
    if do_rename:
        for item in items:
            all_warnings.extend(_rename_item(item, append_original))

    return all_warnings


# ── Convenience single-item wrapper (kept for ad-hoc use) ─────────────────────
def apply_changes(
    item: PhotoItem,
    normalize_dates: bool = False,
    do_rename: bool = False,
    append_original: bool = False,
) -> list[str]:
    """Convenience wrapper — opens its own ExifTool process for one item."""
    warnings: list[str] = []
    try:
        with _et_writer() as et:
            warnings.extend(_write_exif_for_item(item, et, normalize_dates))
    except Exception as exc:
        warnings.append(f"ExifTool error: {exc}")
        return warnings
    if do_rename:
        warnings.extend(_rename_item(item, append_original))
    return warnings
