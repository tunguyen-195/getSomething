from __future__ import annotations

import hashlib
import json
import socket
from pathlib import Path

import pytest

from scripts import verify_offline_release_bundle as bundle_cli
from src.services.model_runtime import (
    OfflineBundleValidationError,
    REQUIRED_BENCHMARK_ROLES,
    load_offline_bundle,
    verify_offline_bundle,
)


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _file_spec(path: str, content: bytes) -> dict:
    return {
        "path": path,
        "size_bytes": len(content),
        "sha256": _sha256(content),
    }


def _bundle(
    components: list[dict],
    *,
    required_roles: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "bundle": {
            "id": "test.offline-bundle",
            "version": "1.0.0",
            "state": "benchmark_candidate",
            "target_profile": "test-win-gpu",
            "required_roles": required_roles or list(REQUIRED_BENCHMARK_ROLES),
            "components": components,
        },
    }


def _write_json(path: Path, payload: dict) -> bytes:
    content = json.dumps(payload, ensure_ascii=True, indent=2).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return content


def _write_bundle(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "config" / "release" / "bundle.json"
    _write_json(path, payload)
    return path


def test_valid_file_set_component_is_verified_without_network(tmp_path, monkeypatch):
    notices = b"offline notices"
    registry = b'{"components":[]}'
    notices_path = tmp_path / "THIRD_PARTY_NOTICES.md"
    registry_path = tmp_path / "config" / "release" / "third-party-components.json"
    notices_path.write_bytes(notices)
    registry_path.parent.mkdir(parents=True)
    registry_path.write_bytes(registry)
    payload = _bundle(
        [
            {
                "id": "license-files",
                "role": "license-bundle",
                "kind": "file_set",
                "files": [
                    _file_spec("THIRD_PARTY_NOTICES.md", notices),
                    _file_spec(
                        "config/release/third-party-components.json",
                        registry,
                    ),
                ],
            }
        ]
    )
    manifest_path = _write_bundle(tmp_path, payload)

    def fail_network(*_args, **_kwargs):
        raise AssertionError("offline bundle verification attempted network access")

    monkeypatch.setattr(socket, "create_connection", fail_network)
    monkeypatch.setattr(socket.socket, "connect", fail_network)

    report = verify_offline_bundle(load_offline_bundle(manifest_path), tmp_path)

    assert report["valid"] is False
    assert report["components"][0]["valid"] is True
    assert "license-bundle" in report["satisfied_roles"]
    assert report["release_ready"] is False
    assert report["status"] == "BLOCKED"


def test_required_role_contract_cannot_be_weakened(tmp_path):
    content = b"license"
    path = tmp_path / "license.txt"
    path.write_bytes(content)
    payload = _bundle(
        [
            {
                "id": "license-files",
                "role": "license-bundle",
                "kind": "file_set",
                "files": [_file_spec("license.txt", content)],
            }
        ],
        required_roles=["license-bundle", "python-wheelhouse"],
    )

    with pytest.raises(OfflineBundleValidationError, match="cannot weaken"):
        load_offline_bundle(_write_bundle(tmp_path, payload))


def test_declared_file_tamper_blocks_candidate(tmp_path):
    original = b"license"
    path = tmp_path / "license.txt"
    path.write_bytes(b"tampered")
    payload = _bundle(
        [
            {
                "id": "license-files",
                "role": "license-bundle",
                "kind": "file_set",
                "files": [_file_spec("license.txt", original)],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    assert report["valid"] is False
    assert report["components"][0]["file_issues"] == [
        "size_mismatch:license.txt"
    ]


def test_duplicate_json_key_is_rejected(tmp_path):
    path = tmp_path / "bundle.json"
    path.write_text(
        '{"schema_version":1,"schema_version":1,"bundle":{}}',
        encoding="utf-8",
    )

    with pytest.raises(OfflineBundleValidationError, match="duplicate JSON key"):
        load_offline_bundle(path)


@pytest.mark.parametrize("unsafe_path", ["../license.txt", "C:/license.txt"])
def test_unsafe_paths_are_rejected(tmp_path, unsafe_path):
    payload = _bundle(
        [
            {
                "id": "license-files",
                "role": "license-bundle",
                "kind": "file_set",
                "files": [
                    {
                        "path": unsafe_path,
                        "size_bytes": 1,
                        "sha256": "0" * 64,
                    }
                ],
            }
        ]
    )

    with pytest.raises(
        OfflineBundleValidationError,
        match="relative path|drive prefix",
    ):
        load_offline_bundle(_write_bundle(tmp_path, payload))


def test_role_kind_mismatch_is_rejected(tmp_path):
    payload = _bundle(
        [
            {
                "id": "fake-asr",
                "role": "asr-model",
                "kind": "file_set",
                "files": [
                    {
                        "path": "fake.bin",
                        "size_bytes": 1,
                        "sha256": "0" * 64,
                    }
                ],
            }
        ]
    )

    with pytest.raises(OfflineBundleValidationError, match="must be 'model_manifest'"):
        load_offline_bundle(_write_bundle(tmp_path, payload))


def _model_manifest(
    content: bytes,
    *,
    model_id: str = "test.asr-model",
    relative_path: str = "asr/test",
    tasks: list[str] | None = None,
) -> dict:
    return {
        "schema_version": 1,
        "manifest_version": "1.0.0",
        "model": {
            "id": model_id,
            "version": "0123456789abcdef",
            "relative_path": relative_path,
            "tasks": tasks or ["transcription"],
            "profiles": ["offline"],
            "artifact_size_bytes": len(content),
            "source": {
                "provider": "huggingface",
                "repository": "test/asr",
                "revision": "0123456789abcdef",
            },
            "license": {
                "spdx": "MIT",
                "name": "MIT License",
                "url": "https://example.invalid/license",
            },
            "backend": {
                "engine": "test",
                "format": "bin",
                "quantization": None,
            },
            "files": [_file_spec("model.bin", content)],
        },
    }


def test_nested_model_manifest_and_artifact_are_replayed(tmp_path):
    content = b"offline-asr"
    model_path = tmp_path / "models" / "asr" / "test" / "model.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(content)
    nested_path = tmp_path / "config" / "models" / "asr.manifest.json"
    nested_content = _write_json(nested_path, _model_manifest(content))
    payload = _bundle(
        [
            {
                "id": "asr-model-manifest",
                "role": "asr-model",
                "kind": "model_manifest",
                "subject_id": "test.asr-model",
                "files": [
                    _file_spec("config/models/asr.manifest.json", nested_content)
                ],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    assert report["valid"] is False
    nested = report["components"][0]["nested_verification"]
    assert nested["valid"] is True
    assert nested["verified_size_bytes"] == len(content)


def test_nested_model_artifact_tamper_is_rejected(tmp_path):
    original = b"offline-asr"
    model_path = tmp_path / "models" / "asr" / "test" / "model.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"tampered-asr")
    nested_path = tmp_path / "config" / "models" / "asr.manifest.json"
    nested_content = _write_json(nested_path, _model_manifest(original))
    payload = _bundle(
        [
            {
                "id": "asr-model-manifest",
                "role": "asr-model",
                "kind": "model_manifest",
                "subject_id": "test.asr-model",
                "files": [
                    _file_spec("config/models/asr.manifest.json", nested_content)
                ],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    assert report["valid"] is False
    issues = report["components"][0]["nested_verification"]["issues"]
    assert issues[0]["code"] == "size_mismatch"


def _runtime_manifest(
    content: bytes,
    *,
    runtime_id: str = "test.ffmpeg-runtime",
    relative_path: str = "runtimes/ffmpeg-test",
) -> dict:
    return {
        "schema_version": 1,
        "manifest_version": "1.0.0",
        "runtime": {
            "id": runtime_id,
            "version": "7.0.0",
            "commit": "0123456789abcdef0123456789abcdef01234567",
            "relative_path": relative_path,
            "platform": "windows",
            "architecture": "x86_64",
            "accelerator": "cpu",
            "source": {
                "provider": "github",
                "repository": "test/ffmpeg",
                "release_url": "https://example.invalid/ffmpeg",
            },
            "license": {
                "spdx": "LGPL-2.1-or-later",
                "name": "GNU Lesser General Public License",
                "url": "https://example.invalid/license",
            },
            "probe": {
                "executable": "ffmpeg.exe",
                "version_contains": "ffmpeg version",
                "device_contains": "cpu",
            },
            "files": [_file_spec("ffmpeg.exe", content)],
        },
    }


def test_nested_runtime_manifest_and_artifact_are_replayed(tmp_path):
    content = b"offline-ffmpeg"
    runtime_path = tmp_path / "runtimes" / "ffmpeg-test" / "ffmpeg.exe"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_bytes(content)
    nested_path = tmp_path / "config" / "runtimes" / "ffmpeg.runtime.json"
    nested_content = _write_json(nested_path, _runtime_manifest(content))
    payload = _bundle(
        [
            {
                "id": "ffmpeg-runtime-manifest",
                "role": "ffmpeg-runtime",
                "kind": "runtime_manifest",
                "subject_id": "test.ffmpeg-runtime",
                "files": [
                    _file_spec("config/runtimes/ffmpeg.runtime.json", nested_content)
                ],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    assert report["valid"] is False
    nested = report["components"][0]["nested_verification"]
    assert nested["verified_file_count"] == 1


def test_cli_returns_nonzero_for_incomplete_candidate(tmp_path):
    content = b'{"files":[]}'
    path = tmp_path / "config" / "release" / "prompt-schema-bundle.manifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    payload = _bundle(
        [
            {
                "id": "prompt-schema-files",
                "role": "prompt-schema-bundle",
                "kind": "file_set",
                "files": [
                    _file_spec(
                        "config/release/prompt-schema-bundle.manifest.json",
                        content,
                    )
                ],
            }
        ]
    )
    manifest = _write_bundle(tmp_path, payload)

    report, exit_code = bundle_cli.run(tmp_path, manifest)

    assert exit_code == 1
    assert report["status"] == "BLOCKED"


def test_model_role_must_match_declared_tasks(tmp_path):
    content = b"not-an-asr-model"
    model_path = tmp_path / "models" / "llm" / "test" / "model.bin"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(content)
    nested_path = tmp_path / "config" / "models" / "wrong.manifest.json"
    nested_content = _write_json(
        nested_path,
        _model_manifest(
            content,
            model_id="test.wrong-asr",
            relative_path="llm/test",
            tasks=["analysis", "summary"],
        ),
    )
    payload = _bundle(
        [
            {
                "id": "wrong-asr-manifest",
                "role": "asr-model",
                "kind": "model_manifest",
                "subject_id": "test.wrong-asr",
                "files": [
                    _file_spec("config/models/wrong.manifest.json", nested_content)
                ],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    nested = report["components"][0]["nested_verification"]
    assert nested["valid"] is False
    assert nested["issues"] == [
        "model_manifest_role_task_mismatch:asr-model:transcription"
    ]


def test_plain_readme_cannot_satisfy_license_bundle(tmp_path):
    content = b"read me"
    path = tmp_path / "README.md"
    path.write_bytes(content)
    payload = _bundle(
        [
            {
                "id": "fake-license",
                "role": "license-bundle",
                "kind": "file_set",
                "files": [_file_spec("README.md", content)],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    assert report["components"][0]["valid"] is False
    assert set(report["components"][0]["file_issues"]) == {
        "role_required_file_missing:THIRD_PARTY_NOTICES.md",
        "role_required_file_missing:config/release/third-party-components.json",
    }


def test_unexpected_nested_model_file_blocks_component(tmp_path):
    content = b"offline-asr"
    model_root = tmp_path / "models" / "asr" / "test"
    model_root.mkdir(parents=True)
    (model_root / "model.bin").write_bytes(content)
    (model_root / "undeclared.bin").write_bytes(b"unexpected")
    nested_path = tmp_path / "config" / "models" / "asr.manifest.json"
    nested_content = _write_json(nested_path, _model_manifest(content))
    payload = _bundle(
        [
            {
                "id": "asr-model-manifest",
                "role": "asr-model",
                "kind": "model_manifest",
                "subject_id": "test.asr-model",
                "files": [
                    _file_spec("config/models/asr.manifest.json", nested_content)
                ],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    nested = report["components"][0]["nested_verification"]
    assert nested["valid"] is False
    assert "unexpected_model_file:undeclared.bin" in nested["issues"]


def test_short_runtime_commit_is_rejected(tmp_path):
    content = b"runtime"
    runtime_path = tmp_path / "runtimes" / "ffmpeg-test" / "ffmpeg.exe"
    runtime_path.parent.mkdir(parents=True)
    runtime_path.write_bytes(content)
    manifest = _runtime_manifest(content)
    manifest["runtime"]["commit"] = "7ba604f1c"
    nested_path = tmp_path / "config" / "runtimes" / "ffmpeg.runtime.json"
    nested_content = _write_json(nested_path, manifest)
    payload = _bundle(
        [
            {
                "id": "ffmpeg-runtime-manifest",
                "role": "ffmpeg-runtime",
                "kind": "runtime_manifest",
                "subject_id": "test.ffmpeg-runtime",
                "files": [
                    _file_spec("config/runtimes/ffmpeg.runtime.json", nested_content)
                ],
            }
        ]
    )

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, payload)),
        tmp_path,
    )

    nested = report["components"][0]["nested_verification"]
    assert nested["valid"] is False
    assert "full lowercase 40-hex" in nested["issues"][0]


def _model_component(
    tmp_path: Path,
    *,
    role: str,
    model_id: str,
    tasks: list[str],
) -> dict:
    slug = role.replace("-", "_")
    content = f"model:{model_id}".encode("utf-8")
    relative_path = f"fixtures/{slug}"
    model_file = tmp_path / "models" / "fixtures" / slug / "model.bin"
    model_file.parent.mkdir(parents=True)
    model_file.write_bytes(content)
    manifest_path = tmp_path / "config" / "models" / f"{slug}.manifest.json"
    manifest_content = _write_json(
        manifest_path,
        _model_manifest(
            content,
            model_id=model_id,
            relative_path=relative_path,
            tasks=tasks,
        ),
    )
    relative_manifest = f"config/models/{slug}.manifest.json"
    return {
        "id": f"{slug}-component",
        "role": role,
        "kind": "model_manifest",
        "subject_id": model_id,
        "files": [_file_spec(relative_manifest, manifest_content)],
    }


def _runtime_component(
    tmp_path: Path,
    *,
    role: str,
    runtime_id: str,
) -> dict:
    slug = role.replace("-", "_")
    content = f"runtime:{runtime_id}".encode("utf-8")
    relative_path = f"runtimes/{slug}"
    runtime_file = tmp_path / relative_path / "ffmpeg.exe"
    runtime_file.parent.mkdir(parents=True)
    runtime_file.write_bytes(content)
    manifest_path = tmp_path / "config" / "runtimes" / f"{slug}.runtime.json"
    manifest_content = _write_json(
        manifest_path,
        _runtime_manifest(
            content,
            runtime_id=runtime_id,
            relative_path=relative_path,
        ),
    )
    relative_manifest = f"config/runtimes/{slug}.runtime.json"
    return {
        "id": f"{slug}-component",
        "role": role,
        "kind": "runtime_manifest",
        "subject_id": runtime_id,
        "files": [_file_spec(relative_manifest, manifest_content)],
    }


def _file_set_component(
    tmp_path: Path,
    *,
    role: str,
    paths: list[str],
) -> dict:
    files = []
    for relative in paths:
        content = f"file:{role}:{relative}".encode("utf-8")
        path = tmp_path / Path(*relative.split("/"))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        files.append(_file_spec(relative, content))
    return {
        "id": f"{role.replace('-', '_')}-component",
        "role": role,
        "kind": "file_set",
        "files": files,
    }


def test_complete_locked_candidate_can_pass_but_is_not_release_authority(tmp_path):
    components = [
        _model_component(
            tmp_path,
            role="asr-model",
            model_id="test.asr",
            tasks=["transcription"],
        ),
        _model_component(
            tmp_path,
            role="diarization-model",
            model_id="test.diarization",
            tasks=["diarization"],
        ),
        _model_component(
            tmp_path,
            role="llm-model",
            model_id="test.llm",
            tasks=["analysis", "summary"],
        ),
    ]
    for role in (
        "database-runtime",
        "ffmpeg-runtime",
        "llm-runtime",
        "node-runtime",
        "python-runtime",
        "queue-runtime",
    ):
        components.append(
            _runtime_component(
                tmp_path,
                role=role,
                runtime_id=f"test.{role}",
            )
        )
    file_set_paths = {
        "app-source-bundle": ["config/release/app-source.manifest.json"],
        "frontend-package-cache": ["frontend/offline-cache/manifest.json"],
        "license-bundle": [
            "THIRD_PARTY_NOTICES.md",
            "config/release/third-party-components.json",
        ],
        "os-prerequisites": ["config/release/os-prerequisites.manifest.json"],
        "prompt-schema-bundle": [
            "config/release/prompt-schema-bundle.manifest.json"
        ],
        "python-wheelhouse": ["wheelhouse/manifest.json"],
        "startup-profile": ["config/release/offline-startup-profile.json"],
    }
    for role, paths in file_set_paths.items():
        components.append(_file_set_component(tmp_path, role=role, paths=paths))

    report = verify_offline_bundle(
        load_offline_bundle(_write_bundle(tmp_path, _bundle(components))),
        tmp_path,
    )

    assert report["valid"] is True
    assert report["status"] == "PASS_CANDIDATE_COMPLETE"
    assert report["candidate_complete"] is True
    assert report["release_ready"] is False
