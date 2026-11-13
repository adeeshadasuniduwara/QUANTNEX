"""Static regression tests for automatic Web updates and Telegram receipts."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "apps" / "web" / "app.js").read_text(encoding="utf-8")
UPDATER = (ROOT / "apps" / "web" / "quantnex_local_server.py").read_text(encoding="utf-8")


class AutomaticUpdateTests(unittest.TestCase):
    def test_new_commit_is_installed_without_a_manual_click(self):
        self.assertIn("await installLatestCommit()", APP)
        self.assertIn("renderUpdateDetails(result,false)", APP)
        self.assertIn("300000", APP)

    def test_update_receipt_uses_existing_local_telegram_connection(self):
        self.assertIn('apiRequest("/api/v1/telegram/notify"', APP)
        self.assertIn("quantnex.webUpdateComplete", APP)
        self.assertIn("127.0.0.1", UPDATER)

    def test_updater_still_pins_and_validates_the_github_archive(self):
        self.assertIn("codeload.github.com/{REPO}/zip/{sha}", UPDATER)
        self.assertIn("validate", UPDATER.lower())
        self.assertIn("backup", UPDATER.lower())


if __name__ == "__main__":
    unittest.main()
