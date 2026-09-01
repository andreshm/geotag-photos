"""workers.py — QThread-based background workers with multi-threaded thumbnail rendering, video support, and smart rename."""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal, QObject
from PySide6.QtGui import QImage

from .photo_item import PhotoItem
from .photo_manager import scan_folder, load_metadata, generate_thumbnail_image, apply_changes_batch
from .backup_manager import BackupService

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Folder scan + metadata worker
# ──────────────────────────────────────────────────────────────────────────────

class ScanWorker(QObject):
    """Scans folder(s) in single pass, loads EXIF/video metadata in batches, emits discovered items."""

    item_ready = Signal(object)      # PhotoItem
    scan_done  = Signal(int)         # total count
    error      = Signal(str)

    def __init__(self, folders: list[Path] | Path, parent=None):
        super().__init__(parent)
        if isinstance(folders, Path):
            self._folders = [folders]
        else:
            self._folders = list(folders)
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        items = []
        try:
            for f in self._folders:
                if self._cancelled:
                    return
                f_items = scan_folder(f)
                items.extend(f_items)
        except Exception as exc:
            self.error.emit(str(exc))
            return

        if self._cancelled:
            return

        # Deduplicate logical items if paths overlap
        seen_paths = set()
        unique_items = []
        for it in items:
            key = str(it.display_path.resolve())
            if key not in seen_paths:
                seen_paths.add(key)
                unique_items.append(it)
        items = unique_items

        # Load EXIF and Video metadata in chunks of 50
        BATCH = 50
        for start in range(0, len(items), BATCH):
            if self._cancelled:
                return
            batch = items[start : start + BATCH]
            try:
                load_metadata(batch)
            except Exception as exc:
                log.warning("Metadata chunk failed: %s", exc)

            for item in batch:
                if self._cancelled:
                    return
                self.item_ready.emit(item)

        self.scan_done.emit(len(items))


class ScanThread(QThread):
    item_ready = Signal(object)
    scan_done  = Signal(int)
    error      = Signal(str)

    def __init__(self, folders: list[Path] | Path, parent=None):
        super().__init__(parent)
        self._worker = ScanWorker(folders)
        self._worker.item_ready.connect(self.item_ready)
        self._worker.scan_done.connect(self.scan_done)
        self._worker.error.connect(self.error)

    def run(self):
        self._worker.run()

    def cancel(self):
        self._worker.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# Multi-Threaded Thumbnail Loader Worker
# ──────────────────────────────────────────────────────────────────────────────

class ThumbnailWorker(QObject):
    """Multi-threaded thumbnail generation using ThreadPoolExecutor and thread-safe QImage."""

    thumbnail_image_ready = Signal(object, object)   # (PhotoItem, QImage)
    all_done              = Signal()

    def __init__(self, items: list[PhotoItem], parent=None):
        super().__init__(parent)
        self._items = items
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def _process_item(self, item: PhotoItem) -> tuple[PhotoItem, Optional[QImage]]:
        if self._cancelled:
            return item, None
        try:
            img = generate_thumbnail_image(item)
            return item, img
        except Exception as exc:
            log.warning("Thumb error %s: %s", item.display_name, exc)
            return item, None

    def run(self):
        items_to_process = [i for i in self._items if i.thumbnail is None]
        if not items_to_process:
            self.all_done.emit()
            return

        max_workers = min(8, max(2, os.cpu_count() or 4))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_item = {
                executor.submit(self._process_item, item): item
                for item in items_to_process
            }

            for future in as_completed(future_to_item):
                if self._cancelled:
                    break
                try:
                    item, qimg = future.result()
                    if qimg:
                        self.thumbnail_image_ready.emit(item, qimg)
                except Exception as exc:
                    log.warning("Thumbnail future failed: %s", exc)

        self.all_done.emit()


class ThumbnailThread(QThread):
    thumbnail_image_ready = Signal(object, object)   # (PhotoItem, QImage)
    all_done              = Signal()

    def __init__(self, items: list[PhotoItem], parent=None):
        super().__init__(parent)
        self._worker = ThumbnailWorker(items)
        self._worker.thumbnail_image_ready.connect(self.thumbnail_image_ready)
        self._worker.all_done.connect(self.all_done)

    def run(self):
        self._worker.run()

    def cancel(self):
        self._worker.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# Save / Apply Changes Worker (with Backup Engine, Format Conversion & Smart Rename)
# ──────────────────────────────────────────────────────────────────────────────

class SaveWorker(QObject):
    """Backs up files, converts mismatched formats, and writes EXIF/GPS/Date changes in background."""

    progress = Signal(int, int, str, str)    # (current, total, filename, stage)
    done     = Signal(list)                  # list[str] warnings
    error    = Signal(str)

    def __init__(
        self,
        items: list[PhotoItem],
        normalize_dates: bool,
        do_rename: bool,
        append_original: bool,
        smart_undated_only: bool = False,
        convert_mismatched: bool = False,
        backup_service: Optional[BackupService] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._items = items
        self._normalize_dates = normalize_dates
        self._do_rename = do_rename
        self._append_original = append_original
        self._smart_undated_only = smart_undated_only
        self._convert_mismatched = convert_mismatched
        self._backup_service = backup_service or BackupService()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            warnings = apply_changes_batch(
                self._items,
                normalize_dates=self._normalize_dates,
                do_rename=self._do_rename,
                append_original=self._append_original,
                smart_undated_only=self._smart_undated_only,
                convert_mismatched=self._convert_mismatched,
                backup_service=self._backup_service,
                progress_callback=lambda n, t, fn="", st="": self.progress.emit(n, t, fn, st),
                is_cancelled=lambda: self._cancelled,
            )
            self.done.emit(warnings)
        except Exception as exc:
            self.error.emit(str(exc))


class SaveThread(QThread):
    progress = Signal(int, int, str, str)
    done     = Signal(list)
    error    = Signal(str)

    def __init__(
        self,
        items: list[PhotoItem],
        normalize_dates: bool,
        do_rename: bool,
        append_original: bool,
        smart_undated_only: bool = False,
        convert_mismatched: bool = False,
        backup_service: Optional[BackupService] = None,
        parent=None,
    ):
        super().__init__(parent)
        self._worker = SaveWorker(
            items,
            normalize_dates,
            do_rename,
            append_original,
            smart_undated_only,
            convert_mismatched,
            backup_service
        )
        self._worker.progress.connect(self.progress)
        self._worker.done.connect(self.done)
        self._worker.error.connect(self.error)

    def run(self):
        self._worker.run()

    def cancel(self):
        self._worker.cancel()
