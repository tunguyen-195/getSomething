from __future__ import annotations

from pathlib import Path

from src.services.transcription.models import pyannote_manager


def _materialize_snapshot(snapshot: Path, required_files: tuple[str, ...]) -> None:
    for relative_path in required_files:
        path = snapshot / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"test-artifact")


def _hf_snapshot(root: Path, model_id: str, revision: str) -> Path:
    owner, name = model_id.split("/", 1)
    return root / f"models--{owner}--{name}" / "snapshots" / revision


def _materialize_pyannote_31_bundle(root: Path) -> Path:
    pipeline = _hf_snapshot(
        root,
        pyannote_manager.PYANNOTE_31_MODEL_ID,
        pyannote_manager.PYANNOTE_31_REVISION,
    )
    _materialize_snapshot(pipeline, pyannote_manager.PYANNOTE_31_REQUIRED_FILES)
    for model_id, revision, required_files in pyannote_manager.PYANNOTE_31_DEPENDENCIES:
        _materialize_snapshot(
            _hf_snapshot(root, model_id, revision),
            required_files,
        )
    return pipeline


def test_current_runtime_selects_pyannote_31_contract(monkeypatch):
    monkeypatch.setattr(pyannote_manager, "_pyannote_audio_major", lambda: 3)

    model_id, revision, required_files = pyannote_manager.compatible_model_spec()

    assert model_id == pyannote_manager.PYANNOTE_31_MODEL_ID
    assert revision == pyannote_manager.PYANNOTE_31_REVISION
    assert required_files == pyannote_manager.PYANNOTE_31_REQUIRED_FILES


def test_pyannote_31_resolver_rejects_config_only_snapshot(monkeypatch, tmp_path):
    monkeypatch.setattr(pyannote_manager, "_pyannote_audio_major", lambda: 3)
    snapshot = _hf_snapshot(
        tmp_path,
        pyannote_manager.PYANNOTE_31_MODEL_ID,
        pyannote_manager.PYANNOTE_31_REVISION,
    )
    snapshot.mkdir(parents=True)
    (snapshot / "config.yaml").write_text("pipeline: test", encoding="utf-8")

    assert pyannote_manager.resolve_compatible_local_snapshot(tmp_path) is None


def test_pyannote_31_resolver_accepts_complete_pinned_snapshot(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(pyannote_manager, "_pyannote_audio_major", lambda: 3)
    snapshot = _materialize_pyannote_31_bundle(tmp_path)

    resolved = pyannote_manager.resolve_compatible_local_snapshot(tmp_path)

    assert resolved == (
        snapshot.resolve(),
        pyannote_manager.PYANNOTE_31_MODEL_ID,
        pyannote_manager.PYANNOTE_31_REVISION,
    )


def test_resolver_rejects_unpinned_snapshot_revision(monkeypatch, tmp_path):
    monkeypatch.setattr(pyannote_manager, "_pyannote_audio_major", lambda: 3)
    snapshot = _hf_snapshot(
        tmp_path,
        pyannote_manager.PYANNOTE_31_MODEL_ID,
        "0" * 40,
    )
    _materialize_snapshot(snapshot, pyannote_manager.PYANNOTE_31_REQUIRED_FILES)

    assert pyannote_manager.resolve_compatible_local_snapshot(tmp_path) is None


def test_community_contract_is_not_selected_by_pyannote_3_runtime(monkeypatch):
    monkeypatch.setattr(pyannote_manager, "_pyannote_audio_major", lambda: 3)

    model_id, _revision, _required_files = pyannote_manager.compatible_model_spec()

    assert model_id != pyannote_manager.PYANNOTE_COMMUNITY_MODEL_ID
