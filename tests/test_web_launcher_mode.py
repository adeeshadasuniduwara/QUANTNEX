"""Regression tests for the QUANTNEX Web server launch mode."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "apps" / "web" / "quantnex_local_server.py"
SPEC = importlib.util.spec_from_file_location("quantnex_local_server_tested", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)


class SupervisorLaunchTests(unittest.TestCase):
    @patch.dict(server.os.environ, {"QUANTNEX_SUPERVISED": "1"}, clear=True)
    @patch.object(server.os, "execv")
    def test_supervised_child_starts_web_server_without_recursion(self, execv):
        server.ensure_supervisor_mode()
        execv.assert_not_called()

    @patch.dict(server.os.environ, {}, clear=True)
    @patch.object(server.os, "execv")
    def test_standalone_server_hands_off_to_full_supervisor(self, execv):
        server.ensure_supervisor_mode()
        launcher = server.ROOT / "run_quantnex_services.py"
        execv.assert_called_once_with(server.sys.executable, [server.sys.executable, str(launcher)])


if __name__ == "__main__":
    unittest.main()
