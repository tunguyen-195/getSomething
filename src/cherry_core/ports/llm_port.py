from abc import ABC, abstractmethod
from typing import Dict, Any

class ILLMEngine(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """
        Generate raw text response from LLM.
        """
        pass

    @abstractmethod
    def load(self) -> bool:
        """
        Load the model into memory.
        """
        pass
