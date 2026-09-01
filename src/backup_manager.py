"""backup_manager.py — Structured directory-mirroring backup engine and UI management dialog."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from PySide6.QtCore import Qt, Signal, Slot, QSize
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QImage
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QMessageBox, QFrame, QSplitter,
    QTreeWidget, QTreeWidgetItem, QMenu, QApplication,
    QFileDialog, QProgressBar,
)

from resources.theme import Colors, STYLE_MODERN_CYBER

log = logging.getLogger(__name__)

# Default project backup root
DEFAULT_BACKUP_ROOT = Path(__file__).parent.parent / "backups"
MANIFEST_FILE = DEFAULT_BACKUP_ROOT / "backup_manifest.json"


# ─────────────────────────────────────────────────────────────────────────────
# Backup Record Model
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class BackupRecord:
    id: str                    # Unique ID (hash or timestamp-based)
    original_path: str         # Full path to original file
    backup_path: str           # Full path to backed up file
    relative_path: str         # Mirrored path inside backups/
    timestamp: str             # ISO timestamp of backup
    size_bytes: int            # Size in bytes
    file_type: str             # e.g. "JPEG", "RAW", "RAW+JPEG"
    action: str = "EXIF Update"

    @property
    def original_path_obj(self) -> Path:
        return Path(self.original_path)

    @property
    def backup_path_obj(self) -> Path:
        return Path(self.backup_path)

    @property
    def filename(self) -> str:
        return Path(self.backup_path).name

    @property
    def original_folder(self) -> str:
        return str(Path(self.original_path).parent)

    @property
    def formatted_size(self) -> str:
        s = self.size_bytes
        if s < 1024:
            return f"{s} B"
        elif s < 1024 * 1024:
            return f"{s / 1024:.1f} KB"
        elif s < 1024 * 1024 * 1024:
            return f"{s / (1024 * 1024):.1f} MB"
        return f"{s / (1024 * 1024 * 1024):.2f} GB"

    @property
    def formatted_date(self) -> str:
        try:
            dt = datetime.fromisoformat(self.timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return self.timestamp


# ─────────────────────────────────────────────────────────────────────────────
# Backup Service
# ─────────────────────────────────────────────────────────────────────────────

class BackupService:
    """Core service for mirroring paths, handling collision naming, and recording backups."""

    def __init__(self, backup_root: Path = DEFAULT_BACKUP_ROOT):
        self.backup_root = Path(backup_root)
        self.manifest_path = self.backup_root / "backup_manifest.json"
        self._ensure_dirs()

    def _ensure_dirs(self):
        try:
            self.backup_root.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error("Failed to create backup root %s: %s", self.backup_root, exc)

    # ── Path mirroring ─────────────────────────────────────────────────────────

    def compute_mirrored_path(self, original_path: Path) -> Path:
        """Converts UNC or local drive paths to a mirrored relative path.

        Examples:
        - \\\\Server\\Share\\Photos\\2026\\img.jpg
          -> Server\\Share\\Photos\\2026\\img.jpg
        - C:\\Users\\User\\Pictures\\img.jpg
          -> C\\Users\\User\\Pictures\\img.jpg
        - /home/user/Pictures/img.jpg
          -> home/user/Pictures/img.jpg
        """
        p_str = str(original_path)

        # 1. UNC Path (\\server\share\...)
        if p_str.startswith(r"\\") or p_str.startswith("//"):
            clean = p_str.lstrip(r"\/")
            return Path(clean)

        # 2. Local Windows Drive (C:\path\...)
        if len(p_str) >= 2 and p_str[1] == ":":
            drive = p_str[0].upper()
            rest = p_str[2:].lstrip(r"\/")
            return Path(drive) / Path(rest)

        # 3. Posix or relative path
        return Path(p_str.lstrip(r"\/"))

    def resolve_collision_path(self, dest_file: Path) -> Path:
        """Windows-style duplicate collision handling: name.ext -> name (1).ext -> name (2).ext."""
        if not dest_file.exists():
            return dest_file

        parent = dest_file.parent
        stem = dest_file.stem
        suffix = dest_file.suffix
        counter = 1

        while True:
            candidate = parent / f"{stem} ({counter}){suffix}"
            if not candidate.exists():
                return candidate
            counter += 1

    # ── Backup Operations ──────────────────────────────────────────────────────

    def backup_file(self, path: Path, action: str = "EXIF Update") -> Optional[BackupRecord]:
        """Backup a single physical file to its mirrored location with collision avoidance."""
        records = self.backup_files([path], action=action)
        return records[0] if records else None

    def backup_files(self, paths: list[Path], action: str = "EXIF Update") -> list[BackupRecord]:
        """Backup physical files to their mirrored locations with collision avoidance.
        Preserves pairing counters across multi-file groups (RAW+JPEG).
        """
        records: list[BackupRecord] = []
        if not paths:
            return records

        self._ensure_dirs()
        now_iso = datetime.now().isoformat()

        # Check if files share the same stem in the same folder (e.g. RAW+JPEG)
        # Find maximum counter needed so both files get the identical counter index
        target_candidates: list[tuple[Path, Path]] = []
        for p in paths:
            if not p.exists():
                continue
            rel = self.compute_mirrored_path(p)
            dest = self.backup_root / rel
            target_candidates.append((p, dest))

        # Collision detection for group
        # If any target exists, find a common counter suffix
        counter = 0
        while True:
            suffix_str = f" ({counter})" if counter > 0 else ""
            any_exists = False
            for p, dest in target_candidates:
                candidate = dest.parent / f"{dest.stem}{suffix_str}{dest.suffix}"
                if candidate.exists():
                    any_exists = True
                    break
            if not any_exists:
                break
            counter += 1

        suffix_str = f" ({counter})" if counter > 0 else ""

        for p, dest in target_candidates:
            final_dest = dest.parent / f"{dest.stem}{suffix_str}{dest.suffix}"
            try:
                final_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(p), str(final_dest))

                rec_id = f"{final_dest.stat().st_mtime_ns}_{p.name}"
                rec = BackupRecord(
                    id=rec_id,
                    original_path=str(p.resolve()),
                    backup_path=str(final_dest.resolve()),
                    relative_path=str(final_dest.relative_to(self.backup_root)),
                    timestamp=now_iso,
                    size_bytes=final_dest.stat().st_size,
                    file_type=p.suffix.upper().lstrip("."),
                    action=action,
                )
                records.append(rec)
                log.info("Backed up: %s -> %s", p, final_dest)
            except Exception as exc:
                log.error("Failed to backup %s to %s: %s", p, final_dest, exc)

        if records:
            self._append_manifest(records)

        return records

    # ── Manifest persistence ───────────────────────────────────────────────────

    def get_all_records(self) -> list[BackupRecord]:
        """Load all backup records from manifest; scans disk if manifest is missing."""
        if not self.manifest_path.exists():
            return self._scan_disk_backups()

        try:
            with open(self.manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return [BackupRecord(**item) for item in data]
        except Exception as exc:
            log.warning("Manifest read error: %s. Scanning disk...", exc)
            return self._scan_disk_backups()

    def _append_manifest(self, new_records: list[BackupRecord]):
        existing = self.get_all_records()
        existing_map = {r.backup_path: r for r in existing}
        for r in new_records:
            existing_map[r.backup_path] = r

        data = [asdict(r) for r in existing_map.values()]
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            log.error("Failed to save manifest: %s", exc)

    def _save_manifest(self, records: list[BackupRecord]):
        data = [asdict(r) for r in records]
        try:
            with open(self.manifest_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            log.error("Failed to save manifest: %s", exc)

    def _scan_disk_backups(self) -> list[BackupRecord]:
        """Fallback to rebuild manifest from disk."""
        records: list[BackupRecord] = []
        if not self.backup_root.exists():
            return records

        for p in self.backup_root.rglob("*"):
            if p.is_file() and p.name != "backup_manifest.json":
                try:
                    rel = p.relative_to(self.backup_root)
                    stat = p.stat()
                    dt = datetime.fromtimestamp(stat.st_mtime).isoformat()
                    rec = BackupRecord(
                        id=f"{stat.st_mtime_ns}_{p.name}",
                        original_path=str(rel),  # approximate if unknown
                        backup_path=str(p.resolve()),
                        relative_path=str(rel),
                        timestamp=dt,
                        size_bytes=stat.st_size,
                        file_type=p.suffix.upper().lstrip("."),
                    )
                    records.append(rec)
                except Exception:
                    continue
        return records

    # ── Restore & Delete Operations ───────────────────────────────────────────

    def restore_record(self, record: BackupRecord, target_override: Optional[Path] = None, overwrite: bool = True) -> tuple[bool, str]:
        """Restore a single backed up file to its original location or target override."""
        src = record.backup_path_obj
        if not src.exists():
            return False, f"Backup file '{src}' does not exist on disk."

        dest = target_override if target_override else record.original_path_obj
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists() and not overwrite:
                dest = self.resolve_collision_path(dest)

            shutil.copy2(str(src), str(dest))
            return True, f"Successfully restored to {dest}"
        except Exception as exc:
            return False, f"Restore failed: {exc}"

    def delete_record(self, record: BackupRecord) -> tuple[bool, str]:
        """Delete a single backup file and update manifest."""
        src = record.backup_path_obj
        try:
            if src.exists():
                src.unlink()

            # Clean empty parent directories up to backup_root
            parent = src.parent
            while parent != self.backup_root and parent.exists():
                if not any(parent.iterdir()):
                    parent.rmdir()
                    parent = parent.parent
                else:
                    break

            records = [r for r in self.get_all_records() if r.backup_path != record.backup_path]
            self._save_manifest(records)
            return True, "Backup deleted."
        except Exception as exc:
            return False, f"Delete failed: {exc}"

    def delete_folder(self, folder_rel_path: str) -> tuple[int, str]:
        """Delete all backups inside a specific mirrored subfolder."""
        target_dir = (self.backup_root / folder_rel_path).resolve()
        if not target_dir.exists() or not target_dir.is_dir():
            return 0, "Folder does not exist."

        records = self.get_all_records()
        to_keep = []
        deleted_count = 0

        for r in records:
            p = r.backup_path_obj
            try:
                p.relative_to(target_dir)
                # Inside folder to delete
                if p.exists():
                    p.unlink()
                deleted_count += 1
            except ValueError:
                to_keep.append(r)

        try:
            shutil.rmtree(str(target_dir), ignore_errors=True)
        except Exception:
            pass

        self._save_manifest(to_keep)
        return deleted_count, f"Deleted {deleted_count} backup files."

    def clear_all(self) -> tuple[int, str]:
        """Remove all backup files and reset manifest."""
        records = self.get_all_records()
        count = len(records)
        try:
            for r in records:
                if r.backup_path_obj.exists():
                    r.backup_path_obj.unlink()
            if self.manifest_path.exists():
                self.manifest_path.unlink()

            # Remove empty subdirectories
            for item in list(self.backup_root.iterdir()):
                if item.is_dir():
                    shutil.rmtree(str(item), ignore_errors=True)
            return count, f"Cleared {count} backups."
        except Exception as exc:
            return 0, f"Error clearing backups: {exc}"

    def get_storage_stats(self) -> dict[str, Any]:
        """Calculate storage statistics."""
        records = self.get_all_records()
        total_bytes = sum(r.size_bytes for r in records if r.backup_path_obj.exists())
        folders = {r.original_folder for r in records}

        oldest = None
        newest = None
        if records:
            sorted_by_date = sorted(records, key=lambda r: r.timestamp)
            oldest = sorted_by_date[0].formatted_date
            newest = sorted_by_date[-1].formatted_date

        return {
            "total_files": len(records),
            "total_bytes": total_bytes,
            "total_folders": len(folders),
            "oldest_backup": oldest or "N/A",
            "newest_backup": newest or "N/A",
            "backup_root": str(self.backup_root),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Backup Manager Dialog UI
# ─────────────────────────────────────────────────────────────────────────────

class BackupManagerDialog(QDialog):
    """Modern Cyber-Dark modal for browsing, searching, restoring, and deleting backups."""

    def __init__(self, parent=None, backup_service: Optional[BackupService] = None):
        super().__init__(parent)
        self.setWindowTitle("Backup Center & Version History")
        self.resize(1100, 680)
        self.setStyleSheet(STYLE_MODERN_CYBER)

        self.service = backup_service or BackupService()
        self._all_records: list[BackupRecord] = []
        self._filtered_records: list[BackupRecord] = []

        self._build_ui()
        self.refresh_data()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Header Bar ────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        icon_box = QLabel("🛡️", self)
        icon_box.setStyleSheet(
            f"background: #082f49; border: 1px solid {Colors.CYAN}; border-radius: 8px; font-size: 20px; padding: 4px;"
        )
        hdr.addWidget(icon_box)

        title_col = QVBoxLayout()
        title_lbl = QLabel("Backup Management Center", self)
        title_lbl.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {Colors.TEXT_PRIMARY};")
        subtitle_lbl = QLabel("Non-destructive original snapshots preserved before EXIF writes and renames", self)
        subtitle_lbl.setStyleSheet(f"font-size: 11px; color: {Colors.TEXT_MUTED};")
        title_col.addWidget(title_lbl)
        title_col.addWidget(subtitle_lbl)
        hdr.addLayout(title_col, stretch=1)

        self._btn_open_folder = QPushButton("📂 Open Backup Folder", self)
        self._btn_open_folder.clicked.connect(self._on_open_backup_folder)
        hdr.addWidget(self._btn_open_folder)

        self._btn_refresh = QPushButton("🔄 Refresh", self)
        self._btn_refresh.clicked.connect(self.refresh_data)
        hdr.addWidget(self._btn_refresh)

        root.addLayout(hdr)

        # ── Stat Cards Bar ────────────────────────────────────────────────────
        stats_layout = QHBoxLayout()
        stats_layout.setSpacing(10)

        self._card_total = self._create_stat_card("TOTAL BACKUPS", "0", Colors.CYAN, "📁")
        self._card_storage = self._create_stat_card("STORAGE USED", "0 MB", Colors.BLUE, "💾")
        self._card_folders = self._create_stat_card("SOURCE FOLDERS", "0", Colors.PURPLE, "🗂️")
        self._card_latest = self._create_stat_card("LATEST SNAPSHOT", "N/A", Colors.EMERALD, "⏳")

        stats_layout.addWidget(self._card_total)
        stats_layout.addWidget(self._card_storage)
        stats_layout.addWidget(self._card_folders)
        stats_layout.addWidget(self._card_latest)
        root.addLayout(stats_layout)

        # ── Filter & Search Toolbar ───────────────────────────────────────────
        filter_bar = QHBoxLayout()
        filter_bar.setSpacing(8)

        self._search_input = QLineEdit(self)
        self._search_input.setPlaceholderText("🔍  Search by filename, path, or date...")
        self._search_input.textChanged.connect(self._apply_filter)
        filter_bar.addWidget(self._search_input, stretch=1)

        self._btn_clear_search = QPushButton("✕", self)
        self._btn_clear_search.setFixedWidth(28)
        self._btn_clear_search.clicked.connect(lambda: self._search_input.clear())
        filter_bar.addWidget(self._btn_clear_search)

        root.addLayout(filter_bar)

        # ── Table View ────────────────────────────────────────────────────────
        self._table = QTableWidget(self)
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels([
            "File Name", "Type", "Original Location", "Backup Date", "Size", "Backup Path"
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.setColumnWidth(0, 220)
        self._table.setColumnWidth(3, 150)
        root.addWidget(self._table, stretch=1)

        # ── Bottom Action Controls ────────────────────────────────────────────
        actions_bar = QHBoxLayout()
        actions_bar.setSpacing(8)

        self._lbl_sel_info = QLabel("0 backups selected", self)
        self._lbl_sel_info.setStyleSheet(f"color: {Colors.TEXT_MUTED}; font-size: 11px;")
        actions_bar.addWidget(self._lbl_sel_info)

        actions_bar.addStretch()

        self._btn_restore_sel = QPushButton("↩️  Restore Selected", self)
        self._btn_restore_sel.setObjectName("btn_action_emerald")
        self._btn_restore_sel.clicked.connect(self._restore_selected)
        actions_bar.addWidget(self._btn_restore_sel)

        self._btn_delete_sel = QPushButton("🗑️  Delete Selected", self)
        self._btn_delete_sel.setObjectName("btn_action_amber")
        self._btn_delete_sel.clicked.connect(self._delete_selected)
        actions_bar.addWidget(self._btn_delete_sel)

        self._btn_clear_all = QPushButton("⚠️ Clear All Backups", self)
        self._btn_clear_all.setStyleSheet(
            f"QPushButton {{ background: #28080e; color: {Colors.ROSE_LIGHT}; border: 1px solid {Colors.ROSE}; }}"
            f"QPushButton:hover {{ background: {Colors.ROSE_BG}; color: #fff; }}"
        )
        self._btn_clear_all.clicked.connect(self._clear_all_backups)
        actions_bar.addWidget(self._btn_clear_all)

        self._btn_close = QPushButton("Close", self)
        self._btn_close.clicked.connect(self.accept)
        actions_bar.addWidget(self._btn_close)

        root.addLayout(actions_bar)

        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)

    def _create_stat_card(self, title: str, val: str, accent: str, icon: str) -> QFrame:
        card = QFrame(self)
        card.setStyleSheet(
            f"QFrame {{ background: {Colors.BG_CARD}; border: 1px solid {Colors.BORDER_CARD}; border-radius: 8px; padding: 6px; }}"
        )
        card.setFixedHeight(58)
        lay = QHBoxLayout(card)
        lay.setContentsMargins(8, 4, 8, 4)
        lay.setSpacing(8)

        icon_lbl = QLabel(icon, card)
        icon_lbl.setStyleSheet("font-size: 18px;")
        lay.addWidget(icon_lbl)

        v = QVBoxLayout()
        v.setSpacing(1)
        t_lbl = QLabel(title, card)
        t_lbl.setStyleSheet(f"font-size: 9px; font-weight: bold; color: {Colors.TEXT_MUTED}; letter-spacing: 0.5px;")
        v_lbl = QLabel(val, card)
        v_lbl.setObjectName("val_label")
        v_lbl.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {accent};")
        v.addWidget(t_lbl)
        v.addWidget(v_lbl)
        lay.addLayout(v, stretch=1)
        return card

    # ── Data Loading & Refresh ────────────────────────────────────────────────

    def refresh_data(self):
        self._all_records = self.service.get_all_records()
        self._update_stats()
        self._apply_filter()

    def _update_stats(self):
        stats = self.service.get_storage_stats()
        total_mb = stats["total_bytes"] / (1024 * 1024)
        storage_str = f"{total_mb:.1f} MB" if total_mb < 1024 else f"{total_mb / 1024:.2f} GB"

        self._card_total.findChild(QLabel, "val_label").setText(str(stats["total_files"]))
        self._card_storage.findChild(QLabel, "val_label").setText(storage_str)
        self._card_folders.findChild(QLabel, "val_label").setText(str(stats["total_folders"]))
        self._card_latest.findChild(QLabel, "val_label").setText(stats["newest_backup"])

    def _apply_filter(self):
        query = self._search_input.text().strip().lower()
        if not query:
            self._filtered_records = list(self._all_records)
        else:
            self._filtered_records = [
                r for r in self._all_records
                if query in r.filename.lower()
                or query in r.original_path.lower()
                or query in r.timestamp.lower()
                or query in r.file_type.lower()
            ]

        self._populate_table()

    def _populate_table(self):
        self._table.setRowCount(len(self._filtered_records))
        for row, rec in enumerate(self._filtered_records):
            item_name = QTableWidgetItem(rec.filename)
            item_name.setData(Qt.ItemDataRole.UserRole, rec)
            item_name.setFont(QFont("Segoe UI", 9, QFont.Weight.Bold))
            item_name.setForeground(QColor(Colors.TEXT_PRIMARY))

            item_type = QTableWidgetItem(rec.file_type)
            item_type.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            item_type.setForeground(QColor(Colors.CYAN_LIGHT))

            item_orig = QTableWidgetItem(rec.original_path)
            item_orig.setToolTip(rec.original_path)
            item_orig.setForeground(QColor(Colors.TEXT_SECONDARY))

            item_date = QTableWidgetItem(rec.formatted_date)
            item_date.setForeground(QColor(Colors.TEXT_MUTED))

            item_size = QTableWidgetItem(rec.formatted_size)
            item_size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            item_size.setForeground(QColor(Colors.TEXT_PRIMARY))

            item_backup = QTableWidgetItem(rec.relative_path)
            item_backup.setToolTip(rec.backup_path)
            item_backup.setForeground(QColor(Colors.TEXT_MUTED))

            self._table.setItem(row, 0, item_name)
            self._table.setItem(row, 1, item_type)
            self._table.setItem(row, 2, item_orig)
            self._table.setItem(row, 3, item_date)
            self._table.setItem(row, 4, item_size)
            self._table.setItem(row, 5, item_backup)

        self._on_table_selection_changed()

    # ── Table Actions & Selection ─────────────────────────────────────────────

    def _selected_records(self) -> list[BackupRecord]:
        selected = []
        for idx in self._table.selectionModel().selectedRows():
            row = idx.row()
            item = self._table.item(row, 0)
            if item:
                rec = item.data(Qt.ItemDataRole.UserRole)
                if rec:
                    selected.append(rec)
        return selected

    def _on_table_selection_changed(self):
        sel = self._selected_records()
        count = len(sel)
        self._lbl_sel_info.setText(f"{count} of {len(self._filtered_records)} backups selected")
        self._btn_restore_sel.setEnabled(count > 0)
        self._btn_delete_sel.setEnabled(count > 0)

    def _show_context_menu(self, pos):
        sel = self._selected_records()
        if not sel:
            return

        menu = QMenu(self)
        menu.setStyleSheet(STYLE_MODERN_CYBER)

        act_restore = menu.addAction(f"↩️  Restore {len(sel)} file(s) to original location")
        act_restore.triggered.connect(self._restore_selected)

        act_restore_custom = menu.addAction("📁  Restore to custom folder...")
        act_restore_custom.triggered.connect(self._restore_to_custom_folder)

        menu.addSeparator()

        if len(sel) == 1:
            act_loc_backup = menu.addAction("🔍  Reveal Backup in Windows Explorer")
            act_loc_backup.triggered.connect(lambda: self._reveal_in_explorer(sel[0].backup_path_obj))

            act_loc_orig = menu.addAction("📍  Reveal Original Location in Explorer")
            act_loc_orig.triggered.connect(lambda: self._reveal_in_explorer(sel[0].original_path_obj))

            menu.addSeparator()

        act_delete = menu.addAction(f"🗑️  Delete {len(sel)} backup(s)")
        act_delete.triggered.connect(self._delete_selected)

        menu.exec(self._table.mapToGlobal(pos))

    # ── User Action Handlers ──────────────────────────────────────────────────

    def _restore_selected(self):
        sel = self._selected_records()
        if not sel:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Restore",
            f"Are you sure you want to restore <b>{len(sel)}</b> file(s) to their original locations?<br><br>"
            "This will replace any existing files at those locations with the backup snapshots.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        success_count = 0
        errors = []
        for r in sel:
            ok, msg = self.service.restore_record(r, overwrite=True)
            if ok:
                success_count += 1
            else:
                errors.append(f"• {r.filename}: {msg}")

        if errors:
            QMessageBox.warning(
                self, "Restore Completed with Issues",
                f"Restored {success_count} / {len(sel)} files.<br><br>" + "<br>".join(errors[:10])
            )
        else:
            QMessageBox.information(
                self, "Restore Successful",
                f"✓ Successfully restored {success_count} file(s) to their original locations."
            )

    def _restore_to_custom_folder(self):
        sel = self._selected_records()
        if not sel:
            return

        target_dir_str = QFileDialog.getExistingDirectory(self, "Select Folder to Restore Into")
        if not target_dir_str:
            return

        target_dir = Path(target_dir_str)
        success_count = 0
        for r in sel:
            dest = target_dir / r.filename
            ok, msg = self.service.restore_record(r, target_override=dest, overwrite=True)
            if ok:
                success_count += 1

        QMessageBox.information(
            self, "Restore Complete",
            f"✓ Restored {success_count} file(s) into:\n{target_dir}"
        )

    def _delete_selected(self):
        sel = self._selected_records()
        if not sel:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Are you sure you want to permanently delete <b>{len(sel)}</b> backup snapshot(s)?<br><br>"
            "This action cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        for r in sel:
            self.service.delete_record(r)

        self.refresh_data()

    def _clear_all_backups(self):
        total = len(self._all_records)
        if total == 0:
            QMessageBox.information(self, "Backups Empty", "There are no backups to clear.")
            return

        reply = QMessageBox.warning(
            self,
            "CLEAR ALL BACKUPS",
            f"⚠️ DANGER: Are you sure you want to delete ALL <b>{total}</b> backups in the system?<br><br>"
            "This will delete all snapshots stored in the backups folder permanently!",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        count, msg = self.service.clear_all()
        self.refresh_data()
        QMessageBox.information(self, "Backups Cleared", f"✓ {msg}")

    def _on_open_backup_folder(self):
        self.service._ensure_dirs()
        self._reveal_in_explorer(self.service.backup_root)

    def _reveal_in_explorer(self, target_path: Path):
        try:
            if target_path.is_file():
                subprocess.Popen(["explorer", "/select,", str(target_path.resolve())])
            else:
                subprocess.Popen(["explorer", str(target_path.resolve())])
        except Exception as exc:
            log.warning("Explorer open failed: %s", exc)
