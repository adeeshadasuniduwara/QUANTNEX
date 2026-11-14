"""Regression tests for automatic rollback after a failed QUANTNEX startup."""
import tempfile
import unittest
from pathlib import Path

import quantnex_updater as updater


class UpdaterRollbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.previous_sha = "a" * 40
        self.installed_sha = "b" * 40
        self.existing = self.root / "apps" / "web" / "app.js"
        self.created = self.root / "backend" / "app" / "new_module.py"
        self.existing.parent.mkdir(parents=True)
        self.created.parent.mkdir(parents=True)
        self.existing.write_text("new version", encoding="utf-8")
        self.created.write_text("new file", encoding="utf-8")
        self.backup = self.root / "data" / "updates" / "backups" / "checkpoint"
        old_copy = self.backup / "apps" / "web" / "app.js"
        old_copy.parent.mkdir(parents=True)
        old_copy.write_text("previous version", encoding="utf-8")
        updater._save_state(self.root, self.installed_sha)
        updater._write_rollback_manifest(
            self.root,
            self.previous_sha,
            self.installed_sha,
            self.backup,
            [Path("apps/web/app.js"), Path("backend/app/new_module.py")],
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_failed_startup_restores_previous_files_and_revision(self):
        self.assertTrue(updater.rollback_last_update(self.root))
        self.assertEqual(self.existing.read_text(encoding="utf-8"), "previous version")
        self.assertFalse(self.created.exists())
        self.assertEqual(updater._load_state(self.root)["commit_sha"], self.previous_sha)
        self.assertFalse((self.root / updater.ROLLBACK_RELATIVE).exists())

    def test_rollback_refuses_to_revert_a_different_installed_revision(self):
        updater._save_state(self.root, "c" * 40)
        self.assertFalse(updater.rollback_last_update(self.root))
        self.assertEqual(self.existing.read_text(encoding="utf-8"), "new version")
        self.assertTrue(self.created.exists())

    def test_successful_startup_confirmation_removes_rollback_checkpoint(self):
        self.assertTrue(updater.confirm_update(self.root))
        self.assertFalse((self.root / updater.ROLLBACK_RELATIVE).exists())
        self.assertEqual(self.existing.read_text(encoding="utf-8"), "new version")


if __name__ == "__main__":
    unittest.main()
