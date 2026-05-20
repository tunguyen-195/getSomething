"""Smoke-test the configured server-side LLM provider.

This script is intentionally small and does not print API keys, transcripts, or
raw provider error bodies. It is meant for new-machine setup after adding
ANALYSIS_LLM_API_KEY to .env.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.config import settings  # noqa: E402
from src.services.summarization.models.llm_manager import (  # noqa: E402
    get_llm_manager,
    llm_provider_configured,
)


def main() -> int:
    provider = settings.ANALYSIS_LLM_PROVIDER
    model = settings.ANALYSIS_LLM_MODEL
    print("SpeechToInformation LLM provider smoke")
    print(f"provider={provider}")
    print(f"model={model}")

    if not llm_provider_configured():
        print("FAIL: llm_not_configured")
        print("Set ANALYSIS_LLM_API_KEY in .env, then rebuild/restart the backend container.")
        return 1

    prompt = (
        "Tóm tắt bằng một câu tiếng Việt: "
        "Khách hàng hẹn thanh toán hợp đồng vào ngày mai và cần xác nhận địa chỉ giao hàng."
    )
    try:
        response = get_llm_manager().generate(
            prompt,
            model=model,
            temperature=0.2,
            max_tokens=128,
        )
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    text = " ".join((response or "").strip().split())
    if len(text) < 10:
        print("FAIL: empty_or_too_short_response")
        return 1
    print("OK: provider returned a response")
    print(f"response_preview={text[:240]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
