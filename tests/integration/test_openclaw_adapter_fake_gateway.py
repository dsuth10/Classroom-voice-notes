# tests/integration/test_openclaw_adapter_fake_gateway.py
import unittest
import http.server
import socket
import threading
import json
import time
from typing import Dict, Any

from app.destinations.openclaw_adapter import OpenClawAdapter
from app.worker.errors import (
    GatewayUnavailableError,
    ExecutionTimeoutUnknown,
    GatewayResponseError
)

class FakeGatewayHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging to keep test output clean
        pass

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length).decode('utf-8')
        req_data = json.loads(body)

        prompt = req_data.get("input", "")

        if "simulate_delay" in prompt:
            # Simulate a read timeout
            time.sleep(2.0)

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()

        resp = {
            "output": f"Echo: {prompt}"
        }
        self.wfile.write(json.dumps(resp).encode('utf-8'))

class TestOpenClawAdapterFakeGateway(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Find a free local port
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        cls.port = s.getsockname()[1]
        s.close()

        cls.server = http.server.HTTPServer(('127.0.0.1', cls.port), FakeGatewayHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever)
        cls.thread.daemon = True
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.config = {
            "gateway_url": f"http://127.0.0.1:{self.port}",
            "responses_path": "/v1/responses",
            "agent_id": "cvn-broker",
            "connect_timeout_seconds": 10.0,  # Must be longer than read timeout to avoid race
        }
        self.adapter = OpenClawAdapter(self.config, "fake-token")

    def test_fake_gateway_success(self):
        req = {
            "model": "openclaw/cvn-broker",
            "input": "Hello Fake Gateway",
            "user": "cvn-task:TEST-123",
            "stream": False,
            "max_output_tokens": 200
        }
        res = self.adapter.execute(req, 5)
        self.assertEqual(res["output"], "Echo: Hello Fake Gateway")

        validated = self.adapter.validate_response(res)
        self.assertEqual(validated["result_summary"], "Echo: Hello Fake Gateway")

    def test_fake_gateway_read_timeout(self):
        req = {
            "model": "openclaw/cvn-broker",
            "input": "simulate_delay",
            "user": "cvn-task:TEST-123",
            "stream": False,
            "max_output_tokens": 200
        }
        # Execute with 1 second read timeout, fake gateway sleeps 2 seconds
        with self.assertRaises(ExecutionTimeoutUnknown):
            self.adapter.execute(req, 1)

    def test_fake_gateway_unreachable(self):
        bad_config = self.config.copy()
        bad_config["gateway_url"] = "http://127.0.0.1:59999"  # Unused port
        bad_adapter = OpenClawAdapter(bad_config, "fake-token")

        req = {
            "model": "openclaw/cvn-broker",
            "input": "Hello Unreachable",
            "user": "cvn-task:TEST-123",
            "stream": False,
            "max_output_tokens": 200
        }
        with self.assertRaises(GatewayUnavailableError):
            bad_adapter.execute(req, 5)
