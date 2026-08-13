import os
import sys
import unittest
import queue
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import driver_install

# a real allowed host (matches driver_install._TRUSTED_URL_HOST_SUFFIXES)
# -- used in place of the old "https://example.com/driver.cab" placeholder
# now that _download enforces a trust check before/after the request
TRUSTED_URL = "https://catalog.s.download.windowsupdate.com/c/msdownload/update/driver/drvs/x/y.cab"


def _mock_download_response(chunks=(b"cab-bytes",), url=TRUSTED_URL):
    resp = Mock()
    resp.raise_for_status = Mock()
    resp.iter_content = Mock(return_value=list(chunks))
    # requests sets .url to the final URL after following any redirects
    # -- _download re-checks this against the trust list, so it must be
    # a real string, not an unconfigured Mock attribute
    resp.url = url
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
        driver_install._run_pipeline(TRUSTED_URL, q)

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
        driver_install._run_pipeline(TRUSTED_URL, q)

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
        driver_install._run_pipeline(TRUSTED_URL, q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.ERROR)
        self.assertIn("connection reset", messages[-1][1])

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_unpack_failure_posts_error(self, mock_get, mock_run):
        mock_get.return_value = _mock_download_response()
        mock_run.return_value = Mock(returncode=1, stdout="", stderr="cabinet is corrupt")

        q = queue.Queue()
        driver_install._run_pipeline(TRUSTED_URL, q)

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
        driver_install._run_pipeline(TRUSTED_URL, q)

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
            driver_install._run_pipeline(TRUSTED_URL, q)

        self.assertEqual(len(captured_dirs), 1)
        self.assertFalse(os.path.exists(captured_dirs[0]))


class TrustedUrlTests(unittest.TestCase):
    """
    _is_cab_installable in gui/app.py is only a UI dispatch hint (it
    just checks the URL ends in ".cab") -- these tests cover the actual
    security gate in driver_install._download, which runs right before
    an elevated pnputil gets involved.
    """

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_http_url_rejected_before_requests_get(self, mock_get, mock_run):
        q = queue.Queue()
        driver_install._run_pipeline("http://catalog.s.download.windowsupdate.com/driver.cab", q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.ERROR)
        self.assertIn("untrusted URL", messages[-1][1])
        mock_get.assert_not_called()
        mock_run.assert_not_called()

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_https_disallowed_host_rejected_before_requests_get(self, mock_get, mock_run):
        q = queue.Queue()
        driver_install._run_pipeline("https://evil.example.com/driver.cab", q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.ERROR)
        self.assertIn("untrusted URL", messages[-1][1])
        mock_get.assert_not_called()
        mock_run.assert_not_called()

    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_redirect_to_untrusted_host_rejected_after_requests_get(self, mock_get, mock_run):
        # the initial URL passes the trust check, but the response's
        # final (post-redirect) URL points somewhere untrusted
        mock_get.return_value = _mock_download_response(url="https://evil.example.com/driver.cab")

        q = queue.Queue()
        driver_install._run_pipeline(TRUSTED_URL, q)

        messages = _drain(q)
        self.assertEqual(messages[-1][0], driver_install.ERROR)
        self.assertIn("untrusted URL", messages[-1][1])
        mock_get.assert_called_once()
        mock_run.assert_not_called()

    def test_is_trusted_url_accepts_windowsupdate_and_microsoft_hosts(self):
        self.assertTrue(driver_install._is_trusted_url(
            "https://catalog.s.download.windowsupdate.com/c/msdownload/update/driver/drvs/x/y.cab"
        ))
        self.assertTrue(driver_install._is_trusted_url("https://download.microsoft.com/driver.cab"))

    def test_is_trusted_url_rejects_http_scheme(self):
        self.assertFalse(driver_install._is_trusted_url("http://download.microsoft.com/driver.cab"))

    def test_is_trusted_url_rejects_lookalike_host(self):
        # "windowsupdate.com.evil.example.com" doesn't end with the
        # trusted suffix "*.windowsupdate.com" -- a naive substring
        # check would be fooled by this, an endswith on hostname isn't
        self.assertFalse(driver_install._is_trusted_url("https://windowsupdate.com.evil.example.com/driver.cab"))


class StartInstallTests(unittest.TestCase):
    @patch("driver_install.subprocess.run")
    @patch("driver_install.requests.get")
    def test_runs_pipeline_on_a_background_thread(self, mock_get, mock_run):
        mock_get.return_value = _mock_download_response()
        mock_run.return_value = Mock(returncode=0, stdout="", stderr="")

        q = queue.Queue()
        thread = driver_install.start_install(TRUSTED_URL, q)
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
