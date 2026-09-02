from __future__ import annotations

import ast
import json
import shutil
import subprocess
from pathlib import Path

from scripts.rehearse_release_candidate import _workspace_fingerprint
from scripts.verify_release_test_profile import (
    ReleaseProfileError,
    assess_collection,
    build_pytest_command,
    parse_collected_nodeids,
    resolve_candidate_python,
    validate_profile,
    verify_candidate_binding,
)


def _write(root: Path, relative: str, content: str) -> None:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def _init_repo(root: Path) -> None:
    subprocess.run(
        ["git", "init", str(root)],
        check=True,
        capture_output=True,
        text=True,
    )


def _profile() -> dict:
    return {
        "schema_version": "stt-release-test-profile-v1",
        "profile_id": "fixture-v1",
        "scope": "fixture",
        "test_root": "tests",
        "pytest_args": ["-q"],
        "selection": {
            "release_blocking_rule": (
                "all_collected_tests_except_declared_non_release"
            ),
            "non_release_tests": [
                {
                    "nodeid": "tests/test_example.py::test_historical",
                    "category": "historical_evidence",
                    "reason_code": "FIXTURE",
                    "rationale": "Fixture evidence is not shipped.",
                    "required_paths": ["docs/evidence.json"],
                    "separate_gate": "fixture evidence gate",
                }
            ],
        },
        "candidate_binding": {
            "required": True,
            "accepted_rehearsal_schema_versions": [
                "stt-release-candidate-rehearsal-v5"
            ],
            "fingerprint_field": (
                "candidate.workspace_content_fingerprint_sha256"
            ),
            "materialized_fingerprint_field": (
                "candidate.materialized_content_fingerprint_sha256"
            ),
            "manifest_verdict_required": "PASS",
            "content_scan_blocked_forbidden": True,
        },
        "limitations": [],
    }


def _candidate_report(root: Path, candidate_root: Path, paths: list[str]) -> dict:
    return {
        "schema_version": "stt-release-candidate-rehearsal-v5",
        "candidate": {
            "tree_oid": "a" * 40,
            "export_root": str(candidate_root),
            "paths": paths,
            "workspace_content_fingerprint_sha256": _workspace_fingerprint(
                root,
                paths,
            ),
            "materialized_content_fingerprint_sha256": _workspace_fingerprint(
                candidate_root,
                paths,
            ),
        },
        "candidate_manifest": {
            "verdict": "PASS",
            "entries": [{"path": path} for path in paths],
        },
        "content_scan": {"verdict": "PASS"},
        "selection": {
            "missing_document_script_references": [],
            "dependency_closure": {"parse_errors": []},
        },
    }


def test_profile_defaults_every_unlisted_test_to_release_blocking(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "tests/test_example.py",
        "def test_release(): pass\n\ndef test_historical(): pass\n",
    )
    profile = _profile()

    assert validate_profile(tmp_path, profile) == []
    collection = assess_collection(
        profile,
        [
            "tests/test_example.py::test_release",
            "tests/test_example.py::test_historical",
        ],
    )

    assert collection["status"] == "PASS"
    assert collection["release_blocking_test_count"] == 1
    assert collection["declared_non_release_test_count"] == 1
    assert collection["non_release_category_counts"] == {"historical_evidence": 1}


def test_repository_profile_non_release_nodeids_reference_declared_tests() -> None:
    root = Path(__file__).resolve().parents[1]
    profile = json.loads(
        (root / "config/release/backend-source-test-profile.v1.json").read_text(
            encoding="utf-8"
        )
    )

    for entry in profile["selection"]["non_release_tests"]:
        test_path, test_name = entry["nodeid"].split("::", 1)
        module = ast.parse((root / test_path).read_text(encoding="utf-8"))
        declared = {
            node.name
            for node in ast.walk(module)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert test_name in declared, entry["nodeid"]


def test_profile_rejects_duplicate_or_missing_exclusion_nodeids(tmp_path: Path) -> None:
    _write(tmp_path, "tests/test_example.py", "def test_historical(): pass\n")
    profile = _profile()
    profile["selection"]["non_release_tests"].append(
        dict(profile["selection"]["non_release_tests"][0])
    )

    errors = validate_profile(tmp_path, profile)

    assert "non_release_tests[1]:nodeid_duplicate" in errors
    collection = assess_collection(profile, ["tests/test_example.py::test_other"])
    assert collection["status"] == "BLOCKED"
    assert collection["missing_declared_nodeids"] == [
        "tests/test_example.py::test_historical"
    ]


def test_candidate_binding_detects_stale_or_unmanifested_source(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    candidate_root = tmp_path / "candidate"
    source_root.mkdir()
    candidate_root.mkdir()
    _init_repo(source_root)
    _write(source_root, "tests/test_example.py", "def test_historical(): pass\n")
    _write(source_root, "src/main.py", "VALUE = 1\n")
    paths = ["src/main.py", "tests/test_example.py"]
    for path in paths:
        target = candidate_root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_root / path, target)
    report = _candidate_report(source_root, candidate_root, paths)

    current = verify_candidate_binding(
        source_root,
        _profile(),
        report,
        candidate_root=candidate_root,
    )
    assert current["status"] == "PASS"
    assert current["source_stale"] is False
    assert current["candidate_materialization_matches"] is True

    _write(source_root, "src/main.py", "VALUE = 2\n")
    stale = verify_candidate_binding(
        source_root,
        _profile(),
        report,
        candidate_root=candidate_root,
    )
    assert stale["status"] == "BLOCKED"
    assert "candidate_source_stale" in stale["errors"]
    assert "candidate_materialization_mismatch" not in stale["errors"]

    _write(source_root, "src/main.py", "VALUE = 1\n")
    _write(source_root, "src/unmanifested.py", "VALUE = 3\n")
    extra = verify_candidate_binding(
        source_root,
        _profile(),
        report,
        candidate_root=candidate_root,
    )
    assert "candidate_unmanifested_release_path" in extra["errors"]
    assert extra["unexpected_release_paths"] == [
        "src/unmanifested.py"
    ]

    _write(candidate_root, "src/main.py", "VALUE = 4\n")
    mismatched = verify_candidate_binding(
        source_root,
        _profile(),
        report,
        candidate_root=candidate_root,
    )
    assert "candidate_materialization_mismatch" in mismatched["errors"]


def test_candidate_binding_allows_a_separately_bound_eol_materialization(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    candidate_root = tmp_path / "candidate"
    source_root.mkdir()
    candidate_root.mkdir()
    _init_repo(source_root)
    (source_root / "src").mkdir()
    (candidate_root / "src").mkdir()
    (source_root / "src/main.py").write_bytes(b"FIRST = 1\nSECOND = 2\n")
    (candidate_root / "src/main.py").write_bytes(
        b"FIRST = 1\r\nSECOND = 2\r\n"
    )
    paths = ["src/main.py"]
    report = _candidate_report(source_root, candidate_root, paths)

    binding = verify_candidate_binding(
        source_root,
        _profile(),
        report,
        candidate_root=candidate_root,
    )

    assert binding["status"] == "PASS"
    assert (
        binding["expected_workspace_content_fingerprint_sha256"]
        != binding["expected_materialized_content_fingerprint_sha256"]
    )
    assert binding["source_stale"] is False
    assert binding["candidate_materialization_matches"] is True


def test_candidate_binding_blocks_unmanifested_files_and_redacts_sensitive_names(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    candidate_root = tmp_path / "candidate"
    source_root.mkdir()
    candidate_root.mkdir()
    _init_repo(source_root)
    _write(source_root, "tests/test_example.py", "def test_historical(): pass\n")
    _write(candidate_root, "tests/test_example.py", "def test_historical(): pass\n")
    paths = ["tests/test_example.py"]
    report = _candidate_report(source_root, candidate_root, paths)
    _write(candidate_root, "notes.txt", "not in manifest\n")
    _write(candidate_root, "private-case-name.wav", "sensitive fixture\n")
    _write(candidate_root, "venv/Lib/site-packages/generated.py", "ignored\n")

    binding = verify_candidate_binding(
        source_root,
        _profile(),
        report,
        candidate_root=candidate_root,
    )

    assert "candidate_unmanifested_path" in binding["errors"]
    assert "candidate_unmanifested_sensitive_path" in binding["errors"]
    extra = binding["unmanifested_candidate_paths"]
    assert extra["review_paths"] == ["notes.txt"]
    assert extra["sensitive_path_count"] == 1
    assert "private-case-name" not in json.dumps(binding)
    assert "generated.py" not in json.dumps(binding)


def test_candidate_binding_report_does_not_copy_candidate_contents(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    marker = "sensitive-fixture-value-must-not-be-serialized"
    _write(tmp_path, "tests/test_example.py", marker)
    paths = ["tests/test_example.py"]

    binding = verify_candidate_binding(
        tmp_path,
        _profile(),
        _candidate_report(tmp_path, tmp_path, paths),
    )

    assert marker not in json.dumps(binding)
    assert len(binding["source_workspace_content_fingerprint_sha256"]) == 64
    assert len(binding["candidate_content_fingerprint_sha256"]) == 64


def test_collection_parser_and_command_use_exact_nodeids() -> None:
    profile = _profile()
    output = """
tests/test_example.py::test_release
tests\\test_example.py::test_historical

2 tests collected in 0.01s
"""

    assert parse_collected_nodeids(output) == [
        "tests/test_example.py::test_historical",
        "tests/test_example.py::test_release",
    ]
    command = build_pytest_command(profile, python_executable="python")
    assert command[:5] == ["python", "-m", "pytest", "tests", "-q"]
    assert command[-1] == (
        "--deselect=tests/test_example.py::test_historical"
    )


def test_candidate_python_must_exist_inside_candidate(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate"
    candidate.mkdir()
    outside = tmp_path / "outside-python.exe"
    outside.write_text("fixture", encoding="utf-8")

    try:
        resolve_candidate_python(candidate, str(outside))
    except ReleaseProfileError as exc:
        assert "inside the candidate" in str(exc)
    else:
        raise AssertionError("outside interpreter must be rejected")

    relative = "venv/Scripts/python.exe"
    _write(candidate, relative, "fixture")
    assert resolve_candidate_python(candidate, relative) == (
        candidate / relative
    ).resolve()
