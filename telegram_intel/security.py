"""Local secrets and storage protection. Never include raw exceptions in output."""

from functools import lru_cache
import getpass
import os
from pathlib import Path
import subprocess
import warnings

from filelock import FileLock, Timeout


class IntelError(Exception):
    """An error containing only text explicitly safe to show to users."""


def hidden_input(prompt: str) -> str:
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass(prompt)
        except (getpass.GetPassWarning, EOFError):
            raise IntelError("Hidden login requires an interactive local terminal.") from None


@lru_cache(maxsize=1)
def _windows_sid() -> str:
    import csv
    result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"],
                            capture_output=True, text=True, check=True)
    sid = next(csv.reader([result.stdout.strip()]))[-1]
    if not sid.startswith("S-1-"):
        raise IntelError("Could not identify the Windows account for storage permissions.")
    return sid


def protect(path: Path, directory: bool = False) -> None:
    """Only call for files owned/created by this application, never parent folders."""
    try:
        if os.name == "nt":
            rights = "(OI)(CI)F" if directory else "F"
            # Reset explicit legacy ACLs to the parent, then remove inheritance.
            # Sensitive content is created only after the data directory is secured.
            for args in (["/reset"], ["/inheritance:r", "/grant:r", f"*{_windows_sid()}:{rights}"]):
                subprocess.run(["icacls", str(path), *args], capture_output=True,
                               check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        else:
            path.chmod(0o700 if directory else 0o600)
    except (OSError, subprocess.SubprocessError, StopIteration):
        raise IntelError("Could not apply private storage permissions; operation stopped.") from None


def prepare_directory(path: Path) -> None:
    if path.is_symlink():
        raise IntelError("Data directory must not be a symbolic link.")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    protect(path, directory=True)


def prepare_data_directory(path: Path) -> None:
    """Never apply app ACLs or purge files in an unrelated user/system folder."""
    path = path.absolute()
    forbidden = {Path(path.anchor), Path.home(), Path.cwd(), *Path.cwd().parents}
    if path in forbidden or path.is_symlink():
        raise IntelError("Choose a dedicated application data folder, not a drive, home or project folder.")
    marker = path / ".telegram-intel-storage"
    known = {".env", "account.session", "account.session-journal", "account.session-wal", "account.session-shm",
             "account.lock", "messages.sqlite3", "messages.sqlite3-journal", "reports", "exports", marker.name}
    if path.exists() and not marker.exists() and any(child.name not in known for child in path.iterdir()):
        raise IntelError("Data folder contains unrelated files. Choose a dedicated empty folder.")
    prepare_directory(path)
    if not marker.exists():
        marker.touch(mode=0o600)
    protect(marker)


class AccountLock:
    """An OS-released process lock, shared by CLI and MCP."""

    def __init__(self, data_dir: Path):
        self.lock = FileLock(data_dir / "account.lock")

    def __enter__(self):
        try:
            self.lock.acquire(timeout=0)
        except Timeout:
            raise IntelError("Another CLI/MCP process is using the account. Finish that request first.") from None
        return self

    def __exit__(self, *args):
        self.lock.release()
