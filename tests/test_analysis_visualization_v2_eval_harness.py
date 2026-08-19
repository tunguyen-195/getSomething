from scripts import evaluate_analysis_visualization_v2 as harness


def _payload(**overrides):
    payload = {
        "schema_version": "investigation-analysis-simple-v2",
        "analysis_status": "success",
        "prompt_version": "investigation-analysis-direct-v14-source-bound-actor",
        "analysis_text": "Noi dung chinh cua cuoc trao doi.",
        "key_points": [],
        "runtime": {
            "generation": "single_prompt_llm",
            "llm_call_count": 1,
            "provider": "ollama",
            "model_id": "test-model",
            "seed": 42,
            "temperature": 0.0,
            "context_window_tokens": 8192,
            "completion_token_budget": 512,
            "full_transcript_included": True,
            "fits_context_window": True,
            "config_fingerprint": "a" * 64,
        },
    }
    payload.update(overrides)
    return payload


def test_success_payload_passes_contract_gates():
    gates = harness._evaluate_payload(_payload())

    assert all(item["result"] == "PASS" for item in gates)


def test_top_level_analysis_generation_is_supported():
    runtime = dict(_payload()["runtime"])
    runtime.pop("generation")
    payload = _payload(
        analysis_generation="single_prompt_llm",
        runtime=runtime,
    )

    gates = harness._evaluate_payload(payload)
    observed = {item["id"]: item["result"] for item in gates}
    assert observed["single_prompt_generation"] == "PASS"


def test_partial_plain_text_payload_passes_without_optional_sections():
    gates = harness._evaluate_payload(
        _payload(
            analysis_status="partial",
            analysis_text="Model returned useful text but invalid JSON.",
        )
    )

    assert all(item["result"] == "PASS" for item in gates)


def test_success_payload_requires_exactly_one_call():
    runtime = dict(_payload()["runtime"])
    runtime["llm_call_count"] = 2
    gates = harness._evaluate_payload(
        _payload(runtime=runtime)
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["llm_call_count"] == "FAIL"


def test_failed_payload_treats_call_count_as_diagnostic_only():
    for call_count in (None, 0, 1):
        runtime = {} if call_count is None else {"llm_call_count": call_count}
        gates = harness._evaluate_payload(
            _payload(
                analysis_status="failed",
                overview="",
                runtime=runtime,
            )
        )
        observed = {item["id"]: item["result"] for item in gates}
        assert observed["llm_call_count"] == "PASS"
        assert observed["useful_content_for_nonfailed"] == "PASS"


def test_success_payload_requires_runtime_provenance_and_full_source_budget():
    runtime = dict(_payload()["runtime"])
    runtime["config_fingerprint"] = None
    runtime["full_transcript_included"] = False

    gates = harness._evaluate_payload(_payload(runtime=runtime))

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["runtime_provenance_recorded"] == "FAIL"
    assert observed["full_transcript_budgeted_without_truncation"] == "FAIL"


def test_present_optional_collections_must_be_arrays():
    gates = harness._evaluate_payload(_payload(events={"description": "bad"}))

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["optional_collection_shapes"] == "FAIL"


def test_optional_placeholder_is_a_content_smoke_failure():
    gates = harness._evaluate_payload(
        _payload(events=[{"description": "Gap mat", "time": "Không xác định"}])
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_optional_placeholders"] == "FAIL"


def test_meaningful_question_with_mid_sentence_khong_ro_is_not_placeholder():
    gates = harness._evaluate_payload(
        _payload(
            follow_ups=[
                {"question": "Cử tri được hỗ trợ thế nào nếu không rõ cách bầu?"}
            ]
        )
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_optional_placeholders"] == "PASS"


def test_leading_khong_ro_still_counts_as_placeholder():
    gates = harness._evaluate_payload(
        _payload(uncertainties=["Không rõ thời gian cụ thể."])
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_optional_placeholders"] == "FAIL"


def test_factual_hedging_is_a_content_smoke_failure():
    gates = harness._evaluate_payload(
        _payload(key_points=[{"text": "Có thể hai người đang tranh cãi."}])
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_factual_hedging"] == "FAIL"


def test_verbatim_source_hedging_is_not_model_inference():
    source = "Có thể nói, các đơn vị đều cùng chung một mục tiêu."
    gates = harness._evaluate_payload(
        _payload(
            overview="",
            key_points=[{"text": source, "evidence_quote": source}],
        ),
        transcript=source,
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_factual_hedging"] == "PASS"


def test_paraphrased_hedging_still_fails_with_source_quote():
    source = "Hai người đang trao đổi lớn tiếng."
    gates = harness._evaluate_payload(
        _payload(
            overview="",
            key_points=[{
                "text": "Có thể hai người đang tranh cãi.",
                "evidence_quote": source,
            }],
        ),
        transcript=source,
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_factual_hedging"] == "FAIL"


def test_uncertainty_section_may_express_uncertainty():
    gates = harness._evaluate_payload(
        _payload(uncertainties=["Co the can them tai lieu de xac minh."])
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_factual_hedging"] == "PASS"


def test_overview_hedging_is_scrutinized():
    gates = harness._evaluate_payload(
        _payload(overview="Có vẻ hai người quen biết nhau.")
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["no_factual_hedging"] == "FAIL"


def test_evidence_quote_must_be_contiguous_source_text():
    gates = harness._evaluate_payload(
        _payload(
            key_points=[{
                "text": "Cử tri gạch tên và giữ bí mật lá phiếu.",
                "evidence_quote": "gạch tên... giữ bí mật lá phiếu",
            }]
        ),
        transcript="Cử tri gạch tên người không bầu rồi gấp phiếu. Giữ bí mật lá phiếu.",
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["evidence_quotes_are_contiguous_source"] == "FAIL"


def test_action_kind_and_status_are_controlled():
    gates = harness._evaluate_payload(
        _payload(actions=[{
            "description": "Đề nghị cử tri đi bầu sớm.",
            "kind": "commitment",
            "status": "completed",
            "evidence_quote": "Đề nghị cử tri đi bầu sớm.",
        }]),
        transcript="Đề nghị cử tri đi bầu sớm.",
    )

    observed = {item["id"]: item["result"] for item in gates}
    assert observed["action_kind_and_status_are_controlled"] == "FAIL"


def test_task_fingerprint_is_stable_for_key_order_only():
    left = {"id": "task", "result": {"segments": [1, 2], "text": "abc"}}
    right = {"result": {"text": "abc", "segments": [1, 2]}, "id": "task"}

    assert harness._task_fingerprint(left) == harness._task_fingerprint(right)
