# tests/unit/test_openclaw_adapter.py
import unittest
from unittest.mock import patch, MagicMock
import requests
from app.destinations.openclaw_adapter import OpenClawAdapter
from app.worker.errors import (
    UnsupportedContractVersion,
    UnsupportedTaskType,
    UnsupportedTargetAgent,
    InvalidTaskPayload,
    GatewayAuthenticationError,
    GatewayUnavailableError,
    GatewayRateLimitError,
    GatewayConfigurationError,
    GatewayResponseError,
    ExecutionTimeoutUnknown,
    InvalidAgentResponse
)

class TestOpenClawAdapter(unittest.TestCase):
    def setUp(self):
        self.config = {
            "gateway_url": "http://127.0.0.1:18789",
            "responses_path": "/v1/responses",
            "agent_id": "cvn-broker",
            "normal_timeout_seconds": 120,
            "maximum_timeout_seconds": 1500,
            "maximum_output_tokens": 2000,
            "maximum_result_characters": 20000,
            "connect_timeout_seconds": 10.0
        }
        self.gateway_token = "test-gateway-token"
        self.adapter = OpenClawAdapter(self.config, self.gateway_token)
        
        self.valid_task = {
            "schema_version": "cvn.agent_task.v1",
            "task_id": "CVN-20260710-120000-ABCD",
            "target_agent": "openclaw",
            "task": {
                "title": "Echo test",
                "instructions": '{"task_type": "cvn.test", "payload": {"test_mode": "success", "text": "Hello OpenClaw"}}'
            }
        }

    def test_validate_task_success(self):
        self.adapter.validate_task(self.valid_task)

    def test_validate_task_unsupported_version(self):
        invalid = self.valid_task.copy()
        invalid["schema_version"] = "cvn.agent_task.v2"
        with self.assertRaises(UnsupportedContractVersion):
            self.adapter.validate_task(invalid)

    def test_validate_task_unsupported_agent(self):
        invalid = self.valid_task.copy()
        invalid["target_agent"] = "hermes"
        with self.assertRaises(UnsupportedTargetAgent):
            self.adapter.validate_task(invalid)

    def test_validate_task_unsupported_type(self):
        invalid = {
            "schema_version": "cvn.agent_task.v1",
            "task_id": "CVN-20260710-120000-ABCD",
            "target_agent": "openclaw",
            "task": {
                "title": "Echo test",
                "instructions": '{"task_type": "unsupported_type"}'
            }
        }
        with self.assertRaises(UnsupportedTaskType):
            self.adapter.validate_task(invalid)

    def test_validate_task_invalid_payload_limits(self):
        invalid = self.valid_task.copy()
        invalid["task"] = {
            "title": "A" * 201,
            "instructions": "Hello"
        }
        with self.assertRaises(InvalidTaskPayload):
            self.adapter.validate_task(invalid)

    def test_convert_task(self):
        req = self.adapter.convert_task(self.valid_task)
        self.assertEqual(req["model"], "openclaw/cvn-broker")
        self.assertEqual(req["input"], "Hello OpenClaw")
        self.assertEqual(req["user"], "cvn-task:CVN-20260710-120000-ABCD")
        self.assertEqual(req["max_output_tokens"], 200)

    @patch("requests.post")
    def test_execute_success(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"output": "CVN adapter connection successful."}
        mock_post.return_value = mock_response
        
        req = self.adapter.convert_task(self.valid_task)
        res = self.adapter.execute(req, 120)
        self.assertEqual(res["output"], "CVN adapter connection successful.")
        
        mock_post.assert_called_once_with(
            "http://127.0.0.1:18789/v1/responses",
            json=req,
            headers={
                "Authorization": "Bearer test-gateway-token",
                "Content-Type": "application/json"
            },
            timeout=(10.0, 120.0)
        )

    @patch("requests.post")
    def test_execute_connect_timeout(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectTimeout("Connect timed out")
        req = self.adapter.convert_task(self.valid_task)
        with self.assertRaises(GatewayUnavailableError):
            self.adapter.execute(req, 120)

    @patch("requests.post")
    def test_execute_read_timeout(self, mock_post):
        mock_post.side_effect = requests.exceptions.ReadTimeout("Read timed out")
        req = self.adapter.convert_task(self.valid_task)
        with self.assertRaises(ExecutionTimeoutUnknown):
            self.adapter.execute(req, 120)

    @patch("requests.post")
    def test_execute_connection_error(self, mock_post):
        mock_post.side_effect = requests.exceptions.ConnectionError("Connection refused")
        req = self.adapter.convert_task(self.valid_task)
        with self.assertRaises(GatewayUnavailableError):
            self.adapter.execute(req, 120)

    @patch("requests.post")
    def test_execute_unauthorized(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_post.return_value = mock_response
        req = self.adapter.convert_task(self.valid_task)
        with self.assertRaises(GatewayAuthenticationError):
            self.adapter.execute(req, 120)

    @patch("requests.post")
    def test_execute_not_found(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_post.return_value = mock_response
        req = self.adapter.convert_task(self.valid_task)
        with self.assertRaises(GatewayConfigurationError):
            self.adapter.execute(req, 120)

    @patch("requests.post")
    def test_execute_rate_limit(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_post.return_value = mock_response
        req = self.adapter.convert_task(self.valid_task)
        with self.assertRaises(GatewayRateLimitError):
            self.adapter.execute(req, 120)

    @patch("requests.post")
    def test_execute_server_error(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_post.return_value = mock_response
        req = self.adapter.convert_task(self.valid_task)
        with self.assertRaises(GatewayResponseError):
            self.adapter.execute(req, 120)

    def test_validate_response_success(self):
        resp = {"output": "Final answer here."}
        validated = self.adapter.validate_response(resp)
        self.assertEqual(validated["result_summary"], "Final answer here.")

    def test_validate_response_choices_format(self):
        resp = {"choices": [{"message": {"content": "Final choices answer."}}]}
        validated = self.adapter.validate_response(resp)
        self.assertEqual(validated["result_summary"], "Final choices answer.")

    def test_validate_response_oversized(self):
        resp = {"output": "A" * 20001}
        with self.assertRaises(InvalidAgentResponse):
            self.adapter.validate_response(resp)

    def test_validate_response_tool_calls_rejected(self):
        resp = {
            "output": "Partial output.",
            "tool_calls": [{"name": "read_filesystem"}]
        }
        with self.assertRaises(InvalidAgentResponse):
            self.adapter.validate_response(resp)

    def test_secret_redaction_in_exceptions(self):
        err = GatewayAuthenticationError("Gateway authentication failed")
        self.assertNotIn(self.gateway_token, str(err))
