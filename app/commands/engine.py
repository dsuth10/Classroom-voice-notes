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
        
        # Check final result if a segment/silence boundary is reached
        if self.rec.AcceptWaveform(chunk_bytes):
            result_json = self.rec.Result()
            try:
                result_data = json.loads(result_json)
                text = result_data.get("text", "").strip()
                words = text.split()
                if len(words) == 1 and words[0] in self.keywords:
                    return words[0]
            except Exception:
                pass
        
        # Check partial result but ONLY execute command if it's the sole word detected
        # to prevent false-triggers from phonetically similar words in normal sentences
        partial_json = self.rec.PartialResult()
        try:
            partial_data = json.loads(partial_json)
            partial_text = partial_data.get("partial", "").strip()
            words = partial_text.split()
            if len(words) == 1 and words[0] in self.keywords:
                # Reset recogniser to avoid double trigger
                self.rec.Reset()
                return words[0]
        except Exception:
            pass
            
        return None
