from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.audit_release_inventory import build_report, classify_path, main


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


def _commit(repo: Path) -> None:
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.name=Release Inventory Test",
        "-c",
        "user.email=release-inventory@example.test",
        "commit",
        "-m",
        "fixture",
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init")
    _write(repo, "src/__init__.py", "")
    _write(repo, "src/main.py", "VALUE = 1\n")
    _write(repo, "frontend/src/main.ts", "export const value = 1;\n")
    _write(repo, ".gitignore", ".env\noutput/\n")
    _commit(repo)
    return repo


def test_detects_tracked_python_import_of_untracked_module(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/main.py", "from src.services.new_runtime import VALUE\n")
    _write(repo, "src/services/new_runtime.py", "VALUE = 1\n")

    report = build_report(repo)

    assert report["verdict"] == "BLOCKED"
    missing = report["dependencies"]["workspace_tracked"][
        "missing_local_dependencies"
    ]
    assert missing == [
        {
            "source": "src/main.py",
            "reference": "src.services.new_runtime",
            "workspace_target": "src/services/new_runtime.py",
            "target_tracked_in_index": False,
        }
    ]
    assert "TRACKED_IMPORTS_UNTRACKED" in {
        blocker["code"] for blocker in report["blockers"]
    }


def test_detects_relative_frontend_import_of_untracked_utility(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "frontend/src/main.ts", "import { value } from './utils/value';\n")
    _write(repo, "frontend/src/utils/value.ts", "export const value = 1;\n")

    report = build_report(repo)

    assert report["dependencies"]["workspace_tracked"][
        "missing_local_dependencies"
    ] == [
        {
            "source": "frontend/src/main.ts",
            "reference": "frontend/src/utils/value.ts",
            "workspace_target": "frontend/src/utils/value.ts",
            "target_tracked_in_index": False,
        }
    ]


def test_does_not_parse_json_or_declaration_files_as_frontend_source(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    _write(
        repo,
        "frontend/src/data.json",
        '{"text": "import ./utils/workspace-only"}\n',
    )
    declaration = repo / "frontend/src/runtime.d.ts"
    declaration.write_text(
        "declare const token: string;\n",
        encoding="utf-16",
    )
    _commit(repo)
    _write(repo, "frontend/src/utils/workspace-only.ts", "export const value = 1;\n")

    report = build_report(repo)

    for snapshot in report["dependencies"].values():
        assert snapshot["parse_errors"] == []
        assert snapshot["missing_local_dependencies"] == []


def test_index_closure_uses_staged_content_not_workspace_content(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/services/helper.py", "VALUE = 2\n")
    _write(repo, "src/main.py", "from src.services.helper import VALUE\n")
    _git(repo, "add", "src/main.py", "src/services/helper.py")
    _write(repo, "src/main.py", "from src.services.workspace_only import VALUE\n")
    _write(repo, "src/services/workspace_only.py", "VALUE = 3\n")

    report = build_report(repo)

    assert report["dependencies"]["index"]["closed"] is True
    assert report["partial_staged_paths"] == ["src/main.py"]
    missing = report["dependencies"]["workspace_tracked"][
        "missing_local_dependencies"
    ]
    assert missing[0]["workspace_target"] == "src/services/workspace_only.py"


def test_classifies_generated_sensitive_and_release_relevant_paths(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, "scripts/preflight_machine.ps1", "Write-Output ok\n")
    _write(repo, "output/report.json", "{}\n")
    _write(repo, ".env", "DO_NOT_READ=this-content\n")
    _write(repo, "id_rsa", "DO_NOT_READ=this-key\n")
    _write(repo, "output/private-case-name/token.json", "DO_NOT_READ=this-token\n")

    report = build_report(repo)

    assert "scripts/preflight_machine.ps1" in report["untracked"][
        "release_relevant_paths"
    ]
    assert report["untracked"]["generated_count"] == 0
    assert report["untracked"]["sensitive_count"] == 0
    risks = {item["path"]: item for item in report["secret_filename_risks"]}
    assert ".env" not in risks
    assert "private-case-name" not in json.dumps(report)
    assert report["secret_filename_risk_summary"]["redacted_path_count"] == 1
    assert risks["id_rsa"]["severity"] == "critical"
    assert risks["id_rsa"]["tracked_in_index"] is False


def test_already_committed_sensitive_data_blocks_release_without_serializing_name(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    sensitive_name = "private-call-recording.mp3"
    _write(repo, sensitive_name, "binary-placeholder")
    _commit(repo)

    report = build_report(repo)
    serialized = json.dumps(report)

    assert report["verdict"] == "BLOCKED"
    assert "TRACKED_SENSITIVE_PATH" in {
        blocker["code"] for blocker in report["blockers"]
    }
    assert report["tracked_prohibited"]["sensitive_count"] == 1
    assert report["tracked_prohibited"]["sensitive_groups"][0][
        "samples_redacted"
    ] is True
    assert sensitive_name not in serialized


def test_path_classification_contract() -> None:
    assert classify_path("src/service.py")[0] == "RUNTIME_REQUIRED"
    assert classify_path("frontend/src/view.tsx")[0] == "RUNTIME_REQUIRED"
    assert classify_path("tests/test_view.py")[0] == "TEST_REQUIRED"
    assert classify_path("scripts/preflight_new_machine.ps1")[0] == "STARTUP_REQUIRED"
    assert classify_path("config/models/model.json")[0] == "CONFIG_MANIFEST"
    assert classify_path("frontend/.eslintrc.cjs")[0] == "CONFIG_MANIFEST"
    assert classify_path("requirements-constraints-py311.txt")[0] == "CONFIG_MANIFEST"
    assert classify_path("output/run.json")[0] == "SENSITIVE_LOCAL"
    assert classify_path("cases.json")[0] == "SENSITIVE_LOCAL"
    assert classify_path("tasks.json")[0] == "SENSITIVE_LOCAL"
    assert classify_path(".cursor/manual-rule/project.mdc")[0] == "GENERATED_LOCAL"
    assert classify_path("frontend/dist/index.js")[0] == "GENERATED_LOCAL"
    assert classify_path("frontend/src/FileCard_old.tsx")[0] == "LEGACY_REMOVE"


def test_secret_walk_prunes_generated_research_and_browser_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    _write(repo, ".planning/cache/token.json", "DO_NOT_READ\n")
    _write(repo, ".playwright-cli/session/private-key.pem", "DO_NOT_READ\n")
    _write(repo, ".env", "DO_NOT_READ\n")

    report = build_report(repo)
    risks = {item["path"] for item in report["secret_filename_risks"]}

    assert ".env" not in risks
    assert not any(path.startswith(".planning/") for path in risks)
    assert not any(path.startswith(".playwright-cli/") for path in risks)
    assert report["secret_filename_risk_summary"]["redacted_path_count"] == 1


def test_cli_writes_json_and_returns_two_for_blockers(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    repo = _repo(tmp_path)
    _write(repo, "src/main.py", "from src.missing_local import VALUE\n")
    _write(repo, "src/missing_local.py", "VALUE = 1\n")
    output = tmp_path / "inventory.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "audit_release_inventory.py",
            "--repo-root",
            str(repo),
            "--output",
            str(output),
        ],
    )

    assert main() == 2
    console = json.loads(capsys.readouterr().out)
    artifact = json.loads(output.read_text(encoding="utf-8"))
    assert console["verdict"] == "BLOCKED"
    assert artifact["schema_version"] == "stt-release-inventory-v2"
    assert artifact["mode"] == "read_only_git_inventory"
