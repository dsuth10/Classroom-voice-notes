import abc
import numpy as np

class WakeEngine(abc.ABC):
    @abc.abstractmethod
    def predict(self, chunk: np.ndarray) -> float:
        """Process a chunk of audio and return a prediction score (0.0 to 1.0)."""
        pass

    @abc.abstractmethod
    def detect(self, chunk: np.ndarray) -> bool:
        """Process a chunk of audio and return True if the wake-phrase is detected."""
        pass

class ManualOnlyEngine(WakeEngine):
    def predict(self, chunk: np.ndarray) -> float:
        # Manual only mode never triggers wake-word detection automatically
        return 0.0

    def detect(self, chunk: np.ndarray) -> bool:
        return False

class OpenWakeWordEngine(WakeEngine):
    def __init__(self, model_path: str, threshold: float = 0.5) -> None:
        self.model_path = model_path
        self.threshold = threshold
        
        # Import openwakeword dynamically
        from openwakeword.model import Model
        self.model = Model(
            wakeword_models=[model_path],
            inference_framework="onnx"
        )

    def predict(self, chunk: np.ndarray) -> float:
        predictions = self.model.predict(chunk)
        if predictions:
            return float(max(predictions.values()))
        return 0.0

    def detect(self, chunk: np.ndarray) -> bool:
        return self.predict(chunk) >= self.threshold

