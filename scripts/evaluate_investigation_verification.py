"""Run the deterministic T4 verification protocol against locked fixtures.

This harness measures structural safety and replay behavior only. It does not
claim investigative accuracy because the repository does not yet contain a
locked, human-labelled Vietnamese noisy-ASR corpus.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import platform
import socket
import statistics
import subprocess
import sys
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence
from unittest import mock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.services.investigation.discovery import (  # noqa: E402
    DISCOVERY_SYSTEM_PROMPT,
    ChunkPlannerConfig,
    LLMAtomicCandidateDraft,
    LLMDiscoveryResponse,
    RetryPolicy,
    build_chunk_plan,
    build_discovery_batch,
    build_discovery_manifest,
    materialize_llm_candidates,
    verify_discovery_batch,
)
from src.services.investigation.contracts import (  # noqa: E402
    ADAPTIVE_DISCOVERY_PROMPT_VERSION,
)
from src.services.investigation.release_adapter import (  # noqa: E402
    InvestigationReleaseError,
    capture_repository_state,
    release_investigation_run,
)
from src.services.investigation.run_contracts import (  # noqa: E402
    InvestigationRun,
    build_investigation_run_manifest,
)
from src.services.investigation.source_revision import (  # noqa: E402
    SourceRevision,
    SourceScope,
    SourceSegmentDraft,
    build_source_revision,
)
from src.services.investigation.verification import (  # noqa: E402
    CheckerObservation,
    build_verification_batch,
    verify_verification_batch,
)
from src.services.investigation.verification_contracts import (  # noqa: E402
    VERIFICATION_REQUIRED_SOURCE_MODULES,
    VerificationBatch,
)

DEFAULT_MANIFEST = Path("tests/eval/investigation_verification_cases.jsonl")
DEFAULT_OUTPUT_DIR = Path("docs/evals/runs/t4-blocked")
PROTOCOL_VERSION = "investigation-verification-eval-v1.3"
QUALITY_CLAIM = "STRUCTURAL_DIAGNOSTIC_ONLY_EXTERNAL_RELEASE_BOUNDARY_BLOCKED"
LOCKED_MANIFEST_SHA256 = (
    "e5797af7e0a05b2e27a877af1fed757dfb68ee0c4d2e2e8f4725fa18cbecc8a2"
)
MANDATORY_CASE_IDS = (
    "supported-atomic-exact-values",
    "unrelated-semantic-forgery",
    "polarity-inversion",
    "reported-speech-withheld",
    "actor-object-reversal-withheld",
    "compound-assertion-withheld",
    "exact-value-owner-unit-mutation",
    "checker-disagreement-withheld",
    "checker-entailment-cannot-override",
    "opposite-source-assertions-preserved",
    "same-surface-different-spans",
)
DEFAULT_BENCHMARK_CANDIDATES = 1_000
DEFAULT_BENCHMARK_WARMUPS = 1
DEFAULT_BENCHMARK_SAMPLES = 5
DEFAULT_BENCHMARK_MEMORY_SAMPLES = 3
DEFAULT_LATENCY_BUDGET_MS = 30_000.0
DEFAULT_PEAK_MEMORY_BUDGET_MIB = 512.0
T4_SOURCE_DIR = PROJECT_ROOT / "src/services/investigation"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _git_info() -> dict[str, Any]:
    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", *args],
            cwd=PROJECT_ROOT,
            text=True,
            encoding="utf-8",
        ).strip()

    status = run("status", "--porcelain=v1")
    return {
        "revision": run("rev-parse", "HEAD"),
        "branch": run("branch", "--show-current"),
        "dirty": bool(status),
        "untracked": any(line.startswith("??") for line in status.splitlines()),
    }


def _source_hashes(names: Sequence[str] | set[str] | frozenset[str]) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for name in sorted(names):
        path = T4_SOURCE_DIR / name
        if not path.is_file():
            raise FileNotFoundError(f"required source module is missing: {path}")
        hashes[name] = _sha256_file(path)
    return hashes


def _load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as source:
        for line_number, raw_line in enumerate(source, start=1):
            line = raw_line.strip()
            if not line:
                continue
            case = json.loads(line)
            missing = {"id", "segments", "candidates", "expected"} - set(case)
            if missing:
                raise ValueError(
                    f"{path}:{line_number} missing fields: {', '.join(sorted(missing))}"
                )
            case_id = str(case["id"])
            if case_id in seen_ids:
                raise ValueError(f"{path}:{line_number} duplicate case id: {case_id}")
            if not case["segments"]:
                raise ValueError(f"{path}:{line_number} requires at least one segment")
            seen_ids.add(case_id)
            cases.append(case)
    if not cases:
        raise ValueError(f"no cases found in {path}")
    return cases


def _revision(case: Mapping[str, Any]) -> SourceRevision:
    texts = [str(item).strip() for item in case["segments"]]
    case_id = str(case["id"])
    return build_source_revision(
        scope=SourceScope(
            case_id=f"eval-case-{case_id}",
            file_id=f"eval-file-{case_id}",
            source_id=f"eval-source-{case_id}",
        ),
        raw_transcript="\n".join(texts),
        segments=[
            SourceSegmentDraft(
                text=text,
                speaker_id=f"SPEAKER_{index}",
                start_seconds=float(index * 2),
                end_seconds=float(index * 2 + 1),
            )
            for index, text in enumerate(texts)
        ],
    )


def _chunk_config() -> ChunkPlannerConfig:
    return ChunkPlannerConfig(
        max_context_tokens=8_192,
        reserved_output_tokens=512,
        target_chunk_tokens=2_048,
        overlap_turns=1,
        chars_per_token=2.8,
    )


def _discovery_source_hashes() -> dict[str, str]:
    return _source_hashes(
        {
            "chunk_planner.py",
            "discovery.py",
            "discovery_common.py",
            "discovery_contracts.py",
            "exact_detectors.py",
        }
    )


def _build_discovery(case: Mapping[str, Any]):
    revision = _revision(case)
    plan = build_chunk_plan(revision, _chunk_config())
    chunk_by_segment = {
        segment_id: chunk
        for chunk in plan.chunks
        for segment_id in chunk.primary_segment_ids
    }
    drafts_by_chunk: dict[str, list[LLMAtomicCandidateDraft]] = {}
    for spec in case["candidates"]:
        segment_index = int(spec["segment_index"])
        if segment_index < 0 or segment_index >= len(revision.segments):
            raise ValueError(
                f"case {case['id']} candidate segment_index is out of range"
            )
        segment = revision.segments[segment_index]
        statement = str(spec.get("statement") or segment.text)
        if statement == "$segment":
            statement = segment.text
        quote_exact = str(spec.get("quote_exact") or segment.text)
        if quote_exact == "$segment":
            quote_exact = segment.text
        draft = LLMAtomicCandidateDraft(
            candidate_kind=spec.get("candidate_kind", "claim"),
            claim_type=spec["claim_type"],
            statement=statement,
            polarity=spec.get("polarity", "affirmed"),
            segment_id=segment.segment_id,
            quote_exact=quote_exact,
            attributes=spec.get("attributes"),
        )
        chunk = chunk_by_segment[segment.segment_id]
        drafts_by_chunk.setdefault(chunk.chunk_id, []).append(draft)

    candidate_records: list[Any] = []
    for chunk in plan.chunks:
        drafts = drafts_by_chunk.get(chunk.chunk_id, [])
        if not drafts:
            continue
        candidate_records.extend(
            materialize_llm_candidates(
                revision,
                chunk,
                LLMDiscoveryResponse(candidates=tuple(drafts)),
            )
        )

    git = _git_info()
    manifest = build_discovery_manifest(
        chunk_plan=plan,
        transmitted_system_prompt=DISCOVERY_SYSTEM_PROMPT,
        model_id="locked-synthetic-fixture",
        model_digest="sha256:" + "0" * 64,
        provider="deterministic-fixture",
        quantization="none",
        tokenizer_revision="fixture-tokenizer-v1",
        tokenizer_sha256="1" * 64,
        chat_template_revision="fixture-template-v1",
        chat_template_sha256="2" * 64,
        runtime_id=f"python-{platform.python_version()}",
        runtime_digest="sha256:" + "3" * 64,
        decoding_config={"temperature": 0, "seed": 0},
        retry_policy=RetryPolicy(),
        source_module_hashes=_discovery_source_hashes(),
        git_revision=git["revision"],
        git_dirty=git["dirty"],
        git_untracked=git["untracked"],
    )
    batch = build_discovery_batch(
        revision=revision,
        chunk_plan=plan,
        manifest=manifest,
        candidate_records=tuple(candidate_records),
    )
    return revision, verify_discovery_batch(batch, revision)


class _LockedChecker:
    def __init__(self, outcome: str):
        self.outcome = outcome

    def manifest(self) -> Mapping[str, Any]:
        return {
            "adapter_id": "locked-fixture-checker",
            "adapter_version": "1",
            "model_id": "synthetic-signal-only",
            "model_revision": "fixture-r1",
            "runtime_id": "deterministic-fixture",
            "network_required": False,
        }

    def evaluate(self, *, premise: str, hypothesis: str, frame: Any):
        del premise, hypothesis, frame
        return CheckerObservation(outcome=self.outcome, score=0.9)


def _build_t4(
    verified_discovery: Any,
    revision: SourceRevision,
    *,
    checker_outcome: str | None = None,
) -> VerificationBatch:
    git = _git_info()
    checker = _LockedChecker(checker_outcome) if checker_outcome else None
    return build_verification_batch(
        verified_discovery=verified_discovery,
        revision=revision,
        source_module_hashes=_source_hashes(VERIFICATION_REQUIRED_SOURCE_MODULES),
        git_revision=git["revision"],
        git_dirty=git["dirty"],
        git_untracked=git["untracked"],
        checker=checker,
    )


class _NetworkGuard:
    def __init__(self) -> None:
        self.attempts: list[str] = []

    def block(self, *args: Any, **kwargs: Any) -> None:
        target = args[-1] if args else kwargs
        self.attempts.append(repr(target))
        raise RuntimeError("network access is disabled by the T4 evaluation harness")


@contextmanager
def _network_denied() -> Iterator[_NetworkGuard]:
    guard = _NetworkGuard()
    with mock.patch(
        "socket.create_connection", side_effect=guard.block
    ), mock.patch.object(socket.socket, "connect", new=guard.block), mock.patch.object(
        socket.socket, "connect_ex", new=guard.block
    ):
        yield guard


def _actual(batch: VerificationBatch) -> dict[str, Any]:
    failure_codes = sorted(
        {code for record in batch.records for code in record.failure_codes}
    )
    return {
        "status": batch.status,
        "record_count": len(batch.records),
        "dispositions": sorted(record.disposition for record in batch.records),
        "projection_eligibilities": sorted(
            record.projection_eligibility for record in batch.records
        ),
        "failure_codes": failure_codes,
        "claim_count": len(batch.ledger.claims) if batch.ledger else 0,
        "claim_polarities": sorted(
            claim.polarity for claim in (batch.ledger.claims if batch.ledger else [])
        ),
        "merge_count": len(batch.merge_records),
        "contradiction_count": len(batch.contradictions),
        "checker_outcomes": sorted(signal.outcome for signal in batch.checker_signals),
        "network_required": batch.network_required,
        "release_authority": batch.release_authority,
    }


def _compare_expected(
    expected: Mapping[str, Any], actual: Mapping[str, Any]
) -> list[str]:
    failures: list[str] = []
    for key in (
        "status",
        "record_count",
        "dispositions",
        "projection_eligibilities",
        "claim_count",
        "claim_polarities",
        "merge_count",
        "contradiction_count",
        "checker_outcomes",
        "network_required",
        "release_authority",
    ):
        if key in expected and actual.get(key) != expected[key]:
            failures.append(
                f"{key}: expected {expected[key]!r}, got {actual.get(key)!r}"
            )
    for code in expected.get("failure_codes_contain", []):
        if code not in actual["failure_codes"]:
            failures.append(f"missing failure code: {code}")
    for code in expected.get("failure_codes_exclude", []):
        if code in actual["failure_codes"]:
            failures.append(f"unexpected failure code: {code}")
    return failures


def _evaluate_case(case: Mapping[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    with _network_denied() as network_guard:
        revision, verified_discovery = _build_discovery(case)
        batch = _build_t4(
            verified_discovery,
            revision,
            checker_outcome=case.get("checker_outcome"),
        )
        replayed = verify_verification_batch(
            batch,
            verified_discovery=verified_discovery,
            revision=revision,
        ).batch
        rebuilt = _build_t4(
            verified_discovery,
            revision,
            checker_outcome=case.get("checker_outcome"),
        )
    actual = _actual(batch)
    deterministic = (
        replayed.batch_id == batch.batch_id
        and rebuilt.batch_id == batch.batch_id
        and rebuilt.model_dump_json(exclude_none=True)
        == batch.model_dump_json(exclude_none=True)
    )
    failures = _compare_expected(case["expected"], actual)
    if not deterministic:
        failures.append("deterministic replay or rebuild mismatch")
    if network_guard.attempts:
        failures.append("network access attempted")
    return {
        "id": case["id"],
        "description": case.get("description"),
        "passed": not failures,
        "failures": failures,
        "actual": actual,
        "batch_id": batch.batch_id,
        "batch_sha256": batch.batch_sha256,
        "deterministic_replay": deterministic,
        "network_attempt_count": len(network_guard.attempts),
        "network_attempts": network_guard.attempts,
        "latency_ms": (time.perf_counter() - started) * 1_000,
    }


def _release_proposal(
    revision: SourceRevision,
    batch: VerificationBatch,
    state: Any,
) -> dict[str, Any]:
    if batch.status != "success" or batch.ledger is None or not batch.ledger.claims:
        raise ValueError("release probe requires a successful factual T4 ledger")
    claim_refs = [claim.claim_id for claim in batch.ledger.claims]
    sentence = {
        "text": batch.ledger.claims[0].statement,
        "sentence_kind": "factual",
        "claim_refs": claim_refs,
    }
    manifest = build_investigation_run_manifest(
        prompt="Release exact T4 facts only.",
        prompt_version=ADAPTIVE_DISCOVERY_PROMPT_VERSION,
        model_id="locked-synthetic-fixture",
        model_digest="sha256:" + "0" * 64,
        provider="deterministic-fixture",
        decoding_config={"temperature": 0, "seed": 0},
        source_module_hashes=state.release_source_hashes,
        git_revision=state.git_revision,
        git_dirty=state.git_dirty,
        git_untracked=state.git_untracked,
    )
    return {
        "schema_version": "investigation-run-v1.0",
        "run_id": "t4-evaluator-release-probe",
        "run_status": "success",
        "ledger": batch.ledger.model_dump(mode="json", exclude_none=True),
        "projections": {
            "summary": {
                "released_claim_refs": claim_refs,
                "themes": [
                    {
                        "theme_id": "theme-t4-evaluator-release-probe",
                        "title": "Dữ kiện trực tiếp",
                        "claim_refs": claim_refs,
                    }
                ],
                "narrative": {
                    "overview": [sentence],
                    "thematic_groups": [
                        {
                            "theme_ref": "theme-t4-evaluator-release-probe",
                            "sentences": [sentence],
                        }
                    ],
                },
            },
            "analysis": {
                "released_claim_refs": claim_refs,
                "source_attributed_claim_refs": claim_refs,
            },
        },
        "provenance": {
            "source_revision_id": revision.source_revision_id,
            "raw_transcript_sha256": revision.raw_transcript_sha256,
            "normalized_transcript_sha256": revision.normalized_transcript_sha256,
            "segment_count": revision.segment_count,
            **(
                {"audio_sha256": revision.audio_sha256}
                if revision.audio_sha256 is not None
                else {}
            ),
        },
        "safety": {
            "transcript_is_untrusted_data": True,
            "evidence_required_for_released_claims": True,
            "high_risk_requires_human_verification": True,
            "unsupported_high_risk_claims_released": False,
        },
        "manifest": manifest.model_dump(mode="json", exclude_none=True),
    }


def _expect_rejection(
    expected: type[BaseException],
    message: str,
    operation: Any,
) -> None:
    try:
        operation()
    except expected as exc:
        if message not in str(exc):
            raise AssertionError(
                f"expected rejection containing {message!r}, got {exc!r}"
            ) from exc
        return
    raise AssertionError(f"expected {expected.__name__} rejection")


def _run_release_probe(probe_id: str, operation: Any) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        operation()
    except Exception as exc:
        return {
            "id": probe_id,
            "passed": False,
            "failure": f"{type(exc).__name__}: {exc}",
            "latency_ms": (time.perf_counter() - started) * 1_000,
        }
    return {
        "id": probe_id,
        "passed": True,
        "failure": None,
        "latency_ms": (time.perf_counter() - started) * 1_000,
    }


def _evaluate_release_boundary() -> dict[str, Any]:
    base_case = {
        "id": "release-boundary-supported",
        "segments": ["Minh chuyển 15 triệu đồng cho Lan lúc 09:00."],
        "candidates": [
            {
                "segment_index": 0,
                "candidate_kind": "claim",
                "claim_type": "event.transfer",
                "statement": "$segment",
                "polarity": "affirmed",
            }
        ],
        "expected": {},
    }
    revision, verified_discovery = _build_discovery(base_case)
    batch = _build_t4(verified_discovery, revision)
    state = capture_repository_state(PROJECT_ROOT)
    proposal = _release_proposal(revision, batch, state)

    def positive_release() -> None:
        released = release_investigation_run(
            discovery_batch=verified_discovery.batch,
            verification_batch=batch,
            source_revision=revision,
            proposed_run=proposal,
            repository_root=PROJECT_ROOT,
        )
        if released.run_status != "success":
            raise AssertionError("trusted release did not return success")

    def direct_context_bypass() -> None:
        import src.services.investigation.release_adapter as release_adapter
        import src.services.investigation.run_contracts as run_contracts

        forbidden = (
            hasattr(release_adapter, "_trusted_context_from_t4"),
            hasattr(release_adapter, "_validation_context_from_replayed_t4"),
            hasattr(run_contracts, "_validate_investigation_run_with_context"),
            hasattr(run_contracts, "_take_release_authority_minter"),
        )
        if any(forbidden):
            raise AssertionError("legacy release authority surface remains importable")
        _expect_rejection(
            ValueError,
            "one-shot authority",
            lambda: InvestigationRun.model_validate(
                proposal,
                context={"investigation_release_authority": object()},
            ),
        )

    def fresh_process_import_order() -> None:
        code = """
import src.services.investigation.run_contracts as run_contracts

assert not hasattr(run_contracts, "_take_release_authority_minter")
try:
    from src.services.investigation.run_contracts import (
        _take_release_authority_minter,
    )
except ImportError:
    pass
else:
    raise AssertionError(_take_release_authority_minter)

import src.services.investigation.release_adapter as release_adapter

assert callable(release_adapter.release_investigation_run)
assert not hasattr(run_contracts, "_take_release_authority_minter")
"""
        completed = subprocess.run(
            [sys.executable, "-c", code],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0:
            details = completed.stderr.strip() or completed.stdout.strip()
            raise AssertionError(f"fresh-process import-order bypass: {details}")

    def replay_wrapper_rejection() -> None:
        replay_result = verify_verification_batch(
            batch,
            verified_discovery=verified_discovery,
            revision=revision,
        )
        _expect_rejection(
            TypeError,
            "raw T4 artifact",
            lambda: release_investigation_run(
                discovery_batch=verified_discovery.batch,
                verification_batch=replay_result,
                source_revision=revision,
                proposed_run=proposal,
                repository_root=PROJECT_ROOT,
            ),
        )

    def source_hash_rejection() -> None:
        forged = json.loads(json.dumps(proposal, ensure_ascii=False))
        hashes = forged["manifest"]["source_module_hashes"]
        digest = hashes["release_adapter.py"]
        hashes["release_adapter.py"] = ("0" if digest[0] != "0" else "1") + digest[1:]
        _expect_rejection(
            InvestigationReleaseError,
            "InvestigationRun source hashes",
            lambda: release_investigation_run(
                discovery_batch=verified_discovery.batch,
                verification_batch=batch,
                source_revision=revision,
                proposed_run=forged,
                repository_root=PROJECT_ROOT,
            ),
        )

    def git_revision_rejection() -> None:
        forged = json.loads(json.dumps(proposal, ensure_ascii=False))
        forged["manifest"]["git_revision"] = f"mismatch-{state.git_revision}"
        _expect_rejection(
            InvestigationReleaseError,
            "InvestigationRun Git revision mismatch",
            lambda: release_investigation_run(
                discovery_batch=verified_discovery.batch,
                verification_batch=batch,
                source_revision=revision,
                proposed_run=forged,
                repository_root=PROJECT_ROOT,
            ),
        )

    def repository_toctou_rejection() -> None:
        changed_state = replace(
            state,
            git_status_sha256=(
                ("0" if state.git_status_sha256[0] != "0" else "1")
                + state.git_status_sha256[1:]
            ),
        )
        with mock.patch(
            "src.services.investigation.release_adapter.capture_repository_state",
            side_effect=(state, changed_state),
        ):
            _expect_rejection(
                InvestigationReleaseError,
                "repository state changed",
                lambda: release_investigation_run(
                    discovery_batch=verified_discovery.batch,
                    verification_batch=batch,
                    source_revision=revision,
                    proposed_run=proposal,
                    repository_root=PROJECT_ROOT,
                ),
            )

    def attributed_assertion_rejection(source: str) -> None:
        case = {
            "id": "release-attribution-probe",
            "segments": [source],
            "candidates": [
                {
                    "segment_index": 0,
                    "candidate_kind": "claim",
                    "claim_type": "criminal.accusation",
                    "statement": "$segment",
                    "polarity": "affirmed",
                }
            ],
            "expected": {},
        }
        attributed_revision, attributed_discovery = _build_discovery(case)
        attributed_batch = _build_t4(attributed_discovery, attributed_revision)
        if attributed_batch.status != "needs_review":
            raise AssertionError("attributed assertion was not withheld")
        _expect_rejection(
            InvestigationReleaseError,
            "status=success",
            lambda: release_investigation_run(
                discovery_batch=attributed_discovery.batch,
                verification_batch=attributed_batch,
                source_revision=attributed_revision,
                proposed_run={"run_status": "success"},
                repository_root=PROJECT_ROOT,
            ),
        )

    probes = (
        ("in-process-structural-replay-positive", positive_release),
        ("plain-context-object-rejected", direct_context_bypass),
        ("fresh-process-import-order-rejected", fresh_process_import_order),
        ("replay-wrapper-rejected", replay_wrapper_rejection),
        ("release-source-hash-rejected", source_hash_rejection),
        ("release-git-revision-rejected", git_revision_rejection),
        ("repository-toctou-rejected", repository_toctou_rejection),
        (
            "reported-theo-loi-rejected",
            lambda: attributed_assertion_rejection(
                "Theo lời Lan, Minh đã nhận 15 triệu đồng."
            ),
        ),
        (
            "allegation-cao-buoc-rejected",
            lambda: attributed_assertion_rejection(
                "Lan cáo buộc Minh đã nhận tiền."
            ),
        ),
        (
            "reported-theo-person-rejected",
            lambda: attributed_assertion_rejection(
                "Theo Lan, Minh đã nhận tiền."
            ),
        ),
        (
            "reported-theo-source-rejected",
            lambda: attributed_assertion_rejection(
                "Theo nguồn tin, Minh đã nhận tiền."
            ),
        ),
        (
            "reported-duoc-cho-la-rejected",
            lambda: attributed_assertion_rejection(
                "Được cho là Minh đã nhận tiền."
            ),
        ),
        (
            "allegation-to-rejected",
            lambda: attributed_assertion_rejection(
                "Lan tố Minh đã nhận tiền."
            ),
        ),
    )
    with _network_denied() as network_guard:
        results = [_run_release_probe(probe_id, operation) for probe_id, operation in probes]
    if network_guard.attempts:
        results.append(
            {
                "id": "release-network-denied",
                "passed": False,
                "failure": f"network attempts: {network_guard.attempts!r}",
                "latency_ms": 0.0,
            }
        )
    return {
        "security_boundary": False,
        "probe_count": len(results),
        "probe_pass_count": sum(item["passed"] for item in results),
        "network_attempt_count": len(network_guard.attempts),
        "passed": all(item["passed"] for item in results),
        "probes": results,
    }


def _percentile(samples: Sequence[float], quantile: float) -> float:
    if not samples:
        raise ValueError("percentile requires at least one sample")
    ordered = sorted(samples)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _sample_summary(samples: Sequence[float]) -> dict[str, Any]:
    values = tuple(float(value) for value in samples)
    return {
        "samples": list(values),
        "sample_count": len(values),
        "min": min(values),
        "median": statistics.median(values),
        "p95": _percentile(values, 0.95),
        "max": max(values),
        "mean": statistics.fmean(values),
        "population_stddev": statistics.pstdev(values),
    }


def _timed_benchmark_iteration(
    verified_discovery: Any,
    revision: SourceRevision,
) -> tuple[VerificationBatch, VerificationBatch, dict[str, float]]:
    gc.collect()
    build_started = time.perf_counter_ns()
    batch = _build_t4(verified_discovery, revision)
    build_latency_ms = (time.perf_counter_ns() - build_started) / 1_000_000
    replay_started = time.perf_counter_ns()
    replayed = verify_verification_batch(
        batch,
        verified_discovery=verified_discovery,
        revision=revision,
    ).batch
    replay_latency_ms = (time.perf_counter_ns() - replay_started) / 1_000_000
    return batch, replayed, {
        "build_latency_ms": build_latency_ms,
        "replay_latency_ms": replay_latency_ms,
        "total_latency_ms": build_latency_ms + replay_latency_ms,
    }


def _peak_memory_sample_mib(
    verified_discovery: Any,
    revision: SourceRevision,
) -> float:
    gc.collect()
    tracemalloc.start()
    try:
        measured_batch = _build_t4(verified_discovery, revision)
        del measured_batch
        _, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return peak_bytes / (1024 * 1024)


def _benchmark_case(
    candidate_count: int,
    *,
    warmup_iterations: int = DEFAULT_BENCHMARK_WARMUPS,
    sample_count: int = DEFAULT_BENCHMARK_SAMPLES,
    memory_sample_count: int = DEFAULT_BENCHMARK_MEMORY_SAMPLES,
) -> dict[str, Any]:
    case = {
        "id": f"benchmark-{candidate_count}",
        "segments": ["Lan có mặt tại điểm hẹn lúc 10:00."],
        "candidates": [
            {
                "segment_index": 0,
                "candidate_kind": "claim",
                "claim_type": "event.presence",
                "statement": "$segment",
                "polarity": "affirmed",
                "attributes": {"benchmark_index": index},
            }
            for index in range(candidate_count)
        ],
        "expected": {},
    }
    revision, verified_discovery = _build_discovery(case)
    warmup_samples: list[dict[str, float]] = []
    measured_samples: list[dict[str, float]] = []
    deterministic_replay = True
    batch: VerificationBatch | None = None
    with _network_denied() as network_guard:
        for _ in range(warmup_iterations):
            warmup_batch, warmup_replayed, timings = _timed_benchmark_iteration(
                verified_discovery,
                revision,
            )
            warmup_samples.append(timings)
            deterministic_replay &= warmup_replayed.batch_id == warmup_batch.batch_id
        for _ in range(sample_count):
            batch, replayed, timings = _timed_benchmark_iteration(
                verified_discovery,
                revision,
            )
            measured_samples.append(timings)
            deterministic_replay &= replayed.batch_id == batch.batch_id
        peak_memory_samples_mib = [
            _peak_memory_sample_mib(verified_discovery, revision)
            for _ in range(memory_sample_count)
        ]

    assert batch is not None
    build_latency = _sample_summary(
        [sample["build_latency_ms"] for sample in measured_samples]
    )
    replay_latency = _sample_summary(
        [sample["replay_latency_ms"] for sample in measured_samples]
    )
    total_latency = _sample_summary(
        [sample["total_latency_ms"] for sample in measured_samples]
    )
    peak_memory = _sample_summary(peak_memory_samples_mib)
    passed = (
        len(batch.records) == candidate_count
        and deterministic_replay
        and not network_guard.attempts
        and total_latency["p95"] <= DEFAULT_LATENCY_BUDGET_MS
        and peak_memory["p95"] <= DEFAULT_PEAK_MEMORY_BUDGET_MIB
    )
    return {
        "candidate_count": candidate_count,
        "record_count": len(batch.records),
        "claim_count": len(batch.ledger.claims) if batch.ledger else 0,
        "merge_count": len(batch.merge_records),
        "methodology": {
            "warmup_iterations": warmup_iterations,
            "measured_iterations": sample_count,
            "memory_iterations": memory_sample_count,
            "gc_before_each_iteration": True,
            "clock": "time.perf_counter_ns",
            "percentile_method": "linear_interpolation_on_sorted_samples",
            "latency_gate_statistic": "total_latency_ms.p95",
            "memory_gate_statistic": "peak_memory_mib.p95",
            "memory_scope": "single_build_with_tracemalloc",
        },
        "warmup_latency_samples": warmup_samples,
        "build_latency_ms": build_latency["median"],
        "replay_latency_ms": replay_latency["median"],
        "latency_ms": total_latency["median"],
        "latency_p95_ms": total_latency["p95"],
        "latency_metrics_ms": {
            "build": build_latency,
            "replay": replay_latency,
            "total": total_latency,
        },
        "latency_budget_ms": DEFAULT_LATENCY_BUDGET_MS,
        "peak_memory_mib": peak_memory["median"],
        "peak_memory_p95_mib": peak_memory["p95"],
        "peak_memory_metrics_mib": peak_memory,
        "peak_memory_budget_mib": DEFAULT_PEAK_MEMORY_BUDGET_MIB,
        "peak_memory_scope": "single_build_with_tracemalloc",
        "network_attempt_count": len(network_guard.attempts),
        "deterministic_replay": deterministic_replay,
        "passed": passed,
    }


def _write_report(report: Mapping[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = str(report["finished_at"]).replace(":", "").replace("-", "")
    timestamp = timestamp.replace("+0000", "Z").replace("+00:00", "Z")
    timestamp = timestamp.replace(".", "")
    report_path = output_dir / f"t4-verification-{timestamp}.json"
    latest_path = output_dir / "latest.json"
    rendered = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    report_path.write_text(rendered, encoding="utf-8")
    latest_path.write_text(rendered, encoding="utf-8")
    return report_path, latest_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--benchmark-candidates",
        type=int,
        default=DEFAULT_BENCHMARK_CANDIDATES,
    )
    parser.add_argument(
        "--benchmark-warmups",
        type=int,
        default=DEFAULT_BENCHMARK_WARMUPS,
    )
    parser.add_argument(
        "--benchmark-samples",
        type=int,
        default=DEFAULT_BENCHMARK_SAMPLES,
    )
    parser.add_argument(
        "--benchmark-memory-samples",
        type=int,
        default=DEFAULT_BENCHMARK_MEMORY_SAMPLES,
    )
    parser.add_argument("--skip-benchmark", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    output_dir = args.output_dir.resolve()
    started_at = datetime.now(timezone.utc)
    manifest_sha256 = _sha256_file(manifest_path)
    cases = _load_cases(manifest_path)
    case_ids = tuple(str(case["id"]) for case in cases)
    case_results = [_evaluate_case(case) for case in cases]
    release_boundary = _evaluate_release_boundary()
    benchmark = None
    if not args.skip_benchmark:
        if args.benchmark_candidates <= 0:
            raise ValueError("--benchmark-candidates must be positive")
        if args.benchmark_warmups < 1:
            raise ValueError("--benchmark-warmups must be at least 1")
        if args.benchmark_samples < 3:
            raise ValueError("--benchmark-samples must be at least 3")
        if args.benchmark_memory_samples < 3:
            raise ValueError("--benchmark-memory-samples must be at least 3")
        benchmark = _benchmark_case(
            args.benchmark_candidates,
            warmup_iterations=args.benchmark_warmups,
            sample_count=args.benchmark_samples,
            memory_sample_count=args.benchmark_memory_samples,
        )
    benchmark_required = benchmark is not None
    benchmark_profile_locked = bool(
        benchmark
        and benchmark["candidate_count"] == DEFAULT_BENCHMARK_CANDIDATES
        and args.benchmark_candidates == DEFAULT_BENCHMARK_CANDIDATES
    )
    gates = {
        "manifest_sha256_matches_locked": manifest_sha256
        == LOCKED_MANIFEST_SHA256,
        "mandatory_case_ids_exact": case_ids == MANDATORY_CASE_IDS,
        "case_count": len(case_results),
        "case_pass_count": sum(item["passed"] for item in case_results),
        "all_fixture_cases_passed": all(item["passed"] for item in case_results),
        "all_replays_deterministic": all(
            item["deterministic_replay"] for item in case_results
        ),
        "release_probe_count": release_boundary["probe_count"],
        "release_probe_pass_count": release_boundary["probe_pass_count"],
        "in_process_structural_replay_passed": release_boundary["passed"],
        "network_attempt_count": sum(
            item["network_attempt_count"] for item in case_results
        )
        + release_boundary["network_attempt_count"]
        + (benchmark["network_attempt_count"] if benchmark else 0),
        "benchmark_required": benchmark_required,
        "benchmark_profile_locked": benchmark_profile_locked,
        "benchmark_passed": bool(benchmark and benchmark["passed"]),
        "external_release_process_implemented": False,
        "signed_receipt_persistence_gate_implemented": False,
    }
    gates["passed"] = (
        gates["manifest_sha256_matches_locked"]
        and gates["mandatory_case_ids_exact"]
        and gates["all_fixture_cases_passed"]
        and gates["all_replays_deterministic"]
        and gates["in_process_structural_replay_passed"]
        and gates["network_attempt_count"] == 0
        and gates["benchmark_required"]
        and gates["benchmark_profile_locked"]
        and gates["benchmark_passed"]
        and gates["external_release_process_implemented"]
        and gates["signed_receipt_persistence_gate_implemented"]
    )
    finished_at = datetime.now(timezone.utc)
    report = {
        "protocol_version": PROTOCOL_VERSION,
        "quality_claim": QUALITY_CLAIM,
        "release_readiness": "BLOCKED",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "locked_manifest_sha256": LOCKED_MANIFEST_SHA256,
        "manifest_case_ids": list(case_ids),
        "mandatory_case_ids": list(MANDATORY_CASE_IDS),
        "git": _git_info(),
        "environment": {
            "python": sys.version,
            "platform": platform.platform(),
        },
        "source_module_hashes": {
            "discovery": _discovery_source_hashes(),
            "verification": _source_hashes(VERIFICATION_REQUIRED_SOURCE_MODULES),
        },
        "cases": case_results,
        "in_process_structural_replay": release_boundary,
        "benchmark": benchmark,
        "gates": gates,
        "limitations": [
            "Synthetic structural fixtures are not a labelled quality corpus.",
            "No factual precision, recall, calibration, or legal-admissibility claim is made.",
            "A locked Vietnamese noisy-ASR corpus is still required before model promotion.",
            "Same-process Python callers can inspect closures and are inside the current trust boundary.",
            "Release remains blocked until an external authority signs receipts and persistence enforces them.",
        ],
    }
    report_path, latest_path = _write_report(report, output_dir)
    print(
        _canonical_json(
            {
                "passed": gates["passed"],
                "report": str(report_path),
                "latest": str(latest_path),
                "gates": gates,
                "in_process_structural_replay": release_boundary,
                "benchmark": benchmark,
            }
        )
    )
    return 0 if gates["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
