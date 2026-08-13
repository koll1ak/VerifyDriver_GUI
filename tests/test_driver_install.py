import os
import sys
import unittest
import queue
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import driver_install


def _mock_download_response(chunks=(b"cab-bytes",)):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.iter_content = Mock(return_value=list(chunks))
    return resp


def _drain(q):
    return [q.get_nowait() for _ in range(q.qsize())]


class RunPipelineTests(unittest.TestCase):
    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_success_posts_downloading_then_installing_then_done(self, mock_get, mock_run):
        mock_get.return_value = _mock_download_response()
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        q = queue.Queue()
        driver_install._run_pipeline("https://example.com/driver.cab", q)

        messages = _drain(q)
        self.assertEqual(
            [m[0] for m in messages],
            [driver_install.DOWNLOADING, driver_install.INSTALLING, driver_install.DONE],
        )

        # Verify subprocess.run calls were made with correct commands
        self.assertEqual(len(mock_run.call_args_list), 2)

        # First call: expand.exe to unpack the .cab file
        expand_call = mock_run.call_args_list[0]
        self.assertEqual(expand_call.args[0][0], "expand.exe")
        self.assertEqual(expand_call.args[0][1], "-F:*")
        self.assertIn("driver.cab", expand_call.args[0][2])  # cab path
        self.assertEqual(expand_call.kwargs["creationflags"], driver_install._NO_WINDOW)
        self.assertTrue(expand_call.kwargs.get("capture_output", False))
        self.assertTrue(expand_call.kwargs.get("text", False))

        # Second call: pnputil.exe to install drivers
        pnputil_call = mock_run.call_args_list[1]
        self.assertEqual(pnputil_call.args[0][0], "pnputil.exe")
        self.assertEqual(pnputil_call.args[0][1], "/add-driver")
        self.assertIn("*.inf", pnputil_call.args[0][2])  # driver pattern
        self.assertIn("/subdirs", pnputil_call.args[0])
        self.assertIn("/install", pnputil_call.args[0])
        self.assertEqual(pnputil_call.kwargs["creationflags"], driver_install._NO_WINDOW)
        self.assertTrue(pnputil_call.kwargs.get("capture_output", False))
        self.assertTrue(pnputil_call.kwargs.get("text", False))

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_reboot_required_exit_code_posts_done_reboot_required(self, mock_get, mock_run):
        mock_get.return_value = _mock_download_response()
        # first call is expand.exe (success), second is pnputil (reboot required)
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),
            Mock(returncode=3010, stdout="", stderr=""),
        ]

        q = queue.Queue()
        driver_install._run_pipeline("https://example.com/driver.cab", q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.DONE_REBOOT_REQUIRED)

        # Verify subprocess.run calls with correct commands
        self.assertEqual(len(mock_run.call_args_list), 2)
        expand_call = mock_run.call_args_list[0]
        self.assertEqual(expand_call.args[0][0], "expand.exe")
        self.assertEqual(expand_call.kwargs["creationflags"], driver_install._NO_WINDOW)
        pnputil_call = mock_run.call_args_list[1]
        self.assertEqual(pnputil_call.args[0][0], "pnputil.exe")
        self.assertEqual(pnputil_call.kwargs["creationflags"], driver_install._NO_WINDOW)

    @patch("driver_install.requests.get")
    def test_download_failure_posts_error_with_reason(self, mock_get):
        mock_get.side_effect = RuntimeError("connection reset")

        q = queue.Queue()
        driver_install._run_pipeline("https://example.com/driver.cab", q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.ERROR)
        self.assertIn("connection reset", messages[-1][1])

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_unpack_failure_posts_error(self, mock_get, mock_run):
        mock_get.return_value = _mock_download_response()
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="cabinet is corrupt")

        q = queue.Queue()
        driver_install._run_pipeline("https://example.com/driver.cab", q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.ERROR)
        self.assertIn("cabinet is corrupt", messages[-1][1])

        # Verify expand.exe was called with correct command
        expand_call = mock_run.call_args_list[0]
        self.assertEqual(expand_call.args[0][0], "expand.exe")
        self.assertEqual(expand_call.args[0][1], "-F:*")
        self.assertEqual(expand_call.kwargs["creationflags"], driver_install._NO_WINDOW)

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_install_failure_posts_error(self, mock_get, mock_run):
        mock_get.return_value = _mock_download_response()
        mock_run.side_effect = [
            Mock(returncode=0, stdout="", stderr=""),               # expand.exe succeeds
            Mock(returncode=5, stdout="", stderr="access denied"),  # pnputil fails
        ]

        q = queue.Queue()
        driver_install._run_pipeline("https://example.com/driver.cab", q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.ERROR)
        self.assertIn("access denied", messages[-1][1])

        # Verify both subprocess.run calls with correct commands
        self.assertEqual(len(mock_run.call_args_list), 2)
        expand_call = mock_run.call_args_list[0]
        self.assertEqual(expand_call.args[0][0], "expand.exe")
        self.assertEqual(expand_call.kwargs["creationflags"], driver_install._NO_WINDOW)
        pnputil_call = mock_run.call_args_list[1]
        self.assertEqual(pnputil_call.args[0][0], "pnputil.exe")
        self.assertIn("/add-driver", pnputil_call.args[0])
        self.assertIn("/subdirs", pnputil_call.args[0])
        self.assertIn("/install", pnputil_call.args[0])
        self.assertEqual(pnputil_call.kwargs["creationflags"], driver_install._NO_WINDOW)

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_temp_dir_cleaned_up_even_on_error(self, mock_get, mock_run):
        mock_get.side_effect = RuntimeError("boom")
        captured_dirs = []
        original_mkdtemp = driver_install.tempfile.mkdtemp

        def _tracking_mkdtemp(*args, **kwargs):
            d = original_mkdtemp(*args, **kwargs)
            captured_dirs.append(d)
            return d

        with patch("driver_install.tempfile.mkdtemp", side_effect=_tracking_mkdtemp):
            q = queue.Queue()
            driver_install._run_pipeline("https://example.com/driver.cab", q)

        self.assertEqual(len(captured_dirs), 1)
        self.assertFalse(os.path.exists(captured_dirs[0]))


class StartInstallTests(unittest.TestCase):
    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_runs_pipeline_on_a_background_thread(self, mock_get, mock_run):
        mock_get.return_value = _mock_download_response()
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        q = queue.Queue()
        thread = driver_install.start_install("https://example.com/driver.cab", q)
        thread.join(timeout=5)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.DONE)
        self.assertFalse(thread.is_alive())

        # Verify subprocess.run calls with correct commands even on background thread
        self.assertEqual(len(mock_run.call_args_list), 2)
        expand_call = mock_run.call_args_list[0]
        self.assertEqual(expand_call.args[0][0], "expand.exe")
        self.assertEqual(expand_call.kwargs["creationflags"], driver_install._NO_WINDOW)
        pnputil_call = mock_run.call_args_list[1]
        self.assertEqual(pnputil_call.args[0][0], "pnputil.exe")
        self.assertEqual(pnputil_call.kwargs["creationflags"], driver_install._NO_WINDOW)


if __name__ == "__main__":
    unittest.main()
