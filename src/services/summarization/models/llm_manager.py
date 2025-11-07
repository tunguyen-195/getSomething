"""
LLM Manager - Singleton Pattern for Ollama
Lazy loading, optional usage (không gọi mặc định)
"""
import logging
import requests
import json
from typing import Optional, Dict, List
from src.core.config import settings

logger = logging.getLogger(__name__)


class LLMManager:
    """
    Singleton manager for Ollama LLM
    Only loads when explicitly requested
    """
    _instance: Optional['LLMManager'] = None
    _initialized: bool = False
    _available_models: List[str] = []
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._initialized:
            self._api_url = "http://localhost:11434/api/generate"
            self._default_model = settings.DEFAULT_AI_MODEL if hasattr(settings, 'DEFAULT_AI_MODEL') else "gemma2:9b"
            self._initialized = True
            logger.info(f"[LLM_MANAGER] Initialized (lazy mode)")
    
    def check_availability(self) -> bool:
        """Check if Ollama is running and available"""
        try:
            response = requests.get("http://localhost:11434/api/tags", timeout=2)
            if response.status_code == 200:
                data = response.json()
                self._available_models = [m['name'] for m in data.get('models', [])]
                logger.info(f"[LLM_MANAGER] Available models: {self._available_models}")
                return True
        except Exception as e:
            logger.warning(f"[LLM_MANAGER] Ollama not available: {e}")
        return False
    
    def get_available_models(self) -> List[str]:
        """Get list of available models"""
        if not self._available_models:
            self.check_availability()
        return self._available_models
    
    def select_best_model(self, preferred: str = None) -> str:
        """
        Select best available model
        Priority: preferred > gemma2:9b > deepseek-r1:7b > first available
        """
        models = self.get_available_models()
        
        if not models:
            logger.warning("[LLM_MANAGER] No models available, using default")
            return self._default_model
        
        if preferred and preferred in models:
            return preferred
        
        priority = ["gemma2:9b", "deepseek-r1:7b", "mistral:7b-instruct", "llama3.2:3b"]
        for model in priority:
            if model in models:
                logger.info(f"[LLM_MANAGER] Selected model: {model}")
                return model
        
        # Return first available
        selected = models[0]
        logger.info(f"[LLM_MANAGER] Using first available: {selected}")
        return selected
    
    def generate(
        self,
        prompt: str,
        model: str = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stream: bool = False
    ) -> str:
        """
        Generate response from LLM
        
        Args:
            prompt: Input prompt
            model: Model name (None = auto-select best)
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Stream response
        
        Returns:
            Generated text
        """
        if not self.check_availability():
            raise Exception("Ollama is not available")
        
        if model is None:
            model = self.select_best_model()
        
        logger.info(f"[LLM_MANAGER] Generating with model: {model}")
        
        try:
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": stream,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }
            
            response = requests.post(
                self._api_url,
                json=payload,
                timeout=120
            )
            
            if response.status_code == 200:
                if stream:
                    # Handle streaming response
                    full_response = ""
                    for line in response.iter_lines():
                        if line:
                            data = json.loads(line)
                            if 'response' in data:
                                full_response += data['response']
                    return full_response
                else:
                    # Handle single response
                    data = response.json()
                    return data.get('response', '')
            else:
                logger.error(f"[LLM_MANAGER] API error: {response.status_code}")
                raise Exception(f"LLM API error: {response.status_code}")
                
        except Exception as e:
            logger.error(f"[LLM_MANAGER] Generation failed: {e}", exc_info=True)
            raise
    
    def analyze_context(self, text: str, model: str = None) -> Dict:
        """
        Analyze context from text using LLM
        Returns structured data
        """
        prompt = f"""
Phân tích hội thoại sau và trích xuất thông tin chi tiết.
Trả về kết quả dưới dạng JSON với các trường:
- summary: Tóm tắt ngắn gọn
- key_points: Các điểm chính (list)
- entities: Các thực thể (people, locations, time, contact_info)
- relationships: Mối quan hệ giữa các thực thể
- actions: Các hành động, quyết định
- sentiment: Cảm xúc, thái độ

Hội thoại:
{text}

JSON:
"""
        
        try:
            response = self.generate(prompt, model=model)
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
            else:
                logger.warning("[LLM_MANAGER] No JSON found in response")
                return {"summary": response, "key_points": []}
        except Exception as e:
            logger.error(f"[LLM_MANAGER] Context analysis failed: {e}")
            return {"summary": "", "key_points": []}
    
    @classmethod
    def get_instance(cls) -> 'LLMManager':
        """Get singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance


# Global accessor
def get_llm_manager() -> LLMManager:
    """Get global LLM manager instance"""
    return LLMManager.get_instance()
