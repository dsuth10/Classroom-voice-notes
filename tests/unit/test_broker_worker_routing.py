# tests/unit/test_broker_worker_routing.py
import unittest
from unittest.mock import patch, MagicMock
from app.worker.broker_worker import BrokerWorker
from app.worker.errors import (
    GatewayAuthenticationError,
    ExecutionTimeoutUnknown,
    GatewayUnavailableError,
    InvalidTaskPayload
)

class TestBrokerWorkerRouting(unittest.TestCase):
    def setUp(self):
        self.config = {
            "poll_interval_seconds": 5,
            "openclaw": {
                "gateway_url": "http://127.0.0.1:18789",
                "responses_path": "/v1/responses",
                "agent_id": "cvn-broker"
            }
        }
        
    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_openclaw_claimed(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)
        
        with patch("app.worker.broker_worker.OpenClawAdapter") as MockAdapterClass:
            mock_adapter = MockAdapterClass.return_value
            mock_adapter.convert_task.return_value = {"input": "test"}
            mock_adapter.execute.return_value = {"output": "success result"}
            mock_adapter.validate_response.return_value = {"result_summary": "success result"}
            
            with patch.object(worker, "complete_task") as mock_complete:
                worker.process_claimed_task("CVN-1234", "openclaw", {"schema_version": "cvn.agent_task.v1", "task": {"instructions": "{}"}})
                
                mock_adapter.validate_task.assert_called_once()
                mock_adapter.execute.assert_called_once()
                mock_complete.assert_called_once_with("CVN-1234", "success result")

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_hermes_rejected(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)
        
        with patch.object(worker, "fail_task") as mock_fail:
            worker.process_claimed_task("CVN-1234", "hermes", {})
            mock_fail.assert_not_called()

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_permanent_failure(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)
        
        with patch("app.worker.broker_worker.OpenClawAdapter") as MockAdapterClass:
            mock_adapter = MockAdapterClass.return_value
            mock_adapter.validate_task.side_effect = InvalidTaskPayload("Invalid envelope")
            
            with patch.object(worker, "fail_task") as mock_fail:
                worker.process_claimed_task("CVN-1234", "openclaw", {})
                mock_fail.assert_called_once_with("CVN-1234", "Invalid envelope", "InvalidTaskPayload", "permanent")

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_unknown_timeout_failure(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)
        
        with patch("app.worker.broker_worker.OpenClawAdapter") as MockAdapterClass:
            mock_adapter = MockAdapterClass.return_value
            mock_adapter.execute.side_effect = ExecutionTimeoutUnknown("Read timed out")
            
            with patch.object(worker, "fail_task") as mock_fail:
                worker.process_claimed_task("CVN-1234", "openclaw", {"schema_version": "cvn.agent_task.v1", "task": {"instructions": "{}"}})
                mock_fail.assert_called_once_with("CVN-1234", "Gateway read timeout occurred after successful dispatch.", "EXECUTION_TIMEOUT_UNKNOWN", "execution_unknown")

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_fatal_gateway_failure(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)
        worker.running = True
        
        with patch("app.worker.broker_worker.OpenClawAdapter") as MockAdapterClass:
            mock_adapter = MockAdapterClass.return_value
            mock_adapter.execute.side_effect = GatewayAuthenticationError("Auth failed")
            
            with patch.object(worker, "fail_task") as mock_fail:
                worker.process_claimed_task("CVN-1234", "openclaw", {"schema_version": "cvn.agent_task.v1", "task": {"instructions": "{}"}})
                mock_fail.assert_called_once_with("CVN-1234", "Auth failed", "GatewayAuthenticationError", "permanent")
                self.assertFalse(worker.running)
