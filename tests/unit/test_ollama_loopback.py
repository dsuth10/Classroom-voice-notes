import pytest
from app.config.settings import SettingsManager, is_loopback_url
from app.ollama_router.classifier import OllamaClassifier

def test_is_loopback_url():
    assert is_loopback_url("http://localhost:11434") is True
    assert is_loopback_url("http://127.0.0.1:11434") is True
    assert is_loopback_url("http://[::1]:11434") is True
    assert is_loopback_url("localhost:11434") is True
    
    assert is_loopback_url("http://192.168.1.50:11434") is False
    assert is_loopback_url("https://ollama.example.com") is False
    assert is_loopback_url("http://10.0.0.1:11434") is False

def test_settings_manager_rejects_non_loopback(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.settings.get_config_path", lambda: tmp_path / "config.json")
    sm = SettingsManager()
    
    sm.set("ollama_url", "http://localhost:11434")
    assert sm.get("ollama_url") == "http://localhost:11434"
    
    with pytest.raises(ValueError, match="Ollama URL must point to local loopback"):
        sm.set("ollama_url", "http://192.168.1.100:11434")

def test_classifier_rejects_non_loopback():
    with pytest.raises(ValueError, match="Ollama URL must point to local loopback"):
        OllamaClassifier(url="http://192.168.1.100:11434")
