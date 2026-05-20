"""
LLM Manager - Singleton Pattern for configured LLM providers.
Lazy loading, optional usage (không gọi mặc định).
"""
import logging
import requests
import json
from typing import Optional, Dict, List
from src.core.config import settings

logger = logging.getLogger(__name__)


def llm_provider_configured() -> bool:
    provider = (settings.ANALYSIS_LLM_PROVIDER or "").lower()
    if provider in {"openai", "openai_compatible", "openrouter"}:
        return bool(settings.ANALYSIS_LLM_API_KEY)
    if provider in {"ollama", "llama_cpp_server"}:
        return True
    return bool(settings.ANALYSIS_LLM_API_KEY)


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
            self._provider = (settings.ANALYSIS_LLM_PROVIDER or "ollama").lower()
            self._base_url = (settings.ANALYSIS_LLM_BASE_URL or "http://localhost:11434").rstrip("/")
            self._api_url = f"{self._base_url}/api/generate"
            self._default_model = settings.ANALYSIS_LLM_MODEL or "gpt-oss:latest"
            self._initialized = True
            logger.info("[LLM_MANAGER] Initialized | provider=%s | model=%s", self._provider, self._default_model)

    def _is_chat_provider(self) -> bool:
        return self._provider in {"openai", "openai_compatible", "openrouter", "llama_cpp_server"}

    def _auth_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if settings.ANALYSIS_LLM_API_KEY:
            headers["Authorization"] = f"Bearer {settings.ANALYSIS_LLM_API_KEY}"
        if self._provider == "openrouter":
            if settings.ANALYSIS_LLM_HTTP_REFERER:
                headers["HTTP-Referer"] = settings.ANALYSIS_LLM_HTTP_REFERER
            if settings.ANALYSIS_LLM_APP_TITLE:
                headers["X-Title"] = settings.ANALYSIS_LLM_APP_TITLE
        return headers

    def _chat_url(self) -> str:
        return f"{self._base_url}/chat/completions"

    def _bounded_prompt(self, prompt: str) -> str:
        max_chars = settings.ANALYSIS_LLM_MAX_INPUT_CHARS
        if max_chars and len(prompt) > max_chars:
            logger.warning(
                "[LLM_MANAGER] Prompt truncated by ANALYSIS_LLM_MAX_INPUT_CHARS | original_chars=%s | max_chars=%s",
                len(prompt),
                max_chars,
            )
            return prompt[:max_chars]
        return prompt

    def _bounded_max_tokens(self, requested: int) -> int:
        configured = settings.ANALYSIS_LLM_MAX_OUTPUT_TOKENS
        if configured and requested > configured:
            return configured
        return requested

    def _http_error_message(self, response: requests.Response) -> str:
        reason = "".join(ch if ch.isalnum() else "_" for ch in str(response.reason or "").lower())
        reason = "_".join(part for part in reason.split("_") if part)[:80]
        suffix = f"_{reason}" if reason else ""
        return f"LLM API error: status={response.status_code}{suffix}"

    def check_availability(self) -> bool:
        """Check if the configured provider is available."""
        if self._is_chat_provider():
            if self._provider in {"openai", "openai_compatible", "openrouter"} and not settings.ANALYSIS_LLM_API_KEY:
                logger.warning("[LLM_MANAGER] API key is missing for provider=%s", self._provider)
                return False
            try:
                response = requests.get(
                    f"{self._base_url}/models",
                    headers=self._auth_headers(),
                    timeout=min(10, settings.ANALYSIS_LLM_TIMEOUT_SECONDS),
                )
                if response.status_code == 200:
                    data = response.json()
                    models = data.get("data", []) if isinstance(data, dict) else []
                    self._available_models = [
                        str(item.get("id"))
                        for item in models
                        if isinstance(item, dict) and item.get("id")
                    ]
                    return True
                logger.warning("[LLM_MANAGER] Provider availability failed | status=%s", response.status_code)
            except Exception as e:
                logger.warning("[LLM_MANAGER] Provider not available | provider=%s | error=%s", self._provider, e)
            return False

        # Ollama native API.
        try:
            response = requests.get(f"{self._base_url}/api/tags", timeout=2)
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
        Priority: preferred > gpt-oss:20b > gpt-oss:latest > gemma2:9b > deepseek-r1:7b > first available
        """
        if self._is_chat_provider():
            if preferred:
                return preferred
            if self._default_model:
                return self._default_model

        models = self.get_available_models()

        if not models:
            logger.warning("[LLM_MANAGER] No models available, using default")
            return self._default_model

        if preferred and preferred in models:
            return preferred

        # Priority list: DeepSeek R1 (Strongest), then others
        priority = [
            "deepseek-r1:8b",        # State-of-the-art Reasoning
            "gemma2:9b",             # High quality general model
            "llama3.1:8b",           # Meta's latest
            "deepseek-coder:6.7b-instruct",
            "gpt-oss:latest"
        ]
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
            raise Exception(f"LLM provider is not available: {self._provider}")

        if model is None:
            model = self.select_best_model()

        prompt = self._bounded_prompt(prompt)
        max_tokens = self._bounded_max_tokens(max_tokens)
        logger.info("[LLM_MANAGER] Generating | provider=%s | model=%s", self._provider, model)

        if self._is_chat_provider():
            try:
                return self._generate_chat_completion(
                    prompt=prompt,
                    model=model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
            except Exception:
                fallback = settings.ANALYSIS_LLM_FALLBACK_MODEL
                if fallback and fallback != model:
                    logger.warning(
                        "[LLM_MANAGER] Primary chat model failed, retrying fallback | provider=%s | fallback=%s",
                        self._provider,
                        fallback,
                    )
                    return self._generate_chat_completion(
                        prompt=prompt,
                        model=fallback,
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                raise

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

            logger.debug(f"[LLM_MANAGER] Sending request to {self._api_url} | model={model} | prompt_length={len(prompt)}")

            # Use longer timeout for large prompts
            # (connect timeout, read timeout) - 30s to connect, 300s (5min) to read
            # For very long transcripts, may need even longer
            connect_timeout = 30
            read_timeout = min(600, max(300, len(prompt) // 100))  # 5-10 min based on prompt length

            response = requests.post(
                self._api_url,
                json=payload,
                timeout=(connect_timeout, read_timeout),
                stream=stream
            )

            if response.status_code == 200:
                if stream:
                    # Handle streaming response
                    full_response = ""
                    for line in response.iter_lines():
                        if line:
                            try:
                                data = json.loads(line)
                                if 'response' in data:
                                    full_response += data['response']
                                if data.get('done', False):
                                    break
                            except json.JSONDecodeError:
                                continue
                    return full_response
                else:
                    # Handle single response
                    data = response.json()
                    result = data.get('response', '')
                    logger.debug(f"[LLM_MANAGER] Received response | length={len(result)}")
                    return result
            else:
                error_msg = self._http_error_message(response)
                logger.error("[LLM_MANAGER] %s", error_msg)
                raise Exception(error_msg)

        except requests.exceptions.Timeout as e:
            logger.error(f"[LLM_MANAGER] Request timeout: {e}")
            raise Exception(f"LLM request timeout after {read_timeout}s. The prompt may be too long or Ollama is slow.")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"[LLM_MANAGER] Connection error: {e}")
            raise Exception(f"Cannot connect to LLM provider: {self._provider}")
        except Exception as e:
            logger.error(f"[LLM_MANAGER] Generation failed: {e}", exc_info=True)
            raise

    def _generate_chat_completion(
        self,
        *,
        prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        timeout = settings.ANALYSIS_LLM_TIMEOUT_SECONDS
        try:
            response = requests.post(
                self._chat_url(),
                json=payload,
                headers=self._auth_headers(),
                timeout=(10, timeout),
            )
            if response.status_code != 200:
                raise Exception(self._http_error_message(response))
            data = response.json()
            choices = data.get("choices") or []
            if not choices:
                return ""
            message = choices[0].get("message") if isinstance(choices[0], dict) else None
            if isinstance(message, dict):
                content = message.get("content")
                if isinstance(content, list):
                    return "".join(
                        str(part.get("text") or "")
                        for part in content
                        if isinstance(part, dict)
                    )
                return str(content or "")
            return str(choices[0].get("text") or "")
        except requests.exceptions.Timeout as e:
            logger.error("[LLM_MANAGER] Chat completion timeout: %s", e)
            raise Exception(f"LLM request timeout after {timeout}s")
        except requests.exceptions.ConnectionError as e:
            logger.error("[LLM_MANAGER] Chat completion connection error: %s", e)
            raise Exception(f"Cannot connect to LLM provider: {self._provider}")

    def analyze_context(self, text: str, model: str = None) -> Dict:
        """
        Analyze context from text using LLM for criminal investigation
        Returns comprehensive structured data with all sensitive information
        """
        prompt = f"""
PHÂN TÍCH HỘI THOẠI CHO ĐIỀU TRA HÌNH SỰ - STRUCTURED OUTPUT

Bạn là chuyên gia điều tra tội phạm. Phân tích hội thoại sau và trích xuất TẤT CẢ thông tin có thể.

Trả về kết quả dưới dạng JSON với cấu trúc sau (BẮT BUỘC phải đúng format JSON hợp lệ):

{{
  "summary": "Tóm tắt toàn diện không giới hạn độ dài. Bao gồm tất cả chi tiết quan trọng.",
  "context": {{
    "topic": "Chủ đề chính",
    "purpose": "Mục đích cuộc gọi",
    "status": "Trạng thái",
    "call_type": "normal|urgent|suspicious",
    "risk_level": "low|medium|high|critical"
  }},
  "key_points": ["Điểm quan trọng 1", "Điểm quan trọng 2"],
  "entities": {{
    "people": [
      {{"name": "Họ tên đầy đủ", "role": "Vai trò", "phone": "SĐT", "id_number": "CCCD", "address": "Địa chỉ", "is_sensitive": true, "context": "Ngữ cảnh", "behavior": "Thái độ"}}
    ],
    "locations": [
      {{"name": "Địa điểm", "address": "Địa chỉ chi tiết", "type": "Loại", "is_sensitive": false, "context": "Mục đích"}}
    ],
    "time": [
      {{"value": "Thời gian cụ thể", "type": "Loại", "context": "Ngữ cảnh", "is_sensitive": false}}
    ],
    "organizations": ["Tên tổ chức"],
    "contact_info": {{
      "phones": [{{"value": "0987654321", "owner": "Chủ SĐT", "type": "mobile", "is_sensitive": true, "context": "Ngữ cảnh"}}],
      "emails": [{{"value": "email@example.com", "owner": "Chủ email", "is_sensitive": true, "context": "Mục đích"}}],
      "ids": [{{"value": "001234567890", "owner": "Chủ CCCD", "type": "cccd", "is_sensitive": true, "context": "Ngữ cảnh"}}],
      "bank_accounts": [{{"account_number": "1234567890", "bank_name": "Ngân hàng", "account_holder": "Chủ TK", "is_sensitive": true, "context": "Mục đích"}}],
      "addresses": [{{"value": "Địa chỉ đầy đủ", "owner": "Chủ địa chỉ", "type": "home|office", "is_sensitive": true, "context": "Loại"}}]
    }}
  }},
  "relationships": [
    {{"source": "Người A", "target": "Người B", "label": "Loại quan hệ", "context": "Chi tiết", "is_suspicious": false}}
  ],
  "events": [
    {{"time": "Thời điểm", "description": "Mô tả sự kiện", "action": "Hành động", "actors": ["Người 1"], "location": "Địa điểm", "is_suspicious": false}}
  ],
  "financial_info": {{
    "transactions": [
      {{"amount": "6000000 VND", "currency": "VND", "purpose": "Mục đích", "method": "Chuyển khoản", "payer": "Người trả", "receiver": "Người nhận", "status": "pending", "is_suspicious": false}}
    ],
    "offers": [{{"content": "Ưu đãi", "value": "Giá trị", "conditions": "Điều kiện"}}]
  }},
  "actions": [{{"actor": "Người thực hiện", "action": "Hành động", "status": "completed|pending", "is_suspicious": false}}],
  "decisions": [{{"decision_maker": "Người quyết định", "decision": "Nội dung", "impact": "Ảnh hưởng"}}],
  "sentiment": {{
    "overall": "positive|negative|neutral",
    "caller_emotion": "Cảm xúc người gọi",
    "receiver_emotion": "Cảm xúc người nhận",
    "honesty_assessment": "honest|evasive|deceptive"
  }},
  "sensitive_info": [
    {{"category": "personal|financial|criminal", "type": "Loại", "value": "Giá trị", "owner": "Chủ sở hữu", "sensitivity_reason": "Lý do", "risk_level": "low|medium|high"}}
  ],
  "anomalies": [
    {{"type": "behavioral|verbal|financial", "description": "Mô tả", "severity": "low|medium|high", "evidence": "Bằng chứng"}}
  ],
  "slang_detected": {{
    "has_slang": false,
    "terms": [{{"term": "Từ lóng", "possible_meaning": "Ý nghĩa", "context": "Ngữ cảnh"}}]
  }},
  "hidden_relationships": [
    {{"description": "Mô tả mối quan hệ ẩn", "involved_parties": ["Bên 1", "Bên 2"], "evidence": "Bằng chứng"}}
  ],
  "contradictions": [
    {{"statement_1": "Lời nói 1", "statement_2": "Lời nói 2 mâu thuẫn", "severity": "minor|significant|major"}}
  ],
  "risk_assessment": {{
    "overall_risk": "low|medium|high|critical",
    "crime_indicators": [{{"crime_type": "fraud|money_laundering|other", "confidence": "low|medium|high", "indicators": ["Chỉ báo"]}}],
    "urgency": "routine|monitor|investigate|immediate_action",
    "recommended_actions": ["Hành động khuyến nghị"]
  }},
  "insight": ["Insight nghiệp vụ, phân tích sâu"],
  "investigation_notes": {{
    "priority_level": "low|medium|high|critical",
    "follow_up_questions": ["Câu hỏi cần truy vấn"],
    "verification_needed": ["Thông tin cần xác minh"],
    "surveillance_targets": ["Đối tượng cần giám sát"],
    "missing_information": ["Thông tin còn thiếu"],
    "next_steps": ["Bước tiếp theo"]
  }}
}}

=== HỘI THOẠI CẦN PHÂN TÍCH ===

{text}

=== HƯỚNG DẪN QUAN TRỌNG ===

1. Trích xuất TẤT CẢ thông tin có thể, không bỏ sót chi tiết nào
2. Thông tin nhân thân (họ tên, SĐT, CCCD, địa chỉ) là ƯU TIÊN TUYỆT ĐỐI
3. Nếu không có thông tin cho trường nào, để [], "", {{}}, hoặc null
4. Tất cả số tiền phải chính xác đến đồng
5. Tất cả thời gian phải cụ thể (ngày/tháng/năm, giờ:phút nếu có)
6. Phát hiện mâu thuẫn, dấu hiệu bất thường là rất quan trọng
7. BẮT BUỘC trả về JSON hợp lệ, không có text thừa

Hãy phân tích kỹ và trả về JSON đầy đủ ngay bây giờ:

JSON:
"""

        try:
            response = self.generate(prompt, model=model, temperature=0.2)  # Lower temp for structured output
            # Try to extract JSON from response
            import re
            json_match = re.search(r'\{{.*\}}', response, re.DOTALL)
            if json_match:
                parsed = json.loads(json_match.group())
                logger.info(f"[LLM_MANAGER] Investigation analysis complete | fields={{len(parsed)}} | risk={{parsed.get('risk_assessment', {{}}).get('overall_risk', 'unknown')}}")
                return parsed
            else:
                logger.warning("[LLM_MANAGER] No JSON found in response")
                return {"summary": response, "key_points": []}
        except Exception as e:
            logger.error(f"[LLM_MANAGER] Investigation analysis failed: {{e}}")
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
