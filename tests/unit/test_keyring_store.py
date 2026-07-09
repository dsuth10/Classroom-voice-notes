from unittest.mock import MagicMock, patch
import keyring
from app.config import keyring_store

@patch("keyring.get_password")
def test_get_secret(mock_get: MagicMock) -> None:
    mock_get.return_value = "my_token"
    val = keyring_store.get_secret("my_ref")
    assert val == "my_token"
    mock_get.assert_called_once_with(keyring_store.SERVICE_NAME, "my_ref")

@patch("keyring.get_password")
def test_get_secret_missing(mock_get: MagicMock) -> None:
    mock_get.return_value = None
    val = keyring_store.get_secret("missing_ref")
    assert val is None

@patch("keyring.set_password")
def test_set_secret(mock_set: MagicMock) -> None:
    mock_set.return_value = None
    success = keyring_store.set_secret("my_ref", "secret_val")
    assert success is True
    mock_set.assert_called_once_with(keyring_store.SERVICE_NAME, "my_ref", "secret_val")

@patch("keyring.get_password")
def test_has_secret(mock_get: MagicMock) -> None:
    mock_get.return_value = "exists"
    assert keyring_store.has_secret("my_ref") is True
    
    mock_get.return_value = None
    assert keyring_store.has_secret("my_ref") is False
