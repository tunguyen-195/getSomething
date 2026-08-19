from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.rehearse_release_candidate import build_candidate


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _write(repo: Path, relative: str, content: str) -> None:
    target = repo / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _fixture_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo, ".gitignore", ".env\noutput/\n")
    _write(repo, "src/__init__.py", "")
    _write(repo, "src/main.py", "VALUE = 1\n")
    _write(repo, "frontend/src/main.ts", "export const value = 1;\n")
    _write(repo, "private.mp3", "sensitive fixture\n")
    _write(repo, "old_backup.py", "VALUE = 0\n")
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Candidate Test",
        "-c",
        "user.email=candidate@example.test",
        "commit",
        "-m",
        "fixture",
    )
    return repo


def test_candidate_uses_workspace_source_without_changing_real_index(
    tmp_path: Path,
) -> None:
    repo = _fixture_repo(tmp_path)
    _write(repo, "src/main.py", "from src.new_runtime import VALUE\n")
    _write(repo, "src/new_runtime.py", "VALUE = 2\n")
    _write(repo, "tests/test_runtime.py", "def test_value(): assert True\n")
    _write(repo, "frontend/.eslintrc.cjs", "module.exports = { root: true };\n")
    _write(repo, "requirements-constraints-py311.txt", "av==14.2.0\n")
    _write(repo, "notes.md", "research only\n")
    _write(repo, ".planning/private-case-name.json", "generated metadata\n")
    _write(repo, "private-case-name.wav", "sensitive metadata\n")
    before = _git(repo, "ls-files", "--stage").stdout

    export_root = tmp_path / "candidate"
    report = build_candidate(repo, export_root)

    assert report["real_index"]["unchanged"] is True
    assert _git(repo, "ls-files", "--stage").stdout == before
    assert (export_root / "src/main.py").read_text(encoding="utf-8") == (
        "from src.new_runtime import VALUE\n"
    )
    assert (export_root / "src/new_runtime.py").is_file()
    assert (export_root / "tests/test_runtime.py").is_file()
    assert (export_root / "frontend/.eslintrc.cjs").is_file()
    assert (export_root / "requirements-constraints-py311.txt").is_file()
    assert not (export_root / "notes.md").exists()
    assert not (export_root / "private.mp3").exists()
    assert not (export_root / "old_backup.py").exists()
    assert "src/new_runtime.py" in report["selection"]["untracked_included"]
    assert report["schema_version"] == "stt-release-candidate-rehearsal-v4"

    serialized = json.dumps(report)
    assert "private-case-name" not in serialized
    assert report["selection"]["untracked_excluded"]["redacted_path_count"] == 2
    assert report["selection"]["tracked_excluded"]["redacted_path_count"] == 1
    review_paths = {
        item["path"]
        for item in report["selection"]["untracked_excluded"]["review_items"]
    }
    assert "notes.md" in review_paths
    assert report["candidate_manifest"]["entry_count"] == report["candidate"][
        "file_count"
    ]
    manifest = {
        item["path"]: item for item in report["candidate_manifest"]["entries"]
    }
    assert manifest["src/new_runtime.py"]["origin"] == "workspace_untracked"
    assert manifest["src/new_runtime.py"]["review_required"] is False
    assert manifest["src/main.py"]["origin"] == "workspace_tracked"
    assert report["candidate_manifest"]["verdict"] == "PASS"
    assert report["candidate_manifest"]["source_candidate_mismatch_count"] == 0
    assert all(
        item["source_candidate_match"]
        for item in report["candidate_manifest"]["entries"]
    )
    assert all(
        len(item["source_sha256"]) == 64
        for item in report["candidate_manifest"]["entries"]
    )
    assert all(
        len(item["candidate_sha256"]) == 64
        for item in report["candidate_manifest"]["entries"]
    )
    assert len(report["candidate"]["workspace_content_fingerprint_sha256"]) == 64


def test_candidate_rejects_nonempty_export_directory(tmp_path: Path) -> None:
    repo = _fixture_repo(tmp_path)
    export_root = tmp_path / "candidate"
    export_root.mkdir()
    _write(export_root, "existing.txt", "do not overwrite\n")

    try:
        build_candidate(repo, export_root)
    except ValueError as exc:
        assert "not empty" in str(exc)
    else:
        raise AssertionError("non-empty export directory must be rejected")


def test_content_scan_blocks_secrets_and_case_data_without_serializing_values(
    tmp_path: Path,
) -> None:
    repo = _fixture_repo(tmp_path)
    secret_value = "ghp_" + "abcdefghijklmnopqrstuvwxyz123456"
    case_value = "123e4567-e89b-42d3-a456-426614174000"
    _write(repo, "config/leaked.txt", f"API_KEY={secret_value}\n")
    _write(
        repo,
        "docs/runbooks/case-example.md",
        f'{{"task_id": "{case_value}"}}\n',
    )
    _write(
        repo,
        "docs/runbooks/placeholder.md",
        "API_KEY=change-me-generate-locally\n",
    )

    report = build_candidate(repo, tmp_path / "candidate")

    assert report["content_scan"]["verdict"] == "BLOCKED"
    rules = {item["rule"] for item in report["content_scan"]["findings"]}
    assert "github_token" in rules
    assert "investigation_record_identifier" in rules
    serialized = json.dumps(report)
    assert secret_value not in serialized
    assert case_value not in serialized
    assert report["content_scan"]["matched_values_recorded"] is False
    assert not any(
        item["path"] == "docs/runbooks/placeholder.md"
        for item in report["content_scan"]["findings"]
    )


def test_document_script_references_drive_selection_and_report_missing(
    tmp_path: Path,
) -> None:
    repo = _fixture_repo(tmp_path)
    _write(
        repo,
        "README.md",
        "Run scripts\\custom_start.ps1 then scripts/missing_probe.py.\n",
    )
    _write(repo, "scripts/custom_start.ps1", "Write-Output ok\n")

    report = build_candidate(repo, tmp_path / "candidate")

    assert (tmp_path / "candidate/scripts/custom_start.ps1").is_file()
    manifest = {
        item["path"]: item for item in report["candidate_manifest"]["entries"]
    }
    assert manifest["scripts/custom_start.ps1"]["selection_reason"] == (
        "canonical_document_reference"
    )
    assert report["selection"]["missing_document_script_references"] == [
        "scripts/missing_probe.py"
    ]


def test_dependency_closure_adds_local_helpers_of_selected_tests(
    tmp_path: Path,
) -> None:
    repo = _fixture_repo(tmp_path)
    _write(repo, "tests/test_helper.py", "from scripts.helper import VALUE\n")
    _write(repo, "scripts/helper.py", "VALUE = 1\n")

    report = build_candidate(repo, tmp_path / "candidate")

    assert (tmp_path / "candidate/scripts/helper.py").is_file()
    manifest = {
        item["path"]: item for item in report["candidate_manifest"]["entries"]
    }
    assert manifest["scripts/helper.py"]["selection_reason"] == (
        "local_dependency_closure"
    )
    assert report["selection"]["dependency_closure"]["added_paths"] == [
        "scripts/helper.py"
    ]
