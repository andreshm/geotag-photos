"""workers.py — QThread-based background workers to keep the UI responsive."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Signal, QObject

from .photo_item import PhotoItem
from .photo_manager import scan_folder, load_metadata, generate_thumbnail, apply_changes_batch

log = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Folder scan + metadata worker
# ──────────────────────────────────────────────────────────────────────────────

class ScanWorker(QObject):
    """Scans a folder, reads metadata, emits items in batches."""

    # Emitted with each discovered PhotoItem (no thumbnail yet)
    item_ready   = Signal(object)          # PhotoItem
    # Emitted when scan is fully done
    scan_done    = Signal(int)             # total item count
    # Emitted on error
    error        = Signal(str)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self._folder = folder
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        try:
            items = scan_folder(self._folder)
        except Exception as exc:
            self.error.emit(str(exc))
            return

        if self._cancelled:
            return

        # Read metadata in batches of 50 for responsiveness
        BATCH = 50
        for start in range(0, len(items), BATCH):
            if self._cancelled:
                return
            batch = items[start : start + BATCH]
            try:
                load_metadata(batch)
            except Exception as exc:
                log.warning("Metadata batch failed: %s", exc)
            for item in batch:
                if self._cancelled:
                    return
                self.item_ready.emit(item)

        self.scan_done.emit(len(items))


class ScanThread(QThread):
    item_ready = Signal(object)
    scan_done  = Signal(int)
    error      = Signal(str)

    def __init__(self, folder: Path, parent=None):
        super().__init__(parent)
        self._worker = ScanWorker(folder)
        self._worker.item_ready.connect(self.item_ready)
        self._worker.scan_done.connect(self.scan_done)
        self._worker.error.connect(self.error)

    def run(self):
        self._worker.run()

    def cancel(self):
        self._worker.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# Thumbnail loader worker
# ──────────────────────────────────────────────────────────────────────────────

class ThumbnailWorker(QObject):
    """Generates thumbnails for a queue of PhotoItems."""

    thumbnail_ready = Signal(object)   # PhotoItem (thumbnail populated)
    all_done        = Signal()

    def __init__(self, items: list[PhotoItem], parent=None):
        super().__init__(parent)
        self._items = items
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    def run(self):
        for item in self._items:
            if self._cancelled:
                break
            if item.thumbnail is None:
                try:
                    item.thumbnail = generate_thumbnail(item)
                except Exception as exc:
                    log.warning("Thumb error %s: %s", item.display_name, exc)
            self.thumbnail_ready.emit(item)
        self.all_done.emit()


class ThumbnailThread(QThread):
    thumbnail_ready = Signal(object)
    all_done        = Signal()

    def __init__(self, items: list[PhotoItem], parent=None):
        super().__init__(parent)
        self._worker = ThumbnailWorker(items)
        self._worker.thumbnail_ready.connect(self.thumbnail_ready)
        self._worker.all_done.connect(self.all_done)

    def run(self):
        self._worker.run()

    def cancel(self):
        self._worker.cancel()


# ──────────────────────────────────────────────────────────────────────────────
# Save / apply-changes worker
# ──────────────────────────────────────────────────────────────────────────────

class SaveWorker(QObject):
    """Applies pending changes (GPS write, date normalise, rename) in bg."""

    progress = Signal(int, int)    # (current, total)
    done     = Signal(list)        # list[str] — warnings
    error    = Signal(str)

    def __init__(
        self,
        items: list[PhotoItem],
        normalize_dates: bool,
        do_rename: bool,
        append_original: bool,
        copy_to_gpsok: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._items = items
        self._normalize_dates = normalize_dates
        self._do_rename = do_rename
        self._append_original = append_original
        self._copy_to_gpsok = copy_to_gpsok

    def run(self):
        try:
            warnings = apply_changes_batch(
                self._items,
                normalize_dates=self._normalize_dates,
                do_rename=self._do_rename,
                append_original=self._append_original,
                copy_to_gpsok=self._copy_to_gpsok,
                progress_callback=lambda n, t: self.progress.emit(n, t),
            )
            self.done.emit(warnings)
        except Exception as exc:
            self.error.emit(str(exc))


class SaveThread(QThread):
    progress = Signal(int, int)
    done     = Signal(list)
    error    = Signal(str)

    def __init__(
        self,
        items: list[PhotoItem],
        normalize_dates: bool,
        do_rename: bool,
        append_original: bool,
        copy_to_gpsok: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self._worker = SaveWorker(
            items, normalize_dates, do_rename, append_original, copy_to_gpsok
        )
        self._worker.progress.connect(self.progress)
        self._worker.done.connect(self.done)
        self._worker.error.connect(self.error)

    def run(self):
        self._worker.run()
