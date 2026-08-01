# tests/unit/test_broker_worker_routing.py
import os
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
        os.environ["CVN_WORKER_ID"] = "vps-worker-id-staging"
        os.environ["AGENT_BROKER_KEY_ID"] = "vps-worker-staging"
        os.environ["CVN_TARGET_AGENT"] = "openclaw"
        os.environ["CVN_BROKER_ENV"] = "staging"
        self.config = {
            "poll_interval_seconds": 5,
            "openclaw": {
                "gateway_url": "http://127.0.0.1:18789",
                "responses_path": "/v1/responses",
                "agent_id": "cvn-broker"
            }
        }

    def tearDown(self):
        os.environ.pop("CVN_WORKER_ID", None)
        os.environ.pop("AGENT_BROKER_KEY_ID", None)
        os.environ.pop("CVN_TARGET_AGENT", None)
        os.environ.pop("CVN_BROKER_ENV", None)

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_openclaw_claimed(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)

        mock_adapter = MagicMock()
        mock_adapter.convert_task.return_value = {"input": "test"}
        mock_adapter.execute.return_value = {"output": "success result"}
        mock_adapter.validate_response.return_value = {"result_summary": "success result"}

        with patch("app.worker.task_adapter.AdapterRegistry.get_adapter", return_value=mock_adapter):
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
            mock_fail.assert_called_once()
            self.assertIn("Hermes task execution is currently unavailable", mock_fail.call_args[0][1])

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_permanent_failure(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)

        mock_adapter = MagicMock()
        mock_adapter.validate_task.side_effect = InvalidTaskPayload("Invalid envelope")

        with patch("app.worker.task_adapter.AdapterRegistry.get_adapter", return_value=mock_adapter):
            with patch.object(worker, "fail_task") as mock_fail:
                worker.process_claimed_task("CVN-1234", "openclaw", {})
                mock_fail.assert_called_once_with("CVN-1234", "Invalid envelope", "InvalidTaskPayload", "permanent")

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_unknown_timeout_failure(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)

        mock_adapter = MagicMock()
        mock_adapter.execute.side_effect = ExecutionTimeoutUnknown("Read timed out")

        with patch("app.worker.task_adapter.AdapterRegistry.get_adapter", return_value=mock_adapter):
            with patch.object(worker, "fail_task") as mock_fail:
                worker.process_claimed_task("CVN-1234", "openclaw", {"schema_version": "cvn.agent_task.v1", "task": {"instructions": "{}"}})
                mock_fail.assert_called_once_with("CVN-1234", "Gateway read timeout occurred after successful dispatch.", "EXECUTION_TIMEOUT_UNKNOWN", "execution_unknown")

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_routing_fatal_gateway_failure(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"
        worker = BrokerWorker(self.config)
        worker.running = True

        mock_adapter = MagicMock()
        mock_adapter.execute.side_effect = GatewayAuthenticationError("Auth failed")

        with patch("app.worker.task_adapter.AdapterRegistry.get_adapter", return_value=mock_adapter):
            with patch.object(worker, "fail_task") as mock_fail:
                worker.process_claimed_task("CVN-1234", "openclaw", {"schema_version": "cvn.agent_task.v1", "task": {"instructions": "{}"}})
                mock_fail.assert_called_once_with("CVN-1234", "Auth failed", "GatewayAuthenticationError", "permanent")
                self.assertFalse(worker.running)

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_worker_gateway_url_validation(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"

        # Valid loopbacks
        valid_urls = [
            "http://127.0.0.1:18789",
            "http://localhost",
            "http://[::1]",
            "unix:///tmp/openclaw.sock",
            "http+unix://%2Ftmp%2Fsocket"
        ]
        for url in valid_urls:
            cfg = self.config.copy()
            cfg["openclaw"] = cfg["openclaw"].copy()
            cfg["openclaw"]["gateway_url"] = url
            # Should not raise RuntimeError
            worker = BrokerWorker(cfg)

        # Invalid endpoints
        invalid_urls = [
            "http://google.com",
            "https://192.168.1.10:18789",
            "ftp://localhost",
            "http://example.com/api"
        ]
        for url in invalid_urls:
            cfg = self.config.copy()
            cfg["openclaw"] = cfg["openclaw"].copy()
            cfg["openclaw"]["gateway_url"] = url
            with self.assertRaises(RuntimeError):
                BrokerWorker(cfg)

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_vps_worker_restrictions(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"

        # Set to VPS worker mode
        os.environ["AGENT_BROKER_KEY_ID"] = "vps-worker-staging"

        # Missing CVN_WORKER_ID
        os.environ.pop("CVN_WORKER_ID", None)
        with self.assertRaises(RuntimeError):
            BrokerWorker(self.config)

        # Missing CVN_TARGET_AGENT
        os.environ["CVN_WORKER_ID"] = "vps-worker-id-staging"
        os.environ.pop("CVN_TARGET_AGENT", None)
        with self.assertRaises(RuntimeError):
            BrokerWorker(self.config)

        # Wrong target agent for VPS worker
        os.environ["CVN_TARGET_AGENT"] = "hermes"
        with self.assertRaises(RuntimeError):
            BrokerWorker(self.config)

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_windows_hermes_fallbacks(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"

        # Non-vps worker mode (Windows/Hermes)
        os.environ["AGENT_BROKER_KEY_ID"] = "windows-worker"
        os.environ.pop("CVN_WORKER_ID", None)
        os.environ["CVN_TARGET_AGENT"] = "hermes"

        # Should initialize successfully and fallback or allow hermes target agent
        worker = BrokerWorker(self.config)
        self.assertEqual(worker.target_agent, "hermes")
        self.assertTrue(worker.worker_id.startswith("openclaw-worker-"))

        # Verify that gateway_token is empty and openclaw config is not required for hermes target
        cfg_no_openclaw = {"poll_interval_seconds": 5}
        worker_no_oc = BrokerWorker(cfg_no_openclaw)
        self.assertEqual(worker_no_oc.gateway_token, "")

    @patch("app.worker.broker_worker.BrokerWorker._resolve_secret")
    def test_broker_worker_env_validation(self, mock_resolve):
        mock_resolve.return_value = "fake-secret-value"

        # Test values that must be rejected
        rejected_envs = [
            "",
            "production",
            "prod",
            "development",
            "Staging",
            "stagin",  # misspelt
        ]

        for env in rejected_envs:
            with patch.dict(os.environ, {"CVN_BROKER_ENV": env}):
                with self.assertRaises(RuntimeError) as cm:
                    BrokerWorker(self.config)
                self.assertEqual(str(cm.exception), "CVN_BROKER_ENV must equal exactly 'staging'")

        # Test missing environment variable (absent)
        with patch.dict(os.environ):
            os.environ.pop("CVN_BROKER_ENV", None)
            with self.assertRaises(RuntimeError) as cm:
                BrokerWorker(self.config)
            self.assertEqual(str(cm.exception), "CVN_BROKER_ENV must equal exactly 'staging'")
