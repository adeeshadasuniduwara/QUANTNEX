"""Regression checks for Windows Python runtime discovery."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class WindowsPythonBootstrapTests(unittest.TestCase):
    def test_shared_resolver_validates_real_python_and_ignores_store_alias_failure(self):
        source = (ROOT / "scripts" / "ensure_python.cmd").read_text(encoding="utf-8")
        self.assertIn("py -3 -c", source)
        self.assertIn("python -c", source)
        self.assertIn("sys.version_info >= (3,11)", source)
        self.assertIn("winget install --id Python.Python.3.12", source)
        self.assertIn("python.org/downloads/windows/", source)

    def test_both_windows_launchers_use_shared_python_resolver(self):
        main = (ROOT / "run_quantnex.bat").read_text(encoding="utf-8")
        backend = (ROOT / "run_backend.bat").read_text(encoding="utf-8")
        self.assertIn("scripts\\ensure_python.cmd", main)
        self.assertIn("%QUANTNEX_PYTHON% -u run_quantnex_services.py", main)
        self.assertIn("scripts\\ensure_python.cmd", backend)
        self.assertIn("%QUANTNEX_PYTHON% -m venv", backend)


if __name__ == "__main__":
    unittest.main()
