import logging
import json
from pathlib import Path
from src.cherry_core.services.prompt_manager import PromptManager
from src.cherry_core.adapters.llm.llamacpp_adapter import LlamaCppAdapter
from src.cherry_core.config import PROMPTS_DIR

logger = logging.getLogger(__name__)

class AnalysisService:
    """
    Forensic Summarization Service.
    Bridge between Transcripts and Strategic Intelligence.
    Standardized Application Service.
    """
    def __init__(self):
        self.engine = LlamaCppAdapter()
        self.prompt_manager = PromptManager()
        self._is_loaded = False

    def load_model(self):
        if not self._is_loaded:
            if self.engine.load():
                self._is_loaded = True
            else:
                raise RuntimeError("Could not load LLM Engine.")

    def analyze_transcript(self, transcript: str, scenario: str = "general_intelligence") -> dict:
        """
        Perform forensic analysis on a transcript.
        Returns plain text report (Báo cáo Trinh sát).
        """
        self.load_model()

        # 1. Render Prompt (Forensic Report - improved prompt)
        template_name = "forensic_report.j2"

        prompt = self.prompt_manager.render_prompt(
            template_name=template_name,
            transcript=transcript,
            scenario=scenario
        )

        logger.info(f"[CHERRY_CORE] Generating Forensic Report (Scenario: {scenario})...")

        # 2. Inference with higher max_tokens for detailed report
        raw_response = self.engine.generate(prompt, max_tokens=4096, temperature=0.1)

        # 3. Clean up response - remove markdown artifacts
        cleaned_response = self._clean_markdown(raw_response)

        logger.info(f"[CHERRY_CORE] Forensic Report generated successfully.")

        return {
            "summary": cleaned_response,
            "scenario": scenario,
            "model": self.engine.model_type,
            "format": "forensic_report"
        }

    def _clean_markdown(self, text: str) -> str:
        """Remove markdown artifacts from LLM output."""
        if not text:
            return ""
        return (text
            .replace("###", "")
            .replace("**", "")
            .replace("__", "")
            .replace("```", "")
            .strip())
