"""Contract checks for the Android-only production release workflow."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class AndroidReleaseWorkflowTests(unittest.TestCase):
    def test_release_builds_and_publishes_only_a_signed_android_apk(self):
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("assembleRelease", workflow)
        self.assertIn("QUANTNEX-Android.apk", workflow)
        self.assertIn("SHA256SUMS.txt", workflow)
        self.assertIn("sha256sum --check", workflow)
        self.assertIn("ANDROID_KEYSTORE_BASE64", workflow)
        self.assertIn("ANDROID_KEYSTORE_PASSWORD", workflow)
        self.assertNotIn("QUANTNEX.exe", workflow)
        self.assertNotIn("pyinstaller", workflow.lower())
        self.assertNotIn("apps/windows", workflow)
        self.assertNotIn("windows-latest", workflow)

    def test_windows_desktop_build_workflow_is_retired(self):
        self.assertFalse((ROOT / ".github" / "workflows" / "windows-build.yml").exists())
        self.assertFalse((ROOT / "apps" / "windows").exists())


if __name__ == "__main__":
    unittest.main()
