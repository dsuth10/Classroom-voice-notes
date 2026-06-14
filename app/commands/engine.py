import abc
import json
import numpy as np

class CommandEngine(abc.ABC):
    @abc.abstractmethod
    def accept_chunk(self, chunk: np.ndarray) -> str | None:
        """Process a chunk of audio and return a recognised command string or None."""
        pass

class VoskCommandEngine(CommandEngine):
    def __init__(self, model_path: str, keywords: list[str], sample_rate: int = 16000) -> None:
        self.model_path = model_path
        self.keywords = keywords
        self.sample_rate = sample_rate
        
        import vosk
        self.model = vosk.Model(model_path)
        # Limit Vosk's search space using a grammar list for maximum speed and accuracy
        grammar = json.dumps(self.keywords + ["[unk]"])
        self.rec = vosk.KaldiRecognizer(self.model, self.sample_rate, grammar)

    def accept_chunk(self, chunk: np.ndarray) -> str | None:
        chunk_bytes = chunk.tobytes()
        self.rec.AcceptWaveform(chunk_bytes)
        
        # Check partial results for instant command execution
        partial_json = self.rec.PartialResult()
        try:
            partial_data = json.loads(partial_json)
            partial_text = partial_data.get("partial", "").strip()
            
            words: list[str] = partial_text.split()
            for word in words:
                if word in self.keywords:
                    # Reset the recogniser to prevent double-firing in subsequent frames
                    self.rec.Reset()
                    return word
        except Exception:
            pass
            
        return None
