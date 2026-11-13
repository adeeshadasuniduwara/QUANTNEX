import unittest
from pathlib import Path


class TelegramReleaseWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "telegram-release-notify.yml"
        ).read_text(encoding="utf-8")

    def test_push_announcement_uses_real_newlines(self):
        intro = self.workflow.split("intro = (", 1)[1].split(")", 1)[0]
        self.assertNotIn(r"\\n", intro)

    def test_http_errors_report_telegram_description_without_exposing_secrets(self):
        self.assertIn("urllib.error.HTTPError", self.workflow)
        self.assertIn('result.get("description")', self.workflow)
        self.assertIn("TELEGRAM_CHAT_ID", self.workflow)
        self.assertNotIn("TELEGRAM_BOT_TOKEN:", self.workflow)


if __name__ == "__main__":
    unittest.main()
