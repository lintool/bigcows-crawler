"""DBLP challenge pages must not be accepted as author profiles."""

import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
DBLP = importlib.import_module("cache_dblp_profiles")


class DblpBlockTests(unittest.TestCase):
    def test_http_200_anubis_challenge_is_blocked(self):
        for quote in ('"', "'"):
            with self.subTest(quote=quote):
                body = (
                    "<title>Making sure you&#39;re not a bot!</title>"
                    f"<script id={quote}anubis_challenge{quote} "
                    'type="application/json">{}</script>'
                )
                response = MagicMock()
                response.status = 200
                response.headers.get_content_charset.return_value = "utf-8"
                response.read.return_value = body.encode()
                response.__enter__.return_value = response
                with patch.object(DBLP.urllib.request, "urlopen", return_value=response):
                    result = DBLP.fetch_profile_once("https://dblp.org/pid/example")
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["status_code"], 200)
                self.assertEqual(result["html"], body)

    def test_research_title_mentioning_anubis_is_not_a_block(self):
        self.assertFalse(DBLP.looks_blocked(
            '<title>dblp: Example Person</title><h1>Example Person</h1>'
            '<article>Anubis: Making sure you are not a bot</article>'
        ))

    def test_captcha_publication_title_is_not_a_block(self):
        self.assertFalse(DBLP.looks_blocked(
            '<html><title>dblp: Junfeng Yang</title><h1>Junfeng Yang</h1>'
            '<article>Understanding Visual-Spatial Cognition in Vision-Language Models for CAPTCHA.</article></html>'
        ))
        self.assertTrue(DBLP.looks_blocked('<html><title>CAPTCHA verification</title></html>'))
        self.assertTrue(DBLP.looks_blocked('<script src="https://www.google.com/recaptcha/api.js"></script>'))


if __name__ == "__main__":
    unittest.main()
