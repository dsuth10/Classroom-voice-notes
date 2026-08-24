# tests/integration/test_openclaw_staging.py
import os
import unittest
import requests
from app.destinations.openclaw_adapter import OpenClawAdapter

@unittest.skipIf(
    os.getenv("RUN_LIVE_OPENCLAW_TESTS") != "true",
    "Skipping live OpenClaw integration tests (set RUN_LIVE_OPENCLAW_TESTS=true to run)"
)
class TestOpenClawStaging(unittest.TestCase):
    def setUp(self):
        self.gateway_url = os.getenv("OPENCLAW_GATEWAY_URL", "http://127.0.0.1:18789")
        self.gateway_token = os.getenv("OPENCLAW_GATEWAY_TOKEN")
        self.agent_id = os.getenv("OPENCLAW_AGENT_ID", "cvn-broker")

        if not self.gateway_token:
            self.fail("OPENCLAW_GATEWAY_TOKEN must be set to run live integration tests")

        self.config = {
            "gateway_url": self.gateway_url,
            "responses_path": "/v1/responses",
            "agent_id": self.agent_id,
            "connect_timeout_seconds": 10.0,
            "maximum_output_tokens": 200,
            "maximum_result_characters": 20000
        }
        self.adapter = OpenClawAdapter(self.config, self.gateway_token)

    def test_live_gateway_echo(self):
        task = {
            "schema_version": "cvn.agent_task.v1",
            "task_id": "CVN-20260710-120000-LIVE",
            "target_agent": "openclaw",
            "task": {
                "title": "Staging Live Echo Check",
                "instructions": '{"task_type": "cvn.test", "payload": {"test_mode": "echo", "text": "Return exactly: CVN_OPENCLAW_STAGING_OK"}}'
            }
        }

        self.adapter.validate_task(task)
        request = self.adapter.convert_task(task)
        response = self.adapter.execute(request, 120)
        result = self.adapter.validate_response(response)

        self.assertEqual(
            result["result_reference"],
            "openclaw_result:CVN_OPENCLAW_STAGING_OK",
        )
        print("[+] Live gateway execution returned a safe receipt.")
