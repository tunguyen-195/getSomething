import json
from types import SimpleNamespace

import pytest

from scripts import benchmark_vietnamese_asr as benchmark
from src.services.transcription.models import whisper_manager
from scripts.benchmark_vietnamese_asr import (
    decode_parameters,
    edit_distance,
    entity_recall,
    error_rate,
    interval_union_seconds,
    normalize_text,
    normalize_benchmark_runtime,
    profile_execution_semantics,
    reference_metrics,
    resolve_snapshot,
    transcript_metrics,
)


def _write_snapshot(tmp_path, revision=None):
    revision = revision or benchmark.MODEL_SPECS["large-v2"]["revision"]
    model_root = tmp_path / "models--Systran--faster-whisper-large-v2"
    snapshot = model_root / "snapshots" / revision
    snapshot.mkdir(parents=True)
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (snapshot / filename).write_bytes(b"model-data")
    ref_path = model_root / "refs" / "main"
    ref_path.parent.mkdir(parents=True)
    ref_path.write_text(revision + "\n", encoding="utf-8")
    return snapshot


def test_investigation_profiles_do_not_use_temperature_sampling():
    accuracy = decode_parameters("investigation-accuracy-v1")
    rescue = decode_parameters("leading-gap-rescue-v1")

    assert accuracy["temperature"] == 0.0
    assert rescue["temperature"] == 0.0
    assert rescue["vad_filter"] is False
    assert rescue["no_speech_threshold"] == 0.5


def test_normalization_and_error_metrics_handle_vietnamese_text():
    assert normalize_text("Nguyen Van A, 12.000 dong!") == "nguyen van a 12 000 dong"
    assert edit_distance(["a", "b"], ["a", "c"]) == 1
    assert error_rate(["a", "b"], ["a", "c"]) == 0.5
    assert reference_metrics("mot hai ba", "mot hai")["wer"] == 1 / 3


def test_interval_union_does_not_double_count_overlapping_segments():
    assert interval_union_seconds([(0.0, 2.0), (1.0, 3.0), (5.0, 6.5)]) == 4.5


def test_entity_recall_reports_ids_without_echoing_sensitive_values():
    result = entity_recall(
        {
            "entities": [
                {"id": "person-1", "type": "person", "value": "Nguyen Van A"},
                {"id": "amount-1", "type": "amount", "value": "12 trieu"},
            ]
        },
        "Nguyen Van A da xuat hien.",
    )

    assert result["recall"] == 0.5
    assert result["missed_entity_ids"] == ["amount-1"]
    assert "Nguyen Van A" not in str(result)


def test_transcript_metrics_export_hash_and_aggregates_not_text():
    result = transcript_metrics(
        "Noi dung nhay cam",
        [
            {
                "start": 0.0,
                "end": 1.5,
                "avg_logprob": -0.2,
                "no_speech_prob": 0.1,
            }
        ],
        3.0,
    )

    assert result["normalized_words"] == 4
    assert result["timeline_coverage_ratio"] == 0.5
    assert "Noi dung" not in str(result)


def test_snapshot_resolution_uses_exact_refs_main_revision(tmp_path):
    pinned_revision = benchmark.MODEL_SPECS["large-v2"]["revision"]
    selected = _write_snapshot(tmp_path, pinned_revision)
    unselected = selected.parent / "other-revision"
    unselected.mkdir()
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (unselected / filename).write_bytes(b"other-model-data")

    _spec, snapshot, revision = resolve_snapshot("large-v2", tmp_path)

    assert snapshot == selected.resolve()
    assert revision == pinned_revision


def test_snapshot_resolution_fails_closed_without_refs_main(tmp_path):
    model_root = tmp_path / "models--Systran--faster-whisper-large-v2"
    for revision in ("revision-a", "revision-b"):
        snapshot = model_root / "snapshots" / revision
        snapshot.mkdir(parents=True)
        for filename in ("config.json", "model.bin", "tokenizer.json"):
            (snapshot / filename).write_bytes(b"model-data")

    with pytest.raises(benchmark.SnapshotResolutionError, match="Missing exact refs/main"):
        resolve_snapshot("large-v2", tmp_path)


def test_snapshot_resolution_rejects_valid_unpromoted_revision(tmp_path):
    selected = _write_snapshot(tmp_path)
    unpromoted_revision = "1" * 40
    unpromoted = selected.parent / unpromoted_revision
    unpromoted.mkdir()
    for filename in ("config.json", "model.bin", "tokenizer.json"):
        (unpromoted / filename).write_bytes(b"unpromoted-model-data")
    ref_path = selected.parents[1] / "refs" / "main"
    ref_path.write_text(unpromoted_revision + "\n", encoding="utf-8")

    with pytest.raises(
        benchmark.SnapshotResolutionError,
        match="does not match the pinned immutable revision",
    ):
        resolve_snapshot("large-v2", tmp_path)


def test_benchmark_model_specs_are_loaded_from_manager_pin_source():
    for alias, spec in benchmark.MODEL_SPECS.items():
        manager_spec = whisper_manager.WHISPER_MODEL_SPECS[alias]
        assert spec["model_id"] == manager_spec["provider_id"]
        assert spec["cache_dir"] == manager_spec["cache_name"]
        assert spec["revision"] == manager_spec["revision"]


def test_cpu_float16_is_normalized_to_supported_int8():
    assert normalize_benchmark_runtime("cpu", "float16") == (
        "cpu",
        "int8",
        "cpu_float16_unsupported_normalized_to_int8",
    )


def test_ungated_rescue_requires_explicit_diagnostic_authorization():
    with pytest.raises(ValueError, match="--ungated-rescue-diagnostic"):
        profile_execution_semantics(
            "leading-gap-rescue-v1",
            ungated_rescue_diagnostic=False,
        )

    semantics = profile_execution_semantics(
        "leading-gap-rescue-v1",
        ungated_rescue_diagnostic=True,
    )
    assert semantics["result_role"] == (
        "diagnostic_ungated_rescue_candidate_generation"
    )
    assert semantics["production_rescue_gate_applied"] is False
    assert semantics["production_rescue_eligible"] is False


def test_cli_rejects_ungated_rescue_with_clear_portable_command_hint(
    monkeypatch,
    capsys,
):
    monkeypatch.setattr(
        benchmark.sys,
        "argv",
        [
            "benchmark_vietnamese_asr.py",
            "--audio",
            "audio.wav",
            "--models",
            "large-v2",
            "--profile",
            "leading-gap-rescue-v1",
        ],
    )

    with pytest.raises(SystemExit) as exc_info:
        benchmark.parse_args()

    assert exc_info.value.code == 2
    assert "--ungated-rescue-diagnostic" in capsys.readouterr().err


def test_default_report_omits_sensitive_paths_and_nests_opt_in_transcript(
    monkeypatch,
    tmp_path,
):
    _write_snapshot(tmp_path)
    audio_path = tmp_path / "sensitive-case-name.wav"
    audio_path.write_bytes(b"synthetic-audio")
    report_path = tmp_path / "report.json"

    class FakeModel:
        def __init__(self, _model_path, **kwargs):
            assert kwargs["device"] == "cpu"
            assert kwargs["compute_type"] == "int8"

        def transcribe(self, _audio_path, **_parameters):
            segment = SimpleNamespace(
                start=0.0,
                end=1.0,
                text="Noi dung nhay cam",
                avg_logprob=-0.1,
                no_speech_prob=0.05,
            )
            info = SimpleNamespace(
                duration=1.0,
                language="vi",
                language_probability=0.99,
            )
            return [segment], info

    monkeypatch.setattr(benchmark, "WhisperModel", FakeModel)
    monkeypatch.setattr(
        benchmark,
        "parse_args",
        lambda: SimpleNamespace(
            audio=audio_path,
            models=["large-v2"],
            profile="investigation-accuracy-v1",
            cache_root=tmp_path,
            device="cpu",
            compute_type="float16",
            reference=None,
            entities=None,
            output=report_path,
            skip_model_hash=True,
            include_transcript=False,
            include_artifact_path=False,
            ungated_rescue_diagnostic=False,
            clip_timestamps=None,
        ),
    )

    assert benchmark.main() == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    serialized = json.dumps(report, ensure_ascii=False)

    assert "name" not in report["audio"]
    assert "artifact_path" not in report["results"][0]
    assert "transcript" not in report["results"][0]
    assert "transcript" not in report["results"][0]["output"]
    assert "sensitive-case-name.wav" not in serialized
    assert str(tmp_path.resolve()) not in serialized
    assert report["runtime"]["compute_type"] == "int8"
    assert report["runtime"]["requested_compute_type"] == "float16"
    assert report["results"][0]["expected_revision"] == (
        benchmark.MODEL_SPECS["large-v2"]["revision"]
    )
    assert report["results"][0]["revision_matches_pin"] is True
    assert report["results"][0]["revision_policy"] == "pinned_immutable"

    semantics = profile_execution_semantics(
        "investigation-accuracy-v1",
        ungated_rescue_diagnostic=False,
    )
    result, _transcript = benchmark.run_model(
        alias="large-v2",
        audio_path=audio_path,
        cache_root=tmp_path,
        profile="investigation-accuracy-v1",
        device="cpu",
        compute_type="float16",
        hash_model=False,
        reference=None,
        entities=None,
        include_transcript=True,
        include_artifact_path=False,
        clip_timestamps=None,
        execution_semantics=semantics,
    )
    assert result["output"]["transcript"] == "Noi dung nhay cam"
    assert "transcript" not in {key for key in result if key != "output"}
