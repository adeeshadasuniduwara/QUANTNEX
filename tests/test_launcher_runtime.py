"""Regression tests for the source-based Web + Backend launcher."""
from __future__ import annotations

from pathlib import Path
import subprocess
import io
import tempfile
import unittest
from unittest.mock import patch

import run_quantnex_services as launcher


class LauncherRuntimeTests(unittest.TestCase):
    def test_backend_venv_python_matches_created_environment(self):
        expected = launcher.BACKEND / ".venv" / (
            Path("Scripts") / "python.exe" if launcher.os.name == "nt" else Path("bin") / "python"
        )
        self.assertEqual(launcher.VENV_DIR, launcher.BACKEND / ".venv")
        self.assertEqual(launcher.VENV_PYTHON, expected)

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

    def test_run_checked_replays_child_output_for_diagnostics(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        completed = subprocess.CompletedProcess([], 0, stdout="pip output", stderr="pip warning")
        with patch.object(launcher.subprocess, "run", return_value=completed):
            with patch("sys.stdout", stdout), patch("sys.stderr", stderr):
                launcher.run_checked(["python", "-m", "pip"], Path("."), "Install")
        self.assertIn("pip output", stdout.getvalue())
        self.assertIn("pip warning", stderr.getvalue())

    def test_prepare_backend_repairs_a_partial_venv(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            backend = root / "backend"
            backend.mkdir()
            (backend / "requirements.txt").write_text("fastapi", encoding="utf-8")
            venv = backend / ".venv"
            venv.mkdir()
            (venv / "partial-file").write_text("incomplete", encoding="utf-8")
            interpreter = venv / "Scripts" / "python.exe"

            def fake_run(command, cwd, label):
                if label == "Create backend virtual environment":
                    interpreter.parent.mkdir(parents=True, exist_ok=True)
                    interpreter.write_bytes(b"test-interpreter")

            with patch.object(launcher, "BACKEND", backend), \
                 patch.object(launcher, "VENV_DIR", venv), \
                 patch.object(launcher, "VENV_PYTHON", interpreter), \
                 patch.object(launcher, "run_checked", side_effect=fake_run) as run:
                self.assertEqual(launcher.prepare_backend(), interpreter)
            self.assertFalse((venv / "partial-file").exists())
            self.assertEqual(run.call_count, 3)

    def test_restart_uses_argument_list_for_workspace_paths_with_spaces(self):
        with tempfile.TemporaryDirectory(prefix="New folder ") as directory:
            root = Path(directory) / "QUANTNEX"
            root.mkdir()
            script = root / "run_quantnex_services.py"
            script.write_text("# test", encoding="utf-8")
            with patch.object(launcher, "ROOT", root), \
                 patch.object(launcher, "__file__", str(script)), \
                 patch.object(launcher.subprocess, "Popen") as popen:
                with self.assertRaises(SystemExit) as stopped:
                    launcher.restart_launcher()
        self.assertEqual(stopped.exception.code, 0)
        args, kwargs = popen.call_args
        self.assertEqual(args[0][0], launcher.sys.executable)
        self.assertEqual(args[0][1], str(script.resolve()))
        self.assertEqual(kwargs["cwd"], str(root))
        self.assertNotIn("shell", kwargs)
        self.assertEqual(kwargs["env"]["QUANTNEX_SUPPRESS_BROWSER_OPEN"], "1")

    def test_pre_update_launcher_passes_browser_suppression_to_new_source(self):
        from types import SimpleNamespace
        fake_updater = SimpleNamespace(check_and_apply=lambda _root: {
            "status": "updated", "message": "updated", "version": "main@abc1234",
            "changed_files": ["run_quantnex_services.py"], "restart_required": True,
        })
        with patch.dict(launcher.os.environ, {}, clear=False):
            launcher.os.environ.pop("QUANTNEX_SUPPRESS_BROWSER_OPEN", None)
            with patch.dict("sys.modules", {"quantnex_updater": fake_updater}):
                self.assertTrue(launcher.check_for_automatic_update())
            self.assertEqual(launcher.os.environ.get("QUANTNEX_SUPPRESS_BROWSER_OPEN"), "1")
            launcher.os.environ.pop("QUANTNEX_SUPPRESS_BROWSER_OPEN", None)

    def test_update_restart_flag_is_consumed_and_does_not_leak_to_normal_launch(self):
        with patch.dict(launcher.os.environ, {"QUANTNEX_SUPPRESS_BROWSER_OPEN": "1"}):
            suppress = launcher.consume_browser_open_suppression()
        self.assertTrue(suppress)
        self.assertNotIn("QUANTNEX_SUPPRESS_BROWSER_OPEN", launcher.os.environ)

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
