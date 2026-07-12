# tests/unit/test_submit_test_task_openclaw.py
import sys
import os
import subprocess
import unittest
from unittest.mock import patch, MagicMock

class TestSubmitTestTaskOpenClaw(unittest.TestCase):

    def setUp(self):
        self.original_env = os.environ.get("CVN_BROKER_ENV")
        os.environ["CVN_BROKER_ENV"] = "staging"

    def tearDown(self):
        if self.original_env is None:
            os.environ.pop("CVN_BROKER_ENV", None)
        else:
            os.environ["CVN_BROKER_ENV"] = self.original_env

    def test_environment_validation(self):
        # We run the script in a separate process to test the top-level env guard
        test_cases = [
            (None, False),          # Missing
            ("", False),            # Empty
            ("production", False),  # Rejected
            ("prod", False),        # Rejected
            ("development", False), # Rejected
            ("Staging", False),     # Case-sensitive check: Staging (capital S) should be rejected
            ("staging", True)       # Accepted
        ]

        for env_val, should_accept in test_cases:
            env = os.environ.copy()
            if env_val is None:
                env.pop("CVN_BROKER_ENV", None)
            else:
                env["CVN_BROKER_ENV"] = env_val

            cmd = [sys.executable, "scripts/submit_test_task_openclaw.py", "--help"]
            res = subprocess.run(cmd, capture_output=True, text=True, env=env)

            if should_accept:
                # If accepted, --help should output usage help and exit with status 0
                self.assertEqual(res.returncode, 0, f"Failed for env '{env_val}': {res.stderr}")
                self.assertIn("usage: submit_test_task_openclaw.py", res.stdout)
            else:
                # If rejected, it should fail closed and exit with status 1
                self.assertEqual(res.returncode, 1, f"Failed for env '{env_val}'")
                self.assertIn("Refusing to submit test tasks", res.stdout)

    @patch("scripts.submit_test_task_openclaw.get_secret")
    @patch("scripts.submit_test_task_openclaw.build_payload")
    @patch("scripts.submit_test_task_openclaw.sign")
    @patch("scripts.submit_test_task_openclaw.requests.post")
    def test_url_project_ref_validation(self, mock_post, mock_sign, mock_build, mock_get_secret):
        # Import the script inside the test (safe since CVN_BROKER_ENV=staging is set in setUp)
        import scripts.submit_test_task_openclaw as submit_script

        mock_get_secret.side_effect = lambda key: "fake-value"
        mock_build.return_value = ({"task_id": "test-task-123"}, "{}", "hash")
        mock_sign.return_value = "fake-signature"

        # Mock requests.post to return a successful response
        mock_res = MagicMock()
        mock_res.status_code = 200
        mock_res.json.return_value = {"success": True}
        mock_post.return_value = mock_res

        # Test 1: Default PROJECT_REF "ukqkkgzimhtjhlnmlyao" should be accepted and invoke post
        with patch.object(sys, "argv", ["scripts/submit_test_task_openclaw.py", "--target", "openclaw"]):
            submit_script.main()
            self.assertTrue(mock_post.called)

        mock_post.reset_mock()

        # Test 2: Modify PROJECT_REF to something else (e.g. production ref)
        # It must fail closed and exit with system exit
        with patch("scripts.submit_test_task_openclaw.PROJECT_REF", "maliciousref"):
            with patch.object(sys, "argv", ["scripts/submit_test_task_openclaw.py", "--target", "openclaw"]):
                with self.assertRaises(SystemExit) as cm:
                    submit_script.main()
                self.assertEqual(cm.exception.code, 1)
                self.assertFalse(mock_post.called)
