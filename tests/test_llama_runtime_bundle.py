from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import verify_llama_runtime as verifier


def _manifest(content: bytes) -> dict:
    digest = hashlib.sha256(content).hexdigest()
    return {
        "schema_version": 1,
        "manifest_version": "1.0.0",
        "runtime": {
            "id": "llama.cpp.test",
            "version": "b1",
            "commit": "abcdef",
            "relative_path": "models/runtimes/test",
            "platform": "windows",
            "architecture": "x86_64",
            "accelerator": "cuda",
            "source": {},
            "license": {},
            "probe": {
                "executable": "bin/llama-server.exe",
                "version_contains": "version: 1",
                "device_contains": "CUDA0",
            },
            "files": [
                {
                    "path": "bin/llama-server.exe",
                    "size_bytes": len(content),
                    "sha256": digest,
                }
            ],
        },
    }


def _write_bundle(tmp_path: Path, content: bytes = b"runtime") -> tuple[Path, dict]:
    runtime = tmp_path / "models" / "runtimes" / "test" / "bin"
    runtime.mkdir(parents=True)
    (runtime / "llama-server.exe").write_bytes(content)
    manifest = _manifest(content)
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_verifies_runtime_files_without_network(tmp_path):
    _path, manifest = _write_bundle(tmp_path)

    report = verifier.verify_runtime(manifest, tmp_path)

    assert report["valid"] is True
    assert report["verified_file_count"] == 1


def test_detects_runtime_checksum_tampering(tmp_path):
    _path, manifest = _write_bundle(tmp_path)
    executable = tmp_path / "models" / "runtimes" / "test" / "bin" / "llama-server.exe"
    executable.write_bytes(b"changed")

    report = verifier.verify_runtime(manifest, tmp_path)

    assert report["valid"] is False
    assert report["issues"][0]["code"] == "checksum_mismatch"


def test_rejects_runtime_path_escape(tmp_path):
    _path, manifest = _write_bundle(tmp_path)
    manifest["runtime"]["relative_path"] = "../outside"

    with pytest.raises(verifier.RuntimeManifestError, match="unsafe relative path"):
        verifier.verify_runtime(manifest, tmp_path)


def test_probe_checks_version_and_cuda_device(monkeypatch, tmp_path):
    _path, manifest = _write_bundle(tmp_path)

    def fake_run(command, **_kwargs):
        if "--version" in command:
            return SimpleNamespace(stdout="version: 1", stderr="")
        return SimpleNamespace(stdout="CUDA0: test GPU", stderr="")

    monkeypatch.setattr(verifier.subprocess, "run", fake_run)

    report = verifier.verify_runtime(manifest, tmp_path, probe=True)

    assert report["valid"] is True
    assert report["probe"]["version_match"] is True
    assert report["probe"]["device_match"] is True
