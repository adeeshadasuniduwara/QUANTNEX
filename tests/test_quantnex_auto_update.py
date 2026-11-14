"""Static regression tests for automatic Web updates and Telegram receipts."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "apps" / "web" / "app.js").read_text(encoding="utf-8")
UPDATER = (ROOT / "apps" / "web" / "quantnex_local_server.py").read_text(encoding="utf-8")
LAUNCHER = (ROOT / "run_quantnex_services.py").read_text(encoding="utf-8")


class AutomaticUpdateTests(unittest.TestCase):
    def test_new_commit_is_installed_without_a_manual_click(self):
        self.assertIn("await installLatestCommit()", APP)
        self.assertIn("renderUpdateDetails(result,false)", APP)
        self.assertIn("300000", APP)

    def test_update_receipt_uses_existing_local_telegram_connection(self):
        self.assertIn('apiRequest("/api/v1/telegram/notify"', APP)
        self.assertIn("quantnex.webUpdateComplete", APP)
        self.assertIn("127.0.0.1", UPDATER)

    def test_supervisor_uses_one_full_source_updater(self):
        self.assertIn('web_env["QUANTNEX_SUPERVISED"] = "1"', LAUNCHER)
        self.assertIn("managed_by_supervisor", UPDATER)
        self.assertIn("supervisor_managed()", UPDATER)
        self.assertIn("managed_by_supervisor", APP)
        self.assertIn("Full source updates are handled by the QUANTNEX supervisor.", UPDATER)


    def test_supervisor_reports_the_actual_installed_and_latest_source_revisions(self):
        import importlib.util
        module_path = ROOT / "apps" / "web" / "quantnex_local_server.py"
        spec = importlib.util.spec_from_file_location("quantnex_update_status_test", module_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        installed = "a" * 40
        latest_sha = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "quantnex_update_state.json"
            state_file.write_text(json.dumps({"commit_sha": installed}), encoding="utf-8")
            with patch.object(updater, "SOURCE_STATE_FILE", state_file), \
                 patch.object(updater, "latest_commit", return_value={
                     "sha": latest_sha, "message": "Fix update status", "html_url": "https://github.com/example/repo/commit/" + latest_sha
                 }), \
                 patch.object(updater, "update_summary", return_value={
                     "changes": ["Fix update status"], "files_changed": 2, "commits_behind": 1
                 }):
                result = updater.supervisor_update_status()
        self.assertEqual(result["installed"], "main@" + installed[:7])
        self.assertEqual(result["latest"], "main@" + latest_sha[:7])
        self.assertTrue(result["managed_by_supervisor"])
        self.assertTrue(result["update_available"])

    def test_missing_source_marker_is_reported_as_initial_sync_not_unknown(self):
        import importlib.util
        module_path = ROOT / "apps" / "web" / "quantnex_local_server.py"
        spec = importlib.util.spec_from_file_location("quantnex_update_status_initial_test", module_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        latest_sha = "c" * 40
        with tempfile.TemporaryDirectory() as directory:
            state_file = Path(directory) / "missing.json"
            with patch.object(updater, "SOURCE_STATE_FILE", state_file), \
                 patch.object(updater, "latest_commit", return_value={
                     "sha": latest_sha, "message": "Initial source sync", "html_url": "https://github.com/example/repo"
                 }):
                result = updater.supervisor_update_status()
        self.assertEqual(result["installed"], "Initial source sync pending")
        self.assertEqual(result["latest"], "main@" + latest_sha[:7])
        self.assertTrue(result["update_available"])


    def test_web_updater_reads_full_source_marker_for_zip_installs(self):
        import importlib.util
        module_path = ROOT / "apps" / "web" / "quantnex_local_server.py"
        spec = importlib.util.spec_from_file_location("quantnex_installed_revision_test", module_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            web_marker = root / "web-version.json"
            source_marker = root / "source-version.json"
            source_sha = "d" * 40
            source_marker.write_text(json.dumps({"commit_sha": source_sha}), encoding="utf-8")
            with patch.object(updater, "VERSION_FILE", web_marker), \
                 patch.object(updater, "SOURCE_STATE_FILE", source_marker):
                self.assertEqual(updater.installed_revision(), source_sha)

    def test_manual_check_request_is_atomically_queued_for_supervisor(self):
        import importlib.util
        module_path = ROOT / "apps" / "web" / "quantnex_local_server.py"
        spec = importlib.util.spec_from_file_location("quantnex_update_queue_test", module_path)
        updater = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(updater)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "updates" / "check_requested.json"
            with patch.object(updater, "SUPERVISOR_CHECK_FILE", marker):
                updater.queue_supervisor_check()
            self.assertTrue(marker.is_file())
            self.assertIn("requested_at", json.loads(marker.read_text(encoding="utf-8")))

    def test_supervisor_ui_uses_real_versions_and_manual_check_endpoint(self):
        self.assertIn('fetch("/__quantnex/check-now"', APP)
        self.assertIn("watchSupervisorUpdate(latestUpdateCommit)", APP)
        self.assertIn("quantnex.webUpdateComplete", APP)
        self.assertIn('result.installed||"Source revision unavailable"', APP)
        self.assertIn("supervisor_update_status()", UPDATER)
        self.assertIn("SUPERVISOR_CHECK_FILE", UPDATER)
        self.assertIn("consume_manual_update_request()", LAUNCHER)

    def test_updater_still_pins_and_validates_the_github_archive(self):
        self.assertIn("codeload.github.com/{REPO}/zip/{sha}", UPDATER)
        self.assertIn("validate", UPDATER.lower())
        self.assertIn("backup", UPDATER.lower())


if __name__ == "__main__":
    unittest.main()
