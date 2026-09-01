"""photo_manager.py — folder scanning, ExifTool I/O, video geotagging, format mismatch conversion, and network-safe writes."""

from __future__ import annotations

import io
import json
import logging
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Optional

import exiftool
import rawpy
from PIL import Image as PilImage, ImageOps

# Disable Pillow decompression bomb limits so large panoramas/gigapixel images load seamlessly
PilImage.MAX_IMAGE_PIXELS = None

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPixmap, QPainter, QLinearGradient, QColor, QFont

from .photo_item import (
    PhotoItem,
    RAW_EXTENSIONS,
    JPEG_EXTENSIONS,
    VIDEO_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    has_date_in_filename,
)
from .backup_manager import BackupService
from resources.theme import Colors

log = logging.getLogger(__name__)

THUMB_SIZE    = (220, 220)
EXIF_DATE_FMT = "%Y:%m:%d %H:%M:%S"

# Formats that fully support EXIF GPS + AllDates
_EXIF_FORMATS: frozenset[str] = (
    RAW_EXTENSIONS | JPEG_EXTENSIONS | frozenset({".tif", ".tiff", ".heic", ".heif"})
)
# Formats that use XMP (stored in iTXt / metadata chunk).
_XMP_FORMATS: frozenset[str] = frozenset({".png", ".webp"})

# Formats that use QuickTime/ISO-BMFF metadata atoms for GPS & dates
_VIDEO_FORMATS: frozenset[str] = frozenset({
    ".mp4", ".mov", ".m4v", ".3gp", ".qt", ".insv", ".avi", ".mkv", ".mts", ".m2ts"
})

# In-memory cache for reverse geocoding coordinates -> address
_GEOCODE_CACHE: dict[tuple[float, float], str] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Reverse Geocoding Helper
# ──────────────────────────────────────────────────────────────────────────────

def reverse_geocode(lat: float, lon: float) -> Optional[str]:
    """Reverse geocode coordinates to human-readable address with caching."""
    key = (round(lat, 5), round(lon, 5))
    if key in _GEOCODE_CACHE:
        return _GEOCODE_CACHE[key]

    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "GeoTagStudioPRO/2.0 (Photo Geotagger)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            addr = data.get("display_name")
            if addr:
                _GEOCODE_CACHE[key] = addr
                return addr
    except Exception as exc:
        log.debug("Reverse geocode (%f, %f) failed: %s", lat, lon, exc)

    return None


# ──────────────────────────────────────────────────────────────────────────────
# ExifTool detection (PyInstaller & Portable safe)
# ──────────────────────────────────────────────────────────────────────────────

def find_exiftool() -> Optional[str]:
    candidates = []

    # If running as PyInstaller frozen bundle
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).parent / "exiftool.exe")
        candidates.append(Path(sys.executable).parent / "exiftool")
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "exiftool.exe")

    # If running in development / script mode
    app_root = Path(__file__).resolve().parent.parent
    candidates.extend([
        app_root / "exiftool.exe",
        app_root / "exiftool",
        Path.cwd() / "exiftool.exe",
        Path.cwd() / "exiftool",
    ])

    for c in candidates:
        if c.exists() and c.is_file():
            return str(c.resolve())

    return shutil.which("exiftool") or shutil.which("exiftool.exe")


EXIFTOOL_PATH: Optional[str] = find_exiftool()


def _et_reader() -> exiftool.ExifToolHelper:
    """Persistent ExifTool process for fast reading with UTF-8 filename support."""
    kw: dict = {
        "common_args": [
            "-fast2",
            "-charset", "filename=utf8",
            "-m",
            "-api", "LargeFileSupport=1",
            "-n",
        ]
    }
    if EXIFTOOL_PATH:
        kw["executable"] = EXIFTOOL_PATH
    return exiftool.ExifToolHelper(**kw)


def _et_writer() -> exiftool.ExifToolHelper:
    """Persistent ExifTool process for writing.
    Uses -overwrite_original_in_place, UTF-8 filename support, and -m to support Windows UNC network paths.
    """
    kw: dict = {
        "common_args": [
            "-charset", "filename=utf8",
            "-m",
            "-api", "LargeFileSupport=1",
            "-overwrite_original_in_place",
        ]
    }
    if EXIFTOOL_PATH:
        kw["executable"] = EXIFTOOL_PATH
    return exiftool.ExifToolHelper(**kw)


# ──────────────────────────────────────────────────────────────────────────────
# Format Mismatch Detection & Conversion Helper
# ──────────────────────────────────────────────────────────────────────────────

def _detect_format_ext(path: Path) -> str:
    """Detect true binary container format from magic bytes."""
    try:
        with open(path, "rb") as fh:
            header = fh.read(32)
    except OSError:
        return path.suffix.lower()

    if header[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if header[:4] in (b"II\x2a\x00", b"MM\x00\x2a"):
        return ".tiff"
    if header[:2] == b"BM":
        return ".bmp"
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return ".webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        brand = header[8:12].lower()
        if brand in (b"heic", b"heix", b"heim", b"heis", b"mif1", b"msf1"):
            return ".heic"
        if brand in (b"avif", b"avis"):
            return ".avif"
        if brand in (b"mp41", b"mp42", b"isom", b"iso2", b"avc1", b"dash"):
            return ".mp4"
        if brand in (b"qt  ", b"moov"):
            return ".mov"
        if brand in (b"3gp4", b"3gp5", b"3gp6"):
            return ".3gp"

    return path.suffix.lower()


def check_format_mismatch(item: PhotoItem) -> None:
    """Check if the physical file is a PNG or format-mismatched file."""
    if item.is_video:
        return
    for p in item.all_paths:
        true_ext = _detect_format_ext(p)
        name_ext = p.suffix.lower()

        if true_ext == ".png" or name_ext == ".png" or ".heic." in p.name.lower() or (true_ext != name_ext and true_ext in (".jpg", ".png", ".webp", ".bmp", ".tiff")):
            item.format_mismatch = (true_ext, name_ext)
            log.debug("Format conversion needed on '%s': true=%s, filename_ext=%s",
                      p.name, true_ext, name_ext)
            return


def convert_to_jpeg_if_mismatched(
    item: PhotoItem, quality: int = 95, backup_service: Optional[BackupService] = None
) -> list[str]:
    """Convert PNG or format-mismatched image (e.g. .png, .heic.jpg) to clean JPEG and delete original source file."""
    warnings: list[str] = []
    if item.is_video:
        return warnings

    service = backup_service or BackupService()

    for path in list(item.all_paths):
        true_ext = _detect_format_ext(path)
        name_ext = path.suffix.lower()
        is_heic_double = ".heic." in path.name.lower()
        is_png = true_ext == ".png" or name_ext == ".png"

        if not is_png and not is_heic_double and true_ext == ".jpg" and name_ext in JPEG_EXTENSIONS:
            continue

        try:
            log.info("Converting file '%s' (true format: %s) to standard JPEG (quality=%d)...",
                     path.name, true_ext, quality)

            # Ensure pristine original backup exists before modifying/deleting source
            try:
                service.backup_file(path, action="Pre-Conversion Original Backup")
            except Exception as b_exc:
                log.warning("Pre-conversion backup note for '%s': %s", path.name, b_exc)

            with PilImage.open(path) as img:
                img = ImageOps.exif_transpose(img) or img
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    # Composite onto clean white background to avoid black background on transparent PNGs
                    bg = PilImage.new("RGB", img.size, (255, 255, 255))
                    if img.mode != "RGBA":
                        img = img.convert("RGBA")
                    bg.paste(img, mask=img.split()[3])
                    rgb = bg
                else:
                    rgb = img.convert("RGB")

                clean_name = path.name
                if ".heic." in clean_name.lower():
                    clean_name = clean_name.replace(".heic.", ".").replace(".HEIC.", ".")
                elif path.suffix.lower() != ".jpg":
                    clean_name = path.stem + ".jpg"

                target_path = path.parent / clean_name
                rgb.save(target_path, "JPEG", quality=quality, subsampling=0)

                # Verify target exists and delete original source file if paths differ
                if target_path != path and path.exists() and target_path.exists() and target_path.stat().st_size > 0:
                    try:
                        path.unlink()
                        log.info("Deleted original PNG source file: '%s'", path.name)
                    except Exception as del_exc:
                        log.warning("Failed to delete source PNG '%s': %s", path.name, del_exc)

                if path == item.display_path: item.display_path = target_path
                if path == item.jpeg_path:    item.jpeg_path    = target_path
                if path == item.raw_path:     item.raw_path     = target_path

            item.format_mismatch = None
            log.info("Successfully converted '%s' -> '%s' (JPEG 95%%)", path.name, target_path.name)
        except Exception as exc:
            msg = f"Failed to convert '{path.name}' to JPEG: {exc}"
            log.error(msg)
            warnings.append(msg)

    return warnings


# ──────────────────────────────────────────────────────────────────────────────
# Folder scanning & RAW+JPEG pairing (Single-pass fast traversal)
# ──────────────────────────────────────────────────────────────────────────────

def scan_folder(folder: Path) -> list[PhotoItem]:
    """Recursively scan *folder* in a single pass, pair RAW+JPEG by stem, return PhotoItems."""
    if not folder.is_dir():
        raise NotADirectoryError(folder)

    seen: set[str] = set()
    all_files: list[Path] = []

    for root, dirs, files in os.walk(str(folder)):
        dirs[:] = [d for d in dirs if d.upper() not in ("GPSOK", "BACKUPS", ".GIT", ".CLAUDE")]

        for fname in files:
            p = Path(root) / fname
            suffix = p.suffix.lower()
            if suffix in SUPPORTED_EXTENSIONS or ".heic" in p.name.lower():
                canon = str(p.resolve()).lower()
                if canon not in seen:
                    seen.add(canon)
                    all_files.append(p)

    all_files.sort(key=lambda p: (str(p.parent).lower(), p.stem.lower(), p.suffix.lower()))

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

        min_pairs = min(len(jpegs), len(raws))
        for idx in range(min_pairs):
            items.append(PhotoItem(
                display_path=jpegs[idx],
                jpeg_path=jpegs[idx],
                raw_path=raws[idx],
            ))

        for j in jpegs[min_pairs:]:
            items.append(PhotoItem(display_path=j, jpeg_path=j))

        for r in raws[min_pairs:]:
            items.append(PhotoItem(display_path=r, raw_path=r))

        for o in other:
            items.append(PhotoItem(display_path=o))

    # Initialize fallback date_taken and detect format mismatches
    for it in items:
        try:
            mtime = it.display_path.stat().st_mtime
            it.date_taken = datetime.fromtimestamp(mtime)
        except Exception:
            pass
        check_format_mismatch(it)

    items.sort(key=lambda i: (str(i.folder).lower(), i.display_name.lower()))
    log.info("Scanned %s -> %d items (%d files)",
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
    return None


def _parse_gps_coord(value, ref: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if ref and str(ref).strip().upper() in ("S", "W"):
        v = -abs(v)
    return v


def _parse_duration(raw) -> Optional[float]:
    """Parse duration in seconds from numeric value or string like '00:01:24' / '12.5 s'."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    s = str(raw).strip().lower().replace("s", "").strip()
    if ":" in s:
        parts = s.split(":")
        try:
            if len(parts) == 3:
                return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
            elif len(parts) == 2:
                return float(parts[0]) * 60 + float(parts[1])
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


def _parse_video_gps_string(coord_str: str) -> Optional[tuple[float, float]]:
    """Parse video GPS coordinates from strings like '+03.4608-076.5325+000.000/' or '3.4608, -76.5325, 0'."""
    if not coord_str or not isinstance(coord_str, str):
        return None
    s = coord_str.strip()
    # Comma separated "lat, lon, alt"
    if "," in s:
        parts = s.split(",")
        try:
            return (float(parts[0].strip()), float(parts[1].strip()))
        except Exception:
            pass

    # ISO 6709 string like +37.7749-122.4194/ or +03.4608-076.5325+000.000/
    import re
    match = re.match(r"([+-]\d+(?:\.\d+)?)([+-]\d+(?:\.\d+)?)", s)
    if match:
        try:
            return (float(match.group(1)), float(match.group(2)))
        except Exception:
            pass
    return None


def load_metadata(items: list[PhotoItem]) -> None:
    """Batch-read EXIF/QuickTime/XMP date, GPS, and camera/video metadata in one ExifTool call."""
    if not items:
        return

    path_map: dict[str, PhotoItem] = {}
    paths_to_query: list[str] = []
    for item in items:
        p_str = str(item.display_path)
        path_map[p_str] = item
        paths_to_query.append(p_str)

    tags = [
        "DateTimeOriginal", "CreateDate", "ModifyDate",
        "Keys:CreationDate", "QuickTime:CreateDate", "MediaCreateDate", "TrackCreateDate",
        "GPSLatitude", "GPSLatitudeRef", "GPSLongitude", "GPSLongitudeRef",
        "Keys:GPSCoordinates", "UserData:GPSCoordinates", "QuickTime:GPSCoordinates",
        "Make", "Model", "LensModel", "Lens", "CompressorName", "HandlerDescription",
        "ISO", "FNumber", "ExposureTime", "FocalLength",
        "ImageWidth", "ImageHeight", "ExifImageWidth", "ExifImageHeight",
        "SourceImageWidth", "SourceImageHeight",
        "Duration", "MediaDuration", "TrackDuration",
        "FileSize", "Orientation",
    ]

    try:
        with _et_reader() as et:
            results = et.get_tags(paths_to_query, tags)
    except Exception as exc:
        log.error("ExifTool metadata read failed: %s", exc)
        return

    for meta in results:
        src_file = meta.get("SourceFile")
        item = path_map.get(src_file)
        if not item:
            for k, it in path_map.items():
                if Path(k).name == Path(src_file).name:
                    item = it
                    break
        if not item:
            continue

        raw_date = (
            meta.get("DateTimeOriginal")
            or meta.get("Keys:CreationDate")
            or meta.get("CreateDate")
            or meta.get("QuickTime:CreateDate")
            or meta.get("MediaCreateDate")
            or meta.get("ModifyDate")
        )
        parsed_dt = _parse_exif_date(raw_date)
        if parsed_dt:
            item.date_taken = parsed_dt

        # GPS extraction (standard EXIF or QuickTime video tags)
        lat = _parse_gps_coord(meta.get("GPSLatitude"), meta.get("GPSLatitudeRef"))
        lon = _parse_gps_coord(meta.get("GPSLongitude"), meta.get("GPSLongitudeRef"))

        if lat is None or lon is None:
            video_gps_raw = (
                meta.get("Keys:GPSCoordinates")
                or meta.get("UserData:GPSCoordinates")
                or meta.get("QuickTime:GPSCoordinates")
            )
            if video_gps_raw:
                vg = _parse_video_gps_string(str(video_gps_raw))
                if vg:
                    lat, lon = vg

        item.gps_lat = lat
        item.gps_lon = lon

        # Video duration
        dur_raw = meta.get("Duration") or meta.get("MediaDuration") or meta.get("TrackDuration")
        item.duration_sec = _parse_duration(dur_raw)

        # Camera & Device info
        item.camera_make  = meta.get("Make")
        item.camera_model = meta.get("Model") or meta.get("CompressorName") or meta.get("HandlerDescription")
        item.lens_model   = meta.get("LensModel") or meta.get("Lens")
        item.iso          = int(meta["ISO"]) if meta.get("ISO") else None
        item.f_number     = float(meta["FNumber"]) if meta.get("FNumber") else None

        exp = meta.get("ExposureTime")
        item.exposure_time = str(exp) if exp else None

        focal = meta.get("FocalLength")
        item.focal_length  = f"{focal}mm" if focal else None

        w = (
            meta.get("ImageWidth")
            or meta.get("ExifImageWidth")
            or meta.get("SourceImageWidth")
        )
        h = (
            meta.get("ImageHeight")
            or meta.get("ExifImageHeight")
            or meta.get("SourceImageHeight")
        )
        if w and h:
            try:
                item.image_width = int(w)
                item.image_height = int(h)
            except Exception:
                pass

        if meta.get("FileSize"):
            try:
                item.file_size = int(meta["FileSize"])
            except Exception:
                pass

        item._metadata_loaded = True


# ──────────────────────────────────────────────────────────────────────────────
# Thumbnail generation (with Automatic EXIF Orientation & Video Poster Frame)
# ──────────────────────────────────────────────────────────────────────────────

from .thumbnail_cache import thumbnail_cache


def _pil_to_qimage(img: PilImage.Image) -> QImage:
    img = img.convert("RGB")
    data = img.tobytes("raw", "RGB")
    qi = QImage(data, img.width, img.height, img.width * 3, QImage.Format.Format_RGB888)
    return qi.copy()


def generate_thumbnail_image(item: PhotoItem) -> Optional[QImage]:
    """Generate a THUMB_SIZE QImage for *item* (Photos & Videos) with fast disk caching."""
    path   = item.display_path
    suffix = path.suffix.lower()

    # 1. Check disk cache first (instant 0.05ms retrieval)
    cached = thumbnail_cache.get_cached_image(path)
    if cached:
        return cached

    # ── Standard raster → Pillow with automatic EXIF orientation transposition ──
    if suffix in JPEG_EXTENSIONS | {".tif", ".tiff", ".png", ".bmp", ".webp"} or ".heic" in path.name.lower():
        try:
            with PilImage.open(path) as img:
                img = ImageOps.exif_transpose(img) or img
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                thumbnail_cache.save_cached_image(path, img)
                return _pil_to_qimage(img)
        except Exception as exc:
            log.warning("Pillow thumb (%s): %s", path.name, exc)

    # ── RAW → rawpy → Pillow ─────────────────────────────────────────────────
    if suffix in RAW_EXTENSIONS:
        try:
            cmd = [EXIFTOOL_PATH or "exiftool", "-b", "-PreviewImage", "-LargeThumbnailImage", str(path)]
            r = subprocess.run(cmd, capture_output=True, timeout=8)
            if r.returncode == 0 and r.stdout:
                img = PilImage.open(io.BytesIO(r.stdout))
                img = ImageOps.exif_transpose(img) or img
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                thumbnail_cache.save_cached_image(path, img)
                return _pil_to_qimage(img)
        except Exception:
            pass

        try:
            with rawpy.imread(str(path)) as raw:
                rgb = raw.postprocess(
                    use_camera_wb=True, half_size=True,
                    no_auto_bright=False, output_bps=8,
                )
            img = PilImage.fromarray(rgb)
            img = ImageOps.exif_transpose(img) or img
            img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
            thumbnail_cache.save_cached_image(path, img)
            return _pil_to_qimage(img)
        except Exception as exc:
            log.warning("rawpy thumb (%s): %s", path.name, exc)

    # ── HEIC / HEIF / Double Extension → ExifTool ─────────────────────────────
    if suffix in {".heic", ".heif"} or ".heic" in path.name.lower():
        try:
            cmd = [EXIFTOOL_PATH or "exiftool", "-b", "-ThumbnailImage", "-PreviewImage", str(path)]
            r = subprocess.run(cmd, capture_output=True, timeout=8)
            if r.returncode == 0 and r.stdout:
                img = PilImage.open(io.BytesIO(r.stdout))
                img = ImageOps.exif_transpose(img) or img
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                thumbnail_cache.save_cached_image(path, img)
                return _pil_to_qimage(img)
        except Exception as exc:
            log.warning("HEIC thumb (%s): %s", path.name, exc)

    # ── Videos (.mp4, .mov, .m4v, .mkv, .avi, etc.) ───────────────────────────
    if suffix in VIDEO_EXTENSIONS:
        # 1. Extract genuine video frame using high-speed cv2 VideoCapture
        try:
            import cv2
            cap = cv2.VideoCapture(str(path.resolve()))
            if cap.isOpened():
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 1
                # Seek to 0.5s or frame 1 to avoid black initial frames
                target_frame = min(int(fps * 0.5), max(0, int(frame_count - 1)))
                cap.set(cv2.CAP_PROP_POS_FRAMES, target_frame)

                ret, frame = cap.read()
                if not ret or frame is None:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()
                cap.release()

                if ret and frame is not None:
                    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = PilImage.fromarray(rgb_frame)
                    img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                    thumbnail_cache.save_cached_image(path, img)
                    return _pil_to_qimage(img)
        except Exception as exc:
            log.debug("cv2 video frame extraction (%s): %s", path.name, exc)

        # 2. Try extracting embedded cover art / poster frame with ExifTool
        try:
            cmd = [
                EXIFTOOL_PATH or "exiftool",
                "-b",
                "-ThumbnailImage",
                "-PreviewImage",
                "-CoverArt",
                "-PosterFrame",
                str(path)
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=6)
            if r.returncode == 0 and r.stdout:
                img = PilImage.open(io.BytesIO(r.stdout))
                img = ImageOps.exif_transpose(img) or img
                img.thumbnail(THUMB_SIZE, PilImage.LANCZOS)
                thumbnail_cache.save_cached_image(path, img)
                return _pil_to_qimage(img)
        except Exception as exc:
            log.debug("ExifTool video preview extraction (%s): %s", path.name, exc)

        # 3. Fallback Sleek Cyberpunk Poster Frame
        pm = QPixmap(THUMB_SIZE[0], THUMB_SIZE[1])
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        grad = QLinearGradient(0, 0, THUMB_SIZE[0], THUMB_SIZE[1])
        grad.setColorAt(0.0, QColor("#1e1b4b"))  # deep indigo
        grad.setColorAt(1.0, QColor("#090d16"))  # cyber dark
        painter.fillRect(0, 0, THUMB_SIZE[0], THUMB_SIZE[1], grad)

        # Large video icon
        painter.setFont(QFont("Segoe UI Emoji", 38))
        painter.drawText(QRect(0, 36, THUMB_SIZE[0], 55), Qt.AlignmentFlag.AlignCenter, "🎬")

        # Video Format Title
        painter.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        painter.setPen(QColor(Colors.CYAN_LIGHT))
        fmt_text = suffix.lstrip(".").upper()
        painter.drawText(QRect(0, 100, THUMB_SIZE[0], 24), Qt.AlignmentFlag.AlignCenter, f"{fmt_text} VIDEO")

        if item.duration_str:
            painter.setFont(QFont("Segoe UI", 9))
            painter.setPen(QColor(Colors.TEXT_MUTED))
            painter.drawText(QRect(0, 126, THUMB_SIZE[0], 20), Qt.AlignmentFlag.AlignCenter, f"⏱ {item.duration_str}")

        painter.end()
        qimg = pm.toImage()

        # Cache the generated poster frame so subsequent loads are instant
        try:
            cache_file = thumbnail_cache.cache_dir / thumbnail_cache._cache_filename(path)
            pm.save(str(cache_file), "JPEG", 85)
        except Exception:
            pass
        return qimg

    return None


# ──────────────────────────────────────────────────────────────────────────────
# Writing changes — ONE ExifTool process for the entire batch
# ──────────────────────────────────────────────────────────────────────────────

def _gps_tags(lat: float, lon: float) -> dict:
    return {
        "GPSLatitude":     abs(lat),
        "GPSLatitudeRef":  "N" if lat >= 0 else "S",
        "GPSLongitude":    abs(lon),
        "GPSLongitudeRef": "E" if lon >= 0 else "W",
    }


def _video_gps_tags(lat: float, lon: float) -> dict:
    """Generate QuickTime and ISO-BMFF GPS tags for MP4/MOV videos."""
    iso_gps = f"{lat:+.6f}{lon:+.6f}+000.000/"
    coord_str = f"{lat:.6f}, {lon:.6f}, 0"
    return {
        "Keys:GPSCoordinates": coord_str,
        "UserData:GPSCoordinates": coord_str,
        "QuickTime:GPSCoordinates": iso_gps,
        "GPSLatitude":     abs(lat),
        "GPSLatitudeRef":  "N" if lat >= 0 else "S",
        "GPSLongitude":    abs(lon),
        "GPSLongitudeRef": "E" if lon >= 0 else "W",
    }


def _tags_for_path(
    path: Path,
    gps: Optional[tuple[float, float]],
    date_taken: Optional[datetime],
    normalize_dates: bool,
    strip_gps: bool = False,
) -> dict:
    ext = _detect_format_ext(path)
    tags: dict = {}

    # Videos (.mp4, .mov, .m4v, .3gp, etc.)
    if ext in _VIDEO_FORMATS or path.suffix.lower() in VIDEO_EXTENSIONS:
        if strip_gps:
            tags["Keys:GPSCoordinates"] = ""
            tags["UserData:GPSCoordinates"] = ""
        elif gps:
            tags.update(_video_gps_tags(*gps))
        if normalize_dates and date_taken:
            dt_str = date_taken.strftime(EXIF_DATE_FMT)
            tags["QuickTime:CreateDate"] = dt_str
            tags["QuickTime:ModifyDate"] = dt_str
            tags["Keys:CreationDate"]   = dt_str

    # Standard EXIF photos
    elif ext in _EXIF_FORMATS:
        if strip_gps:
            tags["GPS:all"] = ""
        elif gps:
            tags.update(_gps_tags(*gps))
        if normalize_dates and date_taken:
            tags["AllDates"] = date_taken.strftime(EXIF_DATE_FMT)

    # XMP formats
    elif ext in _XMP_FORMATS:
        if strip_gps:
            tags["XMP:GPSLatitude"]  = ""
            tags["XMP:GPSLongitude"] = ""
        elif gps:
            tags["XMP:GPSLatitude"]  = gps[0]
            tags["XMP:GPSLongitude"] = gps[1]
        if normalize_dates and date_taken:
            dt_str = date_taken.strftime(EXIF_DATE_FMT)
            tags["XMP:DateTimeOriginal"] = dt_str
            tags["XMP:CreateDate"]       = dt_str
            tags["XMP:ModifyDate"]       = dt_str

    return tags


def _fix_missing_jpeg_eoi(path: Path) -> bool:
    """If a JPEG file lacks the End Of Image marker (0xFF 0xD9) due to Samsung SEF trailer or camera truncation, append it."""
    try:
        if path.suffix.lower() not in JPEG_EXTENSIONS:
            return False
        size = path.stat().st_size
        if size < 4:
            return False
        with open(path, "rb") as f:
            f.seek(max(0, size - 128))
            tail = f.read()
        if b"\xff\xd9" not in tail:
            log.info("Missing JPEG EOI marker (0xFF 0xD9) detected on '%s'. Appending EOI marker to fix ExifTool write compatibility...", path.name)
            with open(path, "ab") as f:
                f.write(b"\xff\xd9")
            return True
    except Exception as exc:
        log.warning("Failed checking/appending EOI marker on '%s': %s", path.name, exc)
    return False


def _repair_jpeg_metadata(path: Path) -> bool:
    """Rebuild corrupt EXIF/IFD structure (e.g. OtherImageStart data errors or missing EOI) using ExifTool clean rebuild."""
    if not EXIFTOOL_PATH or path.suffix.lower() not in JPEG_EXTENSIONS:
        return False

    # 1. First ensure JPEG has a valid End Of Image marker
    fixed_eoi = _fix_missing_jpeg_eoi(path)

    try:
        log.info("Attempting ExifTool metadata structure rebuild on corrupt file '%s'...", path.name)
        cmd = [
            EXIFTOOL_PATH,
            "-all=",
            "-tagsfromfile", "@",
            "-all:all",
            "-unsafe",
            "-icc_profile",
            "-overwrite_original_in_place",
            "-m",
            str(path),
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            log.info("Successfully rebuilt metadata structure on '%s'", path.name)
            return True
        else:
            log.warning("ExifTool rebuild output on '%s': %s (fixed_eoi=%s)", path.name, res.stderr.strip(), fixed_eoi)
            return fixed_eoi
    except Exception as exc:
        log.warning("Metadata repair exception on '%s': %s", path.name, exc)
        return fixed_eoi


def _repair_truncated_mp4(path: Path) -> bool:
    """Scan MP4/MOV top-level atoms and truncate unclosed/garbage trailing bytes (e.g. Truncated atom errors)."""
    try:
        size = path.stat().st_size
        if size < 16:
            return False

        with open(path, "rb") as f:
            pos = 0
            last_valid_end = 0
            while pos + 8 <= size:
                f.seek(pos)
                hdr = f.read(8)
                if len(hdr) < 8:
                    break
                box_len = int.from_bytes(hdr[:4], "big")
                box_type = hdr[4:8]

                if box_len == 0:
                    last_valid_end = size
                    break
                elif box_len == 1:
                    ext_hdr = f.read(8)
                    if len(ext_hdr) < 8:
                        break
                    box_len = int.from_bytes(ext_hdr, "big")

                if box_len < 8 or pos + box_len > size:
                    # Truncated box header or trailing incomplete bytes
                    break

                pos += box_len
                last_valid_end = pos

            if 0 < last_valid_end < size:
                log.info(
                    "Truncated atom detected on '%s' (%d bytes of trailing garbage). Truncating to %d valid bytes...",
                    path.name, size - last_valid_end, last_valid_end
                )
                with open(path, "r+b") as fw:
                    fw.seek(last_valid_end)
                    fw.truncate()
                return True
    except Exception as exc:
        log.warning("MP4 atom repair failed on '%s': %s", path.name, exc)
    return False


def _write_exif_for_item(
    item: PhotoItem,
    et: exiftool.ExifToolHelper,
    normalize_dates: bool,
) -> list[str]:
    warnings: list[str] = []
    gps = item.pending.gps
    strip_gps = item.pending.strip_gps
    write_failed = False

    for path in item.all_paths:
        tags = _tags_for_path(path, gps, item.date_taken, normalize_dates, strip_gps=strip_gps)
        if not tags:
            continue

        p_str = str(path)
        log.debug("ExifTool writing tags to '%s': %s", p_str, tags)

        written_ok = False
        try:
            et.set_tags([p_str], tags)
            log.info("ExifTool updated tags on '%s'", path.name)
            written_ok = True
        except Exception as exc:
            err_details = str(exc)
            if hasattr(et, "last_stderr") and et.last_stderr:
                err_details += f" | Stderr: {et.last_stderr.strip()}"

            log.warning("Initial ExifTool write error on '%s': %s. Attempting self-healing repair...", path.name, err_details)

            # Ensure helper is alive or restart it
            if not getattr(et, "running", False):
                try:
                    et.run()
                except Exception:
                    pass

            # Attempt self-healing repair based on format
            repaired = False
            if path.suffix.lower() in VIDEO_EXTENSIONS or _detect_format_ext(path) in _VIDEO_FORMATS:
                repaired = _repair_truncated_mp4(path)
            else:
                repaired = _repair_jpeg_metadata(path)

            if repaired:
                try:
                    et.set_tags([p_str], tags)
                    log.info("✓ ExifTool successfully updated tags on '%s' after container repair!", path.name)
                    written_ok = True
                except Exception as retry_exc:
                    err_details = f"After repair retry failed: {retry_exc}"

            if not written_ok:
                write_failed = True
                msg = f"ExifTool write failed on '{path.name}': {err_details}"
                log.error(msg)
                warnings.append(msg)

                if not getattr(et, "running", False):
                    try:
                        et.run()
                    except Exception:
                        pass

    # Filesystem timestamp modification
    if normalize_dates and item.date_taken:
        ts = item.date_taken.timestamp()
        for p in item.all_paths:
            try:
                os.utime(str(p), (ts, ts))
            except OSError as exc:
                log.warning("utime failed '%s': %s", p.name, exc)

    if not write_failed:
        if strip_gps:
            item.gps_lat = None
            item.gps_lon = None
            item.pending.strip_gps = False
        elif gps:
            item.gps_lat, item.gps_lon = gps
            item.pending.gps = None

    return warnings


def _rename_item_group(
    item: PhotoItem, append_original: bool, smart_undated_only: bool = False
) -> list[str]:
    """Rename companion files of an item atomically preserving matching stems."""
    warnings: list[str] = []

    # If Smart Rename (Undated Only) is active, skip if filename already contains a date
    if smart_undated_only and item.has_date_in_name:
        log.info("Smart Rename: Skipped '%s' (already contains date format)", item.display_name)
        return warnings

    dt = item.date_taken
    if not dt:
        try:
            mtime = item.display_path.stat().st_mtime
            dt = datetime.fromtimestamp(mtime)
        except Exception:
            pass

    if not dt:
        msg = f"Cannot rename '{item.display_name}': no EXIF date or file timestamp available."
        log.warning(msg)
        warnings.append(msg)
        return warnings

    base_stem = dt.strftime("%Y%m%d %H%M%S")
    parent_dir = item.folder

    # Determine collision counter across all companions in the item
    counter = 0
    while True:
        suffix_count = f" ({counter})" if counter > 0 else ""
        any_conflict = False
        for path in item.all_paths:
            stem_candidate = base_stem
            if append_original:
                stem_candidate = f"{base_stem} {path.stem}"
            target = parent_dir / f"{stem_candidate}{suffix_count}{path.suffix}"
            if target.exists() and target != path:
                any_conflict = True
                break
        if not any_conflict:
            break
        counter += 1

    suffix_count = f" ({counter})" if counter > 0 else ""

    # Execute renames
    for path in list(item.all_paths):
        stem_target = base_stem
        if append_original:
            stem_target = f"{base_stem} {path.stem}"
        new_path = parent_dir / f"{stem_target}{suffix_count}{path.suffix}"

        if new_path == path:
            continue

        try:
            shutil.move(str(path), str(new_path))
            log.info("Renamed '%s' -> '%s'", path.name, new_path.name)
            if path == item.display_path: item.display_path = new_path
            if path == item.jpeg_path:    item.jpeg_path    = new_path
            if path == item.raw_path:     item.raw_path     = new_path
        except OSError as exc:
            msg = f"Rename failed '{path.name}' -> '{new_path.name}': {exc}"
            log.error(msg)
            warnings.append(msg)

    return warnings


def apply_changes_batch(
    items: list[PhotoItem],
    normalize_dates: bool = False,
    do_rename: bool = False,
    append_original: bool = False,
    smart_undated_only: bool = False,
    convert_mismatched: bool = False,
    backup_service: Optional[BackupService] = None,
    progress_callback=None,
) -> list[str]:
    """Write GPS + dates for all *items* (Photos & Videos) after backing up original files."""
    all_warnings: list[str] = []
    total = len(items)
    service = backup_service or BackupService()

    log.info("apply_changes_batch starting for %d items (norm_dates=%s, do_rename=%s, smart_undated=%s, append_orig=%s)",
             total, normalize_dates, do_rename, smart_undated_only, append_original)

    # Ensure all items have date_taken populated from file mtime before EXIF write touches timestamps
    for it in items:
        if not it.date_taken:
            try:
                mtime = it.display_path.stat().st_mtime
                it.date_taken = datetime.fromtimestamp(mtime)
            except Exception:
                pass

    # ── Phase 0: Backup pristine original files to directory mirror ──────────
    all_physical_files = []
    for it in items:
        all_physical_files.extend(it.all_paths)

    if progress_callback:
        try:
            progress_callback(0, total, f"{len(all_physical_files)} physical file(s)", "🛡️ Backing up pristine original files...")
        except TypeError:
            progress_callback(0, total)

    try:
        service.backup_files(all_physical_files, action="Pre-Write Original Backup")
        log.info("Pre-write backup complete for %d physical files", len(all_physical_files))
    except Exception as exc:
        msg = f"Backup warning: {exc}"
        log.warning(msg)
        all_warnings.append(msg)

    # ── Phase 0.5: Convert format-mismatched files & PNGs to clean JPEG ──────
    for item in items:
        if convert_mismatched or item.is_png or item.has_format_mismatch or ".heic." in item.display_name.lower():
            if progress_callback:
                try:
                    progress_callback(0, total, item.display_name, "🔄 Converting PNG to clean JPEG...")
                except TypeError:
                    progress_callback(0, total)
            all_warnings.extend(convert_to_jpeg_if_mismatched(item, quality=95, backup_service=service))

    # ── Phase 1: EXIF / Video QuickTime writes ────────────────────────────────
    try:
        with _et_writer() as et:
            for n, item in enumerate(items, 1):
                if progress_callback:
                    desc = "📍 Writing QuickTime / Video GPS..." if item.is_video else "📍 Writing EXIF / Photo GPS..."
                    if item.pending.strip_gps:
                        desc = "🗑️ Erasing GPS coordinates..."
                    elif normalize_dates and not item.pending.gps:
                        desc = "⏱️ Normalizing timestamps..."
                    try:
                        progress_callback(n, total, item.display_name, desc)
                    except TypeError:
                        progress_callback(n, total)

                all_warnings.extend(
                    _write_exif_for_item(item, et, normalize_dates)
                )
    except Exception as exc:
        msg = f"Fatal batch write error: {exc}"
        log.critical(msg, exc_info=True)
        all_warnings.append(msg)
        return all_warnings

    # ── Phase 2: Renames (with Smart Undated-Only option) ──────────────────────
    if do_rename:
        log.info("Renaming %d photo item groups (smart_undated_only=%s)...", len(items), smart_undated_only)
        for n, item in enumerate(items, 1):
            if progress_callback:
                try:
                    progress_callback(n, total, item.display_name, "🏷️ Renaming file...")
                except TypeError:
                    progress_callback(n, total)
            all_warnings.extend(_rename_item_group(item, append_original, smart_undated_only))

    log.info("apply_changes_batch finished with %d warnings", len(all_warnings))
    return all_warnings
