import logging
import json
import os
from typing import List

from src.cherry_core.adapters.llm.llamacpp_adapter import LlamaCppAdapter
from src.cherry_core.config import PROMPTS_DIR
from src.cherry_core.domain.entities import SpeakerSegment


class RefinementConfig:
    """Optional speaker-role refinement settings for this adapter."""

    ENABLED = os.getenv("CHERRY_CONTEXTUAL_REFINEMENT_ENABLED", "false").casefold() in {
        "1",
        "true",
        "yes",
        "on",
    }
    MODEL_TEMP = float(os.getenv("CHERRY_CONTEXTUAL_REFINEMENT_TEMPERATURE", "0.1"))
    PROMPT_TEMPLATE = os.getenv(
        "CHERRY_CONTEXTUAL_REFINEMENT_PROMPT",
        "role_inference.j2",
    )

logger = logging.getLogger(__name__)

class ContextualSpeakerRefiner:
    """
    Refines speaker labels using LLM-based contextual analysis.
    Infer roles (e.g., "Receptionist", "Customer") from the conversation content.
    """
    
    def __init__(self, llm_adapter: LlamaCppAdapter):
        self.llm = llm_adapter
        
    def refine(self, segments: List[SpeakerSegment]) -> List[SpeakerSegment]:
        if not RefinementConfig.ENABLED:
            logger.info("⏩ Contextual refinement disabled in config.")
            return segments
            
        logger.info("🧠 Running Contextual Speaker Refinement...")
        
        # 1. Prepare Transcript for Context
        # Limit to first N chars to fit context window/speed
        transcript_text = ""
        for seg in segments[:50]: # Analyze first 50 turns for role definition
            transcript_text += f"[{seg.speaker_id}]: {seg.text}\n"
            
        # 2. Load Prompt Template (Modular & Robust)
        # Use simple file read to avoid dependency on PromptManager for this core component
        # But ensure path construction is safe
        try:
             prompt_path = PROMPTS_DIR / "modules" / RefinementConfig.PROMPT_TEMPLATE
             
             if not prompt_path.exists():
                 logger.error(f"❌ Prompt template not found: {prompt_path}")
                 return segments
                 
             with open(prompt_path, "r", encoding="utf-8") as f:
                 template = f.read()
                 
        except Exception as e:
            logger.error(f"❌ Failed to load prompt template: {e}")
            return segments

        prompt = template.replace("{{ transcript_text }}", transcript_text)
        logger.info(f"📝 Refiner Prompt Transcript Preview:\n{transcript_text[:500]}...")
        
        # 3. Call LLM
        try:
            logger.info(f"📤 Sending to LLM (Context: {len(transcript_text)} chars)...")
            response = self.llm.generate(
                prompt=prompt, 
                temperature=RefinementConfig.MODEL_TEMP,
                max_tokens=200
            )
            
            # 4. Parse JSON (Robustness Upgrade)
            json_str = response.strip()
            # Handle markdown code blocks often returned by LLMs
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0].strip()
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0].strip()
            
            # Additional cleanup for potential noise
            if not json_str.startswith("{") and "{" in json_str:
                 json_str = json_str[json_str.find("{"):]
            if not json_str.endswith("}") and "}" in json_str:
                 json_str = json_str[:json_str.rfind("}")+1]
                
            role_map = json.loads(json_str)
            logger.info(f"🕵️ Inferred Roles: {role_map}")
            
            # 5. Apply Refinement
            refined_segments = []
            for seg in segments:
                # Update speaker_id if in map
                new_id = role_map.get(seg.speaker_id, seg.speaker_id)
                # Keep ID format clean? Or just use Role?
                # User preference: "Receptionist" vs "SPEAKER_1 (Receptionist)"
                # Let's append role for clarity: "SPEAKER_1 (Receptionist)" or just replace if unique.
                # If distinct roles, replacing is better for reading.
                
                # Check if new_id is different
                if new_id != seg.speaker_id:
                     # Sanitize
                     new_id = new_id.replace(" ", "_").upper()
                
                refined_segments.append(SpeakerSegment(
                    start_time=seg.start_time,
                    end_time=seg.end_time,
                    speaker_id=new_id,
                    text=seg.text,
                    words=seg.words
                ))
            
            return refined_segments
            
        except Exception as e:
            logger.error(f"❌ Refinement failed: {e}")
            return segments
