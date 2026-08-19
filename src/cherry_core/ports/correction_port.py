from abc import ABC, abstractmethod

class ITextCorrector(ABC):
    @abstractmethod
    def correct(self, text: str) -> str:
        """
        Correct spelling and grammar in the provided text.
        """
        pass
