from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from scripts import model_store as model_store_cli
from src.services.model_runtime import ManifestValidationError, ModelStore, load_manifest


def _manifest_data(
    content: bytes,
    *,
    model_id: str = "test.vi-model",
    relative_path: str = "llm/test-vi-model",
    file_path: str = "model.gguf",
    required: bool = True,
):
    return {
        "schema_version": 1,
        "manifest_version": "1.0.0",
        "model": {
            "id": model_id,
            "version": "test-revision",
            "relative_path": relative_path,
            "tasks": ["analysis", "summary"],
            "profiles": ["production-gpu"],
            "artifact_size_bytes": len(content),
            "source": {
                "provider": "huggingface",
                "repository": "test/repository",
                "revision": "0123456789abcdef",
            },
            "license": {
                "spdx": "Apache-2.0",
                "name": "Apache License 2.0",
                "url": "https://www.apache.org/licenses/LICENSE-2.0",
            },
            "backend": {
                "engine": "llama.cpp",
                "format": "gguf",
                "quantization": "Q4_K_M",
            },
            "files": [
                {
                    "path": file_path,
                    "size_bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                    "required": required,
                }
            ],
        },
    }


def _write_manifest(root: Path, data: dict, name: str = "test.manifest.json") -> Path:
    manifest_dir = root / "config" / "models"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _store(root: Path) -> ModelStore:
    return ModelStore.from_repository(root)


def test_verifies_repository_local_model(tmp_path):
    content = b"offline-model"
    data = _manifest_data(content)
    model_file = tmp_path / "models" / data["model"]["relative_path"] / "model.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(content)
    _write_manifest(tmp_path, data)

    report = _store(tmp_path).preflight()

    assert report.valid is True
    assert report.manifests_found == 1
    assert report.results[0].status == "verified"
    assert report.results[0].verified_size_bytes == len(content)


def test_detects_model_tampering(tmp_path):
    original = b"trusted-model"
    data = _manifest_data(original)
    model_file = tmp_path / "models" / data["model"]["relative_path"] / "model.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(b"altered-model-with-different-size")
    _write_manifest(tmp_path, data)

    result = _store(tmp_path).preflight().results[0]

    assert result.valid is False
    assert {issue.code for issue in result.issues} == {"size_mismatch"}


def test_detects_same_size_checksum_tampering(tmp_path):
    original = b"trusted-model"
    data = _manifest_data(original)
    model_file = tmp_path / "models" / data["model"]["relative_path"] / "model.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(b"changed-model")
    _write_manifest(tmp_path, data)

    result = _store(tmp_path).preflight().results[0]

    assert result.valid is False
    assert {issue.code for issue in result.issues} == {"checksum_mismatch"}


def test_optional_missing_file_is_warning_only(tmp_path):
    content = b"optional"
    data = _manifest_data(content, required=False)
    (tmp_path / "models" / data["model"]["relative_path"]).mkdir(parents=True)
    _write_manifest(tmp_path, data)

    result = _store(tmp_path).preflight().results[0]

    assert result.valid is True
    assert result.issues[0].severity == "warning"
    assert result.issues[0].code == "missing_file"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("relative_path", "../outside"),
        ("relative_path", "C:/outside"),
    ],
)
def test_rejects_unsafe_model_paths(tmp_path, field, value):
    data = _manifest_data(b"model")
    data["model"][field] = value
    path = _write_manifest(tmp_path, data)

    with pytest.raises(ManifestValidationError, match="relative path|drive prefix"):
        load_manifest(path)


def test_rejects_unsafe_file_path(tmp_path):
    data = _manifest_data(b"model", file_path="../../outside.gguf")
    path = _write_manifest(tmp_path, data)

    with pytest.raises(ManifestValidationError, match="normalized relative path"):
        load_manifest(path)


def test_rejects_model_directory_symlink_escape(tmp_path):
    content = b"outside-model"
    data = _manifest_data(content)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "model.gguf").write_bytes(content)
    model_path = tmp_path / "models" / data["model"]["relative_path"]
    model_path.parent.mkdir(parents=True)
    try:
        model_path.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks are unavailable: {exc}")
    _write_manifest(tmp_path, data)

    result = _store(tmp_path).preflight().results[0]

    assert result.valid is False
    assert result.issues[0].code == "unsafe_model_path"


def test_rejects_floating_source_revision(tmp_path):
    data = _manifest_data(b"model")
    data["model"]["source"]["revision"] = "main"
    path = _write_manifest(tmp_path, data)

    with pytest.raises(ManifestValidationError, match="immutable"):
        load_manifest(path)


def test_rejects_duplicate_model_ids(tmp_path):
    data = _manifest_data(b"model")
    _write_manifest(tmp_path, data, "one.manifest.json")
    _write_manifest(tmp_path, data, "two.manifest.json")

    with pytest.raises(ManifestValidationError, match="Duplicate model id"):
        _store(tmp_path).load_manifests()


def test_store_ignores_explicit_non_model_artifact_manifests(tmp_path):
    content = b"offline-model"
    data = _manifest_data(content)
    model_file = tmp_path / "models" / data["model"]["relative_path"] / "model.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(content)
    _write_manifest(tmp_path, data, "qwen.manifest.json")
    _write_manifest(
        tmp_path,
        {
            "schema_version": "1.0",
            "artifact_id": "diarization.pyannote-offline",
            "runtime_contract": {"engine": "pyannote"},
        },
        "pyannote.manifest.json",
    )

    report = _store(tmp_path).preflight()

    assert report.valid is True
    assert report.manifests_found == 1
    assert report.results[0].model_id == data["model"]["id"]


def test_store_does_not_ignore_malformed_model_manifest(tmp_path):
    _write_manifest(
        tmp_path,
        {
            "schema_version": 1,
            "manifest_version": "1.0.0",
            "artifact_id": "ambiguous.model",
        },
        "malformed.manifest.json",
    )

    with pytest.raises(ManifestValidationError, match="model"):
        _store(tmp_path).load_manifests()


def test_preflight_has_no_network_dependency(tmp_path, monkeypatch):
    content = b"offline-only"
    data = _manifest_data(content)
    model_file = tmp_path / "models" / data["model"]["relative_path"] / "model.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(content)
    _write_manifest(tmp_path, data)

    def fail_network(*_args, **_kwargs):
        raise AssertionError("offline preflight attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket.socket, "connect", fail_network)

    assert _store(tmp_path).preflight().valid is True


def test_preflight_fails_closed_without_manifests(tmp_path):
    report = _store(tmp_path).preflight()

    assert report.manifests_found == 0
    assert report.valid is False


def test_cli_inventory_and_verify_json(tmp_path, capsys):
    content = b"cli-model"
    data = _manifest_data(content)
    model_file = tmp_path / "models" / data["model"]["relative_path"] / "model.gguf"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(content)
    _write_manifest(tmp_path, data)

    inventory_code = model_store_cli.main(
        ["--repo-root", str(tmp_path), "inventory", "--json"]
    )
    inventory = json.loads(capsys.readouterr().out)
    verify_code = model_store_cli.main(
        ["--repo-root", str(tmp_path), "verify", "--profile", "production-gpu", "--json"]
    )
    verification = json.loads(capsys.readouterr().out)

    assert inventory_code == 0
    assert inventory[0]["status"] == "present_unverified"
    assert verify_code == 0
    assert verification["offline"] is True
    assert verification["valid"] is True
