import hashlib
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "config/models/pyannote-3.1-offline.manifest.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def test_pyannote_offline_manifest_matches_local_artifacts() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest["pipeline"]["revision"] == (
        "84fd25912480287da0247647c3d2b4853cb3ee5d"
    )
    assert manifest["activation"]["offline"] is True
    for artifact in manifest["files"]:
        path = PROJECT_ROOT / artifact["path"]
        assert path.is_file(), artifact["path"]
        assert path.stat().st_size == artifact["size"]
        assert _sha256(path) == artifact["sha256"]


def test_pyannote_manifest_contains_no_rollback_workspace_path() -> None:
    content = MANIFEST_PATH.read_text(encoding="utf-8").casefold()

    assert "d:/workspace" not in content
    assert "d:\\workspace" not in content
