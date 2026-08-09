"""Capture and seal primary-source metadata used by diarization audits."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Any


CANONICAL_ROOT = Path(r"E:\research\STT")
HARNESS_PATH = "scripts/capture_diarization_primary_sources.py"
DEFAULT_OUTPUT = Path(
    "docs/reviews/artifacts/2026-08-09-diarization-primary-source-verification.json"
)
USER_AGENT = "SpeechToInfomation-RTK-Primary-Capture/1.0"
COMMUNITY_1_REVISION = "3533c8cf8e369892e6b79ff1bf80f7b0286a54ee"
COMMUNITY_1_REQUIRED_FILES = (
    "config.yaml",
    "embedding/pytorch_model.bin",
    "plda/plda.npz",
    "plda/xvec_transform.npz",
    "segmentation/pytorch_model.bin",
)
SOURCE_URLS = {
    "community_1_metadata": (
        "https://huggingface.co/api/models/"
        "pyannote/speaker-diarization-community-1"
    ),
    "pyannote_audio_4_0_0_pypi": (
        "https://pypi.org/pypi/pyannote.audio/4.0.0/json"
    ),
    "pyannote_audio_4_0_0_release": (
        "https://api.github.com/repos/pyannote/pyannote-audio/releases/tags/4.0.0"
    ),
    "arxiv_1911_01255": "https://export.arxiv.org/api/query?id_list=1911.01255",
    "arxiv_1906_07839": "https://export.arxiv.org/api/query?id_list=1906.07839",
    "arxiv_2307_11394": "https://export.arxiv.org/api/query?id_list=2307.11394",
    "pyannote_audio_github": "https://api.github.com/repos/pyannote/pyannote-audio",
}
MIGRATION_SOURCE_IDS = (
    "community_1_metadata",
    "pyannote_audio_4_0_0_pypi",
    "pyannote_audio_4_0_0_release",
)


def _normalized_absolute(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def _canonical_repo(path: Path) -> Path:
    if _normalized_absolute(path) != _normalized_absolute(CANONICAL_ROOT):
        raise ValueError(f"repo must be exactly {CANONICAL_ROOT}")
    return CANONICAL_ROOT


def _validated_output(repo_root: Path, value: Path) -> Path:
    output = value if value.is_absolute() else repo_root / value
    output = output.resolve(strict=False)
    allowed_root = (repo_root / "docs/reviews/artifacts").resolve()
    try:
        within_allowed_root = (
            os.path.commonpath((str(output), str(allowed_root)))
            == str(allowed_root)
        )
    except ValueError:
        within_allowed_root = False
    if not within_allowed_root:
        raise ValueError("output must stay under docs/reviews/artifacts")
    return output


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _content_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _observed_at(value: str | None) -> str:
    if value is None:
        return datetime.now().astimezone().isoformat()
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("observed-at must include a timezone")
    return parsed.isoformat()


def _fetch(url: str) -> tuple[bytes, int, str | None]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read(), int(response.status), response.headers.get("Content-Type")


def _json(content: bytes) -> dict[str, Any]:
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("official JSON response must be an object")
    return payload


def _atom_title(content: bytes) -> str | None:
    root = ET.fromstring(content)
    namespace = "{http://www.w3.org/2005/Atom}"
    node = root.find(f"{namespace}entry/{namespace}title")
    return " ".join((node.text or "").split()) if node is not None else None


def _verified_fields(source_id: str, content: bytes) -> dict[str, Any]:
    if source_id == "community_1_metadata":
        payload = _json(content)
        siblings = {
            str(item.get("rfilename"))
            for item in payload.get("siblings", [])
            if isinstance(item, dict) and item.get("rfilename")
        }
        return {
            "model_id": payload.get("id"),
            "revision": payload.get("sha"),
            "gated": payload.get("gated"),
            "license": (payload.get("cardData") or {}).get("license"),
            "required_files": list(COMMUNITY_1_REQUIRED_FILES),
            "required_files_present": all(
                relative in siblings for relative in COMMUNITY_1_REQUIRED_FILES
            ),
        }
    if source_id == "pyannote_audio_4_0_0_pypi":
        info = _json(content).get("info") or {}
        requirements = list(info.get("requires_dist") or [])
        return {
            "version": info.get("version"),
            "requires_python": info.get("requires_python"),
            "runtime_requirements": [
                requirement
                for requirement in requirements
                if any(
                    name in requirement.casefold()
                    for name in ("torch", "torchaudio", "torchcodec", "huggingface")
                )
            ],
        }
    if source_id == "pyannote_audio_4_0_0_release":
        payload = _json(content)
        body = str(payload.get("body") or "")
        return {
            "tag": payload.get("tag_name"),
            "published_at": payload.get("published_at"),
            "offline_local_load_documented": "Offline (air-gapped) use" in body,
            "token_keyword_breaking_change": "rename `use_auth_token` to `token`"
            in body,
            "torchcodec_audio_io": "switch from `torchaudio` to `torchcodec`"
            in body,
            "community_output_object_documented": all(
                marker in body
                for marker in ("speaker_diarization", "exclusive_speaker_diarization")
            ),
        }
    if source_id.startswith("arxiv_"):
        return {"title": _atom_title(content)}
    if source_id == "pyannote_audio_github":
        payload = _json(content)
        return {
            "full_name": payload.get("full_name"),
            "default_branch": payload.get("default_branch"),
            "license_spdx_id": (payload.get("license") or {}).get("spdx_id"),
        }
    raise ValueError(f"unsupported source id: {source_id}")


def _capture_id(observed_at: str, sources: list[dict[str, Any]]) -> str:
    canonical = json.dumps(
        {"observed_at": observed_at, "sources": sources},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _content_sha256(canonical)


def _stable_semantics_valid(rows: dict[str, dict[str, Any]]) -> bool:
    hf = rows.get("community_1_metadata", {}).get("verified_fields", {})
    pypi = rows.get("pyannote_audio_4_0_0_pypi", {}).get("verified_fields", {})
    release = rows.get("pyannote_audio_4_0_0_release", {}).get(
        "verified_fields", {}
    )
    requirements = set(pypi.get("runtime_requirements") or [])
    expected_titles = {
        "arxiv_1911_01255": "pyannote.audio: neural building blocks for speaker diarization",
        "arxiv_1906_07839": "The Second DIHARD Diarization Challenge: Dataset, task, and baselines",
        "arxiv_2307_11394": "MeetEval: A Toolkit for Computation of Word Error Rates for Meeting Transcription Systems",
    }
    return bool(
        hf.get("model_id") == "pyannote/speaker-diarization-community-1"
        and hf.get("revision") == COMMUNITY_1_REVISION
        and hf.get("gated") == "auto"
        and str(hf.get("license", "")).casefold() == "cc-by-4.0"
        and hf.get("required_files") == list(COMMUNITY_1_REQUIRED_FILES)
        and hf.get("required_files_present") is True
        and pypi.get("version") == "4.0.0"
        and pypi.get("requires_python") == ">=3.10"
        and {
            "huggingface-hub>=0.28.1",
            "torch>=2.8.0",
            "torchaudio>=2.8.0",
            "torchcodec>=0.6.0",
        }.issubset(requirements)
        and release.get("tag") == "4.0.0"
        and release.get("published_at") == "2025-09-29T12:04:16Z"
        and release.get("offline_local_load_documented") is True
        and release.get("token_keyword_breaking_change") is True
        and release.get("torchcodec_audio_io") is True
        and release.get("community_output_object_documented") is True
        and all(
            rows.get(source_id, {}).get("verified_fields", {}).get("title") == title
            for source_id, title in expected_titles.items()
        )
        and rows.get("pyannote_audio_github", {})
        .get("verified_fields", {})
        .get("full_name")
        == "pyannote/pyannote-audio"
    )


def validate_capture_payload(
    repo_root: Path, payload: dict[str, Any]
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    harness = repo_root / HARNESS_PATH
    try:
        observed_at = datetime.fromisoformat(
            str(payload.get("observed_at", "")).replace("Z", "+00:00")
        )
        if observed_at.tzinfo is None:
            errors.append("observed_at_missing_timezone")
    except ValueError:
        errors.append("observed_at_invalid")
    if payload.get("schema_version") != "rtk-evidence-v1":
        errors.append("schema_version_invalid")
    if payload.get("artifact_type") != "diarization-primary-source-capture":
        errors.append("artifact_type_invalid")
    if payload.get("repo_root") != str(repo_root) or payload.get("canonical_workspace") is not True:
        errors.append("workspace_binding_invalid")
    if payload.get("scope") != "official_public_metadata_only_no_model_download":
        errors.append("scope_invalid")
    if payload.get("verdict") != "PASS" or payload.get("exit_code") != 0:
        errors.append("verdict_invalid")
    if payload.get("harness_path") != HARNESS_PATH or not harness.is_file():
        errors.append("harness_path_invalid")
    else:
        harness_sha256 = _sha256(harness)
        if payload.get("harness_sha256") != harness_sha256:
            errors.append("harness_sha256_invalid")
        if payload.get("source_sha256") != {HARNESS_PATH: harness_sha256}:
            errors.append("source_sha256_invalid")
    command = payload.get("command")
    if not isinstance(command, list) or HARNESS_PATH not in command:
        errors.append("command_invalid")
    environment = payload.get("environment")
    if not isinstance(environment, dict) or environment.get("network_access") != "official_metadata_only":
        errors.append("environment_invalid")

    rows_list = payload.get("sources")
    rows = {
        str(row.get("id")): row
        for row in rows_list or []
        if isinstance(row, dict) and row.get("id")
    }
    if not isinstance(rows_list, list) or len(rows_list) != len(rows):
        errors.append("source_rows_invalid")
    if set(rows) != set(SOURCE_URLS):
        errors.append("source_set_invalid")
    for source_id, expected_url in SOURCE_URLS.items():
        row = rows.get(source_id)
        if row is None:
            continue
        if row.get("url") != expected_url or row.get("status") != 200:
            errors.append(f"{source_id}:provenance_invalid")
            continue
        try:
            content = base64.b64decode(row.get("content_base64", ""), validate=True)
        except (TypeError, ValueError):
            errors.append(f"{source_id}:content_base64_invalid")
            continue
        if row.get("content_bytes") != len(content):
            errors.append(f"{source_id}:content_bytes_invalid")
        if row.get("content_sha256") != _content_sha256(content):
            errors.append(f"{source_id}:content_sha256_invalid")
        try:
            verified_fields = _verified_fields(source_id, content)
        except (ET.ParseError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            errors.append(f"{source_id}:content_parse_invalid")
            continue
        if row.get("verified_fields") != verified_fields:
            errors.append(f"{source_id}:verified_fields_invalid")
    if rows and not _stable_semantics_valid(rows):
        errors.append("stable_semantics_invalid")
    if isinstance(rows_list, list) and payload.get("capture_id") != _capture_id(
        str(payload.get("observed_at", "")), rows_list
    ):
        errors.append("capture_id_invalid")
    checks = payload.get("checks")
    if checks != {
        "all_sources_http_200": True,
        "raw_content_hashes_verified": True,
        "stable_semantics_verified": True,
    }:
        errors.append("checks_invalid")
    return not errors, errors


def source_binding(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "url",
            "status",
            "content_type",
            "content_bytes",
            "content_sha256",
            "verified_fields",
        )
    }


def build_capture(repo_root: Path, *, observed_at: str | None) -> dict[str, Any]:
    repo_root = _canonical_repo(repo_root)
    observed = _observed_at(observed_at)
    sources: list[dict[str, Any]] = []
    for source_id, url in SOURCE_URLS.items():
        content, status, content_type = _fetch(url)
        sources.append(
            {
                "id": source_id,
                "url": url,
                "status": status,
                "content_type": content_type,
                "content_bytes": len(content),
                "content_sha256": _content_sha256(content),
                "content_base64": base64.b64encode(content).decode("ascii"),
                "verified_fields": _verified_fields(source_id, content),
            }
        )
    harness_sha256 = _sha256(repo_root / HARNESS_PATH)
    rows = {row["id"]: row for row in sources}
    report = {
        "schema_version": "rtk-evidence-v1",
        "artifact_type": "diarization-primary-source-capture",
        "capture_id": _capture_id(observed, sources),
        "observed_at": observed,
        "repo_root": str(repo_root),
        "canonical_workspace": True,
        "scope": "official_public_metadata_only_no_model_download",
        "verdict": "PASS",
        "exit_code": 0,
        "command": [
            str(repo_root / "venv/Scripts/python.exe"),
            "-B",
            HARNESS_PATH,
            "--output",
            str(DEFAULT_OUTPUT).replace("\\", "/"),
        ],
        "environment": {
            "network_access": "official_metadata_only",
            "user_agent": USER_AGENT,
            "source_count": len(sources),
        },
        "harness_path": HARNESS_PATH,
        "harness_sha256": harness_sha256,
        "source_sha256": {HARNESS_PATH: harness_sha256},
        "sources": sources,
        "checks": {
            "all_sources_http_200": all(row["status"] == 200 for row in sources),
            "raw_content_hashes_verified": all(
                _content_sha256(base64.b64decode(row["content_base64"]))
                == row["content_sha256"]
                for row in sources
            ),
            "stable_semantics_verified": _stable_semantics_valid(rows),
        },
        "limitations": [
            "Official metadata does not prove Vietnamese diarization quality.",
            "No gated model file was downloaded or loaded by this capture.",
        ],
    }
    valid, errors = validate_capture_payload(repo_root, report)
    if not valid:
        raise ValueError("capture validation failed: " + ", ".join(errors))
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, default=CANONICAL_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--observed-at")
    args = parser.parse_args()
    try:
        repo_root = _canonical_repo(args.repo)
        output = _validated_output(repo_root, args.output)
        report = build_capture(repo_root, observed_at=args.observed_at)
    except (OSError, ValueError, ET.ParseError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
