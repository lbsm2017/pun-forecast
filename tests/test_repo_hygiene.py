"""Il repo contiene solo codice: nessun file di dati deve essere tracciato da git."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA_EXT = {".xml", ".zip", ".xlsx", ".xls", ".csv", ".parquet", ".json", ".pkl", ".safetensors"}
ALLOWED = {"data/README.md"}
# JSON ammessi: solo configurazioni di strumenti (nessuno al momento)
ALLOWED_JSON: set[str] = set()


def tracked_files() -> list[str]:
    if not shutil.which("git") or not (ROOT / ".git").exists():
        pytest.skip("git non disponibile")
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True)
    return [line for line in out.stdout.splitlines() if line]


def test_no_data_files_tracked_or_addable():
    bad = []
    for f in tracked_files():
        if f in ALLOWED:
            continue
        p = Path(f)
        if p.parts and p.parts[0] in {"data", "site"}:
            bad.append(f)
        elif p.suffix.lower() in DATA_EXT and f not in ALLOWED_JSON:
            bad.append(f)
    assert not bad, f"file di dati nel repo (o non ignorati da .gitignore): {bad}"


def test_personal_config_is_ignored():
    if not shutil.which("git"):
        pytest.skip("git non disponibile")
    for f in ("data/impianto.toml", "data/gme/x.xml", "site/index.html", ".env"):
        r = subprocess.run(["git", "check-ignore", "-q", f], cwd=ROOT)
        assert r.returncode == 0, f"{f} dovrebbe essere ignorato da git"
