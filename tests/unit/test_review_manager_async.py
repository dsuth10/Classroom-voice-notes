import time
from unittest.mock import MagicMock
from app.destinations.review_manager import ReviewManager

def test_review_manager_runs_async_and_prevents_overlap(tmp_path, monkeypatch):
    vault_dir = tmp_path / "vault"
    queue_dir = vault_dir / "Classroom Voice Notes" / "Review Queue"
    queue_dir.mkdir(parents=True)
    
    mock_settings = MagicMock()
    mock_settings.get.side_effect = lambda key, default=None: {
        "ollama_url": "http://localhost:11434",
        "careful_model": "phi4:14b",
    }.get(key, default)
    
    rm = ReviewManager(str(vault_dir), mock_settings)
    
    scan_count = 0
    def mock_scan_impl(self):
        nonlocal scan_count
        scan_count += 1
        time.sleep(0.1)
        return 0
        
    monkeypatch.setattr(ReviewManager, "_scan_queue_impl", mock_scan_impl)
    
    # Trigger first scan
    rm.trigger_scan()
    assert rm._is_scanning is True
    
    # Immediately trigger second scan while first is in progress
    rm.trigger_scan()
    
    # Wait for background thread to complete
    time.sleep(0.2)
    assert rm._is_scanning is False
    assert scan_count == 1  # Second scan should have been skipped due to lock/flag
