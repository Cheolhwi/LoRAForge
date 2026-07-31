from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_POWERSHELL_DIALOG = r"""
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Windows.Forms

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $env:AUTO_CAT_FOLDER_DIALOG_TITLE
$dialog.ShowNewFolderButton = $true
$dialog.RootFolder = [System.Environment+SpecialFolder]::MyComputer

$owner = New-Object System.Windows.Forms.Form
$owner.ShowInTaskbar = $false
$owner.TopMost = $true
$owner.Opacity = 0
$owner.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterScreen
$owner.Show()

try {
    $result = $dialog.ShowDialog($owner)
    if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::WriteLine($dialog.SelectedPath)
        exit 0
    }
    exit 2
}
finally {
    $owner.Close()
    $owner.Dispose()
    $dialog.Dispose()
}
"""

_APPLESCRIPT_DIALOG = r"""
on run argv
    set dialogTitle to item 1 of argv
    try
        set selectedFolder to choose folder with prompt dialogTitle
        return POSIX path of selectedFolder
    on error number -128
        return "__LORAFORGE_CANCELLED__"
    end try
end run
"""


def select_folder(purpose: str, timeout_seconds: int = 600, locale: str = "zh") -> Path | None:
    if sys.platform not in {"darwin", "win32"}:
        raise RuntimeError("native folder selection is supported only on macOS and Windows")

    if locale == "en":
        title = (
            "Select the image folder to process"
            if purpose == "source"
            else "Select the output folder"
        )
    else:
        title = "选择需要筛选的图片文件夹" if purpose == "source" else "选择筛选结果输出文件夹"

    if sys.platform == "darwin":
        result = subprocess.run(
            ["osascript", "-e", _APPLESCRIPT_DIALOG, title],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            check=False,
        )
        selected = result.stdout.strip()
        if selected == "__LORAFORGE_CANCELLED__":
            return None
        if result.returncode != 0:
            detail = (
                result.stderr.strip()
                or selected
                or f"exit code {result.returncode}"
            )
            raise RuntimeError(f"folder dialog failed: {detail}")
        return _validate_selected_folder(selected)

    environment = os.environ.copy()
    environment["AUTO_CAT_FOLDER_DIALOG_TITLE"] = title
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-STA",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            _POWERSHELL_DIALOG,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        creationflags=creation_flags,
        env=environment,
        check=False,
    )
    if result.returncode == 2:
        return None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"folder dialog failed: {detail}")

    selected = result.stdout.strip().strip("\ufeff").strip()
    return _validate_selected_folder(selected)


def _validate_selected_folder(selected: str) -> Path:
    if not selected:
        raise RuntimeError("folder dialog returned an empty path")
    folder = Path(selected)
    if not folder.is_dir():
        raise RuntimeError(f"selected folder does not exist: {folder}")
    return folder
