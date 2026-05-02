import logging
import json
from typing import Dict, Any
from src.cherry_core.ports.llm_port import ILLMEngine
from src.cherry_core.config import MODELS_DIR

try:
    from llama_cpp import Llama, LlamaGrammar
except ImportError:
    Llama = None
    LlamaGrammar = None

logger = logging.getLogger(__name__)

class LlamaCppAdapter(ILLMEngine):
    """
    Adapter for LlamaCpp Engine.
    Implements the ILLMEngine interface using llama.cpp.
    """

    # Model registry for easy switching
    MODELS = {
        "vistral": ("vistral", "vistral-7b-chat-Q4_K_M.gguf"),
        "qwen3": ("qwen3", "Qwen_Qwen3-8B-Q4_K_M.gguf"),
    }

    def __init__(self, model_name: str = "vistral-7b-chat-Q4_K_M.gguf", model_type: str = "vistral"):
        # Check if using predefined model type
        if model_type in self.MODELS:
            folder, filename = self.MODELS[model_type]
            self.model_path = MODELS_DIR / folder / filename
        else:
            # Custom path fallback
            self.model_path = MODELS_DIR / "vistral" / model_name

        self.model_type = model_type
        self.llm = None
        self.context_window = 8192 if model_type == "vistral" else 32768  # Qwen3 has larger context

    def load(self) -> bool:
        if Llama is None:
            logger.error("llama_cpp library not installed.")
            return False

        if not self.model_path.exists():
            logger.error(f"Model not found at: {self.model_path}")
            return False

        try:
            logger.info(f"Loading LLM from {self.model_path} (type: {self.model_type})...")
            self.llm = Llama(
                model_path=str(self.model_path),
                n_gpu_layers=-1, # Offload all to GPU
                n_ctx=self.context_window,
                n_threads=6,     # Adjust based on CPU
                verbose=False
            )
            logger.info(f"✅ LLM ({self.model_type}) loaded successfully.")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to load LLM: {e}")
            return False

    def generate(self, prompt: str, max_tokens: int = 4096, grammar_path: str = None, temperature: float = 0.1) -> str:
        """
        Generate response from LLM.
        """
        if not self.llm:
            raise RuntimeError("LLM not loaded.")

        grammar = None
        if grammar_path:
            if LlamaGrammar is None:
                logger.warning("LlamaGrammar not available. Ignoring grammar constraint.")
            else:
                try:
                    logger.info(f"🔒 Applying GBNF Grammar from: {grammar_path}")
                    grammar = LlamaGrammar.from_file(grammar_path)
                except Exception as e:
                    logger.error(f"❌ Failed to load grammar: {e}")

        output = self.llm(
            prompt,
            max_tokens=max_tokens,
            temperature=temperature, # Configurable temp
            top_p=0.9,
            echo=False,
            stop=["</s>", "User:", "System:", "<|im_end|>"], # Stop tokens
            grammar=grammar
        )

        return output["choices"][0]["text"].strip()
