"""Check built wheel/sdist inventories for accidental local data inclusion."""

from pathlib import Path, PurePosixPath
import tarfile
import zipfile


def check(names):
    for name in names:
        parts = PurePosixPath(name).parts
        if any(part in {"research", "outputs", "exports", "reports", ".git", ".venv", ".intel-venv", "__pycache__"} for part in parts):
            raise SystemExit(f"Private/generated directory in distribution: {name}")
        leaf = parts[-1]
        if (leaf == ".env" or leaf.startswith(".env.") and leaf != ".env.example"
                or leaf in {"requirements.lock", "cloud-macro-email-setup.txt"}
                or any(token in leaf for token in (".session", ".sqlite"))
                or leaf.endswith((".csv", ".xlsx", ".xltx", ".db", ".pyc"))):
            raise SystemExit(f"Private/generated file in distribution: {name}")


def main():
    archives = sorted(Path("dist").glob("*.whl")) + sorted(Path("dist").glob("*.tar.gz"))
    if not any(path.suffix == ".whl" for path in archives) or not any(path.name.endswith(".tar.gz") for path in archives):
        raise SystemExit("Build both wheel and source distribution before checking.")
    for path in archives:
        if path.suffix == ".whl":
            with zipfile.ZipFile(path) as archive:
                names = archive.namelist()
        else:
            with tarfile.open(path) as archive:
                names = [member.name for member in archive.getmembers() if member.isfile()]
        check(names)
        print(f"Checked {path.name}: {len(names)} files, no private/generated paths.")


if __name__ == "__main__":
    main()
