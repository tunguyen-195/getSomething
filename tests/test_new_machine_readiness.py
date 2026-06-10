import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


FAKE_REVISION = "0123456789abcdef0123456789abcdef01234567"


def _git_blob_id(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode("utf-8") + data).hexdigest()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_fake_hf_snapshot(tmp_path: Path, *, revision: str = FAKE_REVISION, config: bytes = b"abc", model: bytes = b"model") -> Path:
    snapshot = tmp_path / "models" / "whisper" / "models--Systran--faster-whisper-small" / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_bytes(config)
    (snapshot / "model.bin").write_bytes(model)
    return snapshot


def _write_fake_hf_blobs(tmp_path: Path, *, config: bytes = b"abc", model: bytes = b"model") -> Path:
    blobs = tmp_path / "models" / "whisper" / "models--Systran--faster-whisper-small" / "blobs"
    blobs.mkdir(parents=True)
    (blobs / _git_blob_id(config)).write_bytes(config)
    (blobs / _sha256(model)).write_bytes(model)
    return blobs


def _fake_manifest(tmp_path: Path, *, revision: str = FAKE_REVISION, config: bytes = b"abc", model: bytes = b"model") -> dict:
    manifest = {
        "schema_version": "sti.model_artifacts.v1",
        "profiles": {
            "lite_rtx2050": {
                "required": ["faster_whisper_small"],
                "optional": [],
            }
        },
        "artifacts": [
            {
                "id": "faster_whisper_small",
                "kind": "hf_snapshot",
                "source_type": "public_hf",
                "repo_id": "Systran/faster-whisper-small",
                "revision": revision,
                "layout": "hf_cache",
                "cache_root": "models/whisper",
                "files": [
                    {
                        "path": "config.json",
                        "required": True,
                        "size_bytes": len(config),
                        "hf_blob_id": _git_blob_id(config),
                    },
                    {
                        "path": "model.bin",
                        "required": True,
                        "size_bytes": len(model),
                        "lfs_sha256": _sha256(model),
                    },
                ],
            }
        ],
    }
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "model_artifacts.required.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_new_machine_docs_reference_existing_local_scripts():
    docs = [
        ROOT / "README.md",
        ROOT / "docs" / "NEW_MACHINE_SETUP.md",
        ROOT / "docs" / "MODEL_SETUP.md",
        ROOT / "docs" / "DEPLOY_LITE_RTX2050_WIN11.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in docs)
    references = set(re.findall(r"(?:\.\\|scripts[\\/])([A-Za-z0-9_.-]+(?:\.bat|\.py))", text))

    expected = {
        "START_DOCKER_LITE.bat",
        "START_LITE_RTX2050.bat",
        "precache_lite_models.py",
        "verify_models.py",
        "check_lite_runtime.py",
    }
    assert expected.issubset(references)
    assert (ROOT / "START_ALL_SERVICES.bat").is_file()

    for name in references:
        if name.endswith(".bat"):
            assert (ROOT / name).is_file(), name
        elif name.endswith(".py"):
            assert (ROOT / "scripts" / name).is_file() or (ROOT / name).is_file(), name


def test_model_artifact_manifest_covers_pull_ready_lite_profile():
    manifest = json.loads((ROOT / "docs" / "model_artifacts.required.json").read_text(encoding="utf-8"))

    assert manifest["distribution_decision"]["pull_ready_profile"] == "lite_rtx2050"
    assert manifest["distribution_decision"]["unavailable_model_distribution"] == "manual_copy_bundle"

    profile = manifest["profiles"]["lite_rtx2050"]
    assert profile["required"] == ["faster_whisper_medium"]
    assert "faster_whisper_small" in profile["optional"]

    artifacts = {item["id"]: item for item in manifest["artifacts"]}
    lite_model = artifacts["faster_whisper_medium"]
    assert lite_model["kind"] == "hf_snapshot"
    assert lite_model["source_type"] == "public_hf"
    assert lite_model["repo_id"] == "Systran/faster-whisper-medium"
    assert lite_model["revision"] != "main"
    assert lite_model["cache_root"] == "models/whisper"
    assert lite_model["runtime_env"]["ASR_PROFILE"] == "balanced"
    assert lite_model["runtime_env"]["WHISPER_MODEL"] == "medium"

    phowhisper_cpp = artifacts["phowhisper_cpp_large_q5_internal"]
    assert phowhisper_cpp["source_type"] == "manual_copy"
    assert phowhisper_cpp["manifest_path"].endswith(".manifest.json")
    assert phowhisper_cpp["sha256"]
    assert "Copy" in phowhisper_cpp["copy_instructions"]


def test_hf_manifest_entries_are_pinned_and_file_verified():
    manifest = json.loads((ROOT / "docs" / "model_artifacts.required.json").read_text(encoding="utf-8"))

    for artifact in manifest["artifacts"]:
        if artifact.get("source_type") not in {"public_hf", "gated_hf"}:
            continue
        assert artifact["revision"] not in {"main", "master", "latest"}
        assert len(artifact["revision"]) >= 12
        files = artifact.get("files") or []
        assert files, artifact["id"]
        for item in files:
            if not item.get("required", True):
                continue
            assert isinstance(item.get("size_bytes"), int), (artifact["id"], item["path"])
            assert item.get("lfs_sha256") or item.get("hf_blob_id") or item.get("sha256"), (
                artifact["id"],
                item["path"],
            )


def test_full_offline_manual_copy_artifacts_do_not_pass_without_integrity_metadata(tmp_path):
    from src.services.model_artifacts import verify_profile

    models = tmp_path / "models"
    models.mkdir()
    (models / "large-v2.pt").write_bytes(b"fake cherry model")

    phowhisper = models / "phowhisper-safe"
    phowhisper.mkdir()
    (phowhisper / "config.json").write_text("{}", encoding="utf-8")

    silero = models / "silero"
    silero.mkdir()
    (silero / "silero_vad.jit").write_bytes(b"fake silero")
    (silero / "utils_vad.py").write_text("# fake", encoding="utf-8")

    results = verify_profile(
        "full_offline",
        root=tmp_path,
        manifest=ROOT / "docs" / "model_artifacts.required.json",
    )
    errors = {result.artifact_id: result.errors for result in results}

    assert errors["cherry_whisper_large_v2_pt"] == [
        "artifact_integrity_metadata_missing:cherry_whisper_large_v2_pt"
    ]
    assert errors["phowhisper_safe_internal"] == [
        "artifact_integrity_metadata_missing:phowhisper_safe_internal"
    ]
    assert errors["silero_vad_jit"] == [
        "artifact_integrity_metadata_missing:silero_vad_jit"
    ]


def test_model_handoff_does_not_track_lfs_or_public_cache_importer():
    assert not (ROOT / ".gitattributes").exists()
    assert not (ROOT / "scripts" / "import_model_bundle_to_lfs.py").exists()

    docs_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "README.md",
            ROOT / "docs" / "NEW_MACHINE_SETUP.md",
            ROOT / "docs" / "MODEL_SETUP.md",
        ]
    )
    assert "git lfs" not in docs_text.lower()
    assert "import_model_bundle_to_lfs" not in docs_text
    assert "copy .env.example .env" not in docs_text.lower()


def test_docker_compose_default_is_pull_ready_runtime_not_source_mount_dev():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    docs = "\n".join(
        path.read_text(encoding="utf-8")
        for path in [
            ROOT / "README.md",
            ROOT / "docs" / "NEW_MACHINE_SETUP.md",
            ROOT / "docs" / "MODEL_SETUP.md",
            ROOT / "docs" / "DEPLOY_LITE_RTX2050_WIN11.md",
        ]
    )

    assert "- .:/app" not in compose
    assert "- ./frontend:/app" not in compose
    assert "model_sync:" in compose
    assert 'profiles: ["setup"]' in compose
    assert 'profiles: ["full", "dev"]' in compose
    assert "WHISPER_MODEL: ${WHISPER_MODEL:-medium}" in compose
    assert "WHISPER_MODEL_PATH: ${WHISPER_MODEL_PATH:-models/whisper}" in compose
    assert "condition: service_healthy" in compose
    assert ".\\START_DOCKER_LITE.bat" in docs
    assert "docker compose --env-file .env --profile setup run --rm model_sync" in docs
    assert "runs/" in dockerignore
    assert "test-results/" in dockerignore
    assert "frontend/.playwright-cli/" in dockerignore
    assert "runs/" in gitignore
    assert ".coverage" in gitignore
    assert "test-results/" in gitignore
    assert "frontend/.playwright-cli/" in gitignore


def test_frontend_fallback_disables_only_unmanifested_quality_profile():
    source = (ROOT / "frontend" / "src" / "components" / "TranscribeDialog.tsx").read_text(encoding="utf-8")

    quality_block = re.search(r"value: 'quality_local'.*?availability_reason: 'model_artifact_not_manifested'", source, re.S)
    fallback_block = re.search(r"const FALLBACK_ASR_PROFILES = \[(.*?)\];", source, re.S)

    assert "const DEFAULT_ASR_PROFILE = 'balanced'" in source
    assert "useState(runtimeProfile?.asr?.asr_profile || DEFAULT_ASR_PROFILE)" in source
    assert fallback_block and re.search(r"value: 'balanced'.*?value: 'rtx2050_safe'", fallback_block.group(1), re.S)
    assert re.search(r"value: 'balanced'.*?available: true", source, re.S)
    assert quality_block
    assert "disabled={!selectedProfileAvailable}" in source


def test_frontend_dockerfile_uses_vite_compatible_node_and_lockfile_install():
    source = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")

    assert re.search(r"FROM\s+node:22(?:-|$)", source), source
    assert "RUN npm ci" in source
    assert "RUN npm install" not in source


def test_lite_asr_benchmark_reports_transcript_and_wer():
    from scripts.benchmark_lite_asr import word_error_rate

    assert word_error_rate("xin chao viet nam", "xin chao viet nam") == 0.0
    assert word_error_rate("xin chao viet nam", "xin chao") == 0.5


def test_lite_precache_default_is_vietnamese_quality_medium():
    source = (ROOT / "scripts" / "precache_lite_models.py").read_text(encoding="utf-8")
    wrapper = (ROOT / "scripts" / "download_models.py").read_text(encoding="utf-8")
    docs = (ROOT / "docs" / "NEW_MACHINE_SETUP.md").read_text(encoding="utf-8")

    assert 'default=os.getenv("WHISPER_MODEL", "medium")' in source
    assert "precache_lite_models.py --model medium" in wrapper
    assert "faster-whisper medium" in docs
    assert "Tai public faster-whisper small vao cache local" not in docs


def test_strict_hf_verifier_rejects_marker_only_cache(tmp_path):
    from src.services.model_artifacts import verify_profile

    _fake_manifest(tmp_path)
    marker_dir = tmp_path / "models" / "whisper" / "Systran-faster-whisper-small"
    marker_dir.mkdir(parents=True)
    marker_dir.joinpath("SNAPSHOT_PATH.txt").write_text(
        str(tmp_path / "models" / "whisper" / "models--Systran--faster-whisper-small" / "snapshots" / FAKE_REVISION),
        encoding="utf-8",
    )

    result = verify_profile("lite_rtx2050", root=tmp_path)[0]

    assert result.ok is False
    assert any(
        "snapshot_marker_stale" in error
        or "missing_required_file" in error
        or "hf_snapshot_missing" in error
        for error in result.errors
    )


def test_strict_hf_verifier_finds_snapshot_when_absolute_marker_is_stale(tmp_path):
    from src.services.model_artifacts import verify_profile

    _fake_manifest(tmp_path)
    snapshot = _write_fake_hf_snapshot(tmp_path)
    marker_dir = tmp_path / "models" / "whisper" / "Systran-faster-whisper-small"
    marker_dir.mkdir(parents=True)
    marker_dir.joinpath("SNAPSHOT_PATH.txt").write_text(str(tmp_path / "missing" / "snapshot"), encoding="utf-8")

    result = verify_profile("lite_rtx2050", root=tmp_path)[0]

    assert result.ok is True
    assert result.resolved_path == snapshot
    assert "snapshot_marker_stale:faster_whisper_small" in result.warnings


def test_strict_hf_verifier_rejects_existing_wrong_revision_marker(tmp_path):
    from src.services.model_artifacts import verify_profile

    _fake_manifest(tmp_path)
    wrong_snapshot = _write_fake_hf_snapshot(
        tmp_path,
        revision="ffffffffffffffffffffffffffffffffffffffff",
    )
    marker_dir = tmp_path / "models" / "whisper" / "Systran-faster-whisper-small"
    marker_dir.mkdir(parents=True)
    marker_dir.joinpath("SNAPSHOT_PATH.txt").write_text(str(wrong_snapshot), encoding="utf-8")

    result = verify_profile("lite_rtx2050", root=tmp_path)[0]

    assert result.ok is False
    assert result.errors == ["snapshot_marker_revision_mismatch:faster_whisper_small"]


def test_strict_hf_verifier_uses_valid_cache_despite_wrong_revision_marker(tmp_path):
    from src.services.model_artifacts import verify_profile

    _fake_manifest(tmp_path)
    snapshot = _write_fake_hf_snapshot(tmp_path)
    wrong_snapshot = _write_fake_hf_snapshot(
        tmp_path,
        revision="ffffffffffffffffffffffffffffffffffffffff",
    )
    marker_dir = tmp_path / "models" / "whisper" / "Systran-faster-whisper-small"
    marker_dir.mkdir(parents=True)
    marker_dir.joinpath("SNAPSHOT_PATH.txt").write_text(str(wrong_snapshot), encoding="utf-8")

    result = verify_profile("lite_rtx2050", root=tmp_path)[0]

    assert result.ok is True
    assert result.resolved_path == snapshot
    assert "snapshot_marker_revision_mismatch:faster_whisper_small" in result.warnings


def test_strict_hf_verifier_uses_explicit_candidate_despite_stale_provenance_and_marker(tmp_path):
    from src.services.model_artifacts import artifacts_by_id, load_manifest, provenance_path, verify_artifact

    _fake_manifest(tmp_path)
    snapshot = _write_fake_hf_snapshot(tmp_path)
    wrong_snapshot = _write_fake_hf_snapshot(
        tmp_path,
        revision="ffffffffffffffffffffffffffffffffffffffff",
    )
    marker_dir = tmp_path / "models" / "whisper" / "Systran-faster-whisper-small"
    marker_dir.mkdir(parents=True)
    marker_dir.joinpath("SNAPSHOT_PATH.txt").write_text(str(wrong_snapshot), encoding="utf-8")

    manifest = load_manifest(tmp_path)
    artifact = artifacts_by_id(manifest)["faster_whisper_small"]
    provenance = provenance_path(tmp_path, artifact)
    provenance.parent.mkdir(parents=True)
    provenance.write_text(
        json.dumps({
            "artifact_id": "faster_whisper_small",
            "repo_id": "Systran/faster-whisper-small",
            "revision": "ffffffffffffffffffffffffffffffffffffffff",
            "snapshot_relative_path": "models/whisper/missing",
        }),
        encoding="utf-8",
    )

    result = verify_artifact(artifact, root=tmp_path, candidate_path=snapshot)

    assert result.ok is True
    assert result.resolved_path == snapshot
    assert "provenance_revision_mismatch:faster_whisper_small" in result.warnings
    assert "snapshot_marker_revision_mismatch:faster_whisper_small" in result.warnings


def test_strict_hf_verifier_rejects_same_size_blob_mutation(tmp_path):
    from src.services.model_artifacts import verify_profile

    _fake_manifest(tmp_path, config=b"abc")
    snapshot = _write_fake_hf_snapshot(tmp_path, config=b"abc")
    (snapshot / "config.json").write_bytes(b"xyz")

    result = verify_profile("lite_rtx2050", root=tmp_path)[0]

    assert result.ok is False
    assert "hf_blob_id_mismatch:faster_whisper_small:config.json" in result.errors


def test_precache_materializes_zero_byte_hf_snapshot_files_from_blobs(tmp_path):
    from src.services.model_artifacts import artifacts_by_id, load_manifest, materialize_hf_snapshot_from_cache, verify_profile

    _fake_manifest(tmp_path)
    snapshot = _write_fake_hf_snapshot(tmp_path, config=b"", model=b"")
    _write_fake_hf_blobs(tmp_path)
    manifest = load_manifest(tmp_path)
    artifact = artifacts_by_id(manifest)["faster_whisper_small"]

    errors = materialize_hf_snapshot_from_cache(artifact, snapshot, root=tmp_path)
    result = verify_profile("lite_rtx2050", root=tmp_path)[0]

    assert errors == []
    assert result.ok is True
    assert (snapshot / "config.json").read_bytes() == b"abc"
    assert (snapshot / "model.bin").read_bytes() == b"model"


def test_lite_precache_rejects_local_dir_for_hf_cache_layout(tmp_path):
    _fake_manifest(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/precache_lite_models.py",
            "--root",
            str(tmp_path),
            "--model",
            "small",
            "--local-dir",
            "readable-copy",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "local_dir_unsupported_for_hf_cache" in result.stdout


def test_verify_is_read_only_by_default_and_writes_provenance_after_success(tmp_path):
    from src.services.model_artifacts import artifacts_by_id, load_manifest, provenance_path, verify_artifact

    _fake_manifest(tmp_path)
    _write_fake_hf_snapshot(tmp_path)
    manifest = load_manifest(tmp_path)
    artifact = artifacts_by_id(manifest)["faster_whisper_small"]
    provenance = provenance_path(tmp_path, artifact)

    result = verify_artifact(artifact, root=tmp_path)
    assert result.ok is True
    assert not provenance.exists()

    result = verify_artifact(artifact, root=tmp_path, write_provenance=True)
    assert result.ok is True
    assert provenance.exists()
    payload = json.loads(provenance.read_text(encoding="utf-8"))
    assert payload["snapshot_relative_path"].startswith("models/whisper/")
    assert not Path(payload["snapshot_relative_path"]).is_absolute()


def test_health_verifier_caches_strict_result_until_file_stat_changes(monkeypatch, tmp_path):
    from src.services import model_artifacts
    from src.services.model_artifacts import (
        ArtifactVerification,
        artifacts_by_id,
        clear_model_artifact_health_cache,
        load_manifest,
        verify_artifact_for_health,
    )

    _fake_manifest(tmp_path)
    snapshot = _write_fake_hf_snapshot(tmp_path)
    manifest = load_manifest(tmp_path)
    artifact = artifacts_by_id(manifest)["faster_whisper_small"]
    calls = []

    def fake_strict_verify(artifact_arg, **kwargs):
        calls.append(kwargs)
        return ArtifactVerification(True, artifact_arg["id"], snapshot)

    monkeypatch.setattr(model_artifacts, "verify_artifact", fake_strict_verify)
    clear_model_artifact_health_cache()
    try:
        first = verify_artifact_for_health(artifact, root=tmp_path, ttl_seconds=300)
        second = verify_artifact_for_health(artifact, root=tmp_path, ttl_seconds=300)

        assert first.ok is True
        assert second.ok is True
        assert len(calls) == 1

        (snapshot / "model.bin").write_bytes(b"changed-model")
        third = verify_artifact_for_health(artifact, root=tmp_path, ttl_seconds=300)

        assert third.ok is True
        assert len(calls) == 2
    finally:
        clear_model_artifact_health_cache()


def test_verify_models_cli_supports_temp_root(tmp_path):
    _fake_manifest(tmp_path)
    _write_fake_hf_snapshot(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_models.py",
            "--root",
            str(tmp_path),
            "--profile",
            "lite_rtx2050",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[OK] faster_whisper_small" in result.stdout


def test_transcribe_dialog_diarization_toggle_sends_real_method():
    source = (ROOT / "frontend" / "src" / "components" / "TranscribeDialog.tsx").read_text(encoding="utf-8")

    assert "const preferredDiarizationMethod = runtimeProfile?.diarization?.preferred_method || 'pyannote';" in source
    assert "onChange={(e) => handleDiarizationToggle(e.target.checked)}" in source
    assert "onChange={(e) => handleDiarizationMethodChange(e.target.value)}" in source
    assert "setDiarizationMethod(defaultDiarizationEnabled ? preferredDiarizationMethod : 'none');" in source
    assert "['rtx2050_safe', 'rtx2050_fast', 'balanced'" not in source


def test_file_polling_preserves_has_diarization_flag():
    source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")

    assert "if (statusData.has_diarization !== undefined)" in source
    assert "updated.has_diarization = statusData.has_diarization;" in source
