import json
import subprocess
from pathlib import Path

from scripts.audit_reference_repos import (
    build_source_evidence,
    compare_hashes,
    include_untracked,
    model_store_inventory,
)
from scripts.validate_reference_reuse_artifacts import text_check, validate


def test_untracked_inventory_excludes_generated_and_model_trees():
    assert include_untracked("docs/research/protocol.md") is True
    assert include_untracked("src/service.py") is True
    assert include_untracked("models/large/model.gguf") is False
    assert include_untracked(".venv-p6/Lib/site-packages/package.py") is False
    assert include_untracked("node_modules/library/index.js") is False
    assert include_untracked("output/run/result.json") is False


def test_hash_comparison_separates_exact_and_changed_paths():
    result = compare_hashes(
        {
            "left": {"same.py": "a", "changed.py": "b", "left.py": "c"},
            "right": {"same.py": "a", "changed.py": "x", "right.py": "d"},
        }
    )

    pair = result["pairs"][0]
    assert pair["shared_paths"] == 2
    assert pair["exact_paths"] == 1
    assert pair["changed_paths"] == 1
    assert pair["exact_examples"] == ["same.py"]
    assert pair["changed_examples"] == ["changed.py"]


def test_model_store_inventory_records_weight_size_without_hashing(tmp_path: Path):
    model_root = tmp_path / "models" / "asr"
    model_root.mkdir(parents=True)
    (model_root / "model.onnx").write_bytes(b"model")
    (model_root / "tokenizer.json").write_text("{}", encoding="utf-8")
    (model_root / "LICENSE").write_text("test license", encoding="utf-8")

    result = model_store_inventory(tmp_path)

    assert result["present"] is True
    assert result["files"] == 3
    assert result["weight_files"] == 1
    assert result["weight_bytes"] == 5
    assert any(item["path"] == "models/asr/model.onnx" for item in result["largest"])
    assert result["license_files"] == ["models/asr/LICENSE"]


def test_text_check_reports_required_and_forbidden_terms():
    checks = text_check(
        "document",
        "ADOPT this bounded pattern.",
        required_terms=["adopt", "bounded"],
        forbidden_terms=["TBD"],
    )

    assert all(item["passed"] for item in checks)


def test_reference_reuse_artifact_bundle_passes_locked_validator():
    root = Path(__file__).resolve().parents[1]

    report = validate(root)

    assert report["valid"] is True, report["checks_failed"]


def test_source_evidence_identifies_modified_and_untracked_files(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    tracked = repo / "tracked.py"
    tracked.write_text("original\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "tracked.py"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=RTK",
            "-c",
            "user.email=rtk@example.invalid",
            "commit",
            "-m",
            "fixture",
        ],
        check=True,
        capture_output=True,
    )
    tracked.write_text("changed\n", encoding="utf-8")
    (repo / "untracked.py").write_text("new\n", encoding="utf-8")
    spec = tmp_path / "sources.json"
    spec.write_text(
        json.dumps(
            {
                "schema_version": "reference-reuse-source-spec-v1",
                "sources": [
                    {
                        "repo": "ref",
                        "path": "tracked.py",
                        "recommendation_ids": ["TRACKED"],
                        "purpose": "modified fixture",
                    },
                    {
                        "repo": "ref",
                        "path": "untracked.py",
                        "recommendation_ids": ["UNTRACKED"],
                        "purpose": "untracked fixture",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = build_source_evidence(spec, {"ref": repo})

    assert result["errors"] == []
    records = {record["path"]: record for record in result["records"]}
    assert records["tracked.py"]["tracked_state"] == "modified"
    assert records["tracked.py"]["head_git_blob"]
    assert records["tracked.py"]["worktree_git_blob"]
    assert records["untracked.py"]["tracked_state"] == "untracked"
    assert records["untracked.py"]["head_git_blob"] is None
