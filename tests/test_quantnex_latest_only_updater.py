from __future__ import annotations

import io
import unittest
from unittest.mock import patch

import quantnex_updater


class LatestCommitFeedTests(unittest.TestCase):
    def test_reads_latest_commit_sha_from_atom_entry(self) -> None:
        sha = "a" * 40
        atom = f"""<?xml version="1.0" encoding="utf-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <id>https://github.com/adeeshadasuniduwara/QUANTNEX/commits/main.atom</id>
          <entry>
            <id>tag:github.com,2008:Grit::Commit/{sha}</id>
            <title>latest update</title>
          </entry>
        </feed>""".encode()

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with patch.object(quantnex_updater.urllib.request, "urlopen", return_value=Response(atom)):
            self.assertEqual(quantnex_updater._request_latest_commit_sha(), sha)

    def test_rejects_feed_without_a_commit_sha(self) -> None:
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><id>main</id></feed>'

        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        with patch.object(quantnex_updater.urllib.request, "urlopen", return_value=Response(atom)):
            with self.assertRaises(quantnex_updater.UpdateError):
                quantnex_updater._request_latest_commit_sha()




class UpdateIntervalTests(unittest.TestCase):
    def test_supervisor_checks_every_five_minutes_with_jitter(self) -> None:
        import run_quantnex_services
        self.assertEqual(run_quantnex_services.UPDATE_INTERVAL_SECONDS, 5 * 60)
        self.assertEqual(run_quantnex_services.UPDATE_JITTER_SECONDS, 120)
        self.assertTrue(callable(run_quantnex_services._scheduled_update_due))
        self.assertTrue(callable(run_quantnex_services._mark_scheduled_update_check))

    def test_updater_has_retry_after_rate_limit_backoff(self) -> None:
        source = open("quantnex_updater.py", encoding="utf-8").read()
        self.assertIn("Retry-After", source)
        self.assertIn("time.sleep(delay)", source)

if __name__ == "__main__":
    unittest.main()
