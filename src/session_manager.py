"""session_manager.py — Automatic session state persistence and crash recovery."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from .photo_item import PhotoItem

log = logging.getLogger(__name__)

SESSION_FILE = Path(__file__).resolve().parent.parent / ".cache" / "session_state.json"


class SessionManager:
    """Auto-saves and recovers unwritten staged changes, pending coordinates, and selections."""

    def __init__(self, session_file: Optional[Path] = None):
        self.session_file = session_file or SESSION_FILE
        self.session_file.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict = self._load_file()

    def _load_file(self) -> dict:
        if self.session_file.exists():
            try:
                with open(self.session_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as exc:
                log.warning("Failed to load session state: %s", exc)
        return {"folders": {}}

    def _write_file(self):
        try:
            with open(self.session_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as exc:
            log.warning("Failed to write session state: %s", exc)

    def save_staged_state(self, folders: Optional[list[Path] | Path], items: list[PhotoItem]):
        """Persist currently staged GPS coordinates for folder(s)."""
        if not folders:
            return

        target_folders = [folders] if isinstance(folders, Path) else list(folders)
        if not target_folders:
            return

        if "folders" not in self._data:
            self._data["folders"] = {}

        # Partition staged items by folder
        for folder in target_folders:
            folder_key = str(folder.resolve())
            staged = {}
            for it in items:
                if it.pending.gps and (it.folder == folder or folder in it.display_path.parents):
                    staged[str(it.display_path.resolve())] = [it.pending.gps[0], it.pending.gps[1]]

            if staged:
                self._data["folders"][folder_key] = {
                    "updated_at": datetime.now().isoformat(),
                    "staged_gps": staged,
                }
            else:
                self._data["folders"].pop(folder_key, None)

        self._write_file()

    def get_staged_state(self, folders: Optional[list[Path] | Path]) -> dict[str, tuple[float, float]]:
        """Return dict of {file_path_str: (lat, lon)} for folder(s) if previous session had staged changes."""
        if not folders:
            return {}

        target_folders = [folders] if isinstance(folders, Path) else list(folders)
        result = {}
        for folder in target_folders:
            folder_key = str(folder.resolve())
            rec = self._data.get("folders", {}).get(folder_key)
            if rec and "staged_gps" in rec:
                for path_str, coords in rec["staged_gps"].items():
                    if isinstance(coords, (list, tuple)) and len(coords) == 2:
                        result[path_str] = (float(coords[0]), float(coords[1]))
        return result

    def clear_folder_state(self, folders: Optional[list[Path] | Path]):
        """Clear recovered state after successful save."""
        if not folders:
            return
        target_folders = [folders] if isinstance(folders, Path) else list(folders)
        for folder in target_folders:
            folder_key = str(folder.resolve())
            if folder_key in self._data.get("folders", {}):
                del self._data["folders"][folder_key]
        self._write_file()


session_manager = SessionManager()
