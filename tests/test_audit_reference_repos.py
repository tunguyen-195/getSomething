import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

from scripts.audit_reference_repos import (
    build_source_evidence,
    compare_hashes,
    include_untracked,
    model_store_inventory,
)
from scripts.reference_port_register import (
    DEFAULT_EVIDENCE,
    PortRegisterError,
    build_register,
    validate_register,
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


def test_reference_port_register_covers_every_decision_and_forbids_copying():
    root = Path(__file__).resolve().parents[1]

    register = build_register(root)

    entries = register["entries"]
    assert len(entries) == 27
    assert len({item["recommendation_id"] for item in entries}) == 27
    assert all(item["copy_code_allowed"] is False for item in entries)
    assert all(item["sources"] for item in entries)
    assert any(
        item["source_snapshot_status"] == "dirty_content_addressed"
        for item in entries
    )
    assert all(
        item["license_status"] == "pending_owner_authorization"
        for item in entries
        if item["decision"] != "REJECT"
    )


def test_reference_port_register_rejects_permissive_copy_policy():
    root = Path(__file__).resolve().parents[1]
    register = deepcopy(build_register(root))
    recommendation_id = register["entries"][0]["recommendation_id"]
    register["entries"][0]["copy_code_allowed"] = True

    failures = validate_register(root, register)

    assert f"register:copy_allowed:{recommendation_id}" in failures
    assert "register:locked_content" in failures


def test_reference_port_register_rejects_incomplete_source_evidence(
    tmp_path: Path,
):
    root = Path(__file__).resolve().parents[1]
    review = root / "docs/reviews/reference-repository-reuse-audit-2026-08-09.md"
    source_spec = root / "docs/research/reference-repo-audit/source-evidence-spec.json"
    evidence = json.loads((root / DEFAULT_EVIDENCE).read_text(encoding="utf-8"))
    evidence["source_evidence"]["records"].pop()

    target_review = tmp_path / review.relative_to(root)
    target_spec = tmp_path / source_spec.relative_to(root)
    target_evidence = tmp_path / DEFAULT_EVIDENCE
    target_review.parent.mkdir(parents=True, exist_ok=True)
    target_spec.parent.mkdir(parents=True, exist_ok=True)
    target_review.write_bytes(review.read_bytes())
    target_spec.write_bytes(source_spec.read_bytes())
    target_evidence.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(PortRegisterError, match="do not match"):
        build_register(tmp_path)


def test_reference_port_register_rejects_forged_source_identity(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    review = root / "docs/reviews/reference-repository-reuse-audit-2026-08-09.md"
    source_spec = root / "docs/research/reference-repo-audit/source-evidence-spec.json"
    evidence = json.loads((root / DEFAULT_EVIDENCE).read_text(encoding="utf-8"))
    evidence["source_evidence"]["records"][0]["source_identity"] = "sha256:" + "0" * 64

    target_review = tmp_path / review.relative_to(root)
    target_spec = tmp_path / source_spec.relative_to(root)
    target_evidence = tmp_path / DEFAULT_EVIDENCE
    target_review.parent.mkdir(parents=True, exist_ok=True)
    target_spec.parent.mkdir(parents=True, exist_ok=True)
    target_review.write_bytes(review.read_bytes())
    target_spec.write_bytes(source_spec.read_bytes())
    target_evidence.write_text(json.dumps(evidence), encoding="utf-8")

    with pytest.raises(PortRegisterError, match="invalid identity"):
        build_register(tmp_path)


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
