"""folder_dialog.py — Multi-folder selection dialog using Qt QFileDialog with ExtendedSelection."""

from __future__ import annotations

from pathlib import Path
from PySide6.QtWidgets import QFileDialog, QAbstractItemView


class MultiFolderDialog(QFileDialog):
    """Native-styled Qt FileDialog that supports selecting multiple folders simultaneously (Ctrl/Shift)."""

    def __init__(self, parent=None, caption="Select One or More Folders (Hold Ctrl/Shift to pick multiple)", directory=""):
        super().__init__(parent, caption, directory)
        self.setFileMode(QFileDialog.FileMode.Directory)
        self.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        self.setOption(QFileDialog.Option.ShowDirsOnly, True)

        # Enable multi-selection across all item views in the dialog
        for view in self.findChildren(QAbstractItemView):
            view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def selected_folders(self) -> list[Path]:
        dirs: list[Path] = []
        for p_str in self.selectedFiles():
            p = Path(p_str)
            if p.is_dir() and p not in dirs:
                dirs.append(p)

        # If user navigated into a folder and clicked Open without selecting subitems
        if not dirs:
            curr = Path(self.directory().absolutePath())
            if curr.is_dir():
                dirs.append(curr)

        return dirs
