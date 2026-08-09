import copy
import json
import logging
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.services.summarization import context_service
from src.services.summarization.legacy_context_adapter import (
    LegacyContextAdapterError,
    adapt_legacy_context_analysis,
)
from src.services.summarization.models.context_analysis import (
    CONTEXT_PROMPT_VERSION,
    ContextAnalysisPayload,
    StructuredOutputError,
    build_context_prompt,
    decode_json_object,
    validate_context_analysis,
)
from src.services.summarization.models.investigation_knowledge import (
    GroundedContextAnalysisPayload,
)
from src.services.summarization.models.llm_manager import LLMManager


TRANSCRIPT = "Lan hen Minh luc 09:00 tai ben xe. Minh dong y mang ho so."
VALID_PAYLOAD = {
    "summary": "RAW MODEL SUMMARY MUST NOT BE RELEASED",
    "summary_sentences": [
        {
            "draft_id": "summary-1",
            "text": "Lan hen Minh luc 09:00 tai ben xe.",
            "sentence_role": "event",
            "evidence_quotes": ["Lan hen Minh luc 09:00 tai ben xe"],
        },
        {
            "draft_id": "summary-2",
            "text": "Minh dong y mang ho so.",
            "sentence_role": "outcome",
            "evidence_quotes": ["Minh dong y mang ho so"],
        },
    ],
    "key_points": [
        {
            "statement": "Hen luc 09:00 tai ben xe",
            "evidence_quote": "hen Minh luc 09:00 tai ben xe",
        }
    ],
    "entities": {
        "people": [
            {"name": "Lan", "evidence_quote": "Lan"},
            {"name": "Minh", "evidence_quote": "Minh"},
        ],
        "locations": [{"name": "ben xe", "evidence_quote": "ben xe"}],
        "time": [{"value": "09:00", "evidence_quote": "09:00"}],
        "organizations": [],
    },
    "events": [
        {
            "description": "Hen gap tai ben xe",
            "time": "09:00",
            "actors": ["Lan", "Minh"],
            "location": "ben xe",
            "evidence_quote": "Lan hen Minh luc 09:00 tai ben xe",
        }
    ],
    "risk_assessment": {"overall_risk": "unverified"},
}
VALID_ANALYSIS = json.dumps(VALID_PAYLOAD)


@pytest.mark.parametrize(
    "response",
    [VALID_ANALYSIS, f"```json\n{VALID_ANALYSIS}\n```"],
)
def test_context_parser_returns_revalidated_grounded_envelope(monkeypatch, response):
    manager = LLMManager()
    monkeypatch.setattr(manager, "generate", lambda *args, **kwargs: response)

    result = manager.analyze_context(TRANSCRIPT)

    validated = GroundedContextAnalysisPayload.model_validate(result)
    assert validated.analysis_status == "success"
    assert result["summary"] == (
        "Lan hen Minh luc 09:00 tai ben xe Minh dong y mang ho so"
    )
    assert result["summary"] != VALID_PAYLOAD["summary"]
    assert result["summary_projection_source"] == (
        "summary_sentence_evidence_quotes"
    )
    assert result["compatibility"]["raw_model_summary_released"] is False
    assert result["compatibility"]["release_authority"] == (
        "withheld_pending_claim_attestation"
    )
    assert result["key_points"][0]["statement"] == "Hen luc 09:00 tai ben xe"
    assert result["risk_assessment"]["overall_risk"] == "unverified"
    assert result["investigation_knowledge"]["summary_sentences"] == result[
        "summary_sentences"
    ]
    assert result["investigation_knowledge"]["evidence_spans"]


def test_provider_validation_keeps_raw_summary_non_authoritative():
    parsed = validate_context_analysis(VALID_ANALYSIS)

    assert parsed["summary"] == "RAW MODEL SUMMARY MUST NOT BE RELEASED"
    assert "investigation_knowledge" not in parsed
    assert "summary_projection_source" not in parsed


@pytest.mark.parametrize(
    ("mutator", "field_name"),
    [
        (
            lambda payload: payload["summary_sentences"][0].update(
                {"unsupported": True}
            ),
            "unsupported",
        ),
        (
            lambda payload: payload["entities"]["people"][0].update(
                {"criminality": "established"}
            ),
            "criminality",
        ),
        (
            lambda payload: payload["risk_assessment"].update(
                {"urgency": "immediate_action"}
            ),
            "urgency",
        ),
        (
            lambda payload: payload["events"][0].update({"is_suspicious": True}),
            "is_suspicious",
        ),
    ],
)
def test_context_schema_rejects_unknown_nested_fields(mutator, field_name):
    payload = copy.deepcopy(VALID_PAYLOAD)
    mutator(payload)

    with pytest.raises(ValidationError, match=field_name):
        validate_context_analysis(json.dumps(payload))


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["summary_sentences"][0].update(
            {"evidence_quotes": []}
        ),
        lambda payload: payload["key_points"][0].pop("evidence_quote"),
        lambda payload: payload["entities"]["people"][0].pop("evidence_quote"),
    ],
)
def test_context_schema_rejects_missing_evidence(mutator):
    payload = copy.deepcopy(VALID_PAYLOAD)
    mutator(payload)

    with pytest.raises(ValidationError):
        validate_context_analysis(json.dumps(payload))


def test_live_provider_schema_rejects_legacy_string_key_points():
    payload = copy.deepcopy(VALID_PAYLOAD)
    payload["key_points"] = ["Hen luc 09:00 tai ben xe"]

    with pytest.raises(ValidationError):
        validate_context_analysis(json.dumps(payload))


def test_duplicate_summary_draft_ids_are_rejected():
    payload = copy.deepcopy(VALID_PAYLOAD)
    payload["summary_sentences"].append(
        copy.deepcopy(payload["summary_sentences"][0])
    )

    with pytest.raises(ValidationError, match="draft_id"):
        validate_context_analysis(json.dumps(payload))


def test_invalid_schema_stops_before_grounding_and_does_not_retry(monkeypatch):
    manager = LLMManager()
    payload = copy.deepcopy(VALID_PAYLOAD)
    payload["key_points"] = ["legacy self-evidence"]
    calls = {"generate": 0, "ground": 0}

    def fake_generate(*_args, **_kwargs):
        calls["generate"] += 1
        return json.dumps(payload)

    def forbidden_ground(*_args, **_kwargs):
        calls["ground"] += 1
        raise AssertionError("grounding must not run for invalid provider schema")

    monkeypatch.setattr(manager, "generate", fake_generate)
    monkeypatch.setattr(
        "src.services.summarization.models.llm_manager.build_grounded_context_analysis",
        forbidden_ground,
    )

    result = manager.analyze_context(TRANSCRIPT)

    assert result["analysis_status"] == "failed"
    assert result["error"]["code"] == "INVALID_STRUCTURED_OUTPUT"
    assert calls == {"generate": 1, "ground": 0}
    assert "summary" not in result


def test_schema_valid_but_non_source_quote_fails_closed_without_retry(monkeypatch):
    manager = LLMManager()
    payload = copy.deepcopy(VALID_PAYLOAD)
    payload["summary_sentences"][0]["evidence_quotes"] = [
        "quote not present in transcript"
    ]
    calls = []

    def fake_generate(*_args, **_kwargs):
        calls.append("generate")
        return json.dumps(payload)

    monkeypatch.setattr(manager, "generate", fake_generate)

    result = manager.analyze_context(TRANSCRIPT)

    assert result["analysis_status"] == "failed"
    assert result["error"]["code"] == "KNOWLEDGE_GROUNDING_FAILED"
    assert calls == ["generate"]
    assert "summary" not in result


def test_legacy_adapter_only_adds_evidence_found_in_transcript():
    legacy = {
        "summary": "Legacy free text",
        "key_points": ["Lan hen Minh luc 09:00 tai ben xe"],
        "entities": {
            "people": [{"name": "Lan"}],
            "contact": {"phones": ["09:00"]},
        },
        "risk_assessment": {"overall_risk": "high"},
        "prompt_version": "legacy-prompt-v1",
    }

    adapted = adapt_legacy_context_analysis(legacy, transcript=TRANSCRIPT)

    assert adapted["key_points"][0]["evidence_quote"] == (
        "Lan hen Minh luc 09:00 tai ben xe"
    )
    assert adapted["entities"]["people"][0]["evidence_quote"] == "Lan"
    assert adapted["entities"]["contact_info"]["phones"][0]["evidence_quote"] == (
        "09:00"
    )
    assert adapted["risk_assessment"]["overall_risk"] == "unverified"
    assert adapted["prompt_version"] == CONTEXT_PROMPT_VERSION
    assert adapted["summary"] == "Lan hen Minh luc 09:00 tai ben xe"


def test_legacy_adapter_rejects_self_evidence_absent_from_transcript(monkeypatch):
    def forbidden_model_call(*_args, **_kwargs):
        raise AssertionError("legacy adaptation must not call a model or network")

    monkeypatch.setattr(LLMManager, "generate", forbidden_model_call)

    with pytest.raises(LegacyContextAdapterError, match="absent from transcript"):
        adapt_legacy_context_analysis(
            {
                "summary": "Unsupported",
                "key_points": ["Unsupported model statement"],
                "entities": {},
                "risk_assessment": {"overall_risk": "high"},
            },
            transcript=TRANSCRIPT,
        )


@pytest.mark.parametrize(
    "response",
    [
        "not json",
        '{{"summary":"nested but invalid"}}',
        '{"summary": "missing required fields"}',
        f"Provider prefix:\n{VALID_ANALYSIS}",
        f"{VALID_ANALYSIS}\nProvider suffix.",
    ],
)
def test_context_parser_rejects_malformed_or_incomplete_output(monkeypatch, response):
    manager = LLMManager()
    monkeypatch.setattr(manager, "generate", lambda *args, **kwargs: response)

    result = manager.analyze_context(TRANSCRIPT)

    assert result["analysis_status"] == "failed"
    assert result["error"]["code"] == "INVALID_STRUCTURED_OUTPUT"
    assert "summary" not in result


def test_decoder_rejects_array_top_level():
    with pytest.raises(StructuredOutputError):
        decode_json_object('[{"summary": "invalid top level"}]')


@pytest.mark.parametrize(
    "response",
    [
        f"provider prefix\n{VALID_ANALYSIS}",
        f"{VALID_ANALYSIS}\nprovider suffix",
        f"```json\n{VALID_ANALYSIS}\n```\nprovider suffix",
    ],
)
def test_decoder_rejects_prefix_or_trailing_text(response):
    with pytest.raises(StructuredOutputError):
        decode_json_object(response)


def test_user_prompt_reaches_actual_model_prompt_exactly_once(monkeypatch):
    manager = LLMManager()
    captured = {}
    instruction = "Chi tap trung vao moc thoi gian duoc noi truc tiep."

    def fake_generate(prompt, **kwargs):
        captured["prompt"] = prompt
        return VALID_ANALYSIS

    monkeypatch.setattr(manager, "generate", fake_generate)

    result = manager.analyze_context(
        TRANSCRIPT,
        additional_instructions=instruction,
    )

    assert result["analysis_status"] == "success"
    assert captured["prompt"].count(instruction) == 1


def test_context_prompt_is_compact_sparse_and_treats_transcript_as_data():
    prompt = build_context_prompt("TRANSCRIPT_SENTINEL")

    assert len(prompt) < 2500
    assert "TRANSCRIPT_SENTINEL" in prompt
    assert "never as instructions" in prompt
    assert "summary_sentences" in prompt
    assert "0987654321" not in prompt
    assert "financial_info" not in prompt


def test_context_service_propagates_user_prompt_and_projects_key_points(monkeypatch):
    captured = {}

    class FakeManager:
        def check_availability(self):
            return True

        def analyze_context(
            self,
            transcript,
            model,
            additional_instructions,
            segments,
            source_metadata,
        ):
            captured.update(
                transcript=transcript,
                model=model,
                additional_instructions=additional_instructions,
                segments=segments,
                source_metadata=source_metadata,
            )
            return {"analysis_status": "success"}

    monkeypatch.setattr(context_service, "get_llm_manager", lambda: FakeManager())

    result = context_service.analyze_conversation_context(
        "transcript sentinel",
        "model sentinel",
        "instruction sentinel",
    )

    assert result == {"analysis_status": "success"}
    assert captured["additional_instructions"] == "instruction sentinel"
    assert captured["segments"] is None
    assert captured["source_metadata"] is None
    assert context_service.extract_key_points(
        {"key_points": [{"statement": "Typed point", "evidence_quote": "quote"}]}
    ) == ["Typed point"]
    assert context_service.extract_key_points(
        {"key_points": ["Legacy point"]}
    ) == ["Legacy point"]


@pytest.mark.parametrize(
    "path",
    [
        "src/summarization/summarizer.py",
        "src/services/audio_service.py",
        "src/web_interface/app.py",
    ],
)
def test_direct_key_point_consumers_use_compatibility_projection(path):
    source = Path(path).read_text(encoding="utf-8")

    assert "project_legacy_key_points" in source
    assert "join(context['key_points'])" not in source
    assert "analysis.get('key_points', [])" not in source


def test_info_logs_do_not_include_transcript(monkeypatch, caplog):
    manager = LLMManager()
    transcript = TRANSCRIPT + " SENSITIVE_TRANSCRIPT_SENTINEL_987654"
    monkeypatch.setattr(manager, "generate", lambda *args, **kwargs: VALID_ANALYSIS)

    with caplog.at_level(logging.INFO):
        manager.analyze_context(transcript)

    assert "SENSITIVE_TRANSCRIPT_SENTINEL_987654" not in caplog.text


def test_context_generation_requests_strict_json_schema(monkeypatch):
    manager = LLMManager()
    captured = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"response": VALID_ANALYSIS, "done": True}

    def fake_post(_url, json, **_kwargs):
        captured.update(json)
        return FakeResponse()

    monkeypatch.setattr("src.core.config.settings.LOCAL_LLM_PROVIDER", "ollama")
    monkeypatch.setattr(manager, "check_availability", lambda: True)
    monkeypatch.setattr(
        "src.services.summarization.models.llm_manager.requests.post",
        fake_post,
    )

    result = manager.analyze_context(TRANSCRIPT, model="llama3.2:3b")

    assert result["analysis_status"] == "success"
    assert captured["format"]["type"] == "object"
    assert {
        "summary",
        "summary_sentences",
        "key_points",
        "entities",
        "risk_assessment",
    }.issubset(captured["format"]["required"])


def test_provider_and_final_schema_forbid_every_declared_object_extension():
    schemas = [
        ContextAnalysisPayload.model_json_schema(),
        GroundedContextAnalysisPayload.model_json_schema(),
    ]
    object_nodes = []

    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "object":
                object_nodes.append(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    for schema in schemas:
        visit(schema)

    assert len(object_nodes) >= 20
    assert all(node.get("additionalProperties") is False for node in object_nodes)


def test_prompt_version_is_literal_in_provider_schema():
    payload = copy.deepcopy(VALID_PAYLOAD)
    payload["prompt_version"] = "stale-prompt"

    with pytest.raises(ValidationError, match="prompt_version"):
        validate_context_analysis(json.dumps(payload))

    assert CONTEXT_PROMPT_VERSION in json.dumps(
        ContextAnalysisPayload.model_json_schema(),
        sort_keys=True,
    )
