# tests/unit/test_wait_for_gateway.py
import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open
import urllib.error
import io

class TestWaitForGateway(unittest.TestCase):

    def setUp(self):
        # Prevent actually calling time.sleep in tests to speed them up
        self.sleep_patcher = patch("time.sleep")
        self.mock_sleep = self.sleep_patcher.start()

        # Clean environment variables
        self.original_token_file = os.environ.get("OPENCLAW_GATEWAY_TOKEN_FILE")
        os.environ["OPENCLAW_GATEWAY_TOKEN_FILE"] = "/fake/token/path"

    def tearDown(self):
        self.sleep_patcher.stop()
        if self.original_token_file is None:
            os.environ.pop("OPENCLAW_GATEWAY_TOKEN_FILE", None)
        else:
            os.environ["OPENCLAW_GATEWAY_TOKEN_FILE"] = self.original_token_file

    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("builtins.open", new_callable=mock_open, read_data="fake-token-123")
    @patch("urllib.request.build_opener")
    def test_successful_response(self, mock_build_opener, mock_file, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 14

        # Mock opener and its response
        mock_opener = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = b'{"object": "list", "data": [{"id": "openclaw/cvn-broker"}]}'
        mock_opener.open.return_value.__enter__.return_value = mock_response
        mock_build_opener.return_value = mock_opener

        import deploy.wait_for_gateway as wait_script
        self.assertTrue(wait_script.check_gateway())

        # Verify that the build_opener was called and Authorization header was set
        mock_build_opener.assert_called_once()
        args, _ = mock_opener.open.call_args
        req = args[0]
        self.assertEqual(req.get_header("Authorization"), "Bearer fake-token-123")

    @patch("os.path.exists")
    @patch("urllib.request.build_opener")
    def test_gateway_unavailable(self, mock_build_opener, mock_exists):
        mock_exists.return_value = False

        # Mock connection refused
        mock_opener = MagicMock()
        mock_opener.open.side_effect = urllib.error.URLError("Connection refused")
        mock_build_opener.return_value = mock_opener

        import deploy.wait_for_gateway as wait_script
        self.assertFalse(wait_script.check_gateway())

    @patch("os.path.exists")
    @patch("urllib.request.build_opener")
    def test_timeout(self, mock_build_opener, mock_exists):
        mock_exists.return_value = False

        # Mock read timeout
        mock_opener = MagicMock()
        import socket
        mock_opener.open.side_effect = socket.timeout("timed out")
        mock_build_opener.return_value = mock_opener

        import deploy.wait_for_gateway as wait_script
        self.assertFalse(wait_script.check_gateway())

    @patch("os.path.exists")
    @patch("urllib.request.build_opener")
    def test_authentication_rejection(self, mock_build_opener, mock_exists):
        mock_exists.return_value = False

        # Mock 401 error
        mock_opener = MagicMock()
        mock_opener.open.side_effect = urllib.error.HTTPError(
            url="http://127.0.0.1:18789/v1/models",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=None
        )
        mock_build_opener.return_value = mock_opener

        import deploy.wait_for_gateway as wait_script
        self.assertFalse(wait_script.check_gateway())

    @patch("os.path.exists")
    @patch("urllib.request.build_opener")
    def test_5xx_rejected(self, mock_build_opener, mock_exists):
        mock_exists.return_value = False

        # Mock 500 error
        mock_opener = MagicMock()
        mock_opener.open.side_effect = urllib.error.HTTPError(
            url="http://127.0.0.1:18789/v1/models",
            code=500,
            msg="Internal Server Error",
            hdrs=None,
            fp=None
        )
        mock_build_opener.return_value = mock_opener

        import deploy.wait_for_gateway as wait_script
        self.assertFalse(wait_script.check_gateway())

    @patch("os.path.exists")
    @patch("urllib.request.build_opener")
    def test_404_rejected(self, mock_build_opener, mock_exists):
        mock_exists.return_value = False

        # Mock 404 error
        mock_opener = MagicMock()
        mock_opener.open.side_effect = urllib.error.HTTPError(
            url="http://127.0.0.1:18789/v1/models",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=None
        )
        mock_build_opener.return_value = mock_opener

        import deploy.wait_for_gateway as wait_script
        self.assertFalse(wait_script.check_gateway())

    @patch("os.path.exists")
    def test_credential_file_missing(self, mock_exists):
        mock_exists.return_value = False
        import deploy.wait_for_gateway as wait_script
        with patch("urllib.request.build_opener") as mock_build_opener:
            self.assertFalse(wait_script.check_gateway())
            mock_build_opener.assert_not_called()

    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("builtins.open")
    def test_credential_file_unreadable(self, mock_open_func, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 100
        mock_open_func.side_effect = PermissionError("Permission denied")

        import deploy.wait_for_gateway as wait_script
        with patch("urllib.request.build_opener") as mock_build_opener:
            self.assertFalse(wait_script.check_gateway())
            mock_build_opener.assert_not_called()

    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_credential_file_empty(self, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 0

        import deploy.wait_for_gateway as wait_script
        with patch("urllib.request.build_opener") as mock_build_opener:
            self.assertFalse(wait_script.check_gateway())
            mock_build_opener.assert_not_called()

    @patch("os.path.exists")
    @patch("os.path.getsize")
    def test_credential_file_oversized(self, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 5000  # > 4096

        import deploy.wait_for_gateway as wait_script
        with patch("urllib.request.build_opener") as mock_build_opener:
            self.assertFalse(wait_script.check_gateway())
            mock_build_opener.assert_not_called()

    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("builtins.open", new_callable=mock_open, read_data="secret-token-value")
    @patch("urllib.request.build_opener")
    def test_credential_value_absent_from_captured_output(self, mock_build_opener, mock_file, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 18

        # Mock exception that contains the token value in its string representation
        # wait_for_gateway.py must redact it
        mock_opener = MagicMock()
        mock_opener.open.side_effect = Exception("failed with token: secret-token-value")
        mock_build_opener.return_value = mock_opener

        import deploy.wait_for_gateway as wait_script

        # Capture stdout
        stdout_capture = io.StringIO()
        with patch("sys.stdout", stdout_capture):
            self.assertFalse(wait_script.check_gateway())

        output = stdout_capture.getvalue()
        self.assertNotIn("secret-token-value", output)
        self.assertIn("[REDACTED]", output)

    @patch("os.path.exists")
    @patch("os.path.getsize")
    @patch("builtins.open", new_callable=mock_open, read_data="fake-token-123")
    def test_redirects_validation(self, mock_file, mock_getsize, mock_exists):
        mock_exists.return_value = True
        mock_getsize.return_value = 14
        import deploy.wait_for_gateway as wait_script

        # Let's patch build_opener and capture the handler class used
        with patch("urllib.request.build_opener") as mock_build_opener:
            wait_script.check_gateway()
            handler_class = mock_build_opener.call_args[0][0]
            handler_instance = handler_class()

            # 1. Loopback redirect: http://localhost/newpath should be accepted
            req = MagicMock()
            req.get_method.return_value = "GET"
            new_req = handler_instance.redirect_request(req, None, 302, "Found", None, "http://127.0.0.1/newpath")
            self.assertIsNotNone(new_req)

            # 2. IPv6 loopback hostname accepted
            new_req = handler_instance.redirect_request(req, None, 302, "Found", None, "http://[::1]:18789/v1/models")
            self.assertIsNotNone(new_req)

            new_req = handler_instance.redirect_request(req, None, 302, "Found", None, "http://[::1]/newpath")
            self.assertIsNotNone(new_req)

            # 3. 0.0.0.0 rejected
            with self.assertRaises(urllib.error.URLError):
                handler_instance.redirect_request(req, None, 302, "Found", None, "http://0.0.0.0/newpath")

            # 4. [::] rejected
            with self.assertRaises(urllib.error.URLError):
                handler_instance.redirect_request(req, None, 302, "Found", None, "http://[::]/newpath")

            # 5. Non-loopback IPv6 rejected
            with self.assertRaises(urllib.error.URLError):
                handler_instance.redirect_request(req, None, 302, "Found", None, "http://[2001:db8::1]/newpath")

            # 6. Redirect to external host: http://malicious.com should raise URLError
            with self.assertRaises(urllib.error.URLError):
                handler_instance.redirect_request(req, None, 302, "Found", None, "http://malicious.com")
