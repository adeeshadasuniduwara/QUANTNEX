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
        self.assertIn('json.loads(raw).get("description")', self.workflow)
        self.assertIn("TELEGRAM_CHAT_ID", self.workflow)
        handler = self.workflow.split("except urllib.error.HTTPError", 1)[1].split("except urllib.error.URLError", 1)[0]
        self.assertNotIn("TELEGRAM_BOT_TOKEN", handler)

    def test_destination_is_preflighted_without_logging_bot_credentials(self):
        self.assertIn('telegram_api("getMe")', self.workflow)
        self.assertIn('telegram_api("getChat"', self.workflow)
        self.assertIn("TELEGRAM_CHAT_ID points to the bot's own ID", self.workflow)
        self.assertIn("after sending /start to the bot", self.workflow)
        self.assertNotIn('print(token)', self.workflow)

    def test_group_and_channel_destinations_require_verified_bot_permissions(self):
        self.assertIn('telegram_api("getChatMember"', self.workflow)
        self.assertIn('"user_id": int(bot_id)', self.workflow)
        self.assertIn('member.get("can_post_messages") is True', self.workflow)
        self.assertIn('member.get("can_send_messages") is True', self.workflow)
        self.assertIn("The bot must be a channel administrator with Post Messages permission.", self.workflow)
        self.assertIn("The bot is not allowed to send messages in this group.", self.workflow)

    def test_source_update_link_is_not_mislabeled_as_a_release(self):
        self.assertIn('link_label = "View source update"', self.workflow)
        self.assertIn('link_label = "Open release &amp; downloads"', self.workflow)


if __name__ == "__main__":
    unittest.main()
