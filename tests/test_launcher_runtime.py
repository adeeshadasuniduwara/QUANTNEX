"""Regression tests for the source-based Web + Backend launcher."""
from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import run_quantnex_services as launcher


class LauncherRuntimeTests(unittest.TestCase):
    def test_run_checked_reports_a_failed_dependency_install(self):
        with patch.object(launcher.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, "exit code 1"):
                launcher.run_checked(["python", "-m", "pip", "install", "-r", "requirements.txt"],
                                     Path("."), "Install dependencies")

    def test_prepare_backend_uses_retrying_pip_install_and_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            python = Path(directory) / "python"
            python.write_text("", encoding="utf-8")
            with patch.object(launcher, "VENV_PYTHON", python), patch.object(launcher, "run_checked") as run:
                self.assertEqual(launcher.prepare_backend(), python)
            calls = [call.args[0] for call in run.call_args_list]
            self.assertEqual(len(calls), 2)
            self.assertIn("--retries", calls[0])
            self.assertIn("--timeout", calls[0])
            self.assertEqual(calls[1][-1], "bootstrap.py")

    def test_launcher_is_web_backend_only(self):
        source = Path(launcher.__file__).read_text(encoding="utf-8")
        batch = (Path(launcher.__file__).resolve().parent / "run_quantnex.bat").read_text(encoding="utf-8")
        self.assertNotIn("--desktop", source)
        self.assertNotIn("apps/windows", source)
        self.assertNotIn("QUANTNEX.exe", batch)
        self.assertIn("pause", batch.lower())
        self.assertIn("APP_EXIT", batch)
        self.assertIn("!ERRORLEVEL!", batch)
        self.assertNotIn("%ERRORLEVEL%", batch)

    def test_log_tee_writes_to_each_destination(self):
        class Sink:
            def __init__(self):
                self.value = ""
            def write(self, value):
                self.value += value
                return len(value)
            def flush(self):
                pass

        first, second = Sink(), Sink()
        tee = launcher.Tee(first, second)
        self.assertEqual(tee.write("diagnostic"), 10)
        self.assertEqual(first.value, "diagnostic")
        self.assertEqual(second.value, "diagnostic")


if __name__ == "__main__":
    unittest.main()
